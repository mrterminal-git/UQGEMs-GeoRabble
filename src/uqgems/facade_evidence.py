"""Conservative airborne-LiDAR evidence audit for building facades."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import laspy
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Polygon

from uqgems.normalization import TARGET_EPSG

EVIDENCE_COLOURS = {
    "sufficient": "#238B45",
    "marginal": "#F2B134",
    "insufficient": "#C84C4C",
}


@dataclass(frozen=True)
class FacadeAuditConfig:
    """Fixed evidence thresholds for near-footprint airborne LiDAR returns."""

    wall_search_distance_m: float = 0.75
    minimum_segment_length_m: float = 1.0
    bottom_exclusion_m: float = 0.75
    top_exclusion_m: float = 1.0
    coverage_bin_m: float = 1.0
    evidence_classes: tuple[int, ...] = (1, 6)
    vegetation_classes: tuple[int, ...] = (3, 4, 5)
    chunk_size: int = 500_000
    detailed_candidate_count: int = 5
    strong_minimum_points: int = 30
    strong_minimum_density_m2: float = 0.50
    strong_minimum_vertical_coverage: float = 0.50
    strong_minimum_horizontal_coverage: float = 0.35
    strong_minimum_grid_coverage: float = 0.12
    strong_minimum_vertical_span: float = 0.55
    strong_maximum_p95_distance_m: float = 0.55
    marginal_minimum_points: int = 10
    marginal_minimum_density_m2: float = 0.15
    marginal_minimum_vertical_coverage: float = 0.25
    marginal_minimum_horizontal_coverage: float = 0.20
    marginal_minimum_vertical_span: float = 0.30
    marginal_maximum_p95_distance_m: float = 0.75

    def validate(self) -> None:
        if self.wall_search_distance_m <= 0:
            raise ValueError("wall_search_distance_m must be positive")
        if self.minimum_segment_length_m <= 0:
            raise ValueError("minimum_segment_length_m must be positive")
        if self.bottom_exclusion_m < 0 or self.top_exclusion_m < 0:
            raise ValueError("vertical exclusions cannot be negative")
        if self.coverage_bin_m <= 0 or self.chunk_size < 1:
            raise ValueError("coverage_bin_m and chunk_size must be positive")
        if self.detailed_candidate_count < 1:
            raise ValueError("detailed_candidate_count must be positive")
        if set(self.evidence_classes) & set(self.vegetation_classes):
            raise ValueError("evidence and vegetation classes cannot overlap")


def _polygon_parts(geometry: Polygon | MultiPolygon) -> Iterator[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _display_name(value: Any) -> str:
    if value is None or pd.isna(value) or not str(value).strip():
        return "unnamed"
    return str(value)


def build_facade_segments(
    buildings: gpd.GeoDataFrame,
    config: FacadeAuditConfig,
) -> tuple[pd.DataFrame, list[LineString]]:
    """Convert modelled footprint exteriors to auditable wall segments."""
    config.validate()
    records: list[dict[str, Any]] = []
    lines: list[LineString] = []
    modelled = buildings.loc[buildings["model_status"] == "modelled"].copy()
    for row in modelled.itertuples():
        cumulative = 0.0
        sequence = 0
        low_z = float(row.base_z_ahd) + config.bottom_exclusion_m
        roof_p05 = float(row.roof_z_p05_ahd)
        high_z = roof_p05 - config.top_exclusion_m
        for part_index, polygon in enumerate(_polygon_parts(row.geometry), start=1):
            coordinates = np.asarray(polygon.exterior.coords, dtype=float)
            for start, end in zip(coordinates[:-1], coordinates[1:], strict=True):
                length = float(np.linalg.norm(end - start))
                if length < config.minimum_segment_length_m:
                    cumulative += length
                    continue
                sequence += 1
                segment = LineString([start, end])
                dx, dy = end - start
                azimuth = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
                wall_height = max(0.0, high_z - low_z)
                records.append(
                    {
                        "segment_index": len(records),
                        "segment_id": f"{row.building_id}-F{sequence:03d}",
                        "building_id": str(row.building_id),
                        "building_name": _display_name(row.building_name),
                        "part_index": part_index,
                        "segment_sequence": sequence,
                        "start_easting": float(start[0]),
                        "start_northing": float(start[1]),
                        "end_easting": float(end[0]),
                        "end_northing": float(end[1]),
                        "length_m": length,
                        "azimuth_deg": azimuth,
                        "cumulative_start_m": cumulative,
                        "audit_base_z_ahd": low_z,
                        "audit_top_z_ahd": high_z,
                        "audit_height_m": wall_height,
                        "boundary_clipped": bool(row.boundary_clipped),
                    }
                )
                lines.append(segment)
                cumulative += length
    segments = pd.DataFrame(records)
    if segments.empty:
        raise ValueError("No eligible facade segments were found")
    if not np.array_equal(segments["segment_index"], np.arange(len(segments))):
        raise RuntimeError("Facade segment indices are not contiguous")
    return segments, lines


def _scan_angle_degrees(raw_scan_angle: np.ndarray, point_format_id: int) -> np.ndarray:
    """Convert LAS scan-angle storage to degrees according to point format."""
    scale = 0.006 if point_format_id >= 6 else 1.0
    return np.asarray(raw_scan_angle, dtype=float) * scale


def extract_near_facade_returns(
    laz_path: str | Path,
    segments: pd.DataFrame,
    lines: list[LineString],
    config: FacadeAuditConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Stream points and assign each near-wall return to its nearest wall segment."""
    config.validate()
    path = Path(laz_path)
    tree = STRtree(lines)
    line_array = np.asarray(lines, dtype=object)
    lower = segments["audit_base_z_ahd"].to_numpy(dtype=float)
    upper = segments["audit_top_z_ahd"].to_numpy(dtype=float)
    selected_classes = np.asarray(
        sorted(set(config.evidence_classes) | set(config.vegetation_classes)), dtype=np.uint8
    )
    chunks: dict[str, list[np.ndarray]] = {
        name: []
        for name in (
            "segment_index",
            "x",
            "y",
            "z",
            "classification",
            "intensity",
            "scan_angle_deg",
            "distance_m",
            "along_m",
        )
    }
    scanned_points = 0
    relevant_class_points = 0
    pair_matches = 0
    assigned_points = 0
    chunk_count = 0

    with laspy.open(path) as reader:
        crs = reader.header.parse_crs()
        if crs is None or crs.to_epsg() != TARGET_EPSG:
            raise ValueError(f"Facade point cloud must use EPSG:{TARGET_EPSG}")
        point_format_id = int(reader.header.point_format.id)
        dimension_names = tuple(reader.header.point_format.dimension_names)
        point_count = int(reader.header.point_count)
        for points in reader.chunk_iterator(config.chunk_size):
            chunk_count += 1
            scanned_points += len(points)
            classification_all = np.asarray(points.classification, dtype=np.uint8)
            keep_class = np.isin(classification_all, selected_classes)
            if not keep_class.any():
                continue
            x = np.asarray(points.x)[keep_class]
            y = np.asarray(points.y)[keep_class]
            z = np.asarray(points.z)[keep_class]
            classification = classification_all[keep_class]
            intensity = np.asarray(points.intensity)[keep_class]
            scan_angle = _scan_angle_degrees(
                np.asarray(points.scan_angle)[keep_class], point_format_id
            )
            relevant_class_points += len(x)
            point_geometry = shapely.points(x, y)
            matches = tree.query(
                point_geometry,
                predicate="dwithin",
                distance=config.wall_search_distance_m,
            )
            if not matches.size:
                continue
            point_indices = matches[0]
            segment_indices = matches[1]
            pair_matches += len(point_indices)
            vertical = (z[point_indices] >= lower[segment_indices]) & (
                z[point_indices] <= upper[segment_indices]
            )
            point_indices = point_indices[vertical]
            segment_indices = segment_indices[vertical]
            if not len(point_indices):
                continue
            distances = shapely.distance(
                point_geometry[point_indices], line_array[segment_indices]
            )
            order = np.lexsort((segment_indices, distances, point_indices))
            point_indices = point_indices[order]
            segment_indices = segment_indices[order]
            distances = distances[order]
            unique = np.ones(len(point_indices), dtype=bool)
            unique[1:] = point_indices[1:] != point_indices[:-1]
            point_indices = point_indices[unique]
            segment_indices = segment_indices[unique]
            distances = distances[unique]

            start_x = segments["start_easting"].to_numpy()[segment_indices]
            start_y = segments["start_northing"].to_numpy()[segment_indices]
            end_x = segments["end_easting"].to_numpy()[segment_indices]
            end_y = segments["end_northing"].to_numpy()[segment_indices]
            dx = end_x - start_x
            dy = end_y - start_y
            lengths = segments["length_m"].to_numpy()[segment_indices]
            along = (
                (x[point_indices] - start_x) * dx + (y[point_indices] - start_y) * dy
            ) / lengths
            along = np.clip(along, 0.0, lengths)
            values = {
                "segment_index": segment_indices.astype(np.int32),
                "x": x[point_indices].astype(np.float64),
                "y": y[point_indices].astype(np.float64),
                "z": z[point_indices].astype(np.float64),
                "classification": classification[point_indices].astype(np.uint8),
                "intensity": intensity[point_indices].astype(np.uint16),
                "scan_angle_deg": scan_angle[point_indices].astype(np.float32),
                "distance_m": np.asarray(distances, dtype=np.float32),
                "along_m": along.astype(np.float32),
            }
            for name, value in values.items():
                chunks[name].append(value)
            assigned_points += len(point_indices)

    arrays = {
        name: np.concatenate(values) if values else np.asarray([], dtype=float)
        for name, values in chunks.items()
    }
    returns = pd.DataFrame(arrays)
    if not returns.empty:
        returns["segment_index"] = returns["segment_index"].astype(np.int32)
        returns["classification"] = returns["classification"].astype(np.uint8)
        returns["intensity"] = returns["intensity"].astype(np.uint16)
    statistics = {
        "point_format": point_format_id,
        "dimensions": list(dimension_names),
        "rgb_dimensions_present": all(
            name in {str(value).lower() for value in dimension_names}
            for name in ("red", "green", "blue")
        ),
        "header_point_count": point_count,
        "scanned_points": scanned_points,
        "chunks": chunk_count,
        "points_in_selected_classes": relevant_class_points,
        "point_segment_pairs_before_vertical_and_nearest_filters": pair_matches,
        "near_facade_points_assigned": assigned_points,
        "classification_counts": {
            str(int(code)): int(count)
            for code, count in zip(
                *np.unique(returns["classification"], return_counts=True), strict=True
            )
        }
        if not returns.empty
        else {},
    }
    return returns, statistics


