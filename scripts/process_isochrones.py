#!/usr/bin/env python3
"""
Process isochrone data from GTFS using schedule-based reachability analysis.
Uses the old method that builds stop connectivity from trip schedules.
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Optional

from utils import (
    save_json,
    chunk_isochrones,
    build_stop_graph,
    generate_stop_isochrones
)


def process_stop_isochrones(gtfs_data: Dict,
                            output_dir: Path,
                            routes: List[Dict],
                            trips: List[Dict],
                            stop_times_by_trip: Dict[str, List[Dict]],
                            stops_data: Dict[str, Dict],
                            time_intervals: List[int] = [600, 1500, 3300, 6900],
                            buffer_meters: float = 500,
                            cache_dir: Optional[Path] = None) -> None:
    """Process and generate isochrones for all stops using schedule-based method.
    
    This method builds a stop connectivity graph from GTFS trip schedules
    and calculates reachable stops within time limits, then creates polygons
    from those reachable stops.
    
    Args:
        gtfs_data: Pre-loaded GTFS data dict (for backward compatibility)
        output_dir: Directory to save output files
        routes: List of route dictionaries
        trips: List of trip dictionaries
        stop_times_by_trip: Dict mapping trip_id to list of stop_time dicts
        stops_data: Dict mapping stop_id to stop data
        time_intervals: List of time intervals in seconds
        buffer_meters: Buffer distance in meters for isochrone polygons
        cache_dir: Optional directory for caching individual stop isochrones
    """
    print("\n" + "="*50)
    print("Processing stop isochrones using schedule-based method...")
    print("="*50)
    
    # Build stop graph from trip schedules
    print("Building stop connectivity graph from GTFS schedules...")
    stop_graph, stop_departures = build_stop_graph(stop_times_by_trip, trips, stops_data)
    print(f"Built graph with {len(stop_graph)} stops and {sum(len(neighbors) for neighbors in stop_graph.values())} connections")
    
    # Create cache directory if specified
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Process stops in batches
    all_stops = list(stops_data.keys())
    total_stops = len(all_stops)
    batch_size = max(100, total_stops // 20)
    
    all_isochrones: Dict[str, Dict[int, Optional[Dict]]] = {}
    
    print(f"Generating isochrones for {total_stops} stops...")
    for i, stop_id in enumerate(all_stops):
        if (i + 1) % batch_size == 0:
            print(f"Processed {i + 1}/{total_stops} stops ({100 * (i + 1) // total_stops}%)")
        
        # Check cache first
        if cache_dir:
            cache_file = cache_dir / f"{stop_id}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, 'r') as f:
                        cached_data = json.load(f)
                        all_isochrones[stop_id] = {
                            int(k): v for k, v in cached_data.items()
                        }
                        continue
                except Exception:
                    pass
        
        # Generate isochrones for this stop
        isochrones = generate_stop_isochrones(
            stop_id,
            stop_graph,
            stop_departures,
            stops_data,
            time_intervals,
            buffer_meters
        )
        
        all_isochrones[stop_id] = isochrones
        
        # Save to cache
        if cache_dir:
            try:
                cache_file = cache_dir / f"{stop_id}.json"
                with open(cache_file, 'w') as f:
                    json.dump(isochrones, f)
            except Exception:
                pass
    
    # Save aggregated isochrones
    output_data = {}
    for stop_id, isochrones in all_isochrones.items():
        output_data[stop_id] = {}
        for time_interval, polygon in isochrones.items():
            if polygon:
                output_data[stop_id][str(time_interval)] = polygon
    
    # Check if we should chunk the output
    output_file = output_dir / 'stop_isochrones.json'
    test_json = json.dumps(output_data, separators=(',', ':'))
    estimated_size_mb = len(test_json.encode('utf-8')) / (1024 * 1024)
    
    if estimated_size_mb > 10:
        print(f"Output size ({estimated_size_mb:.2f} MB) exceeds 10MB, chunking...")
        chunk_isochrones(output_data, output_dir)
        print("Isochrone chunking complete!")
    else:
        save_json(output_data, output_file)
        print(f"Saved isochrones for {len(output_data)} stops ({estimated_size_mb:.2f} MB)")
    
    print("Stop isochrone processing complete!")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python process_isochrones.py <gtfs_path> <output_dir>")
        sys.exit(1)
    
    gtfs_zip = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    
    if not gtfs_zip.exists():
        print(f"Error: GTFS file not found: {gtfs_zip}")
        sys.exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load GTFS data
    from utils import load_gtfs_data
    
    gtfs_data, routes, trips, stop_times_by_trip, stops_data = load_gtfs_data(gtfs_zip)
    
    # Process isochrones
    isochrone_cache_dir = output_dir / 'isochrone_cache'
    process_stop_isochrones(
        gtfs_data, output_dir, routes, trips, stop_times_by_trip, stops_data,
        time_intervals=[600, 1500, 3300, 6900],  # 10min, 25min, 55min, 115min
        buffer_meters=500,
        cache_dir=isochrone_cache_dir
    )
    
    # Clean up isochrone cache directory (not needed by frontend)
    if isochrone_cache_dir.exists():
        import shutil
        shutil.rmtree(isochrone_cache_dir)
        print(f"Removed isochrone cache directory: {isochrone_cache_dir}")


if __name__ == '__main__':
    main()
