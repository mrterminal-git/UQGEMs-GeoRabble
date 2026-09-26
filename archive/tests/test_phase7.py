"""Unit tests for Phase 7 selective LoD2 roof helpers."""

import numpy as np
import trimesh
from shapely.geometry import box

from uqgems.acquisition import PILOT_AREA
from uqgems.lod2 import (
    MIN_INTERPLANE_ANGLE_DEGREES,
    MIN_LOD2_SLOPE_DEGREES,
    VALIDATION_RESIDUAL_THRESHOLD_M,
    fit_roof_planes,
    lod2_mesh,
    maximum_interplane_angle,
    partition_roof,
)
from uqgems.phase7 import LOD2_REQUIRED_FIELDS, LOD2_STATUSES


def _synthetic_gable_points() -> tuple[np.ndarray, object]:
    west = PILOT_AREA.west + 30
    south = PILOT_AREA.south + 30
    width = 20.0
    depth = 12.0
    x, y = np.meshgrid(
        np.linspace(west + 0.2, west + width - 0.2, 49),
        np.linspace(south + 0.2, south + depth - 0.2, 31),
    )
    ridge_x = west + width / 2
    z = 30.0 - 0.22 * np.abs(x - ridge_x)
    rng = np.random.default_rng(7)
    z += rng.normal(0, 0.025, size=z.shape)
    return np.column_stack([x.ravel(), y.ravel(), z.ravel()]), box(
        west, south, west + width, south + depth
    )


def test_gable_planes_partition_and_mesh_are_defensible() -> None:
    points, footprint = _synthetic_gable_points()
    planes, assignments, fit = fit_roof_planes(points, random_state=17)
    regions, partition = partition_roof(footprint, planes, points, assignments)
    active = [
        (plane, region)
        for plane, region in zip(planes, regions, strict=True)
        if not region.is_empty and region.area > 0.01
    ]
    active_planes = [plane for plane, _ in active]
    active_regions = [region for _, region in active]
    mesh = lod2_mesh(footprint, active_planes, active_regions, base_z=20.0)

    assert len(active_planes) == 2
    assert fit["covered_fraction"] > 0.95
    assert partition["surface_covered_fraction"] > 0.95
    assert partition["footprint_area_coverage"] > 0.999
    assert partition["ridge_count"] == 1
    assert maximum_interplane_angle(active_planes) > MIN_INTERPLANE_ANGLE_DEGREES
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.is_watertight
    assert mesh.is_volume


def test_flat_roof_does_not_earn_meaningful_lod2_slope() -> None:
    points, _ = _synthetic_gable_points()
    rng = np.random.default_rng(13)
    points[:, 2] = 25.0 + rng.normal(0, 0.02, len(points))
    planes, _, fit = fit_roof_planes(points, random_state=19)
    assert planes
    assert fit["covered_fraction"] > 0.95
    assert max(plane["slope_degrees"] for plane in planes) < MIN_LOD2_SLOPE_DEGREES


def test_phase7_thresholds_and_schema_are_explicit() -> None:
    assert VALIDATION_RESIDUAL_THRESHOLD_M == 0.35
    assert {
        "reliable LoD2",
        "approximate LoD2",
        "manual correction required",
        "LoD1 only",
        "missing or outdated source data",
    } == LOD2_STATUSES
    assert {
        "building_id",
        "lod2_status",
        "output_lod",
        "surface_covered_fraction",
        "surface_rmse_m",
    }.issubset(LOD2_REQUIRED_FIELDS)
