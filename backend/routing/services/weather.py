"""Hourly forecasts from Open-Meteo for many locations at once."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache

from ..domain.geo import LatLon
from .http import session

logger = logging.getLogger(__name__)

FREE_URL = "https://api.open-meteo.com/v1/forecast"
CUSTOMER_URL = "https://customer-api.open-meteo.com/v1/forecast"
HOURLY_VARS = ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall")
CHUNK_SIZE = 100
TIMEOUT_S = 25
CACHE_TTL_S = 15 * 60
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54


class WeatherError(Exception):
    """The forecast provider failed."""


@dataclass(frozen=True)
class Sample:
    wind_mph: float
    gust_mph: float | None
    rain_in: float
    snow_in: float


@dataclass
class HourlySeries:
    """Hourly values for one location, starting at ``start`` (UTC, on the hour)."""

    start: datetime
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in: list[float | None]
    snow_in: list[float | None]

    def at(self, when: datetime) -> Sample | None:
        """Conditions at an instant.

        Wind is an instantaneous value, so it is interpolated between the two
        surrounding hours. Rain and snowfall are totals over the preceding
        hour, so the hour that ends at or after ``when`` is used.
        """
        h = (when - self.start).total_seconds() / 3600
        lo, hi = math.floor(h), math.ceil(h)
        if lo < 0 or hi >= len(self.wind_mph):
            return None
        w = _lerp(self.wind_mph[lo], self.wind_mph[hi], h - lo)
        rain, snow = self.rain_in[hi], self.snow_in[hi]
        if w is None or rain is None or snow is None:
            return None
        g = _lerp(self.gust_mph[lo], self.gust_mph[hi], h - lo)
        return Sample(
            wind_mph=round(w, 1),
            gust_mph=None if g is None else round(g, 1),
            rain_in=round(rain, 2),
            snow_in=round(snow, 2),
        )

    def hour(self, index: int) -> Sample | None:
        if not 0 <= index < len(self.wind_mph):
            return None
        w, r, s = self.wind_mph[index], self.rain_in[index], self.snow_in[index]
        if w is None or r is None or s is None:
            return None
        g = self.gust_mph[index]
        return Sample(round(w, 1), None if g is None else round(g, 1), round(r, 2), round(s, 2))


def _lerp(a: float | None, b: float | None, t: float) -> float | None:
    if a is None or b is None:
        return a if t < 0.5 else b
    return a + (b - a) * t


def floor_hour(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def fetch_hourly(locations: Sequence[LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
    """Series for every location covering [start, end] (both rounded to whole hours)."""
    start_h = floor_hour(start)
    end_h = floor_hour(end) + (timedelta(hours=1) if end > floor_hour(end) else timedelta(0))
    chunks = [locations[i : i + CHUNK_SIZE] for i in range(0, len(locations), CHUNK_SIZE)]
    if not chunks:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        results = list(pool.map(lambda c: _fetch_chunk(c, start_h, end_h), chunks))
    return [series for chunk in results for series in chunk]


def _fetch_chunk(locs: Sequence[LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
    params = {
        "latitude": ",".join(f"{lat:.3f}" for lat, _ in locs),
        "longitude": ",".join(f"{lon:.3f}" for _, lon in locs),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "mph",
        "timezone": "GMT",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }
    cache_key = "om:" + hashlib.sha1(repr(sorted(params.items())).encode()).hexdigest()
    payload = cache.get(cache_key)
    if payload is None:
        url = FREE_URL
        if settings.OPEN_METEO_API_KEY:
            url = CUSTOMER_URL
            params = {**params, "apikey": settings.OPEN_METEO_API_KEY}
        try:
            resp = session().get(url, params=params, timeout=TIMEOUT_S)
        except requests.RequestException as exc:
            raise WeatherError("The weather service is unreachable. Try again in a moment.") from exc
        if resp.status_code == 429:
            logger.warning("Open-Meteo rate limit reached (%d locations)", len(locs))
            raise WeatherError(
                "The free weather service limit has been reached. Wait a minute and try again, "
                "or use wider checkpoint spacing for very long trips."
            )
        if resp.status_code != 200:
            reason = ""
            with contextlib.suppress(ValueError):
                reason = resp.json().get("reason", "")
            logger.warning("Open-Meteo %s: %s", resp.status_code, reason or resp.text[:300])
            raise WeatherError("The weather service returned an error. Try again in a moment.")
        payload = resp.json()
        cache.set(cache_key, payload, CACHE_TTL_S)

    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(locs):
        raise WeatherError("The weather service returned an incomplete forecast.")
    return [_parse(item) for item in items]


def _parse(item: dict) -> HourlySeries:
    hourly = item.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise WeatherError("The weather service returned no hourly data.")
    start = datetime.fromisoformat(times[0]).replace(tzinfo=UTC)

    def col(name: str) -> list:
        values = hourly.get(name) or []
        return values + [None] * (len(times) - len(values))

    rain = [
        None if r is None and s is None else ((r or 0) + (s or 0)) / MM_PER_INCH
        for r, s in zip(col("rain"), col("showers"), strict=False)
    ]
    snow = [None if v is None else v / CM_PER_INCH for v in col("snowfall")]
    return HourlySeries(
        start=start,
        wind_mph=col("wind_speed_10m"),
        gust_mph=col("wind_gusts_10m"),
        rain_in=rain,
        snow_in=snow,
    )
