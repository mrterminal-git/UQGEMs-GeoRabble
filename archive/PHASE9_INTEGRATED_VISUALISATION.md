# Phase 9: Integrated Python Visualisation

## Outcome

Phase 9 is complete for the existing 500 m by 500 m UQ St Lucia pilot. The reusable
Python scene builder combines the Phase 5 terrain and LiDAR display sample, the Phase 7
mixed-LoD buildings, and the Phase 8 public utility records. It produces a self-contained
interactive HTML scene, four fixed visual checks, machine-readable configuration and
validation reports, and a notebook suitable for use in VS Code.

All 19 Phase 9 validation checks pass.

## Integrated scene

The default scene contains:

| Layer | Authoritative/display content | Default |
|---|---|---|
| Terrain | 500 by 500 one-metre Phase 5 DTM cells, in metres AHD | visible, 68% opacity |
| Buildings | 58 Phase 7 solids: LoD1 fallback and accepted LoD2 roofs | visible |
| Public utilities | two line records and one node from Phase 8 | visible and dashed |
| LiDAR preview | deterministic 30,000-point sample of 497,936 display points | hidden |

The authoritative horizontal CRS is GDA2020 / MGA zone 56 (`EPSG:7856`). Rendering
uses the documented Phase 4 local origin `(501353.215, 6958460.027, 0.0)` to avoid
floating-point artefacts; this is a reversible display transformation. Terrain and
building elevations retain AHD values.

## Utility display rule

The Phase 8 utility source remains two-dimensional. Physical utility depths are
unknown and no underground positions have been invented.

For visibility only, Phase 9 clips each public alignment to the pilot, samples the
Phase 5 terrain beneath it and draws it at terrain plus `0.75 m`. The line is dashed,
the legend and hover text say that depth is unknown, and the source GeoPackage is not
modified. Automated checks confirm a `0.75 m` minimum and maximum display clearance.

This display is horizontal-alignment context, not an excavation or asset-location
model. A true 3D utility scene remains gated on surveyed depth or elevation data with
a verified vertical datum.

## Interaction and configuration

The HTML scene provides:

- legend toggles for terrain, building LoD groups, stormwater, water and LiDAR;
- grouped utility-type filtering;
- northeast, southwest and plan camera presets;
- full-pilot and utility-detail extents;
- terrain opacity presets of 68%, 25% and hidden;
- hover information for buildings, assets, confidence and provenance.

Python configuration additionally supports positive vertical exaggeration, utility
colouring by network, survey-age band, XY accuracy or overall confidence, and
building/asset ID subsets. Survey-age colouring uses only `survey_date`, never the
service update date; all three current records therefore fall into the unknown band.
The reusable entry points are `SceneDisplayConfig`, `load_integrated_scene_data`,
`build_plotly_figure`, `build_integrated_plotter` and `export_interactive_html` in
`src/uqgems/integrated_scene.py`.

The fixed utility cutaway deliberately retains only the western terrain strip where
the three public records intersect the pilot. The cross-section is a north-south
terrain/building profile at easting `501105.715`; its three utility markers show
horizontal proximity only.

## Outputs

Interactive scene:

```text
reports/scenes/uq_pilot_integrated.html
```

Fixed visual checks:

```text
reports/figures/phase9_integrated_plan.png
reports/figures/phase9_integrated_oblique.png
reports/figures/phase9_utilities_cutaway.png
reports/figures/phase9_cross_section.png
```

Configuration and validation evidence:

```text
data/processed/scene/phase9_manifest.json
data/processed/scene/phase9_scene_config.json
data/scene_model_register.csv
reports/tables/phase9_layer_inventory.csv
reports/tables/phase9_controls.csv
reports/tables/phase9_cross_section_profile.csv
reports/tables/phase9_scene.json
```

The HTML is self-contained and approximately 5.7 MB. It can be opened locally in a
browser without starting a server. Do not distribute it until the Urban Utilities
redistribution terms have been confirmed.

## Reproduce the phase

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase9.py
```

Alternatively, open `notebooks/07_phase9_integrated_visualisation.ipynb`, select the
**UQ GIS** kernel and run all cells. The notebook runs the same pipeline, displays the
interactive scene in VS Code and presents the fixed plan, oblique, cutaway and section
views. Matching source/configuration hashes reuse validated render outputs.

## Decision gate

The integrated Python visualisation workflow is ready for demonstrations of the
public-data pilot and for supporting a better-data request to UQ. The model includes
only three public utility records near the western pilot boundary, so it must not be
presented as campus utility coverage. Authoritative utility depths and the missing
campus-owned networks are still required before producing a defensible combined 3D
GIS/BIM utility model.
