#!/usr/bin/env python3
"""
Main script to process GTFS data and split cache files.
Calls processing functions directly to avoid reloading GTFS data.
"""

import sys
import shutil
from pathlib import Path

from utils import (load_multiple_gtfs_data, discover_gtfs_files, calculate_stop_connectivity,
                   save_json, crop_gtfs_by_radius)
from process_wards import process_wards
from process_hexagons import process_hexagons
from process_isochrones import process_stop_isochrones
from generate_routes_geojson import generate_routes_geojson


def remove_file(file_path: Path):
    """Remove a file if it exists."""
    if file_path.exists():
        file_path.unlink()
        print(f"Removed: {file_path}")


def remove_directory(dir_path: Path):
    """Remove a directory and all its contents if it exists."""
    if dir_path.exists() and dir_path.is_dir():
        shutil.rmtree(dir_path)
        print(f"Removed directory: {dir_path}")


def save_basic_gtfs_data(routes: list, trips: list, stop_times_by_trip: dict,
                         stops_data: dict, output_dir: Path):
    """Save basic GTFS data (stops, routes, stop_connectivity)."""
    print("\n" + "="*50)
    print("Saving basic GTFS data...")
    print("="*50)

    # Save stops
    save_json(stops_data, output_dir / 'stops.json')

    # Save routes
    save_json({route['route_id']: {
        'route_id': route['route_id'],
        'route_short_name': route.get('route_short_name', ''),
        'route_long_name': route.get('route_long_name', '')
    } for route in routes}, output_dir / 'routes.json')

    # Calculate and save stop connectivity
    print("Calculating stop-to-stop connectivity...")
    from utils import build_trip_stop_ids
    trip_stop_ids = build_trip_stop_ids(stop_times_by_trip)
    stop_connectivity = calculate_stop_connectivity(trip_stop_ids, stop_times_by_trip)
    save_json(stop_connectivity, output_dir / 'stop_connectivity.json')


def split_connectivity_matrix(matrix_path: Path, chunks_dir: Path):
    """Split a connectivity matrix into per-region chunks and write a meta file
    holding the precomputed global max score.

    This lets the frontend load only the selected region's connectivity row on
    demand (instead of the whole matrix up front), and read the global max from
    a tiny file instead of scanning the full matrix.
    """
    import json
    from split import split_cache_file

    if not matrix_path.exists():
        print(f"Warning: {matrix_path} not found, skipping connectivity chunking...")
        return

    with open(matrix_path) as f:
        matrix = json.load(f)

    global_max = 0
    for row in matrix.values():
        for score in row.values():
            if score > global_max:
                global_max = score

    split_cache_file(matrix_path, chunks_dir)
    save_json({'globalMaxScore': global_max or 1}, chunks_dir / 'meta.json')
    print(f"Chunked {matrix_path.name}: globalMaxScore={global_max}")


def split_cache_files(data_dir: Path):
    """Split large cache files into chunks."""
    from split import split_cache_file

    routes_cache = data_dir / 'routes_cache.json'
    h3_routes_cache = data_dir / 'h3_routes_cache.json'
    routes_chunks_dir = data_dir / 'routes_cache_chunks'
    h3_routes_chunks_dir = data_dir / 'h3_routes_cache_chunks'

    if routes_cache.exists():
        split_cache_file(routes_cache, routes_chunks_dir)
    else:
        print(f"Warning: {routes_cache} not found, skipping...")

    if h3_routes_cache.exists():
        split_cache_file(h3_routes_cache, h3_routes_chunks_dir)
    else:
        print(f"Warning: {h3_routes_cache} not found, skipping...")

    # Chunk connectivity matrices so they load per-region on demand
    split_connectivity_matrix(data_dir / 'connectivity_matrix.json',
                              data_dir / 'connectivity_chunks')
    split_connectivity_matrix(data_dir / 'h3_connectivity_matrix.json',
                              data_dir / 'h3_connectivity_chunks')


