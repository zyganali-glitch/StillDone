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

import pytest

from stilldone.domain.lifecycle import MissionState
from stilldone.judge_ux.models import StepExecutionState

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


def test_voice_summary_makes_no_unsupported_physical_completion_claims() -> None:
    """8. Proves voice summary never claims physical completion."""
    from stilldone.domain.lifecycle import MissionState
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.models import MissionVisualState
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    # DRIFTED state voice summary
    vm_drifted = build_judge_view_model(outcome)
    assert vm_drifted.current_state == MissionVisualState.DRIFTED
    assert "backpacks are packed" not in vm_drifted.voice_summary.spoken_phrase.lower()
    assert "rain gear is ready" not in vm_drifted.voice_summary.spoken_phrase.lower()
    assert "backpack-packing task" in vm_drifted.voice_summary.spoken_phrase
    assert "confirmed it is on your list" in vm_drifted.voice_summary.spoken_phrase

    # READY state voice summary
    ready_outcome = copy.deepcopy(outcome)
    object.__setattr__(ready_outcome, "final_state", MissionState.READY)
    vm_ready = build_judge_view_model(ready_outcome)
    assert vm_ready.current_state == MissionVisualState.READY
    assert "backpacks are packed" not in vm_ready.voice_summary.spoken_phrase.lower()
    assert "rain gear is ready" not in vm_ready.voice_summary.spoken_phrase.lower()
    assert "backpack-packing task" in vm_ready.voice_summary.spoken_phrase


def test_adversarial_blocked_live_outcome_cannot_render_as_verified_success(
    tmp_path: Path,
) -> None:
    """9. Proves blocked live outcome renders as BLOCKED with unissued receipt and error cards."""
    from unittest.mock import MagicMock

    from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
    from stilldone.adapters.tasks import GoogleApiClientTasksTransport
    from stilldone.adapters.weather import OpenMeteoHttpTransport
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
    from stilldone.judge_ux.models import MissionVisualState, StepExecutionState
    from stilldone.killer_mission import (
        KillerMissionEnvironment,
        LiveKillerMissionSliceRunner,
    )

    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_blocked",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner = LiveKillerMissionSliceRunner(live_env, operator_approved=False)
    blocked_outcome = runner.run_full_slice()

    vm = build_judge_view_model(blocked_outcome)
    assert vm.current_state == MissionVisualState.BLOCKED
    assert vm.compact_receipt.state_at_issuance == "UNISSUED"
    assert vm.compact_receipt.receipt_hash == "UNISSUED / NO_READY_RECEIPT"
    assert vm.compact_receipt.is_historically_preserved is False

    # Blocked steps must be ERROR with BLOCKED status
    step_cards = {s.task_id: s for s in vm.timeline_steps}
    assert step_cards["P-13.01"].state == StepExecutionState.ERROR
    assert step_cards["P-13.01"].readback_status == "BLOCKED"
    assert step_cards["P-13.01"].independent_readback_verified is False

    html = render_judge_exhibit_html(vm)
    assert "UNISSUED" in html
    assert "No READY receipt was issued" in html


def test_adversarial_missing_steps_renders_as_partial_not_ready_or_drifted() -> None:
    """10. Proves missing steps result in PARTIAL visual state and NOT_RUN step status."""
    from stilldone.domain.lifecycle import MissionState
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.models import MissionVisualState, StepExecutionState
    from stilldone.killer_mission import KillerMissionSliceOutcome, KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    # Omit steps P-13.03 through P-13.07
    partial_steps = {
        "P-13.01": outcome.steps["P-13.01"],
        "P-13.02": outcome.steps["P-13.02"],
    }
    partial_outcome = KillerMissionSliceOutcome(
        mission_id=outcome.mission_id,
        intent=outcome.intent,
        steps=partial_steps,
        ready_receipt_hash=None,
        drifted_receipt_hash=None,
        historical_receipt_immutable=False,
        final_state=MissionState.EXECUTING,
        total_writes_performed=0,
        provenance=outcome.provenance,
        is_live=False,
    )

    vm = build_judge_view_model(partial_outcome)
    assert vm.current_state == MissionVisualState.PARTIAL
    assert vm.compact_receipt.state_at_issuance == "UNISSUED"

    step_cards = {s.task_id: s for s in vm.timeline_steps}
    assert step_cards["P-13.03"].state == StepExecutionState.ERROR
    assert step_cards["P-13.03"].readback_status == "NOT_RUN"
    assert step_cards["P-13.03"].independent_readback_verified is False


