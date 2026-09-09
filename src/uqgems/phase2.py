"""Run and validate the complete Phase 2 synthetic workflow."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import rasterio

from uqgems.scene import CAMERAS, SYMBOLIC_UTILITY_RADII_M, export_interactive_html
from uqgems.synthetic import (
    SyntheticDataset,
    authoritative_to_local,
    create_synthetic_dataset,
    dataset_metadata,
    local_to_authoritative,
    terrain_height,
    write_synthetic_gis,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _render_png_isolated(
    output_path: Path, *, camera: str, terrain_opacity: float
) -> Path:
    """Render in a clean process to avoid cross-plotter VTK overlay state on Windows."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uqgems._render_one",
            str(output_path),
            "--camera",
            camera,
            "--terrain-opacity",
            str(terrain_opacity),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return output_path


def validate_phase2_outputs(
    dataset: SyntheticDataset, outputs: dict[str, Path]
) -> dict[str, bool]:
    """Validate coordinate metadata, 3D geometry and generated scene files."""
    checks: dict[str, bool] = {}
    checks["all_outputs_exist"] = all(path.is_file() for path in outputs.values())

    with rasterio.open(outputs["terrain"]) as source:
        checks["terrain_crs_is_epsg_7856"] = source.crs.to_epsg() == 7856
        checks["terrain_transform_matches"] = source.transform.almost_equals(dataset.transform)
        checks["terrain_is_marked_synthetic"] = source.tags().get("SYNTHETIC") == "TRUE"

    layer_names = {str(row[0]) for row in pyogrio.list_layers(outputs["geopackage"])}
    expected_layers = {"buildings", "utilities", "utility_nodes"}
    checks["geopackage_has_expected_layers"] = layer_names == expected_layers
    vector_layers = {
        name: pyogrio.read_dataframe(outputs["geopackage"], layer=name)
        for name in expected_layers
    }
    checks["vector_crs_is_epsg_7856"] = all(
        frame.crs is not None and frame.crs.to_epsg() == 7856 for frame in vector_layers.values()
    )
    checks["utility_geometries_retain_z"] = bool(
        vector_layers["utilities"].geometry.has_z.all()
        and vector_layers["utility_nodes"].geometry.has_z.all()
    )

    sample_local = np.array([[0.0, 0.0, 10.0], [250.0, 250.0, 30.0], [500.0, 500.0, 40.0]])
    round_trip = authoritative_to_local(
        local_to_authoritative(sample_local, dataset.local_origin), dataset.local_origin
    )
    checks["local_authoritative_round_trip"] = bool(np.allclose(round_trip, sample_local))

    below_ground = []
    for geometry in dataset.utilities.geometry:
        coordinates = np.asarray(geometry.coords)
        local = authoritative_to_local(coordinates, dataset.local_origin)
        surface_z = terrain_height(local[:, 0], local[:, 1])
        below_ground.extend(coordinates[:, 2] < surface_z)
    checks["utilities_are_below_terrain"] = bool(all(below_ground))
    checks["flat_and_pitched_roofs_present"] = set(dataset.buildings["roof_type"]) == {
        "flat",
        "pitched",
    }
    checks["lod1_and_lod2_present"] = set(dataset.buildings["lod"]) == {"LoD1", "LoD2"}

    png_paths = [path for key, path in outputs.items() if key.endswith("_png")]
    checks["png_outputs_are_nonempty"] = bool(
        len(png_paths) == 3 and all(path.stat().st_size > 10_000 for path in png_paths)
    )
    checks["interactive_html_is_nonempty"] = outputs["interactive_html"].stat().st_size > 50_000
    return checks


def run_phase2(project_root: str | Path) -> dict[str, Any]:
    """Generate, export, render and validate the complete synthetic workflow."""
    root = Path(project_root).resolve()
    dataset = create_synthetic_dataset()

    outputs = write_synthetic_gis(dataset, root / "data" / "processed" / "synthetic")
    outputs.update(
        {
            "plan_png": _render_png_isolated(
                root / "reports" / "figures" / "phase2_synthetic_plan.png",
                camera="plan",
                terrain_opacity=0.82,
            ),
            "oblique_png": _render_png_isolated(
                root / "reports" / "figures" / "phase2_synthetic_oblique.png",
                camera="oblique",
                terrain_opacity=0.72,
            ),
            "underground_png": _render_png_isolated(
                root / "reports" / "figures" / "phase2_synthetic_underground.png",
                camera="underground",
                terrain_opacity=0.20,
            ),
            "interactive_html": export_interactive_html(
                dataset,
                root / "reports" / "scenes" / "phase2_synthetic_interactive.html",
            ),
        }
    )

    checks = validate_phase2_outputs(dataset, outputs)
    summary_path = root / "reports" / "tables" / "phase2_summary.json"
    serialised_outputs = {
        name: str(path.relative_to(root)).replace("\\", "/") for name, path in outputs.items()
    }
    summary = {
        "phase": 2,
        "status": "passed" if all(checks.values()) else "failed",
        "warning": "Entirely fictional test geometry; do not use as campus asset information.",
        "dataset": dataset_metadata(dataset),
        "fixed_cameras": CAMERAS,
        "visualisation": {
            "utility_tube_radii_m": SYMBOLIC_UTILITY_RADII_M,
            "utility_widths_are_symbolic": True,
            "authoritative_coordinates_used_for_storage": True,
            "local_coordinates_used_for_rendering": True,
        },
        "outputs": serialised_outputs,
        "sha256": {name: _sha256(path) for name, path in outputs.items()},
        "checks": checks,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["summary_report"] = str(summary_path.relative_to(root)).replace("\\", "/")

    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise RuntimeError(f"Phase 2 validation failed: {', '.join(failed_checks)}")
    return summary


def main() -> int:
    """Run Phase 2 using the repository containing this installed package."""
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase2(project_root)
    print(f"Phase 2 status: {summary['status']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
