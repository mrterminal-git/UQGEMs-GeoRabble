"""Acquire, inventory and validate the public Phase 3 pilot inputs."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import laspy
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.patches import Rectangle
from rasterio.warp import transform_bounds
from shapely.geometry import box

from uqgems.acquisition import (
    BUILDINGS_SERVICE,
    IMAGERY_SERVICE,
    PILOT_AREA,
    UQ_CAMPUS_MAP_URL,
    acquire_public_context,
    archive_inventory,
    extract_selected_elvis_2019,
    sha256,
)

DATA_REGISTER_FIELDS = (
    "dataset",
    "source",
    "local_path",
    "download_date",
    "capture_date",
    "licence",
    "horizontal_crs",
    "vertical_datum",
    "resolution",
    "stated_accuracy",
    "processing_status",
    "sha256",
    "notes",
)


def bounds_cover(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float = 0.01,
) -> bool:
    """Return whether one bounding box contains another within a tolerance."""
    return bool(
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _inspect_raster(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as source:
        data = source.read(1, masked=True)
        valid = data.compressed()
        return {
            "path": str(path),
            "driver": source.driver,
            "crs": source.crs.to_string() if source.crs else None,
            "epsg": source.crs.to_epsg() if source.crs else None,
            "bounds": list(source.bounds),
            "width": source.width,
            "height": source.height,
            "band_count": source.count,
            "resolution": list(source.res),
            "nodata": source.nodata,
            "valid_cells": int(valid.size),
            "minimum": float(valid.min()) if valid.size else None,
            "maximum": float(valid.max()) if valid.size else None,
            "sha256": sha256(path),
        }


def _inspect_laz(path: Path) -> dict[str, Any]:
    with laspy.open(path) as source:
        header = source.header
        parsed_crs = header.parse_crs()
        return {
            "path": str(path),
            "las_version": str(header.version),
            "point_format": int(header.point_format.id),
            "point_count": int(header.point_count),
            "crs": parsed_crs.to_string() if parsed_crs else None,
            "epsg": parsed_crs.to_epsg() if parsed_crs else None,
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


def _inspect_geojson(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "error" in payload:
        raise RuntimeError(f"ArcGIS returned an error for {path.name}: {payload['error']}")
    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs(PILOT_AREA.epsg)
    return {
        "path": str(path),
        "features": int(len(frame)),
        "crs": frame.crs.to_string(),
        "epsg": frame.crs.to_epsg(),
        "bounds": list(frame.total_bounds) if len(frame) else None,
        "sha256": sha256(path),
    }


def _inspect_osm(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    building_ways = 0
    building_relations = 0
    for element in root.findall("way"):
        if any(tag.get("k") == "building" for tag in element.findall("tag")):
            building_ways += 1
    for element in root.findall("relation"):
        if any(tag.get("k") == "building" for tag in element.findall("tag")):
            building_relations += 1
    return {
        "path": str(path),
        "nodes": len(root.findall("node")),
        "ways": len(root.findall("way")),
        "relations": len(root.findall("relation")),
        "building_ways": building_ways,
        "building_relations": building_relations,
        "sha256": sha256(path),
    }


def _read_imagery_catalog(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "error" in payload:
        raise RuntimeError(f"Imagery catalogue query failed: {payload['error']}")
    features = payload.get("features", [])
    return {
        "item_count": len(features),
        "items": [feature.get("attributes", {}) for feature in features],
    }


def _create_coverage_figure(
    imagery_path: Path,
    building_path: Path,
    output_path: Path,
) -> Path:
    buildings = gpd.read_file(building_path)
    if buildings.crs is None:
        buildings = buildings.set_crs(PILOT_AREA.epsg)
    buildings = buildings.to_crs(PILOT_AREA.epsg)
    aoi = box(*PILOT_AREA.projected_bounds)
    buildings = buildings[buildings.intersects(aoi)]

    with rasterio.open(imagery_path) as source:
        image = np.moveaxis(source.read([1, 2, 3]), 0, -1)
        image_bounds = source.bounds

    figure, axis = plt.subplots(figsize=(9, 9), constrained_layout=True)
    axis.imshow(
        image,
        extent=(image_bounds.left, image_bounds.right, image_bounds.bottom, image_bounds.top),
        origin="upper",
    )
    buildings.boundary.plot(ax=axis, color="#00ffff", linewidth=1.0, label="QLD outlines")
    west, south, east, north = PILOT_AREA.projected_bounds
    axis.add_patch(
        Rectangle(
            (west, south),
            east - west,
            north - south,
            fill=False,
            edgecolor="#ffcc00",
            linewidth=2.0,
            label="500 m pilot AOI",
        )
    )
    axis.set(xlabel="Easting (m)", ylabel="Northing (m)", title="Phase 3 source alignment check")
    axis.set_aspect("equal")
    axis.legend(loc="lower right")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)
    return output_path


def _register_rows(
    root: Path,
    archives: list[dict[str, Any]],
    selected: dict[str, Path],
    public: dict[str, Path],
    imagery_catalog: dict[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for archive in archives:
        rows.append(
            {
                "dataset": f"ELVIS order archive: {archive['filename']}",
                "source": "ELVIS / Geoscience Australia elevation data portal",
                "local_path": f"data/raw/elvis/incoming/{archive['filename']}",
                "download_date": str(archive["file_modified_date"]),
                "capture_date": "various; see supplied metadata",
                "licence": "See licence/metadata supplied in archive",
                "horizontal_crs": "various; inspect the CRS stored in each product",
                "vertical_datum": "various; see supplied metadata",
                "resolution": "various",
                "stated_accuracy": "see supplied metadata",
                "processing_status": "immutable original; inventoried",
                "sha256": str(archive["sha256"]),
                "notes": "Original ELVIS delivery retained unchanged.",
            }
        )

    main_archive_date = next(
        str(item["file_modified_date"])
        for item in archives
        if item["filename"] == "DATA_2380922.zip"
    )
    common_elvis = {
        "source": "ELVIS: Brisbane 2019 Project, tile SW_501000_6958000",
        "download_date": main_archive_date,
        "capture_date": "2019-06-11 to 2019-08-16",
        "horizontal_crs": "GDA94 / MGA zone 56 (EPSG:28356), as observed",
        "stated_accuracy": "horizontal 0.8 m and vertical 0.3 m at 95% (project index)",
    }
    rows.extend(
        [
            {
                "dataset": "Brisbane 2019 classified LiDAR",
                **common_elvis,
                "local_path": _relative(selected["laz"], root),
                "licence": "Limited Use Licence / State copyright in supplied LiDAR XML",
                "vertical_datum": "AHD",
                "resolution": "point cloud; density to be assessed in Phase 5",
                "processing_status": "selected and extracted without modification",
                "sha256": sha256(selected["laz"]),
                "notes": (
                    "Primary source for roof analysis. Verify derivative/publication rights "
                    "before sharing data or a public model."
                ),
            },
            {
                "dataset": "Brisbane 2019 1 metre DEM",
                **common_elvis,
                "local_path": _relative(selected["dem"], root),
                "licence": "Creative Commons Attribution 4.0 in supplied DEM XML",
                "vertical_datum": "AHD",
                "resolution": "1 metre",
                "processing_status": "selected and extracted without modification",
                "sha256": sha256(selected["dem"]),
                "notes": "Primary terrain input.",
            },
        ]
    )

    latest_imagery = imagery_catalog["items"][0] if imagery_catalog["items"] else {}
    capture_start = latest_imagery.get("capturestart") or latest_imagery.get("CAPTURESTART")
    if isinstance(capture_start, (int, float)):
        capture_start = datetime.fromtimestamp(capture_start / 1000, tz=UTC).date().isoformat()
    rows.extend(
        [
            {
                "dataset": "Queensland generated building outlines",
                "source": f"{BUILDINGS_SERVICE}/11",
                "local_path": _relative(public["qld_building_outlines"], root),
                "download_date": datetime.fromtimestamp(
                    public["qld_building_outlines"].stat().st_mtime
                ).date().isoformat(),
                "capture_date": "feature-specific source fields",
                "licence": "Creative Commons Attribution 4.0",
                "horizontal_crs": "GDA2020 / MGA zone 56 (EPSG:7856)",
                "vertical_datum": "not applicable",
                "resolution": "vector polygons",
                "stated_accuracy": "feature-specific; not survey grade",
                "processing_status": "raw AOI extract acquired",
                "sha256": sha256(public["qld_building_outlines"]),
                "notes": "Primary public footprint candidate; compare against LiDAR and imagery.",
            },
            {
                "dataset": "Queensland topographic building areas",
                "source": f"{BUILDINGS_SERVICE}/20",
                "local_path": _relative(public["qld_building_areas"], root),
                "download_date": datetime.fromtimestamp(
                    public["qld_building_areas"].stat().st_mtime
                ).date().isoformat(),
                "capture_date": "feature-specific source fields",
                "licence": "Creative Commons Attribution 4.0",
                "horizontal_crs": "GDA2020 / MGA zone 56 (EPSG:7856)",
                "vertical_datum": "not applicable",
                "resolution": "vector polygons",
                "stated_accuracy": "feature-specific; not survey grade",
                "processing_status": "raw AOI extract acquired",
                "sha256": sha256(public["qld_building_areas"]),
                "notes": "Secondary public footprint/name candidate.",
            },
            {
                "dataset": "OpenStreetMap pilot extract",
                "source": "https://api.openstreetmap.org/api/0.6/map",
                "local_path": _relative(public["osm_extract"], root),
                "download_date": datetime.fromtimestamp(
                    public["osm_extract"].stat().st_mtime
                ).date().isoformat(),
                "capture_date": "continuously updated; element timestamps in extract",
                "licence": "Open Data Commons Open Database License (ODbL) 1.0",
                "horizontal_crs": "WGS 84 (EPSG:4326)",
                "vertical_datum": "not applicable",
                "resolution": "vector features",
                "stated_accuracy": "community mapped; variable",
                "processing_status": "raw AOI extract acquired",
                "sha256": sha256(public["osm_extract"]),
                "notes": "Prototype footprint/name source; attribution required.",
            },
            {
                "dataset": "Queensland latest public orthophoto basemap extract",
                "source": IMAGERY_SERVICE,
                "local_path": _relative(public["qld_imagery"], root),
                "download_date": datetime.fromtimestamp(
                    public["qld_imagery"].stat().st_mtime
                ).date().isoformat(),
                "capture_date": str(capture_start or "see catalog_query.json"),
                "licence": "Creative Commons Attribution 4.0",
                "horizontal_crs": "GDA2020 / MGA zone 56 (EPSG:7856) export",
                "vertical_datum": "not applicable",
                "resolution": "0.25 metre export pixels; source resolution in catalogue",
                "stated_accuracy": "project-specific",
                "processing_status": "raw service export acquired for visual QA",
                "sha256": sha256(public["qld_imagery"]),
                "notes": "Visual alignment reference only; not a substitute for survey control.",
            },
            {
                "dataset": "UQ St Lucia public campus map",
                "source": UQ_CAMPUS_MAP_URL,
                "local_path": _relative(public["uq_campus_map"], root),
                "download_date": datetime.fromtimestamp(
                    public["uq_campus_map"].stat().st_mtime
                ).date().isoformat(),
                "capture_date": "map current July 2025",
                "licence": "UQ copyright; no open-data licence identified",
                "horizontal_crs": "not stated",
                "vertical_datum": "not applicable",
                "resolution": "one-page PDF reference map",
                "stated_accuracy": "not stated",
                "processing_status": (
                    "reference copy only; do not trace or redistribute derivatives"
                ),
                "sha256": sha256(public["uq_campus_map"]),
                "notes": "Use to cross-check public building names/numbers, subject to UQ terms.",
            },
            {
                "dataset": "UQ BIM, utilities and digital-twin data",
                "source": "UQ Digital Modelling Office / Properties and Facilities",
                "local_path": "",
                "download_date": "",
                "capture_date": "unknown",
                "licence": "permission and publication conditions required from UQ",
                "horizontal_crs": "request GDA2020 / MGA zone 56",
                "vertical_datum": "request AHD",
                "resolution": "unknown",
                "stated_accuracy": "request source dates and accuracy classes",
                "processing_status": (
                    "deferred by project owner until public LoD demonstration exists"
                ),
                "sha256": "",
                "notes": "No authoritative utility geometry has been obtained or inferred.",
            },
        ]
    )
    return rows


def _write_register(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=DATA_REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_phase3(project_root: str | Path) -> dict[str, Any]:
    """Run the scoped Phase 3 public-data acquisition and validation workflow."""
    root = Path(project_root).resolve()
    incoming = root / "data" / "raw" / "elvis" / "incoming"
    if not incoming.is_dir():
        raise FileNotFoundError(f"ELVIS incoming directory does not exist: {incoming}")

    archives = archive_inventory(incoming)
    selected = extract_selected_elvis_2019(
        incoming, root / "data" / "raw" / "elvis" / "selected" / "brisbane_2019"
    )
    public = acquire_public_context(root / "data" / "raw")

    dem = _inspect_raster(selected["dem"])
    laz = _inspect_laz(selected["laz"])
    imagery = _inspect_raster(public["qld_imagery"])
    outlines = _inspect_geojson(public["qld_building_outlines"])
    areas = _inspect_geojson(public["qld_building_areas"])
    osm = _inspect_osm(public["osm_extract"])
    imagery_catalog = _read_imagery_catalog(public["qld_imagery_catalog"])

    dem_pilot_bounds = transform_bounds(
        f"EPSG:{PILOT_AREA.epsg}",
        f"EPSG:{dem['epsg']}",
        *PILOT_AREA.projected_bounds,
        densify_pts=21,
    )
    laz_pilot_bounds = transform_bounds(
        f"EPSG:{PILOT_AREA.epsg}",
        f"EPSG:{laz['epsg']}",
        *PILOT_AREA.projected_bounds,
        densify_pts=21,
    )

    checks = {
        "six_elvis_archives_present": len(archives) == 6,
        "all_elvis_archives_nonempty": all(item["bytes"] > 0 for item in archives),
        "selected_dem_is_geotiff": dem["driver"] == "GTiff",
        "selected_dem_is_one_metre": np.allclose(dem["resolution"], [1.0, 1.0]),
        "selected_dem_crs_is_documented_gda94_mga56": dem["epsg"] == 28356,
        "selected_dem_covers_pilot": bounds_cover(
            tuple(dem["bounds"]), dem_pilot_bounds
        ),
        "selected_laz_contains_points": laz["point_count"] > 0,
        "selected_laz_crs_is_documented_gda94_mga56": laz["epsg"] == 28356,
        "selected_laz_covers_pilot": bounds_cover(
            tuple(laz["bounds"]), laz_pilot_bounds
        ),
        "qld_outlines_available": outlines["features"] > 0,
        "qld_outlines_crs_is_epsg_7856": outlines["epsg"] == PILOT_AREA.epsg,
        "qld_building_areas_available": areas["features"] > 0,
        "osm_buildings_available": osm["building_ways"] + osm["building_relations"] > 0,
        "imagery_is_three_band_geotiff": (
            imagery["driver"] == "GTiff" and imagery["band_count"] == 3
        ),
        "imagery_crs_is_epsg_7856": imagery["epsg"] == PILOT_AREA.epsg,
        "imagery_covers_pilot": bounds_cover(tuple(imagery["bounds"]), PILOT_AREA.projected_bounds),
        "imagery_catalog_has_source": imagery_catalog["item_count"] > 0,
        "uq_reference_map_is_pdf": public["uq_campus_map"].read_bytes()[:4] == b"%PDF",
    }

    register = _write_register(
        root / "data" / "dataset_register.csv",
        _register_rows(root, archives, selected, public, imagery_catalog),
    )
    figure = _create_coverage_figure(
        public["qld_imagery"],
        public["qld_building_outlines"],
        root / "reports" / "figures" / "phase3_source_alignment.png",
    )

    summary_path = root / "reports" / "tables" / "phase3_inventory.json"
    summary = {
        "phase": 3,
        "scope": "public ELVIS prototype; UQ-controlled BIM and utility access deferred",
        "status": "passed" if all(checks.values()) else "failed",
        "pilot_area": {
            "horizontal_crs": f"EPSG:{PILOT_AREA.epsg}",
            "projected_bounds": list(PILOT_AREA.projected_bounds),
            "geographic_bounds": list(PILOT_AREA.geographic_bounds),
        },
        "elvis_archives": archives,
        "selected_dem": dem,
        "selected_laz": laz,
        "qld_building_outlines": outlines,
        "qld_building_areas": areas,
        "openstreetmap": osm,
        "imagery": imagery,
        "imagery_catalog": imagery_catalog,
        "outputs": {
            "data_register": _relative(register, root),
            "alignment_figure": _relative(figure, root),
        },
        "checks": checks,
        "limitations": [
            "The selected elevation capture is from 2019 and will omit later campus changes.",
            "The selected ELVIS elevation is natively GDA94 / MGA zone 56 and must be "
            "transformed to the EPSG:7856 working CRS in Phase 4.",
            "Public footprints are candidates and must be reconciled before modelling.",
            "No UQ-authoritative BIM or utility data is included.",
            "The LiDAR XML states Limited Use Licence; verify publication rights before "
            "distributing LiDAR-derived public products.",
            "The UQ campus-map PDF is a reference only and is not licensed as open GIS data.",
        ],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    summary["summary_report"] = _relative(summary_path, root)

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Phase 3 validation failed: {', '.join(failed)}")
    return summary


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    summary = run_phase3(project_root)
    print(f"Phase 3 status: {summary['status']}")
    print(f"Validation checks passed: {sum(summary['checks'].values())}/{len(summary['checks'])}")
    print(f"Summary report: {project_root / summary['summary_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
