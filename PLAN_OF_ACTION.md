# UQ St Lucia 3D GIS and Utility Map: Plan of Action

## 1. Objective

Create a reproducible 3D GIS model of the University of Queensland's St Lucia campus containing:

- terrain derived from ELVIS elevation data;
- campus-wide Level of Detail 1 (LoD1) buildings;
- Level of Detail 2 (LoD2) buildings where the LiDAR quality supports reliable roof reconstruction;
- underground and above-ground utilities where suitable source data is available;
- explicit provenance, uncertainty and accuracy information;
- interactive 3D views inside VS Code notebooks;
- standalone HTML scenes and standard screenshots for review.

The initial model will be a research and visualisation product. It must not be treated as excavation-safe or survey-accurate unless the relevant utilities have been validated against authoritative survey information.

## 2. Working Approach

The project will be Python-first. Data processing, quality control and primary visualisation will take place through Python notebooks in VS Code. QGIS may be used later as an optional independent check, but it is not required for the main workflow.

```text
Raw source data
      |
      v
Metadata and coordinate-system validation
      |
      v
Terrain and LiDAR processing
      |
      v
LoD1 building generation
      |
      v
Selective LoD2 roof reconstruction
      |
      v
Utility-network standardisation
      |
      v
Integrated Python 3D scene
      |
      +--> Interactive notebook view
      +--> Standalone HTML scene
      +--> Standard PNG views
      +--> Data-quality reports
```

## 3. Phase 1: Environment and Project Setup

Create a dedicated Conda environment rather than modifying the Anaconda base environment or any existing statistics environments.

The initial software stack will include:

- GeoPandas, Shapely and PyProj for vector geometry and coordinate systems;
- Rasterio, Rioxarray and NumPy for terrain and raster processing;
- PDAL, LASPy and LAZRS for LiDAR processing;
- PyVista, VTK and Trame for interactive and static 3D rendering;
- Lonboard for interactive geospatial exploration in notebooks;
- Matplotlib and Plotly for diagnostic plots;
- pandas for data tables and metadata;
- JupyterLab and IPykernel for notebook execution;
- testing and formatting tools for maintainable code.

Use the following initial project structure:

