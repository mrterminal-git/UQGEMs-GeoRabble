"""Run and validate Phase 5 terrain and LiDAR preparation."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import Any

import laspy
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.normalization import TARGET_EPSG
from uqgems.preparation import (
    ANALYSIS_MAX_HEIGHT_M,
    ANALYSIS_MIN_HEIGHT_M,
    DISPLAY_TARGET_POINTS,
    NOISE_CLASSES,
    RASTER_HEIGHT,
    RASTER_RESOLUTION_M,
    RASTER_WIDTH,
    crop_dtm,
    crop_laz_with_pdal,
    deterministic_display_sample,
    filter_analysis_laz,
    hillshade,
    laz_classification_counts,
    point_cloud_rasters,
    read_dtm,
    write_count_raster,
    write_float_raster,
)

PHASE5_SCHEMA_VERSION = 1
PREPARATION_REGISTER_FIELDS = (
    "dataset",
    "source_path",
    "source_sha256",
    "output_path",
    "output_sha256",
    "crs",
    "vertical_datum",
    "resolution_or_sampling",
    "processing",
    "feature_or_cell_count",
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
    pdal_result = subprocess.run(
        ["pdal", "--version"], check=True, capture_output=True, text=True
    )
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "laspy": laspy.__version__,
        "pdal": pdal_result.stdout.strip(),
        "uqgems": version("uqgems"),
    }


def _signature(sources: dict[str, Path]) -> tuple[str, dict[str, Any]]:
    payload = {
        "schema_version": PHASE5_SCHEMA_VERSION,
        "source_sha256": {name: sha256(path) for name, path in sources.items()},
        "pilot_bounds_epsg_7856": list(PILOT_AREA.projected_bounds),
        "raster_resolution_m": RASTER_RESOLUTION_M,
        "analysis_height_range_m": [ANALYSIS_MIN_HEIGHT_M, ANALYSIS_MAX_HEIGHT_M],
        "excluded_asprs_classes": list(NOISE_CLASSES),
        "display_target_points": DISPLAY_TARGET_POINTS,
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialised).hexdigest(), payload


def _inspect_raster(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as source:
        data = source.read(1, masked=True)
        valid = data.compressed()
        result: dict[str, Any] = {
            "path": str(path),
            "epsg": source.crs.to_epsg() if source.crs else None,
            "bounds": list(source.bounds),
            "resolution": list(source.res),
            "shape": [source.height, source.width],
            "dtype": source.dtypes[0],
            "nodata": source.nodata,
            "valid_cells": int(valid.size),
            "minimum": float(valid.min()) if valid.size else None,
            "maximum": float(valid.max()) if valid.size else None,
            "mean": float(valid.mean()) if valid.size else None,
            "sha256": sha256(path),
        }
        if np.issubdtype(valid.dtype, np.integer):
            result["sum"] = int(valid.astype(np.uint64).sum())
        return result


def _inspect_laz(path: Path) -> dict[str, Any]:
    with laspy.open(path) as source:
        header = source.header
        crs = header.parse_crs()
        return {
            "path": str(path),
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
            "sha256": sha256(path),
        }


def _bounds_inside(
    inner: list[float], outer: tuple[float, float, float, float], *, tolerance: float
) -> bool:
    return bool(
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _same_grid(rasters: dict[str, dict[str, Any]]) -> bool:
    expected_bounds = list(PILOT_AREA.projected_bounds)
    return all(
        info["epsg"] == TARGET_EPSG
        and info["shape"] == [RASTER_HEIGHT, RASTER_WIDTH]
        and np.allclose(info["resolution"], [RASTER_RESOLUTION_M, RASTER_RESOLUTION_M])
        and np.allclose(info["bounds"], expected_bounds)
        for info in rasters.values()
    )


def _read_raster(path: Path) -> np.ndarray:
    with rasterio.open(path) as source:
        values = source.read(1).astype(float)
        if source.nodata is not None:
            values[values == source.nodata] = np.nan
        return values


def _class_count(classifications: dict[str, Any], code: int) -> int:
    return int(classifications.get(str(code), {}).get("count", 0))


def _classification_figure(
    full_counts: dict[str, Any], filtered_counts: dict[str, Any], output: Path
) -> Path:
    codes = sorted({int(code) for code in full_counts} | {int(code) for code in filtered_counts})
    metadata = [full_counts.get(str(code)) or filtered_counts[str(code)] for code in codes]
    labels = [f"{code}: {item['name']}" for code, item in zip(codes, metadata, strict=True)]
    full = np.asarray([_class_count(full_counts, code) for code in codes])
    filtered = np.asarray([_class_count(filtered_counts, code) for code in codes])
    positions = np.arange(len(codes))
    figure, axis = plt.subplots(figsize=(11, 6), constrained_layout=True)
    axis.bar(positions - 0.2, full, width=0.4, label="Full crop", color="#607d8b")
    axis.bar(positions + 0.2, filtered, width=0.4, label="Analysis crop", color="#1769aa")
    axis.set(
        yscale="symlog",
        ylabel="Point count (symlog scale)",
        title="LiDAR classifications before and after analysis filtering",
        xticks=positions,
        xticklabels=labels,
    )
    axis.tick_params(axis="x", rotation=42)
    axis.grid(axis="y", alpha=0.25)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _map_figure(
    data: np.ndarray,
    output: Path,
    *,
    title: str,
    colour_map: str,
    colour_label: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Path:
    extent = [PILOT_AREA.west, PILOT_AREA.east, PILOT_AREA.south, PILOT_AREA.north]
    figure, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    image = axis.imshow(
        data,
        extent=extent,
        origin="upper",
        cmap=colour_map,
        vmin=minimum,
        vmax=maximum,
    )
    axis.set(
        title=title,
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    figure.colorbar(image, ax=axis, shrink=0.78, label=colour_label)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _ground_residual_figure(data: np.ndarray, output: Path) -> Path:
    valid = data[np.isfinite(data)]
    limit = max(0.25, float(np.percentile(np.abs(valid), 99)))
    histogram_low, histogram_high = np.percentile(valid, [0.5, 99.5])
    histogram_values = valid[(valid >= histogram_low) & (valid <= histogram_high)]
    extent = [PILOT_AREA.west, PILOT_AREA.east, PILOT_AREA.south, PILOT_AREA.north]
    figure, axes = plt.subplots(1, 2, figsize=(12, 5.5), constrained_layout=True)
    image = axes[0].imshow(
        data,
        extent=extent,
        origin="upper",
        cmap="RdBu_r",
        vmin=-limit,
        vmax=limit,
    )
    axes[0].set(
        title="Mean class-2 ground minus DTM",
        xlabel="Easting (m)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axes[0].ticklabel_format(style="plain", useOffset=False)
    figure.colorbar(image, ax=axes[0], shrink=0.78, label="Residual (m)")
    axes[1].hist(histogram_values, bins=80, color="#1769aa", alpha=0.85)
    axes[1].axvline(0, color="black", linewidth=1)
    axes[1].set(
        title="Cell-mean ground residual distribution (central 99%)",
        xlabel="Residual (m)",
        ylabel="One-metre cells",
    )
    axes[1].grid(axis="y", alpha=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def _create_figures(
    outputs: dict[str, Path],
    statistics: dict[str, Any],
    figure_paths: dict[str, Path],
) -> dict[str, Path]:
    dtm, _ = read_dtm(outputs["dtm"])
    density = _read_raster(outputs["point_density"])
    height = _read_raster(outputs["height_above_ground"])
    residual = _read_raster(outputs["ground_residual"])
    density_limit = max(1.0, float(np.nanpercentile(density, 99)))
    height_limit = max(1.0, float(np.nanpercentile(height, 99)))
    _classification_figure(
        statistics["full_classification_counts"],
        statistics["analysis"]["classification_counts"],
        figure_paths["classifications"],
    )
    _map_figure(
        density,
        figure_paths["density"],
        title="Filtered LiDAR point density (99th percentile colour limit)",
        colour_map="viridis",
        colour_label="Points per square metre",
        minimum=0,
        maximum=density_limit,
    )
    _map_figure(
        hillshade(dtm),
        figure_paths["hillshade"],
        title="UQ pilot bare-earth terrain hillshade",
        colour_map="gray",
        colour_label="Relative illumination",
        minimum=0,
        maximum=1,
    )
    _map_figure(
        height,
        figure_paths["height"],
        title="Normalised surface height (99th percentile colour limit)",
        colour_map="magma",
        colour_label="Height above DTM (m)",
        minimum=0,
        maximum=height_limit,
    )
    _ground_residual_figure(residual, figure_paths["ground_residual"])
    return figure_paths


def _register_rows(
    root: Path,
    sources: dict[str, Path],
    outputs: dict[str, Path],
    laz_info: dict[str, dict[str, Any]],
    raster_info: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    dem_hash = sha256(sources["dem"])
    laz_hash = sha256(sources["laz"])
    common_raster = {
        "source_path": _relative(sources["dem"], root),
        "source_sha256": dem_hash,
        "crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
        "vertical_datum": "AHD",
        "resolution_or_sampling": "1 m grid; exact 500 m x 500 m pilot AOI",
        "feature_or_cell_count": RASTER_WIDTH * RASTER_HEIGHT,
        "validation_status": "passed",
    }
    rows = [
        {
            "dataset": "Phase 5 cropped DTM",
            **common_raster,
            "output_path": _relative(outputs["dtm"], root),
            "output_sha256": raster_info["dtm"]["sha256"],
            "processing": "Bilinear resampling of Phase 4 DTM to exact pilot grid",
            "notes": "Bare-earth terrain; authoritative coordinates retained.",
        },
        {
            "dataset": "Phase 5 DSM",
            **common_raster,
            "source_path": _relative(sources["laz"], root),
            "source_sha256": laz_hash,
            "output_path": _relative(outputs["dsm"], root),
            "output_sha256": raster_info["dsm"]["sha256"],
            "processing": "Maximum retained LiDAR Z per cell; empty valid cells filled from DTM",
            "notes": "Surface model derived after declared noise and height filtering.",
        },
        {
            "dataset": "Phase 5 raw surface minus DTM",
            **common_raster,
            "source_path": f"{_relative(outputs['dsm'], root)} + {_relative(outputs['dtm'], root)}",
            "source_sha256": f"{raster_info['dsm']['sha256']} + {raster_info['dtm']['sha256']}",
            "output_path": _relative(outputs["raw_height"], root),
            "output_sha256": raster_info["raw_height"]["sha256"],
            "processing": "DSM minus DTM; signed diagnostic retained",
            "notes": "Negative residuals are retained for diagnosis.",
        },
        {
            "dataset": "Phase 5 height above ground",
            **common_raster,
            "source_path": _relative(outputs["raw_height"], root),
            "source_sha256": raster_info["raw_height"]["sha256"],
            "output_path": _relative(outputs["height_above_ground"], root),
            "output_sha256": raster_info["height_above_ground"]["sha256"],
            "processing": "Maximum of signed DSM-minus-DTM and zero",
            "notes": "Modelling-ready normalised surface height; not yet a building LoD model.",
        },
        {
            "dataset": "Phase 5 filtered point density",
            **common_raster,
            "source_path": _relative(outputs["analysis_laz"], root),
            "source_sha256": laz_info["analysis_laz"]["sha256"],
            "output_path": _relative(outputs["point_density"], root),
            "output_sha256": raster_info["point_density"]["sha256"],
            "processing": "Count of retained LiDAR points in each one-metre cell",
            "notes": "Zero is a valid count.",
        },
        {
            "dataset": "Phase 5 ground point density",
            **common_raster,
            "source_path": _relative(outputs["analysis_laz"], root),
            "source_sha256": laz_info["analysis_laz"]["sha256"],
            "output_path": _relative(outputs["ground_density"], root),
            "output_sha256": raster_info["ground_density"]["sha256"],
            "processing": "Count of retained ASPRS class-2 points in each one-metre cell",
            "notes": "Supports ground-coverage review.",
        },
        {
            "dataset": "Phase 5 ground-to-DTM residual",
            **common_raster,
            "source_path": _relative(outputs["analysis_laz"], root),
            "source_sha256": laz_info["analysis_laz"]["sha256"],
            "output_path": _relative(outputs["ground_residual"], root),
            "output_sha256": raster_info["ground_residual"]["sha256"],
            "processing": "Mean class-2 LiDAR Z per cell minus DTM",
            "notes": "NoData where a cell has no class-2 point.",
        },
    ]
    laz_rows = [
        (
            "full_laz",
            "Phase 5 full-resolution audit crop",
            "Exact spatial crop only; no points deliberately filtered",
            "All source attributes/classes retained within AOI.",
        ),
        (
            "analysis_laz",
            "Phase 5 modelling analysis crop",
            "Remove ASPRS 7/18 and DTM-relative heights outside -2 to +80 m",
            "Filtering is reproducible; use the full crop to audit removed points.",
        ),
        (
            "display_laz",
            "Phase 5 deterministic display sample",
            "Global stride sample from filtered analysis crop",
            "For responsive visualisation only; not for measurement or modelling.",
        ),
    ]
    for key, dataset, processing, notes in laz_rows:
        info = laz_info[key]
        lineage_source = {
            "full_laz": sources["laz"],
            "analysis_laz": outputs["full_laz"],
            "display_laz": outputs["analysis_laz"],
        }[key]
        rows.append(
            {
                "dataset": dataset,
                "source_path": _relative(lineage_source, root),
                "source_sha256": sha256(lineage_source),
                "output_path": _relative(outputs[key], root),
                "output_sha256": info["sha256"],
                "crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
                "vertical_datum": "AHD",
                "resolution_or_sampling": (
                    "full retained resolution" if key != "display_laz" else "deterministic stride"
                ),
                "processing": processing,
                "feature_or_cell_count": info["point_count"],
                "validation_status": "passed",
                "notes": notes,
            }
        )
    return rows


def _write_register(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=PREPARATION_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_phase5(project_root: str | Path) -> dict[str, Any]:
    """Crop, filter, rasterise and validate Phase 4 elevation data."""
    root = Path(project_root).resolve()
    normalised = root / "data" / "interim" / "normalised" / "elevation"
    sources = {
        "dem": normalised / "brisbane_2019_dem_1m_epsg7856.tif",
        "laz": normalised / "brisbane_2019_classified_ahd_epsg7856.laz",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Phase 5 needs the completed Phase 4 elevation inputs. Missing: "
            + ", ".join(missing)
        )

    output_root = root / "data" / "interim" / "phase5"
    outputs = {
        "dtm": output_root / "elevation" / "dtm_1m.tif",
        "dsm": output_root / "elevation" / "dsm_1m.tif",
        "raw_height": output_root / "elevation" / "surface_minus_dtm_raw.tif",
        "height_above_ground": output_root / "elevation" / "height_above_ground.tif",
        "point_density": output_root / "elevation" / "point_density_1m.tif",
        "ground_density": output_root / "elevation" / "ground_density_1m.tif",
        "ground_residual": output_root / "elevation" / "ground_residual_1m.tif",
        "full_laz": output_root / "pointcloud" / "uq_pilot_cropped_full.laz",
        "analysis_laz": output_root / "pointcloud" / "uq_pilot_analysis_filtered.laz",
        "display_laz": output_root / "pointcloud" / "uq_pilot_display.laz",
        "manifest": output_root / "preparation_manifest.json",
    }
    figure_root = root / "reports" / "figures"
    figure_paths = {
        "classifications": figure_root / "phase5_classification_counts.png",
        "density": figure_root / "phase5_point_density.png",
        "hillshade": figure_root / "phase5_terrain_hillshade.png",
        "height": figure_root / "phase5_height_above_ground.png",
        "ground_residual": figure_root / "phase5_ground_dtm_residual.png",
    }
    signature, signature_payload = _signature(sources)
    previous_manifest: dict[str, Any] = {}
    if outputs["manifest"].is_file():
        previous_manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    generated_names = [name for name in outputs if name != "manifest"]
    recorded_outputs = previous_manifest.get("outputs", {})
    cache_reused = bool(
        previous_manifest.get("configuration_signature") == signature
        and all(
            outputs[name].is_file()
            and recorded_outputs.get(_relative(outputs[name], root)) == sha256(outputs[name])
            for name in generated_names
        )
    )

    processing_logs: dict[str, Any] = {}
    if cache_reused:
        statistics = previous_manifest["generation_statistics"]
    else:
        crop_dtm(sources["dem"], outputs["dtm"])
        processing_logs["pdal_crop"] = crop_laz_with_pdal(
            sources["laz"],
            outputs["full_laz"],
            root / "reports" / "tables" / "phase5_pdal_crop_pipeline.json",
            root / "reports" / "tables" / "phase5_pdal_crop_metadata.json",
        )
        filtering = filter_analysis_laz(
            outputs["full_laz"], outputs["analysis_laz"], outputs["dtm"]
        )
        sampling = deterministic_display_sample(
            outputs["analysis_laz"],
            outputs["display_laz"],
            target_points=DISPLAY_TARGET_POINTS,
        )
        arrays, analysis_statistics = point_cloud_rasters(
            outputs["analysis_laz"], outputs["dtm"]
        )
        write_float_raster(
            outputs["dsm"],
            arrays["dsm"],
            tags={"PHASE": "5", "PRODUCT": "DSM", "VERTICAL_DATUM": "AHD"},
        )
        write_float_raster(
            outputs["raw_height"],
            arrays["surface_minus_dtm_raw"],
            tags={
                "PHASE": "5",
                "PRODUCT": "signed surface minus DTM",
                "UNITS": "metres",
            },
        )
        write_float_raster(
            outputs["height_above_ground"],
            arrays["height_above_ground"],
            tags={"PHASE": "5", "PRODUCT": "height above ground", "UNITS": "metres"},
        )
        write_count_raster(
            outputs["point_density"], arrays["point_density"], product="point density"
        )
        write_count_raster(
            outputs["ground_density"], arrays["ground_density"], product="ground density"
        )
        write_float_raster(
            outputs["ground_residual"],
            arrays["ground_residual"],
            tags={
                "PHASE": "5",
                "PRODUCT": "mean class-2 ground minus DTM",
                "UNITS": "metres",
            },
        )
        statistics = {
            "filtering": filtering,
            "display_sampling": sampling,
            "full_classification_counts": laz_classification_counts(outputs["full_laz"]),
            "analysis": analysis_statistics,
        }

    laz_info = {
        name: _inspect_laz(outputs[name])
        for name in ("full_laz", "analysis_laz", "display_laz")
    }
    raster_info = {
        name: _inspect_raster(outputs[name])
        for name in (
            "dtm",
            "dsm",
            "raw_height",
            "height_above_ground",
            "point_density",
            "ground_density",
            "ground_residual",
        )
    }
    full_class_total = sum(
        int(item["count"]) for item in statistics["full_classification_counts"].values()
    )
    analysis_class_total = sum(
        int(item["count"])
        for item in statistics["analysis"]["classification_counts"].values()
    )
    filtering = statistics["filtering"]
    sampling = statistics["display_sampling"]
    residuals = statistics["analysis"]["ground_dtm_comparison"]
    checks = {
        "all_rasters_share_exact_pilot_grid": _same_grid(raster_info),
        "dtm_has_complete_pilot_coverage": raster_info["dtm"]["valid_cells"]
        == RASTER_WIDTH * RASTER_HEIGHT,
        "full_crop_crs_is_epsg_7856": laz_info["full_laz"]["epsg"] == TARGET_EPSG,
        "analysis_crop_crs_is_epsg_7856": laz_info["analysis_laz"]["epsg"] == TARGET_EPSG,
        "display_sample_crs_is_epsg_7856": laz_info["display_laz"]["epsg"] == TARGET_EPSG,
        "full_crop_bounds_are_inside_pilot": _bounds_inside(
            laz_info["full_laz"]["bounds"], PILOT_AREA.projected_bounds, tolerance=0.02
        ),
        "full_crop_contains_points": laz_info["full_laz"]["point_count"] > 0,
        "filter_accounting_is_exact": filtering["input_points"]
        == filtering["retained_points"] + filtering["removed_total"],
        "analysis_count_matches_filter_log": laz_info["analysis_laz"]["point_count"]
        == filtering["retained_points"],
        "display_count_matches_sample_log": laz_info["display_laz"]["point_count"]
        == sampling["output_points"],
        "display_sample_is_bounded": laz_info["display_laz"]["point_count"]
        <= DISPLAY_TARGET_POINTS,
        "full_classification_accounting_is_exact": full_class_total
        == laz_info["full_laz"]["point_count"],
        "analysis_classification_accounting_is_exact": analysis_class_total
        == laz_info["analysis_laz"]["point_count"],
        "declared_noise_classes_removed": all(
            _class_count(statistics["analysis"]["classification_counts"], code) == 0
            for code in NOISE_CLASSES
        ),
        "analysis_height_range_enforced": filtering["retained_minimum_height_m"]
        >= ANALYSIS_MIN_HEIGHT_M
        and filtering["retained_maximum_height_m"] <= ANALYSIS_MAX_HEIGHT_M,
        "ground_class_available": _class_count(
            statistics["analysis"]["classification_counts"], 2
        )
        > 0,
        "building_class_available": _class_count(
            statistics["analysis"]["classification_counts"], 6
        )
        > 0,
        "density_sum_matches_analysis_points": raster_info["point_density"]["sum"]
        == laz_info["analysis_laz"]["point_count"],
        "normalised_height_is_nonnegative": raster_info["height_above_ground"]["minimum"]
        >= 0,
        "normalised_height_respects_filter_ceiling": raster_info["height_above_ground"]["maximum"]
        <= ANALYSIS_MAX_HEIGHT_M + 0.01,
        "ground_dtm_median_is_consistent": abs(residuals["median_m"]) < 0.25,
        "ground_dtm_rmse_is_consistent": residuals["rmse_m"] < 1.0,
    }

    software = _software_versions()
    register = _write_register(
        root / "data" / "preparation_register.csv",
        _register_rows(root, sources, outputs, laz_info, raster_info),
    )
    figures = _create_figures(outputs, statistics, figure_paths)
    output_hashes = {
        _relative(outputs[name], root): sha256(outputs[name]) for name in generated_names
    }
    manifest = {
        "configuration_signature": signature,
        "signature_inputs": signature_payload,
        "outputs": output_hashes,
        "generation_statistics": statistics,
    }
    if all(checks.values()):
        _write_json(outputs["manifest"], manifest)

    summary_path = root / "reports" / "tables" / "phase5_preparation.json"
    summary = {
        "phase": 5,
        "status": "passed" if all(checks.values()) else "failed",
        "cache_reused": cache_reused,
        "pilot_area": {
            "bounds": list(PILOT_AREA.projected_bounds),
            "area_m2": 250_000,
            "crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "vertical_datum": "AHD",
        },
        "configuration": {
            "raster_resolution_m": RASTER_RESOLUTION_M,
            "analysis_height_range_m": [ANALYSIS_MIN_HEIGHT_M, ANALYSIS_MAX_HEIGHT_M],
            "excluded_asprs_classes": list(NOISE_CLASSES),
            "display_target_points": DISPLAY_TARGET_POINTS,
            "dsm_empty_cell_policy": "fill from DTM, giving zero height above ground",
            "height_above_ground_policy": (
                "retain signed diagnostic, clamp modelling raster at zero"
            ),
        },
        "sources": {name: _relative(path, root) for name, path in sources.items()},
        "point_clouds": laz_info,
        "rasters": raster_info,
        "statistics": statistics,
        "software": software,
        "processing_logs": processing_logs,
        "outputs": {
            **{name: _relative(path, root) for name, path in outputs.items()},
            "preparation_register": _relative(register, root),
            "figures": {name: _relative(path, root) for name, path in figures.items()},
        },
        "checks": checks,
        "limitations": [
            "The DSM stores the maximum retained return per one-metre cell, not a "
            "reconstructed roof surface.",
            "Empty DSM cells are filled from the DTM and therefore receive zero normalised height.",
            "The DTM-relative -2 to +80 m rule is a documented generic outlier screen, "
            "not semantic classification.",
            "The deterministic display sample is intended only for responsive inspection.",
            "These products prepare inputs for LoD generation; they are not themselves "
            "LoD1 or LoD2 buildings.",
        ],
    }
    _write_json(summary_path, summary)
    summary["summary_report"] = _relative(summary_path, root)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 5 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase5(project_root)
    print(f"Phase 5 status: {summary['status']}")
    print(f"Cache reused: {summary['cache_reused']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
