#!/usr/bin/env python3
"""
Generate routes.geojson from GTFS shapes.txt, trips.txt, and routes.txt.
Each feature is a LineString for one route, with route metadata as properties.

Usage:
    python generate_routes_geojson.py <gtfs_dir> <city_code>
    python generate_routes_geojson.py SEQ_GTFS/SEQ_GTFS.zip brisbane
"""

import sys
import zipfile
import csv
import io
import json
from pathlib import Path
from collections import defaultdict

from shapely.geometry import LineString

from utils import discover_gtfs_files, save_json, haversine_km


def _boundary_point(p_in, p_out, center, radius_km):
    """Point on segment p_in->p_out that lies exactly on the radius boundary."""
    clon, clat = center
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        lon = p_in[0] + (p_out[0] - p_in[0]) * mid
        lat = p_in[1] + (p_out[1] - p_in[1]) * mid
        if haversine_km(clon, clat, lon, lat) <= radius_km:
            lo = mid
        else:
            hi = mid
    return (round(p_in[0] + (p_out[0] - p_in[0]) * lo, 6),
            round(p_in[1] + (p_out[1] - p_in[1]) * lo, 6))


def clip_line_to_radius(coords, center, radius_km):
    """Clip a polyline to within `radius_km` of `center` (lon, lat).

    Keeps contiguous runs of in-range vertices and interpolates the exact
    boundary crossing point where a run enters/exits the circle, so lines end
    on the radius. Returns a list of runs (each >=2 points); empty if none.
    """
    clon, clat = center
    inside = [haversine_km(clon, clat, lon, lat) <= radius_km for lon, lat in coords]
    runs = []
    i = 0
    n = len(coords)
    while i < n:
        if not inside[i]:
            i += 1
            continue
        start = i
        while i < n and inside[i]:
            i += 1
        end = i  # exclusive
        run = list(coords[start:end])
        if start > 0:
            run.insert(0, _boundary_point(coords[start], coords[start - 1], center, radius_km))
        if end < n:
            run.append(_boundary_point(coords[end - 1], coords[end], center, radius_km))
        if len(run) >= 2:
            runs.append(run)
    return runs


def clip_line_to_geometry(coords, boundary_geometry):
    """Clip a polyline to a polygon and return its LineString coordinate runs."""
    clipped = LineString(coords).intersection(boundary_geometry)
    runs = []

    def collect_lines(geometry):
        if geometry.is_empty:
            return
        if geometry.geom_type == 'LineString':
            run = [(round(lon, 6), round(lat, 6)) for lon, lat in geometry.coords]
            if len(run) >= 2:
                runs.append(run)
            return
        if hasattr(geometry, 'geoms'):
            for child in geometry.geoms:
                collect_lines(child)

    collect_lines(clipped)
    return runs


def load_csv_from_zip(zip_path, filename):
    rows = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        try:
            with zf.open(filename) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                for row in reader:
                    rows.append(row)
        except KeyError:
            pass
    return rows


