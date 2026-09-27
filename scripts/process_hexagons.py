#!/usr/bin/env python3
"""
Process H3 hexagon-based data from GTFS.
"""

import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set

from utils import (
    save_json, save_geojson, H3_AVAILABLE, H3_API_NEW,
    map_stops_to_h3_hexagons, generate_hexagons_near_stops,
    generate_hexagons_for_convex_hull, cells_to_union_geometry,
    calculate_connectivity_matrix, filter_hexagons,
    build_routes_cache, create_h3_geojson,
    cell_to_latlng
)


def _grid_disk(cell: str, k: int) -> set:
    """Get all h3 cells within distance k (inclusive), handling API versions."""
    import h3
    if H3_API_NEW:
        return set(h3.grid_disk(cell, k))
    return set(h3.k_ring(cell, k))


OSMOSIS_FACTORS = {
    8: ((1, 0.1), (2, 0.01), (3, 0.001)),
    9: ((1, 0.5), (2, 0.25), (3, 0.1)),
}


def apply_osmosis(connectivity_matrix: Dict[str, Dict[str, int]],
                  hexagon_set: set,
                  resolution: int = 8) -> Dict[str, Dict[str, int]]:
    """Apply spatial osmosis to spread connectivity scores to nearby hexagons.

    Decay factors vary by hexagon resolution since smaller hexagons (higher
    resolution) need stronger osmosis to cover equivalent geographic area.
    """
    decay_factors = OSMOSIS_FACTORS.get(resolution, OSMOSIS_FACTORS[8])

    # Collect all target hexagons that have non-zero scores
    targets_with_scores: Set[str] = set()
    for scores in connectivity_matrix.values():
        targets_with_scores.update(scores.keys())

    # Pre-compute rings at each distance for targets only
    target_rings: Dict[str, Dict[int, set]] = {}
    for hex_id in targets_with_scores:
        prev_disk = set()
        rings = {}
        for d in range(0, 4):
            disk = _grid_disk(hex_id, d)
            rings[d] = (disk - prev_disk) & hexagon_set
            prev_disk = disk
        target_rings[hex_id] = rings

    # Apply osmosis per source row
    for source_id, base_scores in connectivity_matrix.items():
        if not base_scores:
            continue

        osmosis: Dict[str, float] = defaultdict(float)
        for target_id, score in list(base_scores.items()):
            rings = target_rings.get(target_id)
            if not rings:
                continue
            for d, factor in decay_factors:
                for neighbor_id in rings[d]:
                    if neighbor_id != source_id:
                        osmosis[neighbor_id] += score * factor

        for target_id, osmosis_score in osmosis.items():
            rounded = round(osmosis_score)
            if rounded > 0:
                base_scores[target_id] = base_scores.get(target_id, 0) + rounded

    return connectivity_matrix


