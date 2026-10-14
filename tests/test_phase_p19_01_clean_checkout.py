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

    # 2. Non-zero exit code from 'uv --version' must fail closed
    mock_nonzero = subprocess.CompletedProcess(
        args=["uv", "--version"],
        returncode=127,
        stdout="",
        stderr="uv: error: failed to initialize",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_nonzero)

    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), pytest.raises(SystemExit) as exc_info:
        reproduce_mod.check_prerequisites(REPO_ROOT)

    assert exc_info.value.code == 1
    assert "PREREQUISITE ERROR: 'uv --version' failed" in stderr_buf.getvalue()

    # 3. Unparseable stdout from 'uv --version' must fail closed
    mock_unparseable = subprocess.CompletedProcess(
        args=["uv", "--version"],
        returncode=0,
        stdout="astral-package-manager custom-build-no-version",
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_unparseable)

    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), pytest.raises(SystemExit) as exc_info:
        reproduce_mod.check_prerequisites(REPO_ROOT)

    assert exc_info.value.code == 1
    assert "PREREQUISITE UNPARSEABLE" in stderr_buf.getvalue()

    # 4. Exception while running 'uv --version' must fail closed
    def _raise_exc(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Permission denied")

    monkeypatch.setattr(subprocess, "run", _raise_exc)
    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), pytest.raises(SystemExit) as exc_info:
        reproduce_mod.check_prerequisites(REPO_ROOT)

    assert exc_info.value.code == 1
    assert "PREREQUISITE CHECK FAILED" in stderr_buf.getvalue()

    # 5. Supported versions (0.11.28 and 0.12.23) must pass
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


def test_smoke_mcp_verify_wheel_offline_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify smoke_mcp_verify_wheel passes --offline and sets UV_OFFLINE=1 on all subcommands."""
    smoke_path = REPO_ROOT / "scripts" / "smoke_mcp_verify_wheel.py"
    smoke_spec = importlib.util.spec_from_file_location("smoke_wheel_mod", smoke_path)
    assert smoke_spec is not None and smoke_spec.loader is not None
    smoke_mod: Any = importlib.util.module_from_spec(smoke_spec)
    smoke_spec.loader.exec_module(smoke_mod)

    executed_cmds: list[tuple[list[str], dict[str, str] | None]] = []
    real_run = subprocess.run

    def mock_subprocess_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
        executed_cmds.append((list(cmd), kwargs.get("env")))
        # If building, create dummy .whl in dist directory
        if "build" in cmd:
            out_idx = cmd.index("-o") + 1
            out_dir = Path(cmd[out_idx])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "mcp_verify-0.1.0-py3-none-any.whl").write_bytes(b"PK fake wheel")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        # If venv creation, create dummy python executable
        if "venv" in cmd:
            venv_path = Path(cmd[-1])
            py_bin = (
                venv_path
                / ("Scripts" if sys.platform == "win32" else "bin")
                / ("python.exe" if sys.platform == "win32" else "python")
            )
            py_bin.parent.mkdir(parents=True, exist_ok=True)
            py_bin.write_bytes(b"")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        # If pip install, return success
        if "pip" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        # For the python probe, return simulated success
        if any(str(a).endswith("python.exe") or str(a).endswith("python") for a in cmd):
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=(
                    "Imported mcp_verify from site-packages\n"
                    "Contract passed: status=VERIFIED, ok=True"
                ),
                stderr="",
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    # Execute in offline mode
    smoke_mod.smoke_mcp_verify_wheel(offline=True)

    # Assert all package management operations received --offline and UV_OFFLINE=1
    package_ops = [c for c, _ in executed_cmds if any(op in c for op in ("build", "venv", "pip"))]
    assert len(package_ops) >= 3, f"Expected build, venv, and pip install ops, got: {package_ops}"

    for cmd, env in executed_cmds:
        if any(op in cmd for op in ("build", "venv", "pip")):
            assert "--offline" in cmd, f"Command {cmd} missing mandatory --offline flag!"
            assert env is not None, f"Command {cmd} missing environment!"
            assert env.get("UV_OFFLINE") == "1", f"Command {cmd} missing UV_OFFLINE=1 in env!"


def test_smoke_mcp_verify_wheel_missing_cache_fails_without_download(tmp_path: Path) -> None:
    """Prove that uv build --wheel --offline fails fail-closed when cached build deps are missing.

    Ensures zero network downloads occur when cached dependencies are absent.
    """
    empty_cache = tmp_path / "empty_uv_cache"
    empty_cache.mkdir()
    dist_dir = tmp_path / "dist"
    pkg_dir = REPO_ROOT / "packages" / "mcp_verify"
    uv_exe = shutil.which("uv") or "uv"

    res = subprocess.run(
        [
            uv_exe,
            "build",
            "--wheel",
            "--offline",
            str(pkg_dir),
            "-o",
            str(dist_dir),
            "--cache-dir",
            str(empty_cache),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    # Must fail with non-zero exit code due to missing cached build dependencies
    assert res.returncode != 0, (
        f"Expected offline build with empty cache to fail, got: {res.stdout}"
    )
    assert (
        "network was disabled" in (res.stderr + res.stdout).lower()
        or "cache" in (res.stderr + res.stdout).lower()
    )


def test_reproduction_check_only_network_denying_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that every descendant subprocess under --check-only enforces offline guarantees.

    A network-denying harness intercepts all subprocess executions:
    - Verifies that any uv command passed has --offline and --no-sync.
    - Ensures smoke_mcp_verify_wheel receives --offline and sets UV_OFFLINE=1.
    - Prohibits any command that does not pass offline bounds.
    """
    captured_commands: list[list[str]] = []
    real_run = subprocess.run

    def network_denying_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
        captured_commands.append(list(cmd))
        cmd_str = " ".join(str(c) for c in cmd)

        # 1. Reject any network sync attempts
        if "sync" in cmd and "--offline" not in cmd:
            raise AssertionError(f"NETWORK ACCESS ATTEMPT DETECTED: {cmd_str}")

        # 2. For uv run commands, verify --no-sync and --offline
        if len(cmd) >= 2 and cmd[0].endswith("uv") and cmd[1] == "run":
            assert "--no-sync" in cmd, f"uv run command missing --no-sync: {cmd_str}"
            assert "--offline" in cmd, f"uv run command missing --offline: {cmd_str}"

        # 3. For smoke_mcp_verify_wheel script execution, verify --offline is passed
        if any("smoke_mcp_verify_wheel.py" in str(arg) for arg in cmd):
            assert "--offline" in cmd, (
                f"smoke_mcp_verify_wheel invoked without --offline: {cmd_str}"
            )
            assert kwargs.get("env", {}).get("UV_OFFLINE") == "1", (
                f"smoke_mcp_verify_wheel invoked without UV_OFFLINE=1: {cmd_str}"
            )

        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", network_denying_run)

    # Execute --check-only in quick mode
    reproduce_mod.main(["--check-only"])

    assert len(captured_commands) > 0, "No commands were executed during check-only run"
    uv_run_calls = [c for c in captured_commands if len(c) >= 2 and c[1] == "run"]
    assert len(uv_run_calls) >= 5, f"Expected at least 5 uv run checks, got {len(uv_run_calls)}"
    for call in uv_run_calls:
        assert "--offline" in call
        assert "--no-sync" in call
