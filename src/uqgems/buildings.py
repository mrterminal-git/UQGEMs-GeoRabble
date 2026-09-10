"""Defensible LoD1 building-model helpers for Phase 6."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import geopandas as gpd
import laspy
import numpy as np
import rasterio
import shapely
import trimesh
from rasterio.features import geometry_mask
from shapely import STRtree
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from uqgems.acquisition import PILOT_AREA
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG

MIN_ROOF_POINTS = 30
MIN_BUILDING_HEIGHT_M = 2.5
MAX_BUILDING_HEIGHT_M = 60.0
ROOF_OUTLIER_MINIMUM_TOLERANCE_M = 1.0
ROOF_OUTLIER_NMAD_MULTIPLIER = 4.0
ROOF_SAMPLE_POINTS_PER_BUILDING = 500

CONFIDENCE_COLOURS = {
    "high": np.array([42, 125, 79, 255], dtype=np.uint8),
    "medium": np.array([33, 113, 181, 255], dtype=np.uint8),
    "low": np.array([230, 126, 34, 255], dtype=np.uint8),
}


def _polygon_parts(geometry: Polygon | MultiPolygon) -> Iterator[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _polygonal_only(geometry: Any) -> Polygon | MultiPolygon:
    """Extract polygonal content from a repaired or clipped geometry."""
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon))]
        flattened = [polygon for part in parts for polygon in _polygon_parts(part)]
        if not flattened:
            return Polygon()
        return MultiPolygon(flattened) if len(flattened) > 1 else flattened[0]
    return Polygon()


def _specific_name(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    name = str(value).strip()
    generic = {
        "",
        "University Of Queensland St Lucia Campus",
        "University of Queensland",
    }
    return None if name in generic else name


def _best_overlapping_name(
    geometry: Polygon | MultiPolygon,
    candidates: gpd.GeoDataFrame,
    *,
    minimum_overlap_fraction: float = 0.10,
) -> tuple[str | None, float]:
    named = candidates.loc[candidates["name"].map(_specific_name).notna()]
    if named.empty:
        return None, 0.0
    possible = named.loc[named.geometry.intersects(geometry)]
    if possible.empty:
        return None, 0.0
    overlap = possible.geometry.intersection(geometry).area
    best_index = overlap.idxmax()
    fraction = float(overlap.loc[best_index] / max(geometry.area, 1e-9))
    if fraction < minimum_overlap_fraction:
        return None, fraction
    return _specific_name(possible.loc[best_index, "name"]), fraction


def prepare_footprints(vector_path: str | Path) -> gpd.GeoDataFrame:
    """Validate, crop, identify and name the primary Queensland building outlines."""
    path = Path(vector_path)
    outlines = gpd.read_file(path, layer="qld_building_outlines")
    qld_areas = gpd.read_file(path, layer="qld_building_areas")
    osm = gpd.read_file(path, layer="osm_buildings")
    if outlines.crs is None or outlines.crs.to_epsg() != TARGET_EPSG:
        raise ValueError(f"Primary footprints must use EPSG:{TARGET_EPSG}")

    aoi = shapely.box(*PILOT_AREA.projected_bounds)
    selected = outlines.loc[outlines.geometry.intersects(aoi)].copy()
    records: list[dict[str, Any]] = []
    for source_index, row in selected.iterrows():
        original = row.geometry
        geometry_was_valid = bool(original.is_valid)
        repaired = shapely.make_valid(original) if not geometry_was_valid else original
        clipped = _polygonal_only(repaired.intersection(aoi))
        if clipped.is_empty or clipped.area <= 1.0:
            continue
        boundary_clipped = not bool(aoi.buffer(-0.001).contains(clipped))
        osm_name, osm_overlap = _best_overlapping_name(clipped, osm)
        qld_name, qld_overlap = _best_overlapping_name(clipped, qld_areas)
        name = osm_name or qld_name
        name_source = (
            "OpenStreetMap"
            if osm_name
            else ("Queensland building areas" if qld_name else None)
        )
        geometry_status = "valid"
        if not geometry_was_valid:
            geometry_status = "repaired"
        if boundary_clipped:
            geometry_status += "; clipped_at_pilot_boundary"
        records.append(
            {
                "source_index": int(source_index),
                "source_objectid": row.get("objectid"),
                "building_name": name,
                "name_source": name_source,
                "name_overlap_fraction": max(osm_overlap, qld_overlap),
                "footprint_source": "Queensland generated building outlines",
                "source_bsm_min_ahd": row.get("bsm_min"),
                "source_bsm_max_ahd": row.get("bsm_max"),
                "source_bsm_edge_ahd": row.get("bsm_edge"),
                "source_dtm_centre_ahd": row.get("dtm_centre"),
                "geometry_status": geometry_status,
                "boundary_clipped": boundary_clipped,
                "geometry": clipped,
            }
        )

    result = gpd.GeoDataFrame(records, geometry="geometry", crs=outlines.crs)
    result["centroid_easting"] = result.geometry.centroid.x
    result["centroid_northing"] = result.geometry.centroid.y
    result = result.sort_values(
        ["centroid_northing", "centroid_easting"], ascending=[False, True]
    ).reset_index(drop=True)
    result.insert(0, "building_id", [f"UQSL-{index:03d}" for index in range(1, len(result) + 1)])
    result["footprint_area_m2"] = result.geometry.area
    return result


def read_terrain(path: str | Path) -> tuple[np.ndarray, Any]:
    with rasterio.open(path) as source:
        if source.crs is None or source.crs.to_epsg() != TARGET_EPSG:
            raise ValueError(f"Terrain must use EPSG:{TARGET_EPSG}")
        data = source.read(1).astype(float)
        if source.nodata is not None:
            data[data == source.nodata] = np.nan
        return data, source.transform


def terrain_at_xy(
    x: np.ndarray,
    y: np.ndarray,
    terrain: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    columns = np.floor(x - PILOT_AREA.west).astype(np.int64)
    rows = np.floor(PILOT_AREA.north - y).astype(np.int64)
    valid = (
        (rows >= 0)
        & (rows < terrain.shape[0])
        & (columns >= 0)
        & (columns < terrain.shape[1])
    )
    values = np.full(x.shape, np.nan, dtype=float)
    values[valid] = terrain[rows[valid], columns[valid]]
    return values, rows, columns


def terrain_values_in_footprint(
    terrain: np.ndarray,
    transform: Any,
    geometry: Polygon | MultiPolygon,
) -> tuple[np.ndarray, np.ndarray]:
    mask = geometry_mask(
        [geometry],
        out_shape=terrain.shape,
        transform=transform,
        invert=True,
        all_touched=True,
    )
    valid = mask & np.isfinite(terrain)
    return terrain[valid], valid


def extract_building_points(
    laz_path: str | Path,
    footprints: gpd.GeoDataFrame,
    terrain: np.ndarray,
    *,
    chunk_size: int = 750_000,
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """Assign class-6 LiDAR points to footprints with a spatial index in chunks."""
    geometries = list(footprints.geometry)
    tree = STRtree(geometries)
    geometry_areas = np.asarray([geometry.area for geometry in geometries])
    point_chunks: dict[str, list[np.ndarray]] = {
        building_id: [] for building_id in footprints["building_id"]
    }
    class6_total = 0
    assigned = 0
    duplicate_matches = 0

    with laspy.open(laz_path) as reader:
        crs = reader.header.parse_crs()
        if crs is None or crs.to_epsg() != TARGET_EPSG:
            raise ValueError(f"Building point cloud must use EPSG:{TARGET_EPSG}")
        for points in reader.chunk_iterator(chunk_size):
            classification = np.asarray(points.classification)
            is_building = classification == 6
            if not is_building.any():
                continue
            x = np.asarray(points.x)[is_building]
            y = np.asarray(points.y)[is_building]
            z = np.asarray(points.z)[is_building]
            class6_total += int(x.size)
            matches = tree.query(shapely.points(x, y), predicate="within")
            if not matches.size:
                continue
            point_indices = matches[0]
            geometry_indices = matches[1]
            if point_indices.size:
                order = np.lexsort((geometry_areas[geometry_indices], point_indices))
                point_indices = point_indices[order]
                geometry_indices = geometry_indices[order]
                keep = np.ones(point_indices.size, dtype=bool)
                keep[1:] = point_indices[1:] != point_indices[:-1]
                duplicate_matches += int((~keep).sum())
                point_indices = point_indices[keep]
                geometry_indices = geometry_indices[keep]
            ground, rows, columns = terrain_at_xy(x[point_indices], y[point_indices], terrain)
            values = np.column_stack(
                [
                    x[point_indices],
                    y[point_indices],
                    z[point_indices],
                    ground,
                    rows,
                    columns,
                ]
            )
            assigned += int(values.shape[0])
            order = np.argsort(geometry_indices, kind="stable")
            sorted_buildings = geometry_indices[order]
            sorted_values = values[order]
            unique_buildings, first = np.unique(sorted_buildings, return_index=True)
            boundaries = np.append(first[1:], len(sorted_buildings))
            for building_index, start, stop in zip(
                unique_buildings, first, boundaries, strict=True
            ):
                building_id = str(footprints.iloc[int(building_index)]["building_id"])
                point_chunks[building_id].append(sorted_values[start:stop])

    arrays = {
        building_id: (
            np.concatenate(chunks) if chunks else np.empty((0, 6), dtype=float)
        )
        for building_id, chunks in point_chunks.items()
    }
    return arrays, {
        "class6_points_in_analysis_cloud": class6_total,
        "class6_points_assigned_to_primary_footprints": assigned,
        "class6_points_outside_primary_footprints": class6_total - assigned,
        "overlapping_footprint_matches_resolved": duplicate_matches,
    }


def _confidence(
    *,
    modelled: bool,
    boundary_clipped: bool,
    points: int,
    density: float,
    coverage: float,
    roof_nmad: float,
    bsm_difference: float,
) -> str:
    if not modelled:
        return "low"
    high = (
        not boundary_clipped
        and points >= 200
        and density >= 5.0
        and coverage >= 0.65
        and roof_nmad <= 1.5
        and abs(bsm_difference) <= 2.0
    )
    medium = (
        points >= MIN_ROOF_POINTS
        and density >= 1.0
        and coverage >= 0.25
        and roof_nmad <= 3.0
    )
    return "high" if high else ("medium" if medium else "low")


def model_lod1_buildings(
    footprints: gpd.GeoDataFrame,
    point_arrays: dict[str, np.ndarray],
    terrain: np.ndarray,
    transform: Any,
) -> tuple[gpd.GeoDataFrame, dict[str, np.ndarray]]:
    """Estimate robust flat-roof LoD1 attributes and retain small visual samples."""
    records: list[dict[str, Any]] = []
    samples: dict[str, np.ndarray] = {}
    for _, footprint in footprints.iterrows():
        building_id = str(footprint["building_id"])
        points = point_arrays[building_id]
        ground_values, footprint_mask = terrain_values_in_footprint(
            terrain, transform, footprint.geometry
        )
        point_ground = points[:, 3] if len(points) else np.array([], dtype=float)
        point_valid = np.isfinite(point_ground)
        points = points[point_valid]
        height_values = points[:, 2] - points[:, 3] if len(points) else np.array([])
        preliminary_median = float(np.median(points[:, 2])) if len(points) else math.nan
        preliminary_nmad = (
            float(1.4826 * np.median(np.abs(points[:, 2] - preliminary_median)))
            if len(points)
            else math.nan
        )
        tolerance = (
            max(
                ROOF_OUTLIER_MINIMUM_TOLERANCE_M,
                ROOF_OUTLIER_NMAD_MULTIPLIER * preliminary_nmad,
            )
            if len(points)
            else math.nan
        )
        robust_keep = (
            np.abs(points[:, 2] - preliminary_median) <= tolerance
            if len(points)
            else np.array([], dtype=bool)
        )
        retained = points[robust_keep]
        retained_heights = height_values[robust_keep]

        ground_z = float(np.median(ground_values)) if ground_values.size else math.nan
        base_z = float(np.min(ground_values) - 0.10) if ground_values.size else math.nan
        roof_z = float(np.median(retained[:, 2])) if len(retained) else math.nan
        height = roof_z - ground_z if np.isfinite(roof_z) and np.isfinite(ground_z) else math.nan
        roof_nmad = (
            float(1.4826 * np.median(np.abs(retained[:, 2] - roof_z)))
            if len(retained)
            else math.nan
        )
        area = float(footprint.geometry.area)
        density = float(len(retained) / area)
        if len(retained):
            cell_pairs = np.unique(retained[:, 4:6].astype(np.int64), axis=0)
            occupied_cells = len(cell_pairs)
        else:
            occupied_cells = 0
        expected_cells = int(footprint_mask.sum())
        coverage = min(1.0, occupied_cells / max(expected_cells, 1))
        source_bsm_edge = float(footprint["source_bsm_edge_ahd"])
        bsm_difference = roof_z - source_bsm_edge if np.isfinite(roof_z) else math.nan
        enough_points = len(retained) >= MIN_ROOF_POINTS
        plausible_height = bool(
            np.isfinite(height)
            and MIN_BUILDING_HEIGHT_M <= height <= MAX_BUILDING_HEIGHT_M
        )
        modelled = bool(enough_points and plausible_height and np.isfinite(base_z))

        issues: list[str] = []
        if footprint["boundary_clipped"]:
            issues.append("partial footprint at pilot boundary")
        if not enough_points:
            issues.append("insufficient building-class points")
        if not plausible_height:
            issues.append("height outside modelling range")
        if coverage < 0.25:
            issues.append("low roof-cell coverage")
        if np.isfinite(roof_nmad) and roof_nmad > 3.0:
            issues.append("high within-footprint roof dispersion")
        if np.isfinite(bsm_difference) and abs(bsm_difference) > 2.0:
            issues.append("LiDAR roof estimate differs from source BSM edge")
        if not footprint["building_name"]:
            issues.append("no specific public building name")

        confidence = _confidence(
            modelled=modelled,
            boundary_clipped=bool(footprint["boundary_clipped"]),
            points=len(retained),
            density=density,
            coverage=coverage,
            roof_nmad=roof_nmad,
            bsm_difference=bsm_difference,
        )
        record = copy.deepcopy(footprint.to_dict())
        record.update(
            {
                "ground_z_ahd": ground_z,
                "base_z_ahd": base_z,
                "roof_z_ahd": roof_z if modelled else math.nan,
                "height_m": height if modelled else math.nan,
                "height_method": (
                    "median class-6 Z after 4-NMAD filter; median footprint DTM ground"
                    if modelled
                    else "not estimated"
                ),
                "lidar_capture_date": "2019",
                "lod": "LoD1" if modelled else "not modelled",
                "confidence": confidence,
                "model_status": "modelled" if modelled else "withheld",
                "roof_points_raw": int(len(points)),
                "roof_points_used": int(len(retained)),
                "roof_points_removed": int(len(points) - len(retained)),
                "roof_point_density_m2": density,
                "roof_cell_coverage": coverage,
                "roof_z_nmad_m": roof_nmad,
                "roof_z_p05_ahd": (
                    float(np.percentile(retained[:, 2], 5)) if len(retained) else math.nan
                ),
                "roof_z_p95_ahd": (
                    float(np.percentile(retained[:, 2], 95)) if len(retained) else math.nan
                ),
                "ground_range_m": (
                    float(np.max(ground_values) - np.min(ground_values))
                    if ground_values.size
                    else math.nan
                ),
                "bsm_edge_difference_m": bsm_difference,
                "issues": "; ".join(issues),
                "notes": (
                    "; ".join(issues)
                    if issues
                    else "No automated quality warnings."
                ),
            }
        )
        records.append(record)
        if len(retained):
            sample_count = min(ROOF_SAMPLE_POINTS_PER_BUILDING, len(retained))
            indices = np.linspace(0, len(retained) - 1, sample_count, dtype=int)
            samples[building_id] = np.column_stack(
                [retained[indices, :3], retained_heights[indices]]
            )
        else:
            samples[building_id] = np.empty((0, 4), dtype=float)

    return gpd.GeoDataFrame(records, geometry="geometry", crs=footprints.crs), samples


def write_lod1_geopackage(buildings: gpd.GeoDataFrame, destination: str | Path) -> Path:
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.part{output.suffix}")
    partial.unlink(missing_ok=True)
    try:
        buildings.to_file(partial, layer="lod1_buildings", driver="GPKG", engine="pyogrio")
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def save_roof_samples(samples: dict[str, np.ndarray], destination: str | Path) -> Path:
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.part{output.suffix}")
    partial.unlink(missing_ok=True)
    try:
        serialisable = {key.replace("-", "_"): value for key, value in samples.items()}
        np.savez_compressed(partial, **serialisable)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def load_roof_samples(path: str | Path) -> dict[str, np.ndarray]:
    with np.load(path) as archive:
        return {key.replace("_", "-"): archive[key] for key in archive.files}


def geometry_mesh_arrays(
    geometry: Polygon | MultiPolygon,
    *,
    base_z: float,
    roof_z: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Create closed triangular LoD1 mesh arrays in display-local XY coordinates."""
    vertices: list[list[float]] = []
    faces: list[list[int]] = []

    def add_triangle(coordinates: list[tuple[float, float]], z: float, *, reverse: bool) -> None:
        start = len(vertices)
        local = [
            [x - LOCAL_ORIGIN[0], y - LOCAL_ORIGIN[1], z] for x, y in coordinates
        ]
        signed_area = sum(
            local[index][0] * local[(index + 1) % 3][1]
            - local[(index + 1) % 3][0] * local[index][1]
            for index in range(3)
        )
        order = [0, 1, 2] if signed_area > 0 else [0, 2, 1]
        if reverse:
            order = list(reversed(order))
        vertices.extend(local)
        faces.append([start + index for index in order])

    for polygon in _polygon_parts(geometry):
        roof_triangles = list(shapely.constrained_delaunay_triangles(polygon).geoms)
        for triangle in roof_triangles:
            coordinates = list(triangle.exterior.coords)[:3]
            add_triangle(coordinates, roof_z, reverse=False)
            add_triangle(coordinates, base_z, reverse=True)
        for ring in [polygon.exterior, *polygon.interiors]:
            coordinates = list(ring.coords)
            for first, second in zip(coordinates[:-1], coordinates[1:], strict=True):
                start = len(vertices)
                x1, y1 = first
                x2, y2 = second
                vertices.extend(
                    [
                        [x1 - LOCAL_ORIGIN[0], y1 - LOCAL_ORIGIN[1], base_z],
                        [x2 - LOCAL_ORIGIN[0], y2 - LOCAL_ORIGIN[1], base_z],
                        [x2 - LOCAL_ORIGIN[0], y2 - LOCAL_ORIGIN[1], roof_z],
                        [x1 - LOCAL_ORIGIN[0], y1 - LOCAL_ORIGIN[1], roof_z],
                    ]
                )
                faces.extend(
                    [[start, start + 1, start + 2], [start, start + 2, start + 3]]
                )
    return np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int64)


