# Phase 7: Selective LoD2 Feasibility and Modelling

Phase 7 is complete for all 61 footprints in the 500 m by 500 m UQ St Lucia public-data
pilot. It tests whether the 2019 classified LiDAR supports defensible roof geometry,
constructs LoD2 shells only where explicit evidence gates pass, and retains the validated
Phase 6 LoD1 shell everywhere else.

The result is intentionally a mixed-LoD model. It is a public-data demonstration, not a
replacement for current UQ BIM or survey information.

## Reproduce the workflow

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase7.py
```

Alternatively, select the **UQ GIS** kernel in VS Code and run
`notebooks/05_phase7_lod2_feasibility.ipynb` from top to bottom.

The first execution scans the Phase 5 analysis LAZ. Later executions reuse the core
products only when their source, configuration and output hashes agree with the Phase 7
manifest. Figures and review tables are refreshed from the validated products.

## Conservative workflow

Every Phase 6 building is assessed, but automated plane fitting is attempted only when
all of these source-support conditions hold:

- the Phase 6 block was modelled;
- the footprint does not intersect the arbitrary pilot boundary;
- at least 200 retained building-class points are present;
- point density is at least 5 points/m2;
- roof-cell coverage is at least 65%.

Candidate points are segmented into at most five planes with deterministic RANSAC. A
plane needs at least 120 points and at least 6% of the candidate points. The initial
RANSAC residual tolerance is 0.20 m; final coverage is measured using a 0.35 m tolerance.

Detected planes are converted into a lower-envelope roof partition. This is appropriate
for common pitched and shed roofs and prevents higher plant/equipment returns from being
silently turned into roof surfaces. Plane intersections are clipped to the public
footprint, walls and bases are constructed, and the resulting shell must be watertight
and have positive volume.

An accepted LoD2 roof must have a material slope of at least 3 degrees. Multi-plane
roofs must also have at least 8 degrees separation between plane normals.

### Acceptance classes

Reliable LoD2 requires:

- at least 80% of source roof points within 0.35 m of the reconstructed surface;
- surface RMSE no greater than 0.20 m for those covered points;
- lower-envelope/nearest-plane assignment consistency of at least 70%;
- complete footprint coverage and a valid closed solid.

Approximate LoD2 uses minimum gates of 65% surface coverage, 0.35 m RMSE and 50%
partition consistency, with the same solid-geometry requirement. Roofs that are
well-supported but effectively flat remain LoD1 because a tilted reconstruction would
not add meaningful geometry.

## Measured result

| Measure | Result |
|---|---:|
| Phase 6 footprints assessed | 61 |
| Source-supported LoD2 candidates | 42 |
| Reliable LoD2 buildings | 8 |
| Approximate LoD2 buildings | 1 |
| Accepted roof surfaces | 17 |
| Detected ridge/intersection segments | 10 |
| LoD1-only buildings | 27 |
| Manual-correction buildings | 22 |
| Missing/outdated-source records | 3 |

Nine of 42 candidates (21.4%) earn LoD2. Across those nine, the minimum accepted surface
coverage is 85.6% and the median is 92.6%. Median surface RMSE is 0.067 m and the maximum
is 0.130 m. These are internal fit statistics against the same LiDAR used to build the
model; they are not independent accuracy estimates.

| Building | Public name | Status | Planes | Ridges |
|---|---|---|---:|---:|
| `UQSL-003` | Building 31B | reliable LoD2 | 2 | 1 |
| `UQSL-016` | Abel Smith Lecture Theatre | reliable LoD2 | 5 | 6 |
| `UQSL-022` | unnamed | reliable LoD2 | 2 | 1 |
| `UQSL-025` | unnamed | reliable LoD2 | 2 | 1 |
| `UQSL-036` | Physics Annexe | reliable LoD2 | 2 | 1 |
| `UQSL-038` | unnamed | reliable LoD2 | 1 | 0 |
| `UQSL-050` | unnamed | reliable LoD2 | 1 | 0 |
| `UQSL-056` | unnamed | reliable LoD2 | 1 | 0 |
| `UQSL-058` | unnamed | approximate LoD2 | 1 | 0 |

All 58 modelled buildings remain present in the mixed presentation GLB. All 58 meshes
are watertight and have positive volume. Rejection of an LoD2 roof therefore reduces
detail but does not create a hole in the presentation model.

## Generated products

| Product | Role |
|---|---|
| `data/processed/lod2/lod2_buildings.gpkg` | Authoritative EPSG:7856 status, 3D roof-surface and ridge layers |
| `data/processed/lod2/uq_pilot_mixed_lod.glb` | Display-local mixed LoD1/LoD2 presentation mesh |
| `data/processed/lod2/local_origin.json` | Exact GLB-to-authoritative coordinate conversion |
| `data/processed/lod2/roof_fit_samples.npz` | Deterministic point/residual samples for visual review |
| `data/processed/lod2/lod2_manifest.json` | Source/configuration signature and core-output hashes |
| `data/lod2_model_register.csv` | Tracked dataset-level lineage register |

The GeoPackage layers are:

- `building_status`: all 61 footprints and their complete feasibility decision;
- `roof_surfaces`: the 17 accepted three-dimensional plane polygons;
- `ridge_lines`: the 10 accepted three-dimensional plane-intersection segments.

The mixed GLB uses local XY coordinates to avoid graphics precision loss. Elevations
remain AHD values. The GeoPackage, not the GLB, is the authoritative GIS record.

## Review outputs

- `reports/figures/phase7_feasibility_map.png`;
- `reports/figures/phase7_roof_planes.png`;
- `reports/figures/phase7_roof_fit_examples.png`;
- `reports/figures/phase7_residuals.png`;
- `reports/figures/phase7_mixed_lod_northeast.png`;
- `reports/figures/phase7_mixed_lod_southwest.png`;
- `reports/tables/phase7_building_feasibility.csv`;
- `reports/tables/phase7_roof_plane_metrics.csv`;
- `reports/tables/phase7_manual_review.csv`;
- `reports/tables/phase7_lod2.json`.

All 21 automated decision and integrity checks pass.

## Decision gate

Do not apply unattended LoD2 reconstruction campus-wide from these public inputs.
Retain the mixed-LoD approach: use validated LoD1 as the complete baseline, accept
selective automated LoD2 only where the same gates pass, and seek current UQ BIM or
manual roof constraints for presentation-critical buildings.

The reason is evidence, not lack of point density. Many roofs contain several levels,
plant, curved or irregular forms, vegetation leakage, or public footprint/epoch mismatch
that a simple lower-envelope plane model cannot distinguish reliably. Current imagery
and UQ BIM are also needed to determine whether a building has changed since 2019.

## Limitations

- The source LiDAR is from 2019 and the public footprints are not UQ-authoritative.
- Coverage, residual and classification screens only indirectly detect vegetation,
  roof-edge mismatch and change; they do not prove those conditions are absent.
- Curved roofs, roof furniture and stepped flat roofs need a richer model or manual
  constraints.
- Automated ridge labels represent fitted plane intersections and are not surveyed
  architectural elements.
- Neither the LoD1 nor LoD2 product is survey-grade or suitable for excavation,
  engineering set-out or asset-location decisions.
