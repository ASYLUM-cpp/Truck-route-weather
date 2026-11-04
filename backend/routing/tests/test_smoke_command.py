from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from routing.services import tomtom
from routing.tests.test_api import fake_route, fake_weather

DENVER, SLC = (39.7392, -104.9903), (40.7608, -111.891)


def calc(locations, *args, **kwargs):
    if len(locations) == 3:
        return []
    return [fake_route([DENVER, (41.3, -106.0), SLC]), fake_route([DENVER, (39.6, -108.5), SLC], mph=50)]


@override_settings(TOMTOM_API_KEY="test")
class SmokeCommandTests(SimpleTestCase):
    @mock.patch("routing.services.weather.fetch_hourly", side_effect=fake_weather)
    @mock.patch("routing.services.tomtom.calculate_routes", side_effect=calc)
    @mock.patch("routing.services.tomtom.search_places", return_value=[{"label": "Denver, CO"}])
    def test_in_process_run_passes(self, *_):
        out = StringIO()
        call_command("smoke_test", stdout=out)
        self.assertIn("All smoke checks passed.", out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())

    @mock.patch("routing.services.tomtom.search_places", return_value=[])
    @mock.patch("routing.services.tomtom.calculate_routes", side_effect=tomtom.TomTomError("bad key"))
    def test_failures_exit_non_zero(self, *_):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("smoke_test", stdout=out, no_color=True)
        self.assertIn("FAIL plan trip  (bad key)", out.getvalue())