def process_hexagons(output_dir: Path, routes: list, trips: list,
                     stop_times_by_trip: Dict[str, list], stops_data: Dict[str, Dict],
                     resolution: int = 8, buffer_rings: int = 2,
                     prune_below: int = 0, add_background: bool = True) -> None:
    """Process H3 hexagon-based data."""
    if not H3_AVAILABLE:
        print("\nSkipping H3 hexagon processing (h3 library not available)")
        return
    
    print("\n" + "="*50)
    print(f"Processing H3 hexagons (resolution {resolution})...")
    print("="*50)
    
    # Convert stops_data to iterator format
    stops_iterator = [
        {'stop_id': stop_id, 'stop_lat': str(stop['stop_lat']), 'stop_lon': str(stop['stop_lon'])}
        for stop_id, stop in stops_data.items()
    ]
    
    # Get all hexagons near stops (stop cells + buffer rings)
    print(f"Generating hexagons near stops (buffer={buffer_rings} rings)...")
    all_hexagons = generate_hexagons_near_stops(
        iter(stops_iterator), resolution=resolution, buffer_rings=buffer_rings
    )
    print(f"Found {len(all_hexagons)} hexagons near stops")
    
    # Map stops to hexagons
    print("Mapping stops to hexagons...")
    hexagon_stops, hexagon_metadata = map_stops_to_h3_hexagons(
        iter(stops_iterator), resolution=resolution
    )
    print(f"Mapped stops to {len(hexagon_stops)} h3 hexagons with stops")
    
    # Pre-compute trip data
    from utils import build_trip_stop_ids, build_trip_to_route, build_routes_dict
    
    trip_stop_ids = build_trip_stop_ids(stop_times_by_trip)
    
    # Identify hexagons with trips
    stops_with_trips = set()
    for trip_stops in trip_stop_ids.values():
        stops_with_trips.update(trip_stops)
    hexagons_with_trips = {hex_id for hex_id, stop_set in hexagon_stops.items() 
                          if stop_set & stops_with_trips}
    print(f"Found {len(hexagons_with_trips)} hexagons with trips")
    
    # Add buffer hexagons (near stops) that have no stops of their own
    print("Using all hexagons near stops...")
    for hex_id in all_hexagons:
        if hex_id not in hexagon_stops:
            hexagon_stops[hex_id] = set()
            center = cell_to_latlng(hex_id)
            hexagon_metadata[hex_id] = {
                'centroid': [center[1], center[0]],
                'stop_count': 0
            }
    
    print(f"Total hexagons (including contiguous): {len(hexagon_stops)}")
    
    # Calculate connectivity
    print("Calculating h3 hexagon connectivity matrix...")
    h3_connectivity_matrix, h3_trip_hexagons, h3_stop_to_hexagons = calculate_connectivity_matrix(
        hexagon_stops, trip_stop_ids
    )
    
    # Ensure all hexagons are in connectivity matrix
    for hex_id in hexagon_stops.keys():
        if hex_id not in h3_connectivity_matrix:
            h3_connectivity_matrix[hex_id] = {}
    
    # Filter hexagons
    hexagon_stops, hexagon_metadata, h3_connectivity_matrix = filter_hexagons(
        hexagon_stops, hexagon_metadata, h3_connectivity_matrix, hexagons_with_trips
    )
    
    print(f"Final hexagon count: {len(hexagon_stops)}")

    # Apply osmosis to spread connectivity to nearby hexagons
    print("Applying osmosis to connectivity matrix...")
    h3_connectivity_matrix = apply_osmosis(h3_connectivity_matrix, set(hexagon_stops.keys()), resolution)
    print("Osmosis complete")

    # Prune connectivity scores that render the same color as "no connectivity".
    # These (e.g. < lowest distinct color threshold) are visually redundant but
    # dominate the matrix size, so dropping them shrinks the payload with no
    # change to the map.
    if prune_below and prune_below > 1:
        before = sum(len(r) for r in h3_connectivity_matrix.values())
        for src, row in h3_connectivity_matrix.items():
            h3_connectivity_matrix[src] = {d: s for d, s in row.items() if s >= prune_below}
        after = sum(len(r) for r in h3_connectivity_matrix.values())
        print(f"Pruned connectivity entries < {prune_below}: {before:,} -> {after:,}")

    # Save connectivity matrix
    save_json(h3_connectivity_matrix, output_dir / 'h3_connectivity_matrix.json')
    
    # Save hexagon stops
    save_json({hex_id: list(stop_set) for hex_id, stop_set in hexagon_stops.items()},
              output_dir / 'h3_hexagon_stops.json')
    
    # Build hexagons list
    print("Building hexagons list...")
    stop_trip_count = defaultdict(int)
    for trip_stop_times in stop_times_by_trip.values():
        for st in trip_stop_times:
            stop_trip_count[st['stop_id']] += 1
    
    hexagons_list = []
    for hex_id, stop_set in hexagon_stops.items():
        metadata = hexagon_metadata.get(hex_id, {})
        largest_stop_id = max(stop_set, key=lambda sid: stop_trip_count.get(sid, 0), default=None)
        hexagon_name = stops_data.get(largest_stop_id, {}).get('stop_name', '') if largest_stop_id else hex_id
        
        hexagons_list.append({
            'id': hex_id,
            'name': hexagon_name or hex_id,
            'centroid': metadata.get('centroid', [0, 0]),
            'stop_count': metadata.get('stop_count', len(stop_set))
        })
    
    save_json(hexagons_list, output_dir / 'hexagons.json')
    print(f"Saved {len(hexagons_list)} hexagons to hexagons.json")
    
    # Pre-compute hexagon routes cache
    print("Pre-computing hexagon routes cache...")
    trip_to_route = build_trip_to_route(trips)
    routes_dict = build_routes_dict(routes)
    h3_routes_cache = build_routes_cache(
        hexagon_stops, routes_dict, trip_to_route, stop_times_by_trip,
        h3_trip_hexagons, h3_stop_to_hexagons, progress_interval=50
    )
    save_json(h3_routes_cache, output_dir / 'h3_routes_cache.json')
    
    # Generate GeoJSON
    print("Generating h3 hexagon GeoJSON...")
    h3_geojson = create_h3_geojson(list(hexagon_stops.keys()))

    # Background fill: union the rest of the convex hull (outside the kept
    # hexagons) into a single feature so the map keeps the full filled look
    # without thousands of empty hexagon features. It carries no connectivity
    # data, so it always renders as the "no connectivity" color.
    if add_background:
        print("Building background fill from remaining convex-hull hexagons...")
        hull_cells = generate_hexagons_for_convex_hull(iter(stops_iterator), resolution=resolution)
        far_cells = hull_cells - set(hexagon_stops.keys())
        bg_geometry = cells_to_union_geometry(far_cells)
        if bg_geometry:
            h3_geojson['features'].append({
                'type': 'Feature',
                'properties': {'hex_id': 'background', 'is_background': True},
                'geometry': bg_geometry
            })
            print(f"Added background fill polygon covering {len(far_cells)} hexagons")

    save_geojson(h3_geojson, output_dir / 'h3_hexagons.geojson')
    print(f"Generated GeoJSON with {len(h3_geojson['features'])} hexagon features")
    print("H3 hexagon processing complete!")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python process_hexagons.py <gtfs_path> <output_dir> [resolution]")
        sys.exit(1)
    
    gtfs_zip = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    resolution = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    
    if not gtfs_zip.exists():
        print(f"Error: GTFS file not found: {gtfs_zip}")
        sys.exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load GTFS data
    from utils import load_gtfs_data
    
    gtfs_data, routes, trips, stop_times_by_trip, stops_data = load_gtfs_data(gtfs_zip)
    
    # Process hexagons
    process_hexagons(output_dir, routes, trips, stop_times_by_trip, 
                     stops_data, resolution)


if __name__ == '__main__':
    main()
