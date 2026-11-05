"""Trip planning: three truck routes, weather at each checkpoint ETA, risk and a recommendation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.conf import settings

from ..domain import geo
from ..domain.checkpoints import INTERVALS_MI, checkpoint_miles, merged_segments, owned_spans, summarize
from ..domain.recommend import RouteScore, recommend
from ..domain.risk import Level, assess
from . import tomtom, weather

logger = logging.getLogger(__name__)

TARGET_ROUTES = 3
LB_TO_KG = 0.45359237
DISTINCT_OVERLAP = 0.9  # routes sharing more than 90% of their length are the same route
MAX_DETOUR_TIME_RATIO = 1.6  # generated alternates may not take 60% longer than the fastest
GEOMETRY_TOLERANCE_DEG = 0.0003  # ~30 m; keeps the map payload small without visible change
POSITION_STEP_S = 15 * 60
REDUCED_INTERVALS_MI = (25, 50)


@dataclass(frozen=True)
class TripRequest:
    origin: geo.LatLon
    destination: geo.LatLon
    departure: datetime
    load_lb: float


@dataclass
class _PreparedRoute:
    route_id: str
    label: str
    raw: tomtom.RawRoute
    cum: list[float]
    profile: geo.TimeProfile
    stops: dict[float, tuple[geo.LatLon, datetime]]  # checkpoint mile -> (position, ETA)


def plan_trip(
    req: TripRequest,
    *,
    routes_fn: Callable[..., list[tomtom.RawRoute]] | None = None,
    weather_fn: Callable[..., list[weather.HourlySeries]] | None = None,
) -> dict:
    """Plan a trip. `routes_fn` and `weather_fn` replace TomTom and Open-Meteo for demo scenarios."""
    gross_lb = req.load_lb + settings.TRUCK_TARE_LB
    raw_routes, notices = _find_routes(req, round(gross_lb * LB_TO_KG), routes_fn or tomtom.calculate_routes)
    raw_routes.sort(key=lambda r: r.travel_time_s)
    intervals = INTERVALS_MI
    routes = [_prepare(r, chr(ord("A") + i), req.departure, intervals) for i, r in enumerate(raw_routes)]
    budget = settings.WEATHER_LOOKUP_BUDGET
    if budget and _lookup_count(routes) > budget:
        intervals = REDUCED_INTERVALS_MI
        routes = [_prepare(r, chr(ord("A") + i), req.departure, intervals) for i, r in enumerate(raw_routes)]
        notices.append(
            "10-mile checkpoints are off for a trip this long, "
            "to stay within the free weather service's limits."
        )

    series_by_loc = _fetch_checkpoint_weather(routes, req.departure, weather_fn or weather.fetch_hourly)

    route_payloads, scores_by_interval = [], {str(i): [] for i in intervals}
    for route in routes:
        analyses = {}
        for interval in intervals:
            analysis = _analyze(route, interval, series_by_loc, req.load_lb)
            analyses[str(interval)] = analysis
            by_level = analysis["miles_by_level"]
            scores_by_interval[str(interval)].append(
                RouteScore(
                    route_id=route.route_id,
                    label=route.label,
                    no_travel_mi=by_level["no_travel"],
                    severe_mi=by_level["severe"],
                    high_mi=by_level["high"],
                    avg_risk=analysis["avg_risk"],
                    duration_s=route.raw.travel_time_s,
                )
            )
        route_payloads.append(_route_payload(route, req.departure, analyses))

    return {
        "departure": _iso(req.departure),
        "load_lb": req.load_lb,
        "gross_weight_lb": gross_lb,
        "intervals": [str(i) for i in intervals],
        "routes": route_payloads,
        "recommendations": {k: recommend(v) for k, v in scores_by_interval.items()},
        "notices": notices,
    }


# Route discovery ---------------------------------------------------------------------------


def _find_routes(
    req: TripRequest, gross_kg: int, calculate: Callable[..., list[tomtom.RawRoute]]
) -> tuple[list[tomtom.RawRoute], list[str]]:
    found = calculate(
        [req.origin, req.destination], req.departure, gross_kg, max_alternatives=TARGET_ROUTES - 1
    )
    distinct: list[tomtom.RawRoute] = []
    for r in found:
        if _is_distinct(r, distinct):
            distinct.append(r)

    if len(distinct) < TARGET_ROUTES:
        fastest = min(r.travel_time_s for r in distinct)
        waypoints = _detour_waypoints(distinct[0], req.origin, req.destination)

        def via(wp: geo.LatLon) -> list[tomtom.RawRoute]:
            try:
                return calculate([req.origin, wp, req.destination], req.departure, gross_kg)
            except tomtom.TomTomError as exc:
                logger.info("Detour via %s skipped: %s", wp, exc)
                return []

        with ThreadPoolExecutor(max_workers=len(waypoints)) as pool:
            candidates = [r for batch in pool.map(via, waypoints) for r in batch]
        candidates = sorted(
            (c for c in candidates if c.travel_time_s <= fastest * MAX_DETOUR_TIME_RATIO),
            key=lambda r: r.travel_time_s,
        )
        for c in candidates:
            if len(distinct) >= TARGET_ROUTES:
                break
            if _is_distinct(c, distinct):
                distinct.append(c)

    notices = []
    # A single route is explained by the recommendation itself; two routes need a word of explanation.
    if 1 < len(distinct) < TARGET_ROUTES:
        notices.append(f"Only {len(distinct)} distinct routes exist for this trip without long detours.")
    return distinct[:TARGET_ROUTES], notices


def _is_distinct(route: tomtom.RawRoute, existing: list[tomtom.RawRoute]) -> bool:
    for other in existing:
        if (
            geo.overlap_fraction(other.overlap_cells, route.overlap_samples) >= DISTINCT_OVERLAP
            and geo.overlap_fraction(route.overlap_cells, other.overlap_samples) >= DISTINCT_OVERLAP
        ):
            return False
    return True


def _detour_waypoints(primary: tomtom.RawRoute, origin: geo.LatLon, dest: geo.LatLon) -> list[geo.LatLon]:
    """Points to either side of the fastest route's midpoint, used to force genuinely different paths."""
    mid = geo.point_at_mile(primary.points, primary.cum, primary.cum[-1] / 2)
    bearing = geo.initial_bearing(origin, dest)
    crow = geo.haversine_mi(origin, dest)
    points = []
    for frac in (0.15, 0.3):
        offset = min(max(crow * frac, 5.0), 150.0)
        for side in (90, -90):
            points.append(geo.destination_point(mid, bearing + side, offset))
    return points


