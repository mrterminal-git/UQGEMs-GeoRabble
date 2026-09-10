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

Phase 8 records public-utility source coverage, standardised assets and validation
issues. Phase 9 writes scene layer/control inventories, a cross-section profile and
`phase9_scene.json`, which records configuration, output metadata and 19 checks.

Phase 10 writes the consolidated phase/notebook/register/manifest/hash/CRS/figure/
software/quality evidence and `phase10_reproducibility.json`. Separate fresh-kernel
notebook copies are retained below `phase10_notebooks/`.

Phase 11 writes the material provenance inventory, a per-building triangle/UV audit and
`phase11_skins.json`. The tables distinguish observed roof/terrain imagery from
procedural facade materials and retain the imagery/LiDAR date mismatch.
