# Phase 4 coordinate-system normalisation

All GIS modelling products use GDA2020 / MGA zone 56 (`EPSG:7856`) horizontally and metres. Elevation remains in Australian Height Datum (AHD). Raw files remain unchanged.

## GDA94 to GDA2020 operation

The 2019 ELVIS DEM and classified LAZ are natively GDA94 / MGA zone 56 (`EPSG:28356`). They are transformed with EPSG operation 8447, the ICSM GDA94→GDA2020 conformal-and-distortion grid. The exact PROJ GeoTIFF grid and its CC BY 4.0 README are cached under `data/raw/geodesy/`; the grid is checksummed and used with PROJ networking disabled during processing.

At a representative pilot-area coordinate, this changes coordinates by approximately 0.596 m east and 1.391 m north. A simple reassignment of the CRS would therefore misalign the elevation data by about 1.51 m.

The DEM is bilinearly resampled onto a target-aligned 1 m grid. The point cloud is transformed through a streaming PDAL pipeline; its point order, classifications and AHD Z values are retained.

## Other sources

- Queensland footprints and the orthophoto export already use `EPSG:7856`; they are validated without a coordinate transformation.
- OSM building multipolygons are transformed from WGS 84 (`EPSG:4326`) to `EPSG:7856`.
- The public UQ PDF is not treated as geospatial input because it has no stated CRS.
- No utility data is present yet.

## Authoritative and display coordinates

All GeoTIFF, LAZ and GeoPackage products retain authoritative `EPSG:7856` coordinates. Visualisation code may translate coordinates around the centre of the pilot:

```text
origin = (501353.215, 6958460.027, 0.0)
render_x = authoritative_x - 501353.215
render_y = authoritative_y - 6958460.027
render_z = authoritative_z
```

The translation is reversible and must never be written back as the GIS coordinate reference system.

## Reproduce

After Phase 3 passes, run:

```powershell
conda run --name uq-gis python pipelines/run_phase4.py
```

Normalised data is written below `data/interim/normalised/`. The machine-readable transformation record is `data/normalisation_register.csv`; detailed validation is written to `reports/tables/phase4_normalisation.json`.
