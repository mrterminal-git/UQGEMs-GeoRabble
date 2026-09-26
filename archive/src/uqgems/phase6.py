"""Run and validate Phase 6 conservative LoD1 building generation."""

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
import pandas as pd
import pyvista as pv
import rasterio
import trimesh

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.buildings import (
    CONFIDENCE_COLOURS,
    MAX_BUILDING_HEIGHT_M,
    MIN_BUILDING_HEIGHT_M,
    MIN_ROOF_POINTS,
    ROOF_OUTLIER_NMAD_MULTIPLIER,
    ROOF_SAMPLE_POINTS_PER_BUILDING,
    building_meshes,
    extract_building_points,
    load_roof_samples,
    model_lod1_buildings,
    prepare_footprints,
    read_terrain,
    save_roof_samples,
    write_lod1_geopackage,
    write_lod1_glb,
)
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG

PHASE6_SCHEMA_VERSION = 2
BUILDING_REGISTER_FIELDS = (
    "dataset",
    "source_paths",
    "source_sha256",
    "output_path",
    "output_sha256",
    "crs",
    "vertical_datum",
    "processing",
    "feature_count",
    "validation_status",
    "notes",
)
REQUIRED_BUILDING_FIELDS = {
    "building_id",
    "building_name",
    "ground_z_ahd",
    "roof_z_ahd",
    "height_m",
    "footprint_source",
    "height_method",
    "lidar_capture_date",
    "lod",
    "confidence",
    "geometry_status",
    "notes",
}


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _software_versions() -> dict[str, str]:
    pdal_result = subprocess.run(
        ["pdal", "--version"], check=True, capture_output=True, text=True
    )
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "geopandas": gpd.__version__,
        "rasterio": rasterio.__version__,
        "laspy": laspy.__version__,
        "trimesh": trimesh.__version__,
        "pyvista": pv.__version__,
        "pdal": pdal_result.stdout.strip(),
        "uqgems": version("uqgems"),
    }


def _signature(sources: dict[str, Path]) -> tuple[str, dict[str, Any]]:
    payload = {
        "schema_version": PHASE6_SCHEMA_VERSION,
        "source_sha256": {name: sha256(path) for name, path in sources.items()},
        "target_epsg": TARGET_EPSG,
        "local_origin": [float(value) for value in LOCAL_ORIGIN],
        "primary_footprint_layer": "qld_building_outlines",
        "name_hierarchy": ["OpenStreetMap specific name", "Queensland specific name"],
        "minimum_roof_points": MIN_ROOF_POINTS,
        "minimum_building_height_m": MIN_BUILDING_HEIGHT_M,
        "maximum_building_height_m": MAX_BUILDING_HEIGHT_M,
        "roof_outlier_nmad_multiplier": ROOF_OUTLIER_NMAD_MULTIPLIER,
        "roof_sample_points_per_building": ROOF_SAMPLE_POINTS_PER_BUILDING,
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialised).hexdigest(), payload


def _inspect_laz(path: Path) -> dict[str, Any]:
    with laspy.open(path) as source:
        crs = source.header.parse_crs()
        return {
            "epsg": crs.to_epsg() if crs else None,
            "point_count": int(source.header.point_count),
            "bounds": [
                float(source.header.mins[0]),
                float(source.header.mins[1]),
                float(source.header.maxs[0]),
                float(source.header.maxs[1]),
            ],
            "sha256": sha256(path),
        }


def _inspect_buildings(path: Path) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    buildings = gpd.read_file(path, layer="lod1_buildings")
    modelled = buildings["model_status"] == "modelled"
    info = {
        "epsg": buildings.crs.to_epsg() if buildings.crs else None,
        "features": len(buildings),
        "modelled": int(modelled.sum()),
        "withheld": int((~modelled).sum()),
        "valid_geometries": int(buildings.geometry.is_valid.sum()),
        "empty_geometries": int(buildings.geometry.is_empty.sum()),
        "named_buildings": int(buildings["building_name"].notna().sum()),
        "boundary_clipped": int(buildings["boundary_clipped"].sum()),
        "confidence_counts": {
            str(key): int(value)
            for key, value in buildings["confidence"].value_counts().sort_index().items()
        },
        "sha256": sha256(path),
    }
    return buildings, info


