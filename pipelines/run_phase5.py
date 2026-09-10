"""Command-line entry point for Phase 5 terrain and LiDAR preparation."""

from pathlib import Path

from uqgems.phase5 import run_phase5

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase5(project_root)
    print(f"Phase 5 status: {result['status']}")
    print(f"Cache reused: {result['cache_reused']}")
    print(f"Summary report: {project_root / result['summary_report']}")
