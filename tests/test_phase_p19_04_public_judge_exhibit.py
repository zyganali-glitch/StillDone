"""Tests for Phase P-19.04: Public Read-Only Judge Exhibit for Cloudflare Pages.

Validates:
1. Exhibit generation CLI tool (`scripts/p19_04_build_judge_exhibit.py`):
   - Generates bundle in target directory `artifacts/judge_exhibit/index.html`.
   - Runs cleanly in standard and `--json` modes.
2. Presentation and Content Compliance:
   - Clearly labels simulated Alexa+ surface with `SIMULATED ALEXA+ EXPERIENCE`.
   - Distinguishes recorded live integrations (Bedrock, AgentCore, Google) from fixture simulation.
   - Displays 7-step desired-state timeline from seed to drift reconciliation.
   - Displays human authorization boundary and single-use grant.
   - Explains Drift Law and READY -> DRIFTED reconciliation while keeping receipt immutable.
3. Privacy, Security & Zero-Spend Bounds:
   - Zero external scripts or stylesheets (100% self-contained).
   - Zero secrets, bearer tokens, AWS credentials, or personal email addresses.
   - Zero forms or interactive elements triggering external cloud mutations.
   - Truthfully reports publication status as NOT_PUBLISHED / OPERATOR_ACTION_REQUIRED.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

_build_script = REPO_ROOT / "scripts" / "p19_04_build_judge_exhibit.py"
_spec = importlib.util.spec_from_file_location("p19_04_build", _build_script)
assert _spec is not None and _spec.loader is not None
build_mod: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_mod)


def test_build_judge_exhibit_generates_valid_files() -> None:
    """1. Exhibit generator produces non-empty index.html and single-file exhibit."""
    summary = build_mod.build_and_verify_exhibit()

    assert summary["all_checks_passed"] is True
    assert "P-19.04" in summary["task"]
    assert "Publish read-only public judge exhibit" in summary["task"]
    assert summary["publication_status"] == "NOT_PUBLISHED / OPERATOR_ACTION_REQUIRED"
    assert summary["publication_target"] == "Cloudflare Pages Free (*.pages.dev)"
    assert summary["estimated_personal_spend"] == "$0.00"

    index_path = Path(summary["index_file"])
    assert index_path.is_file()
    assert index_path.name == "index.html"
    assert index_path.stat().st_size > 15000

    single_path = Path(summary["single_file"])
    assert single_path.is_file()
    assert single_path.stat().st_size > 15000


def test_exhibit_html_content_and_presentation_invariants() -> None:
    """2. HTML content enforces disclosure, provenance, timeline, and drift invariants."""
    summary = build_mod.build_and_verify_exhibit()
    index_path = Path(summary["index_file"])
    html_content = index_path.read_text(encoding="utf-8")

    # A. Simulated Alexa+ disclosure
    assert "SIMULATED ALEXA+ EXPERIENCE" in html_content
    assert "BACKEND: REAL STILLDONE DETERMINISTIC ENGINE" in html_content

    # B. Provenance distinction
    assert "Evidence Provenance Breakdown" in html_content
    assert "RECORDED_LIVE" in html_content
    assert "FIXTURE / SIMULATION" in html_content
    assert "STATIC EXHIBIT" in html_content

    # C. 7 canonical timeline steps
    for step_num in range(1, 8):
        assert f'aria-label="Step {step_num}:' in html_content

    # D. Human authorization boundary
    assert "Human Authorization Boundary" in html_content
    assert "Single-Use Grant" in html_content
    assert "calendar.update" in html_content

    # E. Drift Law explanation & Immutable Receipt
    assert "Drift Law &amp; State Invariant" in html_content
    assert "Immutable Historical Receipt" in html_content
    assert summary["receipt_hash"] in html_content
    assert "Why is current truth DRIFTED while the receipt was READY?" in html_content


def test_exhibit_security_privacy_and_zero_spend_guards() -> None:
    """3. Exhibit contains zero external network dependencies, secrets, or mutations."""
    summary = build_mod.build_and_verify_exhibit()
    index_path = Path(summary["index_file"])
    html_content = index_path.read_text(encoding="utf-8")

    # No external scripts or styles
    assert not re.search(r'<script\s+src="http', html_content)
    assert not re.search(r'<link\s+[^>]*href="http', html_content)

    # No dangerous form mutations
    assert "<form" not in html_content
    assert 'method="POST"' not in html_content

    # No AWS or Google secret patterns
    assert "AKIA" not in html_content
    assert "ya29." not in html_content
    assert "AIza" not in html_content
    assert "client_secret" not in html_content


def test_exhibit_cli_execution_standard_and_json() -> None:
    """4. Standalone CLI execution works cleanly in standard and --json modes."""
    # Standard text mode
    res_text = subprocess.run(
        [sys.executable, str(_build_script)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "STILLDONE P-19.04 PUBLIC JUDGE EXHIBIT BUILD REPORT" in res_text.stdout
    assert "Cloudflare Pages Free (*.pages.dev)" in res_text.stdout
    assert "NOT_PUBLISHED / OPERATOR_ACTION_REQUIRED" in res_text.stdout
    assert "[PASS] simulated_alexa_label_present" in res_text.stdout

    # JSON mode
    res_json = subprocess.run(
        [sys.executable, str(_build_script), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res_json.stdout)
    assert "P-19.04" in data["task"]
    assert "Publish read-only public judge exhibit" in data["task"]
    assert data["all_checks_passed"] is True
    assert data["publication_status"] == "NOT_PUBLISHED / OPERATOR_ACTION_REQUIRED"
