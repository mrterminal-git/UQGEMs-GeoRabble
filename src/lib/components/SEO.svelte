<!-- SEO.svelte -->
<script lang="ts">
	const SITE_URL = 'https://transit-affinity.urbanuru.in';

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
		title = 'Transit Affinity',
		description = 'Visualize the public transport network and connectivity between various areas of a city.',
		keywords = 'bmtc,bmrcl,namma metro,transit,public transport,bus,metro,connectivity,affinity,accessibility,bengaluru,bangalore,blr,chennai,hyderabad,gtfs,urbanuru',
		author = 'Vivek Matthew',
		image = `${SITE_URL}/sharecard.jpg`,
		url = SITE_URL,
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
	<link rel="canonical" href={url} />

	<!-- Open Graph Tags -->
	<meta property="og:title" content={title} />
	<meta property="og:site_name" content={title} />
	<meta property="og:description" content={description} />
	<meta property="og:image" content={image} />
	<meta property="og:image:alt" content={title} />
	<meta property="og:url" content={url} />
	<meta property="og:type" content={type} />

	<!-- Twitter Card Tags -->
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content={title} />
	<meta name="twitter:description" content={description} />
	<meta name="twitter:image" content={image} />
	<meta name="twitter:image:alt" content={title} />

	<!-- Additional Meta Tags -->
	<meta name="language" content="English" />
	<meta name="distribution" content="global" />
	<meta name="mobile-web-app-capable" content="yes" />
</svelte:head>
