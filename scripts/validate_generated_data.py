#!/usr/bin/env python3
"""Validate the static files consumed by the transit-affinity frontend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = {
    'build_metadata.json',
    'hexagons.json',
    'h3_hexagons.geojson',
    'routes.json',
    'routes.geojson',
    'wards.json',
    'wards.geojson',
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def validate_chunks(data_dir: Path, directory_name: str, expected_ids: set[str],
                    require_meta: bool = False) -> tuple[int, int]:
    chunks_dir = data_dir / directory_name
    index = load_json(chunks_dir / 'index.json')
    if set(index) != expected_ids:
        missing = expected_ids - set(index)
        extra = set(index) - expected_ids
        raise ValueError(
            f'{directory_name} index mismatch: missing={len(missing)}, extra={len(extra)}'
        )

    chunk_names = set(index.values())
    indexed_ids = set()
    for chunk_name in chunk_names:
        chunk_path = chunks_dir / chunk_name
        if not chunk_path.exists():
            raise ValueError(f'{directory_name} references missing {chunk_name}')
        indexed_ids.update(load_json(chunk_path))
    if indexed_ids != expected_ids:
        raise ValueError(f'{directory_name} chunk contents do not match their index')

    if require_meta:
        meta = load_json(chunks_dir / 'meta.json')
        if not isinstance(meta.get('globalMaxScore'), int) or meta['globalMaxScore'] < 1:
            raise ValueError(f'{directory_name} has an invalid globalMaxScore')
        global_max = meta['globalMaxScore']
    else:
        global_max = 0
    return len(chunk_names), global_max


def validate(data_dir: Path, expected_wards: int) -> None:
    missing_files = [name for name in REQUIRED_FILES if not (data_dir / name).exists()]
    if missing_files:
        raise ValueError(f'missing required files: {", ".join(sorted(missing_files))}')

    wards = load_json(data_dir / 'wards.json')
    ward_ids = {ward['id'] for ward in wards}
    if len(wards) != expected_wards or len(ward_ids) != expected_wards:
        raise ValueError(f'expected {expected_wards} unique wards, found {len(ward_ids)}')
    ward_geojson = load_json(data_dir / 'wards.geojson')
    ward_feature_ids = {
        feature.get('properties', {}).get('namecol')
        for feature in ward_geojson.get('features', [])
    }
    if ward_feature_ids != ward_ids:
        raise ValueError('wards.json and wards.geojson IDs do not match')

    hexagons = load_json(data_dir / 'hexagons.json')
    hex_ids = {hexagon['id'] for hexagon in hexagons}
    if len(hexagons) != len(hex_ids):
        raise ValueError('hexagons.json contains duplicate IDs')
    hex_geojson = load_json(data_dir / 'h3_hexagons.geojson')
    hex_feature_ids = {
        feature.get('properties', {}).get('hex_id')
        for feature in hex_geojson.get('features', [])
        if not feature.get('properties', {}).get('is_background')
    }
    if hex_feature_ids != hex_ids:
        raise ValueError('hexagons.json and h3_hexagons.geojson IDs do not match')

    routes = load_json(data_dir / 'routes.json')
    route_features = load_json(data_dir / 'routes.geojson').get('features', [])
    unknown_route_ids = {
        feature.get('properties', {}).get('route_id') for feature in route_features
    } - set(routes)
    if unknown_route_ids:
        raise ValueError(f'routes.geojson contains {len(unknown_route_ids)} unknown routes')

    ward_connectivity_chunks, ward_max = validate_chunks(
        data_dir, 'connectivity_chunks', ward_ids, require_meta=True
    )
    ward_route_chunks, _ = validate_chunks(
        data_dir, 'routes_cache_chunks', ward_ids
    )
    h3_connectivity_chunks, h3_max = validate_chunks(
        data_dir, 'h3_connectivity_chunks', hex_ids, require_meta=True
    )
    h3_route_chunks, _ = validate_chunks(
        data_dir, 'h3_routes_cache_chunks', hex_ids
    )

    metadata = load_json(data_dir / 'build_metadata.json')
    if metadata.get('h3_resolution') != 8:
        raise ValueError('build metadata does not record H3 resolution 8')
    if metadata.get('representative_day') != 'wednesday':
        raise ValueError('build metadata does not record Wednesday service')

    print(f'Validated {len(hex_ids)} hexagons and {len(ward_ids)} wards')
    print(f'Routes: {len(routes)} metadata records, {len(route_features)} map features')
    print(
        'Chunks: '
        f'h3 connectivity={h3_connectivity_chunks} (max {h3_max}), '
        f'h3 routes={h3_route_chunks}, '
        f'ward connectivity={ward_connectivity_chunks} (max {ward_max}), '
        f'ward routes={ward_route_chunks}'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir', type=Path)
    parser.add_argument('--expected-wards', type=int, default=26)
    args = parser.parse_args()
    try:
        validate(args.data_dir, args.expected_wards)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f'Validation failed: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
