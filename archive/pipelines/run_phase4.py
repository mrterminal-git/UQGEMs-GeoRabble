"""Command-line entry point for Phase 4 coordinate-system normalisation."""

from pathlib import Path

from uqgems.phase4 import run_phase4

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase4(project_root)
    print(f"Phase 4 status: {result['status']}")
    print(f"Cache reused: {result['cache_reused']}")
    print(f"Summary report: {project_root / result['summary_report']}")
