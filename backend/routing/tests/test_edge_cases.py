"""Edge cases: provider failures, odd responses, boundary input and degenerate trips."""

from datetime import UTC, datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone as dj_tz
from rest_framework.test import APIClient

from routing.services import planner, tomtom, weather
from routing.tests.test_api import CHICAGO, DENVER, fake_route, fake_weather


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def tomtom_route_payload(with_guidance=True):
    route = {
        "summary": {"lengthInMeters": 16093, "travelTimeInSeconds": 900, "trafficDelayInSeconds": 30},
        "legs": [
            {"points": [{"latitude": 40.0, "longitude": -100.0}, {"latitude": 40.0, "longitude": -99.81}]}
        ],
    }
    if with_guidance:
        route["guidance"] = {
            "instructions": [
                {"routeOffsetInMeters": 0, "travelTimeInSeconds": 0, "roadNumbers": ["I-80"]},
                {"routeOffsetInMeters": 8000, "travelTimeInSeconds": 300, "roadNumbers": ["US-6"]},
                # Offsets past the route end must not distort the profile.
                {"routeOffsetInMeters": 99999, "travelTimeInSeconds": 5000},
            ]
        }
    return {"routes": [route]}


@override_settings(TOMTOM_API_KEY="test")
class TomTomClientTests(SimpleTestCase):
    def call(self, response, depart=None):
        session = mock.Mock()
        session.get.return_value = response
        with mock.patch("routing.services.tomtom.session", return_value=session):
            routes = tomtom.calculate_routes(
                [(40.0, -100.0), (40.0, -99.8)], depart or datetime.now(UTC) + timedelta(hours=1), 30000
            )
        return routes, session.get.call_args

    def test_departure_in_the_past_is_sent_as_now(self):
        past = datetime.now(UTC) - timedelta(minutes=5)
        _, call = self.call(FakeResponse(200, tomtom_route_payload()), depart=past)
        sent = datetime.fromisoformat(call.kwargs["params"]["departAt"])
        self.assertGreater(sent, datetime.now(UTC))

    def test_profile_uses_instruction_timing_and_ignores_overflow(self):
        routes, _ = self.call(FakeResponse(200, tomtom_route_payload()))
        profile = routes[0].time_profile
        self.assertIn((8000 / 1609.344, 300.0), profile)
        self.assertEqual(profile[-1], (routes[0].length_mi, 900.0))
        self.assertTrue(all(sec <= 900 for _, sec in profile))
        self.assertEqual(routes[0].road_order, ["I-80", "US-6"])
        # Mileage per road stops at the end of the route.
        self.assertAlmostEqual(routes[0].road_miles["US-6"], (16093 - 8000) / 1609.344, places=3)

    def test_missing_guidance_falls_back_to_start_and_end(self):
        routes, _ = self.call(FakeResponse(200, tomtom_route_payload(with_guidance=False)))
        self.assertEqual(len(routes[0].time_profile), 2)

    def test_unreachable_point_has_specific_message(self):
        body = {"detailedError": {"code": "MAP_MATCHING_FAILURE", "message": "Origin not matched"}}
        with self.assertRaisesMessage(tomtom.NoRouteFound, "too far from a road"):
            self.call(FakeResponse(400, body))

    def test_no_route_found(self):
        body = {"error": {"description": "Engine error while executing route request: NO_ROUTE_FOUND"}}
        with self.assertRaisesMessage(tomtom.NoRouteFound, "No truck route"):
            self.call(FakeResponse(400, body))

    def test_other_bad_request_is_not_reported_as_no_route(self):
        body = {"detailedError": {"code": "BAD_INPUT", "message": "Invalid vehicleWeight"}}
        with self.assertRaises(tomtom.TomTomError) as ctx:
            self.call(FakeResponse(400, body))
        self.assertNotIsInstance(ctx.exception, tomtom.NoRouteFound)

    def test_rejected_key(self):
        with self.assertRaisesMessage(tomtom.TomTomError, "API key"):
            self.call(FakeResponse(403, {}))

    @override_settings(TOMTOM_API_KEY="")
    def test_missing_key(self):
        with self.assertRaisesMessage(tomtom.TomTomError, "missing its TomTom API key"):
            tomtom.calculate_routes([(40.0, -100.0), (40.0, -99.8)], datetime.now(UTC), 1)


