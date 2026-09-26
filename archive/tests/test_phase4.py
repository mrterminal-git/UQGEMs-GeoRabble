"""Unit tests for Phase 4 coordinate-system helpers."""

import numpy as np
from pyproj import Transformer

from uqgems.normalization import (
    EPSG_OPERATION,
    GRID_NAME,
    LOCAL_ORIGIN,
    TARGET_EPSG,
    TRANSFORMATION_PIPELINE,
    authoritative_to_local,
    local_to_authoritative,
    transformed_bounds,
)
from uqgems.phase4 import NORMALISATION_REGISTER_FIELDS


def test_phase4_uses_explicit_conformal_and_distortion_operation() -> None:
    assert EPSG_OPERATION == 8447
    assert GRID_NAME in TRANSFORMATION_PIPELINE
    assert "conformal_and_distortion" in TRANSFORMATION_PIPELINE
    assert TARGET_EPSG == 7856


def test_local_origin_translation_round_trip() -> None:
    authoritative = np.array(
        [
            [LOCAL_ORIGIN[0], LOCAL_ORIGIN[1], 5.0],
            [LOCAL_ORIGIN[0] + 250, LOCAL_ORIGIN[1] - 250, 32.0],
        ]
    )
    local = authoritative_to_local(authoritative)
    assert np.allclose(local[0], [0.0, 0.0, 5.0])
    assert np.allclose(local_to_authoritative(local), authoritative)


def test_transformed_bounds_densifies_edges() -> None:
    transformer = Transformer.from_pipeline("+proj=affine +xoff=2 +yoff=-3")
    result = transformed_bounds((0.0, 0.0, 10.0, 20.0), transformer)
    assert np.allclose(result, [2.0, -3.0, 12.0, 17.0])


def test_normalisation_register_fields_are_complete() -> None:
    required = {
        "dataset",
        "source_path",
        "source_sha256",
        "source_crs",
        "target_path",
        "target_sha256",
        "target_crs",
        "vertical_datum",
        "horizontal_operation",
        "vertical_operation",
        "software",
        "validation_status",
    }
    assert required.issubset(NORMALISATION_REGISTER_FIELDS)
