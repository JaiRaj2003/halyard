"""Run the whole audit in dependency order.

    python analysis/audit/run_audit.py

Every step reads only ``data/raw`` (never mutated) plus the outputs of earlier
steps, and rewrites its own outputs under ``analysis/output``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

STEPS = [
    "01_profile_sources.py",
    "02_resolve_accounts.py",
    "03_resolve_people.py",
    "04_reconstruct_requests.py",
    "05_candidate_paths.py",
    "06_connector_load.py",
    "07_duplicates_trust_visibility.py",
    "08_summarise.py",
]


def run(step: str) -> None:
    path = HERE / step
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load audit step {step}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def main() -> None:
    sys.path.insert(0, str(HERE))
    for step in STEPS:
        print(f"\n{'=' * 78}\n== {step}\n{'=' * 78}")
        run(step)


if __name__ == "__main__":
    main()
