"""Unit tests for the Phase 10 reproducibility helpers."""

import hashlib
from pathlib import Path

from uqgems.acquisition import sha256
from uqgems.phase10 import (
    _directory_records_sha256,
    _flatten_paths,
    _registered_output_target,
)


def test_nested_output_paths_are_flattened_in_order() -> None:
    outputs = {
        "raster": "data/a.tif",
        "figures": {"plan": "reports/plan.png", "section": "reports/section.png"},
        "ignored": 3,
    }
    assert _flatten_paths(outputs) == [
        "data/a.tif",
        "reports/plan.png",
        "reports/section.png",
    ]


def test_phase8_directory_hash_is_ordered_and_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "01_first.geojson"
    second = tmp_path / "02_second.geojson"
    ignored = tmp_path / "metadata.json"
    first.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    second.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    ignored.write_text("{}", encoding="utf-8")
    expected = hashlib.sha256((sha256(first) + sha256(second)).encode()).hexdigest()
    assert _directory_records_sha256(tmp_path) == expected


def test_phase8_directory_hash_changes_when_a_record_changes(tmp_path: Path) -> None:
    record = tmp_path / "record.geojson"
    record.write_text("first", encoding="utf-8")
    initial = _directory_records_sha256(tmp_path)
    record.write_text("second", encoding="utf-8")
    assert _directory_records_sha256(tmp_path) != initial


def test_registered_geopackage_layer_is_resolved_to_its_file() -> None:
    path, layer = _registered_output_target("data/vectors.gpkg:building_outlines")
    assert path == "data/vectors.gpkg"
    assert layer == "building_outlines"
    assert _registered_output_target("data/terrain.tif") == ("data/terrain.tif", "")
