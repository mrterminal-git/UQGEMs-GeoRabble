# Phase 10: Reproducibility and Validation

## Purpose

Phase 10 performs a non-destructive, local reproducibility audit of the completed
500 m by 500 m UQ St Lucia public-data pilot. It verifies that the workflow can be
replayed from the preserved source snapshots and validated derived products without
deleting data, changing source geometry or relying on hidden notebook state.

The audit does not re-download live external services. It therefore tests local
reproducibility, integrity and traceability, not the continuing availability of each
provider's website.

## What the runner validates

The Phase 10 runner:

1. Records the hashes of all core outputs declared by the Phase 4-9 manifests.
2. Executes the Phase 1-9 workflow notebooks in phase order, with a new **UQ GIS**
   kernel for every notebook.
3. Confirms that replayable Phase 4-9 pipelines use their validated caches.
4. Executes the Phase 10 validation notebook in its own fresh kernel.
5. Rechecks manifest hashes and confirms that the core derived files did not change.
6. Audits source and model registers for provenance, dates, licences, CRS, vertical
   reference, processing notes and SHA-256 integrity.
7. Directly inspects authoritative raster, point-cloud and GeoPackage CRS metadata.
8. Checks the common rendering origin, building confidence/status fields and utility
   confidence/sensitivity fields.
9. Confirms that public utility geometry remains 2D with null depth/elevation fields.
10. Confirms streamed point-cloud processing, the bounded display sample and valid
    fixed diagnostic figures.
11. Runs the full Pytest and Ruff quality gates.

Each executed notebook is saved separately below
`reports/tables/phase10_notebooks/`; the source notebooks remain unchanged.

## Reproduce the audit

From the repository root:

```powershell
conda run --name uq-gis python pipelines/run_phase10.py
```

This is intentionally non-destructive. It does not remove `data/interim/`,
`data/processed/` or earlier reports. It also does not publish, upload or redistribute
any data. Normal pipeline behaviour may refresh generated reports and figures, but the
audit verifies that all 28 manifest-controlled Phase 4-9 core outputs remain unchanged.

After the CLI audit, open
`notebooks/08_phase10_reproducibility_validation.ipynb` with the **UQ GIS** kernel to
inspect the consolidated tables and dashboard. Running that notebook by itself
refreshes the audit of the existing execution evidence; use the CLI command when a new
fresh-kernel replay is required.

## Outputs

Consolidated evidence:

```text
reports/tables/phase10_reproducibility.json
reports/tables/phase10_notebook_execution.csv
reports/tables/phase10_phase_results.csv
reports/tables/phase10_source_register_audit.csv
reports/tables/phase10_model_register_audit.csv
reports/tables/phase10_manifest_audit.csv
reports/tables/phase10_output_hash_audit.csv
reports/tables/phase10_spatial_reference_audit.csv
reports/tables/phase10_figure_inventory.csv
reports/tables/phase10_requirements_matrix.csv
reports/tables/phase10_software_inventory.csv
reports/tables/phase10_quality_gates.csv
reports/tables/phase10_pytest.txt
reports/tables/phase10_ruff.txt
reports/figures/phase10_validation_dashboard.png
```

Manifest and register:

```text
data/processed/validation/phase10_manifest.json
data/reproducibility_register.csv
```

## Interpretation of a pass

The completed pilot audit passed all 33 Phase 10 checks. All 10 notebooks executed in
fresh kernels, all 166 prior phase checks remained passed, all 20 acquired source
snapshots matched their registered hashes, and all 28 manifest-controlled core outputs
matched and remained byte-identical during replay. Six processing manifests, 22 model
register records and 24 authoritative spatial-reference components were audited. Ruff
and the complete 40-test Pytest suite also passed.

A pass establishes that:

- the saved raw snapshots required by the public-data pilot are present and unchanged;
- prior decision-gate reports and their declared outputs remain valid;
- the notebook workflow runs without errors in isolated kernels;
- manifest-controlled core outputs remain byte-identical during the cached replay;
- authoritative outputs use GDA2020 / MGA zone 56 (`EPSG:7856`);
- AHD is retained for terrain and buildings;
- confidence, source and processing limitations remain attached to the model; and
- unknown-depth utilities have not been converted into invented underground geometry.

It is not the same as a destructive clean-room rebuild. It also cannot establish that
live external APIs will return identical data in the future. The immutable raw
snapshots and their hashes are what make this dated result reproducible.

## Safety and publication boundary

The current utility result contains only three public records near the western pilot
boundary. Their physical depth is unknown, and the Phase 9 terrain drape is only a
visibility device. The model is not survey-grade, asset-location-grade or
excavation-safe.

Urban Utilities redistribution terms still require confirmation before publishing the
interactive HTML or a derivative utility dataset. No Phase 10 output is uploaded or
published automatically.
