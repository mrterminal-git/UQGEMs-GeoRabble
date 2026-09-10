"""Acquire and standardise public utility records for the Phase 8 pilot.

The public sources are useful planning context, not authoritative survey records.
In particular, source elevation fields are never labelled AHD unless the source
metadata explicitly declares the vertical datum.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box, shape

from uqgems.acquisition import PILOT_AREA
from uqgems.normalization import TARGET_EPSG

BCC_API_ROOT = "https://data.brisbane.qld.gov.au/api/explore/v2.1/catalog/datasets"
ARCGIS_ROOT = "https://services3.arcgis.com/ocUCNI2h4moKOpKX/ArcGIS/rest/services"
ARCGIS_ITEM_ROOT = "https://www.arcgis.com/sharing/rest/content/items"

BCC_DATASETS = {
    "stormwater-pipe-existing": "Stormwater Pipe",
    "stormwater-manhole-existing": "Stormwater Manhole",
    "stormwater-junction-existing": "Stormwater Junction",
    "stormwater-surface-drain-existing": "Stormwater Surface Drain",
    "stormwater-quality-improvement-device-existing": ("Stormwater Quality Improvement Device"),
}

URBAN_UTILITIES_SERVICES = {
    "water": {
        "service": f"{ARCGIS_ROOT}/UU_Water_OpenData/FeatureServer",
        "item_id": "b9ce06269e764a74964178481bfd5aaa",
    },
    "sewer": {
        "service": f"{ARCGIS_ROOT}/UU_Sewer_OpenData/FeatureServer",
        "item_id": "9ffcee891712417c92d3b1034a431d67",
    },
}

UTILITY_REQUIRED_FIELDS = {
    "asset_id",
    "network_type",
    "asset_type",
    "owner",
    "status",
    "diameter_or_size",
    "material",
    "horizontal_source",
    "vertical_source",
    "invert_z_ahd",
    "crown_z_ahd",
    "depth_m",
    "accuracy_xy",
    "accuracy_z",
    "survey_date",
    "confidence",
    "sensitivity",
    "notes",
}

UTILITY_COLUMNS = [
    "asset_id",
    "network_type",
    "asset_type",
    "owner",
    "status",
    "diameter_or_size",
    "material",
    "horizontal_source",
    "vertical_source",
    "vertical_class",
    "vertical_datum_confirmed",
    "invert_z_ahd",
    "crown_z_ahd",
    "depth_m",
    "accuracy_xy",
    "accuracy_z",
    "survey_date",
    "source_update_date",
    "confidence",
    "confidence_xy",
    "confidence_z",
    "sensitivity",
    "source_system",
    "source_dataset",
    "source_layer",
    "source_feature_id",
    "source_url",
    "source_reliability",
    "source_plan_number",
    "upstream_asset_id",
    "downstream_asset_id",
    "raw_upstream_surface_level",
    "raw_downstream_surface_level",
    "raw_upstream_invert_level",
    "raw_downstream_invert_level",
    "raw_invert_level",
    "raw_depth_m",
    "published_grade",
    "geometry_dimension",
    "geometry_status",
    "intersects_pilot",
    "within_pilot",
    "notes",
    "source_attributes_json",
    "geometry",
]

VERTICAL_CLASSES = {
    "surveyed_absolute_ahd",
    "surveyed_depth_below_known_surface",
    "approximate_recorded_depth",
    "schematic_depth",
    "unknown_depth",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _request_json(url: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    if parameters:
        url = f"{url}?{urllib.parse.urlencode(parameters)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "UQGEMs-GeoRabble/0.1 research prototype"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return json.load(response)


def _write_json_once(path: Path, payload: dict[str, Any]) -> Path:
    """Write an immutable raw response once, using an atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path
    partial = path.with_suffix(path.suffix + ".part")
    try:
        partial.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pilot_wkt() -> str:
    west, south, east, north = PILOT_AREA.geographic_bounds
    return f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"


