"""Create a small, fictional GIS dataset for end-to-end workflow testing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, Polygon

SYNTHETIC_CRS = CRS.from_epsg(7856)
REFERENCE_LONGITUDE = 153.0137
REFERENCE_LATITUDE = -27.4975
SITE_SIZE_M = 500.0
RASTER_RESOLUTION_M = 5.0


@dataclass(frozen=True)
class SyntheticDataset:
    """In-memory terrain, building and utility layers for the Phase 2 test."""

    terrain: np.ndarray
    transform: Affine
    crs: CRS
    local_origin: tuple[float, float]
    size_m: float
    resolution_m: float
    buildings: gpd.GeoDataFrame
    utilities: gpd.GeoDataFrame
    utility_nodes: gpd.GeoDataFrame

    @property
    def width(self) -> int:
        """Number of terrain columns."""
        return int(self.terrain.shape[1])

    @property
    def height(self) -> int:
        """Number of terrain rows."""
        return int(self.terrain.shape[0])

    @property
    def x_centres_local(self) -> np.ndarray:
        """Raster-cell centre x coordinates in the local rendering frame."""
        return (np.arange(self.width) + 0.5) * self.resolution_m

    @property
    def y_centres_local_descending(self) -> np.ndarray:
        """Raster-cell centre y coordinates in north-to-south raster order."""
        return self.size_m - (np.arange(self.height) + 0.5) * self.resolution_m


def terrain_height(local_x: Any, local_y: Any) -> np.ndarray:
    """Evaluate the deterministic fictional terrain surface in metres AHD."""
    x = np.asarray(local_x, dtype=float)
    y = np.asarray(local_y, dtype=float)
    return 18.0 + 0.028 * x + 0.014 * y + 1.6 * np.sin(x / 82.0) * np.cos(y / 71.0)


def authoritative_to_local(
    coordinates: Any, local_origin: tuple[float, float]
) -> np.ndarray:
    """Translate authoritative eastings/northings to local rendering coordinates."""
    result = np.asarray(coordinates, dtype=float).copy()
    result[..., 0] -= local_origin[0]
    result[..., 1] -= local_origin[1]
    return result


def local_to_authoritative(
    coordinates: Any, local_origin: tuple[float, float]
) -> np.ndarray:
    """Translate local rendering coordinates back to authoritative coordinates."""
    result = np.asarray(coordinates, dtype=float).copy()
    result[..., 0] += local_origin[0]
    result[..., 1] += local_origin[1]
    return result


def _rectangle(
    bounds: tuple[float, float, float, float], local_origin: tuple[float, float]
) -> Polygon:
    x_min, y_min, x_max, y_max = bounds
    east, north = local_origin
    return Polygon(
        [
            (east + x_min, north + y_min),
            (east + x_max, north + y_min),
            (east + x_max, north + y_max),
            (east + x_min, north + y_max),
        ]
    )


def _line_with_depths(
    vertices: list[tuple[float, float, float]], local_origin: tuple[float, float]
) -> LineString:
    east, north = local_origin
    coordinates = []
    for x, y, depth in vertices:
        z = float(terrain_height(x, y) - depth)
        coordinates.append((east + x, north + y, z))
    return LineString(coordinates)


def create_synthetic_dataset(
    size_m: float = SITE_SIZE_M,
    resolution_m: float = RASTER_RESOLUTION_M,
) -> SyntheticDataset:
    """Build deterministic synthetic layers georeferenced near UQ St Lucia."""
    if size_m <= 0 or resolution_m <= 0:
        raise ValueError("size_m and resolution_m must be positive")
    cell_count = size_m / resolution_m
    if not cell_count.is_integer():
        raise ValueError("size_m must be an exact multiple of resolution_m")

    to_mga56 = Transformer.from_crs(4326, SYNTHETIC_CRS, always_xy=True)
    centre_easting, centre_northing = to_mga56.transform(
        REFERENCE_LONGITUDE, REFERENCE_LATITUDE
    )
    local_origin = (
        round(centre_easting - size_m / 2.0, 3),
        round(centre_northing - size_m / 2.0, 3),
    )

    width = height = int(cell_count)
    x_centres = (np.arange(width) + 0.5) * resolution_m
    y_centres_descending = size_m - (np.arange(height) + 0.5) * resolution_m
    x_grid, y_grid = np.meshgrid(x_centres, y_centres_descending)
    terrain = terrain_height(x_grid, y_grid).astype("float32")
    transform = from_origin(
        local_origin[0], local_origin[1] + size_m, resolution_m, resolution_m
    )

    building_specs = [
        {
            "building_id": "SYN-B001",
            "building_name": "Fictional Flat-Roof Laboratory",
            "bounds": (65.0, 295.0, 140.0, 370.0),
            "height_m": 18.0,
            "roof_type": "flat",
            "lod": "LoD1",
        },
        {
            "building_id": "SYN-B002",
            "building_name": "Fictional Pitched-Roof Hall",
            "bounds": (205.0, 255.0, 305.0, 335.0),
            "height_m": 12.0,
            "ridge_height_m": 19.0,
            "roof_type": "pitched",
            "lod": "LoD2",
        },
        {
            "building_id": "SYN-B003",
            "building_name": "Fictional Services Building",
            "bounds": (345.0, 115.0, 430.0, 190.0),
            "height_m": 10.0,
            "roof_type": "flat",
            "lod": "LoD1",
        },
    ]
    building_rows = []
    for spec in building_specs:
        x_min, y_min, x_max, y_max = spec["bounds"]
        ground_z = float(terrain_height((x_min + x_max) / 2, (y_min + y_max) / 2))
        eave_z = ground_z + float(spec["height_m"])
        ridge_z = ground_z + float(spec.get("ridge_height_m", spec["height_m"]))
        building_rows.append(
            {
                "building_id": spec["building_id"],
                "building_name": spec["building_name"],
                "ground_z_ahd": ground_z,
                "eave_z_ahd": eave_z,
                "ridge_z_ahd": ridge_z,
                "height_m": float(spec["height_m"]),
                "roof_type": spec["roof_type"],
                "lod": spec["lod"],
                "source": "synthetic_phase2",
                "confidence": "synthetic_test_only",
                "geometry": _rectangle(spec["bounds"], local_origin),
            }
        )
    buildings = gpd.GeoDataFrame(building_rows, geometry="geometry", crs=SYNTHETIC_CRS)

    utility_specs = [
        {
            "asset_id": "SYN-WAT-001",
            "network_type": "water",
            "diameter_m": 0.30,
            "vertices": [(20.0, 70.0, 1.4), (250.0, 70.0, 1.5), (480.0, 70.0, 1.6)],
        },
        {
            "asset_id": "SYN-SEW-001",
            "network_type": "sewer",
            "diameter_m": 0.45,
            "vertices": [(170.0, 20.0, 2.0), (170.0, 250.0, 2.5), (170.0, 480.0, 3.0)],
        },
        {
            "asset_id": "SYN-ELE-001",
            "network_type": "electrical",
            "diameter_m": 0.15,
            "vertices": [
                (25.0, 430.0, 0.9),
                (260.0, 430.0, 0.9),
                (430.0, 250.0, 1.0),
                (480.0, 250.0, 1.0),
            ],
        },
    ]
    utility_rows = []
    for spec in utility_specs:
        depths = [vertex[2] for vertex in spec["vertices"]]
        utility_rows.append(
            {
                "asset_id": spec["asset_id"],
                "network_type": spec["network_type"],
                "asset_type": "centreline",
                "diameter_m": spec["diameter_m"],
                "min_depth_m": min(depths),
                "max_depth_m": max(depths),
                "vertical_source": "synthetic_depth_below_surface",
                "confidence": "synthetic_test_only",
                "sensitivity": "fictional_no_restriction",
                "geometry": _line_with_depths(spec["vertices"], local_origin),
            }
        )
    utilities = gpd.GeoDataFrame(utility_rows, geometry="geometry", crs=SYNTHETIC_CRS)

    node_specs = [
        ("SYN-WAT-N01", "water", "valve", 250.0, 70.0, 1.5),
        ("SYN-SEW-N01", "sewer", "pit", 170.0, 250.0, 2.5),
        ("SYN-SEW-N02", "sewer", "pit", 170.0, 480.0, 3.0),
        ("SYN-ELE-N01", "electrical", "joint", 260.0, 430.0, 0.9),
        ("SYN-ELE-N02", "electrical", "pit", 430.0, 250.0, 1.0),
    ]
    east, north = local_origin
    node_rows = []
    for asset_id, network_type, asset_type, x, y, depth in node_specs:
        ground_z = float(terrain_height(x, y))
        asset_z = ground_z - depth
        node_rows.append(
            {
                "asset_id": asset_id,
                "network_type": network_type,
                "asset_type": asset_type,
                "ground_z_ahd": ground_z,
                "asset_z_ahd": asset_z,
                "depth_m": depth,
                "confidence": "synthetic_test_only",
                "sensitivity": "fictional_no_restriction",
                "geometry": Point(east + x, north + y, asset_z),
            }
        )
    utility_nodes = gpd.GeoDataFrame(node_rows, geometry="geometry", crs=SYNTHETIC_CRS)

    return SyntheticDataset(
        terrain=terrain,
        transform=transform,
        crs=SYNTHETIC_CRS,
        local_origin=local_origin,
        size_m=size_m,
        resolution_m=resolution_m,
        buildings=buildings,
        utilities=utilities,
        utility_nodes=utility_nodes,
    )


def dataset_metadata(dataset: SyntheticDataset) -> dict[str, Any]:
    """Return serialisable provenance and coordinate metadata."""
    east, north = dataset.local_origin
    return {
        "dataset": "Phase 2 synthetic 3D GIS workflow test",
        "synthetic": True,
        "authoritative": False,
        "warning": "Entirely fictional test geometry; do not use as campus asset information.",
        "crs": dataset.crs.to_string(),
        "crs_wkt": dataset.crs.to_wkt(),
        "vertical_reference": "Synthetic elevations expressed as metres AHD for workflow testing",
        "reference_wgs84": {
            "longitude": REFERENCE_LONGITUDE,
            "latitude": REFERENCE_LATITUDE,
        },
        "local_origin_mga56": {"easting": east, "northing": north},
        "local_rendering_transform": {
            "x": "authoritative_easting - local_origin_easting",
            "y": "authoritative_northing - local_origin_northing",
            "z": "authoritative_elevation",
        },
        "extent_mga56": {
            "min_easting": east,
            "min_northing": north,
            "max_easting": east + dataset.size_m,
            "max_northing": north + dataset.size_m,
        },
        "terrain": {
            "width": dataset.width,
            "height": dataset.height,
            "resolution_m": dataset.resolution_m,
            "minimum_z_ahd": float(dataset.terrain.min()),
            "maximum_z_ahd": float(dataset.terrain.max()),
        },
        "feature_counts": {
            "buildings": len(dataset.buildings),
            "utility_lines": len(dataset.utilities),
            "utility_nodes": len(dataset.utility_nodes),
        },
    }


def write_synthetic_gis(dataset: SyntheticDataset, output_dir: str | Path) -> dict[str, Path]:
    """Write coordinate-preserving GeoTIFF, GeoPackage and metadata outputs."""
    output_directory = Path(output_dir)
    output_directory.mkdir(parents=True, exist_ok=True)

    terrain_path = output_directory / "synthetic_dtm_5m.tif"
    with rasterio.open(
        terrain_path,
        "w",
        driver="GTiff",
        height=dataset.height,
        width=dataset.width,
        count=1,
        dtype="float32",
        crs=dataset.crs,
        transform=dataset.transform,
        nodata=-9999.0,
        compress="deflate",
        predictor=3,
    ) as destination:
        destination.write(dataset.terrain, 1)
        destination.update_tags(
            SYNTHETIC="TRUE",
            AUTHORITATIVE="FALSE",
            VERTICAL_REFERENCE="Synthetic metres AHD",
        )

    geopackage_path = output_directory / "synthetic_scene.gpkg"
    if geopackage_path.exists():
        geopackage_path.unlink()
    layers = {
        "buildings": dataset.buildings,
        "utilities": dataset.utilities,
        "utility_nodes": dataset.utility_nodes,
    }
    for layer_name, frame in layers.items():
        pyogrio.write_dataframe(
            frame,
            geopackage_path,
            layer=layer_name,
            driver="GPKG",
            append=False,
        )

    metadata_path = output_directory / "synthetic_metadata.json"
    metadata_path.write_text(
        json.dumps(dataset_metadata(dataset), indent=2) + "\n", encoding="utf-8"
    )
    return {
        "terrain": terrain_path,
        "geopackage": geopackage_path,
        "metadata": metadata_path,
    }