```text
uq-campus-map/
|-- data/
|   |-- raw/
|   |-- interim/
|   |-- manual/
|   `-- processed/
|-- notebooks/
|-- src/
|-- pipelines/
|-- reports/
|   |-- figures/
|   |-- scenes/
|   `-- tables/
|-- tests/
|-- environment.yml
`-- README.md
```

The outputs of this phase are:

- a working VS Code notebook kernel;
- a reproducible `environment.yml`;
- an environment diagnostic report;
- Git configuration that excludes large source and derived datasets.

## 4. Phase 2: Synthetic Workflow Test

Before downloading and processing large datasets, create a small artificial scene containing:

- sloping terrain;
- several building footprints;
- one flat roof and one pitched roof;
- water, sewer and electrical lines;
- pits and utility nodes.

Use this scene to verify:

- inline PyVista rendering in VS Code;
- interactive camera controls;
- deterministic PNG screenshot generation;
- standalone HTML export;
- terrain transparency and underground viewing;
- coordinate-preserving GIS exports;
- separation between authoritative coordinates and local rendering coordinates.

### Decision gate

Do not start full ELVIS processing until the synthetic workflow can be run from beginning to end in a restarted notebook kernel.

## 5. Phase 3: Data Acquisition and Provenance

**Implementation status:** Complete for the public-data prototype. The ELVIS order and public context sources are inventoried by a reproducible pipeline. UQ-controlled BIM, digital-twin and utility access is intentionally deferred until the public LoD demonstration is available to support the request.

### 5.1 ELVIS elevation data

Begin with a pilot area of approximately 500 by 500 metres containing several buildings with different roof forms. Download:

- the best available 1 metre DEM or digital terrain model (DTM);
- classified LAS or LAZ point-cloud tiles;
- the complete metadata supplied with each dataset.

Submitting an order through ELVIS is normally an area-of-interest download job, not an application for permission. Original downloaded files must remain unchanged in `data/raw/`.

### 5.2 Building information

Obtain:

- OpenStreetMap building footprints for the initial prototype;
- UQ or Queensland building footprints where available;
- UQ building names and building numbers;
- recent imagery that permits visual checking under its licence.

Google photorealistic 3D data may be used as visual context, but building geometry must not be extracted or traced from Google products.

### 5.3 Utility information

In parallel with the public-data prototype, request from the UQ Digital Modelling Office:

- existing utility GIS layers;
- two-dimensional or three-dimensional DWG service drawings;
- surveyed pits, valves, hydrants and other assets;
- utility depth and invert-elevation information;
- source dates and accuracy classifications;
- data-access, storage and publication conditions;
- access to any relevant St Lucia digital-twin outputs.

Before You Dig Australia information may help identify provider-owned networks and campus-boundary connections. It should not be expected to contain all privately owned UQ services.

### 5.4 Data register

Maintain a machine-readable register with at least these fields:

```text
dataset
source
download_date
capture_date
licence
horizontal_crs
vertical_datum
resolution
stated_accuracy
processing_status
notes
```

## 6. Phase 4: Coordinate-System Normalisation

**Implementation status:** Complete. The native GDA94 elevation products are transformed with the explicit EPSG:8447 conformal-and-distortion grid operation, AHD Z values are retained, public vector/context sources are normalised, and a reversible display origin is documented.

Inspect rather than assume the coordinate reference system and vertical datum of every source.

The provisional working target is:

- horizontal: GDA2020 / MGA Zone 56 (`EPSG:7856`);
- vertical: Australian Height Datum (AHD);
- units: metres.

For each input:

1. read its raster, vector or point-cloud metadata;
2. identify the original horizontal CRS;
3. identify whether elevations are AHD or ellipsoidal;
4. transform coordinates only when necessary;
5. record the transformation and software used;
6. validate the transformed bounds and elevations.

To reduce precision problems in 3D renderers, translate authoritative coordinates to a documented local origin for display:

```text
render_x = authoritative_x - local_origin_x
render_y = authoritative_y - local_origin_y
render_z = authoritative_z
```

This translation affects only visualisation. Stored GIS data retains its authoritative coordinates.

### Quality gate

No dataset proceeds to modelling with an unknown horizontal CRS or vertical datum.

## 7. Phase 5: Terrain and LiDAR Preparation

**Implementation status: complete for the 500 m by 500 m public-data pilot.** The
reproducible pipeline, notebook, output register and measured validation results are
documented in `PHASE5_TERRAIN_LIDAR_PREPARATION.md`. All 22 validation checks pass.

Use PDAL and Rasterio to:

- crop data to the pilot boundary;
- inspect the available LiDAR classifications;
- identify noise and obvious outliers;
- calculate point density;
- separate ground and non-ground returns;
- compare LiDAR ground returns with the supplied DTM;
- generate a digital surface model (DSM) where required;
- calculate a normalised height raster.

```text
normalised height = DSM - DTM
```

Produce:

- `dtm_1m.tif`;
- `dsm_1m.tif`;
- `height_above_ground.tif`;
- cropped full-resolution LAZ data;
- downsampled display LAZ data;
- terrain hillshade;
- LiDAR-classification and density figures;
- alignment and elevation reports.

Full-resolution LiDAR should be processed through PDAL without loading the entire campus into notebook memory. Interactive scenes should use purpose-built samples or level-of-detail representations.

## 8. Phase 6: LoD1 Building Generation

**Implementation status: complete for the public-data pilot.** The complete 61-outline
inventory, 58 defensible LoD1 solids, three withheld exceptions, confidence model,
validation figures and audit tables are documented in `PHASE6_LOD1_BUILDINGS.md`. All
23 validation checks pass.

For each building footprint:

1. validate and, where safe, repair its geometry;
2. sample the relevant bare-earth elevation;
3. select roof returns within the footprint;
4. remove vegetation and obvious outliers where possible;
5. estimate the principal roof elevation using robust statistics;
6. calculate building height;
7. extrude the footprint into an LoD1 block;
8. assign a confidence category.

The building dataset should include:

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

Validation outputs will include:

- footprint and LiDAR plan view;
- isolated roof-point views;
- standard northeast and southwest oblique views;
- a building-height distribution;
- a table of suspicious heights;
- a missing, changed or misaligned building report.

### Milestone

Produce a defensible LoD1 model for the complete pilot area.

## 9. Phase 7: LoD2 Feasibility and Modelling

Attempt LoD2 reconstruction only where the source data supports it. Assess:

- roof-point density;
- vegetation obstruction;
- footprint and roof-edge alignment;
- detectability of roof planes and ridges;
- whether the building has changed since LiDAR capture.

For suitable buildings:

1. segment roof points;
2. fit roof planes using robust methods such as RANSAC;
3. group planes by orientation and elevation;
4. estimate ridge and intersection lines;
5. clip roof surfaces to the footprint;
6. construct walls and a closed building shell;
7. compare the reconstructed model against the source point cloud.

Assign each building one of these statuses:

- reliable LoD2;
- approximate LoD2;
- manual correction required;
- LoD1 only;
- missing or outdated source data.

### Decision gate

Proceed with campus-wide automated LoD2 processing only if the pilot produces useful and defensible roof geometry. Otherwise, retain LoD1 and use UQ BIM or selective manual modelling for priority buildings.

## 10. Phase 8: Utility Data Standardisation

Convert utility sources into a common network schema containing at least:

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

Apply the following vertical-data hierarchy:

1. surveyed absolute AHD elevation;
2. surveyed depth below a known surface;
3. approximate recorded depth;
4. schematic depth used only for visualisation;
5. unknown depth.

Utilities will be represented as three-dimensional centrelines and visualised as coloured tubes. Known physical diameter may control tube width; otherwise use a clearly documented symbolic width.

Validate:

- disconnected network endpoints;
- lines that do not terminate at expected pits or nodes;
- implausible gradients in gravity networks;
- missing depth and invert values;
- utility and building conflicts;
- unexplained vertical discontinuities;
- differences between record sources.

Sensitive utility information must remain separate from any publishable output.

## 11. Phase 9: Integrated Python Visualisation

Build a reusable scene function that accepts terrain, buildings, point clouds, utilities and a display configuration.

Provide controls for:

- layer visibility;
- utility-type filtering;
- vertical exaggeration;
- terrain opacity;
- underground or cutaway viewing;
- building and asset selection;
- colouring by utility type, age, accuracy or confidence;
- standard plan and oblique camera positions;
- cross-section views.

Each run should produce an interactive scene and standard diagnostic figures:

```text
reports/scenes/uq_pilot_interactive.html

