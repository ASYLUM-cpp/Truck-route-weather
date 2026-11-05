"""A catalogue of trips whose recommendation changes with the weather, the cargo weight or the departure time.

Runs offline on the same three Denver to Salt Lake City routes as `prove_rules` (A fastest, then B, then C),
with weather placed on each route on purpose. Everything after the weather lookup is the real code path.
Exits non-zero if any trip is not recommended the route the catalogue expects.

    python manage.py scenarios
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from unittest import mock

from django.core.management.base import BaseCommand, CommandError

from routing.domain import geo
from routing.services import planner, weather
from routing.services.weather import HourlySeries

from . import prove_rules as base

LB_PER_KG = 2.20462262
LINES = {
    rid: geo.densify([base.DENVER, spec["via"], base.SALT_LAKE], 5.0) for rid, spec in base.ROUTES.items()
}


def kg(value: float) -> float:
    """Pounds for a weight typed in kilograms, rounded the way the web app rounds before sending it."""
    return float(round(value * LB_PER_KG))


@dataclass(frozen=True)
class Cell:
    """Weather in the middle of one route: within `radius` miles of the route's midpoint, during `hours`."""

    radius: float
    wind: float = 12.0
    rain: float = 0.0
    snow: float = 0.0
    hours: tuple[float, float] | None = None  # hours after 06:00 UTC; None means all day
    at: float | None = None  # centre as a fraction of the way along the route; None means the midpoint

    def describe(self) -> str:
        parts = []
        if self.wind > 12:
            parts.append(f"wind {self.wind:g} mph")
        if self.rain:
            parts.append(f"rain {self.rain:g} in/hr")
        if self.snow:
            parts.append(f"snow {self.snow:g} in/hr")
        when = "all day"
        if self.hours:
            start = base.DEPARTURE + timedelta(hours=self.hours[0])
            end = base.DEPARTURE + timedelta(hours=self.hours[1])
            when = f"{start:%H:%M}-{end:%H:%M} UTC only"
        where = "" if self.at is None else f" around {self.at:.0%} of the way"
        return f"{' + '.join(parts)}{where}, {when}"

    def centre(self, rid: str):
        if self.at is None:
            return base.ROUTES[rid]["via"]
        line = LINES[rid]
        return line[round(self.at * (len(line) - 1))]


@dataclass(frozen=True)
class Trip:
    label: str
    load_lb: float
    expect: str
    depart_h: float = 0.0  # hours after 06:00 UTC
    all_no_travel: bool = False


@dataclass(frozen=True)
class Scenario:
    title: str
    point: str
    weather: dict[str, Cell | tuple[Cell, ...]]
    trips: list[Trip] = field(default_factory=list)


