# Brisbane Transit Affinity

An interactive map of scheduled public-transport connectivity within the
Brisbane City Council local government area. Select either an H3 area or one of
Brisbane's 26 council wards to see which other regions can be reached on the same
scheduled trip.

This project is based on
[`Vonter/transit-affinity`](https://github.com/Vonter/transit-affinity). See
[`UPSTREAM.md`](UPSTREAM.md) for the imported revision and licence provenance.

## Open the map

The generated Brisbane dataset is committed, so no Python processing is needed
for normal frontend development.

```powershell
pnpm.cmd install
pnpm.cmd run dev -- --open
```

If `pnpm.cmd` is not found, install Node.js and enable pnpm through Corepack:

```powershell
corepack enable
corepack prepare pnpm@12.6.0 --activate
```

Then open <http://localhost:5173/>. Use the **Areas / Wards** control to switch
between H3 hexagons and the 26 council wards.

## Current model

- Scope: Brisbane City Council local government area
- Regions: H3 resolution 8 and all 26 council wards
- Schedule: services whose `calendar.txt` entry runs on a generic Wednesday
- Journeys: direct trips only; transfers are not included
- Modes: every scheduled trip has equal weight, including ferries
- H3 smoothing: Vonter's original destination-side "osmosis" at 10%, 1%, and
  0.1% over the next three H3 rings
- Walking: not modelled in this version

The score is based on scheduled trips, not the number of stops in a region. A
trip contributes once to each distinct pair of regions it visits. The frontend
shows half of the symmetric raw count as an approximate directional service
count. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the complete data flow
and limitations.

## Rebuild the Brisbane data

The Python project requires Python 3.13 and uses
[`uv`](https://docs.astral.sh/uv/) for reproducible dependencies.

```powershell
uv sync --project scripts
.\scripts\.venv\Scripts\python.exe scripts\download_seq_gtfs.py
.\scripts\.venv\Scripts\python.exe scripts\download_brisbane_boundaries.py
.\scripts\.venv\Scripts\python.exe scripts\parse.py SEQ_GTFS\SEQ_GTFS.zip brisbane scripts\geojson\brisbane_wards.geojson 8 --crop-boundary scripts\geojson\brisbane_lga.geojson --skip-isochrones
.\scripts\.venv\Scripts\python.exe scripts\validate_generated_data.py static\data\brisbane
```

The first two downloaders validate and atomically replace their outputs. The
build writes source URLs, retrieval times, checksums, feed validity dates, and
processing choices to
[`static/data/brisbane/build_metadata.json`](static/data/brisbane/build_metadata.json).
Because Translink's URL serves its current feed, rebuilding later can change the
results.

## Checks

```powershell
pnpm.cmd run check
pnpm.cmd run build
.\scripts\.venv\Scripts\python.exe -m unittest discover -s scripts\tests -v
.\scripts\.venv\Scripts\python.exe scripts\validate_generated_data.py static\data\brisbane
```

## Structure

- `src/`: SvelteKit and MapLibre interactive map
- `scripts/`: GTFS, H3, ward, route, chunking, and validation pipeline
- `scripts/geojson/`: reproducible Brisbane ward and LGA boundaries
- `static/data/brisbane/`: browser-ready generated snapshot
- `SEQ_GTFS/`: locally downloaded Translink input (ignored by Git)
- `archive/`: the previous UQ St Lucia project; not part of this application

## Data sources and licences

- Timetables and stops: [Translink open data](https://translink.com.au/about-translink/open-data)
- Ward boundaries: [Queensland Government administrative boundaries](https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/AdministrativeBoundaries/MapServer/8)

The application code is MIT licensed; see [`LICENSE`](LICENSE). Source-data
attribution and licence details are recorded beside the downloaded or generated
data in [`SEQ_GTFS/README.md`](SEQ_GTFS/README.md) and
[`scripts/geojson/README.md`](scripts/geojson/README.md).

## AI declaration

Parts of the code and documentation were developed with AI assistance and were
validated with automated checks and generated-data consistency tests.