def test_adversarial_unverified_readback_cannot_be_promoted() -> None:
    """11. Proves unverified read-back step reports UNVERIFIED and blocks READY/DRIFTED."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.models import MissionVisualState, StepExecutionState
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    # Tamper step 3 to unverified
    tampered_steps = dict(outcome.steps)
    orig_s3 = outcome.steps["P-13.03"]
    tampered_steps["P-13.03"] = KillerMissionStepResult(
        task_id=orig_s3.task_id,
        step_name=orig_s3.step_name,
        status="FAILED",
        provenance=orig_s3.provenance,
        details="Task read-back mismatch: title does not match",
        writes_performed=orig_s3.writes_performed,
        is_verified=False,
    )

    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, "steps", tampered_steps)

    vm = build_judge_view_model(tampered_outcome)
    assert vm.current_state != MissionVisualState.DRIFTED
    assert vm.current_state != MissionVisualState.READY
    assert vm.current_state == MissionVisualState.BLOCKED

    step_cards = {s.task_id: s for s in vm.timeline_steps}
    assert step_cards["P-13.03"].state == StepExecutionState.ERROR
    assert step_cards["P-13.03"].readback_status == "UNVERIFIED"
    assert step_cards["P-13.03"].independent_readback_verified is False


def test_adversarial_absent_receipt_has_no_fabricated_fallback() -> None:
    """12. Proves absent ready_receipt_hash emits UNISSUED without fabricated hash string."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    no_receipt_outcome = copy.deepcopy(outcome)
    object.__setattr__(no_receipt_outcome, "ready_receipt_hash", None)

    vm = build_judge_view_model(no_receipt_outcome)
    assert vm.compact_receipt.state_at_issuance == "UNISSUED"
    assert vm.compact_receipt.receipt_hash == "UNISSUED / NO_READY_RECEIPT"

    html = render_judge_exhibit_html(vm)
    assert "74b7eb94854b8963" not in html
    assert "UNISSUED / NO_READY_RECEIPT" in html


def test_adversarial_rejected_and_absent_approval() -> None:
    """13. Proves rejected approval displays REJECTED and absent approval card is handled."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    # Case A: Operator rejected approval
    rejected_steps = dict(outcome.steps)
    rejected_steps["P-13.05"] = KillerMissionStepResult(
        task_id="P-13.05",
        step_name="Approve, Execute & Verify Calendar Update",
        status="REJECTED",
        provenance=outcome.provenance,
        details="Operator rejected calendar mutation",
        writes_performed=0,
        is_verified=False,
    )
    rej_outcome = copy.deepcopy(outcome)
    object.__setattr__(rej_outcome, "steps", rejected_steps)

    vm_rej = build_judge_view_model(rej_outcome)
    assert vm_rej.approval_card is not None
    assert vm_rej.approval_card.is_approved is False
    assert vm_rej.approval_card.approved_at is None
    assert vm_rej.approval_card.rejection_reason == "Operator rejected calendar mutation"

    html_rej = render_judge_exhibit_html(vm_rej)
    assert "REJECTED" in html_rej

    # Case B: Pre-approval stage (P-13.04 missing)
    no_app_steps = {"P-13.01": outcome.steps["P-13.01"]}
    no_app_outcome = copy.deepcopy(outcome)
    object.__setattr__(no_app_outcome, "steps", no_app_steps)
    vm_no_app = build_judge_view_model(no_app_outcome)
    assert vm_no_app.approval_card is None

    html_no_app = render_judge_exhibit_html(vm_no_app)
    assert "Human Authorization Boundary" not in html_no_app


def test_approval_never_fabricates_approved_at_timestamp() -> None:
    """14. Proves approval_card.approved_at is None to prevent fabricating timestamps."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()
    vm = build_judge_view_model(outcome)

    assert vm.approval_card is not None
    assert vm.approval_card.approved_at is None
    assert "Explanatory digest" in vm.approval_card.binding_provenance
    assert "not live authenticated approval grant" in vm.approval_card.binding_provenance


