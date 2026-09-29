from __future__ import annotations

import sys
import unittest
from pathlib import Path

from shapely.geometry import MultiPolygon, Point, Polygon


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_routes_geojson import clip_line_to_geometry  # noqa: E402
from utils import (  # noqa: E402
    calculate_geojson_geometry_center,
    crop_gtfs_by_boundary,
    map_stops_to_wards,
)


class BoundaryCropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = Polygon([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)])
        self.routes = [{"route_id": "kept"}, {"route_id": "removed"}]
        self.trips = [
            {"trip_id": "crossing", "route_id": "kept"},
            {"trip_id": "one-stop", "route_id": "removed"},
        ]
        self.stop_times = {
            "crossing": [
                {"stop_id": "inside", "stop_sequence": "1"},
                {"stop_id": "edge", "stop_sequence": "2"},
                {"stop_id": "outside", "stop_sequence": "3"},
            ],
            "one-stop": [
                {"stop_id": "inside", "stop_sequence": "1"},
                {"stop_id": "outside", "stop_sequence": "2"},
            ],
        }
        self.stops = {
            "inside": {"stop_lon": 1.0, "stop_lat": 1.0},
            "edge": {"stop_lon": 2.0, "stop_lat": 1.0},
            "outside": {"stop_lon": 3.0, "stop_lat": 1.0},
        }

    def test_polygon_crop_keeps_boundary_points_and_prunes_short_trips(self) -> None:
        routes, trips, stop_times, stops = crop_gtfs_by_boundary(
            self.boundary,
            self.routes,
            self.trips,
            self.stop_times,
            self.stops,
        )

        self.assertEqual([route["route_id"] for route in routes], ["kept"])
        self.assertEqual([trip["trip_id"] for trip in trips], ["crossing"])
        self.assertEqual(list(stop_times), ["crossing"])
        self.assertEqual(
            [row["stop_id"] for row in stop_times["crossing"]],
            ["inside", "edge"],
        )
        self.assertEqual(set(stops), {"inside", "edge"})

    def test_route_geometry_is_clipped_to_boundary(self) -> None:
        runs = clip_line_to_geometry([(-1, 1), (1, 1), (3, 1)], self.boundary)
        self.assertEqual(runs, [[(0.0, 1.0), (1.0, 1.0), (2.0, 1.0)]])


class WardGeometryTests(unittest.TestCase):
    def test_polygon_and_multipolygon_wards_are_supported(self) -> None:
        wards = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"namecol": "A"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {"namecol": "B"},
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]],
                            [[[4, 0], [5, 0], [5, 1], [4, 1], [4, 0]]],
                        ],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {"namecol": "EMPTY"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[8, 0], [9, 0], [9, 1], [8, 1], [8, 0]]],
                    },
                },
            ],
        }
        stops = iter(
            [
                {"stop_id": "a", "stop_lon": "0.5", "stop_lat": "0.5"},
                {"stop_id": "b", "stop_lon": "4.5", "stop_lat": "0.5"},
            ]
        )

        mapped = map_stops_to_wards(stops, wards)

        self.assertEqual(mapped["A"], {"a"})
        self.assertEqual(mapped["B"], {"b"})
        self.assertEqual(mapped["EMPTY"], set())

        lon, lat = calculate_geojson_geometry_center(wards["features"][1]["geometry"])
        multipolygon = MultiPolygon(
            [
                Polygon([(2, 0), (3, 0), (3, 1), (2, 1), (2, 0)]),
                Polygon([(4, 0), (5, 0), (5, 1), (4, 1), (4, 0)]),
            ]
        )
        self.assertTrue(multipolygon.covers(Point(lon, lat)))


if __name__ == "__main__":
    unittest.main()
