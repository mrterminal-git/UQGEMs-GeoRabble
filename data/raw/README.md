# Raw data

Store original ELVIS, building-footprint, imagery and authorised utility downloads here. Do not modify source files in place.

For Phase 3, place the six unchanged ELVIS order zip files in `elvis/incoming/`. The pipeline extracts byte-for-byte working copies of the selected 2019 DEM, LAZ and supplied metadata to `elvis/selected/brisbane_2019/`; it never edits or overwrites the incoming archives.

The pipeline also caches small source extracts below `qld_buildings/`, `qld_imagery/`, `openstreetmap/` and `uq_public/`. These raw files are ignored by Git. Their sources, licences, dates and SHA-256 checksums are recorded in `../dataset_register.csv` and the generated Phase 3 inventory report.

Phase 8 caches immutable public API responses below `public_utilities/`: BCC dataset
metadata and pilot records, plus Urban Utilities item/service metadata and one GeoJSON
extract per published water or sewer layer. Existing source snapshots are not silently
refreshed or overwritten.