SCENARIOS = [
    Scenario(
        "1. Clear day: the fastest route wins",
        "With no weather risk anywhere, the last criterion, travel time, decides.",
        {},
        [Trip("38,000 lb", 38_000, "A")],
    ),
    Scenario(
        "2. Slower but safer, at any weight",
        "Heavy rain is Severe on A. B is 20 minutes slower but clear, so it is recommended. "
        "Rain is not affected by the load rules, so the weight makes no difference.",
        {"A": Cell(30, rain=0.6)},
        [Trip("10,000 lb", 10_000, "B"), Trip("45,000 lb", 45_000, "B")],
    ),
    Scenario(
        "3. The weight flips the route at 40,000 lb",
        "40 mph wind on A is High, but Severe above 40,000 lb. B has more High miles from rain, which "
        "the weight does not change. At exactly 40,000 lb the rule does not apply; 1 lb more and it does.",
        {"A": Cell(20, wind=40), "B": Cell(40, rain=0.3), "C": Cell(60, snow=1.5)},
        [Trip("40,000 lb", 40_000, "A"), Trip("40,001 lb", 40_001, "B")],
    ),
    Scenario(
        "4. The same flip, typed in kilograms",
        "The web app converts kilograms to whole pounds before sending. 18,143 kg is 39,998 lb; "
        "18,144 kg is 40,001 lb, which crosses the 40,000 lb rule.",
        {"A": Cell(20, wind=40), "B": Cell(40, rain=0.3), "C": Cell(60, snow=1.5)},
        [Trip("18,143 kg", kg(18_143), "A"), Trip("18,144 kg", kg(18_144), "B")],
    ),
    Scenario(
        "5. The weight flips the route at 30,000 lb",
        "50 mph wind on A is Severe, but No Travel above 30,000 lb. B has more Severe miles from rain. "
        "Light, A has the fewest Severe miles; 1 lb heavier, A has No Travel miles, which rank worst.",
        {"A": Cell(20, wind=50), "B": Cell(40, rain=0.7), "C": Cell(60, rain=0.8)},
        [Trip("30,000 lb", 30_000, "A"), Trip("30,001 lb", 30_001, "B")],
    ),
    Scenario(
        "6. A three-way flip as the load grows",
        "A has 40 mph wind (High; Severe above 40,000 lb) plus a patch of Severe rain. B has 50 mph wind "
        "(Severe; No Travel above 30,000 lb). C has Severe rain over more miles than A's patch, but fewer "
        "than A's patch plus its wind. Each weight band picks a different route.",
        {
            "A": (Cell(20, wind=40), Cell(40, rain=0.6, at=0.25)),
            "B": Cell(20, wind=50),
            "C": Cell(60, rain=0.6),
        },
        [
            Trip("25,000 lb", 25_000, "B"),
            Trip("35,000 lb", 35_000, "A"),
            Trip("42,000 lb", 42_000, "C"),
        ],
    ),
    Scenario(
        "7. 55 mph is No Travel for any load",
        "Even an empty trailer may not drive into 58 mph wind, so the slower route is chosen.",
        {"A": Cell(20, wind=58)},
        [Trip("0 lb (empty)", 0, "B"), Trip("5,000 lb", 5_000, "B")],
    ),
    Scenario(
        "8. A few Severe miles outweigh many High miles",
        "A has a short burst of heavy snow (Severe). B has High rain for over 200 miles. "
        "Fewest Severe miles comes before fewest High miles, so B wins.",
        {"A": Cell(15, snow=2.5), "B": Cell(110, rain=0.3), "C": Cell(40, rain=0.6)},
        [Trip("38,000 lb", 38_000, "B")],
    ),
    Scenario(
        "9. The departure time changes the route",
        "A front of 38 mph wind crosses A between 08:00 and 10:00. Leaving at 06:00, a 42,000 lb truck "
        "reaches it at about 08:40 (Severe), so B is chosen. Leaving at 04:00 it is through before the "
        "front arrives, and leaving at 09:00 it arrives after it has gone; either way A is clear.",
        {"A": Cell(20, wind=38, hours=(2, 4)), "B": Cell(40, rain=0.3), "C": Cell(30, wind=48)},
        [
            Trip("42,000 lb, leaves 04:00", 42_000, "A", depart_h=-2),
            Trip("42,000 lb, leaves 06:00", 42_000, "B", depart_h=0),
            Trip("42,000 lb, leaves 09:00", 42_000, "A", depart_h=3),
        ],
    ),
    Scenario(
        "10. Average risk decides when no route has High miles",
        "Only Moderate weather: a breeze on A, light rain on C. No route has High miles, so the lowest "
        "average risk wins, even though A is the fastest.",
        {"A": Cell(20, wind=28), "C": Cell(30, rain=0.15)},
        [Trip("38,000 lb", 38_000, "B")],
    ),
    Scenario(
        "11. Every route has No Travel miles",
        "60 mph wind crosses all three routes. The app still ranks them and warns that every option "
        "crosses No Travel conditions. A and C tie on No Travel miles; A has the lower average risk.",
        {"A": Cell(20, wind=60), "B": Cell(40, wind=60), "C": Cell(30, wind=60)},
        [Trip("20,000 lb", 20_000, "A", all_no_travel=True)],
    ),
]


def nearest_route(lat: float, lon: float) -> str:
    return min(LINES, key=lambda rid: min(geo.haversine_mi((lat, lon), p) for p in LINES[rid]))