def _bcc_extract(dataset_id: str) -> dict[str, Any]:
    endpoint = f"{BCC_API_ROOT}/{dataset_id}/records"
    where = f"intersects(geo_shape, geom'{_pilot_wkt()}')"
    results: list[dict[str, Any]] = []
    total = None
    offset = 0
    while total is None or offset < total:
        response = _request_json(
            endpoint,
            {"where": where, "limit": 100, "offset": offset, "timezone": "Australia/Brisbane"},
        )
        total = int(response.get("total_count", 0))
        page = response.get("results", [])
        results.extend(page)
        if not page:
            break
        offset += len(page)
    return {
        "source_url": endpoint,
        "query": {"where": where, "pilot_geographic_bounds": PILOT_AREA.geographic_bounds},
        "acquired_at_utc": _utc_now(),
        "total_count": int(total or 0),
        "results": results,
    }


def _arcgis_extract(service: str, layer_id: int) -> dict[str, Any]:
    endpoint = f"{service}/{layer_id}/query"
    west, south, east, north = PILOT_AREA.geographic_bounds
    base_parameters: dict[str, Any] = {
        "where": "1=1",
        "geometry": f"{west},{south},{east},{north}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": str(TARGET_EPSG),
        "resultRecordCount": "1000",
        "f": "geojson",
    }
    features: list[dict[str, Any]] = []
    crs: dict[str, Any] = {
        "type": "name",
        "properties": {"name": f"EPSG:{TARGET_EPSG}"},
    }
    offset = 0
    while True:
        parameters = {**base_parameters, "resultOffset": str(offset)}
        response = _request_json(endpoint, parameters)
        if "error" in response:
            raise RuntimeError(f"ArcGIS query failed for {endpoint}: {response['error']}")
        page = response.get("features", [])
        crs = response.get("crs", crs)
        features.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)
    return {
        "type": "FeatureCollection",
        "crs": crs,
        "features": features,
        "source_query": {
            "source_url": endpoint,
            "parameters": base_parameters,
            "pilot_geographic_bounds": PILOT_AREA.geographic_bounds,
            "acquired_at_utc": _utc_now(),
        },
    }


def acquire_public_utility_sources(raw_root: str | Path) -> list[dict[str, Any]]:
    """Cache immutable BCC and Urban Utilities public pilot-area responses."""
    root = Path(raw_root)
    sources: list[dict[str, Any]] = []
    for dataset_id, title in BCC_DATASETS.items():
        metadata_path = root / "bcc" / f"{dataset_id}_metadata.json"
        records_path = root / "bcc" / f"{dataset_id}_uq_pilot_records.json"
        if not metadata_path.is_file():
            _write_json_once(metadata_path, _request_json(f"{BCC_API_ROOT}/{dataset_id}"))
        if not records_path.is_file():
            _write_json_once(records_path, _bcc_extract(dataset_id))
        metadata = _load_json(metadata_path)
        record_data = _load_json(records_path)
        sources.append(
            {
                "source_system": "Brisbane City Council Open Data",
                "network_type": "stormwater",
                "dataset": dataset_id,
                "layer_id": None,
                "layer_name": title,
                "geometry_type": _bcc_geometry_type(metadata),
                "metadata_path": metadata_path,
                "records_path": records_path,
                "source_url": f"{BCC_API_ROOT}/{dataset_id}",
                "feature_count": len(record_data.get("results", [])),
                "licence": metadata.get("metas", {})
                .get("default", {})
                .get("license", "not stated"),
                "source_update_date": metadata.get("metas", {}).get("default", {}).get("modified"),
            }
        )

    for network_type, definition in URBAN_UTILITIES_SERVICES.items():
        service = str(definition["service"])
        item_id = str(definition["item_id"])
        service_metadata_path = root / "urban_utilities" / f"{network_type}_service.json"
        item_metadata_path = root / "urban_utilities" / f"{network_type}_item.json"
        if not service_metadata_path.is_file():
            _write_json_once(service_metadata_path, _request_json(service, {"f": "pjson"}))
        if not item_metadata_path.is_file():
            _write_json_once(
                item_metadata_path,
                _request_json(f"{ARCGIS_ITEM_ROOT}/{item_id}", {"f": "json"}),
            )
        service_metadata = _load_json(service_metadata_path)
        item_metadata = _load_json(item_metadata_path)
        for layer in service_metadata.get("layers", []):
            layer_id = int(layer["id"])
            slug = _slugify(str(layer["name"]))
            records_path = (
                root / "urban_utilities" / network_type / f"{layer_id:02d}_{slug}_uq_pilot.geojson"
            )
            if not records_path.is_file():
                _write_json_once(records_path, _arcgis_extract(service, layer_id))
            extract = _load_json(records_path)
            sources.append(
                {
                    "source_system": "Urban Utilities Open Data",
                    "network_type": network_type,
                    "dataset": f"uu_{network_type}_open_data",
                    "layer_id": layer_id,
                    "layer_name": str(layer["name"]),
                    "geometry_type": str(layer.get("geometryType", "unknown")),
                    "metadata_path": service_metadata_path,
                    "item_metadata_path": item_metadata_path,
                    "records_path": records_path,
                    "source_url": f"{service}/{layer_id}",
                    "feature_count": len(extract.get("features", [])),
                    "licence": _arcgis_licence(item_metadata),
                    "source_update_date": _arcgis_date(item_metadata.get("modified")),
                }
            )
    return sources


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _bcc_geometry_type(metadata: dict[str, Any]) -> str:
    geometry_types = metadata.get("metas", {}).get("default", {}).get("geometry_types", [])
    return ",".join(str(value) for value in geometry_types) or "unknown"


