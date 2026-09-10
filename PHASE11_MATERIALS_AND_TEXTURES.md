# Phase 11: Materials and Texture Mapping

## Outcome

Phase 11 is complete for the 500 m by 500 m UQ St Lucia public-data pilot. It adds a
hybrid presentation skin without changing the validated Phase 5 terrain, Phase 7
building geometry or Phase 8 utility records.

The presentation mode uses the registered 24 July 2022 Queensland public orthophoto
for terrain and roof surfaces. Building facades use a deliberately generic procedural
panel-and-window material because nadir imagery and LiDAR do not observe facade
appearance. Public utilities retain their Phase 9 network colours and display-only
terrain drape; physical depth remains unknown.

All 21 Phase 11 validation checks pass.

## Skin modes

The phase preserves two complementary views:

| Mode | Purpose | Representation |
|---|---|---|
| Analysis skin | Inspect LoD, confidence and GIS attributes | Unchanged Phase 9 Plotly scene |
| Presentation skin | Communicate the campus setting visually | Orthophoto terrain/roofs and schematic facades |

Open `reports/scenes/uq_pilot_skin_viewer.html` to switch between the two modes. The
small wrapper loads the two adjacent self-contained scene files and works locally
without a server.

## Texture method

The orthophoto is a three-band, 2,000 by 2,000 pixel GeoTIFF in GDA2020 / MGA zone 56
(`EPSG:7856`). Its 0.25 m pixels and 500 m square bounds exactly match the pilot terrain.
The workflow writes a JPEG presentation derivative and calculates UV coordinates from
each terrain or roof vertex's authoritative easting and northing. In simple terms, the
UV values tell the renderer which orthophoto pixel belongs at each 3D vertex.

Every one of the 2,432 Phase 7 building triangles is assigned once:

- 562 upward-facing roof triangles receive the orthophoto;
- 1,308 approximately vertical triangles receive the procedural facade tile; and
- 562 downward-facing base triangles receive a neutral material.

The split duplicates render vertices where a surface needs a different material, but
does not move, add or infer building surfaces. All 58 modelled buildings are included.

The exported GLB also includes the three sparse Phase 8 utility records as coloured,
dashed display geometry. Their object names contain `DISPLAY_ONLY_DEPTH_UNKNOWN` so
the limitation survives outside the HTML wrapper.

## Outputs

Primary presentation outputs:

```text
reports/scenes/uq_pilot_skin_viewer.html
reports/scenes/uq_pilot_textured.html
data/processed/materials/uq_pilot_textured.glb
```

Texture assets and configuration:

```text
data/processed/materials/orthophoto_texture.jpg
data/processed/materials/procedural_facade_texture.png
data/processed/materials/phase11_skin_config.json
data/processed/materials/phase11_manifest.json
```

Fixed visual checks:

```text
reports/figures/phase11_textured_plan.png
reports/figures/phase11_textured_oblique.png
reports/figures/phase11_skin_comparison.png
```

Validation evidence:

```text
reports/tables/phase11_material_inventory.csv
reports/tables/phase11_building_surface_audit.csv
reports/tables/phase11_skins.json
data/material_model_register.csv
```

## Reproduce the phase

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase11.py
```

Alternatively, open `notebooks/09_phase11_materials_and_textures.ipynb`, select the
**UQ GIS** kernel and run all cells. Matching source and configuration hashes reuse the
validated outputs.

## Interpretation and publication boundary

The presentation skin is suitable for explaining the public-data method and supporting
a request for better UQ data. It is not a photorealistic or authoritative campus digital
twin:

- orthophoto capture is 2022 while LiDAR capture is 2019;
- roofs inherit every accepted or fallback limitation in the Phase 7 geometry;
- facade windows, panels and materials are illustrative rather than observed;
- nadir imagery cannot provide true facade photographs;
- public utility coverage is sparse and physical depth is unknown; and
- the model is not survey-grade or excavation-safe.

The Queensland orthophoto is recorded as Creative Commons Attribution 4.0. Urban
Utilities redistribution terms still require confirmation before publishing the viewer
or a derivative utility dataset.

## Decision gate

The hybrid skin is ready for local demonstrations alongside the unchanged analytical
scene. A later authoritative visual upgrade should use UQ BIM material assets or
appropriately licensed oblique/facade imagery rather than treating the procedural
facades as observations.
