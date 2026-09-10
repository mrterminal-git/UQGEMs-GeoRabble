# Phase 8: Public Utility Data Standardisation

## Outcome

Phase 8 is complete for the agreed 500 m by 500 m pilot and no-login public-data
route. The reproducible pipeline queries Brisbane City Council stormwater data and
all published Urban Utilities water and sewer feature layers, preserves immutable raw
responses, maps returned features into the common utility schema, runs horizontal and
vertical quality checks, and creates fixed visual checks.

All 24 validation checks pass.

The important result is a documented data gap rather than a complete underground
network: only three public records intersect the pilot, and none has sufficient
vertical metadata for defensible 3D placement.

## Sources queried

The pipeline queried 29 public layers:

- five [Brisbane City Council Open Data](https://data.brisbane.qld.gov.au/)
  stormwater datasets: pipes, manholes, junctions, surface drains and quality
  improvement devices;
- all 11 layers in the [Urban Utilities water feature service](https://services3.arcgis.com/ocUCNI2h4moKOpKX/ArcGIS/rest/services/UU_Water_OpenData/FeatureServer);
- all 13 layers in the [Urban Utilities sewer feature service](https://services3.arcgis.com/ocUCNI2h4moKOpKX/ArcGIS/rest/services/UU_Sewer_OpenData/FeatureServer).

Queensland Globe is useful contextual infrastructure, but it is not the source of the
detailed local utility records used here. The reproducible sources are the underlying
public APIs and feature services.

The source snapshot contains 38 immutable response and metadata files below
`data/raw/public_utilities/`. Existing raw files are not overwritten on a rerun.

## Measured pilot result

| Network | Lines | Nodes | Total records | Verified AHD | Usable depth |
|---|---:|---:|---:|---:|---:|
| Stormwater | 1 | 1 | 2 | 0 | 0 |
| Water | 1 | 0 | 1 | 0 | 0 |
| Sewer | 0 | 0 | 0 | 0 | 0 |
| Electricity | 0 | 0 | 0 | 0 | 0 |
| Gas | 0 | 0 | 0 | 0 | 0 |
| Telecommunications | 0 | 0 | 0 | 0 | 0 |

The returned features are:

- BCC stormwater pipe `N14000034`, recorded as a 450 mm drain;
- BCC stormwater manhole `N14000035`;
- Urban Utilities water service `WS11796`, recorded as 225 mm.

The stormwater pipe and water service cross the western pilot boundary. They are not
evidence of full campus coverage.

## Common schema and provenance

The GeoPackage records the Phase 8 fields required by the plan:

```text
asset_id
network_type
asset_type
owner
status
diameter_or_size
material
horizontal_source
vertical_source
invert_z_ahd
crown_z_ahd
depth_m
accuracy_xy
accuracy_z
survey_date
confidence
sensitivity
notes
```

Additional fields preserve source dataset and layer identifiers, source URLs,
reliability, plan number, upstream/downstream identifiers, original level fields,
published grade, geometry status and the full non-geometric source attributes as JSON.

All authoritative horizontal geometry is stored in GDA2020 / MGA zone 56
(`EPSG:7856`).

## Vertical-data decision

No public feature qualifies for the first four levels of the planned vertical-data
hierarchy. All three are assigned `unknown_depth`.

The BCC records contain numeric invert-level fields, but the public dataset metadata
does not identify their vertical datum. Those numbers are retained in `raw_*` fields;
they are not copied into `invert_z_ahd` and are not used to generate 3D geometry. The
published depth values in the pilot records are sentinel values (`999` or `999.99`) and
are converted to null.

No schematic depth has been imposed. Consequently:

- all utility geometry remains explicitly 2D;
- no underground tubes or 3D utility centrelines are generated in Phase 8;
- the data can be overlaid in plan view now;
- 3D placement remains gated on an identified vertical datum or a defensible surveyed
  depth/reference surface.

## Validation findings

The public records produce these review findings:

- one of four clipped line endpoints is not matched to a returned node or the pilot
  boundary within 1 m, consistent with incomplete public/private network coverage;
- one stormwater endpoint matches the public manhole and two endpoints cross the pilot
  boundary;
- the stormwater pipe's recorded invert levels imply a grade of approximately `1:8.8`,
  while the published grade field says `1:85`; the source values must not be used for
  3D modelling without clarification;
- no public utility line intersects a modelled building footprint in plan view;
- vertical gradients, discontinuities and building clearances cannot be assessed
  without verified vertical data;
- the absence of sewer, electricity, gas or telecommunications records is a source
  coverage result, not proof that those physical networks are absent.

The detailed findings are in
`reports/tables/phase8_validation_issues.csv`.

## Outputs

Authoritative processed data:

```text
data/processed/utilities/uq_pilot_public_utilities.gpkg
data/processed/utilities/utility_manifest.json
```

The GeoPackage contains:

- `utility_lines`;
- `utility_nodes`;
- `pilot_boundary`.

Audit tables:

```text
data/utility_model_register.csv
reports/tables/phase8_utility_assets.csv
reports/tables/phase8_source_coverage.csv
reports/tables/phase8_network_summary.csv
reports/tables/phase8_validation_issues.csv
reports/tables/phase8_utilities.json
```

Fixed visual checks:

```text
reports/figures/phase8_utility_plan.png
reports/figures/phase8_utility_detail.png
reports/figures/phase8_public_coverage.png
reports/figures/phase8_vertical_evidence.png
```

## Reproduce the phase

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase8.py
```

Alternatively, run `notebooks/06_phase8_utility_standardisation.ipynb` with the
**UQ GIS** kernel. Repeated runs reuse the immutable raw responses and the hash-checked
processed GeoPackage.

## Licence, sensitivity and safety

- BCC metadata identifies its datasets as Creative Commons Attribution 4.0. The source
  and attribution remain in the data registers.
- Urban Utilities' services are publicly queryable, but no explicit redistribution
  licence was found in the cached ArcGIS item metadata. Verify the applicable terms
  before publishing those extracts or a derivative dataset.
- Only public records are included. No UQ-controlled or BYDA-restricted information is
  present.
- The output is not survey-grade, asset-location-grade or excavation-safe.

## Decision gate

The Phase 8 ingestion and standardisation method is proven, but the public result is too
sparse and vertically undocumented for a defensible 3D campus utility model. Retain it
as clearly labelled 2D context and use the quantified gap—29 layers queried, three
records found, zero defensible depths—as evidence in a future UQ or asset-owner data
request.
