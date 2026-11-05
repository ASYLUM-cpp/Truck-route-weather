"""Prove the risk rules, load rules and recommendation logic on a controlled scenario.

Runs offline: TomTom and Open-Meteo are replaced by fixed data, everything else is the real code path
(`plan_trip`, `assess`, checkpoint attribution, ranking). Exits non-zero if any check fails.

    python manage.py prove_rules
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

from django.core.management.base import BaseCommand, CommandError

from routing.domain import geo
from routing.domain.risk import assess
from routing.services import planner, tomtom, weather
from routing.services.weather import HourlySeries

DENVER = (39.7392, -104.9903)
SALT_LAKE = (40.7608, -111.8910)
DEPARTURE = datetime(2026, 11, 6, 6, 0, tzinfo=UTC)

# Three distinct truck routes, fastest to slowest.
ROUTES = {
    "A": {"via": (41.60, -107.50), "mph": 66.0, "road": "I-80"},  # northern, fastest
    "B": {"via": (40.55, -107.50), "mph": 56.0, "road": "US-40"},  # middle
    "C": {"via": (39.20, -107.50), "mph": 50.0, "road": "US-50"},  # southern, slowest
}

# Weather cells: (centre, radius in miles). Everything outside a cell is calm: 12 mph wind, no rain or snow.
STORM_A = ((41.60, -107.50), 20)  # a front: wind 38 mph between STORM_A_STARTS and STORM_A_ENDS
STORM_A_WIND = 38.0
STORM_A_STARTS = DEPARTURE + timedelta(hours=2)  # 08:00 UTC
STORM_A_ENDS = DEPARTURE + timedelta(hours=4)  # 10:00 UTC
RAIN_B = ((40.55, -107.50), 40)  # rain 0.30 in/hr all day (High)
RAIN_B_RATE = 0.30
GALE_C = ((39.20, -107.50), 30)  # wind 48 mph all day

# Expected overall level for wind speed x cargo weight, written out by hand from the assessment's tables.
# Columns: 28,000  30,000  30,001  40,000  40,001 lb.
LOADS = (28_000, 30_000, 30_001, 40_000, 40_001)
WIND_LADDER = {
    24.9: "low low low low low",
    25.0: "moderate moderate moderate moderate moderate",
    34.9: "moderate moderate moderate moderate moderate",
    35.0: "high high high high severe",
    44.9: "high high high high severe",
    45.0: "severe severe no_travel no_travel no_travel",
    54.9: "severe severe no_travel no_travel no_travel",
    55.0: "no_travel no_travel no_travel no_travel no_travel",
}
RAIN_LADDER = {
    0.099: "low", 0.10: "moderate", 0.249: "moderate", 0.25: "high",
    0.499: "high", 0.50: "severe", 1.00: "severe", 1.001: "no_travel",
}  # fmt: skip
SNOW_LADDER = {
    0.49: "low", 0.5: "moderate", 0.99: "moderate", 1.0: "high",
    1.99: "high", 2.0: "severe", 3.0: "severe", 3.01: "no_travel",
}  # fmt: skip


def _in(cell, lat, lon) -> bool:
    (clat, clon), radius = cell
    return geo.haversine_mi((lat, lon), (clat, clon)) <= radius


def fake_calculate(locations, depart_at, gross_weight_kg, max_alternatives=0):
    out = []
    for spec in ROUTES.values():
        pts = geo.densify([DENVER, spec["via"], SALT_LAKE], 2.0)
        length = geo.cumulative_miles(pts)[-1]
        secs = length / spec["mph"] * 3600
        out.append(
            tomtom.RawRoute(
                points=pts,
                length_mi=length,
                travel_time_s=secs,
                traffic_delay_s=0,
                time_profile=[(0, 0), (length, secs)],
                road_miles={spec["road"]: length},
                road_order=[spec["road"]],
            )
        )
    return out


def fake_weather(locations, start, end, mode="storm"):
    start_h = weather.floor_hour(start)
    hours = int((end - start_h).total_seconds() // 3600) + 3
    series = []
    for lat, lon in locations:
        wind = [12.0] * hours
        rain = [0.0] * hours
        if mode == "breeze":
            # Only a 28 mph breeze (Moderate) on the fastest route. No High, Severe or No Travel anywhere.
            if _in(STORM_A, lat, lon):
                wind = [28.0] * hours
        elif _in(STORM_A, lat, lon):
            wind = [
                STORM_A_WIND if STORM_A_STARTS <= start_h + timedelta(hours=i) <= STORM_A_ENDS else 12.0
                for i in range(hours)
            ]
        if mode == "storm" and _in(RAIN_B, lat, lon):
            rain = [RAIN_B_RATE] * hours
        if mode == "storm" and _in(GALE_C, lat, lon):
            wind = [48.0] * hours
        series.append(
            HourlySeries(
                start=start_h,
                wind_mph=wind,
                gust_mph=[w + 8 for w in wind],
                rain_in=rain,
                snow_in=[0.0] * hours,
            )
        )
    return series


class Report:
    def __init__(self, out):
        self.out, self.failed, self.total = out, 0, 0

    def line(self, text=""):
        self.out.write(text)

    def check(self, name: str, ok: bool, detail: str = ""):
        self.total += 1
        self.failed += 0 if ok else 1
        self.out.write(
            f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else "")
        )


class Command(BaseCommand):
    help = "Prove the risk rules, load rules and recommendation logic on a controlled scenario."

    def handle(self, *args, **options):
        r = Report(self.stdout)
        self.part_one(r)
        self.part_two(r)
        r.line("")
        r.line(f"{r.total - r.failed} of {r.total} checks passed.")
        if r.failed:
            raise CommandError(f"{r.failed} check(s) failed.")
        r.line("ALL CHECKS PASSED")

    # -- Part 1 ---------------------------------------------------------------------------------------------

    def part_one(self, r: Report):
        r.line("PART 1  Rule tables, edge by edge (the real `assess` function)")
        r.line("")
        r.line("  Wind (mph) x cargo (lb) -> overall level")
        r.line("  " + f"{'wind':>6}  " + "  ".join(f"{lb:>9,}" for lb in LOADS))
        for wind, expected in WIND_LADDER.items():
            got = [assess(wind, 0, 0, lb).level.key for lb in LOADS]
            cells = "  ".join(f"{g:>9}" for g in got)
            r.line(f"  {wind:>6}  {cells}")
            r.check(f"wind {wind} mph across the five loads", got == expected.split(), f"got {got}")

        r.line("")
        rain = {x: assess(0, x, 0, 0).level.key for x in RAIN_LADDER}
        r.check(
            "rain edges 0.099 / 0.10 / 0.249 / 0.25 / 0.499 / 0.50 / 1.00 / 1.001 in/hr", rain == RAIN_LADDER
        )
        snow = {x: assess(0, 0, x, 0).level.key for x in SNOW_LADDER}
        r.check("snow edges 0.49 / 0.5 / 0.99 / 1.0 / 1.99 / 2.0 / 3.0 / 3.01 in/hr", snow == SNOW_LADDER)

        mixed = assess(30, 0.30, 0, 10_000)
        r.check(
            "worst condition wins: wind 30 (Moderate) + rain 0.30 (High) = High, driven by rain",
            mixed.level.key == "high" and mixed.drivers == ("rain",),
        )
        quiet = assess(40, 0.60, 0, 50_000)
        r.check(
            "load rule raises wind to Severe, rain 0.60 is also Severe: both are named as drivers",
            quiet.level.key == "severe" and set(quiet.drivers) == {"wind", "rain"},
        )
        masked = assess(40, 1.5, 0, 50_000)
        r.check(
            "when rain is No Travel it outranks the load rule, which is then not credited",
            masked.level.key == "no_travel" and masked.load_rule is None and masked.drivers == ("rain",),
        )

    # -- Part 2 ---------------------------------------------------------------------------------------------

    def run_trip(self, load_lb: float, departure: datetime, mode: str = "storm") -> dict:
        trip = planner.TripRequest(origin=DENVER, destination=SALT_LAKE, departure=departure, load_lb=load_lb)
        with (
            mock.patch("routing.services.tomtom.calculate_routes", side_effect=fake_calculate),
            mock.patch(
                "routing.services.weather.fetch_hourly",
                side_effect=lambda locs, start, end: fake_weather(locs, start, end, mode),
            ),
        ):
            plan = planner.plan_trip(trip)
        # The planner labels routes by travel time. The scenario depends on A being the northern route, so
        # fail loudly if the labels ever stop matching the intended roads.
        roads = [route["via"] for route in plan["routes"]]
        if roads != [spec["road"] for spec in ROUTES.values()]:
            raise CommandError(f"Route labels do not match the scenario's roads: {roads}")
        return plan

    def show(self, r: Report, title: str, plan: dict) -> tuple[dict, dict]:
        rec = plan["recommendations"]["25"]
        r.line("")
        r.line(f"  {title}")
        r.line(f"  {'':14}{'time':>6}{'Low':>6}{'Mod':>6}{'High':>6}{'Sev':>6}{'NoTr':>6}{'avg':>7}")
        for route in plan["routes"]:
            m = route["analyses"]["25"]["miles_by_level"]
            h, mins = divmod(round(route["duration_s"] / 60), 60)
            name = f"{route['label']} {route['via']}"
            star = "  <- recommended" if route["id"] == rec["route_id"] else ""
            r.line(
                f"  {name:14}{f'{h}h{mins:02d}':>6}{m['low']:>6.0f}{m['moderate']:>6.0f}"
                f"{m['high']:>6.0f}{m['severe']:>6.0f}{m['no_travel']:>6.0f}"
                f"{route['analyses']['25']['avg_risk']:>7.2f}{star}"
            )
        r.line(f"  Ranking: {' > '.join(rec['ranking'])}.  Reason: {rec['reason']}")
        return {rt["id"]: rt["analyses"]["25"] for rt in plan["routes"]}, rec

    def part_two(self, r: Report):
        r.line("")
        r.line("PART 2  Denver to Salt Lake City, one weather picture, three trucks (25-mile checkpoints)")
        r.line("")
        r.line(
            "  Weather: Route A (I-80, north) meets a front of 38 mph wind, only between 08:00 and 10:00 UTC."
        )
        r.line(
            "           Route B (US-40, middle) meets rain at 0.30 in/hr (High) over a wider area, all day."
        )
        r.line("           Route C (US-50, south) meets 48 mph wind in its middle, all day. Elsewhere: calm.")
        r.line(
            f"  Departure: {DEPARTURE:%a %d %b %H:%M} UTC. Calm at the start; "
            "Route A reaches the front about 08:40."
        )

        light, light_rec = self.show(
            r, "1) Light truck, 28,000 lb, departs 06:00", self.run_trip(28_000, DEPARTURE)
        )
        heavy, heavy_rec = self.show(
            r, "2) Heavy truck, 42,000 lb, same weather, same departure", self.run_trip(42_000, DEPARTURE)
        )
        later, later_rec = self.show(
            r,
            "3) Heavy truck, 42,000 lb, leaves at 09:00 and reaches the front only after it has gone",
            self.run_trip(42_000, DEPARTURE + timedelta(hours=3)),
        )

        breeze, breeze_rec = self.show(
            r,
            "4) Heavy truck, calm day: only a 28 mph breeze (Moderate) on Route A",
            self.run_trip(42_000, DEPARTURE, mode="breeze"),
        )

        r.line("")
        r.line("  Checkpoints where a load rule fired for the 42,000 lb truck:")
        for rid, a in heavy.items():
            for cp in a["checkpoints"]:
                if cp["load_rule"]:
                    r.line(
                        f"    Route {rid}  mile {cp['mile']:>5.0f}  {cp['eta'][11:16]}Z"
                        f"  wind {cp['wind_mph']:.0f} mph"
                        f"  ->  {cp['level']:<9}  rule {cp['load_rule']}"
                    )
        r.line("")

        def miles(analysis, level):
            return analysis["miles_by_level"][level]

        # The light truck: the load rules do not apply, so the table alone decides.
        r.check(
            "28,000 lb: Route A's 38 mph is High, not Severe",
            miles(light["A"], "high") > 0 and miles(light["A"], "severe") == 0,
        )
        r.check(
            "28,000 lb: Route C's 48 mph is Severe (45-54 mph), not No Travel (needs more than 30,000 lb)",
            miles(light["C"], "severe") > 0 and miles(light["C"], "no_travel") == 0,
        )
        r.check(
            "28,000 lb: Route B is High from rain alone",
            miles(light["B"], "high") > 0 and miles(light["B"], "severe") == 0,
        )
        r.check(
            "28,000 lb: recommends A, the fastest, because its High miles are fewest and nothing is Severe",
            light_rec["ranking"] == ["A", "B", "C"] and "High" in light_rec["reason"],
            f"ranking {light_rec['ranking']}",
        )

        # The heavy truck: same weather, load rules apply.
        r.check(
            "42,000 lb: Route A's 38 mph becomes Severe (35-44 mph with more than 40,000 lb)",
            miles(heavy["A"], "severe") > 0 and miles(heavy["A"], "high") == 0,
        )
        r.check(
            "42,000 lb: Route C's 48 mph becomes No Travel (45-54 mph with more than 30,000 lb)",
            miles(heavy["C"], "no_travel") > 0 and miles(heavy["C"], "severe") == 0,
        )
        r.check(
            "42,000 lb: rain on Route B is unchanged by the load (load rules only touch wind)",
            miles(heavy["B"], "high") == miles(light["B"], "high") and miles(heavy["B"], "severe") == 0,
        )
        r.check(
            "42,000 lb: the recommendation changes to B. A is now Severe and C is No Travel, ranked last",
            heavy_rec["ranking"] == ["B", "A", "C"] and heavy_rec["reason"].startswith("No Severe miles"),
            f"ranking {heavy_rec['ranking']}, reason {heavy_rec['reason']}",
        )
        r.check(
            "42,000 lb: No Travel ranks before Severe (C is last despite fewer Severe miles than A)",
            miles(heavy["C"], "severe") < miles(heavy["A"], "severe") and heavy_rec["ranking"][-1] == "C",
        )
        rules = {
            cp["load_rule"] for a in (heavy["A"], heavy["C"]) for cp in a["checkpoints"] if cp["load_rule"]
        }
        r.check(
            "both load rules are reported on the checkpoints that triggered them",
            rules == {"wind_35_load_40000", "wind_45_load_30000"},
        )
        r.check(
            "the light truck had no load rule on any checkpoint",
            not any(cp["load_rule"] for a in light.values() for cp in a["checkpoints"]),
        )

        # Time: the same route, a different hour, a different answer.
        r.check(
            "leaving at 09:00, the truck meets A's front after it has gone: A is clear (read at ETA)",
            miles(later["A"], "low") > 0
            and miles(later["A"], "severe") == 0
            and miles(later["A"], "high") == 0,
        )
        r.check(
            "the heavy truck is recommended Route A again once it avoids the storm",
            later_rec["route_id"] == "A" and later_rec["ranking"] == ["A", "B", "C"],
            f"ranking {later_rec['ranking']}",
        )
        r.check(
            "calm day: no route has High, Severe or No Travel miles, so the first three criteria tie",
            all(miles(a, lvl) == 0 for a in breeze.values() for lvl in ("high", "severe", "no_travel")),
        )
        r.check(
            "calm day, criterion 4: A is the fastest but has the highest average risk, so it ranks last",
            breeze_rec["ranking"][-1] == "A" and breeze["A"]["avg_risk"] > breeze["B"]["avg_risk"],
            f"ranking {breeze_rec['ranking']}",
        )
        r.check(
            "calm day, criterion 5: B and C have equal risk, so the shorter trip (B) is preferred",
            breeze["B"]["avg_risk"] == breeze["C"]["avg_risk"] and breeze_rec["ranking"] == ["B", "C", "A"],
            f"ranking {breeze_rec['ranking']}, reason {breeze_rec['reason']}",
        )
        r.check(
            "Route B and C are unchanged by the later start (their weather is not time-limited)",
            miles(later["B"], "high") == miles(heavy["B"], "high")
            and miles(later["C"], "no_travel") == miles(heavy["C"], "no_travel"),
        )
