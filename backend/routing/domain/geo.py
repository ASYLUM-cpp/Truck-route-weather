"""Geometry helpers for polylines expressed as (lat, lon) tuples."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_miles(points: Sequence[LatLon]) -> list[float]:
    """Running distance in miles at every vertex of the polyline."""
    if not points:
        return []
    out = [0.0]
    for prev, cur in zip(points, points[1:], strict=False):
        out.append(out[-1] + haversine_mi(prev, cur))
    return out


def point_at_mile(points: Sequence[LatLon], cum: Sequence[float], mile: float) -> LatLon:
    """Linearly interpolated position at a given distance along the polyline."""
    if mile <= 0:
        return points[0]
    if mile >= cum[-1]:
        return points[-1]
    i = bisect_right(cum, mile)
    a, b = points[i - 1], points[i]
    span = cum[i] - cum[i - 1]
    t = 0.0 if span == 0 else (mile - cum[i - 1]) / span
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def densify(points: Sequence[LatLon], step_mi: float) -> list[LatLon]:
    """Points spaced at most ``step_mi`` apart, keeping the original vertices."""
    if len(points) < 2:
        return list(points)
    out: list[LatLon] = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        d = haversine_mi(a, b)
        n = int(d // step_mi)
        for k in range(1, n + 1):
            t = k * step_mi / d
            if t < 1:
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        out.append(b)
    return out


def simplify_indices(points: Sequence[LatLon], tolerance_deg: float) -> list[int]:
    """Indices of vertices to keep: a radial-distance pre-pass, then Ramer-Douglas-Peucker.

    The pre-pass drops vertices closer than the tolerance to the last kept one, which removes most
    of a dense routing polyline cheaply before the quadratic-worst-case RDP pass.
    """
    n = len(points)
    if n < 3:
        return list(range(n))
    tol2 = tolerance_deg * tolerance_deg
    cand = [0]
    last_lat, last_lon = points[0]
    for i in range(1, n - 1):
        lat, lon = points[i]
        if (lat - last_lat) ** 2 + (lon - last_lon) ** 2 > tol2:
            cand.append(i)
            last_lat, last_lon = lat, lon
    cand.append(n - 1)

    m = len(cand)
    keep = [False] * m
    keep[0] = keep[-1] = True
    stack = [(0, m - 1)]
    while stack:
        start, end = stack.pop()
        alat, alon = points[cand[start]]
        blat, blon = points[cand[end]]
        scale = math.cos(math.radians((alat + blat) / 2))
        ax, ay = alon * scale, alat
        dx, dy = blon * scale - ax, blat - ay
        seg2 = dx * dx + dy * dy
        best, best_d2 = -1, tol2
        for k in range(start + 1, end):
            plat, plon = points[cand[k]]
            ex, ey = plon * scale - ax, plat - ay
            if seg2 == 0:
                d2 = ex * ex + ey * ey
            else:
                t = (ex * dx + ey * dy) / seg2
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                fx, fy = ex - t * dx, ey - t * dy
                d2 = fx * fx + fy * fy
            if d2 > best_d2:
                best, best_d2 = k, d2
        if best != -1:
            keep[best] = True
            stack.append((start, best))
            stack.append((best, end))
    return [cand[k] for k in range(m) if keep[k]]


class TimeProfile:
    """Monotonic mapping between distance travelled and elapsed driving time."""

    def __init__(self, pairs: Sequence[tuple[float, float]]):
        cleaned: list[tuple[float, float]] = []
        for mile, sec in sorted(pairs):
            if cleaned and (mile <= cleaned[-1][0] or sec < cleaned[-1][1]):
                continue
            cleaned.append((mile, sec))
        if len(cleaned) < 2:
            raise ValueError("A time profile needs at least two increasing points")
        self._miles = [p[0] for p in cleaned]
        self._secs = [p[1] for p in cleaned]

    @property
    def total_seconds(self) -> float:
        return self._secs[-1]

    @property
    def total_miles(self) -> float:
        return self._miles[-1]

    def seconds_at(self, mile: float) -> float:
        return _interp(self._miles, self._secs, mile)

    def miles_at(self, seconds: float) -> float:
        return _interp(self._secs, self._miles, seconds)


def _interp(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_left(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    if x1 == x0:
        return y1
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def resample(points: Sequence[LatLon], cum: Sequence[float], step_mi: float) -> list[LatLon]:
    """Points every ``step_mi`` along the polyline, plus its end, regardless of vertex density."""
    total = cum[-1]
    n = max(1, math.ceil(total / step_mi))
    return [point_at_mile(points, cum, total * k / n) for k in range(n + 1)]


OVERLAP_CELL_DEG = 0.02  # ~1.4 mi grid used to decide whether two routes share road


def cell_set(samples: Sequence[LatLon], cell_deg: float = OVERLAP_CELL_DEG) -> set[tuple[int, int]]:
    return {(round(lat / cell_deg), round(lon / cell_deg)) for lat, lon in samples}


def overlap_fraction(
    cells: set[tuple[int, int]], samples: Sequence[LatLon], cell_deg: float = OVERLAP_CELL_DEG
) -> float:
    """Share of ``samples`` within one grid cell of ``cells`` (0..1)."""
    if not samples:
        return 0.0
    hits = 0
    for lat, lon in samples:
        ky, kx = round(lat / cell_deg), round(lon / cell_deg)
        if any((ky + dy, kx + dx) in cells for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
            hits += 1
    return hits / len(samples)


def overlap_ratio(a: Sequence[LatLon], b: Sequence[LatLon], cell_deg: float = OVERLAP_CELL_DEG) -> float:
    """Share of polyline ``b`` that runs along polyline ``a`` (0..1)."""
    cells = cell_set(resample(a, cumulative_miles(a), 0.5), cell_deg)
    return overlap_fraction(cells, resample(b, cumulative_miles(b), 1.0), cell_deg)


def destination_point(origin: LatLon, bearing_deg: float, distance_mi: float) -> LatLon:
    lat1, lon1 = map(math.radians, origin)
    brg = math.radians(bearing_deg)
    d = distance_mi / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180)


def initial_bearing(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
