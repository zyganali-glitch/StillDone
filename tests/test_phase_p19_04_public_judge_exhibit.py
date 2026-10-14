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

import copy
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


def test_adversarial_readback_promotion_prevention() -> None:
    """5. Proves planning, approval pauses, and receipts are NOT marked read-back verified."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()
    vm = build_judge_view_model(outcome)

    steps_by_id = {s.task_id: s for s in vm.timeline_steps}

    # Step 2: Planning & Weather observation (0 writes) -> MUST NOT be read-back verified
    step2 = steps_by_id["P-13.02"]
    assert step2.independent_readback_verified is False
    assert step2.readback_status == "NOT_APPLICABLE"

    # Step 4: Approval pause (0 writes, fail-closed pause) -> MUST NOT be read-back verified
    step4 = steps_by_id["P-13.04"]
    assert step4.independent_readback_verified is False
    assert step4.readback_status == "NOT_APPLICABLE"

    # Step 6: Receipt issuance (internal state evaluation) -> MUST NOT be read-back verified
    step6 = steps_by_id["P-13.06"]
    assert step6.independent_readback_verified is False
    assert step6.readback_status == "NOT_APPLICABLE"

    # Steps with authentic read-backs must be truthfully preserved
    assert steps_by_id["P-13.01"].independent_readback_verified is True
    assert steps_by_id["P-13.01"].readback_status == "VERIFIED"

    assert steps_by_id["P-13.03"].independent_readback_verified is True
    assert steps_by_id["P-13.03"].readback_status == "VERIFIED"

    assert steps_by_id["P-13.05"].independent_readback_verified is True
    assert steps_by_id["P-13.05"].readback_status == "VERIFIED"

    assert steps_by_id["P-13.07"].independent_readback_verified is True
    assert steps_by_id["P-13.07"].readback_status == "DRIFT_DETECTED"


def test_approval_fingerprint_is_derived_and_not_decorative_constant() -> None:
    """6. Proves approval fingerprint is derived from authentic outcome facts."""
    from stilldone.domain.mission import MissionId
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()
    vm1 = build_judge_view_model(outcome)

    assert vm1.approval_card is not None
    fp1 = vm1.approval_card.fingerprint
    assert fp1.startswith("sha256:")
    assert len(fp1) == 71  # "sha256:" + 64 hex characters

    # Create modified outcome with distinct mission ID
    modified_outcome = copy.deepcopy(outcome)
    object.__setattr__(modified_outcome, "mission_id", MissionId.generate())
    vm2 = build_judge_view_model(modified_outcome)

    assert vm2.approval_card is not None
    fp2 = vm2.approval_card.fingerprint

    # Proves the fingerprint is dynamically derived from outcome identity, not hardcoded
    assert fp1 != fp2, "Fingerprint must not be a decorative static constant across missions"


def test_wcag_aa_contrast_real_calculation() -> None:
    """7. Proves WCAG AA contrast check executes mathematical verification."""
    summary = build_mod.build_and_verify_exhibit()
    index_path = Path(summary["index_file"])
    html_content = index_path.read_text(encoding="utf-8")

    # Real calculation returns True on rendered valid CSS
    assert build_mod.verify_wcag_aa_contrast(html_content) is True

    # Hostile low-contrast CSS fails
    hostile_css = (
        ":root { --bg-primary: #111111; --bg-card: #222222; "
        "--text-primary: #333333; --text-secondary: #444444; "
        "--color-ready: #555555; --color-drifted: #666666; }"
    )
    assert build_mod.verify_wcag_aa_contrast(hostile_css) is False