class WeatherClientTests(SimpleTestCase):
    start = datetime(2026, 11, 5, 12, tzinfo=UTC)

    def payload(self, wind=10.0):
        return {
            "hourly": {
                "time": ["2026-11-05T12:00", "2026-11-05T13:00"],
                "wind_speed_10m": [wind, None],
                "wind_gusts_10m": [15.0, None],
                "rain": [0.0, None],
                "showers": [0.0, None],
                "snowfall": [0.0, None],
            }
        }

    def fetch(self, response, n=1):
        session = mock.Mock()
        session.get.return_value = response
        with (
            mock.patch("routing.services.weather.session", return_value=session),
            mock.patch("routing.services.weather.cache") as cache,
        ):
            cache.get.return_value = None
            series = weather.fetch_hourly([(40.0 + i, -100.0) for i in range(n)], self.start, self.start)
        return series, session.get.call_args

    def test_single_location_object_response(self):
        series, _ = self.fetch(FakeResponse(200, self.payload()))
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].at(self.start).wind_mph, 10.0)

    def test_missing_hours_give_no_sample(self):
        series, _ = self.fetch(FakeResponse(200, self.payload()))
        self.assertIsNone(series[0].at(self.start + timedelta(minutes=30)))

    def test_rate_limit_has_actionable_message(self):
        with self.assertRaisesMessage(weather.WeatherError, "limit has been reached"):
            self.fetch(FakeResponse(429, {"reason": "Minutely API request limit exceeded"}))

    def test_incomplete_response_is_rejected(self):
        with self.assertRaisesMessage(weather.WeatherError, "incomplete"):
            self.fetch(FakeResponse(200, [self.payload()]), n=2)

    @override_settings(OPEN_METEO_API_KEY="abc")
    def test_commercial_key_uses_customer_endpoint(self):
        _, call = self.fetch(FakeResponse(200, self.payload()))
        self.assertEqual(call.args[0], weather.CUSTOMER_URL)
        self.assertEqual(call.kwargs["params"]["apikey"], "abc")


def gappy_weather(locations, start, end):
    """Forecast that has no data for any point west of -95 degrees."""
    series = fake_weather(locations, start, end)
    for s, (_, lon) in zip(series, locations, strict=True):
        if lon < -95:
            s.wind_mph = [None] * len(s.wind_mph)
    return series


