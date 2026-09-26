"""Command-line entry point for Phase 10 reproducibility validation."""

import argparse
from pathlib import Path

from uqgems.phase10 import run_phase10

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-notebook-evidence",
        action="store_true",
        help=(
            "Reuse the recorded Phase 1-9 notebook results and execute only the final "
            "validation notebook."
        ),
    )
    arguments = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    result = run_phase10(
        project_root,
        execute_notebooks=not arguments.reuse_notebook_evidence,
        execute_validation_notebook=True,
    )
    print(f"Phase 10 status: {result['status']}")
    print(
        "Prior checks: "
        f"{result['prior_phase_validation']['checks_passed']}/"
        f"{result['prior_phase_validation']['checks_total']}"
    )
    print(
        "Fresh-kernel notebooks: "
        f"{result['notebook_execution']['passed']}/"
        f"{result['notebook_execution']['expected']}"
    )
    print(f"Checks: {sum(result['checks'].values())}/{len(result['checks'])}")
    print(f"Summary: {project_root / result['outputs']['summary']}")