# Per-route analysis ------------------------------------------------------------------------


def _prepare(
    raw: tomtom.RawRoute, letter: str, departure: datetime, intervals: tuple[int, ...]
) -> _PreparedRoute:
    cum = raw.cum
    try:
        profile = geo.TimeProfile(raw.time_profile)
    except ValueError:
        profile = geo.TimeProfile([(0.0, 0.0), (raw.length_mi, raw.travel_time_s)])

    stops: dict[float, tuple[geo.LatLon, datetime]] = {}
    for interval in intervals:
        for mile in checkpoint_miles(raw.length_mi, interval):
            if mile not in stops:
                pos = geo.point_at_mile(raw.points, cum, mile)
                stops[mile] = (pos, departure + timedelta(seconds=profile.seconds_at(mile)))
    return _PreparedRoute(letter, f"Route {letter}", raw, cum, profile, stops)


def _loc_key(pos: geo.LatLon) -> geo.LatLon:
    return (round(pos[0], 3), round(pos[1], 3))


def _lookup_count(routes: list[_PreparedRoute]) -> int:
    return len({_loc_key(pos) for r in routes for pos, _ in r.stops.values()})


def _fetch_checkpoint_weather(
    routes: list[_PreparedRoute], departure: datetime, fetch: Callable[..., list[weather.HourlySeries]]
) -> dict[geo.LatLon, weather.HourlySeries]:
    locations = sorted({_loc_key(pos) for r in routes for pos, _ in r.stops.values()})
    latest = max(eta for r in routes for _, eta in r.stops.values())
    series = fetch(locations, departure, latest)
    return dict(zip(locations, series, strict=False))


def _analyze(route: _PreparedRoute, interval: int, series_by_loc: dict, load_lb: float) -> dict:
    miles = checkpoint_miles(route.raw.length_mi, interval)
    checkpoints, levels = [], []
    for mile in miles:
        pos, eta = route.stops[mile]
        sample = series_by_loc[_loc_key(pos)].at(eta)
        level: Level | None = None
        cp = {
            "mile": round(mile, 1),
            "lat": round(pos[0], 5),
            "lon": round(pos[1], 5),
            "eta": _iso(eta),
            "wind_mph": None,
            "gust_mph": None,
            "rain_in": None,
            "snow_in": None,
            "level": None,
            "drivers": [],
            "load_rule": None,
        }
        if sample is not None:
            a = assess(sample.wind_mph, sample.rain_in, sample.snow_in, load_lb)
            level = a.level
            cp.update(
                wind_mph=sample.wind_mph,
                gust_mph=sample.gust_mph,
                rain_in=sample.rain_in,
                snow_in=sample.snow_in,
                level=a.level.key,
                drivers=list(a.drivers),
                load_rule=a.load_rule,
            )
        checkpoints.append(cp)
        levels.append(level)

    spans = owned_spans(miles)
    return {
        "checkpoints": checkpoints,
        "segments": merged_segments(levels, spans),
        **summarize(levels, spans),
    }


def _route_payload(route: _PreparedRoute, departure: datetime, analyses: dict) -> dict:
    raw = route.raw
    keep = geo.simplify_indices(raw.points, GEOMETRY_TOLERANCE_DEG)

    positions = []
    t = 0.0
    while True:
        mile = route.profile.miles_at(t)
        lat, lon = geo.point_at_mile(raw.points, route.cum, mile)
        positions.append([round(t / 3600, 3), round(lon, 5), round(lat, 5), round(mile, 1)])
        if t >= raw.travel_time_s:
            break
        t = min(t + POSITION_STEP_S, raw.travel_time_s)

    top_roads = sorted(raw.road_miles, key=raw.road_miles.get, reverse=True)[:2]
    via = [r for r in raw.road_order if r in top_roads]

    return {
        "id": route.route_id,
        "label": route.label,
        "via": ", ".join(via) or None,
        "distance_mi": round(raw.length_mi, 1),
        "duration_s": round(raw.travel_time_s),
        "traffic_delay_s": round(raw.traffic_delay_s),
        "departure": _iso(departure),
        "arrival": _iso(departure + timedelta(seconds=raw.travel_time_s)),
        "coordinates": [[round(raw.points[i][1], 5), round(raw.points[i][0], 5)] for i in keep],
        "coordinate_miles": [round(route.cum[i], 3) for i in keep],
        "positions": positions,
        "analyses": analyses,
    }


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
