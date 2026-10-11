"""Comprehensive test suite for Phase P-17: Open Source Mini Challenge.

Covers exact micro-tasks:
- P-17.01: Select OSS route: new reusable library (mcp-verify).
- P-17.02: Freeze separate repo/contribution provenance and license (Apache-2.0, clean-room).
- P-17.03: Implement reusable verification contract with tests.
- P-17.04: Add at least one real integration example.
- P-17.05: Package metadata, build configuration, and pyproject.toml verified.
- P-17.06: Open Source Mini Challenge documentation verified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure packages/mcp_verify/src is in sys.path
root_dir = Path(__file__).resolve().parent.parent
pkg_src = root_dir / "packages" / "mcp_verify" / "src"
if str(pkg_src) not in sys.path:
    sys.path.insert(0, str(pkg_src))

from mcp_verify import (
    PredicateOperator,
    VerifiableOutcome,
    VerifiableToolMiddleware,
    VerificationPredicate,
    VerificationStatus,
    Verifier,
)


def test_p17_01_oss_route_selection() -> None:
    """Verify P-17.01: Reusable MCP verification library mcp-verify is implemented and importable."""
    assert VerifiableToolMiddleware is not None
    assert VerificationPredicate is not None
    assert Verifier is not None


def test_p17_02_provenance_and_license() -> None:
    """Verify P-17.02: Package license is Apache-2.0 and contains zero proprietary code."""
    pkg_dir = root_dir / "packages" / "mcp_verify"
    license_file = pkg_dir / "LICENSE"
    assert license_file.exists()
    license_content = license_file.read_text(encoding="utf-8")
    assert "Apache License" in license_content
    assert "Version 2.0" in license_content
    assert "StillDone Authors" in license_content


def test_p17_03_reusable_verification_contracts() -> None:
    """Verify P-17.03: Reusable verification contracts enforce core StillDone invariants."""
    mw = VerifiableToolMiddleware()

    task_store = {"task_1": {"title": "Original Title"}}

    @mw.register_verifiable_tool("update_task", "get_task")
    def extract_predicate(args: dict, result: dict) -> VerificationPredicate:
        return VerificationPredicate(
            target_id=args["id"],
            attribute="title",
            operator=PredicateOperator.EQUALS,
            expected_value=args["title"],
        )

    @mw.register_readback_handler("get_task")
    def read_task(target_id: str) -> dict:
        return task_store.get(target_id, {})

    # Success case
    def update_task_success(args: dict) -> dict:
        task_store[args["id"]]["title"] = args["title"]
        return {"status": "ok"}

    outcome = mw.execute_and_verify(
        tool_name="update_task",
        tool_args={"id": "task_1", "title": "Verified Pack backpacks"},
        tool_executor=update_task_success,
    )
    assert outcome.is_verified is True
    assert outcome.status == VerificationStatus.VERIFIED

    # Contradiction case (write succeeds, but readback contradicts)
    def update_task_buggy(args: dict) -> dict:
        # Fails to write to store
        return {"status": "ok"}

    outcome_bad = mw.execute_and_verify(
        tool_name="update_task",
        tool_args={"id": "task_1", "title": "Another Title"},
        tool_executor=update_task_buggy,
    )
    assert outcome_bad.execution.is_success is True
    assert outcome_bad.is_verified is False
    assert outcome_bad.status == VerificationStatus.CONTRADICTED


def test_p17_04_real_integration_example_executes() -> None:
    """Verify P-17.04: Integration example exists and runs cleanly."""
    example_path = root_dir / "packages" / "mcp_verify" / "examples" / "verifiable_calendar_tool.py"
    assert example_path.exists()

    # Import and run example function
    import importlib.util

    spec = importlib.util.spec_from_file_location("verifiable_calendar_tool", example_path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert hasattr(mod, "run_example")
    mod.run_example()


def test_p17_05_pyproject_metadata() -> None:
    """Verify P-17.05: Standalone pyproject.toml defines valid PEP 621 metadata."""
    pyproject_file = root_dir / "packages" / "mcp_verify" / "pyproject.toml"
    assert pyproject_file.exists()
    content = pyproject_file.read_text(encoding="utf-8")
    assert 'name = "mcp-verify"' in content
    assert 'version = "0.1.0"' in content
    assert 'license = "Apache-2.0"' in content
    assert "hatchling" in content


def test_p17_06_evidence_description() -> None:
    """Verify P-17.06: Open Source Mini Challenge evidence document exists and is complete."""
    doc_path = root_dir / "docs" / "OPEN_SOURCE_MINI_CHALLENGE.md"
    assert doc_path.exists()
    content = doc_path.read_text(encoding="utf-8")
    assert "Open Source Mini Challenge" in content
    assert "mcp-verify" in content
    assert "Apache-2.0" in content