def _coverage(values: np.ndarray, extent: float, bin_size: float) -> tuple[float, np.ndarray]:
    total = max(1, int(math.ceil(extent / bin_size)))
    if not len(values):
        return 0.0, np.asarray([], dtype=np.int64)
    indices = np.floor(np.asarray(values) / bin_size).astype(np.int64)
    indices = np.clip(indices, 0, total - 1)
    unique = np.unique(indices)
    return float(len(unique) / total), unique


def facade_segment_status(metrics: dict[str, float], config: FacadeAuditConfig) -> str:
    """Assign a conservative evidence status from declared segment thresholds."""
    strong = (
        metrics["evidence_points"] >= config.strong_minimum_points
        and metrics["evidence_density_m2"] >= config.strong_minimum_density_m2
        and metrics["vertical_bin_coverage"] >= config.strong_minimum_vertical_coverage
        and metrics["horizontal_bin_coverage"] >= config.strong_minimum_horizontal_coverage
        and metrics["grid_bin_coverage"] >= config.strong_minimum_grid_coverage
        and metrics["vertical_span_fraction"] >= config.strong_minimum_vertical_span
        and metrics["p95_distance_m"] <= config.strong_maximum_p95_distance_m
    )
    if strong:
        return "sufficient"
    marginal = (
        metrics["evidence_points"] >= config.marginal_minimum_points
        and metrics["evidence_density_m2"] >= config.marginal_minimum_density_m2
        and metrics["vertical_bin_coverage"] >= config.marginal_minimum_vertical_coverage
        and metrics["horizontal_bin_coverage"] >= config.marginal_minimum_horizontal_coverage
        and metrics["vertical_span_fraction"] >= config.marginal_minimum_vertical_span
        and metrics["p95_distance_m"] <= config.marginal_maximum_p95_distance_m
    )
    return "marginal" if marginal else "insufficient"


