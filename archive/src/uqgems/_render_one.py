"""Render one synthetic camera view in an isolated VTK process."""

from __future__ import annotations

import argparse
from pathlib import Path

from uqgems.scene import CAMERAS, render_png
from uqgems.synthetic import create_synthetic_dataset


def main() -> int:
    """Parse render arguments and write one PNG."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--camera", choices=sorted(CAMERAS), required=True)
    parser.add_argument("--terrain-opacity", type=float, required=True)
    arguments = parser.parse_args()
    render_png(
        create_synthetic_dataset(),
        arguments.output,
        camera=arguments.camera,
        terrain_opacity=arguments.terrain_opacity,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
