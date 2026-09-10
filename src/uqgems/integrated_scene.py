"""Reusable real-data scene construction for the integrated Phase 9 pilot."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import laspy
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pyogrio
import pyvista as pv
import rasterio
import trimesh
from affine import Affine
from matplotlib import font_manager
from PIL import Image, ImageColor, ImageDraw, ImageFont
from shapely.geometry import LineString, box

from uqgems.acquisition import PILOT_AREA
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG

NETWORK_COLOURS = {
    "stormwater": "#00A6D6",
    "water": "#2357D9",
    "sewer": "#8B5A2B",
    "electricity": "#E5B700",
    "gas": "#F28E2B",
    "telecommunications": "#8E44AD",
}
CONFIDENCE_COLOURS = {
    "high": "#2A9D8F",
    "medium": "#F4A261",
    "low": "#D1495B",
    "unknown": "#6C757D",
}
AGE_COLOURS = {
    "2020 or later": "#2A9D8F",
    "2010-2019": "#E9C46A",
    "before 2010": "#E76F51",
    "unknown": "#6C757D",
}
BUILDING_COLOURS = {
    "reliable LoD2": "#754AAE",
    "approximate LoD2": "#179CA2",
    "LoD1": "#A7B0BA",
}

CAMERAS = {
    "plan": {
        "position": (0.0, 0.0, 760.0),
        "focal_point": (0.0, 0.0, 18.0),
        "view_up": (0.0, 1.0, 0.0),
    },
    "northeast": {
        "position": (570.0, -650.0, 410.0),
        "focal_point": (0.0, 0.0, 18.0),
        "view_up": (0.0, 0.0, 1.0),
    },
    "southwest": {
        "position": (-610.0, 620.0, 370.0),
        "focal_point": (0.0, 0.0, 18.0),
        "view_up": (0.0, 0.0, 1.0),
    },
    "utility_cutaway": {
        "position": (-510.0, -430.0, 170.0),
        "focal_point": (-220.0, -45.0, 16.0),
        "view_up": (0.0, 0.0, 1.0),
    },
}


@dataclass(frozen=True)
class SceneDisplayConfig:
    """Display-only controls; none of these alter authoritative source geometry."""

    terrain_opacity: float = 0.68
    building_opacity: float = 0.96
    vertical_exaggeration: float = 1.0
    utility_drape_offset_m: float = 0.75
    symbolic_utility_radius_m: float = 0.65
    utility_dash_length_m: float = 2.0
    utility_gap_length_m: float = 1.0
    utility_types: tuple[str, ...] = ("stormwater", "water")
    utility_colour_by: str = "network_type"
    show_terrain: bool = True
    show_buildings: bool = True
    show_utilities: bool = True
    show_nodes: bool = True
    show_point_cloud: bool = False
    selected_building_ids: tuple[str, ...] = ()
    selected_asset_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        if not 0.0 <= self.terrain_opacity <= 1.0:
            raise ValueError("terrain_opacity must be between zero and one")
        if not 0.0 <= self.building_opacity <= 1.0:
            raise ValueError("building_opacity must be between zero and one")
        if self.vertical_exaggeration <= 0:
            raise ValueError("vertical_exaggeration must be positive")
        if self.utility_drape_offset_m < 0:
            raise ValueError("utility_drape_offset_m cannot be negative")
        if self.symbolic_utility_radius_m <= 0:
            raise ValueError("symbolic_utility_radius_m must be positive")
        if self.utility_dash_length_m <= 0 or self.utility_gap_length_m < 0:
            raise ValueError("utility dash and gap lengths must be valid")
        unknown = set(self.utility_types) - set(NETWORK_COLOURS)
        if unknown:
            raise ValueError(f"Unknown utility types: {sorted(unknown)}")
        allowed_colour_fields = {"network_type", "confidence", "accuracy", "age"}
        if self.utility_colour_by not in allowed_colour_fields:
            raise ValueError(f"utility_colour_by must be one of {sorted(allowed_colour_fields)}")


@dataclass
class IntegratedSceneData:
    """In-memory authoritative inputs plus a deterministic display-cloud sample."""

    terrain: np.ndarray
    terrain_transform: Affine
    buildings: gpd.GeoDataFrame
    building_meshes: dict[str, trimesh.Trimesh]
    utilities: gpd.GeoDataFrame
    point_cloud_xyz: np.ndarray
    point_cloud_classification: np.ndarray
    local_origin: tuple[float, float, float]


def display_z(values: Any, anchor: float, vertical_exaggeration: float) -> np.ndarray:
    z = np.asarray(values, dtype=float)
    return anchor + (z - anchor) * vertical_exaggeration


def _load_meshes(path: Path) -> dict[str, trimesh.Trimesh]:
    scene = trimesh.load(path, force="scene")
    meshes: dict[str, trimesh.Trimesh] = {}
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(transform)
        meshes[str(node_name)] = mesh
    return meshes


def _load_utilities(path: Path) -> gpd.GeoDataFrame:
    layer_names = set(pyogrio.list_layers(path)[:, 0])
    frames = [
        gpd.read_file(path, layer=layer)
        for layer in ("utility_lines", "utility_nodes")
        if layer in layer_names
    ]
    if not frames:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=TARGET_EPSG)
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=TARGET_EPSG
    )


def _load_point_cloud(path: Path, maximum_points: int) -> tuple[np.ndarray, np.ndarray]:
    with laspy.open(path) as source:
        points = source.read()
    count = len(points)
    indices = (
        np.arange(count)
        if count <= maximum_points
        else np.linspace(0, count - 1, maximum_points, dtype=np.int64)
    )
    xyz = np.column_stack(
        [
            np.asarray(points.x)[indices] - float(LOCAL_ORIGIN[0]),
            np.asarray(points.y)[indices] - float(LOCAL_ORIGIN[1]),
            np.asarray(points.z)[indices],
        ]
    )
    classification = np.asarray(points.classification)[indices].astype(np.uint8)
    return xyz, classification


def load_integrated_scene_data(
    project_root: str | Path, maximum_point_cloud_points: int = 30_000
) -> IntegratedSceneData:
    """Load validated Phase 5, 7 and 8 products for scene construction."""
    root = Path(project_root).resolve()
    paths = {
        "terrain": root / "data/interim/phase5/elevation/dtm_1m.tif",
        "buildings": root / "data/processed/lod2/lod2_buildings.gpkg",
        "building_mesh": root / "data/processed/lod2/uq_pilot_mixed_lod.glb",
        "utilities": root / "data/processed/utilities/uq_pilot_public_utilities.gpkg",
        "point_cloud": root / "data/interim/phase5/pointcloud/uq_pilot_display.laz",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Integrated scene inputs are missing: " + ", ".join(missing))
    with rasterio.open(paths["terrain"]) as source:
        terrain = source.read(1).astype(float)
        if source.nodata is not None:
            terrain[terrain == source.nodata] = np.nan
        transform = source.transform
    buildings = gpd.read_file(paths["buildings"], layer="building_status")
    meshes = _load_meshes(paths["building_mesh"])
    utilities = _load_utilities(paths["utilities"])
    xyz, classification = _load_point_cloud(paths["point_cloud"], maximum_point_cloud_points)
    return IntegratedSceneData(
        terrain=terrain,
        terrain_transform=transform,
        buildings=buildings,
        building_meshes=meshes,
        utilities=utilities,
        point_cloud_xyz=xyz,
        point_cloud_classification=classification,
        local_origin=tuple(float(value) for value in LOCAL_ORIGIN),
    )


def terrain_at_xy(
    terrain: np.ndarray, transform: Affine, x: np.ndarray, y: np.ndarray
) -> np.ndarray:
    """Sample raster cells at authoritative XY, returning NaN outside the raster."""
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    columns = np.floor((x_values - transform.c) / transform.a).astype(int)
    rows = np.floor((y_values - transform.f) / transform.e).astype(int)
    valid = (rows >= 0) & (rows < terrain.shape[0]) & (columns >= 0) & (columns < terrain.shape[1])
    values = np.full(x_values.shape, np.nan, dtype=float)
    values[valid] = terrain[rows[valid], columns[valid]]
    return values


def _line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return [part for part in geometry.geoms if part.geom_type == "LineString"]
    return []


def densify_line(geometry: LineString, spacing_m: float = 1.0) -> np.ndarray:
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    distances = np.arange(0.0, geometry.length, spacing_m)
    distances = np.append(distances, geometry.length)
    points = [geometry.interpolate(float(distance)) for distance in distances]
    return np.asarray([(point.x, point.y) for point in points], dtype=float)


def drape_utility_geometry(
    geometry: Any,
    terrain: np.ndarray,
    transform: Affine,
    local_origin: tuple[float, float, float],
    offset_m: float,
    spacing_m: float = 1.0,
) -> list[np.ndarray]:
    """Create display-only local XYZ lines clipped and draped on the AHD terrain."""
    pilot = box(*PILOT_AREA.projected_bounds)
    output: list[np.ndarray] = []
    for part in _line_parts(geometry.intersection(pilot)):
        xy = densify_line(part, spacing_m=spacing_m)
        z = terrain_at_xy(terrain, transform, xy[:, 0], xy[:, 1])
        valid = np.isfinite(z)
        if valid.sum() < 2:
            continue
        local = np.column_stack(
            [
                xy[valid, 0] - local_origin[0],
                xy[valid, 1] - local_origin[1],
                z[valid] + offset_m,
            ]
        )
        output.append(local)
    return output


def dashed_segments(
    points: np.ndarray, dash_length_m: float = 2.0, gap_length_m: float = 1.0
) -> list[np.ndarray]:
    """Split a dense 3D polyline into approximate display-only dash segments."""
    values = np.asarray(points, dtype=float)
    if len(values) < 2:
        return []
    edge_lengths = np.linalg.norm(np.diff(values[:, :2], axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(edge_lengths)])
    period = dash_length_m + gap_length_m
    if period <= 0 or dash_length_m <= 0:
        raise ValueError("dash_length_m must be positive and gap_length_m non-negative")
    on_edges = ((cumulative[:-1] + edge_lengths / 2.0) % period) < dash_length_m
    segments: list[np.ndarray] = []
    start = None
    for index, is_on in enumerate(on_edges):
        if is_on and start is None:
            start = index
        if start is not None and (not is_on or index == len(on_edges) - 1):
            end = index + 1 if is_on and index == len(on_edges) - 1 else index
            segment = values[start : end + 1]
            if len(segment) >= 2:
                segments.append(segment)
            start = None
    return segments


def _terrain_grid(
    data: IntegratedSceneData,
    config: SceneDisplayConfig,
    step: int = 4,
    western_cutaway_band_m: float | None = None,
) -> pv.StructuredGrid:
    rows = np.arange(0, data.terrain.shape[0], step)
    columns = np.arange(0, data.terrain.shape[1], step)
    x = data.terrain_transform.c + (columns + 0.5) * data.terrain_transform.a
    y = data.terrain_transform.f + (rows + 0.5) * data.terrain_transform.e
    local_x = x - data.local_origin[0]
    local_y = y - data.local_origin[1]
    if western_cutaway_band_m is not None:
        keep = local_x <= local_x.min() + western_cutaway_band_m
        columns = columns[keep]
        local_x = local_x[keep]
    elevation = data.terrain[np.ix_(rows, columns)]
    xx, yy = np.meshgrid(local_x, local_y)
    anchor = float(np.nanmin(data.terrain))
    zz = display_z(elevation, anchor, config.vertical_exaggeration)
    grid = pv.StructuredGrid(xx, yy, zz)
    grid["Elevation_m_AHD"] = elevation.ravel(order="F")
    return grid


def _pyvista_mesh(mesh: trimesh.Trimesh, anchor: float, exaggeration: float) -> pv.PolyData:
    vertices = np.asarray(mesh.vertices).copy()
    vertices[:, 2] = display_z(vertices[:, 2], anchor, exaggeration)
    faces = np.column_stack(
        [np.full(len(mesh.faces), 3, dtype=np.int64), np.asarray(mesh.faces, dtype=np.int64)]
    ).ravel()
    return pv.PolyData(vertices, faces)


def _building_colour(status: Any) -> str:
    if status == "reliable LoD2":
        return BUILDING_COLOURS["reliable LoD2"]
    if status == "approximate LoD2":
        return BUILDING_COLOURS["approximate LoD2"]
    return BUILDING_COLOURS["LoD1"]


def _utility_colour(row: Any, config: SceneDisplayConfig) -> str:
    if config.utility_colour_by == "confidence":
        return CONFIDENCE_COLOURS.get(str(row.confidence), CONFIDENCE_COLOURS["unknown"])
    if config.utility_colour_by == "accuracy":
        return CONFIDENCE_COLOURS.get(str(row.confidence_xy), CONFIDENCE_COLOURS["unknown"])
    if config.utility_colour_by == "age":
        return AGE_COLOURS[_utility_age_band(row)]
    return NETWORK_COLOURS.get(str(row.network_type), "#6C757D")


def _utility_age_band(row: Any) -> str:
    survey_date = pd.to_datetime(getattr(row, "survey_date", None), errors="coerce", utc=True)
    if pd.isna(survey_date):
        return "unknown"
    if survey_date.year >= 2020:
        return "2020 or later"
    if survey_date.year >= 2010:
        return "2010-2019"
    return "before 2010"


def _utility_legend_label(row: Any, config: SceneDisplayConfig) -> str:
    network = str(row.network_type).title()
    if config.utility_colour_by == "confidence":
        qualifier = f"confidence {row.confidence}"
    elif config.utility_colour_by == "accuracy":
        qualifier = f"XY confidence {row.confidence_xy}"
    elif config.utility_colour_by == "age":
        qualifier = f"survey age {_utility_age_band(row)}"
    else:
        qualifier = "depth unknown"
    return f"{network} — {qualifier}"


def apply_camera(plotter: pv.Plotter, camera: str) -> None:
    if camera not in CAMERAS:
        raise ValueError(f"Unknown camera {camera!r}; expected one of {sorted(CAMERAS)}")
    settings = CAMERAS[camera]
    plotter.camera_position = [
        settings["position"],
        settings["focal_point"],
        settings["view_up"],
    ]


def build_integrated_plotter(
    data: IntegratedSceneData,
    config: SceneDisplayConfig | None = None,
    *,
    camera: str = "northeast",
    cutaway: bool = False,
    off_screen: bool = False,
    notebook: bool | None = None,
    show_screen_annotations: bool = True,
    window_size: tuple[int, int] = (1500, 950),
) -> pv.Plotter:
    """Build a configurable PyVista plotter using display-local XY coordinates."""
    config = config or SceneDisplayConfig()
    config.validate()
    plotter = pv.Plotter(off_screen=off_screen, notebook=notebook, window_size=window_size)
    plotter.set_background("#EAF2F8", top="#B7D3E8")
    anchor = float(np.nanmin(data.terrain))
    legend: list[list[str]] = []
    utility_legend_entries: set[tuple[str, str]] = set()

    if config.show_terrain:
        grid = _terrain_grid(
            data,
            config,
            step=4,
            western_cutaway_band_m=20.0 if cutaway else None,
        )
        plotter.add_mesh(
            grid,
            scalars="Elevation_m_AHD",
            cmap="terrain",
            opacity=0.55 if cutaway else config.terrain_opacity,
            show_scalar_bar=True,
            scalar_bar_args={"title": "Terrain m AHD", "fmt": "%.1f"},
        )
        legend.append(["AHD terrain", "#7EB26D"])

    selected_buildings = set(config.selected_building_ids)
    if config.show_buildings:
        for row in data.buildings.itertuples():
            building_id = str(row.building_id)
            if building_id not in data.building_meshes:
                continue
            if selected_buildings and building_id not in selected_buildings:
                continue
            mesh = data.building_meshes[building_id]
            if cutaway and mesh.bounds[0, 0] > -220.0:
                continue
            plotter.add_mesh(
                _pyvista_mesh(mesh, anchor, config.vertical_exaggeration),
                color=_building_colour(row.lod2_status),
                opacity=0.42 if cutaway else config.building_opacity,
                show_edges=True,
                edge_color="#46515C",
                line_width=0.6,
                name=f"building:{building_id}",
            )
        legend.extend(
            [
                ["LoD1 fallback", BUILDING_COLOURS["LoD1"]],
                ["Reliable LoD2", BUILDING_COLOURS["reliable LoD2"]],
                ["Approximate LoD2", BUILDING_COLOURS["approximate LoD2"]],
            ]
        )

    selected_assets = set(config.selected_asset_ids)
    utility_rows = data.utilities[
        data.utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ]
    if config.show_utilities:
        for row in utility_rows.itertuples():
            if row.network_type not in config.utility_types:
                continue
            if selected_assets and row.asset_id not in selected_assets:
                continue
            colour = _utility_colour(row, config)
            utility_legend_entries.add((_utility_legend_label(row, config), colour))
            for part_index, points in enumerate(
                drape_utility_geometry(
                    row.geometry,
                    data.terrain,
                    data.terrain_transform,
                    data.local_origin,
                    config.utility_drape_offset_m,
                )
            ):
                points = points.copy()
                points[:, 2] = display_z(points[:, 2], anchor, config.vertical_exaggeration)
                for dash_index, segment in enumerate(
                    dashed_segments(
                        points,
                        config.utility_dash_length_m,
                        config.utility_gap_length_m,
                    )
                ):
                    line = pv.lines_from_points(segment, close=False)
                    plotter.add_mesh(
                        line.tube(radius=config.symbolic_utility_radius_m, capping=True),
                        color=colour,
                        smooth_shading=True,
                        name=(f"utility:{row.asset_id}:{part_index}:{dash_index}"),
                    )

    node_rows = data.utilities[data.utilities.geometry.geom_type == "Point"]
    if config.show_nodes:
        for row in node_rows.itertuples():
            if row.network_type not in config.utility_types:
                continue
            if selected_assets and row.asset_id not in selected_assets:
                continue
            utility_legend_entries.add(
                (_utility_legend_label(row, config), _utility_colour(row, config))
            )
            x, y = row.geometry.x, row.geometry.y
            terrain_z = terrain_at_xy(
                data.terrain,
                data.terrain_transform,
                np.asarray([x]),
                np.asarray([y]),
            )[0]
            if not math.isfinite(terrain_z):
                continue
            local_point = np.asarray(
                [
                    x - data.local_origin[0],
                    y - data.local_origin[1],
                    display_z(
                        terrain_z + config.utility_drape_offset_m,
                        anchor,
                        config.vertical_exaggeration,
                    ),
                ]
            )
            plotter.add_mesh(
                pv.Sphere(radius=1.8, center=local_point),
                color=_utility_colour(row, config),
                show_edges=True,
                edge_color="white",
                name=f"utility-node:{row.asset_id}",
            )

    for label, colour in sorted(utility_legend_entries):
        legend.append([label, colour])

    if config.show_point_cloud and len(data.point_cloud_xyz):
        points = data.point_cloud_xyz.copy()
        points[:, 2] = display_z(points[:, 2], anchor, config.vertical_exaggeration)
        cloud = pv.PolyData(points)
        cloud["Classification"] = data.point_cloud_classification
        plotter.add_mesh(
            cloud,
            scalars="Classification",
            cmap="viridis",
            point_size=2.0,
            render_points_as_spheres=False,
            show_scalar_bar=False,
        )
        legend.append(["LiDAR preview", "#3F7CAC"])

    if show_screen_annotations:
        plotter.add_legend(legend, bcolor="#FFFFFF", border=True, size=(0.24, 0.25))
        plotter.add_text(
            "PUBLIC UTILITY ALIGNMENT ONLY — DEPTH UNKNOWN",
            position="upper_left",
            font_size=10,
            color="#8B1E1E",
        )
    plotter.add_axes(line_width=2)
    plotter.show_grid(
        xtitle="Local easting (m)",
        ytitle="Local northing (m)",
        ztitle="Display elevation (m; terrain/buildings AHD)",
        color="#4B5563",
        font_size=9,
    )
    apply_camera(plotter, "utility_cutaway" if cutaway else camera)
    if cutaway:
        plotter.camera.zoom(1.7)
    return plotter


def _plotly_camera(camera: str) -> dict[str, dict[str, float]]:
    eyes = {
        "Northeast": {"x": 1.55, "y": -1.65, "z": 1.05},
        "Southwest": {"x": -1.55, "y": 1.55, "z": 0.95},
        "Plan": {"x": 0.0, "y": 0.0, "z": 2.6},
    }
    return {"eye": eyes[camera], "up": {"x": 0.0, "y": 0.0, "z": 1.0}}


def _plotly_mesh_trace(
    mesh: trimesh.Trimesh,
    row: Any,
    anchor: float,
    config: SceneDisplayConfig,
    show_legend: bool,
) -> go.Mesh3d:
    vertices = np.asarray(mesh.vertices).copy()
    vertices[:, 2] = display_z(vertices[:, 2], anchor, config.vertical_exaggeration)
    name = (
        str(row.building_name)
        if pd.notna(row.building_name) and str(row.building_name).strip()
        else str(row.building_id)
    )
    hover = (
        f"<b>{name}</b><br>ID: {row.building_id}<br>Output: {row.output_lod}"
        f"<br>Status: {row.lod2_status}<br>Confidence: {row.confidence}<extra></extra>"
    )
    return go.Mesh3d(
        x=vertices[:, 0],
        y=vertices[:, 1],
        z=vertices[:, 2],
        i=mesh.faces[:, 0],
        j=mesh.faces[:, 1],
        k=mesh.faces[:, 2],
        color=_building_colour(row.lod2_status),
        opacity=config.building_opacity,
        flatshading=True,
        name=str(row.output_lod),
        legendgroup=str(row.output_lod),
        showlegend=show_legend,
        hovertemplate=hover,
    )


def build_plotly_figure(
    data: IntegratedSceneData, config: SceneDisplayConfig | None = None
) -> go.Figure:
    """Build the hoverable, layer-toggleable integrated notebook/HTML scene."""
    config = config or SceneDisplayConfig()
    config.validate()
    figure = go.Figure()
    roles: list[str] = []
    anchor = float(np.nanmin(data.terrain))
    terrain_step = 5
    rows = np.arange(0, data.terrain.shape[0], terrain_step)
    columns = np.arange(0, data.terrain.shape[1], terrain_step)
    x = data.terrain_transform.c + (columns + 0.5) * data.terrain_transform.a - data.local_origin[0]
    y = data.terrain_transform.f + (rows + 0.5) * data.terrain_transform.e - data.local_origin[1]
    terrain = data.terrain[np.ix_(rows, columns)]
    terrain_display = display_z(terrain, anchor, config.vertical_exaggeration)
    figure.add_trace(
        go.Surface(
            x=x,
            y=y,
            z=terrain_display,
            surfacecolor=terrain,
            colorscale="Earth",
            opacity=config.terrain_opacity,
            showscale=True,
            colorbar={"title": "Terrain<br>m AHD", "len": 0.55},
            name="AHD terrain",
            showlegend=True,
            visible=config.show_terrain,
            hovertemplate="Terrain: %{surfacecolor:.2f} m AHD<extra></extra>",
        )
    )
    roles.append("terrain")

    shown_building_groups: set[str] = set()
    selected_buildings = set(config.selected_building_ids)
    for row in data.buildings.itertuples():
        building_id = str(row.building_id)
        if building_id not in data.building_meshes:
            continue
        if selected_buildings and building_id not in selected_buildings:
            continue
        group = str(row.output_lod)
        trace = _plotly_mesh_trace(
            data.building_meshes[building_id],
            row,
            anchor,
            config,
            group not in shown_building_groups,
        )
        trace.visible = config.show_buildings
        figure.add_trace(trace)
        roles.append("buildings")
        shown_building_groups.add(group)

    selected_assets = set(config.selected_asset_ids)
    shown_networks: set[str] = set()
    utility_local_points: list[np.ndarray] = []
    line_rows = data.utilities[
        data.utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ]
    for row in line_rows.itertuples():
        if row.network_type not in config.utility_types:
            continue
        if selected_assets and row.asset_id not in selected_assets:
            continue
        for part_index, points in enumerate(
            drape_utility_geometry(
                row.geometry,
                data.terrain,
                data.terrain_transform,
                data.local_origin,
                config.utility_drape_offset_m,
            )
        ):
            points = points.copy()
            points[:, 2] = display_z(points[:, 2], anchor, config.vertical_exaggeration)
            utility_local_points.append(points)
            name = _utility_legend_label(row, config)
            hover = (
                f"<b>{row.asset_type}</b><br>ID: {row.source_feature_id}"
                f"<br>Owner: {row.owner}<br>Size: {row.diameter_or_size}"
                f"<br>Horizontal confidence: {row.confidence_xy}"
                "<br><b>Depth unknown; display drape only</b><extra></extra>"
            )
            figure.add_trace(
                go.Scatter3d(
                    x=points[:, 0],
                    y=points[:, 1],
                    z=points[:, 2],
                    mode="lines+markers",
                    line={
                        "color": _utility_colour(row, config),
                        "width": 8,
                        "dash": "dash",
                    },
                    marker={"size": 2, "color": _utility_colour(row, config)},
                    name=name,
                    legendgroup=f"utility:{row.network_type}",
                    showlegend=row.network_type not in shown_networks,
                    visible=config.show_utilities,
                    hovertemplate=hover,
                )
            )
            roles.append("utilities")
            shown_networks.add(str(row.network_type))

    node_rows = data.utilities[data.utilities.geometry.geom_type == "Point"]
    for row in node_rows.itertuples():
        if row.network_type not in config.utility_types:
            continue
        if selected_assets and row.asset_id not in selected_assets:
            continue
        terrain_z = terrain_at_xy(
            data.terrain,
            data.terrain_transform,
            np.asarray([row.geometry.x]),
            np.asarray([row.geometry.y]),
        )[0]
        if not math.isfinite(terrain_z):
            continue
        local = np.asarray(
            [
                row.geometry.x - data.local_origin[0],
                row.geometry.y - data.local_origin[1],
                display_z(
                    terrain_z + config.utility_drape_offset_m,
                    anchor,
                    config.vertical_exaggeration,
                ),
            ]
        )
        utility_local_points.append(local.reshape(1, 3))
        figure.add_trace(
            go.Scatter3d(
                x=[local[0]],
                y=[local[1]],
                z=[local[2]],
                mode="markers",
                marker={
                    "size": 6,
                    "color": _utility_colour(row, config),
                    "line": {"color": "white", "width": 1},
                },
                name=f"{row.network_type.title()} node — depth unknown",
                legendgroup=f"utility:{row.network_type}",
                showlegend=False,
                visible=config.show_nodes,
                hovertemplate=(
                    f"<b>{row.asset_type}</b><br>ID: {row.source_feature_id}"
                    f"<br>Owner: {row.owner}<br><b>Depth unknown; display drape only</b>"
                    "<extra></extra>"
                ),
            )
        )
        roles.append("utility_nodes")

    points = data.point_cloud_xyz.copy()
    points[:, 2] = display_z(points[:, 2], anchor, config.vertical_exaggeration)
    figure.add_trace(
        go.Scatter3d(
            x=points[:, 0],
            y=points[:, 1],
            z=points[:, 2],
            mode="markers",
            marker={
                "size": 1.2,
                "color": data.point_cloud_classification,
                "colorscale": "Viridis",
                "opacity": 0.55,
            },
            name="LiDAR preview",
            visible=True if config.show_point_cloud else "legendonly",
            hovertemplate="Class: %{marker.color}<extra></extra>",
        )
    )
    roles.append("point_cloud")

    full_range = [-255.0, 255.0]
    z_values = display_z(
        data.terrain[np.isfinite(data.terrain)], anchor, config.vertical_exaggeration
    )
    z_min = float(np.min(z_values)) - 2.0
    building_z_max = display_z(
        [max(float(mesh.bounds[1, 2]) for mesh in data.building_meshes.values())],
        anchor,
        config.vertical_exaggeration,
    )[0]
    z_max = (
        max(
            float(np.max(z_values)),
            float(building_z_max),
        )
        + 5.0
    )
    utility_bounds = np.vstack(utility_local_points) if utility_local_points else np.empty((0, 3))
    if len(utility_bounds):
        utility_x = [float(utility_bounds[:, 0].min() - 12), float(utility_bounds[:, 0].max() + 12)]
        utility_y = [float(utility_bounds[:, 1].min() - 18), float(utility_bounds[:, 1].max() + 18)]
    else:
        utility_x = full_range
        utility_y = full_range

    terrain_indices = [index for index, role in enumerate(roles) if role == "terrain"]
    figure.update_layout(
        title=(
            "UQ St Lucia pilot — integrated terrain, mixed-LoD buildings and public utilities"
            "<br><sup>Utility Z is a display-only terrain drape; physical depth is unknown</sup>"
        ),
        template="plotly_white",
        height=850,
        margin={"l": 0, "r": 0, "t": 85, "b": 0},
        legend={"groupclick": "togglegroup", "itemsizing": "constant"},
        scene={
            "xaxis": {"title": "Local easting (m)", "range": full_range},
            "yaxis": {"title": "Local northing (m)", "range": full_range},
            "zaxis": {"title": "Display elevation (m)", "range": [z_min, z_max]},
            "aspectmode": "manual",
            "aspectratio": {"x": 1.0, "y": 1.0, "z": 0.32},
            "camera": _plotly_camera("Northeast"),
        },
        updatemenus=[
            {
                "type": "dropdown",
                "direction": "down",
                "x": 0.01,
                "y": 0.99,
                "buttons": [
                    {
                        "label": label,
                        "method": "relayout",
                        "args": [{"scene.camera": _plotly_camera(label)}],
                    }
                    for label in ("Northeast", "Southwest", "Plan")
                ],
            },
            {
                "type": "dropdown",
                "direction": "down",
                "x": 0.18,
                "y": 0.99,
                "buttons": [
                    {
                        "label": "Full pilot extent",
                        "method": "relayout",
                        "args": [
                            {
                                "scene.xaxis.range": full_range,
                                "scene.yaxis.range": full_range,
                            }
                        ],
                    },
                    {
                        "label": "Utility detail extent",
                        "method": "relayout",
                        "args": [
                            {
                                "scene.xaxis.range": utility_x,
                                "scene.yaxis.range": utility_y,
                            }
                        ],
                    },
                ],
            },
            {
                "type": "dropdown",
                "direction": "down",
                "x": 0.39,
                "y": 0.99,
                "buttons": [
                    {
                        "label": "Terrain 68%",
                        "method": "restyle",
                        "args": [{"opacity": 0.68, "visible": True}, terrain_indices],
                    },
                    {
                        "label": "Terrain 25%",
                        "method": "restyle",
                        "args": [{"opacity": 0.25, "visible": True}, terrain_indices],
                    },
                    {
                        "label": "Terrain hidden",
                        "method": "restyle",
                        "args": [{"visible": False}, terrain_indices],
                    },
                ],
            },
        ],
        meta={
            "trace_roles": roles,
            "authoritative_horizontal_crs": f"EPSG:{TARGET_EPSG}",
            "utility_display_method": (
                "Clipped horizontal alignment sampled onto Phase 5 AHD terrain plus a "
                f"{config.utility_drape_offset_m:g} m visibility offset; not asset elevation."
            ),
            "utility_depth_status": "unknown",
        },
    )
    return figure


def export_interactive_html(
    data: IntegratedSceneData,
    output_path: str | Path,
    config: SceneDisplayConfig | None = None,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure = build_plotly_figure(data, config)
    figure.write_html(
        destination,
        include_plotlyjs=True,
        full_html=True,
        auto_open=False,
        config={"displaylogo": False, "scrollZoom": True, "responsive": True},
    )
    return destination


def _annotate_png(path: Path, title: str, subtitle: str) -> None:
    font_path = font_manager.findfont("DejaVu Sans")
    title_font = ImageFont.truetype(font_path, 22)
    subtitle_font = ImageFont.truetype(font_path, 16)
    legend_font = ImageFont.truetype(font_path, 15)
    with Image.open(path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (14, 10, min(image.width - 14, 900), 75),
        radius=5,
        fill="#FFFFFF",
        outline="#94A3B8",
    )
    draw.text((25, 17), title, font=title_font, fill="#17202A")
    draw.text((25, 47), subtitle, font=subtitle_font, fill="#8B1E1E")
    rows = [
        ("LoD1 fallback", BUILDING_COLOURS["LoD1"]),
        ("Reliable LoD2", BUILDING_COLOURS["reliable LoD2"]),
        ("Approximate LoD2", BUILDING_COLOURS["approximate LoD2"]),
        ("Stormwater — depth unknown", NETWORK_COLOURS["stormwater"]),
        ("Water — depth unknown", NETWORK_COLOURS["water"]),
    ]
    right = image.width - 20
    left = right - 285
    top = 85
    bottom = top + 15 + 27 * len(rows)
    draw.rounded_rectangle((left, top, right, bottom), radius=5, fill="#FFFFFF", outline="#94A3B8")
    for index, (label, colour) in enumerate(rows):
        y = top + 10 + index * 27
        draw.rectangle(
            (left + 12, y + 2, left + 28, y + 18),
            fill=ImageColor.getrgb(colour),
            outline="#334155",
        )
        draw.text((left + 38, y), label, font=legend_font, fill="#1F2937")
    image.save(path)


def render_integrated_png(
    data: IntegratedSceneData,
    output_path: str | Path,
    *,
    camera: str,
    config: SceneDisplayConfig | None = None,
    cutaway: bool = False,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plotter = build_integrated_plotter(
        data,
        config,
        camera=camera,
        cutaway=cutaway,
        off_screen=True,
        notebook=False,
        show_screen_annotations=False,
    )
    try:
        plotter.show(screenshot=str(destination), auto_close=False)
    finally:
        plotter.close()
        pv.close_all()
    _annotate_png(
        destination,
        "UQ pilot integrated 3D GIS scene",
        "Public utility alignment only — display drape — physical depth unknown",
    )
    return destination
