// Type definitions for the application

export type RegionType = 'wards' | 'hexagons';

export interface GeoJSONFeature {
	type: string;
	properties?: Record<string, any>;
	geometry?: any;
}

export interface GeoJSONFeatureCollection {
	type: 'FeatureCollection';
	features: GeoJSONFeature[];
}

export interface Ward {
	id: string;
	name: string;
	centroid: [number, number];
	stop_count: number;
}

export interface ConnectivityScore {
	wardId: string;
	score: number;
	normalizedScore: number;
}

export interface Route {
	route_id: string;
	route_short_name: string;
	route_long_name: string;
	trips?: any[];
	trip_count?: number;
}

export interface Stop {
	stop_id: string;
	stop_name: string;
	stop_lat: number;
	stop_lon: number;
}
