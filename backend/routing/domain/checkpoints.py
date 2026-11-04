"""Checkpoint placement and mileage attribution along a route."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .risk import Level

INTERVALS_MI = (10, 25, 50)


def checkpoint_miles(total_mi: float, interval_mi: float) -> list[float]:
    """Mile markers at 0, interval, 2 x interval, ... plus the destination."""
    if total_mi <= 0:
        return [0.0]
    miles: list[float] = []
    k = 0
    while k * interval_mi < total_mi - 1e-6:
        miles.append(round(k * interval_mi, 6))
        k += 1
    miles.append(round(total_mi, 6))
    return miles


def owned_spans(miles: Sequence[float]) -> list[tuple[float, float]]:
    """Each checkpoint represents the stretch of road nearer to it than to its neighbours."""
    if len(miles) == 1:
        return [(miles[0], miles[0])]
    spans = []
    for i, m in enumerate(miles):
        start = miles[0] if i == 0 else (miles[i - 1] + m) / 2
        end = miles[-1] if i == len(miles) - 1 else (m + miles[i + 1]) / 2
        spans.append((start, end))
    return spans


def summarize(levels: Sequence[Level | None], spans: Sequence[tuple[float, float]]) -> dict:
    """Miles per level and the mileage-weighted average risk (0 = Low ... 4 = No Travel)."""
    by_level = {lvl.key: 0.0 for lvl in Level}
    by_level["unknown"] = 0.0
    weighted, known = 0.0, 0.0
    for lvl, (start, end) in zip(levels, spans, strict=False):
        length = end - start
        if lvl is None:
            by_level["unknown"] += length
            continue
        by_level[lvl.key] += length
        weighted += int(lvl) * length
        known += length
    return {
        "miles_by_level": {k: round(v, 2) for k, v in by_level.items()},
        "avg_risk": round(weighted / known, 3) if known > 0 else None,
    }


def merged_segments(levels: Iterable[Level | None], spans: Iterable[tuple[float, float]]) -> list[list]:
    """Consecutive spans sharing a level, as [from_mi, to_mi, level_key]."""
    out: list[list] = []
    for lvl, (start, end) in zip(levels, spans, strict=False):
        key = lvl.key if lvl is not None else None
        if end <= start:
            continue
        if out and out[-1][2] == key and abs(out[-1][1] - round(start, 3)) < 1e-3:
            out[-1][1] = round(end, 3)
        else:
            out.append([round(start, 3), round(end, 3), key])
    return out
