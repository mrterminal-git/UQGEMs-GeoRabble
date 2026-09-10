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

## Data policy

- Files in `data/raw/` are immutable source material.
- Intermediate and processed datasets must be reproducible from source data and documented manual corrections.
- Large local GIS, LiDAR and 3D outputs are ignored by Git.
- Metadata, processing code and attribution information remain version-controlled.
- Utility information must retain its accuracy and sensitivity classifications and must not be published without permission.

## Status

Phases 1 and 2 are implemented. Phase 3 is implemented for the public-data prototype; UQ-controlled BIM and utility acquisition is intentionally deferred until the LoD demonstration is ready. The synthetic workflow validates terrain, LoD1/LoD2 buildings, underground utilities, coordinate-preserving exports and Python-native 3D visualisation before external data is introduced.
