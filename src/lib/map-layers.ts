import type { Map } from 'maplibre-gl';
import maplibregl from 'maplibre-gl';
import type { GeoJSONFeatureCollection, RegionType } from './types';
import { getColorForScore } from './map';
import type { CityConfig } from './cityConfigs';

// Color shown for regions with no connectivity data while nothing is selected.
const UNSELECTED_BASE_COLOR = '#9e9e9e';

let scoreCache = new globalThis.Map<string, number>();
let lastScoreHash = '';

let colorCache = new globalThis.Map<number, string>();
let lastGlobalMaxScore = 1;
let lastRegionType: RegionType | undefined;

let currentSelectedId: string | null = null;
let currentActiveConnectedId: string | null = null;
// Regions currently carrying an explicit `color` feature-state (the connected
// subset). Everything else is painted by the layer's fallback color, so we
// never touch the thousands of unconnected/background features per update.
let coloredRegionIds = new globalThis.Set<string>();
let selectionActive = false;

export function resetMapLayerState(): void {
	currentSelectedId = null;
	currentActiveConnectedId = null;
	coloredRegionIds.clear();
	selectionActive = false;
	scoreCache.clear();
	colorCache.clear();
	lastScoreHash = '';
	lastGlobalMaxScore = 1;
	lastRegionType = undefined;
}

/**
 * Enriches features with a unified `region_id` property (used as the feature
 * id via `promoteId`) plus display name / stop_count from the ward list.
 */
function enrichGeoJSON(
	geojsonData: GeoJSONFeatureCollection,
	regionType?: RegionType,
	wardsData?: Array<{ id: string; name: string; stop_count: number }>
): GeoJSONFeatureCollection {
	const idProperty = regionType === 'wards' ? 'namecol' : 'hex_id';
	const wardLookup = new globalThis.Map<string, { name: string; stop_count: number }>();
	if (wardsData) {
		for (const ward of wardsData) {
			wardLookup.set(ward.id, { name: ward.name, stop_count: ward.stop_count });
		}
	}

	const enrichedFeatures = geojsonData.features.map((feature: any) => {
		const regionId = feature.properties?.[idProperty];
		const wardData = regionId ? wardLookup.get(regionId) : undefined;
		return {
			...feature,
			properties: {
				...feature.properties,
				region_id: regionId,
				...(wardData ? { name: wardData.name, stop_count: wardData.stop_count } : {})
			}
		};
	});

	return { ...geojsonData, features: enrichedFeatures };
}

function fillColorExpression(fallbackColor: string): any {
	return [
		'case',
		['==', ['feature-state', 'isSelected'], true],
		'#5A5A5A',
		['==', ['feature-state', 'isConnected'], true],
		'#2563eb',
		['coalesce', ['feature-state', 'color'], fallbackColor]
	];
}

export function setRegionSourceData(
	map: Map,
	geojsonData: GeoJSONFeatureCollection,
	regionType?: RegionType,
	wardsData?: Array<{ id: string; name: string; stop_count: number }>
): void {
	const source = map.getSource('wards') as maplibregl.GeoJSONSource | undefined;
	if (source) {
		source.setData(enrichGeoJSON(geojsonData, regionType, wardsData) as any);
	}
}

export function initializeMapLayers(
	map: Map,
	geojsonData: GeoJSONFeatureCollection,
	onRegionClick: (regionId: string) => void,
	regionType?: RegionType,
	wardsData?: Array<{ id: string; name: string; stop_count: number }>,
	cityConfig?: CityConfig
): void {
	const enrichedGeoJSON = enrichGeoJSON(geojsonData, regionType, wardsData);

	if (map.getSource('wards')) {
		const source = map.getSource('wards') as maplibregl.GeoJSONSource;
		source.setData(enrichedGeoJSON as any);
	} else {
		// promoteId makes each feature's id equal to its region_id, so
		// setFeatureState can be keyed directly by region id with no lookup table.
		map.addSource('wards', {
			type: 'geojson',
			data: enrichedGeoJSON as any,
			promoteId: 'region_id'
		});
	}

	const isHexMode = regionType === 'hexagons';

	map.addLayer({
		id: 'wards-fill',
		type: 'fill',
		source: 'wards',
		paint: {
			'fill-color': fillColorExpression(UNSELECTED_BASE_COLOR),
			'fill-opacity': [
				'case',
				['==', ['feature-state', 'isSelected'], true],
				0.7,
				['==', ['feature-state', 'isConnected'], true],
				0.6,
				0.4
			],
			'fill-outline-color': 'transparent'
		}
	});

	map.addLayer({
		id: 'wards-outline',
		type: 'line',
		source: 'wards',
		paint: {
			'line-color': [
				'case',
				['==', ['feature-state', 'isSelected'], true],
				'#5A5A5A',
				['==', ['feature-state', 'isConnected'], true],
				'#1e40af',
				'#000000'
			],
			'line-width': [
				'case',
				['==', ['feature-state', 'isSelected'], true],
				isHexMode ? 0 : 4,
				['==', ['feature-state', 'isConnected'], true],
				isHexMode ? 0 : 3,
				0
			],
			'line-opacity': [
				'case',
				['==', ['feature-state', 'isSelected'], true],
				isHexMode ? 0 : 1.0,
				['==', ['feature-state', 'isConnected'], true],
				isHexMode ? 0 : 0.8,
				isHexMode ? 0 : 0.2
			]
		}
	});

	map.on('click', 'wards-fill', (e) => {
		if (e.features && e.features[0]) {
			if (e.features[0].properties?.is_background) return;
			const regionId = e.features[0].properties?.namecol || e.features[0].properties?.hex_id;
			if (regionId) {
				onRegionClick(regionId);
			}
		}
	});

	map.on('mouseenter', 'wards-fill', () => {
		map.getCanvas().style.cursor = 'pointer';
	});

	map.on('mouseleave', 'wards-fill', () => {
		map.getCanvas().style.cursor = '';
	});

	map.removeLayer('boundary_2');
	map.removeLayer('boundary_3');
	map.removeLayer('boundary_disputed');
}

