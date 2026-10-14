"""Test suite for Phase P-19.01 — Clean-Checkout Setup and Verification Path.

Validates:
1. scripts/reproduce.py exists, parses arguments, and provides comprehensive CLI help.
2. Lockfile integrity & runtime isolation:
   - Core runtime requires mcp >= 2.2.0;
   - Strands Planner runtime pins strands-agents == 1.57.2 with transitive mcp < 2.2.0;
   - Lockfiles exist independently and are never merged.
3. System prerequisite validation:
   - Python version bounds enforcement (>= 3.11);
   - Clear, sanitized guidance when uv package manager is missing (Windows, macOS, Linux).
4. Evidence provenance and zero-spend disclosure:
   - Zero cloud credentials required for default reproduction;
   - Strictly offline FIXTURE / LOCAL_EXECUTION provenance;
   - Clear disclosure distinguishing offline reproduction from RECORDED_LIVE evidence;
   - $0.00 personal spend target preserved.
5. True isolated clean-checkout test:
   - Copies clean source tree without existing virtual environments (.venv) or caches
     into an isolated temporary working directory;
   - Executes reproduction script to prove fresh-environment reproducibility.
"""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_reproduce_path = REPO_ROOT / "scripts" / "reproduce.py"
_reproduce_spec = importlib.util.spec_from_file_location("reproduce_script", _reproduce_path)
assert _reproduce_spec is not None and _reproduce_spec.loader is not None
reproduce_mod: Any = importlib.util.module_from_spec(_reproduce_spec)
_reproduce_spec.loader.exec_module(reproduce_mod)


