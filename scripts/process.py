#!/usr/bin/env python3
"""
Legacy wrapper script for backward compatibility.
This script now delegates to the modular processing scripts.
For new code, use parse.py or call the individual scripts directly.
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Main entry point - delegates to modular scripts."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Parse arguments (same as before)
    if len(sys.argv) < 3:
        print("Usage: python process.py <gtfs_dir_or_zip> <city_code> [geojson_path] [hexagon_resolution]")
        print("Example: python process.py scripts/gtfs blr static/geojson/blr.geojson 8")
        print("Example: python process.py scripts/gtfs/chennai.zip chennai 8")
        print("\nNote: This script is a legacy wrapper. Consider using parse.py instead.")
        sys.exit(1)

    gtfs_path = Path(sys.argv[1])
    city_code = sys.argv[2]

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

    from utils import load_multiple_gtfs_data, discover_gtfs_files, calculate_stop_connectivity, save_json

    # Discover GTFS files
    if gtfs_path.is_file() and gtfs_path.suffix == '.zip':
        gtfs_paths = [gtfs_path]
    elif gtfs_path.is_dir():
        gtfs_paths = discover_gtfs_files(gtfs_path, city_code)
    else:
        print(f"Error: GTFS path not found: {gtfs_path}")
        sys.exit(1)

    if not gtfs_paths:
        print(f"Error: No GTFS files found for city '{city_code}' in {gtfs_path}")
        sys.exit(1)

    print(f"Found {len(gtfs_paths)} GTFS file(s): {', '.join(p.name for p in gtfs_paths)}")

    output_dir = project_root / 'static' / 'data' / city_code
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save basic GTFS data
    print("Loading GTFS data...")
    gtfs_data, routes, trips, stop_times_by_trip, stops_data = load_multiple_gtfs_data(gtfs_paths)
    
    save_json(stops_data, output_dir / 'stops.json')
    save_json({route['route_id']: {
        'route_id': route['route_id'],
        'route_short_name': route.get('route_short_name', ''),
        'route_long_name': route.get('route_long_name', '')
    } for route in routes}, output_dir / 'routes.json')
    
    # Calculate stop connectivity
    print("Calculating stop-to-stop connectivity...")
    from utils import build_trip_stop_ids
    trip_stop_ids = build_trip_stop_ids(stop_times_by_trip)
    stop_connectivity = calculate_stop_connectivity(trip_stop_ids, stop_times_by_trip)
    save_json(stop_connectivity, output_dir / 'stop_connectivity.json')
    
    # Process wards if GeoJSON provided
    if geojson_path and geojson_path.exists():
        from process_wards import process_wards
        process_wards(geojson_path, output_dir, routes, trips, 
                      stop_times_by_trip, stops_data, stop_connectivity)
    else:
        print("GeoJSON not provided or not found, skipping ward processing")
    
    # Process hexagons
    from process_hexagons import process_hexagons
    process_hexagons(output_dir, routes, trips, stop_times_by_trip, 
                     stops_data, hexagon_resolution)
    
    # Process isochrones
    from process_isochrones import process_stop_isochrones
    isochrone_cache_dir = output_dir / 'isochrone_cache'
    process_stop_isochrones(
        gtfs_data, output_dir, routes, trips, stop_times_by_trip, stops_data,
        time_intervals=[600, 1500, 3300, 6900],
        buffer_meters=500,
        cache_dir=isochrone_cache_dir
    )
    
    # Clean up isochrone cache directory
    import shutil
    if isochrone_cache_dir.exists():
        shutil.rmtree(isochrone_cache_dir)
        print(f"Removed isochrone cache directory: {isochrone_cache_dir}")
    
    print("\nProcessing complete!")
    print(f"Output files saved to {output_dir}")


if __name__ == '__main__':
    main()
