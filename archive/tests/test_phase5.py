"""Unit tests for Phase 5 terrain and LiDAR preparation helpers."""

import numpy as np

from uqgems.acquisition import PILOT_AREA
from uqgems.phase5 import PREPARATION_REGISTER_FIELDS
from uqgems.preparation import (
    ANALYSIS_MAX_HEIGHT_M,
    ANALYSIS_MIN_HEIGHT_M,
    NOISE_CLASSES,
    RASTER_HEIGHT,
    RASTER_TRANSFORM,
    RASTER_WIDTH,
    _terrain_at_points,
    hillshade,
)


def test_phase5_grid_is_exact_pilot_area() -> None:
    assert (RASTER_WIDTH, RASTER_HEIGHT) == (500, 500)
    assert np.allclose(
        [
            RASTER_TRANSFORM.c,
            RASTER_TRANSFORM.f - RASTER_HEIGHT,
            RASTER_TRANSFORM.c + RASTER_WIDTH,
            RASTER_TRANSFORM.f,
        ],
        PILOT_AREA.projected_bounds,
    )


def test_terrain_sampling_uses_grid_cells_and_rejects_edge() -> None:
    terrain = np.arange(16, dtype=float).reshape(4, 4)
    x = np.array([PILOT_AREA.west + 0.5, PILOT_AREA.east])
    y = np.array([PILOT_AREA.north - 0.5, PILOT_AREA.south])
    sampled, rows, columns = _terrain_at_points(x, y, terrain)
    assert sampled[0] == 0
    assert np.isnan(sampled[1])
    assert np.array_equal(rows, [0, 500])
    assert np.array_equal(columns, [0, 500])


def test_hillshade_is_finite_and_bounded() -> None:
    terrain = np.add.outer(np.arange(10, dtype=float), np.arange(10, dtype=float))
    shaded = hillshade(terrain)
    assert shaded.shape == terrain.shape
    assert np.isfinite(shaded).all()
    assert ((shaded >= 0) & (shaded <= 1)).all()


def test_filter_configuration_is_explicit() -> None:
    assert ANALYSIS_MIN_HEIGHT_M == -2
    assert ANALYSIS_MAX_HEIGHT_M == 80
    assert NOISE_CLASSES == (7, 18)


def test_preparation_register_fields_are_complete() -> None:
    required = {
        "dataset",
        "source_path",
        "source_sha256",
        "output_path",
        "output_sha256",
        "crs",
        "vertical_datum",
        "processing",
        "validation_status",
    }
    assert required.issubset(PREPARATION_REGISTER_FIELDS)
