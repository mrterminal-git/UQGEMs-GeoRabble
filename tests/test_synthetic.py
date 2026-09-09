import numpy as np
import pyogrio
import rasterio

from uqgems.scene import build_plotter
from uqgems.synthetic import (
    authoritative_to_local,
    create_synthetic_dataset,
    local_to_authoritative,
    terrain_height,
    write_synthetic_gis,
)


def test_synthetic_dataset_contains_required_layers() -> None:
    dataset = create_synthetic_dataset()

    assert dataset.crs.to_epsg() == 7856
    assert dataset.terrain.shape == (100, 100)
    assert set(dataset.buildings["lod"]) == {"LoD1", "LoD2"}
    assert set(dataset.buildings["roof_type"]) == {"flat", "pitched"}
    assert set(dataset.utilities["network_type"]) == {"water", "sewer", "electrical"}
    assert len(dataset.utility_nodes) >= 2


def test_coordinate_translation_round_trip_and_utility_depths() -> None:
    dataset = create_synthetic_dataset()
    local = np.array([[12.5, 22.5, 30.0], [490.0, 480.0, 42.0]])

    restored = authoritative_to_local(
        local_to_authoritative(local, dataset.local_origin), dataset.local_origin
    )
    assert np.allclose(restored, local)

    for geometry in dataset.utilities.geometry:
        coordinates = np.asarray(geometry.coords)
        local_coordinates = authoritative_to_local(coordinates, dataset.local_origin)
        surface_z = terrain_height(local_coordinates[:, 0], local_coordinates[:, 1])
        assert np.all(coordinates[:, 2] < surface_z)


def test_coordinate_preserving_exports(tmp_path) -> None:
    dataset = create_synthetic_dataset()
    outputs = write_synthetic_gis(dataset, tmp_path)

    with rasterio.open(outputs["terrain"]) as source:
        assert source.crs.to_epsg() == 7856
        assert source.shape == dataset.terrain.shape
        assert source.transform.almost_equals(dataset.transform)

    layers = {str(row[0]) for row in pyogrio.list_layers(outputs["geopackage"])}
    assert layers == {"buildings", "utilities", "utility_nodes"}
    utilities = pyogrio.read_dataframe(outputs["geopackage"], layer="utilities")
    assert utilities.crs.to_epsg() == 7856
    assert utilities.geometry.has_z.all()


def test_pyvista_scene_can_be_constructed() -> None:
    dataset = create_synthetic_dataset()
    plotter = build_plotter(dataset, off_screen=True)
    try:
        assert len(plotter.renderer.actors) >= 10
    finally:
        plotter.close()