function cachedColor(
	score: number,
	globalMaxScore: number,
	cityConfig?: CityConfig,
	regionType?: RegionType
): string {
	let color = colorCache.get(score);
	if (!color) {
		color = getColorForScore(score, globalMaxScore, cityConfig, regionType);
		colorCache.set(score, color);
	}
	return color;
}

export function updateMapHighlighting(
	map: Map,
	regionType: RegionType,
	selectedRegionId: string | null,
	connectedRegionId: string | null,
	hoveredRegionId: string | null,
	connectivityScores: Array<{ wardId: string; score: number }>,
	globalMaxScore: number,
	cityConfig?: CityConfig
): void {
	const source = map.getSource('wards') as maplibregl.GeoJSONSource | undefined;
	if (!source) return;

	if (globalMaxScore !== lastGlobalMaxScore || regionType !== lastRegionType) {
		colorCache.clear();
		lastGlobalMaxScore = globalMaxScore;
		lastRegionType = regionType;
	}

	const setState = (id: string | null, state: any) => {
		if (!id) return;
		try {
			map.setFeatureState({ source: 'wards', id }, state);
		} catch {
			// ignore features that aren't present in the current source
		}
	};

	// Flip the layer-wide fallback color so every unconnected region (and the
	// merged "background" feature) renders the no-connectivity color while a
	// region is selected, without per-feature writes.
	const active = selectedRegionId !== null;
	if (active !== selectionActive) {
		selectionActive = active;
		const fallback = active
			? cachedColor(0, globalMaxScore, cityConfig, regionType)
			: UNSELECTED_BASE_COLOR;
		map.setPaintProperty('wards-fill', 'fill-color', fillColorExpression(fallback));
	}

	// Recolor the connected subset only when the connectivity set actually
	// changes (i.e. a new region was selected) — hover/connect changes reuse it.
	const scoreHash = connectivityScores.map((s) => `${s.wardId}:${s.score}`).join(',');
	if (scoreHash !== lastScoreHash) {
		lastScoreHash = scoreHash;

		for (const id of coloredRegionIds) {
			setState(id, { color: null });
		}
		coloredRegionIds.clear();
		scoreCache.clear();

		for (const { wardId, score } of connectivityScores) {
			scoreCache.set(wardId, score);
			if (score > 0) {
				setState(wardId, { color: cachedColor(score, globalMaxScore, cityConfig, regionType) });
				coloredRegionIds.add(wardId);
			}
		}
	}

	// Selected region highlight.
	if (currentSelectedId !== selectedRegionId) {
		if (currentSelectedId) setState(currentSelectedId, { isSelected: false });
		if (selectedRegionId) setState(selectedRegionId, { isSelected: true });
		currentSelectedId = selectedRegionId;
	}

	// Active connected/hovered highlight (rendered blue).
	const activeConnectedId = hoveredRegionId || connectedRegionId;
	if (currentActiveConnectedId !== activeConnectedId) {
		if (currentActiveConnectedId) setState(currentActiveConnectedId, { isConnected: false });
		if (activeConnectedId) setState(activeConnectedId, { isConnected: true });
		currentActiveConnectedId = activeConnectedId;
	}
}

/**
 * Adds or updates a route line layer on the map
 */
export function updateRouteLayer(
	map: Map,
	routeGeojson: GeoJSON.Feature | GeoJSON.FeatureCollection | null
): void {
	if (map.getLayer('selected-route')) {
		map.removeLayer('selected-route');
	}
	if (map.getSource('selected-route')) {
		map.removeSource('selected-route');
	}

	if (!routeGeojson) return;

	map.addSource('selected-route', {
		type: 'geojson',
		data: routeGeojson as any
	});

	map.addLayer({
		id: 'selected-route',
		type: 'line',
		source: 'selected-route',
		paint: {
			'line-color': '#2563eb',
			'line-width': 4,
			'line-opacity': 0.8
		}
	});
}
