"""Unit tests for Phase 3 inventory helpers (no network or source data required)."""

from pathlib import Path

from uqgems.acquisition import PILOT_AREA, sha256
from uqgems.phase3 import DATA_REGISTER_FIELDS, bounds_cover


def test_pilot_area_is_500_metres_square() -> None:
    west, south, east, north = PILOT_AREA.projected_bounds
    assert east - west == 500.0
    assert north - south == 500.0
    assert PILOT_AREA.epsg == 7856


def test_bounds_cover() -> None:
    assert bounds_cover((0.0, 0.0, 10.0, 10.0), (2.0, 3.0, 8.0, 9.0))
    assert not bounds_cover((0.0, 0.0, 5.0, 5.0), (2.0, 3.0, 8.0, 9.0))


def test_sha256_streaming(tmp_path: Path) -> None:
    source = tmp_path / "example.bin"
    source.write_bytes(b"uqgems phase 3\n")
    assert sha256(source) == "95d2bd68be23b62f88958e87a253165a0821f5f14f4e07109d95d8ebef3aa3c0"


def test_data_register_contains_plan_fields() -> None:
    required = {
        "dataset",
        "source",
        "download_date",
        "capture_date",
        "licence",
        "horizontal_crs",
        "vertical_datum",
        "resolution",
        "stated_accuracy",
        "processing_status",
        "notes",
    }
    assert required.issubset(DATA_REGISTER_FIELDS)
