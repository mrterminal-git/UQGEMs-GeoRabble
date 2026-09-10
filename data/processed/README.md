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
