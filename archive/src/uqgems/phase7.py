"""Run and validate Phase 7 selective LoD2 roof reconstruction."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyogrio
import pyvista as pv
import rasterio
import trimesh
from matplotlib.patches import Patch

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.buildings import extract_building_points, read_terrain
from uqgems.lod2 import (
    LOD2_STATUS_COLOURS,
    MAX_FIT_POINTS,
    MAX_PLANES,
    MIN_INTERPLANE_ANGLE_DEGREES,
    MIN_LOD2_SLOPE_DEGREES,
    MIN_PLANE_POINT_FRACTION,
    MIN_PLANE_POINTS,
    RANSAC_RESIDUAL_THRESHOLD_M,
    VALIDATION_RESIDUAL_THRESHOLD_M,
    assess_lod2_buildings,
    load_fit_samples,
    mixed_lod_meshes,
    write_fit_samples,
    write_lod2_geopackage,
    write_mixed_lod_glb,
)
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG
from uqgems.phase6 import _inspect_glb, _pyvista_mesh, _software_versions

PHASE7_SCHEMA_VERSION = 3
LOD2_STATUSES = {
    "reliable LoD2",
    "approximate LoD2",
    "manual correction required",
    "LoD1 only",
    "missing or outdated source data",
}
LOD2_REQUIRED_FIELDS = {
    "building_id",
    "lod2_candidate",
    "lod2_status",
    "output_lod",
    "roof_plane_count",
    "surface_covered_fraction",
    "surface_rmse_m",
    "partition_consistency",
    "lod2_reason",
}
LOD2_REGISTER_FIELDS = (
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
STATUS_HEX = {
    "reliable LoD2": "#754aae",
    "approximate LoD2": "#179ca2",
    "manual correction required": "#d1495b",
    "LoD1 only": "#f4a261",
    "missing or outdated source data": "#5f6368",
}


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _signature(sources: dict[str, Path]) -> tuple[str, dict[str, Any]]:
    payload = {
        "schema_version": PHASE7_SCHEMA_VERSION,
        "source_sha256": {name: sha256(path) for name, path in sources.items()},
        "target_epsg": TARGET_EPSG,
        "local_origin": [float(value) for value in LOCAL_ORIGIN],
        "candidate_gate": {
            "phase6_modelled": True,
            "boundary_clipped": False,
            "minimum_density_points_m2": 5.0,
            "minimum_roof_cell_coverage": 0.65,
            "minimum_roof_points": 200,
        },
        "plane_fit": {
            "ransac_residual_threshold_m": RANSAC_RESIDUAL_THRESHOLD_M,
            "validation_residual_threshold_m": VALIDATION_RESIDUAL_THRESHOLD_M,
            "minimum_plane_points": MIN_PLANE_POINTS,
            "minimum_plane_point_fraction": MIN_PLANE_POINT_FRACTION,
            "maximum_planes": MAX_PLANES,
            "maximum_fit_points": MAX_FIT_POINTS,
            "minimum_lod2_slope_degrees": MIN_LOD2_SLOPE_DEGREES,
            "minimum_interplane_angle_degrees": MIN_INTERPLANE_ANGLE_DEGREES,
        },
        "acceptance_gate": {
            "reliable": {
                "minimum_surface_covered_fraction": 0.80,
                "maximum_surface_rmse_m": 0.20,
                "minimum_partition_consistency": 0.70,
            },
            "approximate": {
                "minimum_surface_covered_fraction": 0.65,
                "maximum_surface_rmse_m": 0.35,
                "minimum_partition_consistency": 0.50,
            },
            "solid_geometry_required": True,
        },
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialised).hexdigest(), payload


def _read_raster(path: Path) -> np.ndarray:
    with rasterio.open(path) as source:
        data = source.read(1).astype(float)
        if source.nodata is not None:
            data[data == source.nodata] = np.nan
        return data


def _status_statistics(statuses: gpd.GeoDataFrame) -> dict[str, Any]:
    accepted = statuses[statuses["output_lod"] == "LoD2"]
    candidates = statuses[statuses["lod2_candidate"]]
    return {
        "buildings_assessed": len(statuses),
        "candidate_buildings": len(candidates),
        "accepted_lod2_buildings": len(accepted),
        "accepted_candidate_fraction": len(accepted) / max(len(candidates), 1),
        "status_counts": {
            str(key): int(value) for key, value in statuses["lod2_status"].value_counts().items()
        },
        "accepted_surface_coverage": {
            "minimum": (
                float(accepted["surface_covered_fraction"].min()) if len(accepted) else math.nan
            ),
            "median": (
                float(accepted["surface_covered_fraction"].median()) if len(accepted) else math.nan
            ),
        },
        "accepted_surface_rmse_m": {
            "median": (float(accepted["surface_rmse_m"].median()) if len(accepted) else math.nan),
            "maximum": (float(accepted["surface_rmse_m"].max()) if len(accepted) else math.nan),
        },
    }


def _load_scene_meshes(path: Path) -> dict[str, trimesh.Trimesh]:
    scene = trimesh.load(path, force="scene")
    meshes: dict[str, trimesh.Trimesh] = {}
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        meshes[str(node_name)] = mesh
    return meshes


def _plan_figure(
    statuses: gpd.GeoDataFrame,
    height_path: Path,
    output: Path,
) -> Path:
    height = _read_raster(height_path)
    extent = [PILOT_AREA.west, PILOT_AREA.east, PILOT_AREA.south, PILOT_AREA.north]
    figure, axis = plt.subplots(figsize=(9, 8), constrained_layout=True)
    image = axis.imshow(
        height,
        extent=extent,
        origin="upper",
        cmap="Greys",
        vmin=0,
        vmax=max(1.0, float(np.nanpercentile(height, 99))),
        alpha=0.60,
    )
    for status in STATUS_HEX:
        subset = statuses[statuses["lod2_status"] == status]
        if subset.empty:
            continue
        subset.plot(
            ax=axis,
            facecolor=STATUS_HEX[status],
            edgecolor="white",
            linewidth=0.7,
            alpha=0.82,
        )
    legend = [
        Patch(facecolor=colour, edgecolor="white", label=f"{status} ({count})")
        for status, colour in STATUS_HEX.items()
        if (count := int((statuses["lod2_status"] == status).sum()))
    ]
    axis.legend(handles=legend, loc="upper left", framealpha=0.94, fontsize=8)
    axis.set(
        title="UQ pilot selective LoD2 feasibility",
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    figure.colorbar(image, ax=axis, shrink=0.74, label="Surface height above ground (m)")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _roof_surface_figure(
    statuses: gpd.GeoDataFrame,
    surfaces: gpd.GeoDataFrame,
    ridges: gpd.GeoDataFrame,
    output: Path,
) -> Path:
    figure, axis = plt.subplots(figsize=(9, 8), constrained_layout=True)
    statuses.boundary.plot(ax=axis, color="#777777", linewidth=0.35, alpha=0.65)
    if not surfaces.empty:
        surfaces.plot(
            ax=axis,
            column="slope_degrees",
            cmap="viridis",
            legend=True,
            legend_kwds={"label": "Accepted roof-plane slope (degrees)", "shrink": 0.72},
            edgecolor="white",
            linewidth=0.8,
        )
    if not ridges.empty:
        ridges.plot(ax=axis, color="#ef233c", linewidth=1.4)
    axis.set(
        xlim=(PILOT_AREA.west, PILOT_AREA.east),
        ylim=(PILOT_AREA.south, PILOT_AREA.north),
        title="Accepted LoD2 roof surfaces and detected ridges",
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _fit_examples_figure(
    statuses: gpd.GeoDataFrame,
    surfaces: gpd.GeoDataFrame,
    ridges: gpd.GeoDataFrame,
    samples: dict[str, np.ndarray],
    output: Path,
) -> Path:
    ranked = statuses.loc[
        statuses["building_id"].isin(samples) & statuses["surface_covered_fraction"].notna()
    ].copy()
    rank = {
        "reliable LoD2": 0,
        "approximate LoD2": 1,
        "manual correction required": 2,
        "LoD1 only": 3,
        "missing or outdated source data": 4,
    }
    ranked["status_rank"] = ranked["lod2_status"].map(rank)
    ranked["unnamed_rank"] = ranked["building_name"].apply(
        lambda value: int(pd.isna(value) or not str(value).strip())
    )
    ranked = ranked.sort_values(
        [
            "status_rank",
            "unnamed_rank",
            "roof_plane_count",
            "surface_covered_fraction",
        ],
        ascending=[True, True, False, False],
    ).head(4)
    if ranked.empty:
        raise RuntimeError("No fitted roofs are available for Phase 7 examples")

    figure, axes = plt.subplots(2, 2, figsize=(11, 10), constrained_layout=True)
    axes_flat = axes.ravel()
    plotted = None
    for axis, (_, building) in zip(axes_flat, ranked.iterrows(), strict=False):
        building_id = str(building["building_id"])
        points = samples[building_id]
        plotted = axis.scatter(
            points[:, 0],
            points[:, 1],
            c=np.abs(points[:, 5]),
            s=9,
            cmap="magma_r",
            vmin=0,
            vmax=VALIDATION_RESIDUAL_THRESHOLD_M,
            linewidths=0,
        )
        gpd.GeoSeries([building.geometry], crs=statuses.crs).boundary.plot(
            ax=axis, color="black", linewidth=1.0
        )
        building_surfaces = surfaces[surfaces["building_id"] == building_id]
        if not building_surfaces.empty:
            building_surfaces.boundary.plot(ax=axis, color="#00a896", linewidth=1.0)
        building_ridges = ridges[ridges["building_id"] == building_id]
        if not building_ridges.empty:
            building_ridges.plot(ax=axis, color="#ef233c", linewidth=1.6)
        name = building["building_name"]
        display_name = "unnamed" if pd.isna(name) or not str(name).strip() else str(name)
        axis.set_title(
            f"{building_id}: {display_name}\n{building['lod2_status']}; "
            f"coverage={building['surface_covered_fraction']:.2f}, "
            f"RMSE={building['surface_rmse_m']:.2f} m",
            fontsize=9,
        )
        axis.set_aspect("equal")
        axis.ticklabel_format(style="plain", useOffset=True)
    for axis in axes_flat[len(ranked) :]:
        axis.set_visible(False)
    if plotted is not None:
        figure.colorbar(
            plotted,
            ax=list(axes_flat),
            shrink=0.68,
            label="Absolute residual to nearest detected plane (m)",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _residual_figure(statuses: gpd.GeoDataFrame, output: Path) -> Path:
    candidate = statuses.loc[
        statuses["lod2_candidate"]
        & statuses["surface_covered_fraction"].notna()
        & statuses["surface_rmse_m"].notna()
    ]
    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    for status, colour in STATUS_HEX.items():
        subset = candidate[candidate["lod2_status"] == status]
        if subset.empty:
            continue
        axis.scatter(
            subset["surface_covered_fraction"],
            subset["surface_rmse_m"],
            s=48,
            color=colour,
            edgecolor="white",
            linewidth=0.5,
            label=f"{status} ({len(subset)})",
        )
    axis.axvline(0.65, color="#555555", linestyle=":", label="Approximate gates")
    axis.axhline(0.35, color="#555555", linestyle=":")
    axis.axvline(0.80, color="#111111", linestyle="--", label="Reliable gates")
    axis.axhline(0.20, color="#111111", linestyle="--")
    axis.set(
        title="Candidate roof fit against reconstructed lower-envelope surface",
        xlabel="Fraction of roof points within 0.35 m",
        ylabel="RMSE for points within 0.35 m (m)",
        xlim=(0, 1.02),
        ylim=(0, max(0.40, float(candidate["surface_rmse_m"].max()) * 1.08)),
    )
    axis.grid(alpha=0.22)
    axis.legend(fontsize=8, framealpha=0.94)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _oblique_figure(
    statuses: gpd.GeoDataFrame,
    meshes: dict[str, trimesh.Trimesh],
    terrain_path: Path,
    output: Path,
    *,
    camera: str,
) -> Path:
    terrain = _read_raster(terrain_path)
    step = 4
    x = (PILOT_AREA.west + (np.arange(terrain.shape[1]) + 0.5) - float(LOCAL_ORIGIN[0]))[::step]
    y = (PILOT_AREA.north - (np.arange(terrain.shape[0]) + 0.5) - float(LOCAL_ORIGIN[1]))[::step]
    xx, yy = np.meshgrid(x, y)
    exaggeration = 3.0
    grid = pv.StructuredGrid(xx, yy, terrain[::step, ::step] * exaggeration)
    plotter = pv.Plotter(off_screen=True, window_size=(1500, 950))
    plotter.set_background("#edf2f4")
    plotter.add_mesh(grid, cmap="terrain", opacity=0.68, show_scalar_bar=False)
    indexed = statuses.set_index("building_id")
    for building_id, mesh in meshes.items():
        if building_id not in indexed.index:
            continue
        exaggerated = mesh.copy()
        exaggerated.vertices[:, 2] *= exaggeration
        status = str(indexed.loc[building_id, "lod2_status"])
        plotter.add_mesh(
            _pyvista_mesh(exaggerated),
            color=STATUS_HEX[status],
            smooth_shading=False,
        )
    camera_positions = {
        "northeast": [(650, 650, 420), (0, 0, 55), (0, 0, 1)],
        "southwest": [(-650, -650, 420), (0, 0, 55), (0, 0, 1)],
    }
    plotter.camera_position = camera_positions[camera]
    plotter.add_text(
        f"UQ pilot mixed LoD1/LoD2 - {camera} (3x vertical exaggeration)",
        position="upper_left",
        font_size=12,
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


def _write_tables(
    statuses: gpd.GeoDataFrame,
    surfaces: gpd.GeoDataFrame,
    feasibility_path: Path,
    planes_path: Path,
    review_path: Path,
) -> dict[str, int]:
    feasibility_path.parent.mkdir(parents=True, exist_ok=True)
    feasibility = pd.DataFrame(statuses.drop(columns=statuses.geometry.name))
    feasibility.to_csv(feasibility_path, index=False)
    plane_metrics = pd.DataFrame(surfaces.drop(columns=surfaces.geometry.name))
    plane_metrics.to_csv(planes_path, index=False)

    review = feasibility.loc[~feasibility["lod2_status"].isin(LOD2_STATUS_COLOURS)].copy()
    recommendations = {
        "manual correction required": (
            "Use current UQ BIM or manually constrain roof planes after imagery review."
        ),
        "LoD1 only": "Retain the Phase 6 LoD1 block unless a detailed roof is required.",
        "missing or outdated source data": (
            "Obtain a current UQ footprint/BIM model or newer complete LiDAR coverage."
        ),
    }
    review["recommended_action"] = review["lod2_status"].map(recommendations)
    review["review_priority"] = np.where(
        review["lod2_status"].isin(
            ["manual correction required", "missing or outdated source data"]
        ),
        "high",
        "normal",
    )
    review_columns = [
        "building_id",
        "building_name",
        "lod2_candidate",
        "lod2_status",
        "lod2_reason",
        "review_priority",
        "recommended_action",
    ]
    review[review_columns].to_csv(review_path, index=False)
    return {
        "feasibility_rows": len(feasibility),
        "roof_plane_rows": len(plane_metrics),
        "manual_review_rows": len(review),
    }


def _write_register(
    root: Path,
    sources: dict[str, Path],
    outputs: dict[str, Path],
    statuses: gpd.GeoDataFrame,
    surfaces: gpd.GeoDataFrame,
    glb_info: dict[str, Any],
) -> Path:
    source_paths = "; ".join(_relative(path, root) for path in sources.values())
    source_hashes = "; ".join(f"{name}:{sha256(path)}" for name, path in sources.items())
    rows = [
        {
            "dataset": "Phase 7 selective LoD2 feasibility and roof surfaces",
            "source_paths": source_paths,
            "source_sha256": source_hashes,
            "output_path": _relative(outputs["gpkg"], root),
            "output_sha256": sha256(outputs["gpkg"]),
            "crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "vertical_datum": "AHD",
            "processing": "Robust plane fitting, lower-envelope partition and acceptance gates",
            "feature_count": len(statuses) + len(surfaces),
            "validation_status": "passed",
            "notes": "GIS source of truth; LoD1 remains the fallback for rejected roofs.",
        },
        {
            "dataset": "Phase 7 mixed LoD1/LoD2 presentation mesh",
            "source_paths": _relative(outputs["gpkg"], root),
            "source_sha256": sha256(outputs["gpkg"]),
            "output_path": _relative(outputs["glb"], root),
            "output_sha256": glb_info["sha256"],
            "crs": "display-local XY derived from EPSG:7856",
            "vertical_datum": "AHD Z values retained",
            "processing": "Accepted LoD2 closed shells plus Phase 6 LoD1 fallback shells",
            "feature_count": glb_info["geometry_count"],
            "validation_status": "passed",
            "notes": "Presentation output; recover authoritative XY with local_origin.json.",
        },
    ]
    destination = root / "data" / "lod2_model_register.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LOD2_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def run_phase7(project_root: str | Path) -> dict[str, Any]:
    """Assess all pilot buildings and build only defensible LoD2 roof shells."""
    root = Path(project_root).resolve()
    sources = {
        "lod1_buildings": root / "data" / "processed" / "lod1" / "lod1_buildings.gpkg",
        "phase6_manifest": root / "data" / "processed" / "lod1" / "lod1_manifest.json",
        "analysis_laz": root
        / "data"
        / "interim"
        / "phase5"
        / "pointcloud"
        / "uq_pilot_analysis_filtered.laz",
        "dtm": root / "data" / "interim" / "phase5" / "elevation" / "dtm_1m.tif",
        "height": root / "data" / "interim" / "phase5" / "elevation" / "height_above_ground.tif",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Phase 7 needs the completed Phase 5/6 products. Missing: " + ", ".join(missing)
        )
    phase6_path = root / "reports" / "tables" / "phase6_lod1.json"
    phase6 = json.loads(phase6_path.read_text(encoding="utf-8"))
    if phase6.get("status") != "passed":
        raise RuntimeError("Phase 6 validation report is not in passed state")

    output_root = root / "data" / "processed" / "lod2"
    outputs = {
        "gpkg": output_root / "lod2_buildings.gpkg",
        "glb": output_root / "uq_pilot_mixed_lod.glb",
        "samples": output_root / "roof_fit_samples.npz",
        "local_origin": output_root / "local_origin.json",
        "manifest": output_root / "lod2_manifest.json",
    }
    table_root = root / "reports" / "tables"
    tables = {
        "feasibility": table_root / "phase7_building_feasibility.csv",
        "planes": table_root / "phase7_roof_plane_metrics.csv",
        "manual_review": table_root / "phase7_manual_review.csv",
        "summary": table_root / "phase7_lod2.json",
    }
    figure_root = root / "reports" / "figures"
    figures = {
        "feasibility": figure_root / "phase7_feasibility_map.png",
        "roof_planes": figure_root / "phase7_roof_planes.png",
        "fit_examples": figure_root / "phase7_roof_fit_examples.png",
        "residuals": figure_root / "phase7_residuals.png",
        "northeast": figure_root / "phase7_mixed_lod_northeast.png",
        "southwest": figure_root / "phase7_mixed_lod_southwest.png",
    }
    signature, signature_payload = _signature(sources)
    previous_manifest: dict[str, Any] = {}
    if outputs["manifest"].is_file():
        previous_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    core_names = ("gpkg", "glb", "samples")
    recorded = previous_manifest.get("outputs", {})
    cache_reused = bool(
        previous_manifest.get("configuration_signature") == signature
        and all(
            outputs[name].is_file()
            and recorded.get(_relative(outputs[name], root)) == sha256(outputs[name])
            for name in core_names
        )
    )

    if cache_reused:
        statuses = gpd.read_file(outputs["gpkg"], layer="building_status")
        surfaces = gpd.read_file(outputs["gpkg"], layer="roof_surfaces")
        layers = set(pyogrio.list_layers(outputs["gpkg"])[:, 0])
        ridges = (
            gpd.read_file(outputs["gpkg"], layer="ridge_lines")
            if "ridge_lines" in layers
            else gpd.GeoDataFrame(
                columns=["building_id", "geometry"], geometry="geometry", crs=statuses.crs
            )
        )
        samples = load_fit_samples(outputs["samples"])
        meshes = _load_scene_meshes(outputs["glb"])
        processing_statistics = previous_manifest["processing_statistics"]
    else:
        buildings = gpd.read_file(sources["lod1_buildings"], layer="lod1_buildings")
        terrain, _ = read_terrain(sources["dtm"])
        point_arrays, assignment = extract_building_points(
            sources["analysis_laz"], buildings, terrain
        )
        statuses, surfaces, ridges, lod2_meshes, samples = assess_lod2_buildings(
            buildings, point_arrays
        )
        write_lod2_geopackage(statuses, surfaces, ridges, outputs["gpkg"])
        write_fit_samples(samples, outputs["samples"])
        meshes = mixed_lod_meshes(statuses, lod2_meshes)
        write_mixed_lod_glb(meshes, outputs["glb"])
        processing_statistics = {
            "point_assignment": assignment,
            "roof_assessment": _status_statistics(statuses),
            "accepted_roof_surfaces": len(surfaces),
            "detected_ridge_segments": len(ridges),
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

    glb_info = _inspect_glb(outputs["glb"])
    table_counts = _write_tables(
        statuses,
        surfaces,
        tables["feasibility"],
        tables["planes"],
        tables["manual_review"],
    )
    _plan_figure(statuses, sources["height"], figures["feasibility"])
    _roof_surface_figure(statuses, surfaces, ridges, figures["roof_planes"])
    _fit_examples_figure(statuses, surfaces, ridges, samples, figures["fit_examples"])
    _residual_figure(statuses, figures["residuals"])
    _oblique_figure(statuses, meshes, sources["dtm"], figures["northeast"], camera="northeast")
    _oblique_figure(statuses, meshes, sources["dtm"], figures["southwest"], camera="southwest")

    accepted = statuses[statuses["output_lod"] == "LoD2"]
    modelled = statuses[statuses["model_status"] == "modelled"]
    layers = set(pyogrio.list_layers(outputs["gpkg"])[:, 0])
    reliable = accepted[accepted["lod2_status"] == "reliable LoD2"]
    approximate = accepted[accepted["lod2_status"] == "approximate LoD2"]
    checks = {
        "phase6_validation_passed": phase6["status"] == "passed",
        "complete_phase6_building_inventory": len(statuses) == 61,
        "building_ids_are_unique": statuses["building_id"].is_unique,
        "status_geometry_crs_is_epsg_7856": statuses.crs is not None
        and statuses.crs.to_epsg() == TARGET_EPSG,
        "required_status_fields_present": LOD2_REQUIRED_FIELDS.issubset(statuses.columns),
        "every_building_has_declared_status": set(statuses["lod2_status"]).issubset(LOD2_STATUSES),
        "candidate_gate_excludes_boundary_buildings": bool(
            (~statuses.loc[statuses["lod2_candidate"], "boundary_clipped"]).all()
        ),
        "at_least_one_roof_earned_lod2": len(accepted) >= 1,
        "accepted_buildings_have_roof_surfaces": set(accepted["building_id"]).issubset(
            set(surfaces["building_id"])
        ),
        "accepted_roof_surfaces_are_3d": bool(
            not surfaces.empty and surfaces.geometry.apply(lambda value: value.has_z).all()
        ),
        "reliable_surface_gates_pass": bool(
            (reliable["surface_covered_fraction"] >= 0.80).all()
            and (reliable["surface_rmse_m"] <= 0.20).all()
            and (reliable["partition_consistency"] >= 0.70).all()
        ),
        "approximate_surface_gates_pass": bool(
            (approximate["surface_covered_fraction"] >= 0.65).all()
            and (approximate["surface_rmse_m"] <= 0.35).all()
            and (approximate["partition_consistency"] >= 0.50).all()
        ),
        "geopackage_has_required_layers": {
            "building_status",
            "roof_surfaces",
        }.issubset(layers),
        "fit_samples_cover_fitted_buildings": set(
            statuses.loc[statuses["surface_covered_fraction"].notna(), "building_id"]
        ).issubset(samples),
        "mixed_glb_has_one_mesh_per_phase6_modelled_building": glb_info["geometry_count"]
        == len(modelled),
        "every_mixed_mesh_is_watertight": glb_info["watertight_geometry_count"] == len(modelled),
        "every_mixed_mesh_has_positive_volume": glb_info["positive_volume_geometry_count"]
        == len(modelled),
        "mixed_glb_local_xy_extent_is_numerically_safe": bool(
            glb_info["bounds_local_xy_and_ahd_z"]
            and np.max(np.abs(np.asarray(glb_info["bounds_local_xy_and_ahd_z"])[:, :2])) < 1_000
        ),
        "feasibility_table_is_complete": table_counts["feasibility_rows"] == len(statuses),
        "roof_plane_table_matches_surfaces": table_counts["roof_plane_rows"] == len(surfaces),
        "fixed_validation_figures_created": all(path.is_file() for path in figures.values()),
    }

    register = _write_register(root, sources, outputs, statuses, surfaces, glb_info)
    output_hashes = {_relative(outputs[name], root): sha256(outputs[name]) for name in core_names}
    manifest = {
        "configuration_signature": signature,
        "signature_inputs": signature_payload,
        "outputs": output_hashes,
        "processing_statistics": processing_statistics,
    }
    if all(checks.values()):
        _write_json(outputs["manifest"], manifest)

    decision = (
        "Retain a mixed-LoD model. The public 2019 LiDAR supports selective automated "
        "LoD2, but not unattended campus-wide conversion; use LoD1 fallbacks and seek "
        "current UQ BIM/manual roof constraints for priority buildings."
    )
    summary = {
        "phase": 7,
        "status": "passed" if all(checks.values()) else "failed",
        "cache_reused": cache_reused,
        "scope": "all 61 Phase 6 pilot footprints assessed; supported roofs attempted",
        "model_type": "selective roof-plane LoD2 with conservative LoD1 fallback",
        "authoritative_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_datum": "AHD",
        "configuration": signature_payload,
        "processing_statistics": processing_statistics,
        "current_statistics": {
            **_status_statistics(statuses),
            "accepted_roof_surfaces": len(surfaces),
            "detected_ridge_segments": len(ridges),
        },
        "presentation_mesh": glb_info,
        "decision_gate": decision,
        "local_origin": local_origin,
        "software": _software_versions(),
        "outputs": {
            **{name: _relative(path, root) for name, path in outputs.items()},
            "lod2_model_register": _relative(register, root),
            "tables": {name: _relative(path, root) for name, path in tables.items()},
            "figures": {name: _relative(path, root) for name, path in figures.items()},
        },
        "checks": checks,
        "limitations": [
            "The model uses public 2019 LiDAR and non-authoritative public footprints.",
            "Plane fitting cannot reliably resolve roof furniture, multi-level flat roofs, "
            "curved roofs or footprint/epoch mismatch without manual constraints.",
            "A fitted plane is accepted only when residual, partition and watertight-shell "
            "gates pass; other buildings retain their validated Phase 6 LoD1 shell.",
            "The GLB uses display-local XY coordinates; the GeoPackage is authoritative.",
            "Neither LoD1 nor LoD2 geometry is survey-grade or suitable for excavation use.",
        ],
    }
    _write_json(tables["summary"], summary)
    summary["summary_report"] = _relative(tables["summary"], root)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 7 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase7(project_root)
    print(f"Phase 7 status: {summary['status']}")
    print(f"Cache reused: {summary['cache_reused']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
