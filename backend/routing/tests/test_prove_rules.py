from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase


class ProveRulesTests(SimpleTestCase):
    """Keeps the rules scenario honest: if a threshold, load rule, ranking step or ETA lookup changes, CI fails."""

    def test_scenario_passes(self):
        out = StringIO()
        call_command("prove_rules", stdout=out)
        text = out.getvalue()
        self.assertNotIn("FAIL", text)
        self.assertIn("ALL CHECKS PASSED", text)
        # Both load rules and all five ranking criteria are exercised, not just the first few.
        self.assertIn("wind_35_load_40000", text)
        self.assertIn("wind_45_load_30000", text)
        self.assertIn("criterion 4", text)
        self.assertIn("criterion 5", text)


class ScenarioCatalogueTests(SimpleTestCase):
    """Every trip in `manage.py scenarios` must still get the route the catalogue promises."""

    def test_all_trips_match(self):
        out = StringIO()
        call_command("scenarios", stdout=out)
        text = out.getvalue()
        self.assertNotIn("FAIL", text)
        self.assertIn("20 of 20 trips recommended the expected route.", text)
