"""TomTom Search and Routing clients."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from urllib.parse import quote

import requests
from django.conf import settings

from ..domain import geo
from ..domain.geo import METERS_PER_MILE, LatLon
from .http import session

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tomtom.com"
TIMEOUT_S = 20
# TomTom rejects departures in the past; the form allows a short grace period.
MIN_DEPART_LEAD = timedelta(seconds=60)
NO_ROUTE_CODES = {"NO_ROUTE_FOUND", "ROUTE_NOT_FOUND"}
UNREACHABLE_CODES = {"MAP_MATCHING_FAILURE", "CANNOT_RESTORE_BASEROUTE"}


class TomTomError(Exception):
    """The routing provider failed or rejected the request."""


class NoRouteFound(TomTomError):
    """No truck route exists between the requested points."""


@dataclass
class RawRoute:
    points: list[LatLon]
    length_mi: float
    travel_time_s: float
    traffic_delay_s: float
    # (miles from start, seconds from start), taken from guidance instructions
    time_profile: list[tuple[float, float]]
    road_miles: dict[str, float] = field(default_factory=dict)
    road_order: list[str] = field(default_factory=list)

    @cached_property
    def cum(self) -> list[float]:
        """Distance in miles at each vertex, scaled to TomTom's reported length."""
        raw = geo.cumulative_miles(self.points)
        scale = self.length_mi / raw[-1] if raw[-1] > 0 else 1.0
        return [c * scale for c in raw]

    @cached_property
    def overlap_samples(self) -> list[LatLon]:
        return geo.resample(self.points, self.cum, 1.0)

    @cached_property
    def overlap_cells(self) -> set[tuple[int, int]]:
        return geo.cell_set(geo.resample(self.points, self.cum, 0.5))


def _key() -> str:
    key = settings.TOMTOM_API_KEY
    if not key:
        raise TomTomError("The server is missing its TomTom API key.")
    return key


