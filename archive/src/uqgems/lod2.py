"""Conservative roof-plane fitting and LoD2 geometry helpers for Phase 7."""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import shapely
import trimesh
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
)
from shapely.ops import split, unary_union
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LinearRegression, RANSACRegressor

from uqgems.buildings import CONFIDENCE_COLOURS, building_meshes
from uqgems.normalization import LOCAL_ORIGIN

RANSAC_RESIDUAL_THRESHOLD_M = 0.20
VALIDATION_RESIDUAL_THRESHOLD_M = 0.35
MIN_PLANE_POINTS = 120
MIN_PLANE_POINT_FRACTION = 0.06
MAX_PLANES = 5
MAX_FIT_POINTS = 12_000
MIN_LOD2_SLOPE_DEGREES = 3.0
MIN_INTERPLANE_ANGLE_DEGREES = 8.0
MIN_RIDGE_LENGTH_M = 1.0

LOD2_STATUS_COLOURS = {
    "reliable LoD2": np.array([117, 74, 174, 255], dtype=np.uint8),
    "approximate LoD2": np.array([23, 156, 162, 255], dtype=np.uint8),
}


def _polygon_parts(geometry: Polygon | MultiPolygon) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return []


def _line_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for item in geometry.geoms for part in _line_parts(item)]
    return []


def plane_z(plane: dict[str, Any], x: np.ndarray | float, y: np.ndarray | float) -> Any:
    return (
        plane["a"] * (np.asarray(x) - plane["origin_x"])
        + plane["b"] * (np.asarray(y) - plane["origin_y"])
        + plane["c"]
    )


