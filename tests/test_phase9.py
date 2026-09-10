"""Unit tests for Phase 9 integrated-scene helpers."""

import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString

from uqgems.acquisition import PILOT_AREA
from uqgems.integrated_scene import (
    SceneDisplayConfig,
    dashed_segments,
    display_z,
    drape_utility_geometry,
    terrain_at_xy,
)


def test_display_config_rejects_misleading_or_invalid_settings() -> None:
    SceneDisplayConfig().validate()
    with pytest.raises(ValueError):
        SceneDisplayConfig(vertical_exaggeration=0).validate()
    with pytest.raises(ValueError):
        SceneDisplayConfig(terrain_opacity=1.2).validate()
    with pytest.raises(ValueError):
        SceneDisplayConfig(utility_types=("unknown-network",)).validate()
    for colour_field in ("network_type", "confidence", "accuracy", "age"):
        SceneDisplayConfig(utility_colour_by=colour_field).validate()
    with pytest.raises(ValueError):
        SceneDisplayConfig(utility_colour_by="material").validate()


def test_vertical_exaggeration_preserves_anchor() -> None:
    values = display_z([5.0, 10.0, 15.0], anchor=5.0, vertical_exaggeration=2.0)
    assert np.allclose(values, [5.0, 15.0, 25.0])


def test_terrain_sampling_and_display_drape_are_explicit() -> None:
    west, _, _, north = PILOT_AREA.projected_bounds
    terrain = np.asarray([[10.0, 11.0], [12.0, 13.0]])
    transform = from_origin(west, north, 1.0, 1.0)
    x = np.asarray([west + 0.25, west + 1.25, west - 1.0])
    y = np.asarray([north - 0.25, north - 1.25, north - 0.5])
    sampled = terrain_at_xy(terrain, transform, x, y)
    assert np.allclose(sampled[:2], [10.0, 13.0])
    assert np.isnan(sampled[2])

    line = LineString([(west + 0.1, north - 0.2), (west + 1.8, north - 0.2)])
    parts = drape_utility_geometry(
        line,
        terrain,
        transform,
        local_origin=(west, north, 0.0),
        offset_m=0.75,
        spacing_m=0.25,
    )
    assert len(parts) == 1
    points = parts[0]
    authoritative_x = points[:, 0] + west
    authoritative_y = points[:, 1] + north
    surface = terrain_at_xy(terrain, transform, authoritative_x, authoritative_y)
    assert np.allclose(points[:, 2] - surface, 0.75)


def test_dense_polyline_is_split_into_visible_dash_segments() -> None:
    points = np.column_stack([np.arange(0.0, 10.1, 1.0), np.zeros(11), np.ones(11)])
    segments = dashed_segments(points, dash_length_m=2.0, gap_length_m=1.0)
    assert len(segments) >= 3
    assert all(len(segment) >= 2 for segment in segments)
    assert all(np.allclose(segment[:, 2], 1.0) for segment in segments)
