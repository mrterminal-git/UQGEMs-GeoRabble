"""Command-line entry point for Phase 9 integrated visualisation."""

from pathlib import Path

from uqgems.phase9 import run_phase9

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase9(project_root)
    print(f"Phase 9 status: {result['status']}")
    print(f"Cache reused: {result['cache_reused']}")
    print(f"Checks passed: {sum(result['checks'].values())}/{len(result['checks'])}")
    print(f"Interactive scene: {project_root / result['outputs']['interactive_html']}")
    print(f"Summary report: {project_root / result['summary_report']}")
