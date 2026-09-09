"""Command-line entry point for the Phase 2 synthetic workflow."""

from pathlib import Path

from uqgems.phase2 import run_phase2

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase2(project_root)
    print(f"Phase 2 status: {result['status']}")
    print(f"Summary report: {project_root / result['summary_report']}")
