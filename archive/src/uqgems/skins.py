"""Presentation-only material and texture helpers for the UQ pilot scene."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyvista as pv
import rasterio
import trimesh
from affine import Affine
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont
from trimesh.visual.material import PBRMaterial
from trimesh.visual.texture import TextureVisuals

from uqgems.integrated_scene import (
    CAMERAS,
    NETWORK_COLOURS,
    IntegratedSceneData,
    SceneDisplayConfig,
    apply_camera,
    dashed_segments,
    drape_utility_geometry,
    load_integrated_scene_data,
    terrain_at_xy,
)
from uqgems.normalization import LOCAL_ORIGIN, TARGET_EPSG


@dataclass(frozen=True)
class SkinConfig:
    """Parameters for presentation skins; none alter authoritative geometry."""

    terrain_step: int = 2
    roof_normal_z_minimum: float = 0.15
    base_normal_z_maximum: float = -0.50
    facade_repeat_width_m: float = 6.0
    facade_repeat_height_m: float = 3.2
    orthophoto_jpeg_quality: int = 90
    terrain_opacity: float = 1.0
    building_opacity: float = 1.0
    utility_drape_offset_m: float = 0.75
    symbolic_utility_radius_m: float = 0.65

    def validate(self) -> None:
        if self.terrain_step < 1:
            raise ValueError("terrain_step must be at least one")
        if not 0.0 < self.roof_normal_z_minimum < 1.0:
            raise ValueError("roof_normal_z_minimum must be between zero and one")
        if not -1.0 < self.base_normal_z_maximum < 0.0:
            raise ValueError("base_normal_z_maximum must be between minus one and zero")
        if self.base_normal_z_maximum >= self.roof_normal_z_minimum:
            raise ValueError("base and roof normal thresholds overlap")
        if self.facade_repeat_width_m <= 0 or self.facade_repeat_height_m <= 0:
            raise ValueError("facade repeat dimensions must be positive")
        if not 1 <= self.orthophoto_jpeg_quality <= 95:
            raise ValueError("orthophoto_jpeg_quality must be between 1 and 95")
        if not 0.0 <= self.terrain_opacity <= 1.0:
            raise ValueError("terrain_opacity must be between zero and one")
        if not 0.0 <= self.building_opacity <= 1.0:
            raise ValueError("building_opacity must be between zero and one")
        if self.utility_drape_offset_m < 0 or self.symbolic_utility_radius_m <= 0:
            raise ValueError("utility display dimensions are invalid")


@dataclass
class SkinnedSceneData:
    """Integrated model inputs plus the registered orthophoto."""

    integrated: IntegratedSceneData
    orthophoto_rgb: np.ndarray
    orthophoto_transform: Affine
    orthophoto_bounds: tuple[float, float, float, float]
    orthophoto_crs_epsg: int


@dataclass
class SkinnedComponents:
    """Meshes and evidence produced before GLB and viewer export."""

    meshes: dict[str, trimesh.Trimesh]
    building_surface_audit: pd.DataFrame
    terrain_uv: np.ndarray


def load_skinned_scene_data(project_root: str | Path) -> SkinnedSceneData:
    """Load validated Phase 9 inputs and the Phase 4 RGB orthophoto."""
    root = Path(project_root).resolve()
    image_path = (
        root / "data/interim/normalised/context/latest_public_orthophoto_epsg7856.tif"
    )
    if not image_path.is_file():
        raise FileNotFoundError(f"Orthophoto is missing: {image_path}")
    integrated = load_integrated_scene_data(root, maximum_point_cloud_points=30_000)
    with rasterio.open(image_path) as source:
        if source.count < 3:
            raise ValueError("The presentation skin requires a three-band orthophoto")
        rgb = np.moveaxis(source.read((1, 2, 3)), 0, -1).astype(np.uint8)
        epsg = source.crs.to_epsg() if source.crs is not None else None
        if epsg is None:
            raise ValueError("The orthophoto CRS must have an EPSG identifier")
        bounds = tuple(float(value) for value in source.bounds)
        transform = source.transform
    return SkinnedSceneData(
        integrated=integrated,
        orthophoto_rgb=rgb,
        orthophoto_transform=transform,
        orthophoto_bounds=bounds,
        orthophoto_crs_epsg=int(epsg),
    )


def orthophoto_uv(
    authoritative_x: Any,
    authoritative_y: Any,
    bounds: tuple[float, float, float, float],
) -> np.ndarray:
    """Map authoritative XY to north-up texture coordinates."""
    left, bottom, right, top = bounds
    x = np.asarray(authoritative_x, dtype=float)
    y = np.asarray(authoritative_y, dtype=float)
    if right <= left or top <= bottom:
        raise ValueError("Orthophoto bounds must have positive width and height")
    u = (x - left) / (right - left)
    v = (y - bottom) / (top - bottom)
    return np.column_stack([u, v])


def classify_surface_faces(
    face_normals: Any,
    roof_normal_z_minimum: float = 0.15,
    base_normal_z_maximum: float = -0.50,
) -> np.ndarray:
    """Classify consistently wound triangular faces as roof, facade or base."""
    normals = np.asarray(face_normals, dtype=float)
    if normals.ndim != 2 or normals.shape[1] != 3:
        raise ValueError("face_normals must have shape (n, 3)")
    labels = np.full(len(normals), "facade", dtype="U7")
    labels[normals[:, 2] >= roof_normal_z_minimum] = "roof"
    labels[normals[:, 2] <= base_normal_z_maximum] = "base"
    return labels


def procedural_facade_texture(size: int = 512) -> Image.Image:
    """Create a deterministic, explicitly schematic facade material tile."""
    if size < 64:
        raise ValueError("Facade texture size must be at least 64 pixels")
    image = Image.new("RGB", (size, size), "#C7B38D")
    draw = ImageDraw.Draw(image)
    margin = max(8, size // 20)
    mullion = max(4, size // 64)
    band = max(6, size // 42)
    draw.rectangle((0, 0, size - 1, band), fill="#AA9572")
    draw.rectangle((0, size - band - 1, size - 1, size - 1), fill="#AA9572")
    window_top = margin + band
    window_bottom = size - margin - band
    window_width = (size - 3 * margin) // 2
    for index in range(2):
        left = margin + index * (window_width + margin)
        right = left + window_width
        draw.rectangle(
            (left, window_top, right, window_bottom),
            fill="#526B78",
            outline="#E2D2B2",
            width=mullion,
        )
        middle = (left + right) // 2
        draw.rectangle(
            (middle - mullion // 2, window_top, middle + mullion // 2, window_bottom),
            fill="#AFC1C7",
        )
    draw.rectangle(
        (0, size // 2 - band // 2, size - 1, size // 2 + band // 2),
        fill="#B7A17D",
    )
    return image


def save_texture_assets(
    orthophoto_rgb: np.ndarray,
    orthophoto_path: str | Path,
    facade_path: str | Path,
    *,
    jpeg_quality: int = 90,
) -> tuple[Path, Path]:
    """Write web/GLB-ready copies of the factual and procedural textures."""
    orthophoto_destination = Path(orthophoto_path)
    facade_destination = Path(facade_path)
    orthophoto_destination.parent.mkdir(parents=True, exist_ok=True)
    facade_destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(orthophoto_rgb, dtype=np.uint8), mode="RGB").save(
        orthophoto_destination,
        format="JPEG",
        quality=jpeg_quality,
        optimize=True,
        progressive=True,
    )
    procedural_facade_texture().save(facade_destination, format="PNG", optimize=True)
    return orthophoto_destination, facade_destination


def _sample_indices(length: int, step: int) -> np.ndarray:
    values = np.arange(0, length, step, dtype=np.int64)
    if values[-1] != length - 1:
        values = np.append(values, length - 1)
    return values


def _terrain_mesh(
    data: SkinnedSceneData,
    config: SkinConfig,
    orthophoto_image: Image.Image,
) -> tuple[trimesh.Trimesh, np.ndarray]:
    integrated = data.integrated
    rows = _sample_indices(integrated.terrain.shape[0], config.terrain_step)
    columns = _sample_indices(integrated.terrain.shape[1], config.terrain_step)
    x = integrated.terrain_transform.c + (columns + 0.5) * integrated.terrain_transform.a
    y = integrated.terrain_transform.f + (rows + 0.5) * integrated.terrain_transform.e
    xx, yy = np.meshgrid(x, y)
    zz = integrated.terrain[np.ix_(rows, columns)]
    vertices = np.column_stack(
        [
            xx.ravel() - integrated.local_origin[0],
            yy.ravel() - integrated.local_origin[1],
            zz.ravel(),
        ]
    )
    column_count = len(columns)
    grid = np.arange(len(rows) * column_count, dtype=np.int64).reshape(len(rows), column_count)
    northwest = grid[:-1, :-1].ravel()
    southwest = grid[1:, :-1].ravel()
    northeast = grid[:-1, 1:].ravel()
    southeast = grid[1:, 1:].ravel()
    faces = np.vstack(
        [
            np.column_stack([northwest, southwest, northeast]),
            np.column_stack([northeast, southwest, southeast]),
        ]
    )
    uv = orthophoto_uv(xx.ravel(), yy.ravel(), data.orthophoto_bounds)
    visual = TextureVisuals(
        uv=uv,
        material=PBRMaterial(
            name="2022 Queensland orthophoto - terrain",
            baseColorTexture=orthophoto_image,
            metallicFactor=0.0,
            roughnessFactor=1.0,
            doubleSided=True,
        ),
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, visual=visual, process=False)
    return mesh, uv


def _textured_triangle_mesh(
    triangles: list[np.ndarray],
    uv_triangles: list[np.ndarray],
    *,
    image: Image.Image,
    material_name: str,
) -> trimesh.Trimesh:
    if not triangles:
        raise ValueError(f"No triangles were supplied for {material_name}")
    vertices = np.concatenate(triangles, axis=0)
    uv = np.concatenate(uv_triangles, axis=0)
    faces = np.arange(len(vertices), dtype=np.int64).reshape(-1, 3)
    visual = TextureVisuals(
        uv=uv,
        material=PBRMaterial(
            name=material_name,
            baseColorTexture=image,
            metallicFactor=0.0,
            roughnessFactor=0.92,
            doubleSided=True,
        ),
    )
    return trimesh.Trimesh(vertices=vertices, faces=faces, visual=visual, process=False)


def _coloured_triangle_mesh(
    triangles: list[np.ndarray], color: tuple[int, int, int, int]
) -> trimesh.Trimesh:
    if not triangles:
        raise ValueError("No triangles were supplied for the building bases")
    vertices = np.concatenate(triangles, axis=0)
    faces = np.arange(len(vertices), dtype=np.int64).reshape(-1, 3)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual.face_colors = np.tile(np.asarray(color, dtype=np.uint8), (len(faces), 1))
    return mesh


def _facade_uv(triangle: np.ndarray, normal: np.ndarray, config: SkinConfig) -> np.ndarray:
    tangent = np.asarray([-normal[1], normal[0]], dtype=float)
    norm = float(np.linalg.norm(tangent))
    if norm < 1e-9:
        tangent = np.asarray([1.0, 0.0])
    else:
        tangent /= norm
    u = triangle[:, :2] @ tangent / config.facade_repeat_width_m
    v = triangle[:, 2] / config.facade_repeat_height_m
    return np.column_stack([u, v])


def _building_surface_meshes(
    data: SkinnedSceneData,
    config: SkinConfig,
    orthophoto_image: Image.Image,
    facade_image: Image.Image,
) -> tuple[dict[str, trimesh.Trimesh], pd.DataFrame]:
    roof_triangles: list[np.ndarray] = []
    roof_uv: list[np.ndarray] = []
    facade_triangles: list[np.ndarray] = []
    facade_uv: list[np.ndarray] = []
    base_triangles: list[np.ndarray] = []
    audit_rows: list[dict[str, Any]] = []
    attributes = data.integrated.buildings.set_index("building_id")

    for building_id, mesh in sorted(data.integrated.building_meshes.items()):
        triangles = np.asarray(mesh.triangles, dtype=float)
        normals = np.asarray(mesh.face_normals, dtype=float)
        labels = classify_surface_faces(
            normals,
            config.roof_normal_z_minimum,
            config.base_normal_z_maximum,
        )
        roof_for_building: list[np.ndarray] = []
        for triangle, normal, label in zip(triangles, normals, labels, strict=True):
            if label == "roof":
                authoritative_xy = triangle[:, :2] + np.asarray(LOCAL_ORIGIN[:2])
                mapped_uv = orthophoto_uv(
                    authoritative_xy[:, 0], authoritative_xy[:, 1], data.orthophoto_bounds
                )
                roof_triangles.append(triangle)
                roof_uv.append(mapped_uv)
                roof_for_building.append(mapped_uv)
            elif label == "facade":
                facade_triangles.append(triangle)
                facade_uv.append(_facade_uv(triangle, normal, config))
            else:
                base_triangles.append(triangle)
        row = attributes.loc[str(building_id)]
        building_roof_uv = (
            np.concatenate(roof_for_building, axis=0)
            if roof_for_building
            else np.empty((0, 2), dtype=float)
        )
        audit_rows.append(
            {
                "building_id": str(building_id),
                "building_name": row.get("building_name", ""),
                "output_lod": row.get("output_lod", ""),
                "lod2_status": row.get("lod2_status", ""),
                "confidence": row.get("confidence", ""),
                "source_faces": int(len(labels)),
                "roof_faces": int(np.count_nonzero(labels == "roof")),
                "facade_faces": int(np.count_nonzero(labels == "facade")),
                "base_faces": int(np.count_nonzero(labels == "base")),
                "roof_uv_min": (
                    float(building_roof_uv.min()) if len(building_roof_uv) else math.nan
                ),
                "roof_uv_max": (
                    float(building_roof_uv.max()) if len(building_roof_uv) else math.nan
                ),
            }
        )

    meshes = {
        "building_roofs_orthophoto": _textured_triangle_mesh(
            roof_triangles,
            roof_uv,
            image=orthophoto_image,
            material_name="2022 Queensland orthophoto - roofs",
        ),
        "building_facades_schematic": _textured_triangle_mesh(
            facade_triangles,
            facade_uv,
            image=facade_image,
            material_name="Schematic procedural facade - not observed",
        ),
        "building_bases_schematic": _coloured_triangle_mesh(
            base_triangles, (92, 88, 81, 255)
        ),
    }
    return meshes, pd.DataFrame(audit_rows)


def _utility_meshes(data: SkinnedSceneData, config: SkinConfig) -> dict[str, trimesh.Trimesh]:
    integrated = data.integrated
    display_config = SceneDisplayConfig(
        utility_drape_offset_m=config.utility_drape_offset_m,
        symbolic_utility_radius_m=config.symbolic_utility_radius_m,
    )
    meshes: dict[str, trimesh.Trimesh] = {}
    lines = integrated.utilities[
        integrated.utilities.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ]
    for row in lines.itertuples():
        cylinders: list[trimesh.Trimesh] = []
        for points in drape_utility_geometry(
            row.geometry,
            integrated.terrain,
            integrated.terrain_transform,
            integrated.local_origin,
            config.utility_drape_offset_m,
        ):
            for dash in dashed_segments(
                points,
                display_config.utility_dash_length_m,
                display_config.utility_gap_length_m,
            ):
                for start, end in zip(dash[:-1], dash[1:], strict=True):
                    if np.linalg.norm(end - start) > 1e-8:
                        cylinders.append(
                            trimesh.creation.cylinder(
                                radius=config.symbolic_utility_radius_m,
                                segment=np.vstack([start, end]),
                                sections=8,
                            )
                        )
        if not cylinders:
            continue
        mesh = trimesh.util.concatenate(cylinders)
        colour = NETWORK_COLOURS.get(str(row.network_type), "#6C757D")
        rgb = tuple(int(colour[index : index + 2], 16) for index in (1, 3, 5))
        mesh.visual.face_colors = np.tile(
            np.asarray([*rgb, 255], dtype=np.uint8), (len(mesh.faces), 1)
        )
        meshes[f"DISPLAY_ONLY_DEPTH_UNKNOWN_{row.network_type}_{row.asset_id}"] = mesh

    nodes = integrated.utilities[integrated.utilities.geometry.geom_type == "Point"]
    for row in nodes.itertuples():
        z = terrain_at_xy(
            integrated.terrain,
            integrated.terrain_transform,
            np.asarray([row.geometry.x]),
            np.asarray([row.geometry.y]),
        )[0]
        if not np.isfinite(z):
            continue
        centre = np.asarray(
            [
                row.geometry.x - integrated.local_origin[0],
                row.geometry.y - integrated.local_origin[1],
                z + config.utility_drape_offset_m,
            ]
        )
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=1.8)
        mesh.apply_translation(centre)
        colour = NETWORK_COLOURS.get(str(row.network_type), "#6C757D")
        rgb = tuple(int(colour[index : index + 2], 16) for index in (1, 3, 5))
        mesh.visual.face_colors = np.tile(
            np.asarray([*rgb, 255], dtype=np.uint8), (len(mesh.faces), 1)
        )
        meshes[f"DISPLAY_ONLY_DEPTH_UNKNOWN_{row.network_type}_{row.asset_id}"] = mesh
    return meshes


def build_skinned_components(
    data: SkinnedSceneData,
    config: SkinConfig,
    orthophoto_image: Image.Image,
    facade_image: Image.Image,
) -> SkinnedComponents:
    """Create factual roof/terrain textures and explicitly schematic surfaces."""
    config.validate()
    terrain, terrain_uv = _terrain_mesh(data, config, orthophoto_image)
    building_meshes, audit = _building_surface_meshes(
        data, config, orthophoto_image, facade_image
    )
    meshes = {"terrain_orthophoto": terrain, **building_meshes}
    meshes.update(_utility_meshes(data, config))
    return SkinnedComponents(
        meshes=meshes,
        building_surface_audit=audit,
        terrain_uv=terrain_uv,
    )


def export_textured_glb(components: SkinnedComponents, output_path: str | Path) -> Path:
    """Export the presentation scene with embedded image textures."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    for name, mesh in components.meshes.items():
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.metadata.update(
        {
            "horizontal_crs": f"EPSG:{TARGET_EPSG}",
            "local_origin": list(LOCAL_ORIGIN),
            "orthophoto_capture_date": "2022-07-24",
            "lidar_capture_year": "2019",
            "facades": "schematic procedural material; not observed facade imagery",
            "utilities": "display-only terrain drape; physical depth unknown",
        }
    )
    payload = scene.export(file_type="glb")
    destination.write_bytes(payload)
    return destination