def _arcgis_licence(item: dict[str, Any]) -> str:
    licence = str(item.get("licenseInfo") or item.get("accessInformation") or "").strip()
    return licence or "No explicit redistribution licence found in public item metadata"


def _arcgis_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value)


def _source_gdf(source: dict[str, Any]) -> gpd.GeoDataFrame:
    payload = _load_json(Path(source["records_path"]))
    if source["source_system"] == "Brisbane City Council Open Data":
        records = payload.get("results", [])
        rows: list[dict[str, Any]] = []
        geometries = []
        for record in records:
            geometry_payload = record.get("geo_shape", {}).get("geometry")
            if not geometry_payload:
                continue
            rows.append({key: value for key, value in record.items() if key != "geo_shape"})
            geometries.append(shape(geometry_payload))
        frame = gpd.GeoDataFrame(rows, geometry=geometries, crs=4326)
        return frame.to_crs(TARGET_EPSG) if not frame.empty else _empty_source_gdf()
    features = payload.get("features", [])
    if not features:
        return _empty_source_gdf()
    return gpd.GeoDataFrame.from_features(features, crs=TARGET_EPSG)


def _empty_source_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=TARGET_EPSG)


def _lookup(row: pd.Series, *names: str) -> Any:
    mapping = {str(key).lower(): key for key in row.index}
    for name in names:
        key = mapping.get(name.lower())
        if key is not None:
            value = row[key]
            if not _is_missing(value):
                return value
    return None


def _lookup_declared(row: pd.Series, *names: str) -> Any:
    """Return a published value, preserving explicit values such as ``UNKNOWN``."""
    mapping = {str(key).lower(): key for key in row.index}
    for name in names:
        key = mapping.get(name.lower())
        if key is None:
            continue
        value = row[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().upper() in {"UNKNOWN", "UNK", "NULL", "NONE"}
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def clean_numeric(value: Any, *, sentinels: Iterable[float] = (999.0, 999.99)) -> float:
    """Return a finite source measurement, converting documented sentinel values to NaN."""
    if _is_missing(value):
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    if not math.isfinite(number) or any(math.isclose(number, sentinel) for sentinel in sentinels):
        return math.nan
    return number


def parse_size_mm(value: Any) -> float:
    """Parse a numeric diameter in millimetres from numeric or labelled source values."""
    if _is_missing(value):
        return math.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return clean_numeric(value, sentinels=())
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else math.nan


def _source_attributes(row: pd.Series) -> str:
    values: dict[str, Any] = {}
    for key, value in row.items():
        if key == "geometry" or _is_missing(value):
            continue
        if isinstance(value, (np.integer, np.floating)):
            value = value.item()
        values[str(key)] = value
    return json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))