def building_meshes(buildings: gpd.GeoDataFrame) -> dict[str, trimesh.Trimesh]:
    meshes: dict[str, trimesh.Trimesh] = {}
    for _, building in buildings.loc[buildings["model_status"] == "modelled"].iterrows():
        vertices, faces = geometry_mesh_arrays(
            building.geometry,
            base_z=float(building["base_z_ahd"]),
            roof_z=float(building["roof_z_ahd"]),
        )
        colour = CONFIDENCE_COLOURS[str(building["confidence"])]
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
        mesh.fix_normals()
        mesh.visual.face_colors = np.tile(colour, (len(faces), 1))
        mesh.metadata.update(
            {
                "building_id": building["building_id"],
                "building_name": building["building_name"] or "",
                "confidence": building["confidence"],
                "height_m": float(building["height_m"]),
            }
        )
        meshes[str(building["building_id"])] = mesh
    return meshes


def write_lod1_glb(buildings: gpd.GeoDataFrame, destination: str | Path) -> Path:
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.part{output.suffix}")
    partial.unlink(missing_ok=True)
    try:
        scene = trimesh.Scene()
        for building_id, mesh in building_meshes(buildings).items():
            scene.add_geometry(mesh, node_name=building_id, geom_name=building_id)
        partial.write_bytes(trimesh.exchange.gltf.export_glb(scene))
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output
