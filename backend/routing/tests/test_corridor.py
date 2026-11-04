from django.test import SimpleTestCase

from routing.domain.corridor import build_corridor_grid
from routing.domain.geo import haversine_mi


class CorridorGridTests(SimpleTestCase):
    def test_grid_respects_cell_budget_and_follows_route(self):
        path = [(41.88, -87.63), (41.25, -95.93), (39.74, -104.99)]
        grid = build_corridor_grid([path], max_cells=240)
        self.assertLessEqual(len(grid.cells), 240)
        self.assertGreater(len(grid.cells), 50)
        self.assertEqual(len(grid.cells), len(grid.centers))
        for col, row in grid.cells:
            self.assertTrue(0 <= col < grid.nx and 0 <= row < grid.ny)
        self.assertLess(grid.south, 39.74)
        self.assertGreater(grid.north, 41.88)

    def test_cells_far_from_route_are_excluded(self):
        path = [(40.0, -110.0), (40.0, -90.0)]
        grid = build_corridor_grid([path])
        for lat, lon in grid.centers:
            self.assertLess(haversine_mi((lat, lon), (40.0, lon)), 120)
