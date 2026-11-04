from django.test import SimpleTestCase

from routing.domain import geo


class GeoTests(SimpleTestCase):
    def test_haversine_known_distance(self):
        chicago, denver = (41.8781, -87.6298), (39.7392, -104.9903)
        self.assertAlmostEqual(geo.haversine_mi(chicago, denver), 920, delta=5)

    def test_point_at_mile_interpolates(self):
        pts = [(0.0, 0.0), (0.0, 1.0)]
        cum = geo.cumulative_miles(pts)
        mid = geo.point_at_mile(pts, cum, cum[-1] / 2)
        self.assertAlmostEqual(mid[1], 0.5, places=6)

    def test_time_profile_interpolates_and_inverts(self):
        profile = geo.TimeProfile([(0, 0), (10, 600), (30, 1800)])
        self.assertEqual(profile.seconds_at(20), 1200)
        self.assertEqual(profile.miles_at(300), 5)
        self.assertEqual(profile.seconds_at(99), 1800)

    def test_time_profile_ignores_non_monotonic_points(self):
        profile = geo.TimeProfile([(0, 0), (10, 600), (10, 500), (20, 550), (30, 1800)])
        self.assertEqual(profile.total_seconds, 1800)

    def test_simplify_keeps_endpoints_and_corners(self):
        pts = [(0, 0), (0, 0.5), (0, 1), (1, 1)]
        self.assertEqual(geo.simplify_indices(pts, 0.001), [0, 2, 3])

    def test_overlap_ratio(self):
        a = [(40.0, -100.0), (40.0, -99.0)]
        far = [(41.0, -100.0), (41.0, -99.0)]
        self.assertGreater(geo.overlap_ratio(a, a), 0.99)
        self.assertLess(geo.overlap_ratio(a, far), 0.01)
