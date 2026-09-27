import type { RegionType } from './types';

export type CityCode = 'blr' | 'chennai' | 'pune' | 'hyderabad' | 'andhrapradesh' | 'railways';

export interface ColorScaleThreshold {
	threshold: number;
	color: string;
}

export interface ColorScaleConfig {
	thresholds: ColorScaleThreshold[];
	zeroColor: string; // Color for score 0 (no connectivity)
}

export interface CityConfig {
	code: CityCode;
	name: string;
	siteName: string;
	supportedRegions: RegionType[];
	mapCenter: [number, number]; // [lon, lat]
	mapBbox: [number, number, number, number]; // [minLon, minLat, maxLon, maxLat]
	mapZoom: number;
	gtfsPath: string;
	geojsonPath?: string; // Optional, for wards
	defaultWard?: string; // Optional, default ward ID for wards mode (e.g., '59: Nehru Nagar')
	defaultSearchTerm?: string; // Optional, default search term for hexagons mode
	hexagonResolution?: number; // H3 hexagon resolution (default: 8)
	colorScale?: ColorScaleConfig; // Color scale configuration for trip count mapping
	wardColorScale?: ColorScaleConfig; // Optional separate color scale for ward mode
}

export const cityConfigs: Record<CityCode, CityConfig> = {
	blr: {
		code: 'blr',
		name: 'Bengaluru',
		siteName: 'BLR Transit Affinity',
		supportedRegions: ['hexagons', 'wards'],
		mapCenter: [77.5946, 12.9716],
		mapBbox: [77.3, 12.7, 77.9, 13.2],
		mapZoom: 11,
		gtfsPath: 'scripts/gtfs/blr.zip',
		geojsonPath: 'static/gba_ward.geojson',
		defaultWard: '59: Nehru Nagar',
		defaultSearchTerm: 'Banashankari Bus Station',
		hexagonResolution: 8,
		colorScale: {
			zeroColor: '#d73027', // Bright red for no connectivity
			thresholds: [
				{ threshold: 800, color: '#1a9850' },
				{ threshold: 400, color: '#91cf60' },
				{ threshold: 200, color: '#d9ef8b' },
				{ threshold: 100, color: '#fee08b' },
				{ threshold: 50, color: '#fc8d59' },
				{ threshold: 10, color: '#d73027' }
			]
		},
		wardColorScale: {
			zeroColor: '#d73027',
			thresholds: [
				{ threshold: 500, color: '#1a9850' },
				{ threshold: 200, color: '#91cf60' },
				{ threshold: 100, color: '#d9ef8b' },
				{ threshold: 40, color: '#fee08b' },
				{ threshold: 0, color: '#fc8d59' }
			]
		}
	},
	chennai: {
		code: 'chennai',
		name: 'Chennai',
		siteName: 'Chennai Transit Affinity',
		supportedRegions: ['hexagons'],
		mapCenter: [80.2707, 13.0827],
		mapBbox: [80.0, 12.8, 80.4, 13.3],
		mapZoom: 11,
		gtfsPath: 'scripts/gtfs/chennai.zip',
		defaultSearchTerm: 'MGR Central Railway Station',
		hexagonResolution: 8,
		colorScale: {
			zeroColor: '#d73027',
			thresholds: [
				{ threshold: 750, color: '#1a9850' },
				{ threshold: 500, color: '#91cf60' },
				{ threshold: 250, color: '#d9ef8b' },
				{ threshold: 100, color: '#fee08b' },
				{ threshold: 0, color: '#fc8d59' }
			]
		}
	},
	pune: {
		code: 'pune',
		name: 'Pune',
		siteName: 'Pune Transit Affinity',
		supportedRegions: ['hexagons'],
		mapCenter: [73.8567, 18.5204],
		mapBbox: [73.7, 18.4, 74.05, 18.7],
		mapZoom: 11,
		gtfsPath: 'scripts/gtfs/pune.zip',
		defaultSearchTerm: 'Swargate',
		hexagonResolution: 8,
		colorScale: {
			zeroColor: '#d73027',
			thresholds: [
				{ threshold: 750, color: '#1a9850' },
				{ threshold: 500, color: '#91cf60' },
				{ threshold: 250, color: '#d9ef8b' },
				{ threshold: 100, color: '#fee08b' },
				{ threshold: 0, color: '#fc8d59' }
			]
		}
	},
	hyderabad: {
		code: 'hyderabad',
		name: 'Hyderabad',
		siteName: 'Hyderabad Transit Affinity',
		supportedRegions: ['hexagons'],
		mapCenter: [78.4744, 17.385],
		mapBbox: [78.2, 17.2, 78.7, 17.6],
		mapZoom: 11,
		gtfsPath: 'scripts/gtfs/hyderabad.zip',
		defaultSearchTerm: 'Nanal Nagar',
		hexagonResolution: 8,
		colorScale: {
			zeroColor: '#d73027',
			thresholds: [
				{ threshold: 750, color: '#1a9850' },
				{ threshold: 500, color: '#91cf60' },
				{ threshold: 250, color: '#d9ef8b' },
				{ threshold: 100, color: '#fee08b' },
				{ threshold: 0, color: '#fc8d59' }
			]
		}
	},
	andhrapradesh: {
		code: 'andhrapradesh',
		name: 'Andhra Pradesh',
		siteName: 'APSRTC',
		supportedRegions: ['hexagons'],
		mapCenter: [81.0, 15.9],
		mapBbox: [77.0, 12.4, 85.5, 19.7],
		mapZoom: 9,
		gtfsPath: 'scripts/gtfs/andhrapradesh.zip',
		defaultSearchTerm: 'VISAKHAPATNAM',
		hexagonResolution: 6,
		colorScale: {
			zeroColor: '#d73027',
			thresholds: [
				{ threshold: 32, color: '#1a9850' },
				{ threshold: 16, color: '#91cf60' },
				{ threshold: 8, color: '#d9ef8b' },
				{ threshold: 4, color: '#fee08b' },
				{ threshold: 0, color: '#fc8d59' }
			]
		}
	},
	railways: {
		code: 'railways',
		name: 'Railways',
		siteName: 'Indian Railways Transit Affinity',
		supportedRegions: ['hexagons'],
		mapCenter: [85, 20],
		mapBbox: [70, 0, 100, 45],
		mapZoom: 8,
		gtfsPath: 'scripts/gtfs/railways.zip',
		defaultSearchTerm: 'YESVANTPUR JN.',
		hexagonResolution: 6,
		colorScale: {
			zeroColor: '#d73027',
			thresholds: [
				{ threshold: 16, color: '#1a9850' },
				{ threshold: 8, color: '#91cf60' },
				{ threshold: 4, color: '#d9ef8b' },
				{ threshold: 2, color: '#fee08b' },
				{ threshold: 0, color: '#fc8d59' }
			]
		}
	}
};

export function getCityConfig(cityCode: CityCode | string): CityConfig {
	const code = cityCode.toLowerCase() as CityCode;
	return cityConfigs[code] || cityConfigs.blr;
}

export function getDefaultCity(): CityCode {
	return 'blr';
}
