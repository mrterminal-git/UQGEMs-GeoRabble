import type { Map } from 'maplibre-gl';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { CityConfig, ColorScaleConfig } from './cityConfigs';
import type { RegionType } from './types';

export function createMap(containerId: string | HTMLElement, config: CityConfig): Map {
	const map = new maplibregl.Map({
		container: containerId,
		style: 'https://tiles.openfreemap.org/styles/positron',
		center: config.mapCenter, // [lon, lat]
		zoom: config.mapZoom
	});

	return map;
}

export function getColorForScore(
	score: number,
	maxScore: number,
	config?: CityConfig,
	regionType?: RegionType
): string {
	// Pick region-specific color scale, falling back to the default
	const colorScale: ColorScaleConfig | undefined =
		regionType === 'wards' && config?.wardColorScale ? config.wardColorScale : config?.colorScale;

	if (colorScale) {
		if (score === 0) {
			return colorScale.zeroColor;
		}

		for (const { threshold, color } of colorScale.thresholds) {
			if (score >= threshold) {
				return color;
			}
		}

		const lowestThreshold = colorScale.thresholds[colorScale.thresholds.length - 1];
		return lowestThreshold?.color || colorScale.zeroColor;
	}

	// Default color scale (backward compatibility)
	if (score === 0) return '#d73027'; // Bright red for no connectivity

	// Color scale based on absolute trip counts
	if (score > 750) return '#1a9850'; // Dark green
	if (score >= 500) return '#91cf60'; // Green
	if (score >= 250) return '#d9ef8b'; // Light green
	if (score >= 100) return '#fee08b'; // Pale green
	return '#fc8d59'; // Light yellow for below 100 trips
}
