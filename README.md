# transit-affinity

Is your area well connected by public transport? Explore the affinity between different areas of a city, based on it's public transport network: [https://transit-affinity.urbanuru.in/](https://transit-affinity.urbanuru.in/)

## Develop

- Install dependencies with `pnpm install` (or `npm install`)
- Process data with `python3 scripts/parse.py <gtfs_dir> <city_code> [<geojson_path>] [<hexagon_resolution>]`
- Start local dev server with `pnpm run dev` (or `npm run dev`)
- Build site deployment assets with `pnpm run build` (or `npm run build`)

## Architecture

- Data sourced from published [GTFS](https://gtfs.org/) feeds of various transit agencies (stored in [scripts/gtfs/](scripts/gtfs/))
- Processing of data done by [scripts/parse.py](scripts/parse.py)
- Frontend built with [SvelteKit](https://kit.svelte.dev/) and [MapLibre](https://maplibre.org/)
- Hosted on [Cloudflare Pages](https://developers.cloudflare.com/pages/)

## Methodology

GTFS schedule data is parsed for each city, and transit stops are mapped onto a grid of [H3](https://h3geo.org/) hexagons (and, where boundaries are available, administrative wards). For every pair of areas, an affinity score is computed from the number of daily transit trips that directly connect them, so that areas linked by more frequent direct routes score higher. Connectivity is derived by walking the ordered stop sequence of each trip and counting, for every origin area, the trips that reach each reachable destination area. Scores are color-coded from low (red) to high (green), and the routes connecting any selected pair of areas are surfaced alongside.

## Data

The source for the various GTFS datasets used:
- Bengaluru: [bmtc-gtfs](https://github.com/Vonter/bmtc-gtfs) and [bmrcl-gtfs](github.com/Vonter/bmrcl-gtfs)
- Chennai: [ChennaiGTFS](https://github.com/ungalsoththu/ChennaiGTFS)
- Hyderabad: [TGSRTC Open Data](https://www.tgsrtc.telangana.gov.in/open-data)
- Pune: [pmpml-gtfs](https://github.com/croyla/pmpml-gtfs)
- Indian Railways: [indianrailways-gtfs](https://github.com/Neo2308/indianrailways-gtfs)
- Andhra Pradesh: [apsrtc-gtfs](https://github.com/Neo2308/apsrtc-gtfs)

## License

The code is licensed under **MIT**. The data is available under **ODbL**.

## AI Declaration

Components of this repository, including code and documentation, were written with assistance from Claude AI.