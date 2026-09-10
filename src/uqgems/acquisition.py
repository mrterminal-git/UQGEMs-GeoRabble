"""Source definitions and download helpers for the Phase 3 pilot dataset."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PilotArea:
    """The 500 m by 500 m UQ St Lucia pilot area."""

    epsg: int = 7856
    west: float = 501_103.215
    south: float = 6_958_210.027
    east: float = 501_603.215
    north: float = 6_958_710.027
    west_lon: float = 153.0111692
    south_lat: float = -27.4997572
    east_lon: float = 153.0162307
    north_lat: float = -27.4952427

    @property
    def projected_bounds(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north

    @property
    def geographic_bounds(self) -> tuple[float, float, float, float]:
        return self.west_lon, self.south_lat, self.east_lon, self.north_lat


PILOT_AREA = PilotArea()

ELVIS_MAIN_ARCHIVE = "DATA_2380922.zip"
ELVIS_DEM_MEMBER = (
    "QLD Government/DEM/1 Metre/"
    "Brisbane_2019_Prj_SW_501000_6958000_1k_DEM_1m.tif"
)
ELVIS_DEM_METADATA_MEMBER = "QLD Government/metadata/Brisbane_2019_Prj_1K_DEM_1m.xml"
ELVIS_LIDAR_ARCHIVE_MEMBER = (
    "QLD Government/Point Clouds/AHD/"
    "Brisbane_2019_Prj_SW_501000_6958000_1k_las.zip"
)
ELVIS_LAZ_MEMBER = "Brisbane_2019_Prj_SW_501000_6958000_1k_class_AHD.laz"
ELVIS_LAZ_METADATA_MEMBER = "Metadata/Queensland LiDAR Data - Brisbane 2019 Project.xml"

BUILDINGS_SERVICE = (
    "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
    "Structure/BuildingsAndSettlements/MapServer"
)
IMAGERY_SERVICE = (
    "https://spatial-img.information.qld.gov.au/arcgis/rest/services/"
    "Basemaps/LatestStateProgram_AllUsers/ImageServer"
)
UQ_CAMPUS_MAP_URL = (
    "https://about.uq.edu.au/sites/default/files/2026-07/St-Lucia-campus-map.pdf"
)


def sha256(path: str | Path) -> str:
    """Return the SHA-256 checksum of a file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_inventory(incoming_dir: str | Path) -> list[dict[str, Any]]:
    """Inventory untouched ELVIS zip deliveries and their checksums."""
    incoming = Path(incoming_dir)
    archives = sorted(incoming.glob("*.zip"))
    return [
        {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "file_modified_date": datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
            "sha256": sha256(path),
        }
        for path in archives
    ]


def _copy_member(archive: zipfile.ZipFile, member: str, destination: Path) -> Path:
    """Copy one exact archive member without trusting member paths."""
    if member not in archive.namelist():
        raise FileNotFoundError(f"Expected archive member is missing: {member}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with archive.open(member) as source, partial.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def extract_selected_elvis_2019(
    incoming_dir: str | Path, selected_dir: str | Path
) -> dict[str, Path]:
    """Extract the selected 2019 DEM, LAZ and metadata while retaining originals."""
    incoming = Path(incoming_dir)
    selected = Path(selected_dir)
    main_archive = incoming / ELVIS_MAIN_ARCHIVE
    if not main_archive.is_file():
        raise FileNotFoundError(
            f"{main_archive} was not found. Keep the ELVIS order zips in {incoming}."
        )

    dem_path = selected / Path(ELVIS_DEM_MEMBER).name
    dem_metadata_path = selected / Path(ELVIS_DEM_METADATA_MEMBER).name
    laz_path = selected / ELVIS_LAZ_MEMBER
    laz_metadata_path = selected / Path(ELVIS_LAZ_METADATA_MEMBER).name

    with zipfile.ZipFile(main_archive) as outer:
        _copy_member(outer, ELVIS_DEM_MEMBER, dem_path)
        _copy_member(outer, ELVIS_DEM_METADATA_MEMBER, dem_metadata_path)

        if not laz_path.is_file() or not laz_metadata_path.is_file():
            if ELVIS_LIDAR_ARCHIVE_MEMBER not in outer.namelist():
                raise FileNotFoundError(
                    f"Expected nested archive is missing: {ELVIS_LIDAR_ARCHIVE_MEMBER}"
                )
            with outer.open(ELVIS_LIDAR_ARCHIVE_MEMBER) as nested_source:
                with tempfile.TemporaryFile() as nested_file:
                    shutil.copyfileobj(nested_source, nested_file, length=1024 * 1024)
                    nested_file.seek(0)
                    with zipfile.ZipFile(nested_file) as nested:
                        _copy_member(nested, ELVIS_LAZ_MEMBER, laz_path)
                        _copy_member(nested, ELVIS_LAZ_METADATA_MEMBER, laz_metadata_path)

    return {
        "dem": dem_path,
        "dem_metadata": dem_metadata_path,
        "laz": laz_path,
        "laz_metadata": laz_metadata_path,
    }


