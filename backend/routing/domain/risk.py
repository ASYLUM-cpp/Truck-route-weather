"""Weather risk classification implementing the assessment's risk and load rules.

Band edges follow the published table. Where two bands share an edge
(rain 0.25 is listed under both Moderate and High) the value belongs to the
higher band, matching how the wind row is written (25-34, 35-44, ...).
The top edges of the Severe rain and snow bands are inclusive because the
No Travel column is written as a strict ">".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Level(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def key(self) -> str:
        return self.name.lower()


def classify_wind(mph: float) -> Level:
    if mph >= 55:
        return Level.NO_TRAVEL
    if mph >= 45:
        return Level.SEVERE
    if mph >= 35:
        return Level.HIGH
    if mph >= 25:
        return Level.MODERATE
    return Level.LOW


def classify_rain(in_per_hr: float) -> Level:
    if in_per_hr > 1.0:
        return Level.NO_TRAVEL
    if in_per_hr >= 0.5:
        return Level.SEVERE
    if in_per_hr >= 0.25:
        return Level.HIGH
    if in_per_hr >= 0.10:
        return Level.MODERATE
    return Level.LOW


def classify_snow(in_per_hr: float) -> Level:
    if in_per_hr > 3.0:
        return Level.NO_TRAVEL
    if in_per_hr >= 2.0:
        return Level.SEVERE
    if in_per_hr >= 1.0:
        return Level.HIGH
    if in_per_hr >= 0.5:
        return Level.MODERATE
    return Level.LOW


LOAD_RULE_NO_TRAVEL = "wind_45_load_30000"
LOAD_RULE_SEVERE = "wind_35_load_40000"


@dataclass(frozen=True)
class Assessment:
    level: Level
    drivers: tuple[str, ...]
    load_rule: str | None


def assess(wind_mph: float, rain_in: float, snow_in: float, load_lb: float) -> Assessment:
    """Overall level is the worst condition, after the load rules raise the wind level."""
    wind = classify_wind(wind_mph)
    load_rule = None
    if 45 <= wind_mph < 55 and load_lb > 30_000:
        wind, load_rule = Level.NO_TRAVEL, LOAD_RULE_NO_TRAVEL
    elif 35 <= wind_mph < 45 and load_lb > 40_000:
        wind, load_rule = Level.SEVERE, LOAD_RULE_SEVERE

    levels = {"wind": wind, "rain": classify_rain(rain_in), "snow": classify_snow(snow_in)}
    worst = max(levels.values())
    drivers = tuple(name for name, lvl in levels.items() if lvl == worst and worst > Level.LOW)
    if load_rule and "wind" not in drivers:
        load_rule = None
    return Assessment(level=worst, drivers=drivers, load_rule=load_rule)
