# Notebooks

Reusable algorithms belong in `src/uqgems/`; notebooks document and orchestrate them.

- `00_environment_check.ipynb` verifies the Phase 1 environment.
- `phase2_synthetic_workflow.ipynb` exercises the fictional end-to-end test scene.
- `01_phase3_data_inventory.ipynb` acquires and validates the public pilot inputs.
- `02_phase4_coordinate_normalisation.ipynb` normalises all sources to EPSG:7856.
- `03_phase5_terrain_lidar_preparation.ipynb` prepares and reviews terrain and LiDAR.

Use the **UQ GIS** kernel and run a numbered notebook from top to bottom. Reusable
algorithms remain in `src/uqgems/`; notebooks orchestrate them and expose visual checks.