def _download(url: str, destination: Path) -> Path:
    """Download a source file once, leaving an existing raw file unchanged."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        return destination
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "UQGEMs-GeoRabble/0.1 research prototype"},
    )
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            with partial.open("wb") as target:
                shutil.copyfileobj(response, target, length=1024 * 1024)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def _query_url(endpoint: str, parameters: dict[str, str]) -> str:
    return f"{endpoint}?{urllib.parse.urlencode(parameters)}"


def acquire_public_context(raw_dir: str | Path) -> dict[str, Path]:
    """Acquire public footprint, OSM, imagery and UQ reference-map sources."""
    raw = Path(raw_dir)
    area = PILOT_AREA
    envelope = ",".join(str(value) for value in area.projected_bounds)
    geographic = ",".join(str(value) for value in area.geographic_bounds)

    building_parameters = {
        "where": "1=1",
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": str(area.epsg),
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": str(area.epsg),
        "f": "geojson",
    }
    imagery_export_parameters = {
        "bbox": envelope,
        "bboxSR": str(area.epsg),
        "imageSR": str(area.epsg),
        "size": "2000,2000",
        "format": "tiff",
        "pixelType": "U8",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }
    imagery_query_parameters = {
        "where": "1=1",
        "geometry": json.dumps(
            {
                "xmin": area.west,
                "ymin": area.south,
                "xmax": area.east,
                "ymax": area.north,
                "spatialReference": {"wkid": area.epsg},
            },
            separators=(",", ":"),
        ),
        "geometryType": "esriGeometryEnvelope",
        "inSR": str(area.epsg),
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": (
            "objectid,name,year,title,capturestart,captureend,metalink,"
            "product_type,info_sec_clas,res_value,res_unit"
        ),
        "returnGeometry": "false",
        "orderByFields": "year DESC",
        "f": "json",
    }

    urls = {
        "qld_building_outlines": _query_url(
            f"{BUILDINGS_SERVICE}/11/query", building_parameters
        ),
        "qld_building_areas": _query_url(
            f"{BUILDINGS_SERVICE}/20/query", building_parameters
        ),
        "osm_extract": f"https://api.openstreetmap.org/api/0.6/map?bbox={geographic}",
        "qld_imagery": _query_url(f"{IMAGERY_SERVICE}/exportImage", imagery_export_parameters),
        "qld_imagery_catalog": _query_url(
            f"{IMAGERY_SERVICE}/query", imagery_query_parameters
        ),
        "qld_imagery_service": f"{IMAGERY_SERVICE}?f=pjson",
        "uq_campus_map": UQ_CAMPUS_MAP_URL,
    }
    destinations = {
        "qld_building_outlines": raw / "qld_buildings" / "building_outlines.geojson",
        "qld_building_areas": raw / "qld_buildings" / "building_areas.geojson",
        "osm_extract": raw / "openstreetmap" / "uq_pilot.osm",
        "qld_imagery": raw / "qld_imagery" / "latest_public_orthophoto.tif",
        "qld_imagery_catalog": raw / "qld_imagery" / "catalog_query.json",
        "qld_imagery_service": raw / "qld_imagery" / "service_metadata.json",
        "uq_campus_map": raw / "uq_public" / "St-Lucia-campus-map.pdf",
    }
    return {name: _download(urls[name], path) for name, path in destinations.items()}
