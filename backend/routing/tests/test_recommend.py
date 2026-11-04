from django.test import SimpleTestCase

from routing.domain.recommend import RouteScore, recommend


def score(rid, nt=0.0, sev=0.0, high=0.0, avg=0.0, dur=3600):
    return RouteScore(rid, f"Route {rid}", nt, sev, high, avg, dur)


class RecommendationTests(SimpleTestCase):
    def test_fewest_severe_miles_beats_faster_route(self):
        result = recommend([score("A", sev=20, dur=3600), score("B", sev=0, dur=7200)])
        self.assertEqual(result["route_id"], "B")
        self.assertIn("No Severe miles", result["reason"])

    def test_high_miles_break_severe_tie(self):
        result = recommend([score("A", high=30), score("B", high=12)])
        self.assertEqual(result["route_id"], "B")
        self.assertIn("Fewest High miles", result["reason"])

    def test_average_risk_breaks_mileage_tie(self):
        result = recommend([score("A", avg=0.8), score("B", avg=0.3)])
        self.assertEqual(result["route_id"], "B")
        self.assertIn("Lowest average risk", result["reason"])

    def test_travel_time_is_last_tiebreaker(self):
        result = recommend([score("A", dur=5000), score("B", dur=4000)])
        self.assertEqual(result["route_id"], "B")
        self.assertIn("faster", result["reason"])

    def test_seconds_apart_counts_as_same_travel_time(self):
        result = recommend([score("A", dur=4000), score("B", dur=4010)])
        self.assertEqual(result["reason"], "Same weather risk and travel time as Route B.")

    def test_no_travel_ranks_before_severe(self):
        result = recommend([score("A", nt=5, sev=0), score("B", nt=0, sev=40)])
        self.assertEqual(result["route_id"], "B")
        self.assertFalse(result["all_routes_no_travel"])

    def test_flags_when_every_route_has_no_travel(self):
        result = recommend([score("A", nt=5), score("B", nt=9)])
        self.assertTrue(result["all_routes_no_travel"])

    def test_ranking_lists_every_route(self):
        result = recommend([score("A", sev=3), score("B"), score("C", high=4)])
        self.assertEqual(result["ranking"], ["B", "C", "A"])

    def test_single_route(self):
        result = recommend([score("A")])
        self.assertEqual(result["route_id"], "A")
        self.assertIn("only distinct route", result["reason"])
