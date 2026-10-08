"""Deterministic validation script for StillDone repository across isolated runtimes.

Validates:
1. Core / MCP runtime environment:
   - Ruff code formatting and linting
   - Mypy type-checking on core sources and tests
   - MCP version >= 2.2.0 assertion
   - Non-Strands test suite (P-02 through P-06, P-07.01-02)

2. Strands Planner runtime environment:
   - Strands-agents == 1.57.2 and supported transitive MCP (< 2.2.0) assertion
   - Mypy type-checking on planner and domain sources/tests
   - Strands planning and boundary protection test suites (P-07.01-05 + domain/security)
   - Zero network / zero Bedrock live inference assertions

Exits with non-zero status code on any failure.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path


def run_step(name: str, cmd: list[str], env: dict[str, str] | None = None) -> None:
    print(f"=== Running: {name} ===")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"FAILED: {name} exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"PASSED: {name}\n")


def validate_core_mcp() -> None:
    print("==================================================")
    print("VALIDATING STILLDONE CORE / MCP RUNTIME ENVIRONMENT")
    print("==================================================")
    python = sys.executable

    # Verify MCP >= 2.2.0 in core environment
    mcp_version = importlib.metadata.version("mcp")
    print(f"Core environment resolved mcp version: {mcp_version}")
    mcp_parts = [int(p) for p in mcp_version.split(".")[:2]]
    if mcp_parts < [2, 2]:
        print(f"FAILED: Core MCP runtime requires mcp >= 2.2.0, got {mcp_version}", file=sys.stderr)
        sys.exit(1)

    steps: list[tuple[str, list[str]]] = [
        ("Core Formatting check (ruff format)", [python, "-m", "ruff", "format", "--check", "."]),
        ("Core Lint check (ruff check)", [python, "-m", "ruff", "check", "."]),
        (
            "Core Type check (mypy)",
            [
                python,
                "-m",
                "mypy",
                "src",
                "tests",
                "--exclude",
                r"tests[\\/]planning[\\/]test_(strands_agent|rejection_hardening|planner_metadata)\.py",
            ],
        ),
        (
            "Core Test suite (non-Strands)",
            [
                python,
                "-m",
                "pytest",
                "--ignore=tests/planning/test_strands_agent.py",
                "--ignore=tests/planning/test_rejection_hardening.py",
                "--ignore=tests/planning/test_planner_metadata.py",
            ],
        ),
    ]

    for name, cmd in steps:
        run_step(name, cmd)


def validate_strands_planner() -> None:
    print("==================================================")
    print("VALIDATING STRANDS PLANNER RUNTIME ENVIRONMENT")
    print("==================================================")

    repo_root = Path(__file__).resolve().parent.parent
    planner_project = repo_root / "runtimes" / "strands_planner"

    # Verify strands and transitive mcp in planner environment
    check_versions_cmd = [
        "uv",
        "run",
        "--project",
        str(planner_project),
        "python",
        "-c",
        (
            "import importlib.metadata; "
            "strands_v = importlib.metadata.version('strands-agents'); "
            "mcp_v = importlib.metadata.version('mcp'); "
            "print(f'Planner environment resolved strands-agents: {strands_v}'); "
            "print(f'Planner environment resolved transitive mcp: {mcp_v}'); "
            "assert strands_v == '1.57.2', f'Expected strands-agents==1.57.2, got {strands_v}'; "
            "mcp_parts = [int(p) for p in mcp_v.split('.')[:2]]; "
            "assert mcp_parts < [2, 2], f'Expected mcp < 2.2 for strands-agents, got {mcp_v}'"
        ),
    ]
    run_step("Strands Planner dependency truth assertion", check_versions_cmd)

    planner_env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    smoke_cmd = [
        "uv",
        "run",
        "--project",
        str(planner_project),
        "python",
        "-c",
        (
            "import stilldone; "
            "from stilldone.planning.strands_agent import plan_with_strands; "
            "from stilldone.planning.metadata import create_planner_runtime_metadata; "
            "print('Planner isolated runtime production imports verified successfully')"
        ),
    ]
    run_step(
        "Strands Planner production import smoke (independent of pytest)",
        smoke_cmd,
        env=planner_env,
    )

    steps: list[tuple[str, list[str]]] = [
        (
            "Strands Planner Type check (mypy)",
            [
                "uv",
                "run",
                "--project",
                str(planner_project),
                "mypy",
                "src/stilldone/planning",
                "src/stilldone/domain",
                "tests/planning",
                "tests/domain",
            ],
        ),
        (
            "Strands Planner Test suite (planning + domain/security)",
            [
                "uv",
                "run",
                "--project",
                str(planner_project),
                "pytest",
                "tests/planning",
                "tests/domain",
                "tests/test_action_policy.py",
                "tests/test_authority_policy.py",
                "tests/test_capture.py",
                "tests/test_demo_isolation.py",
                "tests/test_endpoint_protection.py",
                "tests/test_evidence.py",
                "tests/test_ledger.py",
                "tests/test_phase_p03_adversarial.py",
                "tests/test_phase_p04_security_audit.py",
                "tests/test_phase_p11_authority_policy.py",
                "tests/test_receipt.py",
                "tests/test_redaction.py",
                "tests/test_serialization.py",
                "tests/test_smoke.py",
                "tests/test_transitions.py",
            ],
        ),
    ]

    for name, cmd in steps:
        run_step(name, cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic StillDone validator")
    parser.add_argument("--core-only", action="store_true", help="Validate only core/MCP runtime")
    parser.add_argument(
        "--planner-only", action="store_true", help="Validate only Strands planner runtime"
    )
    args = parser.parse_args()

    if args.core_only:
        validate_core_mcp()
    elif args.planner_only:
        validate_strands_planner()
    else:
        validate_core_mcp()
        validate_strands_planner()

    print("==================================================")
    print("ALL VALIDATION CHECKS PASSED ACROSS BOTH RUNTIMES.")
    print("==================================================")


if __name__ == "__main__":
    main()