@override_settings(TOMTOM_API_KEY="test")
class PlannerEdgeTests(SimpleTestCase):
    departure = datetime.now(UTC) + timedelta(hours=1)

    def plan(self, calc, wx=fake_weather, dest=DENVER):
        with (
            mock.patch("routing.services.tomtom.calculate_routes", side_effect=calc),
            mock.patch("routing.services.weather.fetch_hourly", side_effect=wx),
        ):
            return planner.plan_trip(planner.TripRequest(CHICAGO, dest, self.departure, 20000))

    def test_single_route_when_detours_fail(self):
        def calc(locations, *args, **kwargs):
            if len(locations) == 3:
                raise tomtom.NoRouteFound("no")
            return [fake_route([CHICAGO, DENVER])]

        result = self.plan(calc)
        self.assertEqual(len(result["routes"]), 1)
        self.assertEqual(result["notices"], [])
        self.assertIn("only distinct route", result["recommendations"]["25"]["reason"])

    def test_two_routes_get_a_notice(self):
        def calc(locations, *args, **kwargs):
            if len(locations) == 3:
                return []
            return [fake_route([CHICAGO, DENVER]), fake_route([CHICAGO, (43.5, -96.0), DENVER])]

        result = self.plan(calc)
        self.assertEqual(len(result["routes"]), 2)
        self.assertEqual(
            result["notices"], ["Only 2 distinct routes exist for this trip without long detours."]
        )

    def test_duplicate_alternatives_are_removed(self):
        def calc(locations, *args, **kwargs):
            if len(locations) == 3:
                return []
            same = fake_route([CHICAGO, (41.3, -96.0), DENVER])
            return [same, fake_route([CHICAGO, (41.3, -96.0), DENVER], mph=50)]

        result = self.plan(calc)
        self.assertEqual(len(result["routes"]), 1)

    def test_detours_much_slower_than_fastest_are_rejected(self):
        def calc(locations, *args, **kwargs):
            if len(locations) == 3:
                return [fake_route(locations, mph=20)]
            return [fake_route([CHICAGO, DENVER])]

        result = self.plan(calc)
        self.assertEqual(len(result["routes"]), 1)

    def test_missing_forecast_is_reported_as_unknown_not_low(self):
        result = self.plan(
            lambda locations, *a, **k: [fake_route([CHICAGO, DENVER])] if len(locations) == 2 else [],
            wx=gappy_weather,
        )
        analysis = result["routes"][0]["analyses"]["25"]
        self.assertGreater(analysis["miles_by_level"]["unknown"], 0)
        self.assertTrue(any(cp["level"] is None for cp in analysis["checkpoints"]))
        self.assertTrue(any(seg[2] is None for seg in analysis["segments"]))

    def test_trip_shorter_than_every_interval(self):
        near = (CHICAGO[0], CHICAGO[1] - 0.12)  # about 6 miles

        def calc(locations, *args, **kwargs):
            return [fake_route([CHICAGO, near])] if len(locations) == 2 else []

        result = self.plan(calc, dest=near)
        for interval in ("10", "25", "50"):
            cps = result["routes"][0]["analyses"][interval]["checkpoints"]
            self.assertEqual([round(c["mile"]) for c in cps], [0, round(result["routes"][0]["distance_mi"])])

    @override_settings(WEATHER_LOOKUP_BUDGET=50)
    def test_long_trip_over_weather_budget_drops_10_mile_spacing(self):
        result = self.plan(
            lambda locations, *a, **k: [fake_route([CHICAGO, DENVER])] if len(locations) == 2 else []
        )
        self.assertEqual(result["intervals"], ["25", "50"])
        self.assertEqual(set(result["recommendations"]), {"25", "50"})
        self.assertEqual(set(result["routes"][0]["analyses"]), {"25", "50"})
        self.assertTrue(any("10-mile" in n for n in result["notices"]))

    @override_settings(WEATHER_LOOKUP_BUDGET=0)
    def test_zero_budget_means_unlimited(self):
        result = self.plan(
            lambda locations, *a, **k: [fake_route([CHICAGO, DENVER])] if len(locations) == 2 else []
        )
        self.assertEqual(result["intervals"], ["10", "25", "50"])

    def test_positions_cover_the_whole_trip(self):
        result = self.plan(
            lambda locations, *a, **k: [fake_route([CHICAGO, DENVER])] if len(locations) == 2 else []
        )
        route = result["routes"][0]
        self.assertEqual(route["positions"][0][0], 0)
        self.assertAlmostEqual(route["positions"][-1][0] * 3600, route["duration_s"], delta=2)
        self.assertAlmostEqual(route["positions"][-1][3], route["distance_mi"], delta=0.2)


class ValidationEdgeTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    def body(self, **overrides):
        data = {
            "origin": {"lat": CHICAGO[0], "lon": CHICAGO[1]},
            "destination": {"lat": DENVER[0], "lon": DENVER[1]},
            "departure": (dj_tz.now() + timedelta(hours=1)).isoformat(),
            "load_lb": 20000,
        }
        data.update(overrides)
        return data

    def post(self, path, data):
        return self.client.post(path, data, format="json")

    def test_load_limits(self):
        self.assertEqual(self.post("/api/plan", self.body(load_lb=-1)).status_code, 400)
        resp = self.post("/api/plan", self.body(load_lb=80001))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("80,000", resp.json()["load_lb"][0])

    def test_departure_too_far_ahead(self):
        far = (dj_tz.now() + timedelta(days=8)).isoformat()
        resp = self.post("/api/plan", self.body(departure=far))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("7 days", resp.json()["departure"][0])

    def test_out_of_range_coordinates(self):
        resp = self.post("/api/plan", self.body(origin={"lat": 95, "lon": 0}))
        self.assertEqual(resp.status_code, 400)

    def test_malformed_json(self):
        resp = self.client.post("/api/plan", "{not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_missing_fields(self):
        resp = self.post("/api/plan", {})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(set(resp.json()), {"origin", "destination", "departure", "load_lb"})

    @mock.patch("routing.services.weather.fetch_hourly", side_effect=fake_weather)
    def test_heatmap_accepts_departure_from_earlier_today(self, _wx):
        body = {
            "paths": [[[CHICAGO[1], CHICAGO[0]], [DENVER[1], DENVER[0]]]],
            "departure": (dj_tz.now() - timedelta(hours=2)).isoformat(),
            "load_lb": 0,
        }
        self.assertEqual(self.post("/api/heatmap", body).status_code, 200)

    def test_heatmap_rejects_bad_coordinates(self):
        body = {"paths": [[[0, 0], [200, 0]]], "departure": dj_tz.now().isoformat(), "load_lb": 0}
        self.assertEqual(self.post("/api/heatmap", body).status_code, 400)

    def test_heatmap_rejects_too_many_paths(self):
        path = [[CHICAGO[1], CHICAGO[0]], [DENVER[1], DENVER[0]]]
        body = {"paths": [path] * 4, "departure": dj_tz.now().isoformat(), "load_lb": 0}
        self.assertEqual(self.post("/api/heatmap", body).status_code, 400)

    def test_short_place_query_returns_nothing_without_calling_tomtom(self):
        with mock.patch("routing.services.tomtom.search_places") as search:
            resp = self.client.get("/api/places?q=a")
        self.assertEqual(resp.json(), {"results": []})
        search.assert_not_called()

    def test_health_reports_version_and_request_id(self):
        resp = self.client.get("/api/health", HTTP_X_REQUEST_ID="abc123")
        self.assertEqual(resp.json()["status"], "ok")
        self.assertEqual(resp["X-Request-ID"], "abc123")

    def test_unknown_route_is_404(self):
        self.assertEqual(self.client.get("/api/nope").status_code, 404)


@override_settings(TOMTOM_API_KEY="test")
class PlaceSearchTests(SimpleTestCase):
    def search(self, response, query="Denver"):
        session = mock.Mock()
        session.get.return_value = response
        with mock.patch("routing.services.tomtom.session", return_value=session):
            return tomtom.search_places(query), session.get.call_args

    def test_parses_addresses_and_pois_and_drops_duplicates(self):
        payload = {
            "results": [
                {
                    "position": {"lat": 39.74, "lon": -104.99},
                    "address": {
                        "freeformAddress": "Denver, CO",
                        "countrySubdivision": "Colorado",
                        "country": "United States",
                    },
                },
                {
                    "position": {"lat": 39.74, "lon": -104.99},
                    "address": {"freeformAddress": "Denver, CO"},
                },
                {
                    "position": {"lat": 39.85, "lon": -104.67},
                    "poi": {"name": "Denver International Airport"},
                    "address": {"freeformAddress": "8500 Peña Blvd, Denver, CO 80249"},
                },
                {"address": {"freeformAddress": "No position"}},
            ]
        }
        places, _ = self.search(FakeResponse(200, payload))
        self.assertEqual([p["label"] for p in places], ["Denver, CO", "Denver International Airport"])
        self.assertEqual(places[0]["detail"], "Colorado, United States")
        self.assertEqual(places[1]["detail"], "8500 Peña Blvd, Denver, CO 80249")

    def test_query_is_url_encoded_in_the_path(self):
        _, call = self.search(FakeResponse(200, {"results": []}), query="Salt Lake City/UT #1")
        self.assertIn("Salt%20Lake%20City%2FUT%20%231", call.args[0])

    def test_upstream_failure(self):
        with self.assertRaises(tomtom.TomTomError):
            self.search(FakeResponse(500, {}))


@override_settings(TOMTOM_API_KEY="test")
class ReverseGeocodeTests(SimpleTestCase):
    def lookup(self, response, lat=41.79, lon=-107.24):
        session = mock.Mock()
        session.get.return_value = response
        with mock.patch("routing.services.tomtom.session", return_value=session):
            return tomtom.reverse_geocode(lat, lon), session.get.call_args

    def test_street_address_with_town_as_detail(self):
        payload = {
            "addresses": [
                {
                    "address": {
                        "streetNameAndNumber": "1200 W Spruce St",
                        "municipality": "Rawlins",
                        "countrySubdivisionCode": "WY",
                        "country": "United States",
                    }
                }
            ]
        }
        place, call = self.lookup(FakeResponse(200, payload))
        self.assertEqual(place["label"], "1200 W Spruce St")
        self.assertEqual(place["detail"], "Rawlins, WY, United States")
        # The pin stays where it was dropped, not on the matched address.
        self.assertEqual((place["lat"], place["lon"]), (41.79, -107.24))
        self.assertIn("41.790000,-107.240000", call.args[0])

    def test_open_country_falls_back_to_town(self):
        payload = {
            "addresses": [
                {"address": {"countrySecondarySubdivision": "Carbon", "countrySubdivision": "Wyoming"}}
            ]
        }
        place, _ = self.lookup(FakeResponse(200, payload))
        self.assertEqual(place["label"], "Carbon, Wyoming")
        self.assertEqual(place["detail"], "")

    def test_no_address_returns_none(self):
        place, _ = self.lookup(FakeResponse(200, {"addresses": [{"address": {}}]}))
        self.assertIsNone(place)
        place, _ = self.lookup(FakeResponse(200, {"addresses": []}))
        self.assertIsNone(place)

    def test_upstream_failure(self):
        with self.assertRaises(tomtom.TomTomError):
            self.lookup(FakeResponse(503, {}))

    def test_unreachable(self):
        session = mock.Mock()
        session.get.side_effect = tomtom.requests.ConnectionError("down")
        with (
            mock.patch("routing.services.tomtom.session", return_value=session),
            self.assertRaises(tomtom.TomTomError),
        ):
            tomtom.reverse_geocode(1, 2)


class ReverseGeocodeEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    @mock.patch("routing.services.tomtom.reverse_geocode", return_value={"label": "Rawlins, WY"})
    def test_returns_place(self, lookup):
        resp = self.client.get("/api/reverse", {"lat": "41.79", "lon": "-107.24"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"result": {"label": "Rawlins, WY"}})
        lookup.assert_called_once_with(41.79, -107.24)

    @mock.patch("routing.services.tomtom.reverse_geocode", return_value=None)
    def test_nothing_nearby_is_null_not_an_error(self, _lookup):
        resp = self.client.get("/api/reverse", {"lat": "30", "lon": "-140"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["result"])

    def test_rejects_bad_coordinates(self):
        self.assertEqual(self.client.get("/api/reverse", {"lat": "91", "lon": "0"}).status_code, 400)
        self.assertEqual(self.client.get("/api/reverse", {"lat": "abc"}).status_code, 400)
