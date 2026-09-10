# Phase 5: Terrain and LiDAR Preparation

Phase 5 is complete for the 500 m by 500 m UQ St Lucia pilot area. It converts the
Phase 4 elevation sources into a reproducible, quality-controlled terrain and surface
dataset for later LoD building generation.

This phase prepares modelling inputs. It does **not** yet create LoD1 blocks or LoD2
roof geometry; that work begins in Phase 6.

## Inputs and coordinate reference

The pipeline reads the Phase 4 products:

- `data/interim/normalised/elevation/brisbane_2019_dem_1m_epsg7856.tif`;
- `data/interim/normalised/elevation/brisbane_2019_classified_ahd_epsg7856.laz`.

Every output retains GDA2020 / MGA zone 56 (`EPSG:7856`) horizontal coordinates and
Australian Height Datum (AHD) elevations. The exact pilot bounds are
`501103.215, 6958210.027, 501603.215, 6958710.027` metres.

## Reproduce the workflow

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase5.py
```

Alternatively, select the **UQ GIS** kernel in VS Code and run
`notebooks/03_phase5_terrain_lidar_preparation.ipynb`.

The point-cloud crop is implemented as a streamable PDAL bounding-box operation. PDAL
documents both the crop-bound syntax and streaming support in its
[`filters.crop` reference](https://pdal.io/en/stable/stages/filters.crop.html). Remaining
point-cloud operations use chunked Laspy reads, so the full LAZ is never loaded into
notebook memory.

## Processing decisions

The selected defaults are explicit and recorded in the manifest:

1. Crop both elevation sources to the exact 500 m by 500 m pilot area.
2. Preserve an unfiltered, full-resolution LAZ audit crop.
3. Create a separate analysis LAZ after removing:
   - ASPRS class 7 and class 18 noise points;
   - points lower than 2 m below the supplied DTM;
   - points higher than 80 m above the supplied DTM;
   - points without a valid DTM cell.
4. Retain a deterministic, global-stride display sample of at most 500,000 points.
5. Build a one-metre DSM using the maximum retained Z in each cell.
6. Fill otherwise empty, valid DSM cells from the DTM.
7. Save the signed `DSM - DTM` diagnostic and a modelling raster clamped at zero.

The full crop makes every exclusion auditable. The filtered crop is the modelling
input; the display sample is only for responsive visualisation and must not be used for
measurement.

## Generated products

| Product | Role |
|---|---|
| `elevation/dtm_1m.tif` | Bare-earth elevation on the exact pilot grid |
| `elevation/dsm_1m.tif` | Maximum retained surface return per one-metre cell |
| `elevation/surface_minus_dtm_raw.tif` | Signed DSM-minus-DTM diagnostic |
| `elevation/height_above_ground.tif` | Non-negative normalised surface height |
| `elevation/point_density_1m.tif` | Retained points per square metre |
| `elevation/ground_density_1m.tif` | Class-2 ground points per square metre |
| `elevation/ground_residual_1m.tif` | Cell-mean class-2 Z minus DTM |
| `pointcloud/uq_pilot_cropped_full.laz` | Unfiltered audit crop |
| `pointcloud/uq_pilot_analysis_filtered.laz` | Filtered modelling crop |
| `pointcloud/uq_pilot_display.laz` | Deterministic display sample |

These paths are below `data/interim/phase5/`. Generated rasters and LAZ files are
ignored by Git and can be rebuilt from the immutable sources. Hashes and lineage are
recorded in `data/preparation_register.csv` and
`data/interim/phase5/preparation_manifest.json`.

## Measured result

The pilot crop contains 6,490,855 points. Filtering retained 6,473,167 points and
removed 17,688 points (0.27%):

- 16,893 declared class-7 noise points;
- 33 points below the relative-height floor;
- 755 points above the relative-height ceiling;
- 7 boundary points without a valid DTM cell.

The deterministic display LAZ contains 497,936 points. The filtered density averages
25.89 points/m2, with a 5th percentile of 11 and a 95th percentile of 53 points/m2.
Exactly 99.08% of valid one-metre cells contain at least one retained return.

Class-2 ground elevations show close agreement with the supplied DTM:

| Statistic | Result |
|---|---:|
| Ground points compared | 2,198,784 |
| Median residual | 0.0008 m |
| RMSE | 0.0603 m |
| NMAD | 0.0267 m |
| 5th to 95th percentile | -0.0628 to +0.0593 m |

All 22 automated validation checks passed. The machine-readable result is
`reports/tables/phase5_preparation.json`.

## Diagnostic figures

- `reports/figures/phase5_terrain_hillshade.png`;
- `reports/figures/phase5_height_above_ground.png`;
- `reports/figures/phase5_point_density.png`;
- `reports/figures/phase5_classification_counts.png`;
- `reports/figures/phase5_ground_dtm_residual.png`.

The normalised-height figure is the most useful immediate preview for the UQ pitch: it
shows that the open ELVIS data resolves roof masses and vegetation across the pilot
area. It should be described as a surface-height product, not as an LoD2 building
model.

## Limitations carried into Phase 6

- The DSM is the maximum retained return per cell, not a reconstructed roof plane.
- Vegetation remains in the DSM and must be excluded using classifications and
  footprints during building modelling.
- Empty DSM cells are assigned the DTM and therefore zero normalised height.
- A small number of signed surface residuals are negative; the raw diagnostic preserves
  them while the modelling height raster clamps them to zero.
- The generic -2 m to +80 m filter is an outlier screen, not a replacement for building-
  specific robust estimation.
- Public LiDAR represents the 2019 acquisition epoch, so newer or changed buildings may
  disagree with current footprints or UQ records.

The appropriate Phase 6 input is the filtered analysis LAZ plus the Phase 5 DTM and
normalised height raster. The full crop remains the audit fallback whenever a building
appears incomplete or suspicious.
