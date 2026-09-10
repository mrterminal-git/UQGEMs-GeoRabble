# UQGEMs GeoRabble

Python-first, reproducible development of a three-dimensional GIS model for the University of Queensland's St Lucia campus. The intended model combines terrain, LiDAR-derived LoD1/LoD2 buildings and utility networks while retaining source, datum, accuracy and confidence information.

The detailed workflow is documented in [PLAN_OF_ACTION.md](PLAN_OF_ACTION.md).

## Development environment

The project uses the dedicated Conda environment defined in `environment.yml`.

```powershell
conda env create --file environment.yml
conda activate uq-gis
python -m ipykernel install --user --name uq-gis --display-name "UQ GIS"
python -m pip install --no-deps --editable .
```

In VS Code, open a notebook and select **UQ GIS** as its kernel.

## Validate the setup

Run the automated tests:

```powershell
conda run --name uq-gis pytest
```

Then run `notebooks/00_environment_check.ipynb` from a fresh kernel. It writes a machine-readable diagnostic report to `reports/tables/environment_report.json`.

## Run the Phase 2 synthetic workflow

The Phase 2 scene is entirely fictional and is georeferenced near St Lucia only to test coordinate handling. It must not be interpreted as real UQ asset information.

Run it from the command line:

```powershell
conda run --name uq-gis python pipelines/run_phase2.py
```

Or open `notebooks/phase2_synthetic_workflow.ipynb` with the **UQ GIS** kernel and run all cells. The notebook includes fixed-camera visual checks and an interactive PyVista view.

Generated GIS data is written to `data/processed/synthetic/`; PNGs, interactive HTML and validation reports are written below `reports/`. These generated files are intentionally ignored by Git.

## Run Phase 3 data acquisition

Place the six unchanged ELVIS order archives in `data/raw/elvis/incoming/`, then run:

```powershell
conda run --name uq-gis python pipelines/run_phase3.py
```

This selects the Brisbane 2019 classified LiDAR and 1 m DEM, downloads the small public-data extracts for the pilot area, creates `data/dataset_register.csv`, and writes a validation report and alignment figure below `reports/`. See [PHASE3_DATA_PROVENANCE.md](PHASE3_DATA_PROVENANCE.md) for source roles, licences and limitations.

## Run Phase 4 coordinate normalisation

After Phase 3 passes, run:

```powershell
conda run --name uq-gis python pipelines/run_phase4.py
```

This uses the locally cached official conformal-and-distortion grid to transform the native GDA94 elevation sources to GDA2020 / MGA zone 56 (`EPSG:7856`), preserves AHD elevations, standardises vector layers and records the display-only local origin. See [PHASE4_CRS_NORMALISATION.md](PHASE4_CRS_NORMALISATION.md).

The same workflow can be run interactively from `notebooks/02_phase4_coordinate_normalisation.ipynb` using the **UQ GIS** kernel. Once the first transformation is complete, matching source and configuration hashes allow the notebook to reuse the validated products.

## Run Phase 5 terrain and LiDAR preparation

After Phase 4 passes, run:

```powershell
conda run --name uq-gis python pipelines/run_phase5.py
```

This streams the LiDAR crop, preserves a full-resolution audit copy, creates a filtered
modelling copy and deterministic display sample, and derives the one-metre DTM, DSM,
normalised height, density and ground-residual products. See
[PHASE5_TERRAIN_LIDAR_PREPARATION.md](PHASE5_TERRAIN_LIDAR_PREPARATION.md) for the measured
results and declared filtering decisions.

The same workflow can be run from
`notebooks/03_phase5_terrain_lidar_preparation.ipynb` with the **UQ GIS** kernel.

## Data policy

- Files in `data/raw/` are immutable source material.
- Intermediate and processed datasets must be reproducible from source data and documented manual corrections.
- Large local GIS, LiDAR and 3D outputs are ignored by Git.
- Metadata, processing code and attribution information remain version-controlled.
- Utility information must retain its accuracy and sensitivity classifications and must not be published without permission.

## Status

Phases 1–5 are implemented for the public-data prototype; UQ-controlled BIM and utility acquisition is intentionally deferred until the LoD demonstration is ready. The terrain and LiDAR inputs are now cropped, filtered, quality-controlled and ready for Phase 6 LoD1 building generation.
