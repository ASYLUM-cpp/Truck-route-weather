"""Route ranking.

Order of preference: fewest No Travel miles, fewest Severe miles, fewest High
miles, lowest average risk, shortest travel time. The last four are the
assessment's list; No Travel is ranked first because a No Travel mile is
strictly worse than a Severe one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteScore:
    route_id: str
    label: str
    no_travel_mi: float
    severe_mi: float
    high_mi: float
    avg_risk: float | None
    duration_s: float

    def sort_key(self) -> tuple:
        avg = math.inf if self.avg_risk is None else round(self.avg_risk, 2)
        return (
            round(self.no_travel_mi, 1),
            round(self.severe_mi, 1),
            round(self.high_mi, 1),
            avg,
            round(self.duration_s / 60),  # whole minutes; seconds are below routing accuracy
        )


def rank(scores: list[RouteScore]) -> list[RouteScore]:
    return sorted(scores, key=RouteScore.sort_key)


def recommend(scores: list[RouteScore]) -> dict:
    ordered = rank(scores)
    best = ordered[0]
    return {
        "route_id": best.route_id,
        "ranking": [s.route_id for s in ordered],
        "reason": explain(best, ordered[1] if len(ordered) > 1 else None),
        "all_routes_no_travel": round(best.no_travel_mi, 1) > 0,
    }


def explain(best: RouteScore, runner_up: RouteScore | None) -> str:
    if runner_up is None:
        return "This is the only distinct route for this trip without long detours."
    b, r = best.sort_key(), runner_up.sort_key()
    other = runner_up.label

    for idx, name in ((0, "No Travel"), (1, "Severe"), (2, "High")):
        if b[idx] != r[idx]:
            if b[idx] == 0:
                return f"No {name} miles. {other} has {fmt_miles(r[idx])} in {name} conditions."
            return f"Fewest {name} miles: {fmt_miles(b[idx])}, against {fmt_miles(r[idx])} on {other}."
    if b[3] != r[3]:
        return f"Lowest average risk: {b[3]:.2f}, against {r[3]:.2f} on {other}."
    if b[4] != r[4]:
        return f"Same weather risk as {other}, and {fmt_duration((r[4] - b[4]) * 60)} faster."
    return f"Same weather risk and travel time as {other}."


def fmt_miles(mi: float) -> str:
    return f"{mi:.0f} mi" if mi >= 10 else f"{mi:.1f} mi"


def fmt_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    hours, mins = divmod(minutes, 60)
    if hours == 0:
        return f"{mins} min"
    return f"{hours} h {mins:02d} min"
