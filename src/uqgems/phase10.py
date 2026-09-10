"""Non-destructive reproducibility and validation audit for Phases 1-9."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import laspy
import matplotlib.pyplot as plt
import nbformat
import pandas as pd
import pyogrio
import rasterio
from matplotlib.patches import Patch
from nbconvert.preprocessors import ExecutePreprocessor
from PIL import Image
from pyproj import CRS

from uqgems.acquisition import sha256
from uqgems.environment import collect_environment, missing_commands, missing_modules
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG

PHASE10_SCHEMA_VERSION = 1
KERNEL_NAME = "uq-gis"


@dataclass(frozen=True)
class NotebookSpec:
    """One notebook in the required fresh-kernel execution order."""

    phase: int
    label: str
    filename: str


PRIOR_NOTEBOOKS = (
    NotebookSpec(1, "Environment", "00_environment_check.ipynb"),
    NotebookSpec(2, "Synthetic workflow", "phase2_synthetic_workflow.ipynb"),
    NotebookSpec(3, "Data inventory", "01_phase3_data_inventory.ipynb"),
    NotebookSpec(4, "Coordinate normalisation", "02_phase4_coordinate_normalisation.ipynb"),
    NotebookSpec(5, "Terrain and LiDAR", "03_phase5_terrain_lidar_preparation.ipynb"),
    NotebookSpec(6, "LoD1 buildings", "04_phase6_lod1_buildings.ipynb"),
    NotebookSpec(7, "Selective LoD2", "05_phase7_lod2_feasibility.ipynb"),
    NotebookSpec(8, "Public utilities", "06_phase8_utility_standardisation.ipynb"),
    NotebookSpec(9, "Integrated visualisation", "07_phase9_integrated_visualisation.ipynb"),
)
VALIDATION_NOTEBOOK = NotebookSpec(
    10,
    "Reproducibility validation",
    "08_phase10_reproducibility_validation.ipynb",
)

PHASE_REPORTS = {
    2: "reports/tables/phase2_summary.json",
    3: "reports/tables/phase3_inventory.json",
    4: "reports/tables/phase4_normalisation.json",
    5: "reports/tables/phase5_preparation.json",
    6: "reports/tables/phase6_lod1.json",
    7: "reports/tables/phase7_lod2.json",
    8: "reports/tables/phase8_utilities.json",
    9: "reports/tables/phase9_scene.json",
}

MANIFEST_PATHS = (
    "data/interim/normalised/normalisation_manifest.json",
    "data/interim/phase5/preparation_manifest.json",
    "data/processed/lod1/lod1_manifest.json",
    "data/processed/lod2/lod2_manifest.json",
    "data/processed/utilities/utility_manifest.json",
    "data/processed/scene/phase9_manifest.json",
)

MODEL_REGISTER_SPECS = {
    "normalisation_register.csv": (
        "target_path",
        "target_sha256",
        ("dataset", "source_path", "source_sha256", "source_crs", "target_crs", "vertical_datum"),
    ),
    "preparation_register.csv": (
        "output_path",
        "output_sha256",
        ("dataset", "source_path", "source_sha256", "crs", "vertical_datum", "processing"),
    ),
    "building_model_register.csv": (
        "output_path",
        "output_sha256",
        ("dataset", "source_paths", "source_sha256", "crs", "vertical_datum", "processing"),
    ),
    "lod2_model_register.csv": (
        "output_path",
        "output_sha256",
        ("dataset", "source_paths", "source_sha256", "crs", "vertical_datum", "processing"),
    ),
    "utility_model_register.csv": (
        "output_path",
        "output_sha256",
        ("dataset", "source_paths", "source_sha256", "crs", "vertical_datum", "processing"),
    ),
    "scene_model_register.csv": (
        "output_path",
        "output_sha256",
        (
            "dataset",
            "source_paths",
            "source_sha256",
            "horizontal_crs",
            "vertical_reference",
            "processing",
        ),
    ),
}

REQUIRED_DOCUMENTS = (
    "PLAN_OF_ACTION.md",
    "PHASE3_DATA_PROVENANCE.md",
    "PHASE4_CRS_NORMALISATION.md",
    "PHASE5_TERRAIN_LIDAR_PREPARATION.md",
    "PHASE6_LOD1_BUILDINGS.md",
    "PHASE7_LOD2_FEASIBILITY.md",
    "PHASE8_UTILITY_STANDARDISATION.md",
    "PHASE9_INTEGRATED_VISUALISATION.md",
    "PHASE10_REPRODUCIBILITY_VALIDATION.md",
    "data/manual/README.md",
)


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _flatten_paths(value: Any) -> list[str]:
    """Return string leaves from nested phase-output dictionaries."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        paths: list[str] = []
        for child in value.values():
            paths.extend(_flatten_paths(child))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for child in value:
            paths.extend(_flatten_paths(child))
        return paths
    return []


def _directory_records_sha256(path: Path) -> str:
    """Recreate the Phase 8 directory hash from ordered GeoJSON record hashes."""
    record_paths = sorted(path.glob("*.geojson"))
    return hashlib.sha256("".join(sha256(item) for item in record_paths).encode()).hexdigest()


def _path_sha256(path: Path, cache: dict[Path, str]) -> str | None:
    resolved = path.resolve()
    if not resolved.exists():
        return None
    if resolved not in cache:
        cache[resolved] = (
            _directory_records_sha256(resolved) if resolved.is_dir() else sha256(resolved)
        )
    return cache[resolved]