def evaluate_facade_segments(
    segments: pd.DataFrame,
    returns: pd.DataFrame,
    config: FacadeAuditConfig,
) -> pd.DataFrame:
    """Measure density, coverage and planarity evidence for every facade segment."""
    output_rows: list[dict[str, Any]] = []
    evidence_classes = set(config.evidence_classes)
    vegetation_classes = set(config.vegetation_classes)
    grouped = {int(key): value for key, value in returns.groupby("segment_index")}
    for row in segments.itertuples(index=False):
        points = grouped.get(int(row.segment_index), returns.iloc[0:0])
        evidence = points.loc[points["classification"].isin(evidence_classes)]
        vegetation = points.loc[points["classification"].isin(vegetation_classes)]
        wall_area = float(row.length_m * row.audit_height_m)
        vertical_values = evidence["z"].to_numpy() - float(row.audit_base_z_ahd)
        horizontal_values = evidence["along_m"].to_numpy()
        vertical_coverage, vertical_bins = _coverage(
            vertical_values, float(row.audit_height_m), config.coverage_bin_m
        )
        horizontal_coverage, horizontal_bins = _coverage(
            horizontal_values, float(row.length_m), config.coverage_bin_m
        )
        vertical_total = max(1, int(math.ceil(row.audit_height_m / config.coverage_bin_m)))
        horizontal_total = max(1, int(math.ceil(row.length_m / config.coverage_bin_m)))
        if len(evidence):
            vertical_index = np.floor(vertical_values / config.coverage_bin_m).astype(int)
            horizontal_index = np.floor(horizontal_values / config.coverage_bin_m).astype(int)
            vertical_index = np.clip(vertical_index, 0, vertical_total - 1)
            horizontal_index = np.clip(horizontal_index, 0, horizontal_total - 1)
            grid_cells = np.unique(
                np.column_stack([horizontal_index, vertical_index]), axis=0
            )
            grid_coverage = float(len(grid_cells) / (horizontal_total * vertical_total))
            z05, z95 = np.percentile(evidence["z"], [5, 95])
            span_fraction = float((z95 - z05) / max(row.audit_height_m, 1e-9))
            p50_distance, p95_distance = np.percentile(evidence["distance_m"], [50, 95])
            intensity_median = float(np.median(evidence["intensity"]))
            angle_abs_median = float(np.median(np.abs(evidence["scan_angle_deg"])))
            angle_min = float(evidence["scan_angle_deg"].min())
            angle_max = float(evidence["scan_angle_deg"].max())
        else:
            grid_coverage = 0.0
            span_fraction = 0.0
            p50_distance = math.inf
            p95_distance = math.inf
            intensity_median = math.nan
            angle_abs_median = math.nan
            angle_min = math.nan
            angle_max = math.nan
        evidence_count = len(evidence)
        vegetation_count = len(vegetation)
        metrics = {
            "evidence_points": int(evidence_count),
            "class6_points": int((evidence["classification"] == 6).sum()),
            "unclassified_points": int((evidence["classification"] == 1).sum()),
            "vegetation_points": int(vegetation_count),
            "evidence_density_m2": float(evidence_count / max(wall_area, 1e-9)),
            "vertical_bin_coverage": vertical_coverage,
            "horizontal_bin_coverage": horizontal_coverage,
            "grid_bin_coverage": grid_coverage,
            "vertical_span_fraction": span_fraction,
            "median_distance_m": float(p50_distance),
            "p95_distance_m": float(p95_distance),
            "median_intensity": intensity_median,
            "median_absolute_scan_angle_deg": angle_abs_median,
            "minimum_scan_angle_deg": angle_min,
            "maximum_scan_angle_deg": angle_max,
            "vegetation_fraction_near_wall": float(
                vegetation_count / max(evidence_count + vegetation_count, 1)
            ),
            "vertical_bins_observed": int(len(vertical_bins)),
            "horizontal_bins_observed": int(len(horizontal_bins)),
        }
        output = row._asdict()
        output.update(metrics)
        output["evidence_status"] = facade_segment_status(metrics, config)
        output_rows.append(output)
    return pd.DataFrame(output_rows)


