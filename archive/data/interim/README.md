# Interim data

This directory contains reproducible temporary products such as cropped point clouds and reprojected rasters.

Phase 4 writes `normalised/` containing the EPSG:7856 DEM and classified LAZ, a multi-layer footprint GeoPackage, a validated imagery working copy, the transformation manifest and the display-only local-origin definition. These products are generated and ignored by Git.

Phase 5 writes `phase5/` containing exact-pilot DTM/DSM and diagnostic rasters, a
full-resolution LiDAR audit crop, a filtered analysis crop, a deterministic display
sample and the hash-based preparation manifest. These products retain EPSG:7856 and AHD
and are generated and ignored by Git.
