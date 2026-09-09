"""Collect reproducible diagnostics for the UQGEMs Python environment."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODULES: dict[str, str] = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "scikit-learn": "sklearn",
    "matplotlib": "matplotlib",
    "plotly": "plotly",
    "geopandas": "geopandas",
    "shapely": "shapely",
    "pyproj": "pyproj",
    "pyogrio": "pyogrio",
    "rasterio": "rasterio",
    "rioxarray": "rioxarray",
    "xarray": "xarray",
    "gdal": "osgeo.gdal",
    "pdal": "pdal",
    "laspy": "laspy",
    "lazrs": "lazrs",
    "pyarrow": "pyarrow",
    "pyvista": "pyvista",
    "vtk": "vtk",
    "trame": "trame",
    "lonboard": "lonboard",
    "trimesh": "trimesh",
    "jupyterlab": "jupyterlab",
}

COMMANDS = ("python", "jupyter", "gdalinfo", "ogrinfo", "pdal")


def _module_details(distribution: str, module_name: str) -> dict[str, Any]:
    """Return availability, version and import details for one dependency."""
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # diagnostics must report all import failures
        return {
            "available": False,
            "version": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = getattr(module, "__version__", "unknown")

    return {"available": True, "version": str(version), "error": None}


def collect_environment() -> dict[str, Any]:
    """Collect interpreter, dependency and command-line availability."""
    packages = {
        distribution: _module_details(distribution, module_name)
        for distribution, module_name in MODULES.items()
    }
    commands = {command: shutil.which(command) for command in COMMANDS}

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "conda": {
            "default_env": os.environ.get("CONDA_DEFAULT_ENV"),
            "prefix": os.environ.get("CONDA_PREFIX"),
        },
        "packages": packages,
        "commands": commands,
    }


def missing_modules(report: dict[str, Any]) -> list[str]:
    """List required modules that failed to import."""
    return [name for name, details in report["packages"].items() if not details["available"]]


def missing_commands(report: dict[str, Any]) -> list[str]:
    """List required command-line programs that are not on PATH."""
    return [name for name, path in report["commands"].items() if path is None]


def write_report(report: dict[str, Any], path: str | Path) -> Path:
    """Write an environment report as formatted JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    """Write the standard report and return a failing status for missing modules."""
    project_root = Path(__file__).resolve().parents[2]
    report = collect_environment()
    output_path = write_report(report, project_root / "reports/tables/environment_report.json")
    modules_missing = missing_modules(report)
    commands_missing = missing_commands(report)
    print(f"Environment report: {output_path}")
    print(f"Python: {report['python']['version']} ({report['python']['executable']})")
    print(f"Conda environment: {report['conda']['default_env']}")
    if modules_missing:
        print(f"Missing or failed imports: {', '.join(modules_missing)}")
    if commands_missing:
        print(f"Missing commands: {', '.join(commands_missing)}")
    if modules_missing or commands_missing:
        return 1
    print("All required Python modules and commands are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