def _weighted_mean(frame: pd.DataFrame, column: str) -> float:
    valid = frame[column].replace([np.inf, -np.inf], np.nan).notna()
    if not valid.any():
        return math.nan
    return float(np.average(frame.loc[valid, column], weights=frame.loc[valid, "length_m"]))


def evaluate_facade_buildings(
    buildings: gpd.GeoDataFrame,
    segments: pd.DataFrame,
    config: FacadeAuditConfig,
) -> pd.DataFrame:
    """Aggregate segment evidence and rank every modelled building."""
    records: list[dict[str, Any]] = []
    attributes = buildings.set_index("building_id")
    for building_id, frame in segments.groupby("building_id", sort=True):
        perimeter = float(frame["length_m"].sum())
        wall_area = float((frame["length_m"] * frame["audit_height_m"]).sum())
        points = int(frame["evidence_points"].sum())
        vegetation = int(frame["vegetation_points"].sum())
        strong = frame["evidence_status"] == "sufficient"
        marginal = frame["evidence_status"] == "marginal"
        observed = strong | marginal
        strong_fraction = float(frame.loc[strong, "length_m"].sum() / perimeter)
        observed_fraction = float(frame.loc[observed, "length_m"].sum() / perimeter)
        density = float(points / max(wall_area, 1e-9))
        vertical_coverage = _weighted_mean(frame, "vertical_bin_coverage")
        horizontal_coverage = _weighted_mean(frame, "horizontal_bin_coverage")
        grid_coverage = _weighted_mean(frame, "grid_bin_coverage")
        finite_residual = frame["p95_distance_m"].replace([np.inf, -np.inf], np.nan)
        residual = (
            float(
                np.average(
                    finite_residual.dropna(),
                    weights=frame.loc[finite_residual.notna(), "length_m"],
                )
            )
            if finite_residual.notna().any()
            else math.inf
        )
        scan_angle = _weighted_mean(frame, "median_absolute_scan_angle_deg")
        point_score = min(math.log1p(points) / math.log1p(500), 1.0)
        density_score = min(density / 1.0, 1.0)
        observed_score = min((strong_fraction + 0.5 * observed_fraction) / 0.50, 1.0)
        residual_score = max(0.0, 1.0 - min(residual, 0.75) / 0.75)
        angle_score = min((scan_angle if np.isfinite(scan_angle) else 0.0) / 15.0, 1.0)
        score = 100.0 * (
            0.20 * point_score
            + 0.20 * density_score
            + 0.15 * vertical_coverage
            + 0.15 * horizontal_coverage
            + 0.15 * observed_score
            + 0.10 * residual_score
            + 0.05 * angle_score
        )
        source_row = attributes.loc[building_id]
        if bool(source_row["boundary_clipped"]):
            score = max(0.0, score - 5.0)
        sufficient = (
            int(strong.sum()) >= 2
            and strong_fraction >= 0.15
            and points >= 100
            and vertical_coverage >= 0.45
            and density >= 0.30
        )
        marginal_building = (
            (int(strong.sum()) >= 1 or int(marginal.sum()) >= 2)
            and observed_fraction >= 0.10
            and points >= 30
        )
        status = (
            "sufficient"
            if sufficient
            else ("marginal" if marginal_building else "insufficient")
        )
        records.append(
            {
                "building_id": building_id,
                "building_name": _display_name(source_row["building_name"]),
                "output_lod": str(source_row["output_lod"]),
                "lod2_status": str(source_row["lod2_status"]),
                "building_confidence": str(source_row["confidence"]),
                "boundary_clipped": bool(source_row["boundary_clipped"]),
                "facade_segments": len(frame),
                "sufficient_segments": int(strong.sum()),
                "marginal_segments": int(marginal.sum()),
                "insufficient_segments": int((~observed).sum()),
                "audited_perimeter_m": perimeter,
                "audited_wall_area_m2": wall_area,
                "evidence_points": points,
                "class6_points": int(frame["class6_points"].sum()),
                "unclassified_points": int(frame["unclassified_points"].sum()),
                "vegetation_points_near_walls": vegetation,
                "evidence_density_m2": density,
                "weighted_vertical_coverage": vertical_coverage,
                "weighted_horizontal_coverage": horizontal_coverage,
                "weighted_grid_coverage": grid_coverage,
                "strong_perimeter_fraction": strong_fraction,
                "observed_perimeter_fraction": observed_fraction,
                "weighted_p95_distance_m": residual,
                "weighted_median_absolute_scan_angle_deg": scan_angle,
                "vegetation_fraction_near_walls": float(
                    vegetation / max(points + vegetation, 1)
                ),
                "facade_evidence_score": round(score, 3),
                "facade_evidence_status": status,
                "geometry_use": (
                    "candidate for targeted manual wall-plane refinement"
                    if status == "sufficient"
                    else (
                        "manual inspection only; do not automate wall reconstruction"
                        if status == "marginal"
                        else "retain footprint extrusion; evidence insufficient"
                    )
                ),
                "texture_use": "none; LAS point format has no RGB facade imagery",
            }
        )
    output = pd.DataFrame(records).sort_values(
        ["facade_evidence_score", "building_id"], ascending=[False, True]
    )
    output.insert(0, "evidence_rank", np.arange(1, len(output) + 1))
    return output.reset_index(drop=True)


