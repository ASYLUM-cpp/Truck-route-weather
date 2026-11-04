from datetime import UTC, datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone as dj_tz
from rest_framework.test import APIClient

from routing.domain import geo
from routing.services import tomtom
from routing.services.weather import HourlySeries

CHICAGO = (41.8781, -87.6298)
DENVER = (39.7392, -104.9903)


def fake_route(points, mph=55.0):
    pts = geo.densify(points, 2.0)
    length = geo.cumulative_miles(pts)[-1]
    seconds = length / mph * 3600
    return tomtom.RawRoute(
        points=pts,
        length_mi=length,
        travel_time_s=seconds,
        traffic_delay_s=0,
        time_profile=[(0, 0), (length, seconds)],
        road_miles={"I-80": length * 0.8, "I-76": length * 0.2},
        road_order=["I-80", "I-76"],
    )


def fake_calculate(locations, depart_at, gross_weight_kg, max_alternatives=0):
    if len(locations) == 3:
        return [fake_route(locations)]
    return [fake_route([CHICAGO, (41.3, -96.0), DENVER])]


def fake_weather(locations, start, end):
    start_h = start.replace(minute=0, second=0, microsecond=0)
    hours = int((end - start_h).total_seconds() // 3600) + 3
    out = []
    for lat, lon in locations:
        windy = lat > 41.6 and -99 < lon < -94  # a windy patch north of the fastest route
        wind = 50.0 if windy else 12.0
        out.append(
            HourlySeries(
                start=start_h,
                wind_mph=[wind] * hours,
                gust_mph=[wind + 8] * hours,
                rain_in=[0.0] * hours,
                snow_in=[0.0] * hours,
            )
        )
    return out


@override_settings(TOMTOM_API_KEY="test")
class PlanEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.departure = (dj_tz.now() + timedelta(hours=2)).isoformat()

    def payload(self, **overrides):
        body = {
            "origin": {"lat": CHICAGO[0], "lon": CHICAGO[1]},
            "destination": {"lat": DENVER[0], "lon": DENVER[1]},
            "departure": self.departure,
            "load_lb": 35000,
        }
        body.update(overrides)
        return body

    @mock.patch("routing.services.weather.fetch_hourly", side_effect=fake_weather)
    @mock.patch("routing.services.tomtom.calculate_routes", side_effect=fake_calculate)
    def test_plan_returns_three_routes_with_all_intervals(self, _routes, _weather):
        resp = self.client.post("/api/plan", self.payload(), format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(len(data["routes"]), 3)
        self.assertEqual([r["label"] for r in data["routes"]], ["Route A", "Route B", "Route C"])
        durations = [r["duration_s"] for r in data["routes"]]
        self.assertEqual(durations, sorted(durations))
        for route in data["routes"]:
            self.assertEqual(set(route["analyses"]), {"10", "25", "50"})
            self.assertEqual(len(route["coordinates"]), len(route["coordinate_miles"]))
            cps = route["analyses"]["25"]["checkpoints"]
            self.assertEqual(cps[0]["mile"], 0)
            self.assertAlmostEqual(cps[-1]["mile"], route["distance_mi"], delta=0.1)
            etas = [datetime.fromisoformat(c["eta"].replace("Z", "+00:00")) for c in cps]
            self.assertEqual(etas, sorted(etas))
        for key in ("10", "25", "50"):
            rec = data["recommendations"][key]
            self.assertIn(rec["route_id"], {"A", "B", "C"})
            self.assertTrue(rec["reason"])

    @mock.patch("routing.services.weather.fetch_hourly", side_effect=fake_weather)
    @mock.patch("routing.services.tomtom.calculate_routes", side_effect=fake_calculate)
    def test_heavy_load_in_wind_turns_checkpoints_no_travel(self, _routes, _weather):
        resp = self.client.post("/api/plan", self.payload(load_lb=36000), format="json")
        data = resp.json()
        levels = {cp["level"] for r in data["routes"] for cp in r["analyses"]["10"]["checkpoints"]}
        self.assertIn("no_travel", levels)
        windy = [
            cp
            for r in data["routes"]
            for cp in r["analyses"]["10"]["checkpoints"]
            if cp["level"] == "no_travel"
        ]
        self.assertTrue(all(cp["load_rule"] == "wind_45_load_30000" for cp in windy))
        rec = data["recommendations"]["10"]
        best = next(r for r in data["routes"] if r["id"] == rec["route_id"])
        self.assertEqual(best["analyses"]["10"]["miles_by_level"]["no_travel"], 0)

    def test_rejects_past_departure(self):
        past = (dj_tz.now() - timedelta(hours=3)).isoformat()
        resp = self.client.post("/api/plan", self.payload(departure=past), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("departure", resp.json())

    def test_rejects_identical_endpoints(self):
        resp = self.client.post(
            "/api/plan", self.payload(destination={"lat": CHICAGO[0], "lon": CHICAGO[1]}), format="json"
        )
        self.assertEqual(resp.status_code, 400)

    @mock.patch(
        "routing.services.tomtom.calculate_routes",
        side_effect=tomtom.NoRouteFound("No truck route connects these two places."),
    )
    def test_no_route_maps_to_422(self, _routes):
        resp = self.client.post("/api/plan", self.payload(), format="json")
        self.assertEqual(resp.status_code, 422)
        self.assertIn("No truck route", resp.json()["detail"])


class HeatmapEndpointTests(SimpleTestCase):
    @mock.patch("routing.services.weather.fetch_hourly", side_effect=fake_weather)
    def test_heatmap_shape(self, _weather):
        departure = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        body = {
            "paths": [[[CHICAGO[1], CHICAGO[0]], [-96.0, 41.3], [DENVER[1], DENVER[0]]]],
            "departure": departure,
            "load_lb": 20000,
        }
        resp = APIClient().post("/api/heatmap", body, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(len(data["times"]), 49)
        n = len(data["cells"])
        for key in ("risk", "wind", "rain", "snow"):
            self.assertEqual(len(data["values"][key]), n)
            self.assertTrue(all(len(row) == 49 for row in data["values"][key]))