def _inspect_glb(path: Path) -> dict[str, Any]:
    scene = trimesh.load(path, force="scene")
    geometry = list(scene.geometry.values())
    vertices = int(sum(len(mesh.vertices) for mesh in geometry))
    faces = int(sum(len(mesh.faces) for mesh in geometry))
    bounds = scene.bounds.tolist() if vertices else None
    return {
        "geometry_count": len(geometry),
        "watertight_geometry_count": int(sum(mesh.is_watertight for mesh in geometry)),
        "positive_volume_geometry_count": int(sum(mesh.is_volume for mesh in geometry)),
        "vertices": vertices,
        "faces": faces,
        "bounds_local_xy_and_ahd_z": bounds,
        "sha256": sha256(path),
    }


def _hex_colour(confidence: str) -> str:
    colour = CONFIDENCE_COLOURS[confidence][:3]
    return "#" + "".join(f"{int(value):02x}" for value in colour)


def _display_name(value: Any) -> str:
    return "unnamed" if pd.isna(value) or not str(value).strip() else str(value)


def _read_raster(path: Path) -> np.ndarray:
    with rasterio.open(path) as source:
        data = source.read(1).astype(float)
        if source.nodata is not None:
            data[data == source.nodata] = np.nan
        return data


def _plan_figure(buildings: gpd.GeoDataFrame, height_path: Path, output: Path) -> Path:
    height = _read_raster(height_path)
    extent = [PILOT_AREA.west, PILOT_AREA.east, PILOT_AREA.south, PILOT_AREA.north]
    colour_limit = max(1.0, float(np.nanpercentile(height, 99)))
    figure, axis = plt.subplots(figsize=(9, 8), constrained_layout=True)
    image = axis.imshow(
        height,
        extent=extent,
        origin="upper",
        cmap="Greys",
        vmin=0,
        vmax=colour_limit,
        alpha=0.72,
    )
    for confidence in ("low", "medium", "high"):
        subset = buildings.loc[
            (buildings["confidence"] == confidence)
            & (buildings["model_status"] == "modelled")
        ]
        if subset.empty:
            continue
        subset.plot(
            ax=axis,
            facecolor=_hex_colour(confidence),
            edgecolor="white",
            linewidth=0.7,
            alpha=0.72,
            label=f"{confidence.title()} confidence ({len(subset)})",
        )
    withheld = buildings.loc[buildings["model_status"] != "modelled"]
    if not withheld.empty:
        withheld.boundary.plot(
            ax=axis, color="#c62828", linewidth=1.5, linestyle="--", label="Withheld"
        )
    axis.set(
        title="UQ pilot LoD1 footprint plan and confidence",
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    figure.colorbar(image, ax=axis, shrink=0.75, label="Background surface height (m)")
    axis.legend(loc="upper left", framealpha=0.92)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _roof_point_figure(
    buildings: gpd.GeoDataFrame,
    samples: dict[str, np.ndarray],
    output: Path,
) -> Path:
    available = [values for values in samples.values() if len(values)]
    points = np.concatenate(available) if available else np.empty((0, 4))
    figure, axis = plt.subplots(figsize=(9, 8), constrained_layout=True)
    if len(points):
        image = axis.scatter(
            points[:, 0],
            points[:, 1],
            c=points[:, 3],
            s=2.0,
            cmap="viridis",
            vmin=0,
            vmax=max(1.0, float(np.percentile(points[:, 3], 99))),
            linewidths=0,
        )
        figure.colorbar(image, ax=axis, shrink=0.76, label="Point height above DTM (m)")
    buildings.boundary.plot(ax=axis, color="#202020", linewidth=0.65)
    axis.set(
        xlim=(PILOT_AREA.west, PILOT_AREA.east),
        ylim=(PILOT_AREA.south, PILOT_AREA.north),
        title="Class-6 roof-point samples within primary footprints",
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _isolated_roof_figure(
    buildings: gpd.GeoDataFrame,
    samples: dict[str, np.ndarray],
    output: Path,
) -> Path:
    modelled = buildings.loc[buildings["model_status"] == "modelled"].copy()
    candidates: list[str] = []
    if not modelled.empty:
        high = modelled.loc[modelled["confidence"] == "high"]
        if not high.empty:
            candidates.append(str(high.sort_values("footprint_area_m2").iloc[-1]["building_id"]))
            median_area = float(high["footprint_area_m2"].median())
            central = high.iloc[(high["footprint_area_m2"] - median_area).abs().argsort()[:1]]
            candidates.append(str(central.iloc[0]["building_id"]))
        partial = modelled.loc[modelled["boundary_clipped"]]
        if not partial.empty:
            candidates.append(
                str(partial.sort_values("roof_cell_coverage").iloc[0]["building_id"])
            )
        candidates.append(
            str(modelled.sort_values("roof_cell_coverage").iloc[0]["building_id"])
        )
        candidates.extend(
            modelled.sort_values(
                ["confidence", "roof_cell_coverage", "roof_z_nmad_m"],
                ascending=[False, True, False],
            )["building_id"].astype(str)
        )
    candidates = list(dict.fromkeys(candidates))[:4]
    if not candidates:
        raise RuntimeError("No modelled buildings are available for roof-point examples")

    figure, axes = plt.subplots(2, 2, figsize=(11, 10), constrained_layout=True)
    axes_flat = axes.ravel()
    plotted = None
    for axis, building_id in zip(axes_flat, candidates, strict=False):
        building = buildings.loc[buildings["building_id"] == building_id].iloc[0]
        points = samples[building_id]
        plotted = axis.scatter(
            points[:, 0],
            points[:, 1],
            c=points[:, 3],
            s=10,
            cmap="viridis",
            linewidths=0,
        )
        gpd.GeoSeries([building.geometry], crs=buildings.crs).boundary.plot(
            ax=axis, color="black", linewidth=1.2
        )
        display_name = _display_name(building["building_name"])
        axis.set_title(
            f"{building_id}: {display_name}\n"
            f"h={building['height_m']:.1f} m, {building['confidence']} confidence"
        )
        axis.set_aspect("equal")
        axis.ticklabel_format(style="plain", useOffset=False)
    for axis in axes_flat[len(candidates) :]:
        axis.set_visible(False)
    if plotted is not None:
        figure.colorbar(
            plotted,
            ax=list(axes_flat),
            shrink=0.65,
            label="Height above local DTM (m)",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _height_figure(buildings: gpd.GeoDataFrame, output: Path) -> Path:
    modelled = buildings.loc[buildings["model_status"] == "modelled"]
    figure, axis = plt.subplots(figsize=(9, 5.5), constrained_layout=True)
    values = [
        modelled.loc[modelled["confidence"] == confidence, "height_m"].to_numpy()
        for confidence in ("high", "medium", "low")
    ]
    labels = ["High", "Medium", "Low"]
    colours = [_hex_colour(value.lower()) for value in labels]
    axis.hist(values, bins=15, stacked=True, label=labels, color=colours, edgecolor="white")
    axis.axvline(float(modelled["height_m"].median()), color="black", linestyle="--")
    axis.set(
        title="LoD1 building-height distribution",
        xlabel="Robust roof elevation minus median footprint DTM (m)",
        ylabel="Buildings",
    )
    axis.grid(axis="y", alpha=0.25)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _pyvista_mesh(mesh: trimesh.Trimesh) -> pv.PolyData:
    faces = np.column_stack(
        [np.full(len(mesh.faces), 3, dtype=np.int64), np.asarray(mesh.faces)]
    ).ravel()
    return pv.PolyData(np.asarray(mesh.vertices), faces)


def _oblique_figure(
    buildings: gpd.GeoDataFrame,
    terrain_path: Path,
    output: Path,
    *,
    camera: str,
) -> Path:
    terrain = _read_raster(terrain_path)
    step = 4
    x = (
        PILOT_AREA.west
        + (np.arange(terrain.shape[1]) + 0.5)
        - float(LOCAL_ORIGIN[0])
    )[::step]
    y = (
        PILOT_AREA.north
        - (np.arange(terrain.shape[0]) + 0.5)
        - float(LOCAL_ORIGIN[1])
    )[::step]
    xx, yy = np.meshgrid(x, y)
    vertical_exaggeration = 3.0
    grid = pv.StructuredGrid(xx, yy, terrain[::step, ::step] * vertical_exaggeration)
    plotter = pv.Plotter(off_screen=True, window_size=(1500, 950))
    plotter.set_background("#edf2f4")
    plotter.add_mesh(grid, cmap="terrain", opacity=0.72, show_scalar_bar=False)
    for building_id, mesh in building_meshes(buildings).items():
        exaggerated = mesh.copy()
        exaggerated.vertices[:, 2] *= vertical_exaggeration
        confidence = str(
            buildings.loc[buildings["building_id"] == building_id, "confidence"].iloc[0]
        )
        plotter.add_mesh(
            _pyvista_mesh(exaggerated),
            color=_hex_colour(confidence),
            smooth_shading=False,
        )
    camera_positions = {
        "northeast": [(650, 650, 420), (0, 0, 55), (0, 0, 1)],
        "southwest": [(-650, -650, 420), (0, 0, 55), (0, 0, 1)],
    }
    plotter.camera_position = camera_positions[camera]
    plotter.add_text(
        f"UQ pilot LoD1 - view from {camera} (3x vertical exaggeration)",
        position="upper_left",
        font_size=13,
        color="#202020",
    )
    plotter.show_bounds(
        grid="back",
        location="outer",
        xtitle="Local easting (m)",
        ytitle="Local northing (m)",
        ztitle="3x AHD elevation",
        color="#404040",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    plotter.show(screenshot=str(output), auto_close=True)
    return output


def _problem_tables(
    buildings: gpd.GeoDataFrame,
    metrics_path: Path,
    suspicious_path: Path,
    mismatch_path: Path,
) -> dict[str, Any]:
    attributes = pd.DataFrame(buildings.drop(columns="geometry"))
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    attributes.to_csv(metrics_path, index=False)

    suspicious_mask = (
        (buildings["model_status"] == "modelled")
        & (
            (buildings["height_m"] < 3.0)
            | (buildings["height_m"] > 40.0)
            | (buildings["roof_z_nmad_m"] > 2.0)
            | (buildings["bsm_edge_difference_m"].abs() > 2.0)
        )
    )
    suspicious_columns = [
        "building_id",
        "building_name",
        "height_m",
        "roof_z_nmad_m",
        "bsm_edge_difference_m",
        "confidence",
        "issues",
    ]
    suspicious = pd.DataFrame(buildings.loc[suspicious_mask, suspicious_columns])
    suspicious.to_csv(suspicious_path, index=False)

    issues: list[dict[str, Any]] = []
    for _, building in buildings.iterrows():
        evidence: list[str] = []
        if building["model_status"] != "modelled":
            evidence.append("LoD1 height withheld")
        if building["boundary_clipped"]:
            evidence.append("footprint intersects pilot boundary")
        if building["roof_cell_coverage"] < 0.25:
            evidence.append(f"roof-cell coverage={building['roof_cell_coverage']:.2f}")
        if abs(building["bsm_edge_difference_m"]) > 2.0:
            evidence.append(
                f"roof minus BSM edge={building['bsm_edge_difference_m']:.2f} m"
            )
        if evidence:
            issues.append(
                {
                    "building_id": building["building_id"],
                    "building_name": building["building_name"],
                    "review_category": "potentially incomplete or misaligned public source",
                    "evidence": "; ".join(evidence),
                    "recommended_action": (
                        "Compare with imagery/full audit LAZ; request current UQ footprint/BIM "
                        "if the building is presentation-critical."
                    ),
                }
            )
    mismatch_columns = [
        "building_id",
        "building_name",
        "review_category",
        "evidence",
        "recommended_action",
    ]
    mismatch = pd.DataFrame(issues, columns=mismatch_columns)
    mismatch.to_csv(mismatch_path, index=False)
    return {
        "building_metrics_rows": len(attributes),
        "suspicious_height_rows": len(suspicious),
        "missing_changed_or_misaligned_review_rows": len(mismatch),
    }


def _building_statistics(buildings: gpd.GeoDataFrame) -> dict[str, Any]:
    modelled = buildings.loc[buildings["model_status"] == "modelled"]
    return {
        "footprints": len(buildings),
        "modelled": len(modelled),
        "withheld": int((buildings["model_status"] != "modelled").sum()),
        "named": int(buildings["building_name"].notna().sum()),
        "boundary_clipped": int(buildings["boundary_clipped"].sum()),
        "confidence_counts": {
            str(key): int(value)
            for key, value in buildings["confidence"].value_counts().sort_index().items()
        },
        "modelled_confidence_counts": {
            str(key): int(value)
            for key, value in modelled["confidence"].value_counts().sort_index().items()
        },
        "height_m": {
            "minimum": float(modelled["height_m"].min()),
            "median": float(modelled["height_m"].median()),
            "maximum": float(modelled["height_m"].max()),
        },
        "roof_support": {
            "points_used": int(modelled["roof_points_used"].sum()),
            "median_points_per_building": float(modelled["roof_points_used"].median()),
            "median_density_points_m2": float(modelled["roof_point_density_m2"].median()),
            "median_cell_coverage": float(modelled["roof_cell_coverage"].median()),
            "median_roof_nmad_m": float(modelled["roof_z_nmad_m"].median()),
        },
        "bsm_comparison": {
            "median_difference_m": float(modelled["bsm_edge_difference_m"].median()),
            "median_absolute_difference_m": float(
                modelled["bsm_edge_difference_m"].abs().median()
            ),
            "p95_absolute_difference_m": float(
                modelled["bsm_edge_difference_m"].abs().quantile(0.95)
            ),
        },
    }


def _register_rows(
    root: Path,
    sources: dict[str, Path],
    outputs: dict[str, Path],
    building_info: dict[str, Any],
    glb_info: dict[str, Any],
) -> list[dict[str, Any]]:
    source_paths = "; ".join(_relative(path, root) for path in sources.values())
    source_hashes = "; ".join(f"{name}:{sha256(path)}" for name, path in sources.items())
    return [
        {
            "dataset": "Phase 6 authoritative LoD1 building attributes and footprints",
            "source_paths": source_paths,
            "source_sha256": source_hashes,
            "output_path": _relative(outputs["gpkg"], root),
            "output_sha256": building_info["sha256"],
            "crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "vertical_datum": "AHD",
            "processing": "Robust class-6 median roof elevation with footprint DTM ground",
            "feature_count": building_info["features"],
            "validation_status": "passed",
            "notes": "GIS source of truth; geometry is 2D with explicit AHD attributes.",
        },
        {
            "dataset": "Phase 6 LoD1 presentation mesh",
            "source_paths": _relative(outputs["gpkg"], root),
            "source_sha256": building_info["sha256"],
            "output_path": _relative(outputs["glb"], root),
            "output_sha256": glb_info["sha256"],
            "crs": "display-local XY derived from EPSG:7856",
            "vertical_datum": "AHD Z values retained",
            "processing": "Closed flat-roof block mesh; XY translated by recorded local origin",
            "feature_count": glb_info["geometry_count"],
            "validation_status": "passed",
            "notes": "Presentation output; recover authoritative XY with local_origin.json.",
        },
    ]


def _write_register(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=BUILDING_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_phase6(project_root: str | Path) -> dict[str, Any]:
    """Generate a conservative LoD1 model for all primary pilot footprints."""
    root = Path(project_root).resolve()
    sources = {
        "vectors": root
        / "data"
        / "interim"
        / "normalised"
        / "vectors"
        / "phase4_vectors_epsg7856.gpkg",
        "dtm": root / "data" / "interim" / "phase5" / "elevation" / "dtm_1m.tif",
        "height": root
        / "data"
        / "interim"
        / "phase5"
        / "elevation"
        / "height_above_ground.tif",
        "analysis_laz": root
        / "data"
        / "interim"
        / "phase5"
        / "pointcloud"
        / "uq_pilot_analysis_filtered.laz",
        "phase5_manifest": root
        / "data"
        / "interim"
        / "phase5"
        / "preparation_manifest.json",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Phase 6 needs the completed Phase 4/5 products. Missing: " + ", ".join(missing)
        )
    phase5 = json.loads(
        (root / "reports" / "tables" / "phase5_preparation.json").read_text(encoding="utf-8")
    )
    if phase5.get("status") != "passed":
        raise RuntimeError("Phase 5 validation report is not in passed state")

    output_root = root / "data" / "processed" / "lod1"
    outputs = {
        "gpkg": output_root / "lod1_buildings.gpkg",
        "glb": output_root / "uq_pilot_lod1.glb",
        "samples": output_root / "roof_point_samples.npz",
        "local_origin": output_root / "local_origin.json",
        "manifest": output_root / "lod1_manifest.json",
    }
    table_root = root / "reports" / "tables"
    tables = {
        "metrics": table_root / "phase6_building_metrics.csv",
        "suspicious": table_root / "phase6_suspicious_buildings.csv",
        "mismatch": table_root / "phase6_missing_changed_misaligned.csv",
        "summary": table_root / "phase6_lod1.json",
    }
    figure_root = root / "reports" / "figures"
    figures = {
        "plan": figure_root / "phase6_lod1_plan.png",
        "roof_points": figure_root / "phase6_footprint_roof_points.png",
        "isolated_roofs": figure_root / "phase6_isolated_roof_examples.png",
        "height_distribution": figure_root / "phase6_building_height_distribution.png",
        "northeast": figure_root / "phase6_lod1_northeast.png",
        "southwest": figure_root / "phase6_lod1_southwest.png",
    }
    signature, signature_payload = _signature(sources)
    previous_manifest: dict[str, Any] = {}
    if outputs["manifest"].is_file():
        previous_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    main_names = ("gpkg", "glb", "samples")
    recorded = previous_manifest.get("outputs", {})
    cache_reused = bool(
        previous_manifest.get("configuration_signature") == signature
        and all(
            outputs[name].is_file()
            and recorded.get(_relative(outputs[name], root)) == sha256(outputs[name])
            for name in main_names
        )
    )

    processing_statistics: dict[str, Any]
    if cache_reused:
        buildings = gpd.read_file(outputs["gpkg"], layer="lod1_buildings")
        samples = load_roof_samples(outputs["samples"])
        processing_statistics = previous_manifest["processing_statistics"]
    else:
        footprints = prepare_footprints(sources["vectors"])
        terrain, transform = read_terrain(sources["dtm"])
        point_arrays, point_assignment = extract_building_points(
            sources["analysis_laz"], footprints, terrain
        )
        buildings, samples = model_lod1_buildings(
            footprints, point_arrays, terrain, transform
        )
        write_lod1_geopackage(buildings, outputs["gpkg"])
        save_roof_samples(samples, outputs["samples"])
        write_lod1_glb(buildings, outputs["glb"])
        processing_statistics = {
            "point_assignment": point_assignment,
            "building_model": _building_statistics(buildings),
        }

    local_origin = {
        "authoritative_horizontal_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_datum": "AHD",
        "origin": {
            "easting_m": float(LOCAL_ORIGIN[0]),
            "northing_m": float(LOCAL_ORIGIN[1]),
            "elevation_m": float(LOCAL_ORIGIN[2]),
        },
        "mesh_formula": (
            "mesh_x = authoritative_easting - origin_easting; "
            "mesh_y = authoritative_northing - origin_northing; mesh_z = AHD elevation"
        ),
        "inverse_formula": (
            "authoritative_easting = mesh_x + origin_easting; "
            "authoritative_northing = mesh_y + origin_northing; AHD elevation = mesh_z"
        ),
    }
    _write_json(outputs["local_origin"], local_origin)

    buildings, building_info = _inspect_buildings(outputs["gpkg"])
    glb_info = _inspect_glb(outputs["glb"])
    laz_info = _inspect_laz(sources["analysis_laz"])
    problem_counts = _problem_tables(
        buildings,
        tables["metrics"],
        tables["suspicious"],
        tables["mismatch"],
    )
    _plan_figure(buildings, sources["height"], figures["plan"])
    _roof_point_figure(buildings, samples, figures["roof_points"])
    _isolated_roof_figure(buildings, samples, figures["isolated_roofs"])
    _height_figure(buildings, figures["height_distribution"])
    _oblique_figure(buildings, sources["dtm"], figures["northeast"], camera="northeast")
    _oblique_figure(buildings, sources["dtm"], figures["southwest"], camera="southwest")

    modelled = buildings.loc[buildings["model_status"] == "modelled"]
    assignment = processing_statistics["point_assignment"]
    model_stats = processing_statistics["building_model"]
    sample_ids = set(samples)
    output_hashes = {
        _relative(outputs[name], root): sha256(outputs[name]) for name in main_names
    }
    checks = {
        "phase5_validation_passed": phase5["status"] == "passed",
        "analysis_laz_crs_is_epsg_7856": laz_info["epsg"] == TARGET_EPSG,
        "complete_primary_footprint_inventory": len(buildings) == 61,
        "building_ids_are_unique": buildings["building_id"].is_unique,
        "all_output_geometries_are_valid": building_info["valid_geometries"]
        == building_info["features"],
        "all_output_geometries_are_nonempty": building_info["empty_geometries"] == 0,
        "building_output_crs_is_epsg_7856": building_info["epsg"] == TARGET_EPSG,
        "required_building_fields_present": REQUIRED_BUILDING_FIELDS.issubset(
            buildings.columns
        ),
        "modelled_building_fraction_at_least_90_percent": len(modelled)
        / max(len(buildings), 1)
        >= 0.90,
        "modelled_buildings_have_sufficient_roof_points": bool(
            (modelled["roof_points_used"] >= MIN_ROOF_POINTS).all()
        ),
        "modelled_heights_are_plausible": bool(
            modelled["height_m"].between(
                MIN_BUILDING_HEIGHT_M, MAX_BUILDING_HEIGHT_M, inclusive="both"
            ).all()
        ),
        "modelled_roofs_are_above_ground": bool(
            (modelled["roof_z_ahd"] > modelled["ground_z_ahd"]).all()
        ),
        "confidence_categories_are_declared": set(buildings["confidence"]).issubset(
            CONFIDENCE_COLOURS
        ),
        "most_class6_points_are_assigned": assignment[
            "class6_points_assigned_to_primary_footprints"
        ]
        / max(assignment["class6_points_in_analysis_cloud"], 1)
        >= 0.80,
        "roof_samples_cover_every_modelled_building": set(modelled["building_id"]).issubset(
            sample_ids
        ),
        "bsm_comparison_is_consistent": model_stats["bsm_comparison"][
            "median_absolute_difference_m"
        ]
        < 2.0,
        "glb_has_one_mesh_per_modelled_building": glb_info["geometry_count"]
        == len(modelled),
        "every_glb_building_mesh_is_watertight": glb_info["watertight_geometry_count"]
        == len(modelled),
        "every_glb_building_mesh_has_positive_volume": glb_info[
            "positive_volume_geometry_count"
        ]
        == len(modelled),
        "glb_contains_faces": glb_info["faces"] > 0,
        "glb_local_xy_extent_is_numerically_safe": bool(
            glb_info["bounds_local_xy_and_ahd_z"]
            and np.max(np.abs(np.asarray(glb_info["bounds_local_xy_and_ahd_z"])[:, :2]))
            < 1_000
        ),
        "building_metrics_table_is_complete": problem_counts["building_metrics_rows"]
        == len(buildings),
        "fixed_validation_figures_created": all(path.is_file() for path in figures.values()),
    }

    register = _write_register(
        root / "data" / "building_model_register.csv",
        _register_rows(root, sources, outputs, building_info, glb_info),
    )
    manifest = {
        "configuration_signature": signature,
        "signature_inputs": signature_payload,
        "outputs": output_hashes,
        "processing_statistics": processing_statistics,
    }
    if all(checks.values()):
        _write_json(outputs["manifest"], manifest)

    summary = {
        "phase": 6,
        "status": "passed" if all(checks.values()) else "failed",
        "cache_reused": cache_reused,
        "scope": "complete 500 m by 500 m UQ St Lucia public-data pilot",
        "model_type": "conservative LoD1 flat-roof blocks",
        "authoritative_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_datum": "AHD",
        "configuration": signature_payload,
        "source_point_cloud": laz_info,
        "processing_statistics": processing_statistics,
        "building_output": building_info,
        "presentation_mesh": glb_info,
        "problem_reports": problem_counts,
        "local_origin": local_origin,
        "software": _software_versions(),
        "outputs": {
            **{name: _relative(path, root) for name, path in outputs.items()},
            "building_model_register": _relative(register, root),
            "tables": {name: _relative(path, root) for name, path in tables.items()},
            "figures": {name: _relative(path, root) for name, path in figures.items()},
        },
        "checks": checks,
        "limitations": [
            "LoD1 uses one robust flat roof elevation per primary outline; roof forms are "
            "not reconstructed.",
            "Fifteen buildings intersect the arbitrary pilot boundary and represent "
            "partial footprints.",
            "Public footprint and name sources are not UQ-authoritative and may differ "
            "from the 2019 LiDAR epoch.",
            "The GLB uses display-local XY coordinates; the GeoPackage is the "
            "authoritative GIS record.",
            "Automated confidence describes source support, not survey-grade positional accuracy.",
        ],
    }
    _write_json(tables["summary"], summary)
    summary["summary_report"] = _relative(tables["summary"], root)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 6 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase6(project_root)
    print(f"Phase 6 status: {summary['status']}")
    print(f"Cache reused: {summary['cache_reused']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