def save_facade_returns(returns: pd.DataFrame, output_path: str | Path) -> Path:
    """Preserve the complete filtered near-wall point set as compressed numeric arrays."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        **{column: returns[column].to_numpy() for column in returns.columns},
    )
    return destination


def _plot_polygon_boundary(axis: Any, geometry: Polygon | MultiPolygon) -> None:
    for polygon in _polygon_parts(geometry):
        coordinates = np.asarray(polygon.exterior.coords)
        axis.plot(coordinates[:, 0], coordinates[:, 1], color="#243447", linewidth=1.4)


def render_facade_overview(
    buildings: gpd.GeoDataFrame,
    building_audit: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    """Render a campus plan of building-level facade evidence and top-five ranks."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame = buildings.loc[buildings["model_status"] == "modelled", ["building_id", "geometry"]]
    frame = frame.merge(building_audit, on="building_id", how="left")
    figure, axis = plt.subplots(figsize=(11, 9), constrained_layout=True)
    for status in ("insufficient", "marginal", "sufficient"):
        subset = frame.loc[frame["facade_evidence_status"] == status]
        if not subset.empty:
            subset.plot(
                ax=axis,
                facecolor=EVIDENCE_COLOURS[status],
                edgecolor="white",
                linewidth=0.6,
                alpha=0.82,
            )
    for row in frame.loc[frame["evidence_rank"] <= 5].itertuples():
        centroid = row.geometry.centroid
        axis.text(
            centroid.x,
            centroid.y,
            f"{int(row.evidence_rank)}",
            ha="center",
            va="center",
            fontsize=9,
            weight="bold",
            color="white",
            bbox={"boxstyle": "circle,pad=0.18", "facecolor": "#243447", "edgecolor": "white"},
        )
    status_counts = building_audit["facade_evidence_status"].value_counts()
    handles = [
        Patch(
            facecolor=EVIDENCE_COLOURS[status],
            label=f"{status.title()} ({int(status_counts.get(status, 0))})",
        )
        for status in ("sufficient", "marginal", "insufficient")
    ]
    handles.append(
        Line2D([], [], marker="o", color="#243447", linestyle="None", label="Top-five rank")
    )
    axis.legend(handles=handles, loc="upper left", framealpha=0.95)
    axis.set(
        title=(
            "Phase 11 facade-evidence screen\n"
            "Airborne LiDAR near footprint wall planes; geometry evidence only, no RGB"
        ),
        xlabel="Easting (m, GDA2020 / MGA zone 56)",
        ylabel="Northing (m)",
        aspect="equal",
    )
    axis.ticklabel_format(style="plain", useOffset=False)
    figure.savefig(destination, dpi=180)
    plt.close(figure)
    return destination


