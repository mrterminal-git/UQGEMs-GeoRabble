<!-- SEO.svelte -->
<script lang="ts">
	interface Props {
		title?: string;
		description?: string;
		keywords?: string;
		author?: string;
		image?: string;
		url?: string;
		type?: string;
	}

	let {
		title = 'Brisbane Transit Affinity',
		description = 'Explore direct public-transport connectivity between H3 areas and council wards in Brisbane.',
		keywords = 'brisbane,translink,transit,public transport,bus,train,ferry,connectivity,affinity,gtfs,h3,council wards',
		author = 'UQGEMs GeoRabble',
		image = '',
		url = '',
		type = 'website'
	}: Props = $props();
</script>

<svelte:head>
	<!-- Basic Meta Tags -->
	<title>{title}</title>
	<meta name="description" content={description} />
	<meta name="keywords" content={keywords} />
	<meta name="author" content={author} />
	<meta name="robots" content="index, follow" />
	<meta name="viewport" content="width=device-width, initial-scale=1" />

	<!-- Canonical URL -->
	{#if url}<link rel="canonical" href={url} />{/if}

	<!-- Open Graph Tags -->
	<meta property="og:title" content={title} />
	<meta property="og:site_name" content={title} />
	<meta property="og:description" content={description} />
	{#if image}
		<meta property="og:image" content={image} />
		<meta property="og:image:alt" content={title} />
	{/if}
	{#if url}<meta property="og:url" content={url} />{/if}
	<meta property="og:type" content={type} />

	<!-- Twitter Card Tags -->
	<meta name="twitter:card" content={image ? 'summary_large_image' : 'summary'} />
	<meta name="twitter:title" content={title} />
	<meta name="twitter:description" content={description} />
	{#if image}
		<meta name="twitter:image" content={image} />
		<meta name="twitter:image:alt" content={title} />
	{/if}

	<!-- Additional Meta Tags -->
	<meta name="language" content="English" />
	<meta name="distribution" content="global" />
	<meta name="mobile-web-app-capable" content="yes" />
</svelte:head>
