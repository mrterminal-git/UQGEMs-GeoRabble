"""Command-line entry point for Phase 6 LoD1 building generation."""

from pathlib import Path

from uqgems.phase6 import run_phase6

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase6(project_root)
    print(f"Phase 6 status: {result['status']}")
    print(f"Cache reused: {result['cache_reused']}")
    print(f"Summary report: {project_root / result['summary_report']}")