def render_facade_details(
    buildings: gpd.GeoDataFrame,
    segment_audit: pd.DataFrame,
    building_audit: pd.DataFrame,
    returns: pd.DataFrame,
    output_path: str | Path,
    *,
    candidate_count: int = 5,
) -> Path:
    """Render plan and unfolded-elevation evidence for the highest-ranked buildings."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    selected = building_audit.head(candidate_count)
    attributes = buildings.set_index("building_id")
    figure, axes = plt.subplots(
        len(selected),
        2,
        figsize=(17, 4.1 * len(selected)),
        constrained_layout=True,
        gridspec_kw={"width_ratios": [0.8, 1.7]},
    )
    axes = np.atleast_2d(axes)
    for row_index, building in enumerate(selected.itertuples(index=False)):
        segments = segment_audit.loc[
            segment_audit["building_id"] == building.building_id
        ].copy()
        segment_indices = set(segments["segment_index"].astype(int))
        points = returns.loc[returns["segment_index"].isin(segment_indices)].copy()
        evidence = points.loc[points["classification"].isin((1, 6))].copy()
        vegetation = points.loc[points["classification"].isin((3, 4, 5))].copy()
        plan_axis, elevation_axis = axes[row_index]
        geometry = attributes.loc[building.building_id, "geometry"]
        _plot_polygon_boundary(plan_axis, geometry)
        for segment in segments.itertuples(index=False):
            plan_axis.plot(
                [segment.start_easting, segment.end_easting],
                [segment.start_northing, segment.end_northing],
                color=EVIDENCE_COLOURS[segment.evidence_status],
                linewidth=3.0,
            )
        if len(vegetation):
            plan_axis.scatter(
                vegetation["x"],
                vegetation["y"],
                s=4,
                color="#697A6B",
                alpha=0.28,
                marker="x",
            )
        if len(evidence):
            plan_axis.scatter(
                evidence["x"], evidence["y"], s=5, color="#172A3A", alpha=0.48
            )
        minimum_x, minimum_y, maximum_x, maximum_y = geometry.bounds
        padding = max(maximum_x - minimum_x, maximum_y - minimum_y) * 0.12 + 1.0
        plan_axis.set_xlim(minimum_x - padding, maximum_x + padding)
        plan_axis.set_ylim(minimum_y - padding, maximum_y + padding)
        plan_axis.set_aspect("equal")
        plan_axis.ticklabel_format(style="plain", useOffset=False)
        plan_axis.set_title(
            f"#{building.evidence_rank} {building.building_id} plan\n"
            f"{building.building_name}"
        )
        plan_axis.set_xlabel("Easting (m)")
        plan_axis.set_ylabel("Northing (m)")

        segment_lookup = segments.set_index("segment_index")
        for segment in segments.itertuples(index=False):
            left = segment.cumulative_start_m
            right = left + segment.length_m
            elevation_axis.axvspan(
                left,
                right,
                color=EVIDENCE_COLOURS[segment.evidence_status],
                alpha=0.10,
            )
            elevation_axis.axvline(right, color="#AAB4BC", linewidth=0.35)
        if len(evidence):
            point_segments = segment_lookup.loc[evidence["segment_index"].astype(int)]
            perimeter_x = (
                point_segments["cumulative_start_m"].to_numpy()
                + evidence["along_m"].to_numpy()
            )
            relative_z = (
                evidence["z"].to_numpy()
                - point_segments["audit_base_z_ahd"].to_numpy()
            )
            scatter = elevation_axis.scatter(
                perimeter_x,
                relative_z,
                c=np.abs(evidence["scan_angle_deg"]),
                cmap="plasma",
                vmin=0,
                vmax=35,
                s=8,
                alpha=0.70,
                edgecolors="none",
            )
            if row_index == 0:
                figure.colorbar(
                    scatter,
                    ax=elevation_axis,
                    location="right",
                    shrink=0.75,
                    label="Absolute scan angle (degrees)",
                )
        maximum_height = float(segments["audit_height_m"].max())
        elevation_axis.set_ylim(-0.2, maximum_height + 0.5)
        maximum_perimeter = float(
            (segments["cumulative_start_m"] + segments["length_m"]).max()
        )
        elevation_axis.set_xlim(0, maximum_perimeter)
        elevation_axis.set_title(
            f"Unfolded wall evidence: {building.facade_evidence_status} "
            f"({building.facade_evidence_score:.1f}/100)\n"
            f"{building.evidence_points} returns; {building.evidence_density_m2:.2f} points/m²"
        )
        elevation_axis.set_xlabel("Cumulative footprint perimeter (m)")
        elevation_axis.set_ylabel("Height above audited facade base (m)")
        elevation_axis.grid(axis="y", color="#D5DCE1", linewidth=0.5)
    figure.suptitle(
        "Five strongest facade-evidence candidates — geometry assessment only; no RGB texture",
        fontsize=17,
    )
    figure.savefig(destination, dpi=180)
    plt.close(figure)
    return destination


def run_facade_evidence_audit(
    buildings: gpd.GeoDataFrame,
    laz_path: str | Path,
    output_paths: dict[str, Path],
    config: FacadeAuditConfig | None = None,
) -> dict[str, Any]:
    """Run the streamed all-building audit and write tables, sample and figures."""
    config = config or FacadeAuditConfig()
    config.validate()
    segments, lines = build_facade_segments(buildings, config)
    returns, cloud = extract_near_facade_returns(laz_path, segments, lines, config)
    segment_audit = evaluate_facade_segments(segments, returns, config)
    building_audit = evaluate_facade_buildings(buildings, segment_audit, config)
    top_candidates = building_audit.head(config.detailed_candidate_count).copy()

    for key in ("segments", "buildings", "top_candidates"):
        output_paths[key].parent.mkdir(parents=True, exist_ok=True)
    segment_audit.to_csv(output_paths["segments"], index=False)
    building_audit.to_csv(output_paths["buildings"], index=False)
    top_candidates.to_csv(output_paths["top_candidates"], index=False)
    save_facade_returns(returns, output_paths["returns"])
    render_facade_overview(buildings, building_audit, output_paths["overview"])
    render_facade_details(
        buildings,
        segment_audit,
        building_audit,
        returns,
        output_paths["details"],
        candidate_count=config.detailed_candidate_count,
    )

    evidence_mask = returns["classification"].isin(config.evidence_classes)
    checks = {
        "all_58_modelled_buildings_screened": len(building_audit) == 58,
        "all_eligible_segments_evaluated": len(segment_audit) == len(segments),
        "point_cloud_scanned_in_multiple_chunks": cloud["chunks"] > 1,
        "point_cloud_header_and_stream_counts_match": (
            cloud["header_point_count"] == cloud["scanned_points"]
        ),
        "point_cloud_has_scan_angle_and_intensity": (
            "scan_angle" in cloud["dimensions"] and "intensity" in cloud["dimensions"]
        ),
        "point_cloud_has_no_rgb_dimensions": not cloud["rgb_dimensions_present"],
        "near_wall_evidence_returns_found": int(evidence_mask.sum()) > 0,
        "five_candidates_ranked_for_detail": len(top_candidates) == 5,
        "facade_conclusion_does_not_claim_texture_support": bool(
            building_audit["texture_use"].str.startswith("none;").all()
        ),
    }
    summary = {
        "status": "passed" if all(checks.values()) else "failed",
        "method": (
            "Stream class 1/3/4/5/6 returns, retain points within the declared horizontal "
            "wall band and vertical facade interval, assign each return to its nearest "
            "footprint segment, then measure density, coverage, residual and scan angle."
        ),
        "configuration": asdict(config),
        "point_cloud": cloud,
        "screened_buildings": len(building_audit),
        "screened_segments": len(segment_audit),
        "evidence_returns": int(evidence_mask.sum()),
        "vegetation_returns_near_walls": int((~evidence_mask).sum()),
        "building_status_counts": {
            str(key): int(value)
            for key, value in building_audit["facade_evidence_status"].value_counts().items()
        },
        "segment_status_counts": {
            str(key): int(value)
            for key, value in segment_audit["evidence_status"].value_counts().items()
        },
        "top_candidates": top_candidates[
            [
                "evidence_rank",
                "building_id",
                "building_name",
                "facade_evidence_score",
                "facade_evidence_status",
                "evidence_points",
                "evidence_density_m2",
            ]
        ].to_dict(orient="records"),
        "checks": checks,
        "interpretation": (
            "A sufficient result supports targeted manual wall-plane refinement only. "
            "It does not support facade photography, windows, doors or materials."
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Facade evidence audit failed: {', '.join(failed)}")
    return summary
