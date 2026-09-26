"""Memory-bounded terrain and LiDAR preparation helpers for Phase 5."""

from __future__ import annotations

import copy
import json
import math
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

from uqgems.acquisition import PILOT_AREA
from uqgems.normalization import TARGET_EPSG

ANALYSIS_MIN_HEIGHT_M = -2.0
ANALYSIS_MAX_HEIGHT_M = 80.0
NOISE_CLASSES = (7, 18)
DISPLAY_TARGET_POINTS = 500_000
RASTER_RESOLUTION_M = 1.0
RASTER_WIDTH = 500
RASTER_HEIGHT = 500
RASTER_TRANSFORM = from_origin(
    PILOT_AREA.west,
    PILOT_AREA.north,
    RASTER_RESOLUTION_M,
    RASTER_RESOLUTION_M,
)
FLOAT_NODATA = -9999.0


ASPRS_CLASS_NAMES = {
    0: "Created, never classified",
    1: "Unclassified",
    2: "Ground",
    3: "Low vegetation",
    4: "Medium vegetation",
    5: "High vegetation",
    6: "Building",
    7: "Low point (noise)",
    8: "Reserved/model key",
    9: "Water",
    10: "Rail",
    11: "Road surface",
    12: "Reserved/overlap",
    13: "Wire guard",
    14: "Wire conductor",
    15: "Transmission tower",
    16: "Wire connector",
    17: "Bridge deck",
    18: "High noise",
}


def _partial_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.stem}.part{destination.suffix}")


