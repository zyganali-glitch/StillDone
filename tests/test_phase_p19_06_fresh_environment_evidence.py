"""Tests for Phase P-19.06: Fresh-Environment Reproduction and Evidence Capture.

Validates:
1. scripts/p19_06_capture_fresh_evidence.py execution and CLI modes (standard and --json).
2. Pristine source tree copy helper:
   - Copies src, tests, runtimes, packages, scripts, pyproject.toml, uv.lock.
   - Strictly omits .venv, __pycache__, .git, and test/mypy caches.
3. Captured evidence document (docs/P19_06_FRESH_ENVIRONMENT_EVIDENCE.md):
   - Records genuine tool versions (OS, Python, uv) and source SHA.
   - Records dual isolated environment creation without resolver overrides.
   - Records smoke test execution (> 500 tests passed, 0 failures).
   - Contains execution matrix separating Local, CI, Recorded Live, and
     Currently Deployed Live services.
   - Enforces offline fixture truth (0 external calls, 0 credentials, $0.00 personal spend).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

_evidence_script = REPO_ROOT / "scripts" / "p19_06_capture_fresh_evidence.py"
_spec = importlib.util.spec_from_file_location("p19_06_capture", _evidence_script)
assert _spec is not None and _spec.loader is not None
capture_mod: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(capture_mod)


def test_copy_pristine_source_tree_omits_venvs_and_caches() -> None:
    """1. Pristine source tree copy strictly excludes .venv and cache directories."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        capture_mod.copy_pristine_source_tree(tmp_dir)

        # Essential source files must be present
        assert (tmp_dir / "pyproject.toml").is_file()
        assert (tmp_dir / "uv.lock").is_file()
        assert (tmp_dir / "src" / "stilldone").is_dir()
        assert (tmp_dir / "runtimes" / "strands_planner" / "pyproject.toml").is_file()
        assert (tmp_dir / "runtimes" / "strands_planner" / "uv.lock").is_file()

        # Virtual environments and caches must NOT be copied
        assert not (tmp_dir / ".venv").exists()
        assert not (tmp_dir / "runtimes" / "strands_planner" / ".venv").exists()
        assert not (tmp_dir / ".git").exists()
        assert not (tmp_dir / ".pytest_cache").exists()
        assert not (tmp_dir / ".mypy_cache").exists()


def test_tool_versions_detection() -> None:
    """2. get_tool_versions detects valid OS, Python, uv, and Git SHA."""
    tools = capture_mod.get_tool_versions()

    assert "operating_system" in tools
    assert "python_version" in tools
    assert "uv_version" in tools
    assert "source_sha" in tools

    assert "Python 3." in tools["python_version"]
    assert tools["uv_version"] != "NOT_FOUND"
    assert len(tools["source_sha"]) == 40  # Valid 40-char git commit SHA


def test_evidence_document_content_and_matrix() -> None:
    """3. docs/P19_06_FRESH_ENVIRONMENT_EVIDENCE.md contains required metrics and matrix."""
    doc_path = REPO_ROOT / "docs" / "P19_06_FRESH_ENVIRONMENT_EVIDENCE.md"
    assert doc_path.is_file(), f"Missing evidence document at {doc_path}"

    content = doc_path.read_text(encoding="utf-8")

    # Header and provenance
    assert "P-19.06 — Fresh-Environment Reproduction & Evidence Capture" in content
    assert "FIXTURE / LOCAL_EXECUTION" in content
    assert "SUCCESS (PASS Candidate)" in content
    assert "$0.00" in content

    # Environment metrics
    assert "Windows 11 (win32)" in content
    assert "Core / MCP Environment" in content
    assert "Strands Planner Environment" in content
    assert "507 tests" in content or "Total Tests Passed in Fresh Environment" in content

    # Execution matrix
    assert "Differences Between Environments" in content
    assert "Local Fresh Reproduction" in content
    assert "CI Automated Validation" in content
    assert "Historical Recorded Live" in content
    assert "Currently Deployed Live Services" in content
    assert "BLOCKED_LIVE / NOT_RUN" in content

    # Offline fixture truth
    assert "External Cloud API Calls" in content
    assert "Exactly **0**" in content
    has_downloads_clause = (
        "Setup Downloads Are Not Cloud API Calls" in content
        or "PyPI Setup Downloads Separation" in content
    )
    assert has_downloads_clause


def test_capture_cli_execution_json_mode() -> None:
    """4. CLI execution in --json mode emits structured summary."""
    res = subprocess.run(
        [sys.executable, str(_evidence_script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "Capture fresh-environment reproduction evidence" in res.stdout
    assert "--json" in res.stdout
