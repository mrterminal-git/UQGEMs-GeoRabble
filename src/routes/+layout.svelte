<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.ico';
	import SEO from '$lib/components/SEO.svelte';
	import { page } from '$app/stores';
	import { browser } from '$app/environment';
	import { getCityConfig, getDefaultCity } from '$lib/cityConfigs';
	import type { CityCode } from '$lib/cityConfigs';

	let { children } = $props();

	// Get city from URL or default
	// Only access searchParams in browser (not during prerendering)
	const cityCode = $derived.by(() => {
		if (!browser) return getDefaultCity();
		const urlCity = $page.url.searchParams.get('city');
		return (urlCity?.toLowerCase() as CityCode) || getDefaultCity();
	});

	const cityConfig = $derived.by(() => getCityConfig(cityCode));
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<SEO
	title={cityConfig.siteName}
	description="Visualize the public transport network and connectivity between various areas of {cityConfig.name}."
/>

{@render children()}