def cleanup_cache_files(data_dir: Path):
    """Remove unneeded cache files after processing."""
    routes_cache = data_dir / 'routes_cache.json'
    h3_routes_cache = data_dir / 'h3_routes_cache.json'
    stop_isochrones = data_dir / 'stop_isochrones.json'
    isochrone_chunks_dir = data_dir / 'isochrone_chunks'
    isochrone_cache_dir = data_dir / 'isochrone_cache'
    
    # Remove routes cache files (already chunked)
    remove_file(routes_cache)
    remove_file(h3_routes_cache)

    # Remove full connectivity matrices (now chunked per-region)
    remove_file(data_dir / 'connectivity_matrix.json')
    remove_file(data_dir / 'h3_connectivity_matrix.json')

    # Remove intermediate artifacts that the frontend never fetches
    remove_file(data_dir / 'stops.json')
    remove_file(data_dir / 'stop_connectivity.json')
    remove_file(data_dir / 'h3_hexagon_stops.json')
    remove_file(data_dir / 'ward_stops.json')
    
    # Remove isochrones if chunked
    if stop_isochrones.exists() and isochrone_chunks_dir.exists() and (isochrone_chunks_dir / 'index.json').exists():
        remove_file(stop_isochrones)
    
    # Remove isochrone cache directory
    remove_directory(isochrone_cache_dir)


