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
```