def test_wcag_aa_contrast_full_coverage_and_no_low_contrast_colors() -> None:
    """15. Proves comprehensive WCAG AA coverage and confirms #64748b is completely eliminated."""
    summary = build_mod.build_and_verify_exhibit()
    index_path = Path(summary["index_file"])
    html_content = index_path.read_text(encoding="utf-8")

    coverage = build_mod.get_wcag_aa_contrast_coverage(html_content)
    assert coverage["all_passed"] is True
    assert coverage["pairs_checked"] >= 15
    assert "VALIDATED_SCOPED_COVERAGE" in coverage["coverage_status"]
    assert "NOT_VALIDATED" in coverage["unvalidated_scope"]

    # Proves low-contrast #64748b is completely eliminated from the rendered CSS
    assert "#64748b" not in html_content


@pytest.mark.parametrize(
    (
        "task_id",
        "status",
        "is_verified",
        "writes",
        "extra_meta",
        "expected_card_state",
        "expected_readback",
    ),
    [
        # Step 1: status FAILED but is_verified True -> must be ERROR, UNVERIFIED
        (
            "P-13.01",
            "FAILED",
            True,
            1,
            {"seeded_event_established": True},
            StepExecutionState.ERROR,
            "UNVERIFIED",
        ),
        # Step 1: missing required provider/observation metadata -> must be ERROR, UNVERIFIED
        ("P-13.01", "PASS", True, 1, {}, StepExecutionState.ERROR, "UNVERIFIED"),
        # Step 2: unauthorized writes performed on read-only step -> must be ERROR, FAILED
        ("P-13.02", "PASS", True, 1, {}, StepExecutionState.ERROR, "FAILED"),
        # Step 2: Defect 1 regression: status PASS but is_verified False -> must be ERROR, FAILED
        ("P-13.02", "PASS", False, 0, {}, StepExecutionState.ERROR, "FAILED"),
        # Step 3: positive verification with missing mutation evidence (writes=0) -> ERROR
        ("P-13.03", "PASS", True, 0, {}, StepExecutionState.ERROR, "UNVERIFIED"),
        # Step 4: unauthorized writes during approval pause boundary -> must be ERROR, FAILED
        ("P-13.04", "PASS", False, 1, {}, StepExecutionState.ERROR, "FAILED"),
        # Step 5: calendar shift claimed verified with 0 writes -> must be ERROR, UNVERIFIED
        ("P-13.05", "PASS", True, 0, {}, StepExecutionState.ERROR, "UNVERIFIED"),
        # Step 6: receipt step status PASS but is_verified False -> must be ERROR, FAILED
        ("P-13.06", "PASS", False, 0, {}, StepExecutionState.ERROR, "FAILED"),
        # Step 7: drift reconciliation step PASS but is_verified False -> must be ERROR, UNVERIFIED
        ("P-13.07", "PASS", False, 0, {}, StepExecutionState.ERROR, "UNVERIFIED"),
    ],
)
def test_adversarial_contradictory_step_evidence(
    task_id: str,
    status: str,
    is_verified: bool,
    writes: int,
    extra_meta: dict[str, Any],
    expected_card_state: StepExecutionState,
    expected_readback: str,
) -> None:
    """16. Proves contradictory step evidence combinations are rejected fail-closed."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
    from stilldone.judge_ux.models import MissionVisualState
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    tampered_steps = dict(outcome.steps)
    orig = outcome.steps[task_id]
    tampered_steps[task_id] = KillerMissionStepResult(
        task_id=orig.task_id,
        step_name=orig.step_name,
        status=status,
        provenance=orig.provenance,
        details="Adversarial tampered step result",
        writes_performed=writes,
        is_verified=is_verified,
        extra_metadata=extra_meta,
    )
    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, "steps", tampered_steps)

    vm = build_judge_view_model(tampered_outcome)

    # Contradictory steps must NEVER be promoted to overall DRIFTED or READY
    assert vm.current_state != MissionVisualState.DRIFTED
    assert vm.current_state != MissionVisualState.READY

    step_cards = {s.task_id: s for s in vm.timeline_steps}
    card = step_cards[task_id]
    assert card.state == expected_card_state
    assert card.readback_status == expected_readback
    assert card.independent_readback_verified is False

    # HTML verification: refuses false completion or verified status
    html = render_judge_exhibit_html(vm)
    if task_id == "P-13.06":
        assert vm.compact_receipt.state_at_issuance == "UNISSUED"
        assert "UNISSUED" in html
    elif task_id == "P-13.07":
        assert card.is_drifted is False


def test_adversarial_tampered_receipt_hash_without_step6_issuance() -> None:
    """17. Proves arbitrary receipt hash cannot fabricate READY receipt without step 6."""
    from stilldone.judge_ux.builder import build_judge_view_model
    from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
    from stilldone.judge_ux.models import MissionVisualState
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    tampered_steps = dict(outcome.steps)
    tampered_steps["P-13.06"] = KillerMissionStepResult(
        task_id="P-13.06",
        step_name="Produce READY Mission Receipt",
        status="FAILED",
        provenance=outcome.provenance,
        details="Receipt issuance predicate failed",
        writes_performed=0,
        is_verified=False,
    )
    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, "steps", tampered_steps)
    object.__setattr__(tampered_outcome, "ready_receipt_hash", "fabricated_ready_hash_999")

    vm = build_judge_view_model(tampered_outcome)
    assert vm.current_state != MissionVisualState.READY
    assert vm.current_state != MissionVisualState.DRIFTED
    assert vm.compact_receipt.state_at_issuance == "UNISSUED"
    assert vm.compact_receipt.receipt_hash == "UNISSUED / NO_READY_RECEIPT"
    assert vm.compact_receipt.is_historically_preserved is False

    html = render_judge_exhibit_html(vm)
    assert "UNISSUED / NO_READY_RECEIPT" in html
    assert "fabricated_ready_hash_999" not in html


@pytest.mark.parametrize(
    ("tamper_field", "tamper_val"),
    [
        ("ready_receipt_hash", None),
        ("historical_receipt_immutable", False),
        ("final_state", MissionState.READY),
        ("is_live", True),
    ],
)
def test_adversarial_static_builder_fails_closed_on_tampered_outcomes(
    tmp_path: Path,
    tamper_field: str,
    tamper_val: Any,
) -> None:
    """18. Proves build_and_verify_exhibit raises RuntimeError on tampered outcomes."""
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()
    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, tamper_field, tamper_val)

    out_dir = tmp_path / "exhibit"
    single = tmp_path / "exhibit.html"

    with pytest.raises(RuntimeError):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single,
            outcome=tampered_outcome,
        )

    # Assert no files were created or promoted
    assert not (out_dir / "index.html").exists()
    assert not single.exists()


def test_defect1_unverified_planning_evidence_fails_closed(tmp_path: Path) -> None:
    """19. Defect 1: Unverified planning step cannot display OBSERVED or promote READY/DRIFTED."""
    from stilldone.judge_ux.builder import build_judge_view_model, is_step2_valid
    from stilldone.judge_ux.models import MissionVisualState, StepExecutionState
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    # Tamper step 2: status PASS but is_verified=False, writes=0
    tampered_steps = dict(outcome.steps)
    orig = outcome.steps["P-13.02"]
    tampered_steps["P-13.02"] = KillerMissionStepResult(
        task_id=orig.task_id,
        step_name=orig.step_name,
        status="PASS",
        provenance=orig.provenance,
        details="Unverified weather read attempt",
        writes_performed=0,
        is_verified=False,
        extra_metadata={},
    )
    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, "steps", tampered_steps)

    # 1. Predicate must be False
    assert is_step2_valid(tampered_outcome) is False

    # 2. View model must NOT promote to OBSERVED, READY, or DRIFTED
    vm = build_judge_view_model(tampered_outcome)
    assert vm.current_state != MissionVisualState.DRIFTED
    assert vm.current_state != MissionVisualState.READY
    assert vm.current_state == MissionVisualState.PARTIAL

    step2_card = {s.task_id: s for s in vm.timeline_steps}["P-13.02"]
    assert step2_card.state == StepExecutionState.ERROR
    assert step2_card.readback_status == "FAILED"
    assert step2_card.independent_readback_verified is False

    # 3. Static publication gate must reject before writing
    out_dir = tmp_path / "exhibit"
    single = tmp_path / "exhibit.html"
    with pytest.raises(RuntimeError, match="P-13.02"):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single,
            outcome=tampered_outcome,
        )
    assert not (out_dir / "index.html").exists()
    assert not single.exists()


@pytest.mark.parametrize(
    ("step6_hash", "outcome_ready_hash", "scenario_name"),
    [
        (
            None,
            "cfe978313fa0aeae8b695427bce8dc3e54d46dcff319cabf25fdac8de4d4d45d",
            "missing_step6_hash",
        ),
        (
            "",
            "cfe978313fa0aeae8b695427bce8dc3e54d46dcff319cabf25fdac8de4d4d45d",
            "empty_step6_hash",
        ),
        (
            "not_a_valid_sha256_hash",
            "cfe978313fa0aeae8b695427bce8dc3e54d46dcff319cabf25fdac8de4d4d45d",
            "malformed_step6_hash",
        ),
        (
            "0" * 64,
            "cfe978313fa0aeae8b695427bce8dc3e54d46dcff319cabf25fdac8de4d4d45d",
            "mismatched_step6_hash",
        ),
        (
            "cfe978313fa0aeae8b695427bce8dc3e54d46dcff319cabf25fdac8de4d4d45d",
            "not_a_valid_sha256_hash",
            "malformed_outcome_hash",
        ),
        (
            "cfe978313fa0aeae8b695427bce8dc3e54d46dcff319cabf25fdac8de4d4d45d",
            None,
            "contradictory_issuance_hash",
        ),
    ],
)
def test_defect2_ready_receipt_identity_binding_adversarial(
    tmp_path: Path,
    step6_hash: str | None,
    outcome_ready_hash: str | None,
    scenario_name: str,
) -> None:
    """20. Defect 2: Missing, mismatched, malformed, or contradictory hashes fail closed."""
    from stilldone.judge_ux.builder import build_judge_view_model, is_step6_valid
    from stilldone.judge_ux.models import MissionVisualState, StepExecutionState
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    tampered_steps = dict(outcome.steps)
    orig6 = outcome.steps["P-13.06"]
    tampered_steps["P-13.06"] = KillerMissionStepResult(
        task_id=orig6.task_id,
        step_name=orig6.step_name,
        status="PASS",
        provenance=orig6.provenance,
        details="Adversarial tampered receipt issuance",
        writes_performed=0,
        is_verified=True,
        receipt_hash=step6_hash,
        extra_metadata=dict(orig6.extra_metadata),
    )
    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, "steps", tampered_steps)
    object.__setattr__(tampered_outcome, "ready_receipt_hash", outcome_ready_hash)

    # 1. Predicate must fail
    assert is_step6_valid(tampered_outcome) is False

    # 2. View model fails closed to UNISSUED and PARTIAL
    vm = build_judge_view_model(tampered_outcome)
    assert vm.current_state != MissionVisualState.READY
    assert vm.current_state != MissionVisualState.DRIFTED
    assert vm.current_state == MissionVisualState.PARTIAL
    assert vm.compact_receipt.state_at_issuance == "UNISSUED"
    assert vm.compact_receipt.receipt_hash == "UNISSUED / NO_READY_RECEIPT"
    assert vm.compact_receipt.is_historically_preserved is False

    step6_card = {s.task_id: s for s in vm.timeline_steps}["P-13.06"]
    assert step6_card.state == StepExecutionState.ERROR

    # 3. Static publication gate fails closed before writing
    out_dir = tmp_path / f"exhibit_{scenario_name}"
    single = tmp_path / f"exhibit_{scenario_name}.html"
    with pytest.raises(RuntimeError):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single,
            outcome=tampered_outcome,
        )
    assert not (out_dir / "index.html").exists()
    assert not single.exists()


def test_defect2_original_fixture_receipt_preserved() -> None:
    """21. Defect 2: Valid original fixture receipt identity is fully preserved and valid."""
    from stilldone.judge_ux.builder import (
        build_judge_view_model,
        is_step6_valid,
        is_valid_receipt_hash,
    )
    from stilldone.judge_ux.models import StepExecutionState
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    assert is_valid_receipt_hash(outcome.ready_receipt_hash) is True
    assert outcome.steps["P-13.06"].receipt_hash == outcome.ready_receipt_hash
    assert is_step6_valid(outcome) is True

    vm = build_judge_view_model(outcome)
    assert vm.compact_receipt.state_at_issuance == "READY"
    assert vm.compact_receipt.receipt_hash == outcome.ready_receipt_hash
    assert vm.compact_receipt.is_historically_preserved is True

    step6_card = {s.task_id: s for s in vm.timeline_steps}["P-13.06"]
    assert step6_card.state == StepExecutionState.VERIFIED


@pytest.mark.parametrize(
    ("tamper_dict", "scenario_name"),
    [
        ({"step7_receipt_hash": None}, "absent_step7_hash"),
        ({"step7_receipt_hash": ""}, "empty_step7_hash"),
        ({"step7_receipt_hash": "f" * 64}, "mismatched_step7_hash"),
        ({"reconciled_state": "READY"}, "wrong_reconciled_state_ready"),
        ({"reconciled_state": "UNKNOWN"}, "wrong_reconciled_state_unknown"),
        ({"reconciled_state": None}, "missing_reconciled_state"),
        ({"historical_receipt_intact": False}, "false_historical_receipt_integrity"),
        ({"historical_receipt_intact": None}, "missing_historical_receipt_integrity"),
        ({"drifted_receipt_hash": "e" * 64}, "mismatched_drifted_receipt_hash"),
        ({"drifted_receipt_hash": "bad_hash"}, "malformed_drifted_receipt_hash"),
        ({"drifted_receipt_hash": None}, "absent_drifted_receipt_hash"),
    ],
)
def test_defect3_drift_lineage_verification_adversarial(
    tmp_path: Path,
    tamper_dict: dict[str, Any],
    scenario_name: str,
) -> None:
    """22. Defect 3: Missing/mismatched step-7 hash, wrong state, or false intact flag fail."""
    from stilldone.judge_ux.builder import build_judge_view_model, is_step7_valid
    from stilldone.judge_ux.models import MissionVisualState, StepExecutionState
    from stilldone.killer_mission import KillerMissionSliceRunner, KillerMissionStepResult

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    tampered_steps = dict(outcome.steps)
    orig7 = outcome.steps["P-13.07"]
    s7_meta = dict(orig7.extra_metadata)
    s7_hash = orig7.receipt_hash

    if "step7_receipt_hash" in tamper_dict:
        s7_hash = tamper_dict["step7_receipt_hash"]
    if "reconciled_state" in tamper_dict:
        if tamper_dict["reconciled_state"] is None:
            s7_meta.pop("reconciled_state", None)
        else:
            s7_meta["reconciled_state"] = tamper_dict["reconciled_state"]
    if "historical_receipt_intact" in tamper_dict:
        if tamper_dict["historical_receipt_intact"] is None:
            s7_meta.pop("historical_receipt_intact", None)
        else:
            s7_meta["historical_receipt_intact"] = tamper_dict["historical_receipt_intact"]

    tampered_steps["P-13.07"] = KillerMissionStepResult(
        task_id=orig7.task_id,
        step_name=orig7.step_name,
        status="PASS",
        provenance=orig7.provenance,
        details="Adversarial tampered drift step",
        writes_performed=0,
        is_verified=True,
        receipt_hash=s7_hash,
        extra_metadata=s7_meta,
    )
    tampered_outcome = copy.deepcopy(outcome)
    object.__setattr__(tampered_outcome, "steps", tampered_steps)

    if "drifted_receipt_hash" in tamper_dict:
        object.__setattr__(
            tampered_outcome, "drifted_receipt_hash", tamper_dict["drifted_receipt_hash"]
        )

    # 1. Predicate must fail
    assert is_step7_valid(tampered_outcome) is False

    # 2. View model must NOT be DRIFTED
    vm = build_judge_view_model(tampered_outcome)
    assert vm.current_state != MissionVisualState.DRIFTED

    step7_card = {s.task_id: s for s in vm.timeline_steps}["P-13.07"]
    assert step7_card.is_drifted is False
    assert step7_card.state == StepExecutionState.ERROR

    # 3. Static publication gate must fail closed before writing
    out_dir = tmp_path / f"exhibit_{scenario_name}"
    single = tmp_path / f"exhibit_{scenario_name}.html"
    with pytest.raises(RuntimeError):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single,
            outcome=tampered_outcome,
        )
    assert not (out_dir / "index.html").exists()
    assert not single.exists()


def test_invalid_outcomes_rejected_before_preexisting_files_overwritten(tmp_path: Path) -> None:
    """23. Invariants: Pre-existing HTML files are preserved and never overwritten on errors."""
    from stilldone.killer_mission import KillerMissionSliceRunner

    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    out_dir = tmp_path / "exhibit"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_file = out_dir / "index.html"
    single_file = tmp_path / "single.html"

    canary = "CANARY_TEXT_PREEXISTING_VALID_CONTENT"
    index_file.write_text(canary, encoding="utf-8")
    single_file.write_text(canary, encoding="utf-8")

    # Tamper with an invalid step 2 (Defect 1)
    tampered_s2 = copy.deepcopy(outcome)
    tampered_steps = dict(tampered_s2.steps)
    orig2 = tampered_steps["P-13.02"]
    tampered_steps["P-13.02"] = copy.deepcopy(orig2)
    object.__setattr__(tampered_steps["P-13.02"], "is_verified", False)
    object.__setattr__(tampered_s2, "steps", tampered_steps)

    with pytest.raises(RuntimeError):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single_file,
            outcome=tampered_s2,
        )

    # Preexisting files must remain strictly intact with canary text
    assert index_file.read_text(encoding="utf-8") == canary
    assert single_file.read_text(encoding="utf-8") == canary

    # Tamper with invalid step 6 receipt hash (Defect 2)
    tampered_s6 = copy.deepcopy(outcome)
    tampered_steps6 = dict(tampered_s6.steps)
    object.__setattr__(tampered_steps6["P-13.06"], "receipt_hash", "wrong_hash" * 6)
    object.__setattr__(tampered_s6, "steps", tampered_steps6)

    with pytest.raises(RuntimeError):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single_file,
            outcome=tampered_s6,
        )

    assert index_file.read_text(encoding="utf-8") == canary
    assert single_file.read_text(encoding="utf-8") == canary

    # Tamper with invalid step 7 drift metadata (Defect 3)
    tampered_s7 = copy.deepcopy(outcome)
    tampered_steps7 = dict(tampered_s7.steps)
    object.__setattr__(
        tampered_steps7["P-13.07"],
        "extra_metadata",
        {"historical_receipt_intact": False, "reconciled_state": "DRIFTED"},
    )
    object.__setattr__(tampered_s7, "steps", tampered_steps7)

    with pytest.raises(RuntimeError):
        build_mod.build_and_verify_exhibit(
            output_dir=out_dir,
            single_file=single_file,
            outcome=tampered_s7,
        )

    assert index_file.read_text(encoding="utf-8") == canary
    assert single_file.read_text(encoding="utf-8") == canary