def weather_for(cells: dict[str, Cell]):
    def fetch(locations, start, end):
        start_h = weather.floor_hour(start)
        hours = int((end - start_h).total_seconds() // 3600) + 3
        out = []
        for lat, lon in locations:
            wind, rain, snow = [12.0] * hours, [0.0] * hours, [0.0] * hours
            rid = nearest_route(lat, lon)
            here = cells.get(rid, ())
            for cell in here if isinstance(here, tuple) else (here,):
                if geo.haversine_mi((lat, lon), cell.centre(rid)) > cell.radius:
                    continue
                for i in range(hours):
                    at = start_h + timedelta(hours=i)
                    if cell.hours is None or (
                        base.DEPARTURE + timedelta(hours=cell.hours[0])
                        <= at
                        <= base.DEPARTURE + timedelta(hours=cell.hours[1])
                    ):
                        wind[i], rain[i], snow[i] = cell.wind, cell.rain, cell.snow
            out.append(
                HourlySeries(
                    start=start_h, wind_mph=wind, gust_mph=[w + 8 for w in wind], rain_in=rain, snow_in=snow
                )
            )
        return out

    return fetch


def run(scenario: Scenario, trip: Trip) -> dict:
    request = planner.TripRequest(
        origin=base.DENVER,
        destination=base.SALT_LAKE,
        departure=base.DEPARTURE + timedelta(hours=trip.depart_h),
        load_lb=trip.load_lb,
    )
    with (
        mock.patch("routing.services.tomtom.calculate_routes", side_effect=base.fake_calculate),
        mock.patch("routing.services.weather.fetch_hourly", side_effect=weather_for(scenario.weather)),
    ):
        return planner.plan_trip(request)


def summary(analysis: dict) -> str:
    m = analysis["miles_by_level"]
    parts = [
        f"{m[k]:.0f} {name}"
        for k, name in (("no_travel", "NoTr"), ("severe", "Sev"), ("high", "High"))
        if m[k]
    ]
    if not parts and m["moderate"]:
        parts.append(f"{m['moderate']:.0f} Mod")
    return ", ".join(parts) or "clear"


class Command(BaseCommand):
    help = "Trips whose recommendation changes with the weather, the cargo weight or the departure time."

    def handle(self, *args, **options):
        out = self.stdout.write
        out(
            "Denver to Salt Lake City. Route A (I-80) 6 h 21 min, B (US-40) 6 h 41 min, C (US-50) 7 h 54 min."
        )
        out("Departure 06:00 UTC unless stated. Checkpoints every 25 mi. Calm wherever no weather is listed.")
        failed = 0
        for sc in SCENARIOS:
            out("")
            out(sc.title)
            out(f"  {sc.point}")
            for rid in "ABC":
                cells = sc.weather.get(rid, ())
                for cell in cells if isinstance(cells, tuple) else (cells,):
                    out(f"  Weather on {rid}: {cell.describe()}")
            for trip in sc.trips:
                plan = run(sc, trip)
                rec = plan["recommendations"]["25"]
                routes = {r["id"]: r["analyses"]["25"] for r in plan["routes"]}
                ok = rec["route_id"] == trip.expect and rec["all_routes_no_travel"] == trip.all_no_travel
                failed += not ok
                miles = "  ".join(f"{rid}: {summary(routes[rid]):<14}" for rid in "ABC")
                out(f"    {'ok  ' if ok else 'FAIL'} {trip.label:<24} -> Route {rec['route_id']}   {miles}")
                out(
                    f"         {rec['reason']}"
                    + ("  [warning: every route has No Travel miles]" if rec["all_routes_no_travel"] else "")
                )
                if not ok:
                    out(f"         expected Route {trip.expect}, all_no_travel={trip.all_no_travel}")
        total = sum(len(s.trips) for s in SCENARIOS)
        out("")
        out(f"{total - failed} of {total} trips recommended the expected route.")
        if failed:
            raise CommandError(f"{failed} trip(s) did not match.")