def _vertical_evidence(row: pd.Series) -> tuple[dict[str, float], str]:
    raw = {
        "raw_upstream_surface_level": clean_numeric(_lookup(row, "ussl")),
        "raw_downstream_surface_level": clean_numeric(_lookup(row, "dssl")),
        "raw_upstream_invert_level": clean_numeric(_lookup(row, "usil")),
        "raw_downstream_invert_level": clean_numeric(_lookup(row, "dsil")),
        "raw_invert_level": clean_numeric(_lookup(row, "il")),
        "raw_depth_m": clean_numeric(_lookup(row, "averagedepth", "depth", "upstreamdepthinvert")),
    }
    if any(math.isfinite(value) for key, value in raw.items() if "level" in key):
        source = (
            "recorded source level(s), but the public metadata does not state a vertical "
            "datum; retained as raw values and not labelled AHD"
        )
    elif math.isfinite(raw["raw_depth_m"]):
        source = (
            "recorded source depth, but its reference surface and accuracy are not stated; "
            "retained as a raw value and not used for 3D placement"
        )
    else:
        source = "not published; depth unknown"
    return raw, source


def _confidence(source: dict[str, Any], row: pd.Series) -> tuple[str, str, str]:
    reliability = str(_lookup(row, "relycode") or "not published")
    if reliability.upper() == "FIELD LOCATED":
        horizontal = "medium"
    elif reliability.upper() == "AS CONSTRUCTED PLAN":
        horizontal = "medium"
    else:
        horizontal = "unknown"
    return "low", horizontal, "unknown"


