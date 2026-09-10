# Processing pipelines

Store repeatable command-line entry points and declarative processing configurations here, including PDAL JSON pipelines.

Run the synthetic Phase 2 pipeline from the repository root with:

```powershell
conda run --name uq-gis python pipelines/run_phase2.py
```

The real-data stages use the same pattern:

```powershell
conda run --name uq-gis python pipelines/run_phase3.py
conda run --name uq-gis python pipelines/run_phase4.py
conda run --name uq-gis python pipelines/run_phase5.py
conda run --name uq-gis python pipelines/run_phase6.py
conda run --name uq-gis python pipelines/run_phase7.py
conda run --name uq-gis python pipelines/run_phase8.py
conda run --name uq-gis python pipelines/run_phase9.py
conda run --name uq-gis python pipelines/run_phase10.py
conda run --name uq-gis python pipelines/run_phase11.py
```

Phase 10 is a non-destructive validation replay. It executes each notebook in a fresh
kernel and writes separate executed copies below `reports/tables/phase10_notebooks/`.

Phase 11 creates the orthophoto terrain/roof skin, schematic facade material, textured
GLB, switchable HTML viewer and fixed visual checks. It leaves all Phase 5/7/8
authoritative geometry unchanged.
