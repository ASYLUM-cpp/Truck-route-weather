"""Weather grid covering the corridor around a set of routes.

Rows are spaced evenly in Web Mercator rather than in latitude, so the grid
maps one-to-one onto pixels of an image overlay on the web map. Cells further
than ``radius`` from every route are dropped, which keeps the number of
forecast lookups small while still showing weather on either side of the road.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .geo import EARTH_RADIUS_MI, LatLon, cumulative_miles, haversine_mi, point_at_mile


@dataclass(frozen=True)
class CorridorGrid:
    west: float
    east: float
    north: float
    south: float
    nx: int
    ny: int
    cells: list[tuple[int, int]]  # (column, row); row 0 is the northern edge
    centers: list[LatLon]


def _merc_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _lat_from_merc(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def build_corridor_grid(paths: Sequence[Sequence[LatLon]], max_cells: int = 240) -> CorridorGrid:
    paths = [p for p in paths if len(p) >= 2]
    if not paths:
        raise ValueError("At least one path with two or more points is required")
    samples = [p for path in paths for p in _resample(path, 4.0)]

    lats = [p[0] for p in samples]
    lons = [p[1] for p in samples]
    south, north, west, east = min(lats), max(lats), min(lons), max(lons)
    diag_mi = max(haversine_mi((south, west), (north, east)), 10.0)
    radius_mi = min(max(diag_mi * 0.07, 25.0), 90.0)

    pad_lat = radius_mi / 69.0 * 1.2
    mid_lat = (south + north) / 2
    pad_lon = pad_lat / max(math.cos(math.radians(mid_lat)), 0.2)
    south, north = max(south - pad_lat, -84.0), min(north + pad_lat, 84.0)
    west, east = west - pad_lon, east + pad_lon

    x0, x1 = math.radians(west), math.radians(east)
    y0, y1 = _merc_y(south), _merc_y(north)
    ground_per_radian = EARTH_RADIUS_MI * math.cos(math.radians(mid_lat))

    longest_mi = max(cumulative_miles(path)[-1] for path in paths)
    corridor_area = (longest_mi + 2 * radius_mi) * 2 * radius_mi * 1.3
    cell_mi = max(math.sqrt(corridor_area / max_cells), diag_mi / 60.0, 3.0)
    for _ in range(40):
        step = cell_mi / ground_per_radian
        nx = max(2, math.ceil((x1 - x0) / step))
        ny = max(2, math.ceil((y1 - y0) / step))
        cells, centers = _corridor_cells(samples, x0, y1, step, nx, ny, radius_mi, cell_mi)
        if len(cells) <= max_cells:
            break
        cell_mi *= 1.15

    return CorridorGrid(
        west=math.degrees(x0),
        east=math.degrees(x0 + nx * step),
        north=_lat_from_merc(y1),
        south=_lat_from_merc(y1 - ny * step),
        nx=nx,
        ny=ny,
        cells=cells,
        centers=centers,
    )


def _resample(path: Sequence[LatLon], step_mi: float) -> list[LatLon]:
    """Evenly spaced points along a path, independent of its vertex density."""
    cum = cumulative_miles(path)
    n = max(1, math.ceil(cum[-1] / step_mi))
    return [point_at_mile(path, cum, cum[-1] * k / n) for k in range(n + 1)]


def _corridor_cells(
    samples: Sequence[LatLon],
    x0: float,
    y_top: float,
    step: float,
    nx: int,
    ny: int,
    radius_mi: float,
    cell_mi: float,
) -> tuple[list[tuple[int, int]], list[LatLon]]:
    buckets: dict[tuple[int, int], list[LatLon]] = {}
    for lat, lon in samples:
        col = int((math.radians(lon) - x0) / step)
        row = int((y_top - _merc_y(lat)) / step)
        buckets.setdefault((col, row), []).append((lat, lon))

    reach = math.ceil(radius_mi / cell_mi) + 1
    cells: list[tuple[int, int]] = []
    centers: list[LatLon] = []
    for row in range(ny):
        lat = _lat_from_merc(y_top - (row + 0.5) * step)
        for col in range(nx):
            lon = math.degrees(x0 + (col + 0.5) * step)
            if _near(buckets, col, row, reach, (lat, lon), radius_mi):
                cells.append((col, row))
                centers.append((round(lat, 4), round(lon, 4)))
    return cells, centers


def _near(buckets, col, row, reach, center, radius_mi) -> bool:
    for dr in range(-reach, reach + 1):
        for dc in range(-reach, reach + 1):
            for p in buckets.get((col + dc, row + dr), ()):
                if haversine_mi(center, p) <= radius_mi:
                    return True
    return False
