"""Deterministic validation script for StillDone repository.

Runs formatting, linting, type-checking, and test suite in sequence.
Exits with non-zero status code on any failure.
"""

from __future__ import annotations

import subprocess
import sys


def run_step(name: str, cmd: list[str]) -> None:
    print(f"=== Running: {name} ===")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"FAILED: {name} exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"PASSED: {name}\n")


def main() -> None:
    python = sys.executable
    steps: list[tuple[str, list[str]]] = [
        ("Formatting check (ruff format)", [python, "-m", "ruff", "format", "--check", "."]),
        ("Lint check (ruff check)", [python, "-m", "ruff", "check", "."]),
        ("Type check (mypy)", [python, "-m", "mypy", "src", "tests"]),
        ("Test suite (pytest)", [python, "-m", "pytest"]),
    ]

    for name, cmd in steps:
        run_step(name, cmd)

    print("ALL VALIDATION CHECKS PASSED.")


if __name__ == "__main__":
    main()
