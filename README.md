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

## Data policy

- Files in `data/raw/` are immutable source material.
- Intermediate and processed datasets must be reproducible from source data and documented manual corrections.
- Large local GIS, LiDAR and 3D outputs are ignored by Git.
- Metadata, processing code and attribution information remain version-controlled.
- Utility information must retain its accuracy and sensitivity classifications and must not be published without permission.

## Status

Phase 1 establishes the environment, repository structure, validation code and initial notebook. Phase 2 will validate the complete pipeline with a small synthetic terrain/building/utility scene before external data is introduced.

