# Processed data

This directory contains reproducible analysis-ready and visualisation-ready outputs.

Phase 2 creates `synthetic/` containing a GeoTIFF terrain, a multi-layer GeoPackage and provenance metadata. The directory is generated and ignored by Git.

Phase 6 creates `lod1/` containing the authoritative building GeoPackage, local-origin
GLB presentation mesh, display samples, origin metadata and hash-based manifest. These
products are generated from the Phase 4/5 public-data inputs and ignored by Git.

Phase 7 creates `lod2/` containing the all-building feasibility record, accepted 3D roof
planes and ridges, mixed LoD1/LoD2 local-origin GLB, fit samples and hash-based manifest.
Rejected roofs retain the Phase 6 LoD1 shell. These generated products are ignored by
Git.

Phase 8 creates `utilities/` containing the standardised public utility GeoPackage and
hash-based manifest. Utility geometry remains 2D unless a source has a verified vertical
datum or usable surveyed depth; the current public pilot has neither.

Phase 9 creates `scene/` containing the integrated-scene display configuration and a
hash-based manifest. The rendered HTML and figures are stored under `reports/`.
Utility terrain drapes are display-only and do not alter the Phase 8 source geometry.

Phase 10 creates `validation/phase10_manifest.json`, which records the hashes of the
consolidated local reproducibility evidence. The audit does not modify authoritative
source geometry or delete earlier outputs.
