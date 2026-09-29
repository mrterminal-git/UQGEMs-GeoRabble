#!/usr/bin/env python3
"""Download Brisbane City Council wards and derive the enclosing LGA boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape
from shapely.ops import unary_union


WARD_LAYER_URL = (
    "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
    "Boundaries/AdministrativeBoundaries/MapServer/8/query"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "scripts" / "geojson"
EXPECTED_WARD_COUNT = 26
ATTRIBUTION = (
    "State of Queensland (Department of Natural Resources and Mines, "
    "Manufacturing and Regional and Rural Development) and Electoral "
    "Commission of Queensland"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the official Brisbane City Council ward boundaries."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"destination directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--url",
        default=WARD_LAYER_URL,
        help="ArcGIS query endpoint; primarily useful for testing",
    )
    return parser.parse_args()


def query_url(endpoint: str) -> str:
    params = urllib.parse.urlencode(
        {
            "where": "1=1",
            "outFields": "ward_name,lga,elect_yr,act",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        }
    )
    return f"{endpoint}?{params}"


def download_geojson(url: str) -> tuple[dict[str, Any], str, int]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "UQGEMs-GeoRabble boundary downloader"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"could not download {url}: {error}") from error

    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeError("boundary response was not valid JSON") from error

    return document, hashlib.sha256(payload).hexdigest(), len(payload)


def rounded(value: Any, places: int = 6) -> Any:
    """Round GeoJSON coordinates while preserving the surrounding structure."""
    if isinstance(value, float):
        return round(value, places)
    if isinstance(value, list):
        return [rounded(item, places) for item in value]
    if isinstance(value, tuple):
        return [rounded(item, places) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item, places) for key, item in value.items()}
    return value


def normalize_wards(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("type") != "FeatureCollection":
        raise RuntimeError("boundary response is not a GeoJSON FeatureCollection")

    wards = []
    seen_names = set()
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        name = str(properties.get("ward_name", "")).strip()
        geometry = feature.get("geometry")
        if not name or not geometry:
            continue
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise RuntimeError(f"ward {name!r} has unsupported geometry")
        if name in seen_names:
            raise RuntimeError(f"duplicate ward name: {name}")

        ward_geometry = shape(geometry)
        if not ward_geometry.is_valid:
            ward_geometry = ward_geometry.buffer(0)
        if ward_geometry.is_empty or not ward_geometry.is_valid:
            raise RuntimeError(f"ward {name!r} has invalid geometry")

        seen_names.add(name)
        wards.append(
            {
                "type": "Feature",
                "properties": {
                    "namecol": name,
                    "ward_name": name,
                    "lga": properties.get("lga", "Brisbane City"),
                    "election_year": properties.get("elect_yr"),
                },
                "geometry": rounded(mapping(ward_geometry)),
            }
        )

    if len(wards) != EXPECTED_WARD_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_WARD_COUNT} Brisbane wards, received {len(wards)}"
        )

    wards.sort(key=lambda feature: feature["properties"]["namecol"])
    return {"type": "FeatureCollection", "features": wards}


def derive_lga(wards: dict[str, Any]) -> dict[str, Any]:
    ward_geometries = [shape(feature["geometry"]) for feature in wards["features"]]
    boundary = unary_union(ward_geometries)
    if boundary.is_empty or boundary.geom_type not in {"Polygon", "MultiPolygon"}:
        raise RuntimeError("could not derive a polygonal Brisbane LGA boundary")
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Brisbane City Council"},
                "geometry": rounded(mapping(boundary)),
            }
        ],
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def install_boundaries(
    output_directory: Path,
    wards: dict[str, Any],
    lga: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".brisbane-boundaries-", dir=output_directory
    ) as temporary_directory:
        staging = Path(temporary_directory)
        staged_files = {
            "brisbane_wards.geojson": wards,
            "brisbane_lga.geojson": lga,
            "brisbane_boundaries_metadata.json": metadata,
        }
        for filename, document in staged_files.items():
            write_json(staging / filename, document)
        for filename in staged_files:
            (staging / filename).replace(output_directory / filename)


def main() -> int:
    args = parse_args()
    url = query_url(args.url)
    try:
        document, source_sha256, source_size = download_geojson(url)
        wards = normalize_wards(document)
        lga = derive_lga(wards)
        metadata = {
            "source_url": url,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_sha256": source_sha256,
            "source_size_bytes": source_size,
            "ward_count": len(wards["features"]),
            "license": "Creative Commons Attribution 4.0 International",
            "attribution": ATTRIBUTION,
        }
        install_boundaries(args.output.resolve(), wards, lga, metadata)
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}")
        return 1

    print(
        f"Installed {len(wards['features'])} Brisbane wards and the derived LGA "
        f"boundary in {args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