def crop_dtm(source: str | Path, destination: str | Path) -> Path:
    """Resample the Phase 4 DTM to the exact 500-by-500-cell pilot grid."""
    source_path = Path(source).resolve()
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(output)
    partial.unlink(missing_ok=True)
    destination_data = np.full((RASTER_HEIGHT, RASTER_WIDTH), FLOAT_NODATA, dtype=np.float32)
    try:
        with rasterio.open(source_path) as source_raster:
            if source_raster.crs is None or source_raster.crs.to_epsg() != TARGET_EPSG:
                raise ValueError(f"DTM must use EPSG:{TARGET_EPSG}: {source_path}")
            reproject(
                source=source_raster.read(1),
                destination=destination_data,
                src_transform=source_raster.transform,
                src_crs=source_raster.crs,
                src_nodata=source_raster.nodata,
                dst_transform=RASTER_TRANSFORM,
                dst_crs=f"EPSG:{TARGET_EPSG}",
                dst_nodata=FLOAT_NODATA,
                resampling=Resampling.bilinear,
                num_threads=2,
            )
        write_float_raster(
            partial,
            destination_data,
            tags={
                "PHASE": "5",
                "PRODUCT": "DTM",
                "VERTICAL_DATUM": "AHD",
                "SOURCE": source_path.name,
            },
        )
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def crop_laz_with_pdal(
    source: str | Path,
    destination: str | Path,
    pipeline_record: str | Path,
    metadata_path: str | Path,
) -> dict[str, Any]:
    """Crop the full Phase 4 point cloud with a streamable PDAL pipeline."""
    source_path = Path(source).resolve()
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(output)
    partial.unlink(missing_ok=True)
    west, south, east, north = PILOT_AREA.projected_bounds
    payload = {
        "pipeline": [
            {"type": "readers.las", "filename": str(source_path)},
            {
                "type": "filters.crop",
                "bounds": f"([{west},{east}],[{south},{north}])",
            },
            {
                "type": "writers.las",
                "filename": str(partial),
                "a_srs": f"EPSG:{TARGET_EPSG}",
                "compression": True,
                "forward": "all",
                "software_id": "UQGEMs/PDAL",
            },
        ]
    }
    pipeline_path = Path(pipeline_record)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    metadata = Path(metadata_path)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    command = ["pdal", "pipeline", str(pipeline_path), "--stream", "--metadata", str(metadata)]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"PDAL crop failed: {result.stderr.strip()}")
        if not partial.is_file():
            raise RuntimeError("PDAL reported success but did not create the cropped LAZ")
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return {
        "command": ["pdal", "pipeline", "<pipeline.json>", "--stream"],
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def read_dtm(path: str | Path) -> tuple[np.ndarray, Any]:
    """Read a Phase 5 DTM and return data with invalid cells represented by NaN."""
    with rasterio.open(path) as source:
        data = source.read(1).astype(float)
        if source.nodata is not None:
            data[data == source.nodata] = np.nan
        return data, source.transform


def _terrain_at_points(
    x: np.ndarray,
    y: np.ndarray,
    terrain: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    columns = np.floor((x - PILOT_AREA.west) / RASTER_RESOLUTION_M).astype(np.int64)
    rows = np.floor((PILOT_AREA.north - y) / RASTER_RESOLUTION_M).astype(np.int64)
    inside = (
        (rows >= 0)
        & (rows < RASTER_HEIGHT)
        & (columns >= 0)
        & (columns < RASTER_WIDTH)
    )
    sampled = np.full(x.shape, np.nan, dtype=float)
    sampled[inside] = terrain[rows[inside], columns[inside]]
    return sampled, rows, columns


def filter_analysis_laz(
    source: str | Path,
    destination: str | Path,
    dtm_path: str | Path,
    *,
    chunk_size: int = 1_000_000,
) -> dict[str, Any]:
    """Remove declared noise and implausible DTM-relative heights in bounded memory."""
    source_path = Path(source).resolve()
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(output)
    partial.unlink(missing_ok=True)
    terrain, _ = read_dtm(dtm_path)
    statistics = Counter()
    retained_min_height = math.inf
    retained_max_height = -math.inf
    try:
        with laspy.open(source_path) as reader:
            output_header = copy.deepcopy(reader.header)
            output_header.generating_software = "UQGEMs Phase 5"
            with laspy.open(partial, mode="w", header=output_header, do_compress=True) as writer:
                for points in reader.chunk_iterator(chunk_size):
                    x = np.asarray(points.x)
                    y = np.asarray(points.y)
                    z = np.asarray(points.z)
                    classification = np.asarray(points.classification)
                    ground, _, _ = _terrain_at_points(x, y, terrain)
                    terrain_available = np.isfinite(ground)
                    noise = terrain_available & np.isin(classification, NOISE_CLASSES)
                    height = z - ground
                    below = (
                        terrain_available
                        & ~noise
                        & (height < ANALYSIS_MIN_HEIGHT_M)
                    )
                    above = (
                        terrain_available
                        & ~noise
                        & (height > ANALYSIS_MAX_HEIGHT_M)
                    )
                    outside = ~terrain_available
                    keep = terrain_available & ~noise & ~below & ~above

                    statistics["input_points"] += len(points)
                    statistics["removed_noise_class"] += int(noise.sum())
                    statistics["removed_below_height_threshold"] += int(below.sum())
                    statistics["removed_above_height_threshold"] += int(above.sum())
                    statistics["removed_outside_valid_dtm"] += int(outside.sum())
                    statistics["retained_points"] += int(keep.sum())
                    if keep.any():
                        retained_min_height = min(retained_min_height, float(height[keep].min()))
                        retained_max_height = max(retained_max_height, float(height[keep].max()))
                        writer.write_points(points[keep])
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)

    statistics["removed_total"] = statistics["input_points"] - statistics["retained_points"]
    statistics["retained_minimum_height_m"] = retained_min_height
    statistics["retained_maximum_height_m"] = retained_max_height
    statistics["minimum_allowed_height_m"] = ANALYSIS_MIN_HEIGHT_M
    statistics["maximum_allowed_height_m"] = ANALYSIS_MAX_HEIGHT_M
    statistics["noise_classes"] = list(NOISE_CLASSES)
    return dict(statistics)


def deterministic_display_sample(
    source: str | Path,
    destination: str | Path,
    *,
    target_points: int = DISPLAY_TARGET_POINTS,
    chunk_size: int = 1_000_000,
) -> dict[str, int]:
    """Write a deterministic global-stride sample without loading the LAZ at once."""
    source_path = Path(source).resolve()
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(output)
    partial.unlink(missing_ok=True)
    try:
        with laspy.open(source_path) as reader:
            input_count = int(reader.header.point_count)
            step = max(1, math.ceil(input_count / target_points))
            output_header = copy.deepcopy(reader.header)
            output_header.generating_software = "UQGEMs display sample"
            offset = 0
            written = 0
            with laspy.open(partial, mode="w", header=output_header, do_compress=True) as writer:
                for points in reader.chunk_iterator(chunk_size):
                    indices = np.arange(offset, offset + len(points), dtype=np.int64)
                    selected = indices % step == 0
                    writer.write_points(points[selected])
                    written += int(selected.sum())
                    offset += len(points)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return {
        "input_points": input_count,
        "target_points": target_points,
        "stride": step,
        "output_points": written,
    }


def laz_classification_counts(
    source: str | Path,
    *,
    chunk_size: int = 1_000_000,
) -> dict[str, dict[str, int | str]]:
    """Count LAS classifications without loading the point cloud into memory."""
    classifications: Counter[int] = Counter()
    with laspy.open(source) as reader:
        for points in reader.chunk_iterator(chunk_size):
            values, counts = np.unique(points.classification, return_counts=True)
            classifications.update(
                {
                    int(code): int(count)
                    for code, count in zip(values, counts, strict=True)
                }
            )
    return {
        str(code): {
            "name": ASPRS_CLASS_NAMES.get(code, f"Class {code}"),
            "count": count,
        }
        for code, count in sorted(classifications.items())
    }


def point_cloud_rasters(
    analysis_laz: str | Path,
    dtm_path: str | Path,
    *,
    chunk_size: int = 1_000_000,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Build density, DSM and ground-residual arrays from the filtered point cloud."""
    terrain, _ = read_dtm(dtm_path)
    point_count = np.zeros((RASTER_HEIGHT, RASTER_WIDTH), dtype=np.uint32)
    maximum_z = np.full((RASTER_HEIGHT, RASTER_WIDTH), -np.inf, dtype=float)
    ground_count = np.zeros((RASTER_HEIGHT, RASTER_WIDTH), dtype=np.uint32)
    ground_sum = np.zeros((RASTER_HEIGHT, RASTER_WIDTH), dtype=float)
    residual_chunks: list[np.ndarray] = []
    classifications: Counter[int] = Counter()

    with laspy.open(analysis_laz) as reader:
        for points in reader.chunk_iterator(chunk_size):
            x = np.asarray(points.x)
            y = np.asarray(points.y)
            z = np.asarray(points.z)
            classification = np.asarray(points.classification)
            sampled_terrain, rows, columns = _terrain_at_points(x, y, terrain)
            valid = np.isfinite(sampled_terrain)
            rows_valid = rows[valid]
            columns_valid = columns[valid]
            z_valid = z[valid]
            class_valid = classification[valid]
            np.add.at(point_count, (rows_valid, columns_valid), 1)
            np.maximum.at(maximum_z, (rows_valid, columns_valid), z_valid)

            unique_classes, class_counts = np.unique(class_valid, return_counts=True)
            classifications.update(
                {
                    int(code): int(count)
                    for code, count in zip(unique_classes, class_counts, strict=True)
                }
            )
            is_ground = class_valid == 2
            if is_ground.any():
                ground_rows = rows_valid[is_ground]
                ground_columns = columns_valid[is_ground]
                ground_z = z_valid[is_ground]
                np.add.at(ground_count, (ground_rows, ground_columns), 1)
                np.add.at(ground_sum, (ground_rows, ground_columns), ground_z)
                residual_chunks.append(ground_z - sampled_terrain[valid][is_ground])

    valid_terrain = np.isfinite(terrain)
    empty_surface = point_count == 0
    dsm = maximum_z
    dsm[empty_surface & valid_terrain] = terrain[empty_surface & valid_terrain]
    dsm[~valid_terrain] = np.nan
    raw_height = dsm - terrain
    height_above_ground = np.maximum(raw_height, 0.0)

    ground_mean = np.full_like(terrain, np.nan)
    has_ground = ground_count > 0
    ground_mean[has_ground] = ground_sum[has_ground] / ground_count[has_ground]
    ground_residual = ground_mean - terrain
    residuals = np.concatenate(residual_chunks) if residual_chunks else np.array([], dtype=float)
    if not residuals.size:
        raise RuntimeError("No class-2 ground points were available for DTM comparison")

    density_values = point_count[valid_terrain].astype(float)
    residual_statistics = {
        "points": int(residuals.size),
        "mean_m": float(residuals.mean()),
        "median_m": float(np.median(residuals)),
        "rmse_m": float(np.sqrt(np.mean(np.square(residuals)))),
        "nmad_m": float(1.4826 * np.median(np.abs(residuals - np.median(residuals)))),
        "p05_m": float(np.percentile(residuals, 5)),
        "p95_m": float(np.percentile(residuals, 95)),
        "maximum_absolute_m": float(np.max(np.abs(residuals))),
        "cells_with_ground": int(has_ground.sum()),
    }
    statistics = {
        "classification_counts": {
            str(code): {
                "name": ASPRS_CLASS_NAMES.get(code, f"Class {code}"),
                "count": count,
            }
            for code, count in sorted(classifications.items())
        },
        "density": {
            "mean_points_per_m2": float(density_values.mean()),
            "median_points_per_m2": float(np.median(density_values)),
            "p05_points_per_m2": float(np.percentile(density_values, 5)),
            "p95_points_per_m2": float(np.percentile(density_values, 95)),
            "maximum_points_per_m2": int(density_values.max()),
            "nonempty_cell_fraction": float((point_count[valid_terrain] > 0).mean()),
            "empty_cells_filled_from_dtm": int((empty_surface & valid_terrain).sum()),
        },
        "ground_dtm_comparison": residual_statistics,
        "height": {
            "minimum_raw_surface_minus_dtm_m": float(np.nanmin(raw_height)),
            "maximum_height_above_ground_m": float(np.nanmax(height_above_ground)),
            "cells_clamped_to_zero": int(((raw_height < 0) & valid_terrain).sum()),
        },
    }
    arrays = {
        "point_density": point_count,
        "ground_density": ground_count,
        "dsm": dsm,
        "surface_minus_dtm_raw": raw_height,
        "height_above_ground": height_above_ground,
        "ground_residual": ground_residual,
    }
    return arrays, statistics


def write_float_raster(
    path: str | Path,
    data: np.ndarray,
    *,
    tags: dict[str, str],
) -> Path:
    """Write a one-band float32 Phase 5 raster with standard spatial metadata."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(data, dtype=np.float32)
    encoded = np.where(np.isfinite(values), values, FLOAT_NODATA).astype(np.float32)
    with rasterio.open(
        output,
        "w",
        driver="GTiff",
        width=RASTER_WIDTH,
        height=RASTER_HEIGHT,
        count=1,
        dtype="float32",
        crs=f"EPSG:{TARGET_EPSG}",
        transform=RASTER_TRANSFORM,
        nodata=FLOAT_NODATA,
        compress="deflate",
        predictor=3,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as destination:
        destination.write(encoded, 1)
        destination.update_tags(**tags)
    return output


def write_count_raster(
    path: str | Path,
    data: np.ndarray,
    *,
    product: str,
) -> Path:
    """Write a one-band unsigned integer density raster; zero is a valid count."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output,
        "w",
        driver="GTiff",
        width=RASTER_WIDTH,
        height=RASTER_HEIGHT,
        count=1,
        dtype="uint32",
        crs=f"EPSG:{TARGET_EPSG}",
        transform=RASTER_TRANSFORM,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as destination:
        destination.write(np.asarray(data, dtype=np.uint32), 1)
        destination.update_tags(
            PHASE="5",
            PRODUCT=product,
            UNITS="points per 1 square metre cell",
        )
    return output


def hillshade(
    terrain: np.ndarray,
    *,
    azimuth_degrees: float = 315.0,
    altitude_degrees: float = 45.0,
) -> np.ndarray:
    """Calculate a conventional hillshade scaled from zero to one."""
    y_gradient, x_gradient = np.gradient(terrain, RASTER_RESOLUTION_M)
    slope = np.pi / 2 - np.arctan(np.hypot(x_gradient, y_gradient))
    aspect = np.arctan2(-x_gradient, y_gradient)
    azimuth = np.deg2rad(azimuth_degrees)
    altitude = np.deg2rad(altitude_degrees)
    shade = np.sin(altitude) * np.sin(slope) + np.cos(altitude) * np.cos(slope) * np.cos(
        azimuth - aspect
    )
    return np.clip((shade + 1) / 2, 0, 1)