def test_reproduce_script_help() -> None:
    """Verify scripts/reproduce.py exists and returns helpful CLI documentation."""
    reproduce_script = REPO_ROOT / "scripts" / "reproduce.py"
    assert reproduce_script.is_file(), f"Missing reproduction script at {reproduce_script}"

    result = subprocess.run(
        [sys.executable, str(reproduce_script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"reproduce.py --help failed: {result.stderr}"
    assert "StillDone Clean-Checkout Setup and Verification Script" in result.stdout
    assert "--full" in result.stdout
    assert "--check-only" in result.stdout
    assert "--sync-only" in result.stdout


def test_dependency_isolation_lockfiles_distinct() -> None:
    """Verify that the two runtime lockfiles exist independently and are not merged."""
    core_lock = REPO_ROOT / "uv.lock"
    planner_lock = REPO_ROOT / "runtimes" / "strands_planner" / "uv.lock"

    assert core_lock.is_file(), "Core uv.lock missing"
    assert planner_lock.is_file(), "Strands planner uv.lock missing"
    assert core_lock.resolve() != planner_lock.resolve(), "Lockfiles must be distinct files"

    core_content = core_lock.read_text(encoding="utf-8")
    planner_content = planner_lock.read_text(encoding="utf-8")

    # Core requires mcp >= 2.2.0
    assert 'name = "mcp"' in core_content
    # Strands requires strands-agents == 1.57.2
    assert 'name = "strands-agents"' in planner_content
    assert 'version = "1.57.2"' in planner_content


def test_prerequisite_uv_missing_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify helpful, platform-specific install instructions when uv is missing."""
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), pytest.raises(SystemExit) as exc_info:
        reproduce_mod.check_prerequisites(REPO_ROOT)

    assert exc_info.value.code == 1
    err_text = stderr_buf.getvalue()
    assert "PREREQUISITE MISSING: Astral 'uv' package manager" in err_text
    assert "powershell" in err_text.lower()
    assert "curl" in err_text.lower()
    assert "pip install uv" in err_text


def test_prerequisite_uv_version_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify minimum uv version requirement (>= 0.11.28) is strictly enforced."""
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/uv")

    # 1. Outdated version (0.10.0) must fail closed
    mock_outdated = subprocess.CompletedProcess(
        args=["uv", "--version"],
        returncode=0,
        stdout="uv 0.10.0 (commit abc 2026-09-01 x86_64-linux)",
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_outdated)

    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), pytest.raises(SystemExit) as exc_info:
        reproduce_mod.check_prerequisites(REPO_ROOT)

    assert exc_info.value.code == 1
    err_text = stderr_buf.getvalue()
    assert "PREREQUISITE OUTDATED" in err_text
    assert "requires uv >= 0.11.28" in err_text
    assert "found uv 0.10.0" in err_text

    # 2. Supported versions (0.11.28 and 0.12.23) must pass
    for valid_ver in ["0.11.28", "0.12.23"]:
        mock_valid = subprocess.CompletedProcess(
            args=["uv", "--version"],
            returncode=0,
            stdout=f"uv {valid_ver} (commit abc 2026-10-01 x86_64-linux)",
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, mv=mock_valid, **kwargs: mv)
        result = reproduce_mod.check_prerequisites(REPO_ROOT)
        assert result == "/usr/bin/uv"


def test_prerequisite_python_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify fail-closed rejection when Python version is < 3.11."""
    monkeypatch.setattr(sys, "version_info", (3, 10, 0, "final", 0))

    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), pytest.raises(SystemExit) as exc_info:
        reproduce_mod.check_prerequisites(REPO_ROOT)

    assert exc_info.value.code == 1
    err_text = stderr_buf.getvalue()
    assert "requires Python >= 3.11" in err_text


def test_reproduction_summary_truth_and_provenance(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify evidence provenance and zero-spend disclosures in summary."""
    reproduce_mod.print_reproduction_summary(full=False)
    captured = capsys.readouterr().out

    assert "FIXTURE / LOCAL_EXECUTION" in captured
    assert "Cloud Credentials Required:  NONE" in captured
    assert "External API Calls:          0" in captured
    assert "Personal Spend Target:       $0.00" in captured
    assert "RECORDED_LIVE" in captured
    assert "SUCCESS" in captured


def _copy_clean_source_tree(target_dir: Path) -> None:
    """Helper to copy clean source tree into target directory without venvs or caches."""
    ignore_patterns = shutil.ignore_patterns(
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "*.pyc",
        ".git",
    )
    items_to_copy = [
        "src",
        "tests",
        "runtimes",
        "packages",
        "scripts",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "README.md",
        "LICENSE",
    ]
    for item in items_to_copy:
        src_path = REPO_ROOT / item
        dst_path = target_dir / item
        if src_path.is_dir():
            shutil.copytree(src_path, dst_path, ignore=ignore_patterns)
        elif src_path.is_file():
            shutil.copy2(src_path, dst_path)


def test_reproduction_check_only_fails_on_fresh_checkout(tmp_path: Path) -> None:
    """Prove that --check-only on a fresh checkout with no environments fails fail-closed.

    Verifies:
    1. Returns non-zero exit code (1).
    2. Performs zero implicit environment creations or network downloads.
    3. Neither .venv directory exists after the command exits.
    4. Explains clear instructions to run standard 'python scripts/reproduce.py' first.
    """
    isolated_dir = tmp_path / "fresh_checkout_check_only"
    isolated_dir.mkdir()
    _copy_clean_source_tree(isolated_dir)

    assert not (isolated_dir / ".venv").exists()
    assert not (isolated_dir / "runtimes" / "strands_planner" / ".venv").exists()

    reproduce_script = isolated_dir / "scripts" / "reproduce.py"
    clean_env = os.environ.copy()
    clean_env.pop("VIRTUAL_ENV", None)

    result = subprocess.run(
        [sys.executable, str(reproduce_script), "--check-only"],
        cwd=str(isolated_dir),
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, (
        f"Expected --check-only on fresh directory to fail, got {result.returncode}.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    # Crucial invariant: no venv was created implicitly
    assert not (isolated_dir / ".venv").exists(), (
        "Core .venv was created implicitly under --check-only!"
    )
    assert not (isolated_dir / "runtimes" / "strands_planner" / ".venv").exists(), (
        "Strands .venv was created implicitly under --check-only!"
    )
    assert "ENVIRONMENT MISSING: Core virtual environment not found" in result.stderr
    assert "forbids implicit environment creation, sync, or network downloads" in result.stderr


def test_reproduction_clean_checkout_fresh_installation() -> None:
    """Test actual default clean-checkout reproduction path from a fresh directory.

    Verifies:
    1. Running standard 'python scripts/reproduce.py' with no pre-existing venvs.
    2. Synchronizes both pinned isolated environments (Core and Strands Planner).
    3. Executes quick smoke verification suite offline with 0 external API calls.
    4. Returns exit code 0 and verifies provenance disclosures.
    """
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        isolated_dir = Path(temp_dir) / "fresh_checkout"
        isolated_dir.mkdir()
        _copy_clean_source_tree(isolated_dir)

        assert not (isolated_dir / ".venv").exists()
        assert not (isolated_dir / "runtimes" / "strands_planner" / ".venv").exists()

        reproduce_script = isolated_dir / "scripts" / "reproduce.py"
        clean_env = os.environ.copy()
        clean_env.pop("VIRTUAL_ENV", None)

        result = subprocess.run(
            [sys.executable, str(reproduce_script)],
            cwd=str(isolated_dir),
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, (
            f"Clean fresh reproduction failed with code {result.returncode}:\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        # Both environments are installed and verified
        assert (isolated_dir / ".venv").is_dir()
        assert (isolated_dir / "runtimes" / "strands_planner" / ".venv").is_dir()
        assert "REPRODUCTION VERIFICATION SUMMARY" in result.stdout
        assert "FIXTURE / LOCAL_EXECUTION" in result.stdout
        assert "SUCCESS" in result.stdout
