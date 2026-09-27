<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { browser } from '$app/environment';
	import type { Map } from 'maplibre-gl';
	import maplibregl from 'maplibre-gl';
	import { createMap } from '$lib/map';
	import {
		loadRegionData,
		loadConnectingRoutes,
		loadRoutesGeojson,
		loadRegionConnectivity,
		loadRoutes,
		type RegionData
	} from '$lib/data-loader';
	import {
		initializeMapLayers,
		updateMapHighlighting,
		updateRouteLayer,
		resetMapLayerState,
		setRegionSourceData
	} from '$lib/map-layers';
	import type { RegionType, Ward, ConnectivityScore, Route } from '$lib/types';
	import type { CityCode } from '$lib/cityConfigs';
	import { getCityConfig, getDefaultCity, cityConfigs } from '$lib/cityConfigs';
	import RegionTypeToggle from '$lib/components/RegionTypeToggle.svelte';
	import SelectedRegionInfo from '$lib/components/SelectedRegionInfo.svelte';
	import RegionList from '$lib/components/RegionList.svelte';
	import RoutesPanel from '$lib/components/RoutesPanel.svelte';
	import CitySelector from '$lib/components/CitySelector.svelte';

	let map: Map | null = null;
	let mapContainer: HTMLDivElement;
	let selectedWard = $state<Ward | null>(null);
	let selectedConnectedWard = $state<Ward | null>(null);
	let hoveredConnectedWard = $state<string | null>(null);
	let connectivityScores = $state<ConnectivityScore[]>([]);
	let loading = $state(true);
	let loadingMessage = $state('Loading data...');
	let wards = $state<Ward[]>([]);
	let geojsonData = $state<any>(null);
	let connectingRoutes = $state<Route[]>([]);
	let searchQuery = $state('');
	let showSearchResults = $state(false);
	let globalMaxScore = 1;
	let regionType = $state<RegionType>('hexagons');
	let currentCity = $state<CityCode>(getDefaultCity());
	let shareCopied = $state(false);
	let showInfo = $state(false);

	const cityConfig = $derived.by(() => getCityConfig(currentCity));
	const supportedRegions = $derived.by(() => cityConfig.supportedRegions);

	const wardMap = $derived.by(() => {
		const map = new globalThis.Map<string, Ward>();
		for (const ward of wards) {
			map.set(ward.id, ward);
		}
		return map;
	});

	let wardsData: RegionData | null = $state(null);
	let areasData: RegionData | null = $state(null);

	let routesGeojson = $state<GeoJSON.FeatureCollection | null>(null);
	let selectedRouteId = $state<string | null>(null);

	let hoverAnimationFrame: number | null = null;
	let pendingHoverId: string | null = null;

	onMount(async () => {
		try {
			await initializeApp();
		} catch (error) {
			console.error('Error initializing app:', error);
			loadingMessage = 'Error loading data. Please refresh.';
		}
	});

	onDestroy(() => {
		if (hoverAnimationFrame !== null) {
			cancelAnimationFrame(hoverAnimationFrame);
		}
		if (hoverDebounceTimer !== null) {
			clearTimeout(hoverDebounceTimer);
		}
		if (map) {
			map.remove();
		}
	});

	async function initializeApp() {
		loadingMessage = 'Loading data...';

		const urlParams = browser ? $page.url.searchParams : new URLSearchParams();
		const urlCity = urlParams.get('city');
		const urlMode = urlParams.get('mode');
		const urlRegionId = urlParams.get('region');

		if (!Object.keys(cityConfigs).includes(currentCity)) {
			if (urlCity && Object.keys(cityConfigs).includes(urlCity.toLowerCase())) {
				currentCity = urlCity.toLowerCase() as CityCode;
			} else {
				currentCity = getDefaultCity();
			}
		} else if (urlCity && Object.keys(cityConfigs).includes(urlCity.toLowerCase())) {
			const urlCityCode = urlCity.toLowerCase() as CityCode;
			if (currentCity !== urlCityCode) {
				currentCity = urlCityCode;
			}
		}

		if (urlMode === 'wards' || urlMode === 'hexagons') {
			regionType = urlMode;
		} else if (urlMode === 'areas') {
			regionType = 'hexagons';
		} else {
			regionType = supportedRegions.includes('hexagons')
				? 'hexagons'
				: supportedRegions[0] || 'hexagons';
		}

		if (!supportedRegions.includes(regionType)) {
			regionType = supportedRegions.includes('hexagons')
				? 'hexagons'
				: supportedRegions[0] || 'hexagons';
		}

		if (map) {
			map.remove();
			map = null;
		}

		const mapInitPromise = new Promise<Map>((resolve) => {
			const tempMap = createMap(mapContainer, cityConfig);
			tempMap.on('load', () => resolve(tempMap));
		});

		const [data, initializedMap] = await Promise.all([
			loadRegionData(regionType, currentCity),
			mapInitPromise
		]);

		if (!data) return;

		if (regionType === 'wards') {
			wardsData = data;
		} else {
			areasData = data;
		}

		geojsonData = data.geojson;
		wards = data.wards;
		globalMaxScore = data.globalMaxScore;

		map = initializedMap;
		if (map && geojsonData) {
			initializeMapLayers(
				map,
				geojsonData,
				(regionId: string) => {
					selectWard(regionId);
				},
				regionType,
				wards,
				cityConfig
			);

			loading = false;

			schedulePrefetch();

			if (urlRegionId) {
				const region = wardMap.get(urlRegionId);
				if (region) {
					selectWard(urlRegionId);
					map.flyTo({
						center: region.centroid,
						zoom: cityConfig.mapZoom,
						duration: 1000
					});
				} else {
					selectDefaultRegion();
				}
			} else {
				selectDefaultRegion();
			}
		}
	}

	async function handleCityChange(newCity: CityCode) {
		if (map) {
			map.remove();
			map = null;
		}

		currentCity = newCity;
		selectedWard = null;
		selectedConnectedWard = null;
		hoveredConnectedWard = null;
		connectivityScores = [];
		connectingRoutes = [];
		wardsData = null;
		areasData = null;
		geojsonData = null;
		wards = [];
		routesGeojson = null;
		selectedRouteId = null;

		const config = getCityConfig(newCity);
		regionType = config.supportedRegions.includes('hexagons')
			? 'hexagons'
			: config.supportedRegions[0] || 'hexagons';

		loading = true;
		await initializeApp();
	}

	function schedulePrefetch() {
		// Defer prefetch of the other region type so it doesn't compete with the
		// first interaction for CPU/network right after load.
		const run = () => prefetchOtherRegionType();
		if (browser && 'requestIdleCallback' in window) {
			(window as any).requestIdleCallback(run, { timeout: 3000 });
		} else {
			setTimeout(run, 1500);
		}
	}

	async function prefetchOtherRegionType() {
		const otherType: RegionType = regionType === 'wards' ? 'hexagons' : 'wards';
		if (!supportedRegions.includes(otherType)) {
			return;
		}
		try {
			const data = await loadRegionData(otherType, currentCity);
			if (otherType === 'wards') {
				wardsData = data;
			} else {
				areasData = data;
			}
		} catch (error) {
			console.error(`Error prefetching ${otherType} data:`, error);
		}
	}

	function buildShareUrl() {
		const params = new URLSearchParams();
		params.set('city', currentCity);
		const urlMode = regionType === 'hexagons' ? 'areas' : regionType;
		params.set('mode', urlMode);
		if (selectedWard) {
			params.set('region', selectedWard.id);
		}
		return `${$page.url.origin}${$page.url.pathname}?${params.toString()}`;
	}

	async function handleShare() {
		const url = buildShareUrl();
		const shareData = {
			title: cityConfig.siteName,
			text: cityConfig.siteName,
			url
		};

		if (browser && navigator.share) {
			try {
				await navigator.share(shareData);
				return;
			} catch (error) {
				if (error instanceof Error && error.name === 'AbortError') return;
			}
		}

		try {
			await navigator.clipboard.writeText(url);
			shareCopied = true;
			setTimeout(() => (shareCopied = false), 2000);
		} catch (error) {
			console.error('Error sharing:', error);
		}
	}

	function selectDefaultRegion() {
		if (!map) return;

		if (regionType === 'wards') {
			const defaultWardId = cityConfig.defaultWard;
			const defaultWard = defaultWardId ? wardMap.get(defaultWardId) : wards[0];
			if (defaultWard) {
				selectWard(defaultWard.id);
				map.flyTo({
					center: defaultWard.centroid,
					zoom: cityConfig.mapZoom,
					duration: 1000
				});
			}
		} else {
			let defaultHex: Ward | undefined;
			if (cityConfig.defaultSearchTerm) {
				const searchTerm = cityConfig.defaultSearchTerm.toLowerCase();
				for (const ward of wards) {
					if (ward.name.toLowerCase().includes(searchTerm)) {
						defaultHex = ward;
						break;
					}
				}
			}

			if (!defaultHex) {
				defaultHex = wards[0];
			}

			if (defaultHex) {
				selectWard(defaultHex.id);
				map.flyTo({
					center: defaultHex.centroid,
					zoom: cityConfig.mapZoom,
					duration: 1000
				});
			}
		}
	}

	async function selectWard(wardId: string) {
		const ward = wardMap.get(wardId);
		if (!ward || !map || !geojsonData) return;

		if (selectedWard?.id === wardId) {
			selectedWard = null;
			selectedConnectedWard = null;
			hoveredConnectedWard = null;
			connectivityScores = [];
			connectingRoutes = [];
			searchQuery = '';
			showSearchResults = false;
			handleSelectRoute(null);

			updateMapHighlighting(
				map,
				regionType,
				null,
				null,
				null,
				[],
				globalMaxScore,
				cityConfig
			);
			return;
		}

		selectedWard = ward;
		selectedConnectedWard = null;
		hoveredConnectedWard = null;
		connectingRoutes = [];
		searchQuery = '';
		showSearchResults = false;

		map.flyTo({
			center: ward.centroid,
			zoom: cityConfig.mapZoom,
			duration: 1000
		});

		const connections = await loadRegionConnectivity(regionType, wardId, currentCity);

		// Guard against a newer selection having superseded this one while awaiting
		if (selectedWard?.id !== wardId) return;

		connectivityScores = Object.entries(connections).map(([id, score]) => ({
			wardId: id,
			score: score as number,
			normalizedScore: (score as number) / globalMaxScore
		}));

		connectivityScores.sort((a, b) => b.score - a.score);

		updateMapHighlighting(
			map,
			regionType,
			wardId,
			null,
			null,
			connectivityScores,
			globalMaxScore,
			cityConfig
		);
	}

	async function selectConnectedWard(wardId: string) {
		if (!selectedWard || !map || !geojsonData) return;

		const ward = wardMap.get(wardId);
		if (!ward) return;

		if (selectedConnectedWard?.id === wardId) {
			selectedConnectedWard = null;
			hoveredConnectedWard = null;
			connectingRoutes = [];
			handleSelectRoute(null);

			updateMapHighlighting(
				map,
				regionType,
				selectedWard.id,
				null,
				null,
				connectivityScores,
				globalMaxScore,
				cityConfig
			);
			return;
		}

		selectedConnectedWard = ward;
		hoveredConnectedWard = null;
		handleSelectRoute(null);

		map.flyTo({
			center: ward.centroid,
			zoom: cityConfig.mapZoom,
			duration: 1000
		});

		const [routeData, routesLookup] = await Promise.all([
			loadConnectingRoutes(regionType, selectedWard.id, wardId, currentCity),
			loadRoutes(currentCity)
		]);
		connectingRoutes = routeData
			.map((routeData: any) => ({
				...routesLookup[routeData.route_id],
				...routeData
			}))
			.sort((a: any, b: any) => (b.trip_count || 0) - (a.trip_count || 0));

		updateMapHighlighting(
			map,
			regionType,
			selectedWard.id,
			wardId,
			null,
			connectivityScores,
			globalMaxScore,
			cityConfig
		);
	}

	let hoverDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	function handleHoverConnectedWard(wardId: string | null) {
		hoveredConnectedWard = wardId;
		pendingHoverId = wardId;

		if (hoverDebounceTimer !== null) {
			clearTimeout(hoverDebounceTimer);
			hoverDebounceTimer = null;
		}

		if (hoverAnimationFrame !== null) {
			cancelAnimationFrame(hoverAnimationFrame);
		}

		hoverDebounceTimer = setTimeout(() => {
			hoverAnimationFrame = requestAnimationFrame(() => {
				if (map && pendingHoverId === wardId && geojsonData && selectedWard) {
					updateMapHighlighting(
						map,
						regionType,
						selectedWard.id,
						selectedConnectedWard?.id || null,
						pendingHoverId,
						connectivityScores,
						globalMaxScore,
						cityConfig
					);
				}
				hoverAnimationFrame = null;
			});
			hoverDebounceTimer = null;
		}, 16);
	}

	function handleSearchInput(query: string) {
		searchQuery = query;
		showSearchResults = query.length > 0;
	}

	function selectWardFromSearch(wardId: string) {
		selectWard(wardId);
	}

	async function handleSelectRoute(routeId: string | null) {
		selectedRouteId = routeId;
		if (!map) return;

		if (!routeId) {
			updateRouteLayer(map, null);
			return;
		}

		// Lazy-load the (large) routes geometry only when a route is first selected.
		if (!routesGeojson) {
			routesGeojson = await loadRoutesGeojson(currentCity);
		}

		// Guard against the selection changing while the geometry was loading.
		if (selectedRouteId !== routeId || !map) return;

		if (!routesGeojson) {
			updateRouteLayer(map, null);
			return;
		}

		const feature = routesGeojson.features.find((f) => f.properties?.route_id === routeId);
		if (feature) {
			updateRouteLayer(map, feature);
		} else {
			updateRouteLayer(map, null);
		}
	}

	async function switchRegionType(newType: RegionType) {
		if (newType === regionType) return;

		selectedWard = null;
		selectedConnectedWard = null;
		hoveredConnectedWard = null;
		connectivityScores = [];
		connectingRoutes = [];
		searchQuery = '';
		showSearchResults = false;

		const cachedData = newType === 'wards' ? wardsData : areasData;
		const hasCachedData = !!cachedData;

		if (!hasCachedData) {
			loading = true;
			loadingMessage = `Loading...`;
		}

		try {
			let data: RegionData;

			if (hasCachedData) {
				data = cachedData;
			} else {
				data = await loadRegionData(newType, currentCity);
			}

			if (newType === 'wards') {
				wardsData = data;
			} else {
				areasData = data;
			}

			regionType = newType;
			geojsonData = data.geojson;
			wards = data.wards;
			globalMaxScore = data.globalMaxScore;

			resetMapLayerState();

			if (map && geojsonData) {
				const source = map.getSource('wards') as maplibregl.GeoJSONSource;
				if (source) {
					setRegionSourceData(map, geojsonData, regionType, wards);

					// Update outline based on region type - no borders for hexagons
					const isHex = regionType === 'hexagons';
					map.setPaintProperty('wards-outline', 'line-width', [
						'case',
						['==', ['feature-state', 'isSelected'], true],
						isHex ? 0 : 4,
						['==', ['feature-state', 'isConnected'], true],
						isHex ? 0 : 3,
						0
					]);
					map.setPaintProperty('wards-outline', 'line-opacity', [
						'case',
						['==', ['feature-state', 'isSelected'], true],
						isHex ? 0 : 1.0,
						['==', ['feature-state', 'isConnected'], true],
						isHex ? 0 : 0.8,
						isHex ? 0 : 0.2
					]);

					if (source.loaded()) {
						requestAnimationFrame(() => {
							selectDefaultRegion();
						});
					} else {
						map.once('sourcedata', () => {
							if (map && source.loaded()) {
								requestAnimationFrame(() => {
									selectDefaultRegion();
								});
							}
						});
					}
				} else {
					initializeMapLayers(
						map,
						geojsonData,
						(regionId: string) => {
							selectWard(regionId);
						},
						regionType,
						wards,
						cityConfig
					);
					requestAnimationFrame(() => {
						selectDefaultRegion();
					});
				}
			}

			if (hasCachedData) {
				loading = false;
			}

			if (newType === 'wards' && !areasData) {
				prefetchOtherRegionType();
			} else if (newType === 'hexagons' && !wardsData) {
				prefetchOtherRegionType();
			}

			if (!hasCachedData) {
				loading = false;
			}
		} catch (error) {
			console.error('Error switching region type:', error);
			loadingMessage = 'Error loading data. Please refresh.';
			loading = false;
		}
	}
