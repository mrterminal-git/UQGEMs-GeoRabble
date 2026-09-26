"""Command-line entry point for the scoped Phase 3 public-data workflow."""

from pathlib import Path

from uqgems.phase3 import run_phase3

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase3(project_root)
    print(f"Phase 3 status: {result['status']}")
    print(f"Summary report: {project_root / result['summary_report']}")