def simplify_coords(coords, tolerance):
    """Simplify a polyline using the Ramer-Douglas-Peucker algorithm."""
    if len(coords) <= 2:
        return coords

    def point_line_distance(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 and dy == 0:
            return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        proj = (a[0] + t * dx, a[1] + t * dy)
        return ((p[0] - proj[0]) ** 2 + (p[1] - proj[1]) ** 2) ** 0.5

    max_dist = 0
    max_idx = 0
    for i in range(1, len(coords) - 1):
        d = point_line_distance(coords[i], coords[0], coords[-1])
        if d > max_dist:
            max_dist = d
            max_idx = i

    if max_dist > tolerance:
        left = simplify_coords(coords[:max_idx + 1], tolerance)
        right = simplify_coords(coords[max_idx:], tolerance)
        return left[:-1] + right
    return [coords[0], coords[-1]]


def generate_routes_geojson(gtfs_paths, output_path, tolerance=0.0001, min_trips=5,
                            crop_center=None, crop_radius_km=None,
                            boundary_geometry=None, included_route_ids=None):
    routes_by_id = {}
    trip_to_route = {}
    trip_to_shape = {}
    route_trip_count = defaultdict(int)
    shapes = defaultdict(list)

    for gtfs_path in gtfs_paths:
        print(f"Reading {gtfs_path.name}...")

        for row in load_csv_from_zip(gtfs_path, 'routes.txt'):
            rid = row['route_id']
            routes_by_id[rid] = {
                'route_id': rid,
                'route_short_name': row.get('route_short_name', ''),
                'route_long_name': row.get('route_long_name', ''),
            }

        for row in load_csv_from_zip(gtfs_path, 'trips.txt'):
            tid = row['trip_id']
            trip_to_route[tid] = row['route_id']
            route_trip_count[row['route_id']] += 1
            shape_id = row.get('shape_id', '')
            if shape_id:
                trip_to_shape[tid] = shape_id

        for row in load_csv_from_zip(gtfs_path, 'shapes.txt'):
            sid = row['shape_id']
            seq = int(row['shape_pt_sequence'])
            lon = float(row['shape_pt_lon'])
            lat = float(row['shape_pt_lat'])
            shapes[sid].append((seq, lon, lat))

    # Sort shape points by sequence
    for sid in shapes:
        shapes[sid].sort(key=lambda x: x[0])

    # Map route_id -> best shape_id (pick the longest shape per route)
    route_shapes = defaultdict(set)
    for tid, shape_id in trip_to_shape.items():
        rid = trip_to_route.get(tid)
        if rid:
            route_shapes[rid].add(shape_id)

    # For each route, pick the shape with the most points (most detailed)
    route_best_shape = {}
    for rid, shape_ids in route_shapes.items():
        if included_route_ids is not None and rid not in included_route_ids:
            continue
        if route_trip_count[rid] < min_trips:
            continue
        best = max(shape_ids, key=lambda sid: len(shapes.get(sid, [])))
        if shapes.get(best):
            route_best_shape[rid] = best

    total_points_before = 0
    total_points_after = 0
    features = []
    for rid, shape_id in sorted(route_best_shape.items()):
        route_info = routes_by_id.get(rid, {})
        coords = [(lon, lat) for _, lon, lat in shapes[shape_id]]
        if len(coords) < 2:
            continue

        total_points_before += len(coords)
        coords = simplify_coords(coords, tolerance)

        properties = {
            'route_id': rid,
            'route_short_name': route_info.get('route_short_name', ''),
            'route_long_name': route_info.get('route_long_name', ''),
        }

        if boundary_geometry is not None:
            runs = clip_line_to_geometry(coords, boundary_geometry)
            if not runs:
                continue
            total_points_after += sum(len(r) for r in runs)
            if len(runs) == 1:
                geometry = {'type': 'LineString', 'coordinates': runs[0]}
            else:
                geometry = {'type': 'MultiLineString', 'coordinates': runs}
        elif crop_radius_km and crop_center:
            runs = clip_line_to_radius(coords, crop_center, crop_radius_km)
            if not runs:
                continue
            total_points_after += sum(len(r) for r in runs)
            if len(runs) == 1:
                geometry = {'type': 'LineString', 'coordinates': runs[0]}
            else:
                geometry = {'type': 'MultiLineString', 'coordinates': runs}
        else:
            total_points_after += len(coords)
            geometry = {'type': 'LineString', 'coordinates': coords}

        features.append({
            'type': 'Feature',
            'properties': properties,
            'geometry': geometry,
        })

    print(f"Simplified shapes: {total_points_before} -> {total_points_after} points "
          f"({total_points_after/total_points_before*100:.1f}%)" if total_points_before else "")

    geojson = {
        'type': 'FeatureCollection',
        'features': features,
    }

    print(f"Generated {len(features)} route features")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(geojson, f, separators=(',', ':'))
    print(f"Saved {output_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python generate_routes_geojson.py <gtfs_dir> <city_code>")
        sys.exit(1)

    gtfs_dir = Path(sys.argv[1])
    city_code = sys.argv[2]

    gtfs_paths = discover_gtfs_files(gtfs_dir, city_code)
    if not gtfs_paths:
        print(f"No GTFS files found for '{city_code}' in {gtfs_dir}")
        sys.exit(1)

    project_root = Path(__file__).parent.parent
    output_path = project_root / 'static' / 'data' / city_code / 'routes.geojson'

    generate_routes_geojson(gtfs_paths, output_path)


if __name__ == '__main__':
    main()
