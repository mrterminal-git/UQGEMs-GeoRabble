# Data directories

- `raw/`: immutable source downloads and their original metadata.
- `interim/`: cropped, reprojected or otherwise temporary products.
- `manual/`: documented human corrections that can be reapplied by the workflow.
- `processed/`: final machine-generated datasets used by visualisations and reports.

Large data files are intentionally excluded from Git.

`reproducibility_register.csv` records the final non-destructive Phase 10 validation
result and the hash of its consolidated report.
