"""End-to-end check against the real TomTom and Open-Meteo APIs.

    python manage.py smoke_test                      # in-process, uses TOMTOM_API_KEY from .env
    python manage.py smoke_test --url https://api... # against a deployed API

Exits non-zero if any step fails, so it can gate a release.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import requests
from django.core.management.base import BaseCommand, CommandError

from ...services import heatmap, planner, tomtom

ORIGIN = (39.7392, -104.9903)  # Denver, CO
DESTINATION = (40.7608, -111.8910)  # Salt Lake City, UT
LOAD_LB = 38_000


class Command(BaseCommand):
    help = "Plan a real trip (Denver to Salt Lake City) and check every part of the response."

    def add_arguments(self, parser):
        parser.add_argument("--url", help="Base URL of a deployed API. Omit to run in-process.")

    def handle(self, *args, **options):
        self.failures: list[str] = []
        departure = (datetime.now(UTC) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        if options["url"]:
            self._run_http(options["url"].rstrip("/"), departure)
        else:
            self._run_local(departure)
        if self.failures:
            raise CommandError(f"{len(self.failures)} check(s) failed: " + "; ".join(self.failures))
        self.stdout.write(self.style.SUCCESS("All smoke checks passed."))

    # Runners ---------------------------------------------------------------------------

    def _run_local(self, departure: datetime) -> None:
        places = self._step("place search", lambda: tomtom.search_places("Denver"))
        self._check("place search returns results", bool(places))
        plan = self._step(
            "plan trip",
            lambda: planner.plan_trip(planner.TripRequest(ORIGIN, DESTINATION, departure, LOAD_LB)),
        )
        if plan:
            self._check_plan(plan, departure)
            paths = [[(lat, lon) for lon, lat in r["coordinates"]] for r in plan["routes"]]
            hm = self._step("corridor forecast", lambda: heatmap.corridor_heatmap(paths, departure, LOAD_LB))
            if hm:
                self._check_heatmap(hm)

    def _run_http(self, base: str, departure: datetime) -> None:
        health = self._step("health", lambda: self._get(f"{base}/api/health"))
        self._check("health is ok", health and health.get("status") == "ok")
        places = self._step("place search", lambda: self._get(f"{base}/api/places", {"q": "Denver"}))
        self._check("place search returns results", places and places.get("results"))
        body = {
            "origin": {"lat": ORIGIN[0], "lon": ORIGIN[1]},
            "destination": {"lat": DESTINATION[0], "lon": DESTINATION[1]},
            "departure": departure.isoformat(),
            "load_lb": LOAD_LB,
        }
        plan = self._step("plan trip", lambda: self._post(f"{base}/api/plan", body))
        if plan:
            self._check_plan(plan, departure)
            paths = [r["coordinates"][:: max(1, len(r["coordinates"]) // 1500)] for r in plan["routes"]]
            hm_body = {"paths": paths, "departure": departure.isoformat(), "load_lb": LOAD_LB}
            hm = self._step("corridor forecast", lambda: self._post(f"{base}/api/heatmap", hm_body))
            if hm:
                self._check_heatmap(hm)

    # Checks ----------------------------------------------------------------------------

    def _check_plan(self, plan: dict, departure: datetime) -> None:
        routes = plan["routes"]
        self._check("one to three routes", 1 <= len(routes) <= 3, f"{len(routes)} routes")
        self._check(
            "routes sorted fastest first",
            [r["duration_s"] for r in routes] == sorted(r["duration_s"] for r in routes),
        )
        self._check("25 and 50 mile spacings present", {"25", "50"} <= set(plan["intervals"]))
        for route in routes:
            label = route["label"]
            self._check(f"{label} has geometry", len(route["coordinates"]) >= 2)
            self._check(
                f"{label} distance plausible", 300 < route["distance_mi"] < 900, f"{route['distance_mi']} mi"
            )
            for interval in plan["intervals"]:
                cps = route["analyses"][interval]["checkpoints"]
                etas = [datetime.fromisoformat(c["eta"].replace("Z", "+00:00")) for c in cps]
                self._check(
                    f"{label} {interval} mi starts at departure",
                    abs((etas[0] - departure).total_seconds()) < 60,
                )
                self._check(f"{label} {interval} mi ETAs increase", etas == sorted(etas))
                known = sum(c["level"] is not None for c in cps)
                self._check(
                    f"{label} {interval} mi forecast coverage",
                    known == len(cps),
                    f"{known}/{len(cps)} checkpoints have a forecast",
                )
        for interval, rec in plan["recommendations"].items():
            self._check(
                f"recommendation for {interval} mi",
                rec["route_id"] in {r["id"] for r in routes} and rec["reason"],
            )
        rec = plan["recommendations"]["25"]
        best = next(r for r in routes if r["id"] == rec["route_id"])
        miles = best["analyses"]["25"]["miles_by_level"]
        self.stdout.write(
            f"  Recommended {best['label']} via {best['via'] or 'n/a'}: {best['distance_mi']} mi, "
            f"{best['duration_s'] / 3600:.1f} h, severe {miles['severe']} mi, high {miles['high']} mi. "
            f"{rec['reason']}"
        )

    def _check_heatmap(self, hm: dict) -> None:
        self._check("forecast covers 49 hours", len(hm["times"]) == 49)
        self._check("forecast grid has cells", 0 < len(hm["cells"]) <= 240, f"{len(hm['cells'])} cells")
        filled = sum(v is not None for row in hm["values"]["wind"] for v in row)
        total = len(hm["cells"]) * len(hm["times"])
        self._check("forecast values present", filled >= total * 0.95, f"{filled}/{total}")

    # Helpers ---------------------------------------------------------------------------

    def _step(self, name, fn):
        started = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - report any failure as a failed step
            self._report(False, name, str(exc))
            return None
        self._report(True, name, f"{(time.perf_counter() - started) * 1000:.0f} ms")
        return result

    def _check(self, name, ok, detail=""):
        self._report(bool(ok), name, detail if not ok else "")

    def _report(self, ok, name, detail):
        if not ok:
            self.failures.append(name)
        mark = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
        self.stdout.write(f"{mark} {name}" + (f"  ({detail})" if detail else ""))

    def _get(self, url, params=None):
        resp = requests.get(url, params=params, timeout=90)
        return self._json(resp)

    def _post(self, url, body):
        resp = requests.post(url, json=body, timeout=90)
        return self._json(resp)

    @staticmethod
    def _json(resp):
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()
