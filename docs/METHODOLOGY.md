# Methodology

## What the map answers

For a selected Brisbane region, the map shows how many scheduled direct trips
also visit every other region. It supports two independently processed region
systems:

- H3 resolution 8 cells (labelled **Areas** in the interface)
- Brisbane City Council's 26 electoral wards

The present score is a service-frequency measure. It is not a journey planner,
travel-time estimate, population-accessibility score, or walking model.

## Processing flow

1. `download_seq_gtfs.py` downloads and validates Translink's current South East
   Queensland GTFS archive.
2. `download_brisbane_boundaries.py` downloads the official ward layer, checks
   for exactly 26 unique wards, and dissolves them into the BCC LGA boundary.
3. `parse.py` selects services marked active on Wednesday in `calendar.txt`.
4. Stops outside the BCC boundary are removed. Trips with fewer than two
   surviving stops and routes with no surviving trips are removed.
5. Each remaining stop is assigned to one H3 cell and, where covered by the
   official geometry, one ward.
6. Every trip is reduced to the set of regions it visits. That trip adds one to
   every distinct region pair in that set. Stop count does not multiply the
   score, and there is no transfer between trips.
7. H3 scores receive the upstream destination-side smoothing described below.
   Ward scores do not.
8. Route metadata and route geometry are generated for the selected pairs;
   geometry is clipped to the BCC boundary.
9. Large connectivity and route dictionaries are split into indexed chunks so
   the browser fetches only the selected region's data.

## Symmetry and the displayed number

The processor writes every connection in both directions. It also combines the
scheduled trips travelling each physical direction into the same symmetric
region-pair score. The frontend divides raw connectivity and per-route counts by
two, preserving the behaviour of the upstream application and approximating a
one-direction service count.

This is only an approximation when service levels differ by direction. A later
model should retain ordered origin/destination pairs instead of halving a
symmetric total.

## H3 destination smoothing ("osmosis")

For every non-zero H3 destination score, the processor adds a decayed copy to
nearby destination cells:

| H3 distance from destination | Added share |
| ---------------------------- | ----------: |
| 1 ring                       |         10% |
| 2 rings                      |          1% |
| 3 rings                      |        0.1% |

Values are accumulated and rounded to whole numbers. The selected source cell
itself is not expanded into a walking catchment. Consequently, two adjacent
source cells can still produce sharply different maps—the issue that motivates
the planned walkable source and destination catchments.

## Transport modes

The pipeline does not assign different values by `route_type`. A scheduled bus,
train, light-rail, or ferry trip contributes one trip under the same rules.
Ferries therefore work without a separate scoring branch when they are present
in the Translink GTFS feed.

## Wednesday semantics

"Wednesday" currently means any service with `wednesday=1` in GTFS
`calendar.txt`; it is not a specific calendar date or multi-week average. The
current loader does not apply `calendar_dates.txt` exceptions. The exact feed
snapshot and validity dates are recorded in `build_metadata.json`.

## Deliberately deferred work

This version does not include walking paths, OpenStreetMap routing, exponential
walking-time decay, maximum walking time, or transfers. Those changes should be
implemented as a new scoring model rather than silently folded into this
Brisbane baseline.
