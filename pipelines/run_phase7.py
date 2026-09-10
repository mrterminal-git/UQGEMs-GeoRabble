"""Command-line entry point for Phase 7 selective LoD2 reconstruction."""

from pathlib import Path

from uqgems.phase7 import run_phase7

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase7(project_root)
    print(f"Phase 7 status: {result['status']}")
    print(f"Cache reused: {result['cache_reused']}")
    print(f"Summary report: {project_root / result['summary_report']}")
