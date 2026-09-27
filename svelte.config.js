import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://svelte.dev/docs/kit/integrations
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	// precompress emits .br/.gz alongside built assets (incl. the large *.json
	// data files) for hosts that serve precompressed static files.
	kit: { adapter: adapter({ precompress: true }) }
};

export default config;
