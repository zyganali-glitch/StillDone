"""Reproducible package smoke test for packages/mcp_verify wheel build and install.

Proves:
1. Builds standard wheel artifact from packages/mcp_verify.
2. Creates isolated temporary virtual environment.
3. Installs built wheel cleanly.
4. Ensures repository source tree is NOT on sys.path.
5. Imports mcp_verify from site-packages.
6. Executes verification contract end-to-end.
7. Exits 0 on verified success, non-zero on failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def smoke_mcp_verify_wheel() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    pkg_dir = root_dir / "packages" / "mcp_verify"

    if not (pkg_dir / "pyproject.toml").exists():
        print(f"ERROR: pyproject.toml not found in {pkg_dir}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        dist_dir = tmp_path / "dist"
        venv_dir = tmp_path / "venv"

        print(f"[1/5] Building wheel from {pkg_dir} into {dist_dir}...")
        # Use uv build --wheel
        uv_exe = shutil.which("uv") or "uv"
        build_res = subprocess.run(
            [uv_exe, "build", "--wheel", str(pkg_dir), "-o", str(dist_dir)],
            capture_output=True,
            text=True,
        )
        if build_res.returncode != 0:
            print(
                f"ERROR: Wheel build failed:\n{build_res.stderr}\n{build_res.stdout}",
                file=sys.stderr,
            )
            sys.exit(build_res.returncode)

        wheels = list(dist_dir.glob("*.whl"))
        if not wheels:
            print("ERROR: No .whl file found in dist directory after build.", file=sys.stderr)
            sys.exit(1)
        built_wheel = wheels[0]
        print(f"Built wheel: {built_wheel.name} ({built_wheel.stat().st_size} bytes)")

        print(f"[2/5] Creating isolated venv at {venv_dir}...")
        venv_res = subprocess.run(
            [uv_exe, "venv", str(venv_dir)],
            capture_output=True,
            text=True,
        )
        if venv_res.returncode != 0:
            print(f"ERROR: venv creation failed:\n{venv_res.stderr}", file=sys.stderr)
            sys.exit(venv_res.returncode)

        venv_python = (
            venv_dir / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else venv_dir / "bin" / "python"
        )
        if not venv_python.exists():
            print(f"ERROR: venv python binary not found at {venv_python}", file=sys.stderr)
            sys.exit(1)

        print(f"[3/5] Installing built wheel {built_wheel.name} into isolated venv...")
        install_res = subprocess.run(
            [uv_exe, "pip", "install", "--python", str(venv_python), str(built_wheel)],
            capture_output=True,
            text=True,
        )
        if install_res.returncode != 0:
            print(f"ERROR: Wheel installation failed:\n{install_res.stderr}", file=sys.stderr)
            sys.exit(install_res.returncode)

        print("[4/5] Executing verification contract probe outside repo source tree...")
        probe_code = (
            "import sys\n"
            "import mcp_verify\n"
            "from mcp_verify import Verifier, VerificationPredicate, PredicateOperator\n"
            "pkg_file = mcp_verify.__file__\n"
            "print(f'Imported mcp_verify from: {pkg_file}')\n"
            "assert 'site-packages' in pkg_file.lower() or 'lib' in pkg_file.lower(), "
            "f'Expected site-packages import, got {pkg_file}'\n"
            "pred = VerificationPredicate(\n"
            "    target_id='smoke_task_1',\n"
            "    attribute='status',\n"
            "    operator=PredicateOperator.EQUALS,\n"
            "    expected_value='VERIFIED_DONE',\n"
            ")\n"
            "res = Verifier.verify_observation(\n"
            "    predicate=pred,\n"
            "    observed_properties={'status': 'VERIFIED_DONE'},\n"
            "    readback_tool_name='get_task',\n"
            ")\n"
            "assert res.is_verified is True, f'Contract failed: {res}'\n"
            "print(f'Contract passed: status={res.status.value}, ok={res.is_verified}')\n"
        )

        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)

        probe_res = subprocess.run(
            [str(venv_python), "-B", "-c", probe_code],
            cwd=str(tmp_path),
            env=clean_env,
            capture_output=True,
            text=True,
        )
        if probe_res.returncode != 0:
            print(
                f"ERROR: Probe execution failed:\n{probe_res.stderr}\n{probe_res.stdout}",
                file=sys.stderr,
            )
            sys.exit(probe_res.returncode)

        print(probe_res.stdout.strip())
        print("[5/5] mcp-verify wheel package smoke check PASSED successfully.")


if __name__ == "__main__":
    smoke_mcp_verify_wheel()
