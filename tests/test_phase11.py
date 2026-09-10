"""Unit tests for presentation-skin geometry and texture helpers."""

import numpy as np
import pytest

from uqgems.skins import (
    SkinConfig,
    classify_surface_faces,
    orthophoto_uv,
    procedural_facade_texture,
)


def test_skin_config_rejects_invalid_geometry_or_display_settings() -> None:
    with pytest.raises(ValueError):
        SkinConfig(terrain_step=0).validate()
    with pytest.raises(ValueError):
        SkinConfig(facade_repeat_height_m=0).validate()
    with pytest.raises(ValueError):
        SkinConfig(utility_drape_offset_m=-1).validate()


def test_authoritative_xy_maps_to_north_up_texture_corners() -> None:
    bounds = (100.0, 200.0, 600.0, 700.0)
    uv = orthophoto_uv([100.0, 600.0, 350.0], [200.0, 700.0, 450.0], bounds)
    np.testing.assert_allclose(uv, [[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]])


def test_surface_normal_classification_is_complete_and_exclusive() -> None:
    normals = np.asarray(
        [
            [0.0, 0.0, 1.0],
            [0.4, 0.0, 0.9165],
            [1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0],
        ]
    )
    labels = classify_surface_faces(normals)
    assert labels.tolist() == ["roof", "roof", "facade", "base"]


def test_procedural_facade_texture_is_deterministic_and_not_flat() -> None:
    first = np.asarray(procedural_facade_texture(128))
    second = np.asarray(procedural_facade_texture(128))
    assert first.shape == (128, 128, 3)
    assert np.array_equal(first, second)
    assert len(np.unique(first.reshape(-1, 3), axis=0)) >= 5
