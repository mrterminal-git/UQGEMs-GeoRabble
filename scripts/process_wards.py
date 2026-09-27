#!/usr/bin/env python3
"""
Process ward-based data from GTFS and GeoJSON.
"""

import sys
from pathlib import Path
from typing import Dict, Set

from utils import (
    load_geojson, save_json, save_geojson,
    map_stops_to_wards, calculate_connectivity_matrix,
    calculate_polygon_centroid, build_routes_cache
)


def process_wards(geojson_path: Path, output_dir: Path,
                  routes: list, trips: list, stop_times_by_trip: Dict[str, list],
                  stops_data: Dict[str, Dict]) -> Dict[str, Set[str]]:
    """Process ward-based data using optimized stop connectivity aggregation."""
    print("\n" + "="*50)
    print("Processing wards...")
    print("="*50)
    
    # Load GeoJSON
    geojson = load_geojson(str(geojson_path))
    
    # Map stops to wards - convert stops_data to iterator format
    stops_iterator = [
        {'stop_id': stop_id, 'stop_lat': str(stop['stop_lat']), 'stop_lon': str(stop['stop_lon'])}
        for stop_id, stop in stops_data.items()
    ]
    print("Mapping stops to wards...")
    ward_stops = map_stops_to_wards(iter(stops_iterator), geojson)
    print(f"Mapped stops to {len(ward_stops)} wards")
    
    # Save basic data
    save_json({ward_id: list(stop_set) for ward_id, stop_set in ward_stops.items()},
              output_dir / 'ward_stops.json')
    
    # Save ward GeoJSON
    save_geojson(geojson, output_dir / 'wards.geojson')
    
    # Pre-compute trip data
    print("Pre-computing data structures...")
    from utils import build_trip_stop_ids, build_trip_to_route, build_routes_dict
    
    trip_stop_ids = build_trip_stop_ids(stop_times_by_trip)
    trip_to_route = build_trip_to_route(trips)
    routes_dict = build_routes_dict(routes)
    
    # Calculate connectivity - count each trip once per region pair
    print("Calculating connectivity matrix...")
    connectivity_matrix, trip_regions_result, stop_to_regions_result = calculate_connectivity_matrix(
        ward_stops, trip_stop_ids
    )
    
    # Ensure all wards are in the connectivity matrix
    for ward_id in ward_stops.keys():
        if ward_id not in connectivity_matrix:
            connectivity_matrix[ward_id] = {}
    
    save_json(connectivity_matrix, output_dir / 'connectivity_matrix.json')
    
    # Build wards list with metadata
    print("Building wards list...")
    wards_list = []
    for feature in geojson.get('features', []):
        if feature['geometry']['type'] != 'Polygon':
            continue
        
        ward_id = feature['properties'].get('namecol', '')
        if not ward_id:
            continue
        
        # Calculate centroid from polygon
        polygon_coords = feature['geometry']['coordinates']
        centroid_lon, centroid_lat = calculate_polygon_centroid(polygon_coords)
        
        # Get stop count
        stop_count = len(ward_stops.get(ward_id, set()))
        
        wards_list.append({
            'id': ward_id,
            'name': ward_id,
            'centroid': [centroid_lon, centroid_lat],
            'stop_count': stop_count
        })
    
    # Sort by ward ID for consistency
    wards_list.sort(key=lambda w: w['id'])
    save_json(wards_list, output_dir / 'wards.json')
    print(f"Saved {len(wards_list)} wards to wards.json")
    
    # Use trip_regions and stop_to_regions from connectivity calculation
    stop_to_regions = {k: v for k, v in stop_to_regions_result.items()}
    trip_regions = trip_regions_result
    
    # Pre-compute routes cache
    print("Pre-computing routes cache...")
    routes_cache = build_routes_cache(
        ward_stops, routes_dict, trip_to_route, stop_times_by_trip,
        trip_regions, stop_to_regions, progress_interval=10
    )
    save_json(routes_cache, output_dir / 'routes_cache.json')
    
    print("Ward processing complete!")
    return ward_stops


def main():
    """Main entry point (for standalone execution)."""
    if len(sys.argv) < 4:
        print("Usage: python process_wards.py <gtfs_path> <geojson_path> <output_dir>")
        sys.exit(1)
    
    from utils import load_gtfs_data

    gtfs_zip = Path(sys.argv[1])
    geojson_path = Path(sys.argv[2])
    output_dir = Path(sys.argv[3])

    if not gtfs_zip.exists():
        print(f"Error: GTFS file not found: {gtfs_zip}")
        sys.exit(1)

    if not geojson_path.exists():
        print(f"Error: GeoJSON file not found: {geojson_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load GTFS data
    gtfs_data, routes, trips, stop_times_by_trip, stops_data = load_gtfs_data(gtfs_zip)

    # Process wards
    process_wards(geojson_path, output_dir, routes, trips,
                  stop_times_by_trip, stops_data)


if __name__ == '__main__':
    main()
