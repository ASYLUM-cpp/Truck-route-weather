"""Hourly weather grid for the trip corridor, 0-48 hours from departure."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from ..domain.corridor import build_corridor_grid
from ..domain.geo import LatLon
from ..domain.risk import assess
from . import weather

HOURS = 48
MAX_CELLS = 200  # keeps a plan plus its corridor forecast within the free weather tier's minute limit


def corridor_heatmap(
    paths: Sequence[Sequence[LatLon]],
    departure: datetime,
    load_lb: float,
    weather_fn: Callable[..., list[weather.HourlySeries]] | None = None,
) -> dict:
    grid = build_corridor_grid(paths, max_cells=MAX_CELLS)
    start = weather.floor_hour(departure)
    end = start + timedelta(hours=HOURS)
    series_list = (weather_fn or weather.fetch_hourly)(grid.centers, start, end)

    risk, wind, rain, snow = [], [], [], []
    for series in series_list:
        offset = round((start - series.start).total_seconds() / 3600)
        r_row, w_row, rn_row, s_row = [], [], [], []
        for h in range(HOURS + 1):
            sample = series.hour(offset + h)
            if sample is None:
                r_row.append(None)
                w_row.append(None)
                rn_row.append(None)
                s_row.append(None)
                continue
            r_row.append(int(assess(sample.wind_mph, sample.rain_in, sample.snow_in, load_lb).level))
            w_row.append(sample.wind_mph)
            rn_row.append(sample.rain_in)
            s_row.append(sample.snow_in)
        risk.append(r_row)
        wind.append(w_row)
        rain.append(rn_row)
        snow.append(s_row)

    return {
        "bounds": {
            "west": round(grid.west, 5),
            "east": round(grid.east, 5),
            "north": round(grid.north, 5),
            "south": round(grid.south, 5),
        },
        "nx": grid.nx,
        "ny": grid.ny,
        "cells": [list(c) for c in grid.cells],
        "times": [
            (start + timedelta(hours=h)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for h in range(HOURS + 1)
        ],
        "values": {"risk": risk, "wind": wind, "rain": rain, "snow": snow},
    }
