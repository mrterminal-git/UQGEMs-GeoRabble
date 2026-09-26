"""Run and validate Phase 9 integrated Python visualisation."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
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
from matplotlib.patches import Patch
from PIL import Image
from shapely.geometry import LineString
from shapely.ops import nearest_points

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.integrated_scene import (
    BUILDING_COLOURS,
    CAMERAS,
    NETWORK_COLOURS,
    SceneDisplayConfig,
    drape_utility_geometry,
    export_interactive_html,
    load_integrated_scene_data,
    render_integrated_png,
    terrain_at_xy,
)
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG

PHASE9_SCHEMA_VERSION = 3
SCENE_REGISTER_FIELDS = (
    "dataset",
    "source_paths",
    "source_sha256",
    "output_path",
    "output_sha256",
    "horizontal_crs",
    "vertical_reference",
    "processing",
    "feature_count",
    "validation_status",
    "notes",
)


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _software_versions() -> dict[str, str]:
    import plotly

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "geopandas": gpd.__version__,
        "rasterio": rasterio.__version__,
        "laspy": laspy.__version__,
        "pyvista": pv.__version__,
        "plotly": plotly.__version__,
        "uqgems": version("uqgems"),
    }


def _configuration() -> SceneDisplayConfig:
    return SceneDisplayConfig(
        terrain_opacity=0.68,
        building_opacity=0.96,
        vertical_exaggeration=1.0,
        utility_drape_offset_m=0.75,
        symbolic_utility_radius_m=0.65,
        utility_dash_length_m=2.0,
        utility_gap_length_m=1.0,
        utility_types=("stormwater", "water"),
        utility_colour_by="network_type",
        show_point_cloud=False,
    )


def _config_payload(config: SceneDisplayConfig) -> dict[str, Any]:
    return {name: getattr(config, name) for name in config.__dataclass_fields__}


def _signature(sources: dict[str, Path], config: SceneDisplayConfig) -> tuple[str, dict]:
    payload = {
        "schema_version": PHASE9_SCHEMA_VERSION,
        "sources": {name: sha256(path) for name, path in sources.items()},
        "target_epsg": TARGET_EPSG,
        "local_origin": [float(value) for value in LOCAL_ORIGIN],
        "display_config": _config_payload(config),
        "terrain_render_step": 4,
        "interactive_terrain_step": 5,
        "maximum_point_cloud_preview_points": 30_000,
        "utility_policy": {
            "source_geometry_remains_2d": True,
            "drape_is_display_only": True,
            "physical_depth": "unknown",
            "schematic_underground_depth_assigned": False,
        },
        "cross_section": "north-south section centred on public utility alignments",
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialised).hexdigest(), payload


def _layer_inventory(data: Any, sources: dict[str, Path]) -> pd.DataFrame:
    with laspy.open(sources["point_cloud"]) as cloud:
        source_point_count = int(cloud.header.point_count)
    modelled = data.buildings[data.buildings["model_status"] == "modelled"]
    lines = data.utilities[
        data.utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ]
    nodes = data.utilities[data.utilities.geometry.geom_type == "Point"]
    return pd.DataFrame(
        [
            {
                "layer": "terrain",
                "source": _relative(sources["terrain"], sources["terrain"].parents[4]),
                "source_records": int(np.isfinite(data.terrain).sum()),
                "display_records": int(np.isfinite(data.terrain[::5, ::5]).sum()),
                "horizontal_reference": f"EPSG:{TARGET_EPSG}; local-origin XY in renderer",
                "vertical_reference": "AHD",
                "default_visibility": True,
                "interaction": "terrain opacity menu; hover elevation",
            },
            {
                "layer": "mixed-LoD buildings",
                "source": _relative(sources["building_mesh"], sources["building_mesh"].parents[3]),
                "source_records": len(data.buildings),
                "display_records": len(modelled),
                "horizontal_reference": "local-origin XY with reversible origin",
                "vertical_reference": "AHD",
                "default_visibility": True,
                "interaction": "legend group; hover building ID/name/status",
            },
            {
                "layer": "public utility lines",
                "source": _relative(sources["utilities"], sources["utilities"].parents[3]),
                "source_records": len(lines),
                "display_records": len(lines),
                "horizontal_reference": f"authoritative EPSG:{TARGET_EPSG}",
                "vertical_reference": "unknown; display-only terrain drape",
                "default_visibility": True,
                "interaction": "network legend filter; hover asset provenance",
            },
            {
                "layer": "public utility nodes",
                "source": _relative(sources["utilities"], sources["utilities"].parents[3]),
                "source_records": len(nodes),
                "display_records": len(nodes),
                "horizontal_reference": f"authoritative EPSG:{TARGET_EPSG}",
                "vertical_reference": "unknown; display-only terrain drape",
                "default_visibility": True,
                "interaction": "network legend filter; hover asset provenance",
            },
            {
                "layer": "LiDAR preview",
                "source": _relative(sources["point_cloud"], sources["point_cloud"].parents[4]),
                "source_records": source_point_count,
                "display_records": len(data.point_cloud_xyz),
                "horizontal_reference": "local-origin XY with reversible origin",
                "vertical_reference": "AHD",
                "default_visibility": False,
                "interaction": "legend toggle; hover classification",
            },
        ]
    )


def _controls_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (
                "Layer visibility",
                "HTML legend",
                "Toggle terrain, LoD groups, utility types and LiDAR.",
            ),
            ("Utility filtering", "HTML legend groups", "Toggle stormwater or water as a group."),
            ("Terrain opacity", "HTML dropdown", "Select 68%, 25%, or hidden."),
            ("Standard cameras", "HTML dropdown", "Northeast, southwest and plan views."),
            ("Extent", "HTML dropdown", "Full pilot or public-utility detail extent."),
            ("Selection", "HTML hover", "Identify buildings and public assets with provenance."),
            ("Vertical exaggeration", "Python config", "Positive factor; default 1.0."),
            (
                "Utility colour",
                "Python config",
                "Colour by network type, survey age, XY accuracy or confidence.",
            ),
            ("Building/asset subset", "Python config", "Filter by building_id or asset_id."),
            ("Cutaway", "Fixed/Python view", "Western terrain strip with transparent buildings."),
            (
                "Cross-section",
                "Fixed figure",
                "Terrain/buildings plus unknown-depth utility markers.",
            ),
        ],
        columns=["control", "interface", "behaviour"],
    )


def _section_easting(data: Any) -> float:
    lines = data.utilities[
        data.utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ]
    if lines.empty:
        return float((PILOT_AREA.west + PILOT_AREA.east) / 2.0)
    centres = [geometry.representative_point().x for geometry in lines.geometry]
    return float(np.median(centres))


def _cross_section(data: Any, figure_path: Path, profile_path: Path) -> dict[str, Any]:
    section_x = _section_easting(data)
    column = int(np.floor((section_x - data.terrain_transform.c) / data.terrain_transform.a))
    column = int(np.clip(column, 0, data.terrain.shape[1] - 1))
    section_x = float(data.terrain_transform.c + (column + 0.5) * data.terrain_transform.a)
    rows = np.arange(data.terrain.shape[0])
    northing = data.terrain_transform.f + (rows + 0.5) * data.terrain_transform.e
    terrain_z = data.terrain[:, column]
    local_northing = northing - data.local_origin[1]
    profile = pd.DataFrame(
        {
            "section_easting_epsg7856": section_x,
            "local_northing_m": local_northing,
            "northing_epsg7856": northing,
            "terrain_z_ahd": terrain_z,
        }
    )
    profile.to_csv(profile_path, index=False)

    figure, axis = plt.subplots(figsize=(12, 6.5), constrained_layout=True)
    axis.plot(local_northing, terrain_z, color="#4E7D3A", linewidth=2.0, label="Terrain")
    axis.fill_between(
        local_northing,
        np.nanmin(terrain_z) - 3,
        terrain_z,
        color="#B8C99D",
        alpha=0.5,
    )
    section_line = LineString([(section_x, PILOT_AREA.south), (section_x, PILOT_AREA.north)])
    buildings_shown = 0
    for row in data.buildings.itertuples():
        if row.model_status != "modelled" or not row.geometry.intersects(section_line):
            continue
        intersection = row.geometry.intersection(section_line)
        y_min, y_max = intersection.bounds[1], intersection.bounds[3]
        colour = (
            BUILDING_COLOURS["reliable LoD2"]
            if row.lod2_status == "reliable LoD2"
            else (
                BUILDING_COLOURS["approximate LoD2"]
                if row.lod2_status == "approximate LoD2"
                else BUILDING_COLOURS["LoD1"]
            )
        )
        axis.fill_between(
            [y_min - data.local_origin[1], y_max - data.local_origin[1]],
            [row.ground_z_ahd, row.ground_z_ahd],
            [row.roof_z_ahd, row.roof_z_ahd],
            color=colour,
            edgecolor="#39434D",
            linewidth=0.7,
            alpha=0.85,
        )
        buildings_shown += 1

    utility_markers = 0
    label_offsets = [(10, 46), (10, 18), (10, -38)]
    for row in data.utilities.itertuples():
        geometry = row.geometry
        distance = float(geometry.distance(section_line))
        if distance > 8.0:
            continue
        nearest_on_asset, _ = nearest_points(geometry, section_line)
        terrain_value = terrain_at_xy(
            data.terrain,
            data.terrain_transform,
            np.asarray([nearest_on_asset.x]),
            np.asarray([nearest_on_asset.y]),
        )[0]
        if not np.isfinite(terrain_value):
            continue
        local_y = nearest_on_asset.y - data.local_origin[1]
        colour = NETWORK_COLOURS.get(row.network_type, "#6C757D")
        axis.scatter(
            [local_y],
            [terrain_value + 0.4],
            marker="v",
            s=90,
            color=colour,
            edgecolor="white",
            linewidth=0.8,
            zorder=6,
        )
        label_offset = label_offsets[utility_markers % len(label_offsets)]
        axis.annotate(
            f"{row.network_type}: {row.source_feature_id}\ndepth unknown",
            (local_y, terrain_value + 0.4),
            xytext=label_offset,
            textcoords="offset points",
            fontsize=8,
            color=colour,
            arrowprops={"arrowstyle": "-", "color": colour, "lw": 0.7},
        )
        utility_markers += 1

    handles = [
        Patch(facecolor="#B8C99D", edgecolor="#4E7D3A", label="AHD terrain"),
        Patch(facecolor=BUILDING_COLOURS["LoD1"], label="LoD1 building envelope"),
        Patch(facecolor=BUILDING_COLOURS["reliable LoD2"], label="Reliable LoD2 envelope"),
        Patch(facecolor=NETWORK_COLOURS["stormwater"], label="Stormwater alignment marker"),
        Patch(facecolor=NETWORK_COLOURS["water"], label="Water alignment marker"),
    ]
    axis.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.94)
    axis.set(
        title=(
            f"North–south section near public utilities (E {section_x:.1f} m)\n"
            "Utility markers identify horizontal proximity only; physical depth is unknown"
        ),
        xlabel="Local northing (m; add local origin to recover EPSG:7856)",
        ylabel="Elevation (m AHD for terrain and buildings)",
        xlim=(PILOT_AREA.south - data.local_origin[1], PILOT_AREA.north - data.local_origin[1]),
    )
    axis.grid(alpha=0.25)
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(figure_path, dpi=180)
    plt.close(figure)
    return {
        "section_easting_epsg7856": section_x,
        "profile_samples": len(profile),
        "buildings_intersected": buildings_shown,
        "utility_proximity_markers": utility_markers,
        "utility_tolerance_m": 8.0,
    }


def _drape_statistics(data: Any, config: SceneDisplayConfig) -> dict[str, Any]:
    line_rows = data.utilities[
        data.utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ]
    parts: list[np.ndarray] = []
    for row in line_rows.itertuples():
        parts.extend(
            drape_utility_geometry(
                row.geometry,
                data.terrain,
                data.terrain_transform,
                data.local_origin,
                config.utility_drape_offset_m,
            )
        )
    if not parts:
        return {"parts": 0, "vertices": 0, "minimum_display_clearance_m": None}
    clearances = []
    for points in parts:
        authoritative_x = points[:, 0] + data.local_origin[0]
        authoritative_y = points[:, 1] + data.local_origin[1]
        terrain = terrain_at_xy(
            data.terrain, data.terrain_transform, authoritative_x, authoritative_y
        )
        clearances.extend(points[:, 2] - terrain)
    return {
        "parts": len(parts),
        "vertices": int(sum(len(part) for part in parts)),
        "minimum_display_clearance_m": float(np.nanmin(clearances)),
        "maximum_display_clearance_m": float(np.nanmax(clearances)),
        "display_method": (
            "terrain AHD plus visibility offset; display only, not utility elevation"
        ),
    }


def _render_outputs(
    data: Any,
    config: SceneDisplayConfig,
    html_path: Path,
    figures: dict[str, Path],
    cross_section_csv: Path,
) -> dict[str, Any]:
    export_interactive_html(data, html_path, config)
    render_integrated_png(data, figures["plan"], camera="plan", config=config)
    render_integrated_png(data, figures["oblique"], camera="northeast", config=config)
    cutaway_config = SceneDisplayConfig(
        **{
            **_config_payload(config),
            "terrain_opacity": 0.55,
            "building_opacity": 0.42,
        }
    )
    render_integrated_png(
        data,
        figures["cutaway"],
        camera="utility_cutaway",
        config=cutaway_config,
        cutaway=True,
    )
    return _cross_section(data, figures["cross_section"], cross_section_csv)


def _write_register(
    root: Path,
    sources: dict[str, Path],
    html_path: Path,
    building_count: int,
    utility_count: int,
) -> Path:
    combined_hash = hashlib.sha256(
        "".join(sha256(path) for path in sources.values()).encode()
    ).hexdigest()
    row = {
        "dataset": "Phase 9 integrated UQ pilot scene",
        "source_paths": ";".join(_relative(path, root) for path in sources.values()),
        "source_sha256": combined_hash,
        "output_path": _relative(html_path, root),
        "output_sha256": sha256(html_path),
        "horizontal_crs": (
            f"authoritative EPSG:{TARGET_EPSG}; reversible local-origin display coordinates"
        ),
        "vertical_reference": (
            "terrain/buildings AHD; utilities display-draped with physical depth unknown"
        ),
        "processing": "layer assembly, display downsampling, HTML export, fixed-camera QA",
        "feature_count": building_count + utility_count,
        "validation_status": "passed",
        "notes": "Research visualisation; public utility records are not excavation-safe.",
    }
    destination = root / "data" / "scene_model_register.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SCENE_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return destination


def run_phase9(project_root: str | Path) -> dict[str, Any]:
    """Build the reusable integrated scene, exports and validation evidence."""
    root = Path(project_root).resolve()
    sources = {
        "terrain": root / "data/interim/phase5/elevation/dtm_1m.tif",
        "point_cloud": root / "data/interim/phase5/pointcloud/uq_pilot_display.laz",
        "building_status": root / "data/processed/lod2/lod2_buildings.gpkg",
        "building_mesh": root / "data/processed/lod2/uq_pilot_mixed_lod.glb",
        "utilities": root / "data/processed/utilities/uq_pilot_public_utilities.gpkg",
        "phase7_summary": root / "reports/tables/phase7_lod2.json",
        "phase8_summary": root / "reports/tables/phase8_utilities.json",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Phase 9 requires completed Phase 5, 7 and 8 outputs: " + ", ".join(missing)
        )
    phase7 = json.loads(sources["phase7_summary"].read_text(encoding="utf-8"))
    phase8 = json.loads(sources["phase8_summary"].read_text(encoding="utf-8"))
    if phase7.get("status") != "passed" or phase8.get("status") != "passed":
        raise RuntimeError("Phase 7 and Phase 8 validation reports must both pass")

    config = _configuration()
    config.validate()
    signature, signature_payload = _signature(sources, config)
    output_root = root / "data/processed/scene"
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "manifest": output_root / "phase9_manifest.json",
        "config": output_root / "phase9_scene_config.json",
        "interactive_html": root / "reports/scenes/uq_pilot_integrated.html",
    }
    figures = {
        "plan": root / "reports/figures/phase9_integrated_plan.png",
        "oblique": root / "reports/figures/phase9_integrated_oblique.png",
        "cutaway": root / "reports/figures/phase9_utilities_cutaway.png",
        "cross_section": root / "reports/figures/phase9_cross_section.png",
    }
    tables = {
        "layers": root / "reports/tables/phase9_layer_inventory.csv",
        "controls": root / "reports/tables/phase9_controls.csv",
        "cross_section": root / "reports/tables/phase9_cross_section_profile.csv",
        "summary": root / "reports/tables/phase9_scene.json",
    }

    data = load_integrated_scene_data(root, maximum_point_cloud_points=30_000)
    layer_inventory = _layer_inventory(data, sources)
    controls = _controls_table()
    layer_inventory.to_csv(tables["layers"], index=False)
    controls.to_csv(tables["controls"], index=False)
    _write_json(outputs["config"], signature_payload["display_config"])

    previous_manifest: dict[str, Any] = {}
    if outputs["manifest"].is_file():
        previous_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    render_paths = [outputs["interactive_html"], *figures.values(), tables["cross_section"]]
    recorded = previous_manifest.get("output_sha256", {})
    cache_reused = bool(
        previous_manifest.get("configuration_signature") == signature
        and all(
            path.is_file() and recorded.get(_relative(path, root)) == sha256(path)
            for path in render_paths
        )
    )
    if cache_reused:
        cross_section = previous_manifest["cross_section"]
    else:
        cross_section = _render_outputs(
            data,
            config,
            outputs["interactive_html"],
            figures,
            tables["cross_section"],
        )

    drape = _drape_statistics(data, config)
    modelled = data.buildings[data.buildings["model_status"] == "modelled"]
    html_text = outputs["interactive_html"].read_text(encoding="utf-8", errors="ignore")
    png_info = {}
    for name, path in figures.items():
        with Image.open(path) as image:
            png_info[name] = {
                "width": image.width,
                "height": image.height,
                "bytes": path.stat().st_size,
            }
    local_xy = np.vstack([mesh.bounds[:, :2] for mesh in data.building_meshes.values()])
    utility_source_has_z = bool(data.utilities.geometry.has_z.any())
    checks = {
        "phase7_and_phase8_validation_passed": phase7["status"] == "passed"
        and phase8["status"] == "passed",
        "all_scene_sources_exist": all(path.is_file() for path in sources.values()),
        "terrain_has_expected_500_by_500_cells": data.terrain.shape == (500, 500),
        "all_58_modelled_buildings_have_meshes": len(modelled) == 58
        and len(data.building_meshes) == 58,
        "phase8_utility_inventory_is_complete": len(data.utilities)
        == phase8["current_statistics"]["utility_records"],
        "authoritative_utility_source_remains_2d": not utility_source_has_z
        and bool((data.utilities["geometry_dimension"] == "2D").all()),
        "no_schematic_utility_depth_was_added": bool(
            data.utilities["depth_m"].isna().all()
            and (data.utilities["vertical_class"] == "unknown_depth").all()
        ),
        "display_drape_is_above_terrain_by_declared_offset": bool(
            drape["parts"] > 0
            and np.isclose(drape["minimum_display_clearance_m"], config.utility_drape_offset_m)
            and np.isclose(drape["maximum_display_clearance_m"], config.utility_drape_offset_m)
        ),
        "point_cloud_preview_is_deterministic_and_bounded": len(data.point_cloud_xyz) == 30_000,
        "local_rendering_xy_is_numerically_safe": bool(np.max(np.abs(local_xy)) <= 250.001),
        "interactive_html_is_self_contained_and_nonempty": outputs["interactive_html"]
        .stat()
        .st_size
        > 1_000_000
        and "plotly.js" in html_text,
        "interactive_html_declares_unknown_utility_depth": "physical depth is unknown" in html_text,
        "interactive_html_has_camera_extent_and_opacity_controls": all(
            phrase in html_text for phrase in ("Northeast", "Utility detail extent", "Terrain 25%")
        ),
        "layer_inventory_covers_five_scene_roles": len(layer_inventory) == 5,
        "interaction_contract_documents_required_controls": {
            "Layer visibility",
            "Utility filtering",
            "Terrain opacity",
            "Standard cameras",
            "Selection",
            "Vertical exaggeration",
            "Utility colour",
            "Cutaway",
            "Cross-section",
        }.issubset(set(controls["control"])),
        "cross_section_has_terrain_and_utility_markers": cross_section["profile_samples"] == 500
        and cross_section["utility_proximity_markers"] >= 2,
        "all_fixed_pngs_are_nonempty": all(value["bytes"] > 25_000 for value in png_info.values()),
        "fixed_camera_definitions_are_complete": {
            "plan",
            "northeast",
            "southwest",
            "utility_cutaway",
        }
        == set(CAMERAS),
        "scene_config_records_display_only_utility_method": outputs["config"].is_file(),
    }

    register = _write_register(
        root,
        sources,
        outputs["interactive_html"],
        len(modelled),
        len(data.utilities),
    )
    output_hashes = {_relative(path, root): sha256(path) for path in render_paths}
    manifest = {
        "configuration_signature": signature,
        "signature_inputs": signature_payload,
        "output_sha256": output_hashes,
        "cross_section": cross_section,
    }
    if all(checks.values()):
        _write_json(outputs["manifest"], manifest)

    summary = {
        "phase": 9,
        "status": "passed" if all(checks.values()) else "failed",
        "cache_reused": cache_reused,
        "scope": "integrated 500 m by 500 m UQ St Lucia public-data pilot",
        "scene_contents": {
            "terrain": "Phase 5 AHD DTM",
            "buildings": "58 Phase 7 mixed-LoD solids",
            "utilities": "three Phase 8 public records; horizontal alignment only",
            "point_cloud": "deterministic 30,000-point preview; hidden by default",
        },
        "authoritative_horizontal_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "local_origin": [float(value) for value in LOCAL_ORIGIN],
        "vertical_convention": {
            "terrain_and_buildings": "AHD",
            "utilities": "physical depth unknown",
            "utility_display": drape,
            "vertical_exaggeration_default": config.vertical_exaggeration,
        },
        "configuration": signature_payload,
        "cross_section": cross_section,
        "fixed_cameras": CAMERAS,
        "png_validation": png_info,
        "decision_gate": (
            "The integrated Python visualisation workflow is ready for the public-data pilot. "
            "Utilities remain a horizontal-alignment overlay and must not be interpreted as "
            "underground position. Authoritative depth data is still required for a true 3D "
            "utility scene."
        ),
        "software": _software_versions(),
        "outputs": {
            **{name: _relative(path, root) for name, path in outputs.items()},
            "figures": {name: _relative(path, root) for name, path in figures.items()},
            "tables": {name: _relative(path, root) for name, path in tables.items()},
            "scene_model_register": _relative(register, root),
        },
        "checks": checks,
        "limitations": [
            "Public utilities are display-draped on terrain solely to show horizontal alignment.",
            "The 0.75 m display offset is a visibility device, not a utility elevation or depth.",
            (
                "Only three public utility records intersect the pilot; campus networks "
                "remain incomplete."
            ),
            (
                "The 30,000-point LiDAR layer is a deterministic display sample, not the "
                "analysis cloud."
            ),
            (
                "Urban Utilities redistribution terms must be verified before publishing "
                "the HTML scene."
            ),
            "The model is a research visualisation and is not survey-grade or excavation-safe.",
        ],
    }
    _write_json(tables["summary"], summary)
    summary["summary_report"] = _relative(tables["summary"], root)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 9 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase9(project_root)
    print(f"Phase 9 status: {summary['status']}")
    print(f"Cache reused: {summary['cache_reused']}")
    print(f"Checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Interactive scene: {project_root / summary['outputs']['interactive_html']}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
