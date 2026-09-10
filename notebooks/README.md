# Notebooks

Reusable algorithms belong in `src/uqgems/`; notebooks document and orchestrate them.

- `00_environment_check.ipynb` verifies the Phase 1 environment.
- `phase2_synthetic_workflow.ipynb` exercises the fictional end-to-end test scene.
- `01_phase3_data_inventory.ipynb` acquires and validates the public pilot inputs.
- `02_phase4_coordinate_normalisation.ipynb` normalises all sources to EPSG:7856.
- `03_phase5_terrain_lidar_preparation.ipynb` prepares and reviews terrain and LiDAR.
- `04_phase6_lod1_buildings.ipynb` creates and validates conservative LoD1 buildings.
- `05_phase7_lod2_feasibility.ipynb` assesses selective LoD2 roofs and the mixed-LoD
  decision gate.
- `06_phase8_utility_standardisation.ipynb` acquires, standardises and validates the
  selected BCC and Urban Utilities public records without inventing utility depths.
- `07_phase9_integrated_visualisation.ipynb` assembles the real terrain, LiDAR preview,
  mixed-LoD buildings and display-only public utility alignments into an interactive
  scene and fixed visual checks.
- `08_phase10_reproducibility_validation.ipynb` presents the consolidated fresh-kernel,
  provenance, hash, spatial-reference, confidence and quality-gate audit.

Use the **UQ GIS** kernel and run a numbered notebook from top to bottom. Reusable
algorithms remain in `src/uqgems/`; notebooks orchestrate them and expose visual checks.