def _as_pyvista(mesh: trimesh.Trimesh) -> pv.PolyData:
    faces = np.column_stack(
        [np.full(len(mesh.faces), 3, dtype=np.int64), np.asarray(mesh.faces, dtype=np.int64)]
    ).ravel()
    output = pv.PolyData(np.asarray(mesh.vertices), faces)
    uv = getattr(mesh.visual, "uv", None)
    if uv is not None:
        output.active_texture_coordinates = np.asarray(uv, dtype=float)
    return output


def build_skinned_plotter(
    components: SkinnedComponents,
    orthophoto_texture_path: str | Path,
    facade_texture_path: str | Path,
    *,
    camera: str = "northeast",
    off_screen: bool = False,
    notebook: bool | None = None,
    show_annotations: bool = True,
    window_size: tuple[int, int] = (1500, 950),
) -> pv.Plotter:
    """Build a textured PyVista presentation while retaining utility warnings."""
    plotter = pv.Plotter(off_screen=off_screen, notebook=notebook, window_size=window_size)
    plotter.set_background("#DDEAF2", top="#9FC1D6")
    orthophoto = pv.read_texture(orthophoto_texture_path)
    orthophoto.interpolate = True
    facade = pv.read_texture(facade_texture_path)
    facade.interpolate = True
    facade.repeat = True

    plotter.add_mesh(
        _as_pyvista(components.meshes["terrain_orthophoto"]),
        texture=orthophoto,
        smooth_shading=False,
        name="Terrain - 2022 orthophoto",
    )
    plotter.add_mesh(
        _as_pyvista(components.meshes["building_roofs_orthophoto"]),
        texture=orthophoto,
        smooth_shading=False,
        name="Roofs - 2022 orthophoto",
    )
    plotter.add_mesh(
        _as_pyvista(components.meshes["building_facades_schematic"]),
        texture=facade,
        smooth_shading=False,
        name="Facades - schematic",
    )
    plotter.add_mesh(
        _as_pyvista(components.meshes["building_bases_schematic"]),
        color="#5C5851",
        name="Building bases - schematic",
    )
    for name, mesh in components.meshes.items():
        if not name.startswith("DISPLAY_ONLY_DEPTH_UNKNOWN_"):
            continue
        network_type = name.split("_", 5)[4]
        plotter.add_mesh(
            _as_pyvista(mesh),
            color=NETWORK_COLOURS.get(network_type, "#6C757D"),
            smooth_shading=True,
            name=name,
        )

    if show_annotations:
        plotter.add_text(
            "PRESENTATION SKIN | QUEENSLAND ORTHOPHOTO 2022 (CC BY 4.0) | LIDAR 2019",
            position="upper_left",
            font_size=10,
            color="#243447",
        )
        plotter.add_text(
            "FACADES SCHEMATIC | PUBLIC UTILITIES: DEPTH UNKNOWN",
            position="lower_left",
            font_size=10,
            color="#8B1E1E",
        )
    plotter.add_axes(line_width=2)
    apply_camera(plotter, camera)
    return plotter


