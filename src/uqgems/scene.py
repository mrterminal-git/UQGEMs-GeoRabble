"""PyVista scene construction and export for the synthetic 3D GIS test."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
from matplotlib import font_manager
from PIL import Image, ImageColor, ImageDraw, ImageFont

from uqgems.synthetic import SyntheticDataset, authoritative_to_local

NETWORK_COLOURS = {
    "water": "#168AAD",
    "sewer": "#7F5539",
    "electrical": "#F4A261",
}
BUILDING_COLOURS = {"LoD1": "#8796A5", "LoD2": "#D47F6A"}
SYMBOLIC_UTILITY_RADII_M = {"water": 0.8, "sewer": 1.0, "electrical": 0.6}

CAMERAS: dict[str, dict[str, tuple[float, float, float]]] = {
    "plan": {
        "position": (250.0, 250.0, 850.0),
        "focal_point": (250.0, 250.0, 25.0),
        "view_up": (0.0, 1.0, 0.0),
    },
    "oblique": {
        "position": (720.0, -570.0, 430.0),
        "focal_point": (250.0, 250.0, 27.0),
        "view_up": (0.0, 0.0, 1.0),
    },
    "underground": {
        "position": (660.0, -470.0, 145.0),
        "focal_point": (230.0, 240.0, 20.0),
        "view_up": (0.0, 0.0, 1.0),
    },
}


def _display_z(values: Any, anchor: float, vertical_exaggeration: float) -> np.ndarray:
    z = np.asarray(values, dtype=float)
    return anchor + (z - anchor) * vertical_exaggeration


def _terrain_mesh(
    dataset: SyntheticDataset, vertical_exaggeration: float, z_anchor: float
) -> pv.StructuredGrid:
    x = dataset.x_centres_local
    y = dataset.y_centres_local_descending[::-1]
    elevation = dataset.terrain[::-1, :].astype(float)
    x_grid, y_grid = np.meshgrid(x, y)
    z_grid = _display_z(elevation, z_anchor, vertical_exaggeration)
    mesh = pv.StructuredGrid(x_grid, y_grid, z_grid)
    mesh["Elevation_m_AHD"] = elevation.ravel(order="F")
    return mesh


def _pitched_building_mesh(
    bounds: tuple[float, float, float, float],
    ground_z: float,
    eave_z: float,
    ridge_z: float,
) -> pv.PolyData:
    x_min, y_min, x_max, y_max = bounds
    y_mid = (y_min + y_max) / 2.0
    points = np.array(
        [
            [x_min, y_min, ground_z],
            [x_max, y_min, ground_z],
            [x_max, y_max, ground_z],
            [x_min, y_max, ground_z],
            [x_min, y_min, eave_z],
            [x_max, y_min, eave_z],
            [x_max, y_max, eave_z],
            [x_min, y_max, eave_z],
            [x_min, y_mid, ridge_z],
            [x_max, y_mid, ridge_z],
        ]
    )
    faces = np.hstack(
        [
            [4, 0, 3, 2, 1],
            [4, 0, 1, 5, 4],
            [4, 3, 7, 6, 2],
            [4, 0, 4, 7, 3],
            [3, 4, 8, 7],
            [4, 1, 2, 6, 5],
            [3, 5, 6, 9],
            [4, 4, 5, 9, 8],
            [4, 7, 8, 9, 6],
        ]
    )
    return pv.PolyData(points, faces)


def _building_mesh(
    row: Any,
    local_origin: tuple[float, float],
    vertical_exaggeration: float,
    z_anchor: float,
) -> pv.DataSet:
    min_easting, min_northing, max_easting, max_northing = row.geometry.bounds
    local_bounds = authoritative_to_local(
        [[min_easting, min_northing], [max_easting, max_northing]], local_origin
    )
    x_min, y_min = local_bounds[0]
    x_max, y_max = local_bounds[1]
    ground_z, eave_z, ridge_z = _display_z(
        [row.ground_z_ahd, row.eave_z_ahd, row.ridge_z_ahd],
        z_anchor,
        vertical_exaggeration,
    )
    if row.roof_type == "pitched":
        return _pitched_building_mesh(
            (x_min, y_min, x_max, y_max), ground_z, eave_z, ridge_z
        )
    return pv.Box(bounds=(x_min, x_max, y_min, y_max, ground_z, eave_z))


def _utility_mesh(
    geometry: Any,
    local_origin: tuple[float, float],
    vertical_exaggeration: float,
    z_anchor: float,
    radius: float,
) -> pv.PolyData:
    points = authoritative_to_local(np.asarray(geometry.coords), local_origin)
    points[:, 2] = _display_z(points[:, 2], z_anchor, vertical_exaggeration)
    centreline = pv.lines_from_points(points, close=False)
    return centreline.tube(radius=radius, capping=True)


def apply_camera(plotter: pv.Plotter, camera: str) -> None:
    """Apply one of the documented, fixed camera definitions."""
    if camera not in CAMERAS:
        raise ValueError(f"Unknown camera {camera!r}; expected one of {sorted(CAMERAS)}")
    settings = CAMERAS[camera]
    plotter.camera_position = [
        settings["position"],
        settings["focal_point"],
        settings["view_up"],
    ]


def build_plotter(
    dataset: SyntheticDataset,
    *,
    camera: str = "oblique",
    terrain_opacity: float = 0.72,
    vertical_exaggeration: float = 1.0,
    show_terrain: bool = True,
    show_buildings: bool = True,
    utility_types: set[str] | None = None,
    show_nodes: bool = True,
    show_annotations: bool = True,
    off_screen: bool = False,
    notebook: bool | None = None,
    window_size: tuple[int, int] = (1200, 800),
) -> pv.Plotter:
    """Create a configurable PyVista plotter in local rendering coordinates."""
    if vertical_exaggeration <= 0:
        raise ValueError("vertical_exaggeration must be positive")
    if not 0.0 <= terrain_opacity <= 1.0:
        raise ValueError("terrain_opacity must be between zero and one")
    selected_utilities = utility_types or set(NETWORK_COLOURS)
    unknown = selected_utilities - set(NETWORK_COLOURS)
    if unknown:
        raise ValueError(f"Unknown utility types: {sorted(unknown)}")

    plotter = pv.Plotter(off_screen=off_screen, notebook=notebook, window_size=window_size)
    plotter.set_background("#EDF2F7", top="#BFD7EA")
    z_anchor = float(dataset.terrain.min()) - 5.0

    legend_entries: list[list[str]] = []
    if show_terrain:
        terrain = _terrain_mesh(dataset, vertical_exaggeration, z_anchor)
        plotter.add_mesh(
            terrain,
            scalars="Elevation_m_AHD",
            cmap="terrain",
            opacity=terrain_opacity,
            show_scalar_bar=True,
            scalar_bar_args={"title": "Elevation (m AHD)", "fmt": "%.1f"},
        )
        legend_entries.append(["Synthetic terrain", "#8DBF67"])

    if show_buildings:
        for row in dataset.buildings.itertuples():
            colour = BUILDING_COLOURS[row.lod]
            plotter.add_mesh(
                _building_mesh(row, dataset.local_origin, vertical_exaggeration, z_anchor),
                color=colour,
                show_edges=True,
                edge_color="#374151",
                line_width=1.0,
            )
        for lod, colour in BUILDING_COLOURS.items():
            legend_entries.append([f"{lod} building", colour])

    for row in dataset.utilities.itertuples():
        if row.network_type not in selected_utilities:
            continue
        colour = NETWORK_COLOURS[row.network_type]
        mesh = _utility_mesh(
            row.geometry,
            dataset.local_origin,
            vertical_exaggeration,
            z_anchor,
            SYMBOLIC_UTILITY_RADII_M[row.network_type],
        )
        plotter.add_mesh(mesh, color=colour, smooth_shading=True)

    if show_nodes:
        for row in dataset.utility_nodes.itertuples():
            if row.network_type not in selected_utilities:
                continue
            point = authoritative_to_local(
                np.asarray(row.geometry.coords[0]), dataset.local_origin
            )
            point[2] = _display_z(point[2], z_anchor, vertical_exaggeration)
            plotter.add_mesh(
                pv.Sphere(radius=3.0, center=point),
                color=NETWORK_COLOURS[row.network_type],
                show_edges=True,
                edge_color="#1F2937",
            )

    for network_type in sorted(selected_utilities):
        legend_entries.append([network_type.title(), NETWORK_COLOURS[network_type]])

    if show_annotations:
        plotter.add_legend(legend_entries, bcolor="#FFFFFF", border=True, size=(0.18, 0.24))
        plotter.add_text(
            "SYNTHETIC / NON-AUTHORITATIVE",
            position="upper_left",
            font_size=11,
            color="#8B1E1E",
        )
    plotter.add_axes(line_width=2)
    plotter.show_grid(
        xtitle="Local easting (m)",
        ytitle="Local northing (m)",
        ztitle="Elevation (m AHD)",
        color="#4B5563",
        font_size=9,
    )
    apply_camera(plotter, camera)
    return plotter


def _annotate_png(path: Path) -> None:
    """Add a stable title and colour key after VTK completes its 3D render."""
    font_path = font_manager.findfont("DejaVu Sans")
    title_font = ImageFont.truetype(font_path, 22)
    legend_font = ImageFont.truetype(font_path, 18)
    rows = [
        ("Synthetic terrain", "#8DBF67"),
        ("LoD1 building", BUILDING_COLOURS["LoD1"]),
        ("LoD2 building", BUILDING_COLOURS["LoD2"]),
        ("Electrical", NETWORK_COLOURS["electrical"]),
        ("Sewer", NETWORK_COLOURS["sewer"]),
        ("Water", NETWORK_COLOURS["water"]),
    ]
    with Image.open(path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text((18, 12), "SYNTHETIC / NOT REAL UQ DATA", font=title_font, fill="#8B1E1E")

    right = image.width - 24
    left = right - 260
    top = 34
    row_height = 30
    bottom = top + 20 + len(rows) * row_height
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=6,
        fill="#FFFFFF",
        outline="#94A3B8",
        width=1,
    )
    for index, (label, colour) in enumerate(rows):
        y = top + 13 + index * row_height
        draw.rectangle(
            (left + 14, y + 3, left + 31, y + 20),
            fill=ImageColor.getrgb(colour),
            outline="#334155",
        )
        draw.text((left + 42, y), label, font=legend_font, fill="#1F2937")
    image.save(path)


def render_png(
    dataset: SyntheticDataset,
    output_path: str | Path,
    *,
    camera: str = "oblique",
    terrain_opacity: float = 0.72,
) -> Path:
    """Render a deterministic, fixed-camera PNG using off-screen VTK."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plotter = build_plotter(
        dataset,
        camera=camera,
        terrain_opacity=terrain_opacity,
        show_annotations=False,
        off_screen=True,
        notebook=False,
    )
    try:
        plotter.show(screenshot=str(destination), auto_close=False)
    finally:
        plotter.close()
        pv.close_all()
    _annotate_png(destination)
    return destination


def export_interactive_html(
    dataset: SyntheticDataset,
    output_path: str | Path,
    *,
    terrain_opacity: float = 0.55,
) -> Path:
    """Export the synthetic scene as a self-contained interactive HTML file."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plotter = build_plotter(
        dataset,
        camera="oblique",
        terrain_opacity=terrain_opacity,
        off_screen=True,
        notebook=False,
    )
    try:
        plotter.render()
        plotter.export_html(destination)
    finally:
        plotter.close()
        pv.close_all()
    return destination
