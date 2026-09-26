"""Unit tests for Phase 8 utility standardisation helpers."""

import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from uqgems.acquisition import PILOT_AREA
from uqgems.utilities import (
    UTILITY_REQUIRED_FIELDS,
    clean_numeric,
    connectivity_statistics,
    grade_diagnostics,
    linestring_with_linear_z,
    parse_grade_denominator,
    parse_size_mm,
)


def test_source_sentinels_and_sizes_are_cleaned() -> None:
    assert math.isnan(clean_numeric(999))
    assert math.isnan(clean_numeric(999.99))
    assert clean_numeric(15.005) == 15.005
    assert parse_size_mm("450 MM") == 450.0
    assert parse_size_mm(225) == 225.0
    assert math.isnan(parse_size_mm("UNKNOWN"))


def test_published_grade_discrepancy_is_detected() -> None:
    row = pd.Series(
        {
            "raw_upstream_invert_level": 15.005,
            "raw_downstream_invert_level": 11.957,
            "published_grade": "1:85",
            "geometry": LineString([(0, 0), (26.72, 0)]),
        }
    )
    result = grade_diagnostics(row)
    assert parse_grade_denominator("1:85") == 85.0
    assert result["grade_discrepancy"]
    assert 8.0 < result["computed_grade_denominator"] < 10.0


def test_connectivity_distinguishes_node_boundary_and_open_endpoints() -> None:
    west, south, east, _ = PILOT_AREA.projected_bounds
    lines = gpd.GeoDataFrame(
        [
            {
                "asset_id": "storm-1",
                "network_type": "stormwater",
                "geometry": LineString([(west, south + 20), (west + 50, south + 20)]),
            }
        ],
        crs=PILOT_AREA.epsg,
    )
    nodes = gpd.GeoDataFrame(
        [
            {
                "asset_id": "node-1",
                "network_type": "stormwater",
                "geometry": Point(west + 50, south + 20),
            }
        ],
        crs=PILOT_AREA.epsg,
    )
    result = connectivity_statistics(lines, nodes)
    assert result["line_endpoints_total"] == 2
    assert result["endpoints_matched_to_public_node_1m"] == 1
    assert result["endpoints_at_pilot_boundary_1m"] == 1
    assert result["unexplained_open_endpoints"] == 0


def test_linear_z_helper_and_common_schema_are_explicit() -> None:
    line = linestring_with_linear_z(LineString([(0, 0), (3, 0), (3, 4)]), 10.0, 5.0)
    coordinates = list(line.coords)
    assert coordinates[0][2] == 10.0
    assert math.isclose(coordinates[1][2], 10.0 - 5.0 * 3.0 / 7.0)
    assert coordinates[-1][2] == 5.0
    assert {
        "asset_id",
        "network_type",
        "vertical_source",
        "invert_z_ahd",
        "depth_m",
        "sensitivity",
    }.issubset(UTILITY_REQUIRED_FIELDS)