def render_skinned_png(
    components: SkinnedComponents,
    orthophoto_texture_path: str | Path,
    facade_texture_path: str | Path,
    output_path: str | Path,
    *,
    camera: str = "northeast",
) -> Path:
    """Render a fixed presentation view for visual validation."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plotter = build_skinned_plotter(
        components,
        orthophoto_texture_path,
        facade_texture_path,
        camera=camera,
        off_screen=True,
        notebook=False,
        show_annotations=False,
    )
    try:
        plotter.show(screenshot=str(destination), auto_close=False)
    finally:
        plotter.close()
        pv.close_all()
    _annotate_skinned_png(destination)
    return destination


def _annotate_skinned_png(path: Path) -> None:
    """Add stable disclosure banners without relying on VTK text placement."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    font_path = font_manager.findfont("DejaVu Sans")
    title_font = ImageFont.truetype(font_path, 21)
    warning_font = ImageFont.truetype(font_path, 19)
    draw.rectangle((0, 0, image.width, 42), fill="#F8FAFC")
    draw.text(
        (12, 8),
        "PRESENTATION SKIN | QUEENSLAND ORTHOPHOTO 2022 (CC BY 4.0) | LIDAR 2019",
        font=title_font,
        fill="#243447",
    )
    draw.rectangle((0, image.height - 39, image.width, image.height), fill="#F8FAFC")
    draw.text(
        (12, image.height - 33),
        "FACADES SCHEMATIC | PUBLIC UTILITIES: PHYSICAL DEPTH UNKNOWN",
        font=warning_font,
        fill="#8B1E1E",
    )
    image.save(path)


def export_skinned_html(
    components: SkinnedComponents,
    orthophoto_texture_path: str | Path,
    facade_texture_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Export a self-contained vtk.js presentation scene through PyVista."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plotter = build_skinned_plotter(
        components,
        orthophoto_texture_path,
        facade_texture_path,
        off_screen=True,
        notebook=False,
        show_annotations=True,
    )
    try:
        plotter.render()
        plotter.export_html(destination)
    finally:
        plotter.close()
        pv.close_all()
    return destination


def camera_names() -> tuple[str, ...]:
    """Expose presentation cameras without duplicating Phase 9 definitions."""
    return tuple(name for name in ("plan", "northeast", "southwest") if name in CAMERAS)
