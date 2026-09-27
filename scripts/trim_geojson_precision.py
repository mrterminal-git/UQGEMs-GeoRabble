#!/usr/bin/env python3
"""Trim coordinate precision of all GeoJSON files under static/data in place.

Rounds geometry coordinates to 6 decimal places (~10cm), which is well beyond
what the map renders, shrinking the geometry payloads with no visible change.
Idempotent: re-running on already-trimmed files is a no-op in size.

Usage:
    python scripts/trim_geojson_precision.py [DATA_DIR] [--precision N]
"""

import argparse
import json
import sys
from pathlib import Path


def round_coords(coords, precision):
    if isinstance(coords, float):
        return round(coords, precision)
    if isinstance(coords, int):
        return coords
    if isinstance(coords, list):
        return [round_coords(c, precision) for c in coords]
    return coords


def trim_file(path: Path, precision: int) -> tuple[int, int]:
    before = path.stat().st_size
    with open(path) as f:
        gj = json.load(f)

    for feature in gj.get('features', []):
        geometry = feature.get('geometry')
        if geometry and 'coordinates' in geometry:
            geometry['coordinates'] = round_coords(geometry['coordinates'], precision)

    with open(path, 'w') as f:
        json.dump(gj, f, separators=(',', ':'))

    after = path.stat().st_size
    return before, after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_dir', nargs='?', default='static/data')
    parser.add_argument('--precision', type=int, default=6)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Directory not found: {data_dir}", file=sys.stderr)
        return 1

    files = sorted(
        p for p in data_dir.rglob('*.geojson')
        if not any(part.startswith('.') for part in p.relative_to(data_dir).parts)
    )
    if not files:
        print(f"No .geojson files under {data_dir}")
        return 0

    total_before = total_after = 0
    for path in files:
        before, after = trim_file(path, args.precision)
        total_before += before
        total_after += after
        pct = 100 * (1 - after / before) if before else 0
        print(f"{path}: {before / 1e6:.2f}MB -> {after / 1e6:.2f}MB ({pct:.1f}%)")

    pct = 100 * (1 - total_after / total_before) if total_before else 0
    print(f"\nTotal: {total_before / 1e6:.2f}MB -> {total_after / 1e6:.2f}MB ({pct:.1f}% smaller)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
