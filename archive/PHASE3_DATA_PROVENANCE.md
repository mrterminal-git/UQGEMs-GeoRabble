# Phase 3 data acquisition and provenance

Phase 3 is scoped to the public-data prototype requested before approaching UQ. It acquires and validates elevation, footprint, imagery and public campus-reference data for the 500 m by 500 m pilot area. UQ-controlled BIM and utility data are deliberately recorded as deferred rather than treated as missing public data.

## Pilot area

- Intended working CRS: GDA2020 / MGA zone 56 (`EPSG:7856`)
- Bounds: E 501103.215–501603.215, N 6958210.027–6958710.027
- WGS84 bounds: 153.0111692, -27.4997572 to 153.0162307, -27.4952427
- Observed native horizontal CRS of the selected 2019 elevation products: GDA94 / MGA zone 56 (`EPSG:28356`)
- Vertical datum for selected elevation products: Australian Height Datum (AHD), using AUSGeoid09 according to the supplied metadata

The ELVIS order interface requested GDA2020, but both the GeoTIFF and LAZ headers identify the delivered 2019 source as `EPSG:28356`, consistent with the supplied XML. Phase 4 must perform and document the transformation to `EPSG:7856`; Phase 3 does not silently relabel the data.

## Source roles

| Source | Role | Use constraint |
|---|---|---|
| ELVIS Brisbane 2019 classified LiDAR | Building heights and roof analysis | Supplied XML says Limited Use Licence and State copyright; verify publication rights |
| ELVIS Brisbane 2019 1 m DEM | Terrain | Confirmed CRS, coverage and AHD metadata before modelling |
| Queensland generated building outlines | Primary public footprint candidate | CC BY 4.0; reconcile with LiDAR and imagery |
| Queensland topographic building areas | Secondary footprints/names | CC BY 4.0; feature currency varies |
| OpenStreetMap extract | Prototype footprints and names | ODbL 1.0; attribution and share-alike obligations apply |
| Queensland latest public imagery | Visual alignment check | CC BY 4.0; accuracy and capture date are project-specific |
| UQ St Lucia campus-map PDF | Building-number/name reference | UQ copyright; do not trace into or redistribute as GIS data |
| UQ BIM, digital twin and utilities | Future authoritative institutional inputs | Permission, security and publication conditions required |

The machine-readable record is `data/dataset_register.csv`. Checksums for local source files and validation results are written to `reports/tables/phase3_inventory.json`.

## Reproduce the acquisition

Keep all six ELVIS zip files in `data/raw/elvis/incoming/`, then run:

```powershell
conda run --name uq-gis python pipelines/run_phase3.py
```

The pipeline does not overwrite existing raw downloads. Delete or move a particular cached public source only if you intentionally want to acquire a fresh copy. Original ELVIS archives are never modified.

## Interpretation limits

- Passing Phase 3 means the sources are present, readable, spatially aligned at metadata/bounds level and documented. It does not establish modelling quality.
- Point density, classification quality, ground/DEM agreement and roof reconstruction suitability belong to Phase 5.
- The LiDAR may be processed for the prototype, but its supplied Limited Use Licence should be clarified before distributing source data or a public LiDAR-derived model.
- Public building polygons are candidates, not UQ-authoritative BIM footprints.
- No utility lines, asset locations or depths are inferred from imagery, surface clues or non-authoritative context.
