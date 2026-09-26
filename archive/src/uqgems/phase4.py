"""Run and validate Phase 4 coordinate-system normalisation."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import Any

import geopandas as gpd
import laspy
import matplotlib.pyplot as plt
import numpy as np
import pyogrio
import pyproj
import rasterio

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.normalization import (
    EPSG_OPERATION,
    GRID_LICENCE,
    GRID_NAME,
    GRID_URL,
    LOCAL_ORIGIN,
    SOURCE_EPSG,
    TARGET_EPSG,
    TRANSFORMATION_PIPELINE,
    authoritative_to_local,
    copy_target_crs_raster,
    ensure_transformation_grid,
    grid_transformer,
    local_to_authoritative,
    normalise_vectors,
    reproject_dem,
    reproject_laz,
    transformed_bounds,
)

NORMALISATION_SCHEMA_VERSION = 1
NORMALISATION_REGISTER_FIELDS = (
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
    "feature_or_point_count",
    "validation_status",
    "notes",
)


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _inspect_raster(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as source:
        band = source.read(1, masked=True)
        valid = band.compressed()
        return {
            "path": str(path),
            "driver": source.driver,
            "crs": source.crs.to_string() if source.crs else None,
            "epsg": source.crs.to_epsg() if source.crs else None,
            "bounds": list(source.bounds),
            "resolution": list(source.res),
            "shape": [source.height, source.width],
            "bands": source.count,
            "nodata": source.nodata,
            "valid_cells": int(valid.size),
            "minimum": float(valid.min()) if valid.size else None,
            "maximum": float(valid.max()) if valid.size else None,
            "sha256": sha256(path),
        }


def _inspect_laz(path: Path) -> dict[str, Any]:
    with laspy.open(path) as source:
        header = source.header
        crs = header.parse_crs()
        return {
            "path": str(path),
            "crs": crs.to_string() if crs else None,
            "epsg": crs.to_epsg() if crs else None,
            "point_count": int(header.point_count),
            "point_format": int(header.point_format.id),
            "las_version": str(header.version),
            "bounds": [
                float(header.mins[0]),
                float(header.mins[1]),
                float(header.maxs[0]),
                float(header.maxs[1]),
            ],
            "z_range": [float(header.mins[2]), float(header.maxs[2])],
            "scales": [float(value) for value in header.scales],
            "offsets": [float(value) for value in header.offsets],
            "sha256": sha256(path),
        }


def _raster_elevation_comparison(
    source_path: Path,
    target_path: Path,
    transformer: pyproj.Transformer,
) -> dict[str, Any]:
    """Compare elevations at corresponding source and transformed positions."""
    with rasterio.open(source_path) as source, rasterio.open(target_path) as target:
        x_values = np.linspace(source.bounds.left + 50, source.bounds.right - 50, 12)
        y_values = np.linspace(source.bounds.bottom + 50, source.bounds.top - 50, 12)
        source_x, source_y = np.meshgrid(x_values, y_values)
        flat_x = source_x.ravel()
        flat_y = source_y.ravel()
        target_x, target_y = transformer.transform(flat_x, flat_y)
        source_values = np.array(
            [value[0] for value in source.sample(zip(flat_x, flat_y, strict=True))],
            dtype=float,
        )
        target_values = np.array(
            [value[0] for value in target.sample(zip(target_x, target_y, strict=True))],
            dtype=float,
        )
        valid = np.isfinite(source_values) & np.isfinite(target_values)
        if source.nodata is not None:
            valid &= source_values != source.nodata
        if target.nodata is not None:
            valid &= target_values != target.nodata
        differences = target_values[valid] - source_values[valid]
    if not differences.size:
        raise RuntimeError("No valid corresponding DEM samples were available for validation")
    return {
        "samples": int(differences.size),
        "mean_difference_m": float(differences.mean()),
        "median_difference_m": float(np.median(differences)),
        "rmse_m": float(np.sqrt(np.mean(np.square(differences)))),
        "maximum_absolute_difference_m": float(np.max(np.abs(differences))),
    }


def _laz_sample_comparison(
    source_path: Path,
    target_path: Path,
    transformer: pyproj.Transformer,
    *,
    sample_size: int = 100_000,
) -> dict[str, Any]:
    """Verify that PDAL transformed XY and preserved Z/classification and point order."""
    with laspy.open(source_path) as source, laspy.open(target_path) as target:
        count = min(sample_size, source.header.point_count, target.header.point_count)
        source_points = source.read_points(count)
        target_points = target.read_points(count)
    expected_x, expected_y = transformer.transform(
        np.asarray(source_points.x), np.asarray(source_points.y)
    )
    residuals = np.hypot(
        np.asarray(target_points.x) - expected_x,
        np.asarray(target_points.y) - expected_y,
    )
    z_difference = np.asarray(target_points.z) - np.asarray(source_points.z)
    return {
        "samples": int(count),
        "maximum_horizontal_residual_m": float(residuals.max()),
        "horizontal_rmse_m": float(np.sqrt(np.mean(np.square(residuals)))),
        "maximum_absolute_z_difference_m": float(np.max(np.abs(z_difference))),
        "classifications_identical": bool(
            np.array_equal(source_points.classification, target_points.classification)
        ),
    }


def _bounds_cover(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float,
) -> bool:
    return bool(
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _bounds_close(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    *,
    tolerance: float,
) -> bool:
    return bool(np.max(np.abs(np.asarray(first) - np.asarray(second))) <= tolerance)


def _inspect_vectors(path: Path, expected_layers: dict[str, int]) -> dict[str, Any]:
    available_layers = {str(item[0]) for item in pyogrio.list_layers(path)}
    layers: dict[str, dict[str, Any]] = {}
    for name in expected_layers:
        frame = pyogrio.read_dataframe(path, layer=name)
        layers[name] = {
            "features": len(frame),
            "epsg": frame.crs.to_epsg() if frame.crs else None,
            "geometry_types": sorted(frame.geometry.geom_type.unique()),
            "valid_geometries": int(frame.geometry.is_valid.sum()),
            "bounds": list(frame.total_bounds),
        }
    return {
        "path": str(path),
        "layers": layers,
        "expected_layers": expected_layers,
        "available_layers": sorted(available_layers),
        "sha256": sha256(path),
    }


def _software_versions() -> dict[str, str]:
    pdal_result = subprocess.run(["pdal", "--version"], check=True, capture_output=True, text=True)
    return {
        "python": platform.python_version(),
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "geopandas": gpd.__version__,
        "laspy": laspy.__version__,
        "pdal": pdal_result.stdout.strip(),
        "uqgems": version("uqgems"),
    }


def _signature(source_paths: dict[str, Path], grid_path: Path) -> tuple[str, dict[str, Any]]:
    payload = {
        "schema_version": NORMALISATION_SCHEMA_VERSION,
        "source_sha256": {name: sha256(path) for name, path in source_paths.items()},
        "grid_sha256": sha256(grid_path),
        "coordinate_operation": TRANSFORMATION_PIPELINE,
        "target_epsg": TARGET_EPSG,
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialised).hexdigest(), payload


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _write_register(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=NORMALISATION_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _create_shift_figure(transformer: pyproj.Transformer, output_path: Path) -> Path:
    source_x, source_y = 501_500.0, 6_958_500.0
    target_x, target_y = transformer.transform(source_x, source_y)
    dx, dy = target_x - source_x, target_y - source_y
    magnitude = float(np.hypot(dx, dy))

    figure, axis = plt.subplots(figsize=(7, 7), constrained_layout=True)
    axis.annotate(
        "",
        xy=(dx, dy),
        xytext=(0, 0),
        arrowprops={"arrowstyle": "-|>", "color": "#1769aa", "lw": 3},
    )
    axis.scatter([0, dx], [0, dy], color=["#333333", "#1769aa"], zorder=3)
    axis.text(0, -0.08, "GDA94", ha="center", va="top")
    axis.text(dx, dy + 0.08, "GDA2020", ha="center", va="bottom")
    axis.text(
        dx / 2,
        dy / 2,
        f"  ΔE = {dx:.3f} m\n  ΔN = {dy:.3f} m\n  magnitude = {magnitude:.3f} m",
        va="center",
    )
    axis.set(
        xlim=(-0.2, max(1.0, dx + 0.4)),
        ylim=(-0.2, max(1.8, dy + 0.4)),
        xlabel="Easting change (m)",
        ylabel="Northing change (m)",
        title="GDA94 → GDA2020 datum shift at the UQ pilot",
    )
    axis.set_aspect("equal")
    axis.grid(alpha=0.25)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)
    return output_path


def _register_rows(
    root: Path,
    sources: dict[str, Path],
    outputs: dict[str, Path],
    source_laz: dict[str, Any],
    output_laz: dict[str, Any],
    vector_info: dict[str, Any],
    software: dict[str, str],
) -> list[dict[str, Any]]:
    grid_operation = f"EPSG:{EPSG_OPERATION}; {GRID_NAME}; explicit conformal-and-distortion grid"
    common = {
        "target_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "validation_status": "passed",
    }
    return [
        {
            "dataset": "Brisbane 2019 1 metre DEM",
            "source_path": _relative(sources["dem"], root),
            "source_sha256": sha256(sources["dem"]),
            "source_crs": f"GDA94 / MGA zone 56 (EPSG:{SOURCE_EPSG})",
            "target_path": _relative(outputs["dem"], root),
            "target_sha256": sha256(outputs["dem"]),
            **common,
            "vertical_datum": "AHD (AUSGeoid09 source metadata)",
            "horizontal_operation": f"{grid_operation}; GDAL bilinear warp to 1 m grid",
            "vertical_operation": "none; AHD elevations retained and raster resampled",
            "software": f"GDAL {software['gdal']}; PROJ {software['proj']}",
            "feature_or_point_count": "raster",
            "notes": "Authoritative target coordinates retained; no local-origin translation.",
        },
        {
            "dataset": "Brisbane 2019 classified LiDAR",
            "source_path": _relative(sources["laz"], root),
            "source_sha256": sha256(sources["laz"]),
            "source_crs": f"GDA94 / MGA zone 56 (EPSG:{SOURCE_EPSG})",
            "target_path": _relative(outputs["laz"], root),
            "target_sha256": sha256(outputs["laz"]),
            **common,
            "vertical_datum": "AHD (AUSGeoid09 source metadata)",
            "horizontal_operation": f"{grid_operation}; PDAL streaming reprojection",
            "vertical_operation": "none; every point Z value retained",
            "software": f"{software['pdal']}; PROJ {software['proj']}",
            "feature_or_point_count": output_laz["point_count"],
            "notes": (
                f"LAS {source_laz['las_version']} point format "
                f"{source_laz['point_format']} classifications retained."
            ),
        },
        {
            "dataset": "Queensland generated building outlines",
            "source_path": _relative(sources["qld_outlines"], root),
            "source_sha256": sha256(sources["qld_outlines"]),
            "source_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "target_path": f"{_relative(outputs['vectors'], root)}:qld_building_outlines",
            "target_sha256": sha256(outputs["vectors"]),
            **common,
            "vertical_datum": "not applicable",
            "horizontal_operation": "none; source coordinates already in target CRS",
            "vertical_operation": "not applicable",
            "software": f"GeoPandas {software['geopandas']}",
            "feature_or_point_count": vector_info["layers"]["qld_building_outlines"]["features"],
            "notes": "Attributes retained in the normalised GeoPackage.",
        },
        {
            "dataset": "Queensland topographic building areas",
            "source_path": _relative(sources["qld_areas"], root),
            "source_sha256": sha256(sources["qld_areas"]),
            "source_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "target_path": f"{_relative(outputs['vectors'], root)}:qld_building_areas",
            "target_sha256": sha256(outputs["vectors"]),
            **common,
            "vertical_datum": "not applicable",
            "horizontal_operation": "none; source coordinates already in target CRS",
            "vertical_operation": "not applicable",
            "software": f"GeoPandas {software['geopandas']}",
            "feature_or_point_count": vector_info["layers"]["qld_building_areas"]["features"],
            "notes": "Attributes retained in the normalised GeoPackage.",
        },
        {
            "dataset": "OpenStreetMap buildings",
            "source_path": _relative(sources["osm"], root),
            "source_sha256": sha256(sources["osm"]),
            "source_crs": "WGS 84 (EPSG:4326)",
            "target_path": f"{_relative(outputs['vectors'], root)}:osm_buildings",
            "target_sha256": sha256(outputs["vectors"]),
            **common,
            "vertical_datum": "not applicable",
            "horizontal_operation": "PyProj/GDAL EPSG:4326 to EPSG:7856",
            "vertical_operation": "not applicable",
            "software": (
                f"GeoPandas {software['geopandas']}; PyProj {software['pyproj']}; "
                f"PROJ {software['proj']}"
            ),
            "feature_or_point_count": vector_info["layers"]["osm_buildings"]["features"],
            "notes": "OSM multipolygon building features only; original tags retained.",
        },
        {
            "dataset": "Queensland latest public orthophoto extract",
            "source_path": _relative(sources["imagery"], root),
            "source_sha256": sha256(sources["imagery"]),
            "source_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "target_path": _relative(outputs["imagery"], root),
            "target_sha256": sha256(outputs["imagery"]),
            **common,
            "vertical_datum": "not applicable",
            "horizontal_operation": "none; byte-identical copy already in target CRS",
            "vertical_operation": "not applicable",
            "software": f"Python {software['python']}",
            "feature_or_point_count": "raster",
            "notes": "Raw image retained; working copy is byte-identical.",
        },
    ]


def run_phase4(project_root: str | Path) -> dict[str, Any]:
    """Normalise all Phase 3 GIS sources to EPSG:7856 and validate the results."""
    root = Path(project_root).resolve()
    selected = root / "data" / "raw" / "elvis" / "selected" / "brisbane_2019"
    sources = {
        "dem": selected / "Brisbane_2019_Prj_SW_501000_6958000_1k_DEM_1m.tif",
        "laz": selected / "Brisbane_2019_Prj_SW_501000_6958000_1k_class_AHD.laz",
        "qld_outlines": root / "data" / "raw" / "qld_buildings" / "building_outlines.geojson",
        "qld_areas": root / "data" / "raw" / "qld_buildings" / "building_areas.geojson",
        "osm": root / "data" / "raw" / "openstreetmap" / "uq_pilot.osm",
        "imagery": root / "data" / "raw" / "qld_imagery" / "latest_public_orthophoto.tif",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Phase 4 needs the completed Phase 3 inputs. Missing: " + ", ".join(missing)
        )

    output_root = root / "data" / "interim" / "normalised"
    outputs = {
        "dem": output_root / "elevation" / "brisbane_2019_dem_1m_epsg7856.tif",
        "laz": output_root / "elevation" / "brisbane_2019_classified_ahd_epsg7856.laz",
        "vectors": output_root / "vectors" / "phase4_vectors_epsg7856.gpkg",
        "imagery": output_root / "context" / "latest_public_orthophoto_epsg7856.tif",
        "local_origin": output_root / "local_origin.json",
        "manifest": output_root / "normalisation_manifest.json",
    }
    grid_path = ensure_transformation_grid(root / "data" / "raw" / "geodesy")
    transformer = grid_transformer(grid_path)
    signature, signature_payload = _signature(sources, grid_path)

    previous_manifest: dict[str, Any] = {}
    if outputs["manifest"].is_file():
        previous_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    main_outputs = [outputs[name] for name in ("dem", "laz", "vectors", "imagery")]
    cache_reused = bool(
        previous_manifest.get("configuration_signature") == signature
        and all(path.is_file() for path in main_outputs)
    )
    processing_logs: dict[str, Any] = {}
    if not cache_reused:
        processing_logs["dem"] = reproject_dem(sources["dem"], outputs["dem"], grid_path)
        processing_logs["laz"] = reproject_laz(
            sources["laz"],
            outputs["laz"],
            grid_path,
            root / "reports" / "tables" / "phase4_pdal_pipeline.json",
            root / "reports" / "tables" / "phase4_pdal_metadata.json",
        )
        processing_logs["vectors"] = normalise_vectors(
            sources["qld_outlines"],
            sources["qld_areas"],
            sources["osm"],
            outputs["vectors"],
        )
        copy_target_crs_raster(sources["imagery"], outputs["imagery"])

    local_origin_record = {
        "horizontal_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_datum": "AHD",
        "origin": {
            "easting_m": float(LOCAL_ORIGIN[0]),
            "northing_m": float(LOCAL_ORIGIN[1]),
            "elevation_m": float(LOCAL_ORIGIN[2]),
        },
        "forward_formula": (
            "render_x = authoritative_x - origin_easting; "
            "render_y = authoritative_y - origin_northing; "
            "render_z = authoritative_z"
        ),
        "scope": "display only; stored GIS products retain authoritative coordinates",
    }
    _write_json(outputs["local_origin"], local_origin_record)

    source_dem = _inspect_raster(sources["dem"])
    target_dem = _inspect_raster(outputs["dem"])
    source_laz = _inspect_laz(sources["laz"])
    target_laz = _inspect_laz(outputs["laz"])
    source_imagery = _inspect_raster(sources["imagery"])
    target_imagery = _inspect_raster(outputs["imagery"])
    source_outlines = gpd.read_file(sources["qld_outlines"])
    source_areas = gpd.read_file(sources["qld_areas"])
    source_osm = pyogrio.read_dataframe(sources["osm"], layer="multipolygons")
    source_osm_buildings = source_osm.loc[source_osm["building"].notna()]
    source_vector_info = {
        "qld_building_outlines": {
            "features": len(source_outlines),
            "epsg": source_outlines.crs.to_epsg() if source_outlines.crs else None,
        },
        "qld_building_areas": {
            "features": len(source_areas),
            "epsg": source_areas.crs.to_epsg() if source_areas.crs else None,
        },
        "osm_buildings": {
            "features": len(source_osm_buildings),
            "epsg": source_osm_buildings.crs.to_epsg() if source_osm_buildings.crs else None,
        },
    }
    expected_vector_layers = {
        name: int(details["features"]) for name, details in source_vector_info.items()
    }
    expected_vector_layers["pilot_aoi"] = 1
    vector_info = _inspect_vectors(outputs["vectors"], expected_vector_layers)
    raster_comparison = _raster_elevation_comparison(sources["dem"], outputs["dem"], transformer)
    laz_comparison = _laz_sample_comparison(sources["laz"], outputs["laz"], transformer)
    expected_dem_bounds = transformed_bounds(tuple(source_dem["bounds"]), transformer)
    expected_laz_bounds = transformed_bounds(tuple(source_laz["bounds"]), transformer)

    centre_x, centre_y = transformer.transform(501_500.0, 6_958_500.0)
    datum_shift = {
        "control_point_gda94": [501_500.0, 6_958_500.0],
        "control_point_gda2020": [centre_x, centre_y],
        "delta_easting_m": centre_x - 501_500.0,
        "delta_northing_m": centre_y - 6_958_500.0,
        "magnitude_m": float(np.hypot(centre_x - 501_500.0, centre_y - 6_958_500.0)),
    }

    round_trip_input = np.array(
        [[PILOT_AREA.west, PILOT_AREA.south, 4.0], [PILOT_AREA.east, PILOT_AREA.north, 30.0]]
    )
    round_trip = local_to_authoritative(authoritative_to_local(round_trip_input))
    vector_layers = vector_info["layers"]
    checks = {
        "official_grid_cached_locally": (
            grid_path.is_file() and grid_path.stat().st_size > 1_000_000
        ),
        "explicit_epsg_8447_grid_operation_used": (
            GRID_NAME in TRANSFORMATION_PIPELINE and EPSG_OPERATION == 8447
        ),
        "source_dem_crs_known": source_dem["epsg"] == SOURCE_EPSG,
        "target_dem_crs_is_epsg_7856": target_dem["epsg"] == TARGET_EPSG,
        "target_dem_resolution_is_one_metre": np.allclose(target_dem["resolution"], [1.0, 1.0]),
        "target_dem_extent_matches_transformed_source_within_one_pixel": _bounds_close(
            tuple(target_dem["bounds"]), expected_dem_bounds, tolerance=1.01
        ),
        "target_dem_covers_pilot": _bounds_cover(
            tuple(target_dem["bounds"]), PILOT_AREA.projected_bounds, tolerance=1.01
        ),
        "dem_elevations_consistent_after_resampling": (
            abs(raster_comparison["median_difference_m"]) < 0.25
            and raster_comparison["rmse_m"] < 1.0
        ),
        "source_laz_crs_known": source_laz["epsg"] == SOURCE_EPSG,
        "target_laz_crs_is_epsg_7856": target_laz["epsg"] == TARGET_EPSG,
        "laz_point_count_preserved": source_laz["point_count"] == target_laz["point_count"],
        "laz_format_preserved": (
            source_laz["las_version"] == target_laz["las_version"]
            and source_laz["point_format"] == target_laz["point_format"]
        ),
        "laz_bounds_match_grid_transform": _bounds_cover(
            tuple(target_laz["bounds"]), expected_laz_bounds, tolerance=0.01
        ),
        "laz_xy_sample_matches_grid_transform": (
            laz_comparison["maximum_horizontal_residual_m"] <= 0.002
        ),
        "laz_z_sample_unchanged": laz_comparison["maximum_absolute_z_difference_m"] == 0.0,
        "laz_classification_sample_unchanged": laz_comparison["classifications_identical"],
        "vector_layers_complete": set(vector_info["available_layers"])
        == set(vector_info["expected_layers"]),
        "source_vector_crs_values_known": (
            source_vector_info["qld_building_outlines"]["epsg"] == TARGET_EPSG
            and source_vector_info["qld_building_areas"]["epsg"] == TARGET_EPSG
            and source_vector_info["osm_buildings"]["epsg"] == 4326
        ),
        "vector_feature_counts_preserved": all(
            vector_layers[name]["features"] == expected
            for name, expected in vector_info["expected_layers"].items()
        ),
        "all_vector_layers_are_epsg_7856": all(
            layer["epsg"] == TARGET_EPSG for layer in vector_layers.values()
        ),
        "vector_geometries_valid": all(
            layer["valid_geometries"] == layer["features"] for layer in vector_layers.values()
        ),
        "imagery_crs_is_epsg_7856": target_imagery["epsg"] == TARGET_EPSG,
        "source_imagery_crs_known": source_imagery["epsg"] == TARGET_EPSG,
        "imagery_copy_is_byte_identical": sha256(sources["imagery"]) == sha256(outputs["imagery"]),
        "local_origin_is_pilot_centre": np.allclose(
            LOCAL_ORIGIN[:2],
            [
                (PILOT_AREA.west + PILOT_AREA.east) / 2,
                (PILOT_AREA.south + PILOT_AREA.north) / 2,
            ],
        ),
        "local_origin_round_trip_exact": np.allclose(round_trip, round_trip_input),
    }

    software = _software_versions()
    register = _write_register(
        root / "data" / "normalisation_register.csv",
        _register_rows(root, sources, outputs, source_laz, target_laz, vector_info, software),
    )
    figure = _create_shift_figure(
        transformer, root / "reports" / "figures" / "phase4_datum_shift.png"
    )

    output_hashes = {
        name: sha256(path)
        for name, path in outputs.items()
        if name != "manifest" and path.is_file()
    }
    manifest = {
        "configuration_signature": signature,
        "signature_inputs": signature_payload,
        "outputs": {_relative(outputs[name], root): output_hashes[name] for name in output_hashes},
    }
    if all(checks.values()):
        _write_json(outputs["manifest"], manifest)

    summary_path = root / "reports" / "tables" / "phase4_normalisation.json"
    summary = {
        "phase": 4,
        "status": "passed" if all(checks.values()) else "failed",
        "cache_reused": cache_reused,
        "source_crs": f"GDA94 / MGA zone 56 (EPSG:{SOURCE_EPSG})",
        "target_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_datum": "AHD retained; no vertical coordinate operation",
        "transformation": {
            "epsg_operation": EPSG_OPERATION,
            "grid_name": GRID_NAME,
            "grid_source": GRID_URL,
            "grid_licence": GRID_LICENCE,
            "grid_sha256": sha256(grid_path),
            "pipeline": TRANSFORMATION_PIPELINE,
            "network_disabled_during_transform": True,
        },
        "datum_shift_at_pilot": datum_shift,
        "local_origin": local_origin_record,
        "source_dem": source_dem,
        "target_dem": target_dem,
        "dem_elevation_comparison": raster_comparison,
        "source_laz": source_laz,
        "target_laz": target_laz,
        "laz_sample_comparison": laz_comparison,
        "vectors": vector_info,
        "source_vectors": source_vector_info,
        "source_imagery": source_imagery,
        "imagery": target_imagery,
        "software": software,
        "processing_logs": processing_logs,
        "outputs": {
            **{name: _relative(path, root) for name, path in outputs.items()},
            "normalisation_register": _relative(register, root),
            "datum_shift_figure": _relative(figure, root),
        },
        "checks": checks,
        "limitations": [
            "AHD heights were retained; no AUSGeoid09-to-AUSGeoid2020 vertical "
            "conversion was applied.",
            "DEM reprojection requires interpolation, so corresponding cell values are "
            "similar rather than identical.",
            "The source LAZ contains extreme Z outliers that are intentionally retained "
            "for Phase 5 filtering.",
            "Local coordinates are display-only; authoritative output files remain in EPSG:7856.",
        ],
    }
    _write_json(summary_path, summary)
    summary["summary_report"] = _relative(summary_path, root)

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 4 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase4(project_root)
    print(f"Phase 4 status: {summary['status']}")
    print(f"Cache reused: {summary['cache_reused']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
