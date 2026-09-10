# Tables

Generated environment, provenance and data-quality reports are written here.
`phase5_preparation.json` records the crop, filtering, classification, density,
ground-to-DTM comparison, output metadata and 22 decision-gate checks. The adjacent
PDAL JSON files preserve the exact streaming crop pipeline and its metadata.

Phase 6 writes per-building metrics, suspicious-height and potential source-mismatch
tables plus `phase6_lod1.json`, which records modelling statistics, mesh topology and 23
decision-gate checks.

Phase 7 writes all-building feasibility, accepted plane metrics and manual-review tables
plus `phase7_lod2.json`, which records selective roof results, the mixed-model topology
and 21 decision-gate checks.