def _fit_linear_plane(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> dict[str, float]:
    origin_x = float(np.mean(x))
    origin_y = float(np.mean(y))
    design = np.column_stack([x - origin_x, y - origin_y])
    model = LinearRegression().fit(design, z)
    a, b = (float(value) for value in model.coef_)
    c = float(model.intercept_)
    slope = float(np.degrees(np.arctan(np.hypot(a, b))))
    aspect = float((np.degrees(np.arctan2(-a, -b)) + 360) % 360)
    return {
        "a": a,
        "b": b,
        "c": c,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "slope_degrees": slope,
        "aspect_degrees": aspect,
    }


def _fit_ransac_plane(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    *,
    random_state: int,
) -> tuple[dict[str, float], np.ndarray]:
    origin_x = float(np.mean(x))
    origin_y = float(np.mean(y))
    design = np.column_stack([x - origin_x, y - origin_y])
    estimator = RANSACRegressor(
        estimator=LinearRegression(),
        min_samples=3,
        residual_threshold=RANSAC_RESIDUAL_THRESHOLD_M,
        max_trials=100,
        stop_probability=0.995,
        random_state=random_state,
        loss="absolute_error",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        estimator.fit(design, z)
    inliers = np.asarray(estimator.inlier_mask_, dtype=bool)
    plane = _fit_linear_plane(x[inliers], y[inliers], z[inliers])
    return plane, inliers


def _normal(plane: dict[str, Any]) -> np.ndarray:
    vector = np.array([-plane["a"], -plane["b"], 1.0], dtype=float)
    return vector / np.linalg.norm(vector)


def maximum_interplane_angle(planes: list[dict[str, Any]]) -> float:
    maximum = 0.0
    for first_index, first in enumerate(planes):
        for second in planes[first_index + 1 :]:
            dot = float(np.clip(abs(np.dot(_normal(first), _normal(second))), 0, 1))
            maximum = max(maximum, float(np.degrees(np.arccos(dot))))
    return maximum


def _plane_divider(
    reference: Polygon | MultiPolygon,
    first: dict[str, Any],
    second: dict[str, Any],
) -> LineString | None:
    """Return a long local line where two fitted planes have equal elevation."""
    a = first["a"] - second["a"]
    b = first["b"] - second["b"]
    c = (
        first["c"]
        - second["c"]
        - first["a"] * first["origin_x"]
        - first["b"] * first["origin_y"]
        + second["a"] * second["origin_x"]
        + second["b"] * second["origin_y"]
    )
    norm_squared = a * a + b * b
    if norm_squared < 1e-16:
        return None
    centre = reference.centroid
    centre_value = a * centre.x + b * centre.y + c
    point_x = centre.x - a * centre_value / norm_squared
    point_y = centre.y - b * centre_value / norm_squared
    norm = math.sqrt(norm_squared)
    direction_x = -b / norm
    direction_y = a / norm
    west, south, east, north = reference.bounds
    length = 10 * math.hypot(east - west, north - south) + 10
    return LineString(
        [
            (point_x - direction_x * length, point_y - direction_y * length),
            (point_x + direction_x * length, point_y + direction_y * length),
        ]
    )


def fit_roof_planes(
    points: np.ndarray,
    *,
    random_state: int,
) -> tuple[list[dict[str, Any]], np.ndarray, dict[str, Any]]:
    """Fit and validate a small set of robust planes against all supplied XYZ points."""
    all_xyz = np.asarray(points[:, :3], dtype=float)
    if len(all_xyz) < MIN_PLANE_POINTS:
        return (
            [],
            np.full(len(all_xyz), -1, dtype=int),
            {
                "input_points": len(all_xyz),
                "covered_fraction": 0.0,
                "rmse_m": math.nan,
                "median_absolute_residual_m": math.nan,
                "p95_absolute_residual_m": math.nan,
            },
        )
    fit_xyz = all_xyz
    if len(fit_xyz) > 200:
        low, high = np.percentile(fit_xyz[:, 2], [0.5, 99.5])
        fit_xyz = fit_xyz[(fit_xyz[:, 2] >= low) & (fit_xyz[:, 2] <= high)]
    sample_indices = np.linspace(0, len(fit_xyz) - 1, min(MAX_FIT_POINTS, len(fit_xyz)), dtype=int)
    fit_points = fit_xyz[sample_indices]
    remaining = np.ones(len(fit_points), dtype=bool)
    planes: list[dict[str, Any]] = []
    minimum_support = max(
        MIN_PLANE_POINTS,
        int(math.ceil(MIN_PLANE_POINT_FRACTION * len(fit_points))),
    )
    for plane_index in range(MAX_PLANES):
        indices = np.flatnonzero(remaining)
        if len(indices) < minimum_support:
            break
        subset = fit_points[indices]
        try:
            plane, inliers = _fit_ransac_plane(
                subset[:, 0],
                subset[:, 1],
                subset[:, 2],
                random_state=random_state + plane_index,
            )
        except (ValueError, ZeroDivisionError):
            break
        if int(inliers.sum()) < minimum_support:
            break
        plane["fit_sample_points"] = int(inliers.sum())
        planes.append(plane)
        remaining[indices[inliers]] = False

    assignments = np.full(len(all_xyz), -1, dtype=int)
    if not planes:
        return (
            [],
            assignments,
            {
                "input_points": len(all_xyz),
                "covered_fraction": 0.0,
                "rmse_m": math.nan,
                "median_absolute_residual_m": math.nan,
                "p95_absolute_residual_m": math.nan,
            },
        )

    for _ in range(2):
        predictions = np.column_stack(
            [plane_z(plane, all_xyz[:, 0], all_xyz[:, 1]) for plane in planes]
        )
        residuals = np.abs(predictions - all_xyz[:, 2, None])
        nearest = residuals.argmin(axis=1)
        nearest_residual = residuals[np.arange(len(all_xyz)), nearest]
        covered = nearest_residual <= VALIDATION_RESIDUAL_THRESHOLD_M
        refined: list[dict[str, Any]] = []
        minimum_full_support = max(
            MIN_PLANE_POINTS,
            int(math.ceil(MIN_PLANE_POINT_FRACTION * len(all_xyz))),
        )
        for old_index, plane in enumerate(planes):
            support = covered & (nearest == old_index)
            if int(support.sum()) < minimum_full_support:
                continue
            fitted = _fit_linear_plane(
                all_xyz[support, 0], all_xyz[support, 1], all_xyz[support, 2]
            )
            fitted["fit_sample_points"] = plane["fit_sample_points"]
            refined.append(fitted)
        planes = refined
        if not planes:
            break

    if not planes:
        return (
            [],
            assignments,
            {
                "input_points": len(all_xyz),
                "covered_fraction": 0.0,
                "rmse_m": math.nan,
                "median_absolute_residual_m": math.nan,
                "p95_absolute_residual_m": math.nan,
            },
        )
    predictions = np.column_stack(
        [plane_z(plane, all_xyz[:, 0], all_xyz[:, 1]) for plane in planes]
    )
    absolute_residuals = np.abs(predictions - all_xyz[:, 2, None])
    nearest = absolute_residuals.argmin(axis=1)
    nearest_residual = absolute_residuals[np.arange(len(all_xyz)), nearest]
    covered = nearest_residual <= VALIDATION_RESIDUAL_THRESHOLD_M
    assignments[covered] = nearest[covered]
    signed_residual = predictions[np.arange(len(all_xyz)), nearest] - all_xyz[:, 2]
    valid_residual = signed_residual[covered]
    for plane_index, plane in enumerate(planes):
        support = covered & (nearest == plane_index)
        plane["support_points"] = int(support.sum())
        plane["support_fraction"] = float(support.mean())
        plane["rmse_m"] = float(np.sqrt(np.mean(np.square(signed_residual[support]))))
        plane["median_absolute_residual_m"] = float(np.median(np.abs(signed_residual[support])))
    statistics = {
        "input_points": len(all_xyz),
        "covered_points": int(covered.sum()),
        "covered_fraction": float(covered.mean()),
        "rmse_m": (
            float(np.sqrt(np.mean(np.square(valid_residual)))) if valid_residual.size else math.nan
        ),
        "median_absolute_residual_m": (
            float(np.median(np.abs(valid_residual))) if valid_residual.size else math.nan
        ),
        "p95_absolute_residual_m": (
            float(np.percentile(np.abs(valid_residual), 95)) if valid_residual.size else math.nan
        ),
        "maximum_interplane_angle_degrees": maximum_interplane_angle(planes),
        "maximum_slope_degrees": max(plane["slope_degrees"] for plane in planes),
    }
    return planes, assignments, statistics


def _half_plane_region(
    region: Polygon | MultiPolygon,
    first: dict[str, Any],
    second: dict[str, Any],
) -> Polygon | MultiPolygon:
    """Keep the portion where the first plane is below the second plane."""
    a = first["a"] - second["a"]
    b = first["b"] - second["b"]
    c = (
        first["c"]
        - second["c"]
        - first["a"] * first["origin_x"]
        - first["b"] * first["origin_y"]
        + second["a"] * second["origin_x"]
        + second["b"] * second["origin_y"]
    )
    norm_squared = a * a + b * b
    if norm_squared < 1e-16:
        return region if c <= 0 else Polygon()
    divider = _plane_divider(region, first, second)
    if divider is None:
        return region if c <= 0 else Polygon()
    pieces = split(region, divider)
    kept: list[Polygon] = []
    for piece in pieces.geoms:
        for polygon in _polygon_parts(piece):
            representative = polygon.representative_point()
            value = a * representative.x + b * representative.y + c
            if value <= 1e-7:
                kept.append(polygon)
    if not kept:
        return Polygon()
    merged = unary_union(kept)
    return merged if isinstance(merged, (Polygon, MultiPolygon)) else Polygon()


def partition_roof(
    footprint: Polygon | MultiPolygon,
    planes: list[dict[str, Any]],
    points: np.ndarray,
    assignments: np.ndarray,
) -> tuple[list[Polygon | MultiPolygon], dict[str, Any]]:
    """Partition a footprint using the lower envelope of fitted planes."""
    regions: list[Polygon | MultiPolygon] = []
    for plane_index, plane in enumerate(planes):
        region: Polygon | MultiPolygon = footprint
        for other_index, other in enumerate(planes):
            if plane_index == other_index or region.is_empty:
                continue
            region = _half_plane_region(region, plane, other)
        regions.append(region)
    nonempty = [region for region in regions if not region.is_empty and region.area > 0.01]
    union = unary_union(nonempty) if nonempty else Polygon()
    area_coverage = float(union.area / max(footprint.area, 1e-9))
    if len(points):
        predictions = np.column_stack(
            [plane_z(plane, points[:, 0], points[:, 1]) for plane in planes]
        )
        lower_envelope = predictions.argmin(axis=1)
        surface_residuals = predictions[np.arange(len(points)), lower_envelope] - points[:, 2]
        surface_covered = np.abs(surface_residuals) <= VALIDATION_RESIDUAL_THRESHOLD_M
        fitted = assignments >= 0
        consistency = (
            float((lower_envelope[fitted] == assignments[fitted]).mean()) if fitted.any() else 0.0
        )
        surface_covered_fraction = float(surface_covered.mean())
        surface_rmse = (
            float(np.sqrt(np.mean(np.square(surface_residuals[surface_covered]))))
            if surface_covered.any()
            else math.nan
        )
    else:
        consistency = 0.0
        surface_covered_fraction = 0.0
        surface_rmse = math.nan
    ridge_count = 0
    ridge_length = 0.0
    for first_index, first_region in enumerate(regions):
        if first_region.is_empty:
            continue
        for second_index in range(first_index + 1, len(regions)):
            second_region = regions[second_index]
            if second_region.is_empty:
                continue
            divider = _plane_divider(footprint, planes[first_index], planes[second_index])
            if divider is None:
                continue
            shared = (
                divider.intersection(footprint)
                .intersection(first_region.buffer(1e-5))
                .intersection(second_region.buffer(1e-5))
            )
            segments = [line for line in _line_parts(shared) if line.length >= MIN_RIDGE_LENGTH_M]
            ridge_count += len(segments)
            ridge_length += sum(line.length for line in segments)
    return regions, {
        "region_count": len(nonempty),
        "footprint_area_coverage": area_coverage,
        "lower_envelope_assignment_consistency": consistency,
        "surface_covered_fraction": surface_covered_fraction,
        "surface_rmse_m": surface_rmse,
        "ridge_count": ridge_count,
        "ridge_length_m": float(ridge_length),
    }


def _polygon_with_z(
    geometry: Polygon | MultiPolygon,
    plane: dict[str, Any],
) -> Polygon | MultiPolygon:
    def convert(polygon: Polygon) -> Polygon:
        exterior = [(x, y, float(plane_z(plane, x, y))) for x, y, *_ in polygon.exterior.coords]
        holes = [
            [(x, y, float(plane_z(plane, x, y))) for x, y, *_ in ring.coords]
            for ring in polygon.interiors
        ]
        return Polygon(exterior, holes)

    parts = [convert(polygon) for polygon in _polygon_parts(geometry)]
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _line_with_z(line: LineString, first: dict[str, Any], second: dict[str, Any]) -> LineString:
    return LineString(
        [
            (
                x,
                y,
                float((plane_z(first, x, y) + plane_z(second, x, y)) / 2),
            )
            for x, y, *_ in line.coords
        ]
    )


def roof_surfaces_and_ridges(
    building_id: str,
    footprint: Polygon | MultiPolygon,
    planes: list[dict[str, Any]],
    regions: list[Polygon | MultiPolygon],
    status: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    surfaces: list[dict[str, Any]] = []
    ridges: list[dict[str, Any]] = []
    for plane_index, (plane, region) in enumerate(zip(planes, regions, strict=True)):
        if region.is_empty or region.area <= 0.01:
            continue
        surfaces.append(
            {
                "building_id": building_id,
                "plane_id": f"{building_id}-P{plane_index + 1:02d}",
                "lod2_status": status,
                "slope_degrees": plane["slope_degrees"],
                "aspect_degrees": plane["aspect_degrees"],
                "support_points": plane["support_points"],
                "support_fraction": plane["support_fraction"],
                "rmse_m": plane["rmse_m"],
                "a_dz_dx": plane["a"],
                "b_dz_dy": plane["b"],
                "origin_x": plane["origin_x"],
                "origin_y": plane["origin_y"],
                "origin_z": plane["c"],
                "surface_area_2d_m2": region.area,
                "geometry": _polygon_with_z(region, plane),
            }
        )
    for first_index, first_region in enumerate(regions):
        if first_region.is_empty:
            continue
        for second_index in range(first_index + 1, len(regions)):
            second_region = regions[second_index]
            if second_region.is_empty:
                continue
            divider = _plane_divider(footprint, planes[first_index], planes[second_index])
            if divider is None:
                continue
            shared = (
                divider.intersection(footprint)
                .intersection(first_region.buffer(1e-5))
                .intersection(second_region.buffer(1e-5))
            )
            for ridge_index, line in enumerate(_line_parts(shared), start=1):
                if line.length < MIN_RIDGE_LENGTH_M:
                    continue
                ridges.append(
                    {
                        "building_id": building_id,
                        "ridge_id": (
                            f"{building_id}-R{first_index + 1:02d}-{second_index + 1:02d}-"
                            f"{ridge_index:02d}"
                        ),
                        "plane_1": f"{building_id}-P{first_index + 1:02d}",
                        "plane_2": f"{building_id}-P{second_index + 1:02d}",
                        "length_m": line.length,
                        "geometry": _line_with_z(line, planes[first_index], planes[second_index]),
                    }
                )
    return surfaces, ridges


def _add_triangle(
    vertices: list[list[float]],
    faces: list[list[int]],
    coordinates: list[tuple[float, float]],
    z_values: list[float],
    *,
    reverse: bool,
) -> None:
    start = len(vertices)
    local = [
        [x - LOCAL_ORIGIN[0], y - LOCAL_ORIGIN[1], z]
        for (x, y), z in zip(coordinates, z_values, strict=True)
    ]
    signed_area = sum(
        local[index][0] * local[(index + 1) % 3][1] - local[(index + 1) % 3][0] * local[index][1]
        for index in range(3)
    )
    order = [0, 1, 2] if signed_area > 0 else [0, 2, 1]
    if reverse:
        order = list(reversed(order))
    vertices.extend(local)
    faces.append([start + index for index in order])


def lod2_mesh(
    footprint: Polygon | MultiPolygon,
    planes: list[dict[str, Any]],
    regions: list[Polygon | MultiPolygon],
    *,
    base_z: float,
) -> trimesh.Trimesh:
    """Create a closed lower-envelope roof mesh with walls and a flat base."""
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    active_planes = [
        plane
        for plane, region in zip(planes, regions, strict=True)
        if not region.is_empty and region.area > 0.01
    ]
    active_regions = [region for region in regions if not region.is_empty and region.area > 0.01]
    for plane, region in zip(active_planes, active_regions, strict=True):
        for polygon in _polygon_parts(region):
            for triangle in shapely.constrained_delaunay_triangles(polygon).geoms:
                coordinates = [(x, y) for x, y, *_ in list(triangle.exterior.coords)[:3]]
                z_values = [float(plane_z(plane, x, y)) for x, y in coordinates]
                _add_triangle(vertices, faces, coordinates, z_values, reverse=False)
        for polygon in _polygon_parts(region):
            for ring in [polygon.exterior, *polygon.interiors]:
                coordinates = list(ring.coords)
                for first, second in zip(coordinates[:-1], coordinates[1:], strict=True):
                    edge = LineString([first, second])
                    midpoint = edge.interpolate(0.5, normalized=True)
                    if footprint.boundary.distance(midpoint) > 1e-5:
                        continue
                    x1, y1 = first[:2]
                    x2, y2 = second[:2]
                    top1 = float(plane_z(plane, x1, y1))
                    top2 = float(plane_z(plane, x2, y2))
                    start = len(vertices)
                    vertices.extend(
                        [
                            [x1 - LOCAL_ORIGIN[0], y1 - LOCAL_ORIGIN[1], base_z],
                            [x2 - LOCAL_ORIGIN[0], y2 - LOCAL_ORIGIN[1], base_z],
                            [x2 - LOCAL_ORIGIN[0], y2 - LOCAL_ORIGIN[1], top2],
                            [x1 - LOCAL_ORIGIN[0], y1 - LOCAL_ORIGIN[1], top1],
                        ]
                    )
                    faces.extend([[start, start + 1, start + 2], [start, start + 2, start + 3]])
    for region in active_regions:
        for polygon in _polygon_parts(region):
            for triangle in shapely.constrained_delaunay_triangles(polygon).geoms:
                coordinates = [(x, y) for x, y, *_ in list(triangle.exterior.coords)[:3]]
                _add_triangle(
                    vertices,
                    faces,
                    coordinates,
                    [base_z, base_z, base_z],
                    reverse=True,
                )
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices),
        faces=np.asarray(faces),
        process=True,
    )
    mesh.merge_vertices(digits_vertex=5)
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    return mesh


def assess_lod2_buildings(
    buildings: gpd.GeoDataFrame,
    point_arrays: dict[str, np.ndarray],
) -> tuple[
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    dict[str, trimesh.Trimesh],
    dict[str, np.ndarray],
]:
    """Evaluate every building and reconstruct only roofs that pass strict gates."""
    status_records: list[dict[str, Any]] = []
    surface_records: list[dict[str, Any]] = []
    ridge_records: list[dict[str, Any]] = []
    accepted_meshes: dict[str, trimesh.Trimesh] = {}
    samples: dict[str, np.ndarray] = {}

    for _, building in buildings.iterrows():
        building_id = str(building["building_id"])
        points = point_arrays[building_id]
        candidate = bool(
            building["model_status"] == "modelled"
            and not building["boundary_clipped"]
            and building["roof_point_density_m2"] >= 5.0
            and building["roof_cell_coverage"] >= 0.65
            and building["roof_points_used"] >= 200
        )
        record = building.to_dict()
        record.update(
            {
                "lod2_candidate": candidate,
                "lod2_status": "LoD1 only",
                "output_lod": "LoD1" if building["model_status"] == "modelled" else "none",
                "roof_plane_count": 0,
                "detected_plane_count": 0,
                "fit_covered_fraction": math.nan,
                "fit_rmse_m": math.nan,
                "surface_covered_fraction": math.nan,
                "surface_rmse_m": math.nan,
                "fit_median_abs_residual_m": math.nan,
                "fit_p95_abs_residual_m": math.nan,
                "partition_consistency": math.nan,
                "roof_area_coverage": math.nan,
                "maximum_slope_degrees": math.nan,
                "maximum_interplane_angle_degrees": math.nan,
                "ridge_count": 0,
                "ridge_length_m": 0.0,
                "lod2_reason": "did not meet non-boundary source-support gate",
            }
        )
        if building["model_status"] != "modelled":
            record["lod2_status"] = "missing or outdated source data"
            record["lod2_reason"] = "Phase 6 height was withheld"
            status_records.append(record)
            continue
        if not candidate:
            if building["boundary_clipped"]:
                record["lod2_reason"] = "partial footprint at pilot boundary"
            status_records.append(record)
            continue

        seed = int(building_id.split("-")[-1]) * 101
        planes, assignments, fit = fit_roof_planes(points, random_state=seed)
        if not planes:
            record["lod2_status"] = "manual correction required"
            record["lod2_reason"] = "robust plane segmentation found no supported plane"
            status_records.append(record)
            continue
        regions, partition = partition_roof(building.geometry, planes, points[:, :3], assignments)
        active_pairs = [
            (plane, region)
            for plane, region in zip(planes, regions, strict=True)
            if not region.is_empty and region.area > 0.01
        ]
        active_planes = [plane for plane, _ in active_pairs]
        active_regions = [region for _, region in active_pairs]
        meaningful = bool(
            active_planes
            and max(plane["slope_degrees"] for plane in active_planes) >= MIN_LOD2_SLOPE_DEGREES
            and (
                len(active_planes) == 1
                or maximum_interplane_angle(active_planes) >= MIN_INTERPLANE_ANGLE_DEGREES
            )
        )
        mesh = lod2_mesh(
            building.geometry,
            active_planes,
            active_regions,
            base_z=float(building["base_z_ahd"]),
        )
        geometry_valid = bool(
            mesh.is_watertight and mesh.is_volume and partition["footprint_area_coverage"] >= 0.995
        )
        reliable = bool(
            meaningful
            and geometry_valid
            and partition["surface_covered_fraction"] >= 0.80
            and partition["surface_rmse_m"] <= 0.20
            and partition["lower_envelope_assignment_consistency"] >= 0.70
        )
        approximate = bool(
            meaningful
            and geometry_valid
            and partition["surface_covered_fraction"] >= 0.65
            and partition["surface_rmse_m"] <= 0.35
            and partition["lower_envelope_assignment_consistency"] >= 0.50
        )
        if reliable:
            status = "reliable LoD2"
            reason = "plane, residual, partition and solid-geometry gates passed"
        elif approximate:
            status = "approximate LoD2"
            reason = "minimum LoD2 gates passed; one or more reliable gates missed"
        elif not meaningful and partition["surface_covered_fraction"] >= 0.65:
            status = "LoD1 only"
            reason = "supported roof is effectively flat; LoD2 adds no material geometry"
        else:
            status = "manual correction required"
            reason = "roof planes or their spatial partition did not pass acceptance gates"

        record.update(
            {
                "lod2_status": status,
                "output_lod": "LoD2" if status in LOD2_STATUS_COLOURS else "LoD1",
                "roof_plane_count": len(active_planes),
                "detected_plane_count": len(planes),
                "fit_covered_fraction": fit["covered_fraction"],
                "fit_rmse_m": fit["rmse_m"],
                "surface_covered_fraction": partition["surface_covered_fraction"],
                "surface_rmse_m": partition["surface_rmse_m"],
                "fit_median_abs_residual_m": fit["median_absolute_residual_m"],
                "fit_p95_abs_residual_m": fit["p95_absolute_residual_m"],
                "partition_consistency": partition["lower_envelope_assignment_consistency"],
                "roof_area_coverage": partition["footprint_area_coverage"],
                "maximum_slope_degrees": max(plane["slope_degrees"] for plane in active_planes),
                "maximum_interplane_angle_degrees": maximum_interplane_angle(active_planes),
                "ridge_count": partition["ridge_count"],
                "ridge_length_m": partition["ridge_length_m"],
                "lod2_reason": reason,
            }
        )
        if status in LOD2_STATUS_COLOURS:
            accepted_meshes[building_id] = mesh
            surfaces, ridges = roof_surfaces_and_ridges(
                building_id,
                building.geometry,
                active_planes,
                active_regions,
                status,
            )
            surface_records.extend(surfaces)
            ridge_records.extend(ridges)

        sample_count = min(500, len(points))
        sample_indices = np.linspace(0, len(points) - 1, sample_count, dtype=int)
        sampled = points[sample_indices, :3]
        predictions = np.column_stack(
            [plane_z(plane, sampled[:, 0], sampled[:, 1]) for plane in planes]
        )
        nearest = np.abs(predictions - sampled[:, 2, None]).argmin(axis=1)
        predicted_z = predictions[np.arange(sample_count), nearest]
        samples[building_id] = np.column_stack(
            [sampled, nearest, predicted_z, predicted_z - sampled[:, 2]]
        )
        status_records.append(record)

    statuses = gpd.GeoDataFrame(status_records, geometry="geometry", crs=buildings.crs)
    surface_columns = [
        "building_id",
        "plane_id",
        "lod2_status",
        "slope_degrees",
        "aspect_degrees",
        "support_points",
        "support_fraction",
        "rmse_m",
        "a_dz_dx",
        "b_dz_dy",
        "origin_x",
        "origin_y",
        "origin_z",
        "surface_area_2d_m2",
        "geometry",
    ]
    ridge_columns = [
        "building_id",
        "ridge_id",
        "plane_1",
        "plane_2",
        "length_m",
        "geometry",
    ]
    surfaces = gpd.GeoDataFrame(surface_records, columns=surface_columns, crs=buildings.crs)
    ridges = gpd.GeoDataFrame(ridge_records, columns=ridge_columns, crs=buildings.crs)
    return statuses, surfaces, ridges, accepted_meshes, samples


def write_lod2_geopackage(
    statuses: gpd.GeoDataFrame,
    surfaces: gpd.GeoDataFrame,
    ridges: gpd.GeoDataFrame,
    destination: str | Path,
) -> Path:
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.part{output.suffix}")
    partial.unlink(missing_ok=True)
    try:
        statuses.to_file(
            partial,
            layer="building_status",
            driver="GPKG",
            engine="pyogrio",
        )
        if not surfaces.empty:
            surfaces.to_file(
                partial,
                layer="roof_surfaces",
                driver="GPKG",
                engine="pyogrio",
                mode="a",
            )
        if not ridges.empty:
            ridges.to_file(
                partial,
                layer="ridge_lines",
                driver="GPKG",
                engine="pyogrio",
                mode="a",
            )
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def write_fit_samples(samples: dict[str, np.ndarray], destination: str | Path) -> Path:
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.part{output.suffix}")
    partial.unlink(missing_ok=True)
    try:
        np.savez_compressed(
            partial,
            **{building_id.replace("-", "_"): values for building_id, values in samples.items()},
        )
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def load_fit_samples(path: str | Path) -> dict[str, np.ndarray]:
    with np.load(path) as archive:
        return {key.replace("_", "-"): archive[key] for key in archive.files}


def mixed_lod_meshes(
    statuses: gpd.GeoDataFrame,
    accepted_lod2: dict[str, trimesh.Trimesh],
) -> dict[str, trimesh.Trimesh]:
    lod1 = building_meshes(statuses)
    result: dict[str, trimesh.Trimesh] = {}
    for _, building in statuses.iterrows():
        building_id = str(building["building_id"])
        if building_id in accepted_lod2:
            mesh = accepted_lod2[building_id].copy()
            colour = LOD2_STATUS_COLOURS[str(building["lod2_status"])]
            mesh.visual.face_colors = np.tile(colour, (len(mesh.faces), 1))
        elif building_id in lod1:
            mesh = lod1[building_id]
            colour = CONFIDENCE_COLOURS[str(building["confidence"])]
            mesh.visual.face_colors = np.tile(colour, (len(mesh.faces), 1))
        else:
            continue
        mesh.metadata.update(
            {
                "building_id": building_id,
                "lod2_status": building["lod2_status"],
                "output_lod": building["output_lod"],
            }
        )
        result[building_id] = mesh
    return result


def write_mixed_lod_glb(
    meshes: dict[str, trimesh.Trimesh],
    destination: str | Path,
) -> Path:
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.part{output.suffix}")
    partial.unlink(missing_ok=True)
    try:
        scene = trimesh.Scene()
        for building_id, mesh in meshes.items():
            scene.add_geometry(mesh, node_name=building_id, geom_name=building_id)
        partial.write_bytes(trimesh.exchange.gltf.export_glb(scene))
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output
