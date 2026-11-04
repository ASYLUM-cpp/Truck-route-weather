from django.test import SimpleTestCase

from routing.domain.checkpoints import checkpoint_miles, merged_segments, owned_spans, summarize
from routing.domain.risk import Level


class CheckpointMilesTests(SimpleTestCase):
    def test_includes_origin_and_destination(self):
        self.assertEqual(checkpoint_miles(57, 25), [0, 25, 50, 57])

    def test_exact_multiple_does_not_duplicate_destination(self):
        self.assertEqual(checkpoint_miles(50, 25), [0, 25, 50])

    def test_route_shorter_than_interval(self):
        self.assertEqual(checkpoint_miles(8, 10), [0, 8])


class AttributionTests(SimpleTestCase):
    def test_spans_cover_route_exactly_once(self):
        miles = [0, 25, 50, 57]
        spans = owned_spans(miles)
        self.assertEqual(spans, [(0, 12.5), (12.5, 37.5), (37.5, 53.5), (53.5, 57)])
        self.assertAlmostEqual(sum(e - s for s, e in spans), 57)

    def test_summary_weights_by_miles(self):
        spans = owned_spans([0, 25, 50, 57])
        levels = [Level.LOW, Level.HIGH, Level.SEVERE, None]
        result = summarize(levels, spans)
        self.assertEqual(result["miles_by_level"]["high"], 25)
        self.assertEqual(result["miles_by_level"]["severe"], 16)
        self.assertEqual(result["miles_by_level"]["unknown"], 3.5)
        expected = (0 * 12.5 + 2 * 25 + 3 * 16) / 53.5
        self.assertAlmostEqual(result["avg_risk"], expected, places=3)

    def test_segments_merge_adjacent_levels(self):
        spans = owned_spans([0, 10, 20, 30])
        levels = [Level.LOW, Level.LOW, Level.HIGH, Level.HIGH]
        self.assertEqual(merged_segments(levels, spans), [[0, 15, "low"], [15, 30, "high"]])
