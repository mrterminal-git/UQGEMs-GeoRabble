import type { RegionType } from './types';

export type CityCode = 'brisbane';

export interface ColorScaleThreshold {
	threshold: number;
	color: string;
}

export interface ColorScaleConfig {
	thresholds: ColorScaleThreshold[];
	zeroColor: string;
}

export interface CityConfig {
	code: CityCode;
	name: string;
	siteName: string;
	supportedRegions: RegionType[];
	mapCenter: [number, number];
	mapBbox: [number, number, number, number];
	mapZoom: number;
	gtfsPath: string;
	geojsonPath?: string;
	defaultWard?: string;
	defaultSearchTerm?: string;
	hexagonResolution?: number;
	colorScale?: ColorScaleConfig;
	wardColorScale?: ColorScaleConfig;
}

export const cityConfigs: Record<CityCode, CityConfig> = {
	brisbane: {
		code: 'brisbane',
		name: 'Brisbane',
		siteName: 'Brisbane Transit Affinity',
		supportedRegions: ['hexagons', 'wards'],
		mapCenter: [153.0251, -27.4698],
		mapBbox: [152.679693, -27.660219, 153.468229, -27.021557],
		mapZoom: 11,
		gtfsPath: 'SEQ_GTFS/SEQ_GTFS.zip',
		geojsonPath: 'scripts/geojson/brisbane_wards.geojson',
		defaultWard: 'CENTRAL',
		defaultSearchTerm: 'Adelaide Street Stop 28 near Hutton Lane',
		hexagonResolution: 8,
		// These are the original Bengaluru scales. Keeping them unchanged makes the
		// first Brisbane version a direct geographic port of Vonter's scoring model.
		colorScale: {
			zeroColor: '#d73027',
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
	}
};

export function getCityConfig(cityCode: CityCode | string): CityConfig {
	const code = cityCode.toLowerCase() as CityCode;
	return cityConfigs[code] || cityConfigs.brisbane;
}

export function getDefaultCity(): CityCode {
	return 'brisbane';
}