def main():
    """Main entry point."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # Optional flag: skip isochrone generation (not consumed by the frontend)
    skip_isochrones = '--skip-isochrones' in sys.argv
    sys.argv = [arg for arg in sys.argv if arg != '--skip-isochrones']

    def extract_value_flag(name: str, default: int) -> int:
        """Pull `--name <int>` out of sys.argv, returning its value or default."""
        if name in sys.argv:
            idx = sys.argv.index(name)
            value = int(sys.argv[idx + 1])
            del sys.argv[idx:idx + 2]
            return value
        return default

    def extract_float_flag(name: str, default):
        """Pull `--name <float>` out of sys.argv, returning its value or default."""
        if name in sys.argv:
            idx = sys.argv.index(name)
            value = float(sys.argv[idx + 1])
            del sys.argv[idx:idx + 2]
            return value
        return default

    def extract_str_flag(name: str, default):
        """Pull `--name <str>` out of sys.argv, returning its value or default."""
        if name in sys.argv:
            idx = sys.argv.index(name)
            value = sys.argv[idx + 1]
            del sys.argv[idx:idx + 2]
            return value
        return default

    # --hex-buffer N: rings of hexagons to keep around stops (>= max osmosis ring)
    # --prune-below N: drop connectivity scores below N (those that render the
    #                  same color as "no connectivity"); 0 disables pruning
    hex_buffer = extract_value_flag('--hex-buffer', 2)
    prune_below = extract_value_flag('--prune-below', 0)

    # --crop-radius-km R --crop-center "<lon>,<lat>": restrict all derived data
    #   to stops within R km of the center, shrinking the map extent and outputs.
    crop_radius_km = extract_float_flag('--crop-radius-km', None)
    crop_center_arg = extract_str_flag('--crop-center', None)
    crop_center = None
    if crop_radius_km and crop_center_arg:
        lon_str, lat_str = crop_center_arg.split(',')
        crop_center = (float(lon_str), float(lat_str))
    elif crop_radius_km and not crop_center_arg:
        print("Error: --crop-radius-km requires --crop-center \"<lon>,<lat>\"")
        sys.exit(1)

    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: python parse.py <gtfs_dir> [city_code] [<geojson_path>] [<hexagon_resolution>]")
        print("       [--hex-buffer N] [--prune-below N] [--crop-radius-km R --crop-center \"<lon>,<lat>\"]")
        print("Example: python parse.py scripts/gtfs blr scripts/geojson/blr.geojson 8")
        print("BLR (35km crop):  python parse.py scripts/gtfs blr scripts/geojson/blr.geojson 8 \\")
        print("                    --crop-radius-km 35 --crop-center \"77.5946,12.9716\" \\")
        print("                    --prune-below 50 --skip-isochrones")
        print("Discovers all GTFS files matching <city_code>.zip and <city_code>-*.zip in <gtfs_dir>")
        sys.exit(1)

    gtfs_dir = Path(sys.argv[1])
    city_code = sys.argv[2] if len(sys.argv) > 2 else 'blr'

    # Parse optional arguments
    geojson_path = None
    hexagon_resolution = 8

    if len(sys.argv) > 3:
        arg3 = sys.argv[3]
        if arg3.isdigit():
            hexagon_resolution = int(arg3)
        else:
            geojson_path = Path(arg3)

    if len(sys.argv) > 4:
        arg4 = sys.argv[4]
        if arg4.isdigit():
            hexagon_resolution = int(arg4)
        elif geojson_path is None:
            geojson_path = Path(arg4)

    # Support passing a single zip file directly for backwards compatibility
    if gtfs_dir.is_file() and gtfs_dir.suffix == '.zip':
        gtfs_paths = [gtfs_dir]
    elif gtfs_dir.is_dir():
        gtfs_paths = discover_gtfs_files(gtfs_dir, city_code)
    else:
        print(f"Error: GTFS path not found: {gtfs_dir}")
        sys.exit(1)

    if not gtfs_paths:
        print(f"Error: No GTFS files found for city '{city_code}' in {gtfs_dir}")
        sys.exit(1)

    print(f"Found {len(gtfs_paths)} GTFS file(s): {', '.join(p.name for p in gtfs_paths)}")
    
    # City-specific data directory
    data_dir = project_root / 'static' / 'data' / city_code
    data_dir.mkdir(parents=True, exist_ok=True)
    
    if geojson_path and not geojson_path.exists():
        print(f"Warning: GeoJSON file not found: {geojson_path}, skipping ward processing")
        geojson_path = None
    
    # Step 0: Load GTFS data once
    print("\n" + "="*60)
    print(f"STEP 0: Loading GTFS data for {city_code}")
    print("="*60)
    print("\n" + "="*50)
    print(f"Loading GTFS data from {len(gtfs_paths)} file(s)...")
    print("="*50)
    gtfs_data, routes, trips, stop_times_by_trip, stops_data = load_multiple_gtfs_data(gtfs_paths)

    if crop_center and crop_radius_km:
        routes, trips, stop_times_by_trip, stops_data = crop_gtfs_by_radius(
            crop_center, crop_radius_km, routes, trips, stop_times_by_trip, stops_data)
        gtfs_data = {'routes': routes, 'trips': trips,
                     'stop_times': stop_times_by_trip, 'stops': stops_data}

    save_basic_gtfs_data(routes, trips, stop_times_by_trip, stops_data, data_dir)
    
    # Step 1: Process wards (if GeoJSON provided)
    if geojson_path:
        print("\n" + "="*60)
        print(f"STEP 1: Processing wards for {city_code}")
        print("="*60)
        process_wards(geojson_path, data_dir, routes, trips, stop_times_by_trip,
                      stops_data)
    
    # Step 2: Process hexagons
    print("\n" + "="*60)
    print(f"STEP 2: Processing hexagons for {city_code}")
    print("="*60)
    process_hexagons(data_dir, routes, trips, stop_times_by_trip, stops_data,
                     hexagon_resolution, buffer_rings=hex_buffer, prune_below=prune_below)
    
    # Step 3: Process isochrones
    if skip_isochrones:
        print("\n" + "="*60)
        print(f"STEP 3: Skipping isochrones for {city_code} (--skip-isochrones)")
        print("="*60)
    else:
        print("\n" + "="*60)
        print(f"STEP 3: Processing isochrones for {city_code}")
        print("="*60)
        isochrone_cache_dir = data_dir / 'isochrone_cache'
        process_stop_isochrones(
            gtfs_data, data_dir, routes, trips, stop_times_by_trip, stops_data,
            time_intervals=[600, 1500, 3300, 6900],
            buffer_meters=500,
            cache_dir=isochrone_cache_dir
        )
        # Clean up isochrone cache directory immediately after processing
        remove_directory(isochrone_cache_dir)
    
    # Step 4: Generate routes GeoJSON
    print("\n" + "="*60)
    print(f"STEP 4: Generating routes GeoJSON for {city_code}")
    print("="*60)
    generate_routes_geojson(gtfs_paths, data_dir / 'routes.geojson',
                            crop_center=crop_center, crop_radius_km=crop_radius_km)

    # Step 5: Split cache files
    print("\n" + "="*60)
    print("STEP 5: Splitting cache files")
    print("="*60)
    split_cache_files(data_dir)

    # Step 6: Cleanup unneeded cache files
    print("\n" + "="*60)
    print("STEP 6: Cleaning up cache files")
    print("="*60)
    cleanup_cache_files(data_dir)
    
    print("\n" + "="*60)
    print(f"All steps completed successfully for {city_code}!")
    print("="*60)


if __name__ == '__main__':
    main()
