"""Unit tests for Phase 6 LoD1 building helpers."""

import numpy as np
import trimesh
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from uqgems.acquisition import PILOT_AREA
from uqgems.buildings import (
    MAX_BUILDING_HEIGHT_M,
    MIN_BUILDING_HEIGHT_M,
    MIN_ROOF_POINTS,
    geometry_mesh_arrays,
    terrain_at_xy,
    terrain_values_in_footprint,
)
from uqgems.phase6 import BUILDING_REGISTER_FIELDS, REQUIRED_BUILDING_FIELDS


def _processed_mesh(geometry: Polygon, base_z: float = 10, roof_z: float = 20) -> trimesh.Trimesh:
    vertices, faces = geometry_mesh_arrays(geometry, base_z=base_z, roof_z=roof_z)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def test_lod1_mesh_is_watertight_and_has_expected_volume() -> None:
    geometry = box(
        PILOT_AREA.west,
        PILOT_AREA.south,
        PILOT_AREA.west + 10,
        PILOT_AREA.south + 10,
    )
    mesh = _processed_mesh(geometry)
    assert mesh.is_watertight
    assert mesh.is_volume
    assert np.isclose(mesh.volume, 1_000)


def test_lod1_mesh_respects_courtyard_holes() -> None:
    exterior = [
        (PILOT_AREA.west, PILOT_AREA.south),
        (PILOT_AREA.west + 10, PILOT_AREA.south),
        (PILOT_AREA.west + 10, PILOT_AREA.south + 10),
        (PILOT_AREA.west, PILOT_AREA.south + 10),
    ]
    hole = [
        (PILOT_AREA.west + 4, PILOT_AREA.south + 4),
        (PILOT_AREA.west + 6, PILOT_AREA.south + 4),
        (PILOT_AREA.west + 6, PILOT_AREA.south + 6),
        (PILOT_AREA.west + 4, PILOT_AREA.south + 6),
    ]
    mesh = _processed_mesh(Polygon(exterior, [hole]))
    assert mesh.is_watertight
    assert mesh.is_volume
    assert np.isclose(mesh.volume, 960)


def test_terrain_sampling_rejects_upper_and_right_edges() -> None:
    terrain = np.arange(16, dtype=float).reshape(4, 4)
    x = np.array([PILOT_AREA.west + 0.5, PILOT_AREA.west + 4])
    y = np.array([PILOT_AREA.north - 0.5, PILOT_AREA.north - 4])
    values, rows, columns = terrain_at_xy(x, y, terrain)
    assert values[0] == 0
    assert np.isnan(values[1])
    assert np.array_equal(rows, [0, 4])
    assert np.array_equal(columns, [0, 4])


def test_footprint_terrain_mask_includes_touched_cells() -> None:
    terrain = np.arange(25, dtype=float).reshape(5, 5)
    transform = from_origin(PILOT_AREA.west, PILOT_AREA.north, 1, 1)
    geometry = box(
        PILOT_AREA.west + 1,
        PILOT_AREA.north - 3,
        PILOT_AREA.west + 3,
        PILOT_AREA.north - 1,
    )
    values, mask = terrain_values_in_footprint(terrain, transform, geometry)
    assert values.size > 0
    assert mask.shape == terrain.shape


def test_phase6_thresholds_and_schema_are_explicit() -> None:
    assert MIN_ROOF_POINTS == 30
    assert MIN_BUILDING_HEIGHT_M == 2.5
    assert MAX_BUILDING_HEIGHT_M == 60
    assert {
        "building_id",
        "ground_z_ahd",
        "roof_z_ahd",
        "height_m",
        "confidence",
        "geometry_status",
    }.issubset(REQUIRED_BUILDING_FIELDS)
    assert {
        "dataset",
        "source_paths",
        "source_sha256",
        "output_path",
        "output_sha256",
        "validation_status",
    }.issubset(BUILDING_REGISTER_FIELDS)
