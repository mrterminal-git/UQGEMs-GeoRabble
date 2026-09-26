# Phase 6: LoD1 Building Generation

Phase 6 is complete for the full 500 m by 500 m UQ St Lucia public-data pilot. It
combines the Phase 5 terrain and filtered building-class LiDAR with Queensland generated
building outlines to create conservative flat-roof LoD1 blocks.

The GeoPackage is the authoritative GIS result. The GLB is a local-origin presentation
mesh. Neither product should be represented as current UQ-authoritative BIM.

## Reproduce the workflow

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase6.py
```

Alternatively, select the **UQ GIS** kernel in VS Code and run
`notebooks/04_phase6_lod1_buildings.ipynb` from top to bottom.

The initial execution scans the Phase 5 analysis LAZ in chunks. Later executions reuse
the processed products only when every source, configuration and output hash agrees with
the Phase 6 manifest.

## Source hierarchy

- **Geometry:** Queensland generated building outlines are the primary footprints.
- **Names:** specific OpenStreetMap names are attached by spatial overlap. The generic
  Queensland value “University Of Queensland St Lucia Campus” is not treated as an
  individual building name.
- **Ground:** median AHD value of Phase 5 DTM cells touching each footprint.
- **Roof:** median class-6 LiDAR Z after a robust four-NMAD outlier screen.
- **Epoch:** Brisbane 2019 LiDAR.

The 61 primary outlines are retained in the output inventory. Fifteen intersect the
arbitrary pilot boundary and are marked as partial. Thirty-seven outlines receive a
specific public name; unmatched names remain blank.

## Modelling and confidence rules

A block is generated only when it has at least 30 retained roof points, valid terrain,
and a height between 2.5 m and 60 m. The flat roof represents a robust principal roof
elevation; it does not reproduce pitches, ridges, plant rooms or multiple roof levels.

High confidence requires all of the following:

- the footprint is not clipped by the pilot boundary;
- at least 200 retained roof points;
- at least 5 retained points/m2;
- at least 65% roof-cell coverage;
- roof-elevation NMAD no greater than 1.5 m;
- agreement with the Queensland source BSM edge elevation within 2 m.

Medium confidence requires at least 30 points, 1 point/m2, 25% cell coverage and roof
NMAD no greater than 3 m. Other modelled blocks are low confidence. A low confidence
classification is a review instruction, not an assertion that the building is wrong.

## Generated products

| Product | Role |
|---|---|
| `data/processed/lod1/lod1_buildings.gpkg` | Authoritative EPSG:7856 footprint and attribute dataset |
| `data/processed/lod1/uq_pilot_lod1.glb` | Display-local watertight LoD1 presentation mesh |
| `data/processed/lod1/local_origin.json` | Exact GLB-to-authoritative coordinate conversion |
| `data/processed/lod1/roof_point_samples.npz` | Deterministic per-building visual samples |
| `data/processed/lod1/lod1_manifest.json` | Source/configuration signature and output hashes |
| `data/building_model_register.csv` | Tracked dataset-level lineage register |

The GeoPackage contains all requested fields:

```text
building_id
building_name
ground_z_ahd
roof_z_ahd
height_m
footprint_source
height_method
lidar_capture_date
lod
confidence
geometry_status
notes
```

It also records roof-point counts and density, cell coverage, roof NMAD and percentiles,
DTM range, boundary status, source BSM values, modelling status and review issues.

## Measured result

| Measure | Result |
|---|---:|
| Primary footprint records | 61 |
| LoD1 blocks generated | 58 |
| Heights deliberately withheld | 3 |
| High-confidence blocks | 32 |
| Medium-confidence blocks | 18 |
| Low-confidence blocks | 8 |
| Specifically named outlines | 37 |
| Boundary-clipped outlines | 15 |
| Minimum modelled height | 2.80 m |
| Median modelled height | 6.58 m |
| Maximum modelled height | 23.89 m |

Of 2,004,615 class-6 points in the analysis LAZ, 1,867,084 (93.14%) fall inside a
primary footprint. The robust models use 1,741,935 points. Median support per modelled
outline is 7,162 points, median density is 17.84 points/m2, median roof-cell coverage is
90.96%, and median roof NMAD is 0.360 m.

The median absolute difference between the robust roof estimate and the Queensland BSM
edge elevation is 0.691 m. This comparison is a consistency check, not independent
accuracy validation, because the public products may share source data.

All 23 automated validation checks pass. In particular, all 58 GLB geometries are
watertight, have positive volume and use numerically safe local XY coordinates.

## Withheld outlines

Three source outlines have good point support but a robust height below 2.5 m:

- `UQSL-040`, an unnamed 20.5 m2 outline;
- `UQSL-051`, a 50.5 m2 outline overlapping the public Andrew N. Liveris Building name;
- `UQSL-061`, an unnamed 13.2 m2 boundary fragment.

These may represent canopy/roof fragments, source segmentation or boundary effects.
Their records and evidence are preserved, but no block is invented. Presentation-
critical cases should be compared with the full audit LAZ, current imagery or UQ BIM.

## Validation outputs

- `reports/figures/phase6_lod1_plan.png`;
- `reports/figures/phase6_footprint_roof_points.png`;
- `reports/figures/phase6_isolated_roof_examples.png`;
- `reports/figures/phase6_lod1_northeast.png`;
- `reports/figures/phase6_lod1_southwest.png`;
- `reports/figures/phase6_building_height_distribution.png`;
- `reports/tables/phase6_building_metrics.csv`;
- `reports/tables/phase6_suspicious_buildings.csv`;
- `reports/tables/phase6_missing_changed_misaligned.csv`;
- `reports/tables/phase6_lod1.json`.

The oblique figures use three-times vertical exaggeration only for visual review. The GLB
and all stored elevations retain their true scale.

## Limitations and Phase 7 handoff

- Each LoD1 outline has a single flat roof elevation.
- Complexes split into several Queensland outlines can appear as adjacent blocks with
  different roof heights.
- Boundary blocks are partial and should not be used to infer complete building area or
  volume.
- Public names are spatial matches and may attach to a roof section rather than an entire
  named complex.
- Confidence measures source support; it is not survey-grade accuracy certification.
- The 2019 acquisition may not represent subsequent construction or demolition.

Phase 7 should test LoD2 only on non-boundary buildings with sufficient coverage and
low roof dispersion. Buildings with large roof NMAD can contain useful multiple planes,
but can also reflect complex geometry, vegetation leakage or mismatched footprints and
must be reviewed rather than accepted automatically.
