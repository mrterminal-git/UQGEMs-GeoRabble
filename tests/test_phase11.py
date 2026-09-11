"""Unit tests for presentation-skin geometry and texture helpers."""

import numpy as np
import pytest

from uqgems.facade_evidence import (
    FacadeAuditConfig,
    _scan_angle_degrees,
    facade_segment_status,
)
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


def test_las14_scan_angles_are_converted_from_006_degree_units() -> None:
    values = _scan_angle_degrees(np.asarray([-500, 0, 5500]), point_format_id=6)
    np.testing.assert_allclose(values, [-3.0, 0.0, 33.0])


def test_facade_segment_gate_distinguishes_geometry_evidence_levels() -> None:
    config = FacadeAuditConfig()
    sufficient = {
        "evidence_points": 50,
        "evidence_density_m2": 0.8,
        "vertical_bin_coverage": 0.7,
        "horizontal_bin_coverage": 0.6,
        "grid_bin_coverage": 0.2,
        "vertical_span_fraction": 0.8,
        "p95_distance_m": 0.3,
    }
    assert facade_segment_status(sufficient, config) == "sufficient"
    marginal = sufficient | {
        "evidence_points": 15,
        "evidence_density_m2": 0.2,
        "vertical_bin_coverage": 0.3,
        "horizontal_bin_coverage": 0.3,
        "grid_bin_coverage": 0.05,
        "vertical_span_fraction": 0.4,
        "p95_distance_m": 0.7,
    }
    assert facade_segment_status(marginal, config) == "marginal"
    assert facade_segment_status(marginal | {"evidence_points": 5}, config) == "insufficient"