def search_places(query: str, limit: int = 6) -> list[dict]:
    params = {"key": _key(), "typeahead": "true", "limit": limit, "language": "en-US"}
    if settings.TOMTOM_COUNTRY_SET:
        params["countrySet"] = settings.TOMTOM_COUNTRY_SET
    url = f"{BASE_URL}/search/2/search/{quote(query, safe='')}.json"
    try:
        resp = session().get(url, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        raise TomTomError("Place search is unreachable. Try again in a moment.") from exc
    if resp.status_code != 200:
        logger.warning("TomTom search %s: %s", resp.status_code, resp.text[:300])
        raise TomTomError("Place search failed. Try again in a moment.")

    places, seen = [], set()
    for item in resp.json().get("results", []):
        pos, addr = item.get("position") or {}, item.get("address") or {}
        if "lat" not in pos or "lon" not in pos:
            continue
        poi_name = (item.get("poi") or {}).get("name")
        label = poi_name or addr.get("freeformAddress") or ""
        detail_parts = [
            addr.get("municipality"),
            addr.get("countrySubdivisionCode") or addr.get("countrySubdivision"),
            addr.get("country"),
        ]
        detail = ", ".join(p for p in detail_parts if p and p not in label)
        if poi_name and addr.get("freeformAddress"):
            detail = addr["freeformAddress"]
        dedupe_key = (label, round(pos["lat"], 3), round(pos["lon"], 3))
        if not label or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        places.append({"label": label, "detail": detail, "lat": pos["lat"], "lon": pos["lon"]})
    return places


def reverse_geocode(lat: float, lon: float) -> dict | None:
    """The nearest address to a point, labelled like a search result, or None in open country or water.

    The coordinates returned are the ones asked for, so a pin dropped on a yard stays where it was put.
    """
    params = {"key": _key(), "language": "en-US", "radius": 2000}
    url = f"{BASE_URL}/search/2/reverseGeocode/{lat:.6f},{lon:.6f}.json"
    try:
        resp = session().get(url, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        raise TomTomError("Place lookup is unreachable. Try again in a moment.") from exc
    if resp.status_code != 200:
        logger.warning("TomTom reverse geocode %s: %s", resp.status_code, resp.text[:300])
        raise TomTomError("Place lookup failed. Try again in a moment.")

    for item in resp.json().get("addresses", []):
        addr = item.get("address") or {}
        town = (
            addr.get("municipality")
            or addr.get("municipalitySubdivision")
            or addr.get("countrySecondarySubdivision")
        )
        state = addr.get("countrySubdivisionCode") or addr.get("countrySubdivision")
        street = addr.get("streetNameAndNumber") or addr.get("street") or addr.get("streetName")
        place = ", ".join(p for p in (town, state) if p)
        label = street or place or addr.get("freeformAddress") or ""
        if not label:
            continue
        detail_parts = [place if street else None, addr.get("country")]
        detail = ", ".join(p for p in detail_parts if p)
        return {"label": label, "detail": detail, "lat": lat, "lon": lon}
    return None


def calculate_routes(
    locations: list[LatLon],
    depart_at: datetime,
    gross_weight_kg: int,
    max_alternatives: int = 0,
) -> list[RawRoute]:
    """Truck routes through ``locations`` (origin, optional waypoints, destination)."""
    path = ":".join(f"{lat:.6f},{lon:.6f}" for lat, lon in locations)
    depart_at = max(depart_at, datetime.now(UTC) + MIN_DEPART_LEAD)
    params = {
        "key": _key(),
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "vehicleWeight": gross_weight_kg,
        "departAt": depart_at.isoformat(timespec="seconds"),
        "traffic": "true",
        "routeType": "fastest",
        "instructionsType": "text",
        "language": "en-US",
        "routeRepresentation": "polyline",
    }
    if max_alternatives:
        params["maxAlternatives"] = max_alternatives
        params["alternativeType"] = "anyRoute"

    url = f"{BASE_URL}/routing/1/calculateRoute/{path}/json"
    try:
        resp = session().get(url, params=params, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        raise TomTomError("The routing service is unreachable. Try again in a moment.") from exc

    if resp.status_code == 403:
        raise TomTomError("The routing service rejected the server's API key.")
    if resp.status_code == 429:
        raise TomTomError("The routing service is rate limited. Wait a minute and try again.")
    if resp.status_code == 400:
        code, detail = _error_detail(resp)
        logger.info("TomTom routing 400: %s %s", code, detail)
        text = f"{code} {detail}".upper()
        if code in UNREACHABLE_CODES or "MAP_MATCHING" in text:
            raise NoRouteFound(
                "One of the places is too far from a road a truck can use. Choose a more specific address."
            )
        if code in NO_ROUTE_CODES or "NO_ROUTE" in text or "NOT FOUND" in text:
            raise NoRouteFound("No truck route connects these two places.")
        raise TomTomError("The routing service could not plan this trip. Check both places and try again.")
    if resp.status_code != 200:
        logger.warning("TomTom routing %s: %s", resp.status_code, resp.text[:300])
        raise TomTomError("The routing service returned an error. Try again in a moment.")

    routes = [_parse_route(r) for r in resp.json().get("routes", [])]
    routes = [r for r in routes if r is not None]
    if not routes:
        raise NoRouteFound("No truck route connects these two places.")
    return routes


def _error_detail(resp: requests.Response) -> tuple[str, str]:
    """(code, message) from a TomTom error body, tolerant of its two error shapes."""
    try:
        body = resp.json()
    except ValueError:
        return "", resp.text[:300]
    detailed = body.get("detailedError") or {}
    error = body.get("error") or {}
    code = str(detailed.get("code") or "").upper()
    message = detailed.get("message") or error.get("description") or ""
    return code, str(message)[:300]


def _parse_route(route: dict) -> RawRoute | None:
    points: list[LatLon] = []
    for leg in route.get("legs", []):
        for p in leg.get("points", []):
            pt = (p["latitude"], p["longitude"])
            if not points or points[-1] != pt:
                points.append(pt)
    if len(points) < 2:
        return None

    summary = route.get("summary", {})
    length_mi = summary.get("lengthInMeters", 0) / METERS_PER_MILE
    travel_s = float(summary.get("travelTimeInSeconds", 0))
    if length_mi <= 0 or travel_s <= 0:
        return None

    profile = [(0.0, 0.0)]
    road_miles: dict[str, float] = defaultdict(float)
    road_order: list[str] = []
    instructions = (route.get("guidance") or {}).get("instructions") or []
    for cur, nxt in zip(instructions, instructions[1:] + [None], strict=False):
        offset_m = cur.get("routeOffsetInMeters")
        elapsed = cur.get("travelTimeInSeconds")
        if offset_m is not None and elapsed is not None:
            offset_mi = offset_m / METERS_PER_MILE
            if 0 < offset_mi < length_mi and 0 < elapsed < travel_s:
                profile.append((offset_mi, float(elapsed)))
        if nxt is not None and offset_m is not None and nxt.get("routeOffsetInMeters") is not None:
            road = _primary_road(cur.get("roadNumbers") or [])
            if road:
                end_m = min(nxt["routeOffsetInMeters"], summary.get("lengthInMeters", 0))
                road_miles[road] += max(0.0, end_m - offset_m) / METERS_PER_MILE
                if road not in road_order:
                    road_order.append(road)
    profile.append((length_mi, travel_s))

    return RawRoute(
        points=points,
        length_mi=length_mi,
        travel_time_s=travel_s,
        traffic_delay_s=float(summary.get("trafficDelayInSeconds", 0)),
        time_profile=profile,
        road_miles=dict(road_miles),
        road_order=road_order,
    )


def _primary_road(numbers: list[str]) -> str | None:
    for prefix in ("I-", "I ", "US-", "US "):
        for n in numbers:
            if n.upper().startswith(prefix):
                return n.replace(" ", "-")
    return numbers[0] if numbers else None