def _registered_output_target(value: str) -> tuple[str, str]:
    """Split the ``file.gpkg:layer`` convention used by the Phase 4 register."""
    marker = ".gpkg:"
    if marker not in value:
        return value, ""
    path_prefix, layer = value.split(marker, maxsplit=1)
    return f"{path_prefix}.gpkg", layer


def _executed_notebook_path(root: Path, spec: NotebookSpec) -> Path:
    return (
        root
        / "reports/tables/phase10_notebooks"
        / f"{spec.phase:02d}_{Path(spec.filename).stem}.executed.ipynb"
    )


def _inspect_notebook(
    root: Path,
    spec: NotebookSpec,
    executed: nbformat.NotebookNode,
    *,
    source_sha256: str,
    execution_id: str,
    started_at: str,
    finished_at: str,
    duration_s: float,
    error: str,
) -> dict[str, Any]:
    code_cells = [cell for cell in executed.cells if cell.cell_type == "code"]
    error_outputs = [
        output
        for cell in code_cells
        for output in cell.get("outputs", [])
        if output.get("output_type") == "error"
    ]
    executed_cells = sum(cell.get("execution_count") is not None for cell in code_cells)
    output_path = _executed_notebook_path(root, spec)
    return {
        "phase": spec.phase,
        "label": spec.label,
        "source_notebook": f"notebooks/{spec.filename}",
        "source_sha256": source_sha256,
        "executed_notebook": _relative(output_path, root),
        "executed_sha256": sha256(output_path) if output_path.is_file() else "",
        "kernel": KERNEL_NAME,
        "fresh_kernel_session": execution_id,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "duration_seconds": round(duration_s, 3),
        "code_cells": len(code_cells),
        "executed_code_cells": executed_cells,
        "error_outputs": len(error_outputs),
        "status": (
            "passed"
            if not error and not error_outputs and executed_cells == len(code_cells)
            else "failed"
        ),
        "error": error,
    }


def execute_notebook(root: Path, spec: NotebookSpec, *, timeout_s: int = 900) -> dict[str, Any]:
    """Execute one source notebook in a new kernel and preserve a separate copy."""
    source_path = root / "notebooks" / spec.filename
    if not source_path.is_file():
        return {
            "phase": spec.phase,
            "label": spec.label,
            "source_notebook": _relative(source_path, root),
            "source_sha256": "",
            "executed_notebook": _relative(_executed_notebook_path(root, spec), root),
            "executed_sha256": "",
            "kernel": KERNEL_NAME,
            "fresh_kernel_session": "",
            "started_at_utc": "",
            "finished_at_utc": "",
            "duration_seconds": 0.0,
            "code_cells": 0,
            "executed_code_cells": 0,
            "error_outputs": 0,
            "status": "failed",
            "error": "source notebook missing",
        }

    execution_id = str(uuid.uuid4())
    started_datetime = datetime.now(UTC)
    started = time.perf_counter()
    notebook = nbformat.read(source_path, as_version=4)
    error = ""
    try:
        processor = ExecutePreprocessor(
            timeout=timeout_s,
            startup_timeout=120,
            kernel_name=KERNEL_NAME,
            allow_errors=False,
        )
        processor.preprocess(notebook, {"metadata": {"path": str(root)}})
    except Exception as exc:  # preserve the failing notebook and audit every stage
        error = f"{type(exc).__name__}: {exc}"
    duration = time.perf_counter() - started
    output_path = _executed_notebook_path(root, spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, output_path)
    return _inspect_notebook(
        root,
        spec,
        notebook,
        source_sha256=sha256(source_path),
        execution_id=execution_id,
        started_at=started_datetime.isoformat(),
        finished_at=datetime.now(UTC).isoformat(),
        duration_s=duration,
        error=error,
    )


