"""Command-line entry point for Phase 8 public utility standardisation."""

from pathlib import Path

from uqgems.phase8 import run_phase8

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase8(project_root)
    print(f"Phase 8 status: {result['status']}")
    print(f"Cache reused: {result['cache_reused']}")
    print(f"Utility records: {result['current_statistics']['utility_records']}")
    print(f"Summary report: {project_root / result['summary_report']}")