reports/figures/
|-- 01_terrain_plan.png
|-- 02_lidar_classification.png
|-- 03_lod1_plan.png
|-- 04_lod1_oblique.png
|-- 05_lod2_roof_fit.png
|-- 06_utilities_cutaway.png
`-- 07_integrated_scene.png
```

The PNG files are the principal collaborative visual checks because they can be generated with fixed camera positions and compared consistently between runs.

## 12. Phase 10: Reproducibility and Validation

Use a numbered notebook sequence:

```text
00_environment_check.ipynb
01_data_inventory.ipynb
02_crs_and_datums.ipynb
03_lidar_quality.ipynb
04_surface_models.ipynb
05_lod1_buildings.ipynb
06_lod2_roofs.ipynb
07_utilities.ipynb
08_integrated_scene.ipynb
09_validation_report.ipynb
```

Reusable algorithms should live in `src/`; notebooks should document and orchestrate them.

The project is reproducible when:

- all notebooks run successfully from restarted kernels in numerical order;
- derived outputs can be recreated from raw data and documented manual corrections;
- no transformation or manual edit is undocumented;
- every dataset records its source, date, licence, CRS and datum;
- every building and utility has an explicit confidence classification;
- large point clouds are processed without loading everything into memory;
- fixed-camera images demonstrate correct layer alignment;
- approximate utilities are never presented as survey-accurate.

## 13. Immediate Execution Sequence

1. Create the dedicated Conda environment.
2. Create the project directory structure.
3. Build the synthetic terrain, building and utility test scene.
4. Verify interactive notebook rendering, HTML export and PNG output.
5. Select and download one ELVIS pilot area.
6. Inventory its metadata and verify its coordinate reference systems.
7. Generate the terrain and LiDAR quality report.
8. Produce the first LoD1 buildings.
9. Test LoD2 roof reconstruction on one or two suitable buildings.
10. Make the LoD1/LoD2 campus-wide processing decision.
11. Import and validate a sample utility network.
12. Scale the proven workflow to the complete St Lucia campus.

## 14. Principal Risks and Controls

| Risk | Control |
|---|---|
| LiDAR is too old for newer buildings | Retain capture dates, flag changed buildings and seek newer UQ data |
| Point density is insufficient for LoD2 | Use LoD1 or obtain BIM/manual models for priority buildings |
| Building footprints are incomplete or misaligned | Compare multiple sources and retain provenance per feature |
| Vertical datums are mixed | Reject unknown data and record every transformation |
| Utility data is two-dimensional or indicative | Use confidence classes and distinguish surveyed, derived and schematic elevations |
| Private UQ utilities are missing from BYDA | Obtain UQ Digital Modelling Office records |
| Critical infrastructure is sensitive | Maintain private and sanitised publication layers |
| Point clouds exceed available memory | Use PDAL streaming, spatial tiles and display downsampling |
| Notebook execution has hidden state | Restart the kernel and run all notebooks during validation |
| 3D rendering loses precision at large coordinates | Render relative to a documented local origin |