def _phase_results(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for phase, relative_path in PHASE_REPORTS.items():
        path = root / relative_path
        payload: dict[str, Any] = {}
        parse_error = ""
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                parse_error = f"{type(exc).__name__}: {exc}"
        checks = payload.get("checks", {})
        declared_outputs = sorted(set(_flatten_paths(payload.get("outputs", {}))))
        existing_outputs = sum((root / item).exists() for item in declared_outputs)
        rows.append(
            {
                "phase": phase,
                "report": relative_path,
                "report_exists": path.is_file(),
                "report_phase_matches": payload.get("phase") == phase,
                "status": payload.get("status", "missing"),
                "checks_passed": sum(value is True for value in checks.values()),
                "checks_total": len(checks),
                "all_checks_passed": bool(checks)
                and all(value is True for value in checks.values()),
                "cache_reused": payload.get("cache_reused", "not applicable"),
                "declared_outputs": len(declared_outputs),
                "existing_outputs": existing_outputs,
                "all_declared_outputs_exist": existing_outputs == len(declared_outputs),
                "parse_error": parse_error,
            }
        )
    return pd.DataFrame(rows)


def _manifest_expected_outputs(root: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    rows: list[dict[str, Any]] = []
    expected: dict[str, str] = {}
    for relative_path in MANIFEST_PATHS:
        manifest_path = root / relative_path
        if not manifest_path.is_file():
            rows.append(
                {
                    "manifest": relative_path,
                    "configuration_signature_present": False,
                    "signature_inputs_present": False,
                    "declared_outputs": 0,
                    "status": "missing",
                }
            )
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = payload.get("outputs")
        if not isinstance(outputs, dict):
            outputs = payload.get("output_sha256")
        if isinstance(outputs, str):
            outputs = {"data/processed/utilities/uq_pilot_public_utilities.gpkg": outputs}
        if not isinstance(outputs, dict):
            outputs = {}
        for output_path, expected_hash in outputs.items():
            expected[str(output_path)] = str(expected_hash)
        configuration_signature = str(payload.get("configuration_signature", ""))
        rows.append(
            {
                "manifest": relative_path,
                "configuration_signature_present": len(configuration_signature) == 64,
                "signature_inputs_present": bool(payload.get("signature_inputs")),
                "declared_outputs": len(outputs),
                "status": "passed",
            }
        )
    return pd.DataFrame(rows), expected


def _hash_audit(
    root: Path,
    before_replay: dict[str, str | None] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    manifest_rows, expected = _manifest_expected_outputs(root)
    cache: dict[Path, str] = {}
    rows = []
    for relative_path, expected_hash in expected.items():
        path = root / relative_path
        actual = _path_sha256(path, cache)
        before = before_replay.get(relative_path) if before_replay is not None else None
        rows.append(
            {
                "path": relative_path,
                "expected_sha256": expected_hash,
                "before_replay_sha256": before or "",
                "actual_sha256": actual or "",
                "exists": path.exists(),
                "matches_manifest": actual == expected_hash,
                "unchanged_by_replay": before == actual if before_replay is not None else "not run",
            }
        )
    return manifest_rows, pd.DataFrame(rows)


def _dataset_register_audit(root: Path, hash_cache: dict[Path, str]) -> pd.DataFrame:
    register = pd.read_csv(root / "data/dataset_register.csv", dtype=str).fillna("")
    standard_fields = (
        "dataset",
        "source",
        "capture_date",
        "licence",
        "horizontal_crs",
        "vertical_datum",
        "resolution",
        "stated_accuracy",
        "processing_status",
        "notes",
    )
    rows = []
    for row in register.itertuples(index=False):
        values = row._asdict()
        deferred = "deferred" in values["processing_status"].lower()
        path_text = values["local_path"].strip()
        path = root / path_text if path_text else None
        actual_hash = _path_sha256(path, hash_cache) if path is not None else None
        metadata_complete = all(str(values[field]).strip() for field in standard_fields)
        acquired_fields_complete = bool(
            deferred or (path_text and values["download_date"].strip() and values["sha256"].strip())
        )
        rows.append(
            {
                "dataset": values["dataset"],
                "processing_status": values["processing_status"],
                "deferred_source": deferred,
                "metadata_complete": metadata_complete and acquired_fields_complete,
                "local_path": path_text,
                "path_exists": path.exists() if path is not None else deferred,
                "expected_sha256": values["sha256"],
                "actual_sha256": actual_hash or "",
                "hash_matches": actual_hash == values["sha256"] if path is not None else deferred,
                "status": (
                    "documented deferred source"
                    if deferred and metadata_complete
                    else (
                        "passed"
                        if metadata_complete
                        and acquired_fields_complete
                        and path is not None
                        and path.exists()
                        and actual_hash == values["sha256"]
                        else "failed"
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def _model_register_audit(root: Path, hash_cache: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for filename, (path_field, hash_field, required_fields) in MODEL_REGISTER_SPECS.items():
        path = root / "data" / filename
        if not path.is_file():
            rows.append(
                {
                    "register": filename,
                    "dataset": "",
                    "metadata_complete": False,
                    "validation_status": "missing",
                    "output_path": "",
                    "output_exists": False,
                    "hash_matches": False,
                    "status": "failed",
                }
            )
            continue
        register = pd.read_csv(path, dtype=str).fillna("")
        for record in register.to_dict(orient="records"):
            output_path, output_layer = _registered_output_target(record[path_field])
            output = root / output_path
            actual_hash = _path_sha256(output, hash_cache)
            complete = all(str(record[field]).strip() for field in required_fields)
            validation_passed = str(record["validation_status"]).startswith("passed")
            hash_matches = actual_hash == record[hash_field]
            layer_exists = bool(
                not output_layer
                or (output.is_file() and output_layer in set(pyogrio.list_layers(output)[:, 0]))
            )
            output_exists = output.is_file() and layer_exists
            rows.append(
                {
                    "register": filename,
                    "dataset": record["dataset"],
                    "metadata_complete": complete,
                    "validation_status": record["validation_status"],
                    "output_path": record[path_field],
                    "resolved_file": output_path,
                    "registered_layer": output_layer,
                    "output_exists": output_exists,
                    "expected_sha256": record[hash_field],
                    "actual_sha256": actual_hash or "",
                    "hash_matches": hash_matches,
                    "status": (
                        "passed"
                        if complete and validation_passed and output_exists and hash_matches
                        else "failed"
                    ),
                }
            )
    return pd.DataFrame(rows)


def _spatial_reference_audit(root: Path) -> tuple[pd.DataFrame, bool]:
    rows: list[dict[str, Any]] = []
    raster_paths = [
        "data/interim/normalised/elevation/brisbane_2019_dem_1m_epsg7856.tif",
        "data/interim/normalised/context/latest_public_orthophoto_epsg7856.tif",
        "data/interim/phase5/elevation/dtm_1m.tif",
        "data/interim/phase5/elevation/dsm_1m.tif",
        "data/interim/phase5/elevation/surface_minus_dtm_raw.tif",
        "data/interim/phase5/elevation/height_above_ground.tif",
        "data/interim/phase5/elevation/point_density_1m.tif",
        "data/interim/phase5/elevation/ground_density_1m.tif",
        "data/interim/phase5/elevation/ground_residual_1m.tif",
    ]
    laz_paths = [
        "data/interim/normalised/elevation/brisbane_2019_classified_ahd_epsg7856.laz",
        "data/interim/phase5/pointcloud/uq_pilot_cropped_full.laz",
        "data/interim/phase5/pointcloud/uq_pilot_analysis_filtered.laz",
        "data/interim/phase5/pointcloud/uq_pilot_display.laz",
    ]
    gpkg_paths = [
        "data/interim/normalised/vectors/phase4_vectors_epsg7856.gpkg",
        "data/processed/lod1/lod1_buildings.gpkg",
        "data/processed/lod2/lod2_buildings.gpkg",
        "data/processed/utilities/uq_pilot_public_utilities.gpkg",
    ]
    for relative_path in raster_paths:
        path = root / relative_path
        epsg = None
        if path.is_file():
            with rasterio.open(path) as source:
                epsg = source.crs.to_epsg() if source.crs else None
        rows.append(
            {
                "dataset": relative_path,
                "component": "raster",
                "layer": "",
                "observed_epsg": epsg,
                "expected_epsg": TARGET_EPSG,
                "status": "passed" if epsg == TARGET_EPSG else "failed",
            }
        )
    for relative_path in laz_paths:
        path = root / relative_path
        epsg = None
        if path.is_file():
            with laspy.open(path) as source:
                parsed = source.header.parse_crs()
                epsg = parsed.to_epsg() if parsed else None
        rows.append(
            {
                "dataset": relative_path,
                "component": "point cloud",
                "layer": "",
                "observed_epsg": epsg,
                "expected_epsg": TARGET_EPSG,
                "status": "passed" if epsg == TARGET_EPSG else "failed",
            }
        )
    for relative_path in gpkg_paths:
        path = root / relative_path
        if not path.is_file():
            rows.append(
                {
                    "dataset": relative_path,
                    "component": "vector",
                    "layer": "",
                    "observed_epsg": None,
                    "expected_epsg": TARGET_EPSG,
                    "status": "failed",
                }
            )
            continue
        for layer_name in pyogrio.list_layers(path)[:, 0]:
            info = pyogrio.read_info(path, layer=str(layer_name))
            crs_value = info.get("crs")
            epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
            rows.append(
                {
                    "dataset": relative_path,
                    "component": "vector",
                    "layer": str(layer_name),
                    "observed_epsg": epsg,
                    "expected_epsg": TARGET_EPSG,
                    "status": "passed" if epsg == TARGET_EPSG else "failed",
                }
            )

    origin_files = (
        root / "data/interim/normalised/local_origin.json",
        root / "data/processed/lod1/local_origin.json",
        root / "data/processed/lod2/local_origin.json",
    )
    origins = []
    for path in origin_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        origin = payload["origin"]
        origins.append(
            (float(origin["easting_m"]), float(origin["northing_m"]), float(origin["elevation_m"]))
        )
    phase9 = json.loads((root / PHASE_REPORTS[9]).read_text(encoding="utf-8"))
    origins.append(tuple(float(value) for value in phase9["local_origin"]))
    expected_origin = tuple(float(value) for value in LOCAL_ORIGIN)
    origins_agree = all(origin == expected_origin for origin in origins)
    return pd.DataFrame(rows), origins_agree


def _confidence_and_utility_audit(root: Path) -> dict[str, Any]:
    lod1 = gpd.read_file(root / "data/processed/lod1/lod1_buildings.gpkg", layer="lod1_buildings")
    lod2 = gpd.read_file(root / "data/processed/lod2/lod2_buildings.gpkg", layer="building_status")
    utility_path = root / "data/processed/utilities/uq_pilot_public_utilities.gpkg"
    utility_frames = [
        gpd.read_file(utility_path, layer=layer) for layer in ("utility_lines", "utility_nodes")
    ]
    utilities = pd.concat(utility_frames, ignore_index=True)
    confidence_values = {"high", "medium", "low"}
    building_confidence_complete = bool(
        lod1["confidence"].isin(confidence_values).all()
        and lod2["confidence"].isin(confidence_values).all()
        and lod2["lod2_status"].astype(str).str.strip().ne("").all()
        and lod2["output_lod"].astype(str).str.strip().ne("").all()
    )
    utility_confidence_complete = bool(
        utilities["confidence"].isin(confidence_values).all()
        and utilities["confidence_xy"].astype(str).str.strip().ne("").all()
        and utilities["confidence_z"].astype(str).str.strip().ne("").all()
        and utilities["sensitivity"].astype(str).str.strip().ne("").all()
    )
    utility_depth_unknown = bool(
        utilities["depth_m"].isna().all()
        and utilities["invert_z_ahd"].isna().all()
        and utilities["crown_z_ahd"].isna().all()
        and (utilities["vertical_class"] == "unknown_depth").all()
        and not utilities.geometry.has_z.any()
    )
    return {
        "phase6_building_records": len(lod1),
        "phase7_building_records": len(lod2),
        "utility_records": len(utilities),
        "building_confidence_complete": building_confidence_complete,
        "utility_confidence_complete": utility_confidence_complete,
        "utility_depth_unknown_and_geometry_2d": utility_depth_unknown,
        "phase7_status_counts": {
            str(key): int(value) for key, value in lod2["lod2_status"].value_counts().items()
        },
        "utility_confidence_counts": {
            str(key): int(value) for key, value in utilities["confidence"].value_counts().items()
        },
    }


def _figure_audit(root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted((root / "reports/figures").glob("phase*.png")):
        error = ""
        width = height = 0
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
        except Exception as exc:  # report corrupt products without stopping the audit
            error = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "figure": _relative(path, root),
                "bytes": path.stat().st_size,
                "width": width,
                "height": height,
                "valid_image": not error and width >= 600 and height >= 400,
                "error": error,
            }
        )
    return pd.DataFrame(rows)


def _software_inventory(environment: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "component": "python",
            "version": environment["python"]["version"],
            "available": True,
            "detail": environment["python"]["executable"],
        }
    ]
    rows.extend(
        {
            "component": name,
            "version": details["version"],
            "available": details["available"],
            "detail": details["error"] or "",
        }
        for name, details in environment["packages"].items()
    )
    rows.extend(
        {
            "component": f"command:{name}",
            "version": "",
            "available": bool(path),
            "detail": path or "",
        }
        for name, path in environment["commands"].items()
    )
    return pd.DataFrame(rows)


def _run_quality_command(root: Path, name: str, command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    log_path = root / f"reports/tables/phase10_{name}.txt"
    log_path.write_text(output + "\n", encoding="utf-8")
    return {
        "gate": name,
        "command": " ".join(command),
        "return_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "status": "passed" if result.returncode == 0 else "failed",
        "log": _relative(log_path, root),
        "last_output_line": output.splitlines()[-1] if output else "",
    }


def _run_quality_gates(root: Path) -> pd.DataFrame:
    rows = [
        _run_quality_command(root, "ruff", [sys.executable, "-m", "ruff", "check", "."]),
        _run_quality_command(root, "pytest", [sys.executable, "-m", "pytest", "-q"]),
    ]
    return pd.DataFrame(rows)


def _load_quality_gates(root: Path) -> pd.DataFrame:
    path = root / "reports/tables/phase10_quality_gates.csv"
    if path.is_file():
        return pd.read_csv(path, dtype={"return_code": int})
    return pd.DataFrame(
        [
            {"gate": "ruff", "status": "not run", "return_code": -1},
            {"gate": "pytest", "status": "not run", "return_code": -1},
        ]
    )


def _requirements_matrix(checks: dict[str, bool]) -> pd.DataFrame:
    rows = [
        (
            "R1",
            "Every workflow notebook executes in phase order from a fresh kernel.",
            "phase10_notebook_execution.csv",
            checks["all_notebooks_passed_in_fresh_kernels"],
        ),
        (
            "R2",
            "Derived core outputs can be replayed without changing validated bytes.",
            "phase10_output_hash_audit.csv and cache-reuse flags",
            checks["manifest_outputs_unchanged_by_replay"]
            and checks["replayable_phases_used_validated_cache"],
        ),
        (
            "R3",
            "Transformations and manual-correction policy are documented.",
            "Phase documents and data/manual/README.md",
            checks["required_method_documents_exist"]
            and checks["manual_correction_state_is_documented"],
        ),
        (
            "R4",
            "Datasets record source, date, licence, CRS and vertical datum.",
            "dataset_register.csv and model registers",
            checks["acquired_source_metadata_is_complete"]
            and checks["derived_register_metadata_is_complete"],
        ),
        (
            "R5",
            "Every building and public utility has explicit confidence/status fields.",
            "LoD1, mixed-LoD and utility GeoPackages",
            checks["building_confidence_is_complete"] and checks["utility_confidence_is_complete"],
        ),
        (
            "R6",
            "Large point-cloud processing uses streaming and bounded display samples.",
            "PDAL --stream, laspy chunk_iterator and Phase 9 30,000-point preview",
            checks["large_point_cloud_processing_is_streamed"]
            and checks["interactive_point_cloud_is_bounded"],
        ),
        (
            "R7",
            "Fixed diagnostic images are valid and prior alignment gates pass.",
            "phase10_figure_inventory.csv and Phase 2-9 checks",
            checks["fixed_diagnostic_figures_are_valid"]
            and checks["all_prior_phase_checks_passed"],
        ),
        (
            "R8",
            "Unknown-depth utilities are never presented as survey-accurate 3D assets.",
            "2D utility geometry, null depth fields and labelled Phase 9 display drape",
            checks["utilities_remain_2d_with_unknown_depth"]
            and checks["utility_limitations_are_prominent"],
        ),
    ]
    return pd.DataFrame(rows, columns=["requirement_id", "requirement", "evidence", "passed"])


def _validation_dashboard(
    phase_results: pd.DataFrame,
    notebooks: pd.DataFrame,
    requirements: pd.DataFrame,
    output_path: Path,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    phases = phase_results["phase"].astype(str)
    axes[0, 0].barh(phases, phase_results["checks_total"], color="#D6E4F0")
    axes[0, 0].barh(phases, phase_results["checks_passed"], color="#2A9D8F")
    axes[0, 0].invert_yaxis()
    axes[0, 0].set_title("Prior phase decision-gate checks")
    axes[0, 0].set_xlabel("Checks")
    axes[0, 0].legend(
        handles=[
            Patch(color="#2A9D8F", label="passed"),
            Patch(color="#D6E4F0", label="total"),
        ],
        loc="lower right",
    )

    notebook_colours = [
        "#2A9D8F" if value == "passed" else "#D1495B" for value in notebooks["status"]
    ]
    axes[0, 1].barh(
        notebooks["phase"].astype(str), notebooks["duration_seconds"], color=notebook_colours
    )
    axes[0, 1].invert_yaxis()
    axes[0, 1].set_title("Fresh-kernel notebook execution")
    axes[0, 1].set_xlabel("Seconds")

    axes[1, 0].axis("off")
    axes[1, 0].set_title("Phase 10 requirements", loc="left")
    for index, row in enumerate(requirements.itertuples()):
        symbol = "PASS" if row.passed else "FAIL"
        colour = "#1B7F5A" if row.passed else "#B42318"
        axes[1, 0].text(
            0.01,
            0.94 - index * 0.105,
            f"{symbol}  {row.requirement_id}: {row.requirement}",
            transform=axes[1, 0].transAxes,
            fontsize=9,
            color=colour,
            va="top",
            wrap=True,
        )

    axes[1, 1].axis("off")
    checks_passed = int(phase_results["checks_passed"].sum())
    checks_total = int(phase_results["checks_total"].sum())
    summary_lines = [
        "PUBLIC-DATA PILOT",
        f"Prior checks: {checks_passed}/{checks_total}",
        f"Fresh-kernel notebooks: {(notebooks['status'] == 'passed').sum()}/{len(notebooks)}",
        f"Requirements: {requirements['passed'].sum()}/{len(requirements)}",
        "Authoritative horizontal CRS: EPSG:7856",
        "Terrain/buildings: metres AHD",
        "Utilities: physical depth unknown",
        "Scope: 500 m x 500 m UQ St Lucia pilot",
    ]
    axes[1, 1].text(
        0.04,
        0.92,
        "\n".join(summary_lines),
        transform=axes[1, 1].transAxes,
        fontsize=13,
        linespacing=1.55,
        va="top",
        color="#243447",
    )
    axes[1, 1].text(
        0.04,
        0.16,
        "NOT SURVEY-GRADE OR EXCAVATION-SAFE",
        transform=axes[1, 1].transAxes,
        fontsize=13,
        weight="bold",
        color="#B42318",
    )
    figure.suptitle("UQGEMs GeoRabble - Phase 10 reproducibility validation", fontsize=18)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _write_reproducibility_register(
    root: Path, summary_path: Path, summary: dict[str, Any]
) -> Path:
    output = root / "data/reproducibility_register.csv"
    row = {
        "dataset": "Phase 10 non-destructive reproducibility audit",
        "source_paths": ";".join(PHASE_REPORTS.values()),
        "output_path": _relative(summary_path, root),
        "output_sha256": sha256(summary_path),
        "notebook_count": summary["notebook_execution"]["passed"],
        "prior_check_count": summary["prior_phase_validation"]["checks_passed"],
        "validation_status": summary["status"],
        "notes": (
            "Local validation only; preserved raw/derived data were not deleted. "
            "Utilities remain unknown-depth public context."
        ),
    }
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    return output


def _audit(
    root: Path,
    notebook_rows: list[dict[str, Any]],
    before_replay: dict[str, str | None],
    quality_gates: pd.DataFrame,
) -> dict[str, Any]:
    table_root = root / "reports/tables"
    figure_path = root / "reports/figures/phase10_validation_dashboard.png"
    outputs = {
        "summary": table_root / "phase10_reproducibility.json",
        "notebooks": table_root / "phase10_notebook_execution.csv",
        "phases": table_root / "phase10_phase_results.csv",
        "source_register": table_root / "phase10_source_register_audit.csv",
        "model_registers": table_root / "phase10_model_register_audit.csv",
        "manifests": table_root / "phase10_manifest_audit.csv",
        "hashes": table_root / "phase10_output_hash_audit.csv",
        "spatial_references": table_root / "phase10_spatial_reference_audit.csv",
        "figures": table_root / "phase10_figure_inventory.csv",
        "requirements": table_root / "phase10_requirements_matrix.csv",
        "software": table_root / "phase10_software_inventory.csv",
        "quality_gates": table_root / "phase10_quality_gates.csv",
    }
    table_root.mkdir(parents=True, exist_ok=True)

    notebooks = pd.DataFrame(notebook_rows).sort_values("phase").reset_index(drop=True)
    phase_results = _phase_results(root)
    manifests, hashes = _hash_audit(root, before_replay)
    hash_cache: dict[Path, str] = {}
    source_register = _dataset_register_audit(root, hash_cache)
    model_registers = _model_register_audit(root, hash_cache)
    spatial_references, origins_agree = _spatial_reference_audit(root)
    confidence = _confidence_and_utility_audit(root)
    figures = _figure_audit(root)
    environment = collect_environment()
    software = _software_inventory(environment)

    expected_specs = PRIOR_NOTEBOOKS + (
        (VALIDATION_NOTEBOOK,) if any(row["phase"] == 10 for row in notebook_rows) else ()
    )
    expected_sources = {f"notebooks/{spec.filename}" for spec in expected_specs}
    actual_sources = set(notebooks["source_notebook"]) if not notebooks.empty else set()
    phase9_html = (root / "reports/scenes/uq_pilot_integrated.html").read_text(
        encoding="utf-8", errors="ignore"
    )
    phase9_summary = json.loads((root / PHASE_REPORTS[9]).read_text(encoding="utf-8"))
    manual_files = [
        path
        for path in (root / "data/manual").rglob("*")
        if path.is_file() and path.name != "README.md"
    ]
    preparation_source = (root / "src/uqgems/preparation.py").read_text(encoding="utf-8")
    acquired_sources = source_register.loc[~source_register["deferred_source"]]

    checks = {
        "environment_has_all_required_modules_and_commands": (
            not missing_modules(environment)
            and not missing_commands(environment)
            and environment["conda"]["default_env"] == KERNEL_NAME
        ),
        "all_prior_phase_reports_exist": bool(phase_results["report_exists"].all()),
        "all_prior_phase_reports_match_their_phase": bool(
            phase_results["report_phase_matches"].all()
        ),
        "all_prior_phase_statuses_passed": bool((phase_results["status"] == "passed").all()),
        "all_prior_phase_checks_passed": bool(phase_results["all_checks_passed"].all()),
        "all_declared_phase_outputs_exist": bool(phase_results["all_declared_outputs_exist"].all()),
        "all_notebook_sources_exist": all((root / path).is_file() for path in expected_sources),
        "all_notebooks_passed_in_fresh_kernels": bool(
            len(notebooks) == len(expected_specs)
            and actual_sources == expected_sources
            and (notebooks["status"] == "passed").all()
            and notebooks["fresh_kernel_session"].nunique() == len(notebooks)
        ),
        "every_notebook_code_cell_was_executed": bool(
            (notebooks["code_cells"] == notebooks["executed_code_cells"]).all()
            and (notebooks["error_outputs"] == 0).all()
        ),
        "replayable_phases_used_validated_cache": bool(
            phase_results.loc[phase_results.phase.between(4, 9), "cache_reused"]
            .astype(str)
            .str.lower()
            .eq("true")
            .all()
        ),
        "all_processing_manifests_are_complete": bool(
            (manifests["status"] == "passed").all()
            and manifests["configuration_signature_present"].all()
            and manifests["signature_inputs_present"].all()
        ),
        "all_manifest_output_hashes_match": bool(hashes["matches_manifest"].all()),
        "manifest_outputs_unchanged_by_replay": bool(
            hashes["unchanged_by_replay"].astype(str).str.lower().eq("true").all()
        ),
        "acquired_source_metadata_is_complete": bool(source_register["metadata_complete"].all()),
        "all_acquired_source_paths_exist": bool(acquired_sources["path_exists"].all()),
        "all_acquired_source_hashes_match": bool(acquired_sources["hash_matches"].all()),
        "deferred_uq_source_is_explicit": bool(
            (source_register["status"] == "documented deferred source").sum() == 1
        ),
        "derived_register_metadata_is_complete": bool(model_registers["metadata_complete"].all()),
        "derived_register_outputs_and_hashes_match": bool(
            model_registers["output_exists"].all()
            and model_registers["hash_matches"].all()
            and (model_registers["status"] == "passed").all()
        ),
        "all_authoritative_spatial_outputs_use_epsg_7856": bool(
            (spatial_references["status"] == "passed").all()
        ),
        "all_local_rendering_origins_agree": origins_agree,
        "building_confidence_is_complete": confidence["building_confidence_complete"],
        "utility_confidence_is_complete": confidence["utility_confidence_complete"],
        "utilities_remain_2d_with_unknown_depth": confidence[
            "utility_depth_unknown_and_geometry_2d"
        ],
        "large_point_cloud_processing_is_streamed": (
            '"--stream"' in preparation_source and "chunk_iterator" in preparation_source
        ),
        "interactive_point_cloud_is_bounded": (
            phase9_summary["scene_contents"]["point_cloud"].startswith("deterministic 30,000-point")
        ),
        "fixed_diagnostic_figures_are_valid": bool(
            len(figures) >= 30 and figures["valid_image"].all()
        ),
        "utility_limitations_are_prominent": all(
            phrase in phase9_html.lower()
            for phrase in ("physical depth is unknown", "display drape only")
        ),
        "required_method_documents_exist": all(
            (root / relative_path).is_file() for relative_path in REQUIRED_DOCUMENTS
        ),
        "manual_correction_state_is_documented": bool(
            not manual_files and (root / "data/manual/README.md").is_file()
        ),
        "ruff_quality_gate_passed": bool(
            (quality_gates.loc[quality_gates.gate == "ruff", "status"] == "passed").all()
        ),
        "pytest_quality_gate_passed": bool(
            (quality_gates.loc[quality_gates.gate == "pytest", "status"] == "passed").all()
        ),
    }

    requirements = _requirements_matrix(checks)
    _validation_dashboard(phase_results, notebooks, requirements, figure_path)
    checks["validation_dashboard_is_nonempty"] = figure_path.stat().st_size > 25_000

    frames = {
        outputs["notebooks"]: notebooks,
        outputs["phases"]: phase_results,
        outputs["source_register"]: source_register,
        outputs["model_registers"]: model_registers,
        outputs["manifests"]: manifests,
        outputs["hashes"]: hashes,
        outputs["spatial_references"]: spatial_references,
        outputs["figures"]: figures,
        outputs["requirements"]: requirements,
        outputs["software"]: software,
        outputs["quality_gates"]: quality_gates,
    }
    for path, frame in frames.items():
        frame.to_csv(path, index=False)

    checks_passed = sum(value is True for value in checks.values())
    checks_total = len(checks)
    summary = {
        "phase": 10,
        "status": "passed" if checks_passed == checks_total else "failed",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "audit_mode": "non-destructive local replay from preserved raw data and caches",
        "scope": "500 m by 500 m UQ St Lucia public-data pilot",
        "prior_phase_validation": {
            "phases": [2, 3, 4, 5, 6, 7, 8, 9],
            "checks_passed": int(phase_results["checks_passed"].sum()),
            "checks_total": int(phase_results["checks_total"].sum()),
        },
        "notebook_execution": {
            "kernel": KERNEL_NAME,
            "fresh_kernel_per_notebook": True,
            "expected": len(expected_specs),
            "passed": int((notebooks["status"] == "passed").sum()),
            "total_duration_seconds": round(float(notebooks["duration_seconds"].sum()), 3),
        },
        "source_provenance": {
            "registered_sources": len(source_register),
            "acquired_sources": int((~source_register["deferred_source"]).sum()),
            "documented_deferred_sources": int(source_register["deferred_source"].sum()),
            "matching_acquired_source_hashes": int(acquired_sources["hash_matches"].sum()),
        },
        "derived_integrity": {
            "processing_manifests": len(manifests),
            "manifest_outputs": len(hashes),
            "matching_output_hashes": int(hashes["matches_manifest"].sum()),
            "unchanged_by_replay": int(
                hashes["unchanged_by_replay"].astype(str).str.lower().eq("true").sum()
            ),
            "model_register_records": len(model_registers),
        },
        "spatial_reference": {
            "authoritative_horizontal_crs": f"GDA2020 / MGA zone 56 (EPSG:{TARGET_EPSG})",
            "terrain_and_buildings_vertical_reference": "AHD",
            "utility_vertical_reference": "unknown; authoritative geometry remains 2D",
            "audited_components": len(spatial_references),
            "local_origin": [float(value) for value in LOCAL_ORIGIN],
        },
        "confidence_and_safety": confidence,
        "manual_corrections": {
            "applied_correction_files": len(manual_files),
            "status": "none applied; future corrections require author/date/source/reason",
        },
        "quality_gates": quality_gates.to_dict(orient="records"),
        "checks": checks,
        "decision_gate": (
            "The public-data pilot is reproducible from the preserved local source snapshots "
            "and validated caches. It is ready for demonstration and for supporting a UQ data "
            "request. It is not a campus-wide, survey-grade or excavation-safe utility model."
        ),
        "limitations": [
            "This was a non-destructive replay; derived directories were not deleted first.",
            (
                "External services were not independently re-downloaded, so current "
                "availability was not tested."
            ),
            (
                "The audit establishes reproducibility from preserved local raw snapshots, "
                "not from the live web."
            ),
            (
                "Only three public utility records intersect the pilot and all have unknown "
                "physical depth."
            ),
            "Urban Utilities redistribution terms remain to be confirmed before publication.",
            "No manual correction datasets have been applied.",
        ],
        "outputs": {
            "summary": _relative(outputs["summary"], root),
            "dashboard": _relative(figure_path, root),
            "tables": {
                name: _relative(path, root) for name, path in outputs.items() if name != "summary"
            },
            "executed_notebooks": "reports/tables/phase10_notebooks/",
            "manifest": "data/processed/validation/phase10_manifest.json",
            "register": "data/reproducibility_register.csv",
        },
    }
    _write_json(outputs["summary"], summary)

    manifest_outputs = [*frames, figure_path, outputs["summary"]]
    manifest = {
        "schema_version": PHASE10_SCHEMA_VERSION,
        "audit_mode": summary["audit_mode"],
        "source_notebooks": {row["source_notebook"]: row["source_sha256"] for row in notebook_rows},
        "prior_phase_reports": {
            relative_path: sha256(root / relative_path) for relative_path in PHASE_REPORTS.values()
        },
        "output_sha256": {_relative(path, root): sha256(path) for path in manifest_outputs},
    }
    manifest_path = root / summary["outputs"]["manifest"]
    _write_json(manifest_path, manifest)
    _write_reproducibility_register(root, outputs["summary"], summary)
    return summary


def run_phase10(
    project_root: str | Path,
    *,
    execute_notebooks: bool = True,
    execute_validation_notebook: bool = True,
) -> dict[str, Any]:
    """Run the non-destructive Phase 10 replay and consolidated audit."""
    root = Path(project_root).resolve()
    required_inputs = [root / path for path in (*PHASE_REPORTS.values(), *MANIFEST_PATHS)]
    missing = [str(path) for path in required_inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Phase 10 prerequisites are missing: " + ", ".join(missing))

    _, initial_hashes = _hash_audit(root)
    before_replay = {
        str(row.path): str(row.actual_sha256) or None for row in initial_hashes.itertuples()
    }
    notebook_table = root / "reports/tables/phase10_notebook_execution.csv"
    if execute_notebooks:
        notebook_rows = [execute_notebook(root, spec) for spec in PRIOR_NOTEBOOKS]
        quality_gates = _run_quality_gates(root)
    else:
        notebook_rows = (
            pd.read_csv(notebook_table, dtype=str, keep_default_na=False).to_dict(orient="records")
            if notebook_table.is_file()
            else []
        )
        for row in notebook_rows:
            for key in (
                "phase",
                "code_cells",
                "executed_code_cells",
                "error_outputs",
            ):
                row[key] = int(row[key])
            row["duration_seconds"] = float(row["duration_seconds"])
        quality_gates = _load_quality_gates(root)

    if not execute_notebooks and execute_validation_notebook:
        notebook_rows = [row for row in notebook_rows if row["phase"] != VALIDATION_NOTEBOOK.phase]

    summary = _audit(root, notebook_rows, before_replay, quality_gates)
    if execute_validation_notebook:
        validation_result = execute_notebook(root, VALIDATION_NOTEBOOK)
        notebook_rows = [row for row in notebook_rows if row["phase"] != VALIDATION_NOTEBOOK.phase]
        notebook_rows.append(validation_result)
        summary = _audit(root, notebook_rows, before_replay, quality_gates)

    failed = [name for name, passed in summary["checks"].items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 10 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    summary = run_phase10(root)
    print(f"Phase 10 status: {summary['status']}")
    print(
        "Prior checks: "
        f"{summary['prior_phase_validation']['checks_passed']}/"
        f"{summary['prior_phase_validation']['checks_total']}"
    )
    print(
        "Fresh-kernel notebooks: "
        f"{summary['notebook_execution']['passed']}/"
        f"{summary['notebook_execution']['expected']}"
    )
    print(f"Phase 10 checks: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary: {root / summary['outputs']['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
