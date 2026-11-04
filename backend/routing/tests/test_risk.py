from django.test import SimpleTestCase

from routing.domain.risk import (
    LOAD_RULE_NO_TRAVEL,
    LOAD_RULE_SEVERE,
    Level,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
)


class ThresholdTests(SimpleTestCase):
    def test_wind_bands(self):
        cases = [
            (0, Level.LOW),
            (24.9, Level.LOW),
            (25, Level.MODERATE),
            (34.9, Level.MODERATE),
            (35, Level.HIGH),
            (44.9, Level.HIGH),
            (45, Level.SEVERE),
            (54.9, Level.SEVERE),
            (55, Level.NO_TRAVEL),
            (80, Level.NO_TRAVEL),
        ]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(classify_wind(mph), expected)

    def test_rain_bands(self):
        cases = [
            (0, Level.LOW),
            (0.09, Level.LOW),
            (0.10, Level.MODERATE),
            (0.24, Level.MODERATE),
            (0.25, Level.HIGH),
            (0.49, Level.HIGH),
            (0.50, Level.SEVERE),
            (1.00, Level.SEVERE),
            (1.01, Level.NO_TRAVEL),
        ]
        for inches, expected in cases:
            with self.subTest(inches=inches):
                self.assertEqual(classify_rain(inches), expected)

    def test_snow_bands(self):
        cases = [
            (0, Level.LOW),
            (0.49, Level.LOW),
            (0.5, Level.MODERATE),
            (0.99, Level.MODERATE),
            (1.0, Level.HIGH),
            (1.99, Level.HIGH),
            (2.0, Level.SEVERE),
            (3.0, Level.SEVERE),
            (3.01, Level.NO_TRAVEL),
        ]
        for inches, expected in cases:
            with self.subTest(inches=inches):
                self.assertEqual(classify_snow(inches), expected)


class LoadRuleTests(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        self.assertEqual(assess(55, 0, 0, 0).level, Level.NO_TRAVEL)
        self.assertIsNone(assess(55, 0, 0, 0).load_rule)

    def test_45_to_54_mph_over_30000_lb_is_no_travel(self):
        a = assess(45, 0, 0, 30_001)
        self.assertEqual(a.level, Level.NO_TRAVEL)
        self.assertEqual(a.load_rule, LOAD_RULE_NO_TRAVEL)
        self.assertEqual(assess(54.9, 0, 0, 45_000).level, Level.NO_TRAVEL)

    def test_45_to_54_mph_at_or_below_30000_lb_stays_severe(self):
        self.assertEqual(assess(50, 0, 0, 30_000).level, Level.SEVERE)

    def test_35_to_44_mph_over_40000_lb_is_severe(self):
        a = assess(35, 0, 0, 40_001)
        self.assertEqual(a.level, Level.SEVERE)
        self.assertEqual(a.load_rule, LOAD_RULE_SEVERE)

    def test_35_to_44_mph_at_or_below_40000_lb_stays_high(self):
        self.assertEqual(assess(44, 0, 0, 40_000).level, Level.HIGH)

    def test_worst_condition_wins_and_drivers_are_reported(self):
        a = assess(30, 0.6, 0.2, 10_000)
        self.assertEqual(a.level, Level.SEVERE)
        self.assertEqual(a.drivers, ("rain",))

    def test_load_rule_dropped_when_another_condition_is_worse(self):
        a = assess(40, 1.5, 0, 45_000)
        self.assertEqual(a.level, Level.NO_TRAVEL)
        self.assertEqual(a.drivers, ("rain",))
        self.assertIsNone(a.load_rule)

    def test_calm_weather_has_no_drivers(self):
        self.assertEqual(assess(5, 0, 0, 40_000).drivers, ())
