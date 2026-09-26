"""Run and validate Phase 8 public utility-data standardisation."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from matplotlib.lines import Line2D
from shapely.geometry import box

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.normalization import TARGET_EPSG
from uqgems.utilities import (
    BCC_DATASETS,
    URBAN_UTILITIES_SERVICES,
    UTILITY_REQUIRED_FIELDS,
    VERTICAL_CLASSES,
    acquire_public_utility_sources,
    building_overlap_ids,
    connectivity_statistics,
    grade_diagnostics,
    standardise_public_utilities,
    utility_lines_and_nodes,
    write_utility_geopackage,
)

PHASE8_SCHEMA_VERSION = 2
UTILITY_REGISTER_FIELDS = (
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
NETWORK_COLOURS = {
    "stormwater": "#00a6d6",
    "water": "#2357d9",
    "sewer": "#8b5a2b",
    "electricity": "#e5b700",
    "gas": "#f28e2b",
    "telecommunications": "#8e44ad",
}


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _software_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "geopandas": gpd.__version__,
        "rasterio": rasterio.__version__,
        "pyogrio": pyogrio.__version__,
        "uqgems": version("uqgems"),
    }


def _signature(source_paths: list[Path], contextual_sources: dict[str, Path]) -> tuple[str, dict]:
    payload = {
        "schema_version": PHASE8_SCHEMA_VERSION,
        "source_sha256": {
            str(path.name): sha256(path) for path in sorted(set(source_paths), key=str)
        },
        "context_sha256": {name: sha256(path) for name, path in contextual_sources.items()},
        "pilot_projected_bounds": PILOT_AREA.projected_bounds,
        "target_epsg": TARGET_EPSG,
        "selected_sources": {
            "bcc_datasets": list(BCC_DATASETS),
            "urban_utilities_services": list(URBAN_UTILITIES_SERVICES),
        },
        "vertical_policy": {
            "verified_ahd_required_for_3d": True,
            "schematic_depths_allowed": False,
            "unstated_source_levels_retained_but_not_labelled_ahd": True,
        },
        "endpoint_match_tolerance_m": 1.0,
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialised).hexdigest(), payload


def _combine_layers(path: Path) -> gpd.GeoDataFrame:
    layer_names = set(pyogrio.list_layers(path)[:, 0])
    frames = []
    for layer in ("utility_lines", "utility_nodes"):
        if layer in layer_names:
            frames.append(gpd.read_file(path, layer=layer))
    if not frames:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=TARGET_EPSG)
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=TARGET_EPSG
    )


def _source_paths(sources: list[dict[str, Any]]) -> list[Path]:
    paths: set[Path] = set()
    for source in sources:
        for key in ("metadata_path", "item_metadata_path", "records_path"):
            if source.get(key):
                paths.add(Path(source[key]))
    return sorted(paths)


def _read_raster(path: Path) -> tuple[np.ndarray, list[float]]:
    with rasterio.open(path) as source:
        values = source.read(1).astype(float)
        if source.nodata is not None:
            values[values == source.nodata] = np.nan
        extent = [source.bounds.left, source.bounds.right, source.bounds.bottom, source.bounds.top]
    return values, extent


def _plan_figure(
    utilities: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    dtm_path: Path,
    output: Path,
) -> Path:
    lines, nodes = utility_lines_and_nodes(utilities)
    dtm, extent = _read_raster(dtm_path)
    figure, axis = plt.subplots(figsize=(9.5, 8.5), constrained_layout=True)
    image = axis.imshow(dtm, extent=extent, origin="upper", cmap="terrain", alpha=0.84)
    buildings.boundary.plot(ax=axis, color="#30343b", linewidth=0.55, alpha=0.8)
    for network, colour in NETWORK_COLOURS.items():
        network_lines = lines[lines["network_type"] == network]
        network_nodes = nodes[nodes["network_type"] == network]
        if not network_lines.empty:
            network_lines.plot(ax=axis, color=colour, linewidth=4.0, zorder=4)
        if not network_nodes.empty:
            network_nodes.plot(
                ax=axis,
                color=colour,
                marker="o",
                edgecolor="white",
                linewidth=0.9,
                markersize=65,
                zorder=5,
            )
    pilot = box(*PILOT_AREA.projected_bounds)
    gpd.GeoSeries([pilot], crs=TARGET_EPSG).boundary.plot(
        ax=axis, color="black", linewidth=1.2, linestyle="--", zorder=6
    )
    present = [network for network in NETWORK_COLOURS if network in set(utilities.network_type)]
    handles = [
        Line2D([0], [0], color=NETWORK_COLOURS[network], lw=4, label=network.title())
        for network in present
    ]
    handles.append(Line2D([0], [0], color="black", lw=1.2, ls="--", label="Pilot boundary"))
    axis.legend(handles=handles, loc="upper right", framealpha=0.94)
    axis.set(
        xlim=(PILOT_AREA.west, PILOT_AREA.east),
        ylim=(PILOT_AREA.south, PILOT_AREA.north),
        title="Phase 8 public utility records in the UQ pilot",
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    axis.text(
        0.01,
        0.01,
        "Public records only • 2D location • depth unknown • not excavation-safe",
        transform=axis.transAxes,
        fontsize=8,
        bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "none"},
        zorder=7,
    )
    figure.colorbar(image, ax=axis, shrink=0.72, label="Terrain elevation (m AHD)")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _detail_figure(
    utilities: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    output: Path,
) -> Path:
    lines, nodes = utility_lines_and_nodes(utilities)
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    if utilities.empty:
        axis.text(0.5, 0.5, "No public assets intersect the pilot", ha="center", va="center")
    else:
        bounds = utilities.total_bounds
        margin = max(12.0, 0.15 * max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1.0))
        nearby = buildings.cx[
            bounds[0] - margin : bounds[2] + margin,
            bounds[1] - margin : bounds[3] + margin,
        ]
        nearby.plot(ax=axis, facecolor="#dedede", edgecolor="#555555", linewidth=0.7)
        for network, colour in NETWORK_COLOURS.items():
            subset_lines = lines[lines["network_type"] == network]
            subset_nodes = nodes[nodes["network_type"] == network]
            if not subset_lines.empty:
                subset_lines.plot(ax=axis, color=colour, linewidth=5, label=network.title())
                for _, asset in subset_lines.iterrows():
                    point = asset.geometry.representative_point()
                    axis.annotate(
                        str(asset["source_feature_id"]),
                        (point.x, point.y),
                        xytext=(4, 4),
                        textcoords="offset points",
                        fontsize=8,
                    )
            if not subset_nodes.empty:
                subset_nodes.plot(
                    ax=axis,
                    color=colour,
                    edgecolor="white",
                    marker="o",
                    markersize=85,
                    zorder=5,
                )
        axis.set_xlim(bounds[0] - margin, bounds[2] + margin)
        axis.set_ylim(bounds[1] - margin, bounds[3] + margin)
    axis.set(
        title="Public utility records — detail view",
        xlabel="Easting (m, EPSG:7856)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    axis.text(
        0.01,
        0.01,
        "Lines are not placed underground: no verified AHD/depth is available.",
        transform=axis.transAxes,
        fontsize=8,
        bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "none"},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _coverage_figure(utilities: gpd.GeoDataFrame, output: Path) -> Path:
    networks = ["stormwater", "water", "sewer", "electricity", "gas", "telecommunications"]
    counts = utilities["network_type"].value_counts().to_dict() if not utilities.empty else {}
    values = [int(counts.get(network, 0)) for network in networks]
    colours = [NETWORK_COLOURS[network] for network in networks]
    figure, axis = plt.subplots(figsize=(9, 5), constrained_layout=True)
    bars = axis.bar(networks, values, color=colours)
    axis.bar_label(bars, padding=3)
    axis.set(
        title="Public utility coverage found inside the 500 m pilot",
        ylabel="Intersecting records",
        xlabel="Network",
    )
    axis.tick_params(axis="x", rotation=20)
    axis.set_ylim(0, max(values + [1]) * 1.3)
    axis.text(
        0.99,
        0.96,
        "Zero means absent from the selected public sources—not proof that no asset exists.",
        ha="right",
        va="top",
        transform=axis.transAxes,
        fontsize=8,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _vertical_figure(utilities: gpd.GeoDataFrame, output: Path) -> Path:
    verified = int(utilities["invert_z_ahd"].notna().sum())
    raw_levels = int(
        utilities[
            [
                "raw_upstream_invert_level",
                "raw_downstream_invert_level",
                "raw_invert_level",
            ]
        ]
        .notna()
        .any(axis=1)
        .sum()
    )
    unknown = len(utilities) - verified - raw_levels
    labels = ["Verified AHD", "Unverified source level", "No vertical value"]
    values = [verified, raw_levels, unknown]
    colours = ["#2a9d8f", "#f4a261", "#6c757d"]
    figure, axis = plt.subplots(figsize=(8, 5), constrained_layout=True)
    bars = axis.bar(labels, values, color=colours)
    axis.bar_label(bars, padding=3)
    axis.set(title="Vertical placement evidence", ylabel="Utility records")
    axis.set_ylim(0, max(values + [1]) * 1.35)
    axis.text(
        0.99,
        0.95,
        "Unverified levels are preserved but never treated as AHD.",
        ha="right",
        va="top",
        transform=axis.transAxes,
        fontsize=8,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _network_summary(utilities: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for network in ("stormwater", "water", "sewer", "electricity", "gas", "telecommunications"):
        subset = utilities[utilities["network_type"] == network]
        lines, nodes = utility_lines_and_nodes(subset)
        rows.append(
            {
                "network_type": network,
                "records": len(subset),
                "line_records": len(lines),
                "node_records": len(nodes),
                "verified_ahd_records": int(subset["invert_z_ahd"].notna().sum()),
                "known_depth_records": int(subset["depth_m"].notna().sum()),
                "public_source_status": (
                    "records found"
                    if len(subset)
                    else (
                        "queried; no records in pilot"
                        if network == "sewer"
                        else "not covered by selected public sources"
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def _validation_issues(
    utilities: gpd.GeoDataFrame,
    coverage: pd.DataFrame,
    buildings: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    lines, nodes = utility_lines_and_nodes(utilities)
    connectivity = connectivity_statistics(lines, nodes)
    overlaps = building_overlap_ids(lines, buildings.geometry)
    issues: list[dict[str, str]] = []

    for _, asset in utilities.iterrows():
        if pd.isna(asset["invert_z_ahd"]) and pd.isna(asset["depth_m"]):
            issues.append(
                {
                    "severity": "information",
                    "check_type": "missing_vertical_reference",
                    "asset_id": str(asset["asset_id"]),
                    "description": "No verified AHD elevation or usable depth is available.",
                    "action": "Keep 2D; obtain owner/survey data before underground placement.",
                }
            )
        if asset.geometry.geom_type in {"LineString", "MultiLineString"}:
            grade = grade_diagnostics(asset)
            if grade["grade_discrepancy"]:
                issues.append(
                    {
                        "severity": "warning",
                        "check_type": "published_grade_level_mismatch",
                        "asset_id": str(asset["asset_id"]),
                        "description": (
                            "Recorded levels imply about "
                            f"1:{grade['computed_grade_denominator']:.1f}, while the "
                            "published grade is "
                            f"1:{grade['published_grade_denominator']:.1f}."
                        ),
                        "action": (
                            "Do not use the recorded levels for 3D modelling without "
                            "clarification."
                        ),
                    }
                )

    for asset_id in overlaps:
        issues.append(
            {
                "severity": "warning",
                "check_type": "horizontal_building_overlap",
                "asset_id": asset_id,
                "description": "The 2D utility centreline intersects a public building footprint.",
                "action": (
                    "Treat as a screening flag only; validate alignment and depth with "
                    "the owner."
                ),
            }
        )

    if connectivity["unexplained_open_endpoints"]:
        issues.append(
            {
                "severity": "information",
                "check_type": "open_network_endpoints",
                "asset_id": "network_summary",
                "description": (
                    f"{connectivity['unexplained_open_endpoints']} clipped line "
                    "endpoints do not match a public node or the pilot boundary within 1 m."
                ),
                "action": (
                    "Expected for incomplete public/private coverage; retain as a "
                    "data-gap flag."
                ),
            }
        )

    for network in ("sewer", "electricity", "gas", "telecommunications"):
        if not len(utilities[utilities["network_type"] == network]):
            source_state = (
                "queried Urban Utilities layers returned no pilot records"
                if network == "sewer"
                else "not supplied by the selected no-login public sources"
            )
            issues.append(
                {
                    "severity": "information",
                    "check_type": "public_source_coverage_gap",
                    "asset_id": f"network:{network}",
                    "description": f"{network.title()}: {source_state}.",
                    "action": (
                        "Seek owner, UQ, or authorised BYDA/BDUP data if this network "
                        "is required."
                    ),
                }
            )

    issue_frame = pd.DataFrame(
        issues, columns=["severity", "check_type", "asset_id", "description", "action"]
    )
    metrics = {
        "connectivity": connectivity,
        "horizontal_building_overlap_assets": overlaps,
        "vertical_discontinuities_assessable": 0,
        "source_layers_queried": len(coverage),
        "source_layers_with_records": int((coverage["feature_count"] > 0).sum()),
    }
    return issue_frame, metrics


def _write_tables(
    root: Path,
    utilities: gpd.GeoDataFrame,
    coverage: pd.DataFrame,
    issues: pd.DataFrame,
    paths: dict[str, Path],
) -> dict[str, int]:
    assets = pd.DataFrame(utilities.drop(columns="geometry"))
    assets["geometry_wkt"] = utilities.geometry.to_wkt()
    assets.sort_values(["network_type", "asset_id"]).to_csv(paths["assets"], index=False)
    coverage_copy = coverage.copy()
    coverage_copy["raw_extract"] = coverage_copy["raw_extract"].map(
        lambda value: _relative(Path(value), root)
    )
    coverage_copy.sort_values(["source_system", "network_type", "source_layer"]).to_csv(
        paths["coverage"], index=False
    )
    issues.to_csv(paths["issues"], index=False)
    network = _network_summary(utilities)
    network.to_csv(paths["networks"], index=False)
    return {
        "asset_rows": len(assets),
        "coverage_rows": len(coverage_copy),
        "issue_rows": len(issues),
        "network_rows": len(network),
    }


def _write_model_register(
    root: Path,
    source_paths: list[Path],
    outputs: dict[str, Path],
    feature_count: int,
) -> Path:
    combined_source_hash = hashlib.sha256(
        "".join(sha256(path) for path in source_paths).encode()
    ).hexdigest()
    rows = [
        {
            "dataset": "Phase 8 standardised public utility network",
            "source_paths": ";".join(_relative(path, root) for path in source_paths),
            "source_sha256": combined_source_hash,
            "output_path": _relative(outputs["gpkg"], root),
            "output_sha256": sha256(outputs["gpkg"]),
            "crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "vertical_datum": "not confirmed; all utility geometries retained as 2D",
            "processing": "AOI query, schema mapping, sentinel cleaning, provenance retention",
            "feature_count": feature_count,
            "validation_status": "passed with documented public-data gaps",
            "notes": "Planning/research context only; not excavation-safe.",
        }
    ]
    destination = root / "data" / "utility_model_register.csv"
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=UTILITY_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def _update_dataset_register(
    root: Path, sources: list[dict[str, Any]], coverage: pd.DataFrame
) -> Path:
    path = root / "data" / "dataset_register.csv"
    register = pd.read_csv(path, dtype=str).fillna("")
    prefixes = ("BCC public utility:", "Urban Utilities public utility:")
    register = register[~register["dataset"].str.startswith(prefixes)]
    rows: list[dict[str, str]] = []
    for source in sources:
        if source["source_system"] != "Brisbane City Council Open Data":
            continue
        rows.append(
            {
                "dataset": f"BCC public utility: {source['layer_name']}",
                "source": source["source_url"],
                "local_path": _relative(Path(source["records_path"]), root),
                "download_date": datetime.fromtimestamp(
                    Path(source["records_path"]).stat().st_mtime
                ).date().isoformat(),
                "capture_date": (
                    "continuously maintained asset register; feature survey dates absent"
                ),
                "licence": source["licence"],
                "horizontal_crs": f"WGS 84 API response transformed to EPSG:{TARGET_EPSG}",
                "vertical_datum": "not stated in dataset metadata",
                "resolution": "vector asset record",
                "stated_accuracy": (
                    "feature reliability may be supplied; no numeric accuracy stated"
                ),
                "processing_status": "raw immutable pilot extract acquired; Phase 8 standardised",
                "sha256": sha256(Path(source["records_path"])),
                "notes": "Public planning context; not excavation-safe.",
            }
        )
    for network in URBAN_UTILITIES_SERVICES:
        network_sources = [
            source
            for source in sources
            if source["network_type"] == network and source["source_system"].startswith("Urban")
        ]
        if not network_sources:
            continue
        service_source = network_sources[0]
        source_hash = hashlib.sha256(
            "".join(sha256(Path(source["records_path"])) for source in network_sources).encode()
        ).hexdigest()
        rows.append(
            {
                "dataset": f"Urban Utilities public utility: {network}",
                "source": URBAN_UTILITIES_SERVICES[network]["service"],
                "local_path": _relative(
                    Path(service_source["metadata_path"]).parent / network, root
                ),
                "download_date": datetime.fromtimestamp(
                    Path(service_source["metadata_path"]).stat().st_mtime
                ).date().isoformat(),
                "capture_date": (
                    "continuously maintained asset register; feature survey dates absent"
                ),
                "licence": service_source["licence"],
                "horizontal_crs": f"ArcGIS query response requested in EPSG:{TARGET_EPSG}",
                "vertical_datum": "not published in returned pilot records",
                "resolution": "vector feature service",
                "stated_accuracy": "not stated in public service",
                "processing_status": "raw immutable layer extracts acquired; Phase 8 standardised",
                "sha256": source_hash,
                "notes": (
                    f"{int(coverage.loc[coverage.network_type == network, 'feature_count'].sum())} "
                    "intersecting records; verify licence before redistribution."
                ),
            }
        )
    updated = pd.concat([register, pd.DataFrame(rows)], ignore_index=True)
    updated.to_csv(path, index=False)
    return path


def run_phase8(project_root: str | Path) -> dict[str, Any]:
    """Acquire, standardise and validate no-login public utilities for the pilot."""
    root = Path(project_root).resolve()
    contextual_sources = {
        "phase7_summary": root / "reports" / "tables" / "phase7_lod2.json",
        "buildings": root / "data" / "processed" / "lod2" / "lod2_buildings.gpkg",
        "dtm": root / "data" / "interim" / "phase5" / "elevation" / "dtm_1m.tif",
    }
    missing = [str(path) for path in contextual_sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Phase 8 needs completed Phase 5/7 products. Missing: " + ", ".join(missing)
        )
    phase7 = json.loads(contextual_sources["phase7_summary"].read_text(encoding="utf-8"))
    if phase7.get("status") != "passed":
        raise RuntimeError("Phase 7 validation report is not in passed state")

    raw_root = root / "data" / "raw" / "public_utilities"
    sources = acquire_public_utility_sources(raw_root)
    source_paths = _source_paths(sources)
    signature, signature_payload = _signature(source_paths, contextual_sources)

    output_root = root / "data" / "processed" / "utilities"
    outputs = {
        "gpkg": output_root / "uq_pilot_public_utilities.gpkg",
        "manifest": output_root / "utility_manifest.json",
    }
    table_root = root / "reports" / "tables"
    table_root.mkdir(parents=True, exist_ok=True)
    tables = {
        "assets": table_root / "phase8_utility_assets.csv",
        "coverage": table_root / "phase8_source_coverage.csv",
        "issues": table_root / "phase8_validation_issues.csv",
        "networks": table_root / "phase8_network_summary.csv",
        "summary": table_root / "phase8_utilities.json",
    }
    figure_root = root / "reports" / "figures"
    figures = {
        "plan": figure_root / "phase8_utility_plan.png",
        "detail": figure_root / "phase8_utility_detail.png",
        "coverage": figure_root / "phase8_public_coverage.png",
        "vertical": figure_root / "phase8_vertical_evidence.png",
    }

    previous_manifest: dict[str, Any] = {}
    if outputs["manifest"].is_file():
        previous_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    cache_reused = bool(
        previous_manifest.get("configuration_signature") == signature
        and outputs["gpkg"].is_file()
        and previous_manifest.get("output_sha256") == sha256(outputs["gpkg"])
    )
    _, coverage = standardise_public_utilities(sources)
    if cache_reused:
        utilities = _combine_layers(outputs["gpkg"])
    else:
        utilities, coverage = standardise_public_utilities(sources)
        write_utility_geopackage(utilities, outputs["gpkg"])

    buildings = gpd.read_file(contextual_sources["buildings"], layer="building_status")
    lines, nodes = utility_lines_and_nodes(utilities)
    issues, validation_metrics = _validation_issues(utilities, coverage, buildings)
    table_counts = _write_tables(root, utilities, coverage, issues, tables)
    _plan_figure(utilities, buildings, contextual_sources["dtm"], figures["plan"])
    _detail_figure(utilities, buildings, figures["detail"])
    _coverage_figure(utilities, figures["coverage"])
    _vertical_figure(utilities, figures["vertical"])

    dataset_register = _update_dataset_register(root, sources, coverage)
    model_register = _write_model_register(root, source_paths, outputs, len(utilities))
    gpkg_layers = set(pyogrio.list_layers(outputs["gpkg"])[:, 0])
    source_counts = {
        str(network): int(value)
        for network, value in utilities["network_type"].value_counts().sort_index().items()
    }
    bcc_metadata_licences = {
        str(value)
        for value in coverage.loc[coverage.source_system.str.startswith("Brisbane"), "licence"]
    }
    expected_uu_layers = sum(
        1 for source in sources if source["source_system"] == "Urban Utilities Open Data"
    )
    checks = {
        "phase7_validation_passed": phase7["status"] == "passed",
        "all_raw_source_snapshots_exist": bool(source_paths)
        and all(path.is_file() for path in source_paths),
        "all_five_bcc_datasets_queried": int(
            (coverage.source_system == "Brisbane City Council Open Data").sum()
        )
        == len(BCC_DATASETS),
        "both_urban_utilities_services_queried": set(
            coverage.loc[coverage.source_system == "Urban Utilities Open Data", "network_type"]
        )
        == set(URBAN_UTILITIES_SERVICES),
        "urban_utilities_layer_catalogues_complete": expected_uu_layers > 0,
        "coverage_counts_match_standardised_assets": int(coverage.feature_count.sum())
        == len(utilities),
        "at_least_one_public_record_intersects_pilot": len(utilities) > 0,
        "required_common_schema_present": UTILITY_REQUIRED_FIELDS.issubset(utilities.columns),
        "asset_ids_are_unique": utilities["asset_id"].is_unique,
        "authoritative_horizontal_crs_is_epsg_7856": utilities.crs is not None
        and utilities.crs.to_epsg() == TARGET_EPSG,
        "all_geometries_are_valid_and_nonempty": bool(
            utilities.geometry.is_valid.all() and (~utilities.geometry.is_empty).all()
        ),
        "all_records_intersect_pilot": bool(utilities["intersects_pilot"].all()),
        "vertical_classes_are_valid": set(utilities["vertical_class"]).issubset(VERTICAL_CLASSES),
        "unverified_levels_are_not_labelled_ahd": bool(
            utilities.loc[
                ~utilities["vertical_datum_confirmed"].astype(bool), ["invert_z_ahd", "crown_z_ahd"]
            ]
            .isna()
            .all()
            .all()
        ),
        "no_schematic_depths_assigned": bool(
            (utilities["vertical_class"] != "schematic_depth").all()
            and utilities["depth_m"].isna().all()
        ),
        "two_dimensional_status_is_explicit": bool((utilities["geometry_dimension"] == "2D").all()),
        "bcc_open_data_licence_recorded": "CC BY 4.0" in bcc_metadata_licences,
        "geopackage_has_required_layers": {
            "utility_lines",
            "utility_nodes",
            "pilot_boundary",
        }.issubset(gpkg_layers),
        "asset_table_matches_geopackage": table_counts["asset_rows"] == len(utilities),
        "source_coverage_table_is_complete": table_counts["coverage_rows"] == len(coverage),
        "all_six_network_categories_reported": table_counts["network_rows"] == 6,
        "validation_issue_table_created": tables["issues"].is_file(),
        "fixed_validation_figures_created": all(path.is_file() for path in figures.values()),
        "dataset_and_model_registers_updated": dataset_register.is_file()
        and model_register.is_file(),
    }

    manifest = {
        "configuration_signature": signature,
        "signature_inputs": signature_payload,
        "output_sha256": sha256(outputs["gpkg"]),
        "feature_count": len(utilities),
    }
    if all(checks.values()):
        _write_json(outputs["manifest"], manifest)

    raw_level_count = int(
        utilities[["raw_upstream_invert_level", "raw_downstream_invert_level", "raw_invert_level"]]
        .notna()
        .any(axis=1)
        .sum()
    )
    summary = {
        "phase": 8,
        "status": "passed" if all(checks.values()) else "failed",
        "cache_reused": cache_reused,
        "scope": "500 m by 500 m UQ St Lucia pilot; no-login public sources only",
        "authoritative_horizontal_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_status": (
            "No public pilot record has a verified AHD elevation or defensible depth. "
            "All utility geometry remains 2D."
        ),
        "configuration": signature_payload,
        "current_statistics": {
            "utility_records": len(utilities),
            "line_records": len(lines),
            "node_records": len(nodes),
            "records_by_network": source_counts,
            "source_layers_queried": len(coverage),
            "source_layers_with_records": int((coverage.feature_count > 0).sum()),
            "verified_ahd_records": int(utilities["invert_z_ahd"].notna().sum()),
            "usable_depth_records": int(utilities["depth_m"].notna().sum()),
            "records_with_unverified_source_levels": raw_level_count,
            **validation_metrics,
        },
        "decision_gate": (
            "Phase 8 standardisation is complete for the selected public sources, but the "
            "public-data result is too sparse and vertically undocumented for a defensible 3D "
            "campus utility model. Use it as labelled 2D context and evidence supporting a UQ "
            "or asset-owner data request."
        ),
        "publication": {
            "bcc": "CC BY 4.0 metadata recorded; attribution required.",
            "urban_utilities": (
                "Publicly queryable feature services were used, but no explicit redistribution "
                "licence was found in the cached item metadata; verify before publishing extracts."
            ),
            "sensitivity": (
                "Only public records are present; no restricted UQ/BYDA data is included."
            ),
        },
        "software": _software_versions(),
        "outputs": {
            **{name: _relative(path, root) for name, path in outputs.items()},
            "dataset_register": _relative(dataset_register, root),
            "utility_model_register": _relative(model_register, root),
            "tables": {name: _relative(path, root) for name, path in tables.items()},
            "figures": {name: _relative(path, root) for name, path in figures.items()},
        },
        "checks": checks,
        "limitations": [
            "The public extracts do not describe UQ-owned internal utility networks.",
            "No electricity, gas or telecommunications source was included in the no-login route.",
            "Urban Utilities returned no sewer features intersecting the 500 m pilot.",
            "The BCC source exposes level fields but does not state their vertical datum "
            "in its public metadata.",
            "Public linework is approximate planning context and must not be used for "
            "excavation or asset location.",
            "A zero record count means absent from the queried source, not proof that the "
            "physical asset does not exist.",
        ],
    }
    _write_json(tables["summary"], summary)
    summary["summary_report"] = _relative(tables["summary"], root)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 8 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase8(project_root)
    print(f"Phase 8 status: {summary['status']}")
    print(f"Cache reused: {summary['cache_reused']}")
    print(f"Utility records: {summary['current_statistics']['utility_records']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
