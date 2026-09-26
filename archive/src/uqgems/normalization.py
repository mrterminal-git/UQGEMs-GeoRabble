"""Coordinate-normalisation operations shared by the Phase 4 workflow."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import pyproj
from pyproj import Transformer
from shapely.geometry import box

from uqgems.acquisition import PILOT_AREA, download_file, sha256

SOURCE_EPSG = 28356
TARGET_EPSG = 7856
GRID_NAME = "au_icsm_GDA94_GDA2020_conformal_and_distortion.tif"
GRID_URL = f"https://cdn.proj.org/{GRID_NAME}"
GRID_README_NAME = "au_icsm_README.txt"
GRID_README_URL = f"https://cdn.proj.org/{GRID_README_NAME}"
GRID_LICENCE = "Creative Commons Attribution 4.0"
EPSG_OPERATION = 8447
TRANSFORMATION_PIPELINE = (
    "+proj=pipeline "
    "+step +inv +proj=utm +zone=56 +south +ellps=GRS80 "
    f"+step +proj=hgridshift +grids={GRID_NAME} "
    "+step +proj=utm +zone=56 +south +ellps=GRS80"
)
LOCAL_ORIGIN = np.array(
    [
        (PILOT_AREA.west + PILOT_AREA.east) / 2,
        (PILOT_AREA.south + PILOT_AREA.north) / 2,
        0.0,
    ],
    dtype=float,
)


def ensure_transformation_grid(raw_geodesy_dir: str | Path) -> Path:
    """Cache the exact official grid used for every GDA94-to-GDA2020 transform."""
    grid_path = Path(raw_geodesy_dir) / GRID_NAME
    download_file(GRID_URL, grid_path)
    download_file(GRID_README_URL, grid_path.parent / GRID_README_NAME)
    if grid_path.stat().st_size < 1_000_000:
        raise RuntimeError(f"Downloaded transformation grid is unexpectedly small: {grid_path}")
    with grid_path.open("rb") as stream:
        byte_order = stream.read(2)
    if byte_order not in {b"II", b"MM"}:
        raise RuntimeError(f"Transformation grid is not a TIFF: {grid_path}")
    return grid_path


def proj_environment(grid_dir: str | Path) -> dict[str, str]:
    """Build an offline PROJ environment containing the project grid and base database."""
    environment = os.environ.copy()
    search_paths = [str(Path(grid_dir).resolve()), pyproj.datadir.get_data_dir()]
    environment["PROJ_DATA"] = os.pathsep.join(search_paths)
    environment["PROJ_NETWORK"] = "OFF"
    return environment


def grid_transformer(grid_path: str | Path) -> Transformer:
    """Create the explicitly selected conformal-and-distortion transformation."""
    grid = Path(grid_path).resolve()
    if grid.name != GRID_NAME or not grid.is_file():
        raise FileNotFoundError(f"Required transformation grid is unavailable: {grid}")
    pyproj.datadir.append_data_dir(str(grid.parent))
    pyproj.network.set_network_enabled(False)
    transformer = Transformer.from_pipeline(TRANSFORMATION_PIPELINE)
    test_x, test_y = transformer.transform(501_500.0, 6_958_500.0)
    if not np.isfinite([test_x, test_y]).all():
        raise RuntimeError("The conformal-and-distortion transformation could not use its grid")
    return transformer


def authoritative_to_local(coordinates: np.ndarray) -> np.ndarray:
    """Translate authoritative EPSG:7856 coordinates to the display origin."""
    points = np.asarray(coordinates, dtype=float)
    if points.shape[-1] not in {2, 3}:
        raise ValueError("Coordinates must end in either two or three components")
    return points - LOCAL_ORIGIN[: points.shape[-1]]


def local_to_authoritative(coordinates: np.ndarray) -> np.ndarray:
    """Reverse the display-only local-origin translation."""
    points = np.asarray(coordinates, dtype=float)
    if points.shape[-1] not in {2, 3}:
        raise ValueError("Coordinates must end in either two or three components")
    return points + LOCAL_ORIGIN[: points.shape[-1]]


def transformed_bounds(
    bounds: tuple[float, float, float, float],
    transformer: Transformer,
    *,
    edge_samples: int = 21,
) -> tuple[float, float, float, float]:
    """Densify and transform the edges of a bounding box."""
    west, south, east, north = bounds
    x_values = np.linspace(west, east, edge_samples)
    y_values = np.linspace(south, north, edge_samples)
    edge_x = np.concatenate(
        [x_values, x_values, np.full(edge_samples, west), np.full(edge_samples, east)]
    )
    edge_y = np.concatenate(
        [np.full(edge_samples, south), np.full(edge_samples, north), y_values, y_values]
    )
    target_x, target_y = transformer.transform(edge_x, edge_y)
    return min(target_x), min(target_y), max(target_x), max(target_y)


def _partial_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.stem}.part{destination.suffix}")


def reproject_dem(
    source: str | Path,
    destination: str | Path,
    grid_path: str | Path,
) -> dict[str, Any]:
    """Warp the DEM with GDAL using the explicit EPSG:8447 grid operation."""
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(destination_path)
    partial.unlink(missing_ok=True)
    command = [
        "gdalwarp",
        "-overwrite",
        "-s_srs",
        f"EPSG:{SOURCE_EPSG}",
        "-t_srs",
        f"EPSG:{TARGET_EPSG}",
        "-ct",
        TRANSFORMATION_PIPELINE,
        "-r",
        "bilinear",
        "-tr",
        "1",
        "1",
        "-tap",
        "-ot",
        "Float32",
        "-dstnodata",
        "-9999",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "TILED=YES",
        "-co",
        "PREDICTOR=3",
        "-co",
        "BIGTIFF=IF_SAFER",
        str(source_path),
        str(partial),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=proj_environment(Path(grid_path).parent),
        )
        partial.replace(destination_path)
    finally:
        partial.unlink(missing_ok=True)
    return {"command": command[:-2] + ["<source>", "<destination>"], "log": result.stdout}


def reproject_laz(
    source: str | Path,
    destination: str | Path,
    grid_path: str | Path,
    pipeline_record: str | Path,
    metadata_path: str | Path,
) -> dict[str, Any]:
    """Reproject a classified LAZ with PDAL's streaming pipeline."""
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(destination_path)
    partial.unlink(missing_ok=True)
    payload = {
        "pipeline": [
            {
                "type": "readers.las",
                "filename": str(source_path),
                "spatialreference": f"EPSG:{SOURCE_EPSG}",
            },
            {
                "type": "filters.projpipeline",
                "out_srs": f"EPSG:{TARGET_EPSG}",
                "coord_op": TRANSFORMATION_PIPELINE,
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
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=proj_environment(Path(grid_path).parent),
        )
        partial.replace(destination_path)
    finally:
        partial.unlink(missing_ok=True)
    return {"command": ["pdal", "pipeline", "<pipeline.json>", "--stream"], "log": result.stdout}


def normalise_vectors(
    qld_outlines_path: str | Path,
    qld_areas_path: str | Path,
    osm_path: str | Path,
    destination: str | Path,
) -> dict[str, int]:
    """Write footprint candidates and the pilot AOI to one EPSG:7856 GeoPackage."""
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(output)
    partial.unlink(missing_ok=True)

    outlines = gpd.read_file(qld_outlines_path)
    areas = gpd.read_file(qld_areas_path)
    if outlines.crs is None:
        outlines = outlines.set_crs(TARGET_EPSG)
    if areas.crs is None:
        areas = areas.set_crs(TARGET_EPSG)
    outlines = outlines.to_crs(TARGET_EPSG)
    areas = areas.to_crs(TARGET_EPSG)
    outlines["source_dataset"] = "Queensland generated building outlines"
    outlines["normalisation_operation"] = "validated in EPSG:7856; no coordinate change"
    areas["source_dataset"] = "Queensland topographic building areas"
    areas["normalisation_operation"] = "validated in EPSG:7856; no coordinate change"

    osm = pyogrio.read_dataframe(osm_path, layer="multipolygons")
    osm_buildings = osm.loc[osm["building"].notna()].copy()
    osm_buildings["source_dataset"] = "OpenStreetMap"
    osm_buildings["normalisation_operation"] = "reprojected EPSG:4326 to EPSG:7856"
    osm_buildings = osm_buildings.to_crs(TARGET_EPSG)

    aoi = gpd.GeoDataFrame(
        {
            "area_id": ["uq_st_lucia_pilot_500m"],
            "horizontal_crs": [f"EPSG:{TARGET_EPSG}"],
            "local_origin_easting": [LOCAL_ORIGIN[0]],
            "local_origin_northing": [LOCAL_ORIGIN[1]],
        },
        geometry=[box(*PILOT_AREA.projected_bounds)],
        crs=TARGET_EPSG,
    )

    layers = {
        "qld_building_outlines": outlines,
        "qld_building_areas": areas,
        "osm_buildings": osm_buildings,
        "pilot_aoi": aoi,
    }
    try:
        for index, (layer_name, frame) in enumerate(layers.items()):
            pyogrio.write_dataframe(
                frame,
                partial,
                layer=layer_name,
                driver="GPKG",
                append=index > 0,
            )
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return {name: len(frame) for name, frame in layers.items()}


def copy_target_crs_raster(source: str | Path, destination: str | Path) -> Path:
    """Copy an already-normalised raw raster into the derived workspace."""
    source_path = Path(source)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(output)
    partial.unlink(missing_ok=True)
    try:
        shutil.copy2(source_path, partial)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    if sha256(source_path) != sha256(output):
        raise RuntimeError("The normalised imagery copy differs from its already-EPSG:7856 source")
    return output
