from datetime import UTC, datetime

from django.test import SimpleTestCase

from routing.services.weather import HourlySeries, _parse

T0 = datetime(2026, 11, 5, 12, tzinfo=UTC)


class HourlySeriesTests(SimpleTestCase):
    def setUp(self):
        self.series = HourlySeries(
            start=T0,
            wind_mph=[10.0, 20.0, 30.0],
            gust_mph=[15.0, 25.0, 35.0],
            rain_in=[0.0, 0.2, 0.4],
            snow_in=[0.0, 0.0, 1.0],
        )

    def test_wind_interpolates_between_hours(self):
        s = self.series.at(datetime(2026, 11, 5, 12, 30, tzinfo=UTC))
        self.assertEqual(s.wind_mph, 15.0)

    def test_precipitation_uses_hour_ending_after_eta(self):
        s = self.series.at(datetime(2026, 11, 5, 13, 10, tzinfo=UTC))
        self.assertEqual(s.rain_in, 0.4)
        self.assertEqual(s.snow_in, 1.0)

    def test_outside_range_returns_none(self):
        self.assertIsNone(self.series.at(datetime(2026, 11, 5, 15, tzinfo=UTC)))


class ParseTests(SimpleTestCase):
    def test_converts_units_and_adds_showers_to_rain(self):
        series = _parse(
            {
                "hourly": {
                    "time": ["2026-11-05T12:00"],
                    "wind_speed_10m": [12.0],
                    "wind_gusts_10m": [20.0],
                    "rain": [2.54],
                    "showers": [2.54],
                    "snowfall": [2.54],
                }
            }
        )
        self.assertEqual(series.start, T0)
        self.assertAlmostEqual(series.rain_in[0], 0.2)
        self.assertAlmostEqual(series.snow_in[0], 1.0)
