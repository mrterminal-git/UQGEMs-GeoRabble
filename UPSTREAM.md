# Upstream provenance

This project incorporates source code from
[`Vonter/transit-affinity`](https://github.com/Vonter/transit-affinity), originally
created by Vivek Matthew.

- Upstream commit: `323bca90659c52a1196dcf894aff5725541b4067`
- Imported: 26 September 2026
- Upstream licence: MIT; see [`LICENSE`](LICENSE)

The upstream application and processing source was imported into this repository as a
starting point for a South East Queensland transit-affinity map. Existing GeoRabble
files, including the Translink GTFS downloader and the archived UQ St Lucia project,
were retained.

The upstream `.git` directory, editor-specific `.cursor` and `.vscode` settings, and
the Bengaluru boundary dataset at `scripts/geojson/blr.geojson` were not imported.
Those files are not required source code for this project. The validated Brisbane
frontend snapshot is committed so a fresh clone can run immediately; downloaded GTFS
inputs remain excluded from Git and are identified by checksums in build metadata.