</script>

<div class="flex flex-col md:flex-row h-screen w-screen">
	<!-- Map Container -->
	<div class="flex-1 md:flex-1 relative h-[33vh] md:h-auto" bind:this={mapContainer}>
		{#if loading}
			<div class="absolute inset-0 flex items-center justify-center bg-gray-100 z-50">
				<div class="text-center">
					<div
						class="animate-spin rounded-full h-12 w-12 border-b-2 border-black mx-auto mb-4"
					></div>
					<p class="text-black" style="font-family: ui-sans-serif, system-ui, sans-serif;">
						{loadingMessage}
					</p>
				</div>
			</div>
		{/if}
	</div>

	<!-- Sidebar -->
	<div
		class="w-full md:w-96 overflow-y-auto flex flex-col h-[67vh] md:h-screen md:relative z-40"
		style="background-color: rgb(245, 241, 232);"
	>
		<div class="p-4">
			<div class="flex items-center justify-between gap-2">
				<h1
					class="text-sm font-bold text-black flex items-center gap-2 flex-wrap"
					style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; letter-spacing: 0.35px;"
				>
					<CitySelector {currentCity} onCityChange={handleCityChange} />
					<span>TRANSIT AFFINITY</span>
				</h1>

				<div class="flex items-center gap-2 shrink-0">
					<button
						type="button"
						onclick={handleShare}
						title="Share"
						class="flex items-center gap-1 rounded border border-black/30 h-7 px-2 text-xs font-bold text-black cursor-pointer hover:bg-black/5 transition-colors"
						style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; letter-spacing: 0.35px;"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							aria-hidden="true"
						>
							<circle cx="18" cy="5" r="3" />
							<circle cx="6" cy="12" r="3" />
							<circle cx="18" cy="19" r="3" />
							<line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
							<line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
						</svg>
						<span>{shareCopied ? 'COPIED' : 'SHARE'}</span>
					</button>

					<button
						type="button"
						onclick={() => (showInfo = true)}
						title="About"
						aria-label="About"
						class="flex items-center justify-center rounded border border-black/30 h-7 w-7 text-black cursor-pointer hover:bg-black/5 transition-colors"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="16"
							height="16"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							aria-hidden="true"
						>
							<circle cx="12" cy="12" r="10" />
							<line x1="12" y1="16" x2="12" y2="12" />
							<line x1="12" y1="8" x2="12.01" y2="8" />
						</svg>
					</button>
				</div>
			</div>

			<RegionTypeToggle {regionType} {supportedRegions} onSwitch={switchRegionType} />
		</div>

		{#if selectedWard}
			{#if connectivityScores.length > 0}
				<SelectedRegionInfo selectedRegion={selectedWard.name} />
			{/if}

			<RegionList
				{connectivityScores}
				{wards}
				selectedConnectedWardId={selectedConnectedWard?.id || null}
				{regionType}
				onSelectConnectedWard={selectConnectedWard}
				onHoverConnectedWard={handleHoverConnectedWard}
			/>

			{#if selectedConnectedWard}
				<RoutesPanel
					{connectingRoutes}
					{regionType}
					{selectedRouteId}
					onSelectRoute={handleSelectRoute}
				/>
			{/if}
		{:else}
			<div
				class="p-4 text-black text-sm"
				style="font-family: ui-sans-serif, system-ui, sans-serif;"
			>
				Select a {regionType === 'wards' ? 'ward' : 'area'} to see it's affinity to other
				{regionType === 'wards' ? 'wards' : 'areas'}.
			</div>
		{/if}
	</div>
</div>

<svelte:window onkeydown={(e) => e.key === 'Escape' && (showInfo = false)} />

{#if showInfo}
	<div
		class="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4"
		role="presentation"
		onclick={(e) => e.target === e.currentTarget && (showInfo = false)}
	>
		<div
			class="relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-lg p-6 shadow-xl"
			style="background-color: rgb(245, 241, 232);"
			role="dialog"
			aria-modal="true"
			aria-labelledby="info-title"
			tabindex="-1"
		>
			<button
				type="button"
				onclick={() => (showInfo = false)}
				title="Close"
				aria-label="Close"
				class="absolute right-3 top-3 flex items-center justify-center rounded p-1 text-black cursor-pointer hover:bg-black/5 transition-colors"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<line x1="18" y1="6" x2="6" y2="18" />
					<line x1="6" y1="6" x2="18" y2="18" />
				</svg>
			</button>

			<h2
				id="info-title"
				class="mb-3 pr-6 text-sm font-bold text-black"
				style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; letter-spacing: 0.35px;"
			>
				ABOUT TRANSIT AFFINITY
			</h2>

			<div
				class="space-y-3 text-sm leading-relaxed text-black"
				style="font-family: ui-sans-serif, system-ui, sans-serif;"
			>
				<p>
					Transit Affinity visualizes the public transport network and connectivity between 
					various areas of a city.
				</p>
				<p>
					Stops and schedules are taken from GTFS data, then mapped onto a grid of H3
					hexagon areas or wards. For each pair of areas, a score is computed based on
					the number of daily transit trips that directly connect the areas. Areas
					linked by more frequent direct routes score higher. These areas are considered
					to have higher transit affinity.
				</p>
				<p>
					Select any area on the map to see its connectedness or affinity to the rest of
					the city, color-coded from low (red) to high (green).
				</p>
				<p>
					Select a paired area to view the routes that connect the two areas together.
				</p>
			</div>

			<a
				href="https://github.com/Vonter/transit-affinity"
				target="_blank"
				rel="noopener noreferrer"
				class="mt-4 inline-flex items-center gap-2 rounded border border-black/30 px-3 py-1.5 text-xs font-bold text-black hover:bg-black/5 transition-colors"
				style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; letter-spacing: 0.35px;"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="currentColor"
					aria-hidden="true"
				>
					<path
						d="M12 .5C5.37.5 0 5.87 0 12.5c0 5.3 3.44 9.8 8.21 11.39.6.11.82-.26.82-.58 0-.29-.01-1.04-.02-2.04-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.09-.75.08-.73.08-.73 1.2.08 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 3-.4c1.02 0 2.05.14 3 .4 2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.49 5.92.43.37.81 1.1.81 2.22 0 1.6-.01 2.89-.01 3.29 0 .32.22.7.83.58A12.01 12.01 0 0 0 24 12.5C24 5.87 18.63.5 12 .5z"
					/>
				</svg>
				<span>VIEW ON GITHUB</span>
			</a>
		</div>
	</div>
{/if}

<style>
	:global(body) {
		margin: 0;
		padding: 0;
		overflow: hidden;
	}

	:global(.maplibregl-popup-content) {
		font-family: ui-sans-serif, system-ui, sans-serif;
	}

	:global(body) {
		font-family: ui-sans-serif, system-ui, sans-serif;
		font-size: 16px;
		color: rgb(0, 0, 0);
	}
</style>
