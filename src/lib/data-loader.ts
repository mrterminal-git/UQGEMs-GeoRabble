import type { RegionType, Ward, Route, GeoJSONFeatureCollection } from './types';
import type { CityCode } from './cityConfigs';

// Trip counts in the data represent trips in both directions. The site shows
// connectivity directionally, so every count is halved as it enters the frontend.
function toDirectionalCount(count: number): number {
	return count / 2;
}

export interface RegionData {
	wards: Ward[];
	geojson: GeoJSONFeatureCollection;
	globalMaxScore: number;
}

export async function loadRegionData(
	type: RegionType,
	cityCode: CityCode = 'brisbane'
): Promise<RegionData> {
	const dataPath = `/data/${cityCode}`;
	const regionFile = type === 'wards' ? 'wards.json' : 'hexagons.json';
	const geojsonFile = type === 'wards' ? 'wards.geojson' : 'h3_hexagons.geojson';

	// Connectivity is no longer loaded up front — only the selected region's row
	// is fetched on demand. routes.json is deferred to loadRoutes (only needed
	// once a connected pair is selected). We only need the precomputed global max here.
	const [regionRes, geojsonRes, globalMaxScore] = await Promise.all([
		fetch(`${dataPath}/${regionFile}`),
		fetch(`${dataPath}/${geojsonFile}`),
		loadGlobalMaxScore(type, cityCode)
	]);

	return {
		wards: await regionRes.json(),
		geojson: await geojsonRes.json(),
		globalMaxScore
	};
}

let routesCache: Record<string, Record<string, Route>> = {};

export async function loadRoutes(cityCode: CityCode = 'brisbane'): Promise<Record<string, Route>> {
	if (routesCache[cityCode]) {
		return routesCache[cityCode];
	}
	const response = await fetch(`/data/${cityCode}/routes.json`);
	routesCache[cityCode] = await response.json();
	return routesCache[cityCode];
}

let cacheIndexCache: Record<string, Record<string, string>> = {};

async function loadCacheIndex(
	type: RegionType,
	cityCode: CityCode = 'brisbane'
): Promise<Record<string, string>> {
	const cacheKey = `${cityCode}-${type}`;
	if (cacheIndexCache[cacheKey]) {
		return cacheIndexCache[cacheKey];
	}

	const dataPath = `/data/${cityCode}`;
	const indexPath =
		type === 'wards'
			? `${dataPath}/routes_cache_chunks/index.json`
			: `${dataPath}/h3_routes_cache_chunks/index.json`;

	const response = await fetch(indexPath);
	cacheIndexCache[cacheKey] = await response.json();
	return cacheIndexCache[cacheKey];
}

function toDirectionalRoute(route: Route): Route {
	if (route.trip_count === undefined || route.trip_count === null) {
		return route;
	}
	return { ...route, trip_count: toDirectionalCount(route.trip_count) };
}

export async function loadConnectingRoutes(
	type: RegionType,
	fromRegionId: string,
	toRegionId: string,
	cityCode: CityCode = 'brisbane'
): Promise<Route[]> {
	try {
		const index = await loadCacheIndex(type, cityCode);
		const chunkFilename = index[fromRegionId];

		if (!chunkFilename) {
			return [];
		}

		const dataPath = `/data/${cityCode}`;
		const chunkPath =
			type === 'wards'
				? `${dataPath}/routes_cache_chunks/${chunkFilename}`
				: `${dataPath}/h3_routes_cache_chunks/${chunkFilename}`;

		const response = await fetch(chunkPath);
		const chunkData = await response.json();

		const connections = chunkData[fromRegionId];
		if (connections && connections[toRegionId]) {
			return connections[toRegionId].map(toDirectionalRoute);
		}

		for (const regionId in chunkData) {
			if (regionId === fromRegionId) {
				const regionConnections = chunkData[regionId];
				return (regionConnections?.[toRegionId] || []).map(toDirectionalRoute);
			}
		}

		return [];
	} catch (error) {
		console.error('Error loading connecting routes:', error);
		return [];
	}
}

function connectivityDir(type: RegionType): string {
	return type === 'wards' ? 'connectivity_chunks' : 'h3_connectivity_chunks';
}

let connectivityIndexCache: Record<string, Record<string, string>> = {};
let globalMaxScoreCache: Record<string, number> = {};

export async function loadGlobalMaxScore(
	type: RegionType,
	cityCode: CityCode = 'brisbane'
): Promise<number> {
	const cacheKey = `${cityCode}-${type}`;
	if (globalMaxScoreCache[cacheKey] !== undefined) {
		return globalMaxScoreCache[cacheKey];
	}
	try {
		const response = await fetch(`/data/${cityCode}/${connectivityDir(type)}/meta.json`);
		const meta = await response.json();
		globalMaxScoreCache[cacheKey] = meta.globalMaxScore
			? toDirectionalCount(meta.globalMaxScore)
			: 1;
	} catch {
		globalMaxScoreCache[cacheKey] = 1;
	}
	return globalMaxScoreCache[cacheKey];
}

async function loadConnectivityIndex(
	type: RegionType,
	cityCode: CityCode = 'brisbane'
): Promise<Record<string, string>> {
	const cacheKey = `${cityCode}-${type}`;
	if (connectivityIndexCache[cacheKey]) {
		return connectivityIndexCache[cacheKey];
	}
	const response = await fetch(`/data/${cityCode}/${connectivityDir(type)}/index.json`);
	connectivityIndexCache[cacheKey] = await response.json();
	return connectivityIndexCache[cacheKey];
}

export async function loadRegionConnectivity(
	type: RegionType,
	regionId: string,
	cityCode: CityCode = 'brisbane'
): Promise<Record<string, number>> {
	try {
		const index = await loadConnectivityIndex(type, cityCode);
		const chunkFilename = index[regionId];
		if (!chunkFilename) return {};

		const response = await fetch(`/data/${cityCode}/${connectivityDir(type)}/${chunkFilename}`);
		const chunkData = await response.json();
		const connectivity: Record<string, number> = chunkData[regionId] || {};
		return Object.fromEntries(
			Object.entries(connectivity).map(([id, count]) => [id, toDirectionalCount(count)])
		);
	} catch (error) {
		console.error('Error loading region connectivity:', error);
		return {};
	}
}

export async function loadRoutesGeojson(
	cityCode: CityCode = 'brisbane'
): Promise<GeoJSON.FeatureCollection | null> {
	try {
		const response = await fetch(`/data/${cityCode}/routes.geojson`);
		if (!response.ok) return null;
		return await response.json();
	} catch {
		return null;
	}
}