def standardise_public_utilities(
    sources: list[dict[str, Any]],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Map heterogeneous public extracts into the common Phase 8 schema."""
    pilot = box(*PILOT_AREA.projected_bounds)
    records: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for source in sources:
        frame = _source_gdf(source)
        coverage_rows.append(
            {
                "source_system": source["source_system"],
                "network_type": source["network_type"],
                "source_dataset": source["dataset"],
                "source_layer": source["layer_name"],
                "source_layer_id": source["layer_id"],
                "geometry_type": source["geometry_type"],
                "feature_count": len(frame),
                "licence": source["licence"],
                "source_update_date": source["source_update_date"],
                "source_url": source["source_url"],
                "raw_extract": str(source["records_path"]),
            }
        )
        for index, row in frame.iterrows():
            geometry = row.geometry
            source_id = _lookup(row, "assetid", "objectid", "globalid")
            source_id = str(source_id if source_id is not None else index)
            prefix = "bcc" if source["source_system"].startswith("Brisbane") else "uu"
            asset_id = (
                f"{prefix}_{source['network_type']}_{_slugify(source['layer_name'])}_{source_id}"
            )
            if source["source_system"] == "Urban Utilities Open Data":
                detail = _lookup_declared(row, "servicetype", "subtypecd")
                asset_type_value = source["layer_name"]
                if detail is not None:
                    asset_type_value = f"{asset_type_value} ({detail})"
            else:
                asset_type_value = _lookup_declared(
                    row,
                    "pipetype",
                    "manholetype",
                    "sqidtype",
                    "draintype",
                    "subtype",
                    "subtypecd",
                )
            raw_vertical, vertical_source = _vertical_evidence(row)
            overall, confidence_xy, confidence_z = _confidence(source, row)
            diameter_value = _lookup(row, "diameter", "width", "nominaldiameter")
            diameter_mm = parse_size_mm(diameter_value)
            diameter_or_size = (
                f"{diameter_mm:g} mm" if math.isfinite(diameter_mm) else "not published"
            )
            reliability = _lookup_declared(row, "relycode")
            owner = str(_lookup_declared(row, "owner") or "not published")
            if owner.upper() == "QUU":
                owner = "Urban Utilities (QUU)"
            attributes = _source_attributes(row)
            records.append(
                {
                    "asset_id": asset_id,
                    "network_type": source["network_type"],
                    "asset_type": str(asset_type_value or source["layer_name"]),
                    "owner": owner,
                    "status": str(
                        _lookup_declared(row, "status", "retired") or "not published"
                    ),
                    "diameter_or_size": diameter_or_size,
                    "material": str(
                        _lookup_declared(row, "material", "material_abb")
                        or "not published"
                    ),
                    "horizontal_source": (
                        f"{source['source_system']}: {source['layer_name']} public extract"
                    ),
                    "vertical_source": vertical_source,
                    "vertical_class": "unknown_depth",
                    "vertical_datum_confirmed": False,
                    "invert_z_ahd": math.nan,
                    "crown_z_ahd": math.nan,
                    "depth_m": math.nan,
                    "accuracy_xy": (
                        f"source reliability: {reliability}; no numeric accuracy stated"
                        if reliability is not None
                        else "not stated in public source"
                    ),
                    "accuracy_z": "not stated; vertical datum not confirmed",
                    "survey_date": None,
                    "source_update_date": source["source_update_date"],
                    "confidence": overall,
                    "confidence_xy": confidence_xy,
                    "confidence_z": confidence_z,
                    "sensitivity": "public open-data record",
                    "source_system": source["source_system"],
                    "source_dataset": source["dataset"],
                    "source_layer": source["layer_name"],
                    "source_feature_id": source_id,
                    "source_url": source["source_url"],
                    "source_reliability": str(reliability or "not published"),
                    "source_plan_number": str(
                        _lookup(row, "planno", "amendedplanno") or "not published"
                    ),
                    "upstream_asset_id": str(_lookup(row, "usassetid") or ""),
                    "downstream_asset_id": str(_lookup(row, "dsassetid") or ""),
                    **raw_vertical,
                    "published_grade": str(_lookup(row, "grade") or ""),
                    "geometry_dimension": "2D",
                    "geometry_status": (
                        "valid" if geometry is not None and geometry.is_valid else "invalid"
                    ),
                    "intersects_pilot": bool(geometry is not None and geometry.intersects(pilot)),
                    "within_pilot": bool(geometry is not None and geometry.within(pilot)),
                    "notes": (
                        "Public planning context only; not excavation-safe. No schematic depth "
                        "has been assigned. Source attributes are retained in JSON."
                    ),
                    "source_attributes_json": attributes,
                    "geometry": geometry,
                }
            )
    if records:
        utilities = gpd.GeoDataFrame(records, columns=UTILITY_COLUMNS, crs=TARGET_EPSG)
    else:
        utilities = gpd.GeoDataFrame(columns=UTILITY_COLUMNS, geometry="geometry", crs=TARGET_EPSG)
    coverage = pd.DataFrame(coverage_rows)
    return utilities, coverage


def utility_lines_and_nodes(
    utilities: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    lines = utilities[utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    nodes = utilities[utilities.geometry.geom_type.isin(["Point", "MultiPoint"])].copy()
    return lines, nodes


def parse_grade_denominator(value: Any) -> float:
    if _is_missing(value):
        return math.nan
    match = re.search(r"1\s*:\s*([0-9]+(?:\.[0-9]+)?)", str(value))
    return float(match.group(1)) if match else math.nan


def grade_diagnostics(row: pd.Series) -> dict[str, float | bool]:
    """Compare published pipe grade with geometry length and recorded invert levels."""
    upstream = clean_numeric(row.get("raw_upstream_invert_level"))
    downstream = clean_numeric(row.get("raw_downstream_invert_level"))
    denominator = parse_grade_denominator(row.get("published_grade"))
    length = float(row.geometry.length) if row.geometry is not None else math.nan
    if not all(math.isfinite(value) for value in (upstream, downstream, length)):
        return {
            "computed_drop_m": math.nan,
            "computed_gradient_percent": math.nan,
            "computed_grade_denominator": math.nan,
            "published_grade_denominator": denominator,
            "grade_discrepancy": False,
        }
    drop = upstream - downstream
    computed = length / abs(drop) if not math.isclose(drop, 0.0) else math.inf
    discrepancy = bool(
        math.isfinite(denominator)
        and math.isfinite(computed)
        and abs(computed - denominator) / max(denominator, 1.0) > 0.25
    )
    return {
        "computed_drop_m": drop,
        "computed_gradient_percent": 100.0 * drop / length if length else math.nan,
        "computed_grade_denominator": computed,
        "published_grade_denominator": denominator,
        "grade_discrepancy": discrepancy,
    }


def _line_endpoints(geometry: Any) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
        return [Point(coordinates[0]), Point(coordinates[-1])]
    endpoints: list[Point] = []
    if geometry.geom_type == "MultiLineString":
        for part in geometry.geoms:
            endpoints.extend(_line_endpoints(part))
    return endpoints


def connectivity_statistics(
    lines: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, tolerance_m: float = 1.0
) -> dict[str, int]:
    """Screen clipped line endpoints against public nodes and the pilot boundary."""
    pilot = box(*PILOT_AREA.projected_bounds)
    endpoints_total = 0
    matched = 0
    boundary = 0
    unexplained = 0
    for _, line in lines.iterrows():
        clipped = line.geometry.intersection(pilot)
        for endpoint in _line_endpoints(clipped):
            endpoints_total += 1
            same_network = nodes[nodes["network_type"] == line["network_type"]]
            node_match = bool(
                len(same_network)
                and float(same_network.geometry.distance(endpoint).min()) <= tolerance_m
            )
            boundary_match = endpoint.distance(pilot.boundary) <= tolerance_m
            if node_match:
                matched += 1
            elif boundary_match:
                boundary += 1
            else:
                unexplained += 1
    return {
        "line_endpoints_total": endpoints_total,
        "endpoints_matched_to_public_node_1m": matched,
        "endpoints_at_pilot_boundary_1m": boundary,
        "unexplained_open_endpoints": unexplained,
    }


def building_overlap_ids(lines: gpd.GeoDataFrame, building_geometries: gpd.GeoSeries) -> list[str]:
    overlaps: list[str] = []
    for _, line in lines.iterrows():
        if bool(building_geometries.intersects(line.geometry).any()):
            overlaps.append(str(line["asset_id"]))
    return overlaps


def write_utility_geopackage(utilities: gpd.GeoDataFrame, destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines, nodes = utility_lines_and_nodes(utilities)
    boundary = gpd.GeoDataFrame(
        [{"area_id": "uq_pilot_500m", "geometry": box(*PILOT_AREA.projected_bounds)}],
        crs=TARGET_EPSG,
    )
    temporary = destination.with_name(destination.stem + ".part.gpkg")
    temporary.unlink(missing_ok=True)
    try:
        if not lines.empty:
            lines.to_file(temporary, layer="utility_lines", driver="GPKG", engine="pyogrio")
        if not nodes.empty:
            nodes.to_file(temporary, layer="utility_nodes", driver="GPKG", engine="pyogrio")
        boundary.to_file(temporary, layer="pilot_boundary", driver="GPKG", engine="pyogrio")
        if destination.is_file():
            destination.unlink()
        shutil.move(str(temporary), str(destination))
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def linestring_with_linear_z(geometry: LineString, start_z: float, end_z: float) -> LineString:
    """Return a 3D line with elevations interpolated by cumulative plan length."""
    coordinates = list(geometry.coords)
    if len(coordinates) < 2:
        raise ValueError("A utility line needs at least two vertices")
    lengths = [0.0]
    for first, second in zip(coordinates[:-1], coordinates[1:], strict=True):
        lengths.append(lengths[-1] + Point(first).distance(Point(second)))
    total = lengths[-1]
    if total <= 0:
        raise ValueError("A utility line cannot have zero plan length")
    xyz = [
        (float(x), float(y), float(start_z + (end_z - start_z) * distance / total))
        for (x, y, *_), distance in zip(coordinates, lengths, strict=True)
    ]
    return LineString(xyz)
