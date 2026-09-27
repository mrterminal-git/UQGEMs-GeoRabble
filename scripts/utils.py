#!/usr/bin/env python3
"""
Common utilities for GTFS data processing.
Shared functionality for wards, hexagons, and isochrones processing.
"""

import zipfile
import json
import csv
import io
import math
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Iterator, Optional, Any

# H3 API compatibility
try:
    import h3
    H3_AVAILABLE = True
    H3_API_NEW = hasattr(h3, 'latlng_to_cell')
except ImportError:
    H3_AVAILABLE = False
    H3_API_NEW = False

# Convex hull calculation
try:
    from scipy.spatial import ConvexHull
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# Isochrone generation
try:
    from shapely.geometry import MultiPoint, Point, LineString
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    MultiPoint = None
    Point = None
    LineString = None

# NetworkX is no longer used - removed dependency


# ============================================================================
# I/O Utilities
# ============================================================================

def parse_csv_from_zip(zip_path: str, filename: str) -> Iterator[Dict]:
    """Parse a CSV file from a zip archive using streaming."""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        with zip_ref.open(filename) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))

def load_geojson(geojson_path: str) -> Dict:
    """Load GeoJSON file."""
    with open(geojson_path, 'r') as f:
        return json.load(f)

def sort_json_recursive(obj: Any) -> Any:
    """Recursively sort JSON-serializable objects for consistent output."""
    if isinstance(obj, dict):
        return {k: sort_json_recursive(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        if obj and (isinstance(obj[0], dict) or isinstance(obj[0], list)):
            if obj and isinstance(obj[0], dict):
                if all(isinstance(item, dict) and ('id' in item or 'route_id' in item) for item in obj):
                    sort_key = 'id' if 'id' in obj[0] else 'route_id'
                    return sorted([sort_json_recursive(item) for item in obj], 
                                 key=lambda x: x.get(sort_key, ''))
                elif all(isinstance(item, dict) for item in obj):
                    return sorted([sort_json_recursive(item) for item in obj],
                                 key=lambda x: json.dumps(x, sort_keys=True))
            return [sort_json_recursive(item) for item in obj]
        return obj
    else:
        return obj

def round_coords(coords: Any, precision: int = 6) -> Any:
    """Recursively round GeoJSON coordinate numbers to `precision` decimals.

    ~6 decimals is roughly 10cm, far beyond what the map renders, so trimming
    the default sub-micron precision shrinks geometry files substantially.
    """
    if isinstance(coords, (int, float)):
        return round(coords, precision)
    if isinstance(coords, list):
        return [round_coords(c, precision) for c in coords]
    return coords


def round_geojson_precision(geojson: Dict, precision: int = 6) -> Dict:
    """Round all feature-geometry coordinates in a GeoJSON object in place."""
    for feature in geojson.get('features', []):
        geometry = feature.get('geometry')
        if geometry and 'coordinates' in geometry:
            geometry['coordinates'] = round_coords(geometry['coordinates'], precision)
    return geojson


def save_geojson(geojson: Dict, path: Path, precision: int = 6) -> None:
    """Round coordinate precision then save GeoJSON via save_json."""
    save_json(round_geojson_precision(geojson, precision), path)


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two lon/lat points in kilometres."""
    from math import radians, sin, cos, asin, sqrt
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def crop_gtfs_by_radius(
    center: Tuple[float, float], radius_km: float,
    routes: List[Dict], trips: List[Dict],
    stop_times_by_trip: Dict[str, List[Dict]], stops_data: Dict[str, Dict]
) -> Tuple[List[Dict], List[Dict], Dict[str, List[Dict]], Dict[str, Dict]]:
    """Restrict GTFS data to stops within `radius_km` of `center` (lon, lat).

    Drops out-of-range stops, prunes stop_times to kept stops (dropping trips
    left with <2 stops), and keeps only routes that still have a surviving trip.
    Everything downstream (hexagons, connectivity, route caches) then crops
    consistently because it all derives from these structures.
    """
    clon, clat = center
    kept_stops = {
        sid: s for sid, s in stops_data.items()
        if haversine_km(clon, clat, s['stop_lon'], s['stop_lat']) <= radius_km
    }

    new_stop_times: Dict[str, List[Dict]] = {}
    for trip_id, stop_times in stop_times_by_trip.items():
        filtered = [st for st in stop_times if st.get('stop_id') in kept_stops]
        if len(filtered) >= 2:
            new_stop_times[trip_id] = filtered

    kept_trip_ids = set(new_stop_times.keys())
    new_trips = [t for t in trips if t.get('trip_id') in kept_trip_ids]
    kept_route_ids = {t.get('route_id') for t in new_trips}
    new_routes = [r for r in routes if r.get('route_id') in kept_route_ids]

    print(
        f"Cropped GTFS to {radius_km}km radius: "
        f"stops {len(stops_data)}->{len(kept_stops)}, "
        f"trips {len(trips)}->{len(new_trips)}, "
        f"routes {len(routes)}->{len(new_routes)}"
    )
    return new_routes, new_trips, new_stop_times, kept_stops


def save_json(data: Any, path: Path) -> None:
    """Save data as compact JSON with sorted keys for consistent output."""
    try:
        sorted_data = sort_json_recursive(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(sorted_data, f, separators=(',', ':'))
        print(f"Saved {path}")
    except Exception as e:
        print(f"Error saving {path}: {e}")
        raise


# ============================================================================
# H3 Utilities
# ============================================================================

def latlng_to_cell(lat: float, lon: float, resolution: int) -> str:
    """Convert lat/lon to h3 cell ID."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    if H3_API_NEW:
        return h3.latlng_to_cell(lat, lon, resolution)
    return h3.geo_to_h3(lat, lon, resolution)

def cell_to_latlng(cell: str) -> Tuple[float, float]:
    """Convert h3 cell ID to lat/lon."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    if H3_API_NEW:
        return h3.cell_to_latlng(cell)
    return h3.h3_to_geo(cell)

def cell_to_boundary(cell: str) -> List[Tuple[float, float]]:
    """Get boundary of h3 cell."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    if H3_API_NEW:
        return h3.cell_to_boundary(cell)
    try:
        boundary = h3.h3_to_geo_boundary(cell, geo_json=True)
        return [(coord[1], coord[0]) for coord in boundary]
    except (TypeError, ValueError):
        return h3.h3_to_geo_boundary(cell)

def get_cell_neighbors(cell: str) -> Set[str]:
    """Get all neighboring cells of a given cell."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    if H3_API_NEW:
        if hasattr(h3, 'grid_disk'):
            return set(h3.grid_disk(cell, k=1)) - {cell}
        elif hasattr(h3, 'cell_to_neighbors'):
            return set(h3.cell_to_neighbors(cell))
        return set(h3.grid_ring(cell, k=1))
    return set(h3.k_ring(cell, 1)) - {cell}


# ============================================================================
# Geometry Utilities
# ============================================================================

def get_polygon_bounds(polygon_coords: List[List[List[float]]]) -> Tuple[float, float, float, float]:
    """Get bounding box of polygon (min_lon, min_lat, max_lon, max_lat)."""
    if not polygon_coords or not polygon_coords[0]:
        return (0, 0, 0, 0)
    ring = polygon_coords[0]
    return (min(p[0] for p in ring), min(p[1] for p in ring),
            max(p[0] for p in ring), max(p[1] for p in ring))

def point_in_polygon(lon: float, lat: float, polygon_coords: List[List[List[float]]], 
                     bounds: Optional[Tuple[float, float, float, float]] = None) -> bool:
    """Check if a point is inside a polygon using ray casting."""
    if not polygon_coords or not polygon_coords[0]:
        return False
    
    if bounds:
        min_lon, min_lat, max_lon, max_lat = bounds
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            return False
    
    ring = polygon_coords[0]
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def extract_stop_coordinates(stops: Iterator[Dict]) -> List[Tuple[float, float]]:
    """Extract (lat, lon) coordinates from stops."""
    return [
        (float(stop['stop_lat']), float(stop['stop_lon']))
        for stop in stops
        if all(k in stop for k in ['stop_lat', 'stop_lon'])
    ]

def calculate_convex_hull(stops: Iterator[Dict]) -> Optional[List[Tuple[float, float]]]:
    """Calculate convex hull of all stops. Returns list of (lat, lon) points."""
    if not SCIPY_AVAILABLE:
        return None
    
    coords = extract_stop_coordinates(stops)
    if len(coords) < 3:
        return None
    
    try:
        points = [(lon, lat) for lat, lon in coords]
        hull = ConvexHull(points)
        hull_points = [(points[i][1], points[i][0]) for i in hull.vertices]
        if hull_points[0] != hull_points[-1]:
            hull_points.append(hull_points[0])
        return hull_points
    except Exception as e:
        print(f"Warning: Convex hull calculation failed: {e}")
        return None

def get_bbox_from_coords(coords: List[Tuple[float, float]], buffer: float = 0.1) -> Tuple[float, float, float, float]:
    """Get bounding box from coordinates with optional buffer."""
    if not coords:
        return (0, 0, 0, 0)
    
    lats, lons = zip(*coords)
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    
    lat_buffer = (max_lat - min_lat) * buffer
    lon_buffer = (max_lon - min_lon) * buffer
    return (min_lat - lat_buffer, min_lon - lon_buffer, max_lat + lat_buffer, max_lon + lon_buffer)

def calculate_polygon_centroid(polygon_coords: List[List[List[float]]]) -> Tuple[float, float]:
    """Calculate centroid of a polygon as the average of all coordinates."""
    if not polygon_coords or not polygon_coords[0]:
        return (0.0, 0.0)
    
    ring = polygon_coords[0]
    coords = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    
    if not coords:
        return (0.0, 0.0)
    
    total_lon = sum(p[0] for p in coords)
    total_lat = sum(p[1] for p in coords)
    count = len(coords)
    
    return (total_lon / count, total_lat / count)


# ============================================================================
# Stop Mapping
# ============================================================================

def map_stops_to_wards(stops: Iterator[Dict], geojson: Dict) -> Dict[str, Set[str]]:
    """Map each stop to the ward(s) it belongs to."""
    ward_stops: Dict[str, Set[str]] = defaultdict(set)
    
    ward_polygons: Dict[str, Tuple[List[List[List[float]]], Tuple[float, float, float, float]]] = {}
    for feature in geojson.get('features', []):
        if feature['geometry']['type'] != 'Polygon':
            continue
        ward_id = feature['properties'].get('namecol', '')
        if ward_id:
            polygon_coords = feature['geometry']['coordinates']
            ward_polygons[ward_id] = (polygon_coords, get_polygon_bounds(polygon_coords))
    
    for stop in stops:
        try:
            lat, lon = float(stop['stop_lat']), float(stop['stop_lon'])
            stop_id = stop['stop_id']
        except (ValueError, KeyError):
            continue
        
        for ward_id, (polygon_coords, bounds) in ward_polygons.items():
            if point_in_polygon(lon, lat, polygon_coords, bounds):
                ward_stops[ward_id].add(stop_id)
    
    return dict(ward_stops)

def map_stops_to_h3_hexagons(stops: Iterator[Dict], resolution: int = 8) -> Tuple[Dict[str, Set[str]], Dict[str, Dict]]:
    """Map each stop to h3 hexagon(s) it belongs to."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    
    hexagon_stops: Dict[str, Set[str]] = defaultdict(set)
    
    for stop in stops:
        try:
            lat, lon = float(stop['stop_lat']), float(stop['stop_lon'])
            hex_id = latlng_to_cell(lat, lon, resolution)
            hexagon_stops[hex_id].add(stop['stop_id'])
        except (ValueError, KeyError):
            continue
    
    hexagon_metadata: Dict[str, Dict] = {}
    for hex_id, stop_set in hexagon_stops.items():
        center = cell_to_latlng(hex_id)
        hexagon_metadata[hex_id] = {
            'centroid': [center[1], center[0]],
            'stop_count': len(stop_set)
        }
    
    return dict(hexagon_stops), hexagon_metadata


# ============================================================================
# Connectivity Calculation
# ============================================================================

def calculate_stop_connectivity(trip_stop_ids: Dict[str, Set[str]],
                                stop_times_by_trip: Dict[str, List[Dict]]) -> Dict[str, Dict[str, int]]:
    """Calculate stop-to-stop connectivity matrix (number of connecting trips).
    
    Uses trip-based calculation from GTFS schedule data.
    For each trip, counts connections between all pairs of stops in sequence.
    """
    print("Calculating stop-to-stop connectivity from trip schedules...")
    stop_connectivity: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    
    for trip_id, stop_ids in trip_stop_ids.items():
        stop_list = list(stop_ids)
        trip_stop_times = stop_times_by_trip.get(trip_id, [])
        
        # Build stop sequence mapping for this trip
        stop_sequence: Dict[str, int] = {}
        for idx, st in enumerate(trip_stop_times):
            stop_sequence[st['stop_id']] = idx
        
        # Count connections between all pairs of stops in this trip
        for i, stop1_id in enumerate(stop_list):
            for stop2_id in stop_list[i + 1:]:
                seq1 = stop_sequence.get(stop1_id, -1)
                seq2 = stop_sequence.get(stop2_id, -1)
                if seq1 >= 0 and seq2 >= 0 and seq1 < seq2:
                    stop_connectivity[stop1_id][stop2_id] += 1
                    stop_connectivity[stop2_id][stop1_id] += 1
    
    print(f"Calculated connectivity for {len(stop_connectivity)} stops")
    return dict(stop_connectivity)

def calculate_connectivity_matrix_from_stops(region_stops: Dict[str, Set[str]],
                                             stop_connectivity: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """Calculate region connectivity matrix by aggregating stop-to-stop connectivity."""
    print("Aggregating stop connectivity to regions...")
    connectivity_matrix: Dict[str, Dict[str, int]] = {r: {} for r in region_stops.keys()}
    
    stop_to_regions: Dict[str, Set[str]] = defaultdict(set)
    for region_id, region_stop_set in region_stops.items():
        for stop_id in region_stop_set:
            stop_to_regions[stop_id].add(region_id)
    
    for stop1_id, connections in stop_connectivity.items():
        regions1 = stop_to_regions.get(stop1_id, set())
        if not regions1:
            continue
            
        for stop2_id, trip_count in connections.items():
            regions2 = stop_to_regions.get(stop2_id, set())
            if not regions2:
                continue
            
            for region1_id in regions1:
                for region2_id in regions2:
                    if region1_id != region2_id:
                        connectivity_matrix[region1_id].setdefault(region2_id, 0)
                        connectivity_matrix[region1_id][region2_id] += trip_count
    
    print(f"Aggregated connectivity for {len(connectivity_matrix)} regions")
    return connectivity_matrix

def calculate_connectivity_matrix(region_stops: Dict[str, Set[str]], 
                                 trip_stop_ids: Dict[str, Set[str]]) -> Tuple[Dict[str, Dict[str, int]], 
                                                                              Dict[str, Set[str]], 
                                                                              Dict[str, Set[str]]]:
    """Calculate connectivity matrix for all region pairs (legacy method from trips)."""
    stop_to_regions: Dict[str, Set[str]] = defaultdict(set)
    for region_id, region_stop_set in region_stops.items():
        for stop_id in region_stop_set:
            stop_to_regions[stop_id].add(region_id)
    
    trip_regions: Dict[str, Set[str]] = defaultdict(set)
    for trip_id, stop_ids in trip_stop_ids.items():
        for stop_id in stop_ids:
            trip_regions[trip_id].update(stop_to_regions.get(stop_id, set()))
    
    connectivity_matrix: Dict[str, Dict[str, int]] = {r: {} for r in region_stops.keys()}
    
    for trip_id, regions_in_trip in trip_regions.items():
        regions_list = list(regions_in_trip)
        for i, region1_id in enumerate(regions_list):
            for region2_id in regions_list[i + 1:]:
                connectivity_matrix[region1_id].setdefault(region2_id, 0)
                connectivity_matrix[region1_id][region2_id] += 1
                connectivity_matrix[region2_id].setdefault(region1_id, 0)
                connectivity_matrix[region2_id][region1_id] += 1
    
    return connectivity_matrix, trip_regions, stop_to_regions


# ============================================================================
# Data Structure Helpers
# ============================================================================

def build_trip_stop_ids(stop_times_by_trip: Dict[str, List[Dict]]) -> Dict[str, Set[str]]:
    """Build trip_stop_ids mapping from stop_times_by_trip."""
    return {trip_id: {st['stop_id'] for st in trip_stop_times}
            for trip_id, trip_stop_times in stop_times_by_trip.items()}

def build_trip_to_route(trips: List[Dict]) -> Dict[str, str]:
    """Build trip_to_route mapping from trips."""
    return {trip['trip_id']: trip['route_id'] for trip in trips}

def build_routes_dict(routes: List[Dict]) -> Dict[str, Dict]:
    """Build routes_dict mapping from routes."""
    return {route['route_id']: route for route in routes}


# ============================================================================
# Routes Cache Building
# ============================================================================

def precompute_trip_region_indices(stop_times_by_trip: Dict[str, List[Dict]],
                                   trip_regions: Dict[str, Set[str]],
                                   stop_to_regions: Dict[str, Set[str]]) -> Dict[str, Dict[str, List[int]]]:
    """Pre-compute stop indices for each trip-region combination."""
    trip_region_indices: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    
    for trip_id, trip_stop_times in stop_times_by_trip.items():
        regions_in_trip = trip_regions.get(trip_id, set())
        if not regions_in_trip:
            continue
        
        for idx, st in enumerate(trip_stop_times):
            stop_regions = stop_to_regions.get(st['stop_id'], set())
            for region_id in stop_regions & regions_in_trip:
                trip_region_indices[trip_id][region_id].append(idx)
    
    return trip_region_indices

def precompute_region_pair_trips(region_stops: Dict[str, Set[str]],
                                 trip_regions: Dict[str, Set[str]],
                                 trip_region_indices: Dict[str, Dict[str, List[int]]]) -> Dict[str, Dict[str, Set[str]]]:
    """Pre-compute which trips connect each region pair."""
    region_pair_trips: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    
    for trip_id, regions_in_trip in trip_regions.items():
        regions_list = list(regions_in_trip)
        for i, region1_id in enumerate(regions_list):
            for region2_id in regions_list[i + 1:]:
                indices1 = trip_region_indices.get(trip_id, {}).get(region1_id, [])
                indices2 = trip_region_indices.get(trip_id, {}).get(region2_id, [])
                
                if indices1 and indices2:
                    min1, max1 = min(indices1), max(indices1)
                    min2, max2 = min(indices2), max(indices2)
                    
                    if max1 < min2 or max2 < min1:
                        region_pair_trips[region1_id][region2_id].add(trip_id)
                        region_pair_trips[region2_id][region1_id].add(trip_id)
    
    return region_pair_trips

def build_routes_cache(region_stops: Dict[str, Set[str]], routes_dict: Dict[str, Dict],
                      trip_to_route: Dict[str, str], stop_times_by_trip: Dict[str, List[Dict]],
                      trip_regions: Dict[str, Set[str]], stop_to_regions: Dict[str, Set[str]],
                      progress_interval: int = 10) -> Dict[str, Dict[str, List[Dict]]]:
    """Build routes cache for all region pairs."""
    trip_region_indices = precompute_trip_region_indices(stop_times_by_trip, trip_regions, stop_to_regions)
    region_pair_trips = precompute_region_pair_trips(region_stops, trip_regions, trip_region_indices)
    
    routes_cache = {}
    regions = list(region_stops.keys())
    
    for i, region1_id in enumerate(regions):
        if i % progress_interval == 0:
            print(f"Processing routes for {i+1}/{len(regions)}...")
        
        routes_cache[region1_id] = {}
        connecting_trip_ids = region_pair_trips.get(region1_id, {})
        
        for region2_id in regions:
            if region1_id != region2_id:
                trip_ids = connecting_trip_ids.get(region2_id, set())
                if trip_ids:
                    route_to_trip_count: Dict[str, int] = defaultdict(int)
                    for trip_id in trip_ids:
                        route_id = trip_to_route.get(trip_id)
                        if route_id:
                            route_to_trip_count[route_id] += 1
                    
                    routes_cache[region1_id][region2_id] = [
                        {
                            'route_id': route_id,
                            'route_short_name': routes_dict.get(route_id, {}).get('route_short_name', ''),
                            'route_long_name': routes_dict.get(route_id, {}).get('route_long_name', ''),
                            'trip_count': trip_count
                        }
                        for route_id, trip_count in route_to_trip_count.items()
                        if trip_count > 0
                    ]
    
    return routes_cache


# ============================================================================
# GTFS Data Loading
# ============================================================================

def _load_calendar_services(gtfs_zip: str, representative_day: str = 'wednesday') -> Optional[Set[str]]:
    """Load calendar.txt and return service_ids active on the representative day.

    Returns None if calendar.txt is not found (meaning no filtering should be applied).
    """
    try:
        services = set()
        all_services = set()
        for row in parse_csv_from_zip(gtfs_zip, 'calendar.txt'):
            all_services.add(row.get('service_id', ''))
            if row.get(representative_day, '0') == '1':
                services.add(row.get('service_id', ''))
        if not services:
            print(f"Warning: no services run on {representative_day}, using all services")
            return None
        if services != all_services:
            print(f"Filtering to {len(services)}/{len(all_services)} services active on {representative_day}")
        return services
    except KeyError:
        return None


def load_gtfs_data(gtfs_zip: Path) -> Tuple[Dict, List[Dict], List[Dict], Dict[str, List[Dict]], Dict[str, Dict]]:
    """Load GTFS data directly from zip file.

    Filters trips to a representative day (Wednesday) using calendar.txt
    so that trip counts reflect a single day's schedule.

    Returns:
        Tuple of (gtfs_data, routes, trips, stop_times_by_trip, stops_data)
        gtfs_data: Dict containing raw GTFS data for backward compatibility
    """
    print("Loading GTFS data from zip file...")

    # Load calendar to determine which services run on a representative day
    active_services = _load_calendar_services(str(gtfs_zip))

    # Load routes
    routes = []
    try:
        for row in parse_csv_from_zip(str(gtfs_zip), 'routes.txt'):
            routes.append(dict(row))
    except KeyError:
        print("Warning: routes.txt not found in GTFS zip")

    # Load trips, filtering to representative day if calendar is available
    trips = []
    active_trip_ids: Optional[Set[str]] = None
    try:
        all_trip_count = 0
        for row in parse_csv_from_zip(str(gtfs_zip), 'trips.txt'):
            all_trip_count += 1
            if active_services is None or row.get('service_id', '') in active_services:
                trips.append(dict(row))
        if active_services is not None and all_trip_count != len(trips):
            print(f"Filtered trips: {len(trips)}/{all_trip_count} active on representative day")
            active_trip_ids = {t['trip_id'] for t in trips}
    except KeyError:
        print("Warning: trips.txt not found in GTFS zip")

    # Load stop_times (only for active trips)
    stop_times_by_trip: Dict[str, List[Dict]] = defaultdict(list)
    try:
        for row in parse_csv_from_zip(str(gtfs_zip), 'stop_times.txt'):
            trip_id = row.get('trip_id', '')
            if trip_id and (active_trip_ids is None or trip_id in active_trip_ids):
                stop_times_by_trip[trip_id].append(dict(row))
    except KeyError:
        print("Warning: stop_times.txt not found in GTFS zip")

    # Sort stop_times by sequence
    for trip_id in stop_times_by_trip:
        stop_times_by_trip[trip_id].sort(key=lambda x: int(x.get('stop_sequence', 0)))

    # Load stops
    stops_data = {}
    try:
        for row in parse_csv_from_zip(str(gtfs_zip), 'stops.txt'):
            try:
                stop_id = row.get('stop_id', '')
                if stop_id:
                    stops_data[stop_id] = {
                        'stop_name': row.get('stop_name', ''),
                        'stop_lat': float(row.get('stop_lat', 0)),
                        'stop_lon': float(row.get('stop_lon', 0))
                    }
            except (ValueError, KeyError):
                continue
    except KeyError:
        print("Warning: stops.txt not found in GTFS zip")

    # Create gtfs_data dict for backward compatibility
    gtfs_data = {
        'routes': routes,
        'trips': trips,
        'stop_times': stop_times_by_trip,
        'stops': stops_data
    }

    print(f"Loaded {len(routes)} routes, {len(trips)} trips, {len(stops_data)} stops")
    return gtfs_data, routes, trips, stop_times_by_trip, stops_data


def discover_gtfs_files(gtfs_dir: Path, city_code: str) -> List[Path]:
    """Discover all GTFS zip files for a city in the given directory.

    Matches files named {city_code}.zip and {city_code}-*.zip.
    """
    matches = []
    primary = gtfs_dir / f"{city_code}.zip"
    if primary.exists():
        matches.append(primary)
    for path in sorted(gtfs_dir.glob(f"{city_code}-*.zip")):
        matches.append(path)
    return matches


def load_multiple_gtfs_data(gtfs_zips: List[Path]) -> Tuple[Dict, List[Dict], List[Dict], Dict[str, List[Dict]], Dict[str, Dict]]:
    """Load and merge GTFS data from multiple zip files.

    Returns the same tuple as load_gtfs_data but with merged data.
    """
    if len(gtfs_zips) == 1:
        return load_gtfs_data(gtfs_zips[0])

    all_routes = []
    all_trips = []
    all_stop_times_by_trip: Dict[str, List[Dict]] = {}
    all_stops_data: Dict[str, Dict] = {}

    for gtfs_zip in gtfs_zips:
        print(f"\nLoading GTFS: {gtfs_zip.name}")
        _, routes, trips, stop_times_by_trip, stops_data = load_gtfs_data(gtfs_zip)
        all_routes.extend(routes)
        all_trips.extend(trips)
        all_stop_times_by_trip.update(stop_times_by_trip)
        all_stops_data.update(stops_data)

    gtfs_data = {
        'routes': all_routes,
        'trips': all_trips,
        'stop_times': all_stop_times_by_trip,
        'stops': all_stops_data
    }

    print(f"\nMerged totals: {len(all_routes)} routes, {len(all_trips)} trips, {len(all_stops_data)} stops")
    return gtfs_data, all_routes, all_trips, all_stop_times_by_trip, all_stops_data



# ============================================================================
# Hexagon Generation & Filtering
# ============================================================================

def point_in_convex_hull(lat: float, lon: float, hull_points: List[Tuple[float, float]]) -> bool:
    """Check if point is inside convex hull polygon."""
    if not hull_points or len(hull_points) < 3:
        return False
    
    inside = False
    j = len(hull_points) - 1
    for i in range(len(hull_points)):
        pi_lat, pi_lon = hull_points[i]
        pj_lat, pj_lon = hull_points[j]
        if ((pi_lat > lat) != (pj_lat > lat)) and (lon < (pj_lon - pi_lon) * (lat - pi_lat) / (pj_lat - pi_lat) + pi_lon):
            inside = not inside
        j = i
    return inside

def generate_hexagons_in_bbox(min_lat: float, min_lon: float, max_lat: float, max_lon: float, 
                              resolution: int = 8) -> Set[str]:
    """Generate hexagons covering a bounding box."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    
    if H3_API_NEW and hasattr(h3, 'bbox_to_cells'):
        try:
            return set(h3.bbox_to_cells(min_lon, min_lat, max_lon, max_lat, resolution))
        except Exception:
            pass
    
    step = 0.002
    all_cells = set()
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            all_cells.add(latlng_to_cell(lat, lon, resolution))
            lon += step
        lat += step
    return all_cells

def generate_hexagons_for_convex_hull(stops: Iterator[Dict], resolution: int = 8) -> Set[str]:
    """Generate hexagons covering the convex hull of all stops."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    
    if not SCIPY_AVAILABLE:
        print("Warning: scipy not available, using bbox instead of convex hull")
        stops_list = list(extract_stop_coordinates(stops))
        if not stops_list:
            return set()
        bbox = get_bbox_from_coords(stops_list)
        min_lat, min_lon, max_lat, max_lon = bbox
        return generate_hexagons_in_bbox(min_lat, min_lon, max_lat, max_lon, resolution)
    
    hull_points = calculate_convex_hull(stops)
    if not hull_points:
        print("Warning: Could not calculate convex hull, falling back to bbox")
        stops_list = list(extract_stop_coordinates(stops))
        if not stops_list:
            return set()
        bbox = get_bbox_from_coords(stops_list)
        min_lat, min_lon, max_lat, max_lon = bbox
        return generate_hexagons_in_bbox(min_lat, min_lon, max_lat, max_lon, resolution)
    
    print(f"Convex hull has {len(hull_points)} vertices")
    
    bbox = get_bbox_from_coords(hull_points, buffer=0.05)
    min_lat, min_lon, max_lat, max_lon = bbox
    print(f"Bounding box: ({min_lat:.4f}, {min_lon:.4f}) to ({max_lat:.4f}, {max_lon:.4f})")
    
    if H3_API_NEW and hasattr(h3, 'bbox_to_cells'):
        try:
            cells = set(h3.bbox_to_cells(min_lon, min_lat, max_lon, max_lat, resolution))
            filtered_cells = {cell for cell in cells if point_in_convex_hull(*cell_to_latlng(cell), hull_points)}
            print(f"Using bbox_to_cells + hull filter: {len(filtered_cells)} hexagons")
            return filtered_cells
        except Exception as e:
            print(f"Warning: bbox_to_cells failed, using grid sampling: {e}")
    
    all_cells = set()
    sample_count = 0
    
    if resolution == 5:
        step = 0.7
    elif resolution == 6:
        step = 0.1
    elif resolution == 7:
        step = 0.014
    elif resolution == 8:
        step = 0.002
    elif resolution == 9:
        step = 0.00028
    elif resolution == 10:
        step = 0.00004
    else:
        step = 0.002
    
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            if point_in_convex_hull(lat, lon, hull_points):
                all_cells.add(latlng_to_cell(lat, lon, resolution))
                sample_count += 1
            lon += step
        lat += step
    
    print(f"Grid sampling: {sample_count} sample points generated {len(all_cells)} unique hexagons")
    return all_cells

def grid_disk(cell: str, k: int) -> Set[str]:
    """Get all h3 cells within grid distance k (inclusive)."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    if H3_API_NEW:
        return set(h3.grid_disk(cell, k))
    return set(h3.k_ring(cell, k))

def generate_hexagons_near_stops(stops: Iterator[Dict], resolution: int = 8,
                                 buffer_rings: int = 2) -> Set[str]:
    """Generate hexagons containing stops, plus a buffer of neighbor rings.

    Unlike filling the entire convex hull of all stops (which is dominated by
    empty hexagons far from any transit), this keeps only the hexagons near
    actual stops. The buffer keeps corridors visually contiguous and leaves
    room for osmosis to spread, while drastically reducing the hexagon count
    (and therefore the payload the site has to load).
    """
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")

    stop_cells = {
        latlng_to_cell(lat, lon, resolution)
        for lat, lon in extract_stop_coordinates(stops)
    }
    if buffer_rings <= 0:
        return stop_cells

    cells = set(stop_cells)
    for cell in stop_cells:
        cells |= grid_disk(cell, buffer_rings)
    return cells

def cells_to_union_geometry(cells: Set[str]) -> Optional[Dict]:
    """Union a set of h3 cells into a single GeoJSON (Multi)Polygon geometry.

    Used to collapse the large area of empty hexagons (outside the buffer near
    stops) into one filled shape, so the map keeps its full appearance without
    thousands of individual hexagon features.
    """
    if not H3_AVAILABLE or not cells:
        return None
    try:
        shape = h3.cells_to_h3shape(set(cells))  # h3 v4
        return shape.__geo_interface__
    except AttributeError:
        # h3 v3 fallback
        polys = h3.h3_set_to_multi_polygon(list(cells), geo_json=True)
        return {'type': 'MultiPolygon', 'coordinates': polys}

def build_neighbor_graph(hexagon_set: Set[str]) -> Dict[str, Set[str]]:
    """Build neighbor graph for hexagon set."""
    neighbors: Dict[str, Set[str]] = {}
    for hex_id in hexagon_set:
        try:
            all_neighbors = get_cell_neighbors(hex_id)
            neighbors[hex_id] = all_neighbors & hexagon_set
        except Exception:
            neighbors[hex_id] = set()
    return neighbors

def find_reachable_hexagons(start_set: Set[str], hexagon_set: Set[str], 
                           neighbors: Dict[str, Set[str]]) -> Set[str]:
    """Find all hexagons reachable from start set via BFS."""
    reachable = set(start_set)
    queue = deque(start_set)
    while queue:
        current = queue.popleft()
        for neighbor in neighbors.get(current, set()):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    return reachable

def filter_hexagons(hexagon_stops: Dict[str, Set[str]],
                   hexagon_metadata: Dict[str, Dict],
                   connectivity_matrix: Dict[str, Dict[str, int]],
                   hexagons_with_trips: Set[str]) -> Tuple[Dict[str, Set[str]], Dict[str, Dict], Dict[str, Dict[str, int]]]:
    """Filter hexagons to remove unused/isolated ones, preserving contiguity."""
    hexagon_set = set(hexagon_stops.keys())
    active_hexagons = hexagons_with_trips | {h for h, stops in hexagon_stops.items() if stops}
    
    neighbors = build_neighbor_graph(hexagon_set)
    reachable = find_reachable_hexagons(active_hexagons, hexagon_set, neighbors)
    
    no_connections = {h for h, conns in connectivity_matrix.items() if not any(conns.values())}
    unused = {h for h in hexagon_stops.keys() 
              if not hexagon_stops[h] and h in no_connections 
              and h not in hexagons_with_trips and h not in reachable}
    isolated = hexagon_set - reachable
    without_neighbors = {h for h in hexagon_set - reachable if not neighbors.get(h, set())}
    
    to_remove = unused | isolated | without_neighbors
    
    if to_remove:
        print(f"Removing {len(to_remove)} filtered hexagons...")
        for hex_id in to_remove:
            hexagon_stops.pop(hex_id, None)
            hexagon_metadata.pop(hex_id, None)
            connectivity_matrix.pop(hex_id, None)
        
        for hex_id in list(connectivity_matrix.keys()):
            for removed_id in to_remove:
                connectivity_matrix[hex_id].pop(removed_id, None)
    
    return hexagon_stops, hexagon_metadata, connectivity_matrix

def create_h3_geojson(hexagon_ids: List[str]) -> Dict:
    """Create GeoJSON from h3 hexagon IDs."""
    if not H3_AVAILABLE:
        raise ImportError("h3 library is required")
    
    features = []
    for hex_id in hexagon_ids:
        try:
            boundary = cell_to_boundary(hex_id)
            ring = [[lon, lat] for lat, lon in boundary]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            features.append({
                'type': 'Feature',
                'properties': {'hex_id': hex_id},
                'geometry': {'type': 'Polygon', 'coordinates': [ring]}
            })
        except Exception as e:
            print(f"Warning: Could not create boundary for hex {hex_id}: {e}")
    
    return {'type': 'FeatureCollection', 'features': features}


# ============================================================================
# Isochrone Generation
# ============================================================================

def parse_time(time_str: str) -> int:
    """Parse GTFS time string (HH:MM:SS) to seconds since midnight."""
    try:
        parts = time_str.split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        return 0

def build_stop_graph(stop_times_by_trip: Dict[str, List[Dict]], 
                     trips: List[Dict],
                     stops_data: Dict[str, Dict]) -> Tuple[Dict[str, Dict[str, int]], Dict[str, List[Tuple[str, int, str]]]]:
    """Build a graph of stops with travel times and wait times."""
    print("Building stop graph from GTFS schedule...")
    stop_graph: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(lambda: float('inf')))
    stop_departures: Dict[str, List[Tuple[str, int, str]]] = defaultdict(list)
    
    trip_to_route = {trip['trip_id']: trip.get('route_id', '') for trip in trips}
    
    for trip_id, stop_times in stop_times_by_trip.items():
        if len(stop_times) < 2:
            continue
        
        sorted_stops = sorted(stop_times, key=lambda x: int(x.get('stop_sequence', 0)))
        
        for i in range(len(sorted_stops) - 1):
            current_stop = sorted_stops[i]
            next_stop = sorted_stops[i + 1]
            
            current_stop_id = current_stop['stop_id']
            next_stop_id = next_stop['stop_id']
            
            if current_stop_id not in stops_data or next_stop_id not in stops_data:
                continue
            
            arrival_time = parse_time(next_stop.get('arrival_time', '00:00:00'))
            departure_time = parse_time(current_stop.get('departure_time', '00:00:00'))
            
            if arrival_time > departure_time:
                travel_time = arrival_time - departure_time
            else:
                travel_time = (24 * 3600 - departure_time) + arrival_time
            
            if travel_time < stop_graph[current_stop_id][next_stop_id]:
                stop_graph[current_stop_id][next_stop_id] = travel_time
            
            stop_departures[current_stop_id].append((trip_id, departure_time, next_stop_id))
    
    return dict({k: dict(v) for k, v in stop_graph.items()}), dict(stop_departures)

def calculate_reachable_stops(start_stop_id: str,
                              stop_graph: Dict[str, Dict[str, int]],
                              stop_departures: Dict[str, List[Tuple[str, int, str]]],
                              stops_data: Dict[str, Dict],
                              time_limits: List[int],
                              transfer_penalty: int = 300,
                              wait_time_estimate: int = 300) -> Dict[int, Set[str]]:
    """Calculate all reachable stops from a start stop within time limits."""
    if start_stop_id not in stops_data:
        return {limit: set() for limit in time_limits}
    
    min_times_no_transfer: Dict[str, int] = {start_stop_id: 0}
    min_times_with_transfer: Dict[str, int] = {}
    
    reachable_by_limit: Dict[int, Set[str]] = {limit: set() for limit in time_limits}
    reachable_by_limit[max(time_limits)].add(start_stop_id)
    
    queue = deque([(start_stop_id, 0, 0)])
    processed: Set[Tuple[str, int]] = set()
    
    while queue:
        current_stop, arrival_time, transfers = queue.popleft()
        
        state_key = (current_stop, transfers)
        if state_key in processed:
            continue
        processed.add(state_key)
        
        for limit in time_limits:
            if arrival_time <= limit:
                reachable_by_limit[limit].add(current_stop)
        
        if arrival_time > max(time_limits):
            continue
        
        for next_stop, travel_time in stop_graph.get(current_stop, {}).items():
            total_time = arrival_time + wait_time_estimate + travel_time
            
            if total_time > max(time_limits):
                continue
            
            if next_stop not in min_times_no_transfer or total_time < min_times_no_transfer[next_stop]:
                min_times_no_transfer[next_stop] = total_time
                queue.append((next_stop, total_time, 0))
            
            if transfers < 1:
                for transfer_stop, transfer_travel_time in stop_graph.get(next_stop, {}).items():
                    if transfer_stop == current_stop or transfer_stop == start_stop_id:
                        continue
                    
                    transfer_time = total_time + transfer_penalty + wait_time_estimate + transfer_travel_time
                    
                    if transfer_time > max(time_limits):
                        continue
                    
                    if transfer_stop not in min_times_with_transfer or transfer_time < min_times_with_transfer[transfer_stop]:
                        min_times_with_transfer[transfer_stop] = transfer_time
                        queue.append((transfer_stop, transfer_time, 1))
    
    return reachable_by_limit

def create_isochrone_polygon(reachable_stops: Set[str],
                             stops_data: Dict[str, Dict],
                             buffer_meters: float = 500) -> Optional[Dict]:
    """Create an isochrone polygon from a set of reachable stops."""
    if not reachable_stops:
        return None
    
    try:
        points = []
        for stop_id in reachable_stops:
            if stop_id in stops_data:
                stop = stops_data[stop_id]
                points.append((stop['stop_lon'], stop['stop_lat']))
        
        if len(points) < 3:
            if len(points) == 1:
                if not SHAPELY_AVAILABLE or Point is None:
                    return None
                point = Point(points[0])
                buffered = point.buffer(buffer_meters / 111320.0)
            elif len(points) == 2:
                if not SHAPELY_AVAILABLE or LineString is None:
                    return None
                line = LineString(points)
                buffered = line.buffer(buffer_meters / 111320.0)
            else:
                return None
        else:
            if not SHAPELY_AVAILABLE or MultiPoint is None:
                return None
            multipoint = MultiPoint(points)
            convex_hull = multipoint.convex_hull
            
            avg_lat = sum(p[1] for p in points) / len(points)
            lat_factor = abs(math.cos(math.radians(avg_lat)))
            buffer_degrees = buffer_meters / (111320.0 * lat_factor)
            
            buffered = convex_hull.buffer(buffer_degrees)
        
        if hasattr(buffered, '__geo_interface__'):
            return buffered.__geo_interface__
        else:
            if hasattr(buffered, 'exterior'):
                coords = list(buffered.exterior.coords)
                return {
                    'type': 'Polygon',
                    'coordinates': [coords]
                }
            return None
            
    except Exception as e:
        print(f"Warning: Failed to create isochrone polygon: {e}")
        return None

def generate_stop_isochrones(stop_id: str,
                            stop_graph: Dict[str, Dict[str, int]],
                            stop_departures: Dict[str, List[Tuple[str, int, str]]],
                            stops_data: Dict[str, Dict],
                            time_intervals: List[int],
                            buffer_meters: float = 500) -> Dict[int, Optional[Dict]]:
    """Generate isochrone polygons for a stop at different time intervals."""
    reachable_by_limit = calculate_reachable_stops(
        stop_id, stop_graph, stop_departures, stops_data, time_intervals
    )
    
    isochrones = {}
    for time_limit in time_intervals:
        reachable_stops = reachable_by_limit.get(time_limit, set())
        polygon = create_isochrone_polygon(reachable_stops, stops_data, buffer_meters)
        isochrones[time_limit] = polygon
    
    return isochrones


def chunk_isochrones(isochrone_data: Dict[str, Dict[str, Any]], 
                     output_dir: Path,
                     max_chunk_size_mb: float = 10.0) -> None:
    """Chunk isochrone data into smaller files."""
    chunks_dir = output_dir / 'isochrone_chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)
    
    max_chunk_size_bytes = int(max_chunk_size_mb * 1024 * 1024)
    index: Dict[str, str] = {}
    total_size = 0
    chunk_count = 0
    current_chunk: Dict[str, Dict[str, Any]] = {}
    current_chunk_size = 0
    
    def write_chunk(chunk_data: Dict[str, Dict[str, Any]], chunk_num: int) -> str:
        chunk_filename = f"chunk_{chunk_num:04d}.json"
        chunk_path = chunks_dir / chunk_filename
        
        with open(chunk_path, 'w') as f:
            json.dump(chunk_data, f, separators=(',', ':'))
        
        return chunk_filename
    
    for stop_id, intervals in isochrone_data.items():
        test_chunk = {stop_id: intervals}
        test_json = json.dumps(test_chunk, separators=(',', ':'))
        stop_size = len(test_json.encode('utf-8'))
        
        if current_chunk_size > 0 and current_chunk_size + stop_size > max_chunk_size_bytes:
            chunk_filename = write_chunk(current_chunk, chunk_count)
            chunk_size = (chunks_dir / chunk_filename).stat().st_size
            total_size += chunk_size
            
            for sid in current_chunk.keys():
                index[sid] = chunk_filename
            
            chunk_count += 1
            current_chunk = {}
            current_chunk_size = 0
            
            if chunk_count % 10 == 0:
                print(f"  Processed {chunk_count} chunks...")
        
        current_chunk[stop_id] = intervals
        current_chunk_size += stop_size
    
    if current_chunk:
        chunk_filename = write_chunk(current_chunk, chunk_count)
        chunk_size = (chunks_dir / chunk_filename).stat().st_size
        total_size += chunk_size
        
        for sid in current_chunk.keys():
            index[sid] = chunk_filename
        
        chunk_count += 1
    
    index_path = chunks_dir / 'index.json'
    with open(index_path, 'w') as f:
        json.dump(index, f, separators=(',', ':'))
    
    avg_size_mb = (total_size / chunk_count / (1024*1024)) if chunk_count > 0 else 0
    print(f"\nIsochrone chunking complete!")
    print(f"  Total chunks: {chunk_count}")
    print(f"  Total size: {total_size / (1024*1024):.2f} MB")
    print(f"  Average chunk size: {avg_size_mb:.2f} MB")
    print(f"  Max chunk size: {max_chunk_size_mb} MB")
    print(f"  Index file: {index_path}")
    print(f"  Output directory: {chunks_dir}")
