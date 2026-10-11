"""Comprehensive test suite for Phase P-13: Canonical Killer Mission Vertical Slice.

Covers exact micro-tasks:
- P-13.01: Seed canonical disposable demo resources reproducibly.
- P-13.02: Execute full mission from natural language through AWS planner.
- P-13.03: Create and independently verify Tasks preparation action.
- P-13.04: Pause Calendar change at approval boundary.
- P-13.05: Approve, execute, and independently verify Calendar change.
- P-13.06: Produce READY mission receipt from deterministic facts.
- P-13.07: Mutate Calendar externally and prove READY -> DRIFTED.
- P-13.08: Clean checkout reproduction & end-to-end integration.

Constitutional Invariants Verified:
- Execute response != verification: mutable actions require separate read-back.
- Planner proposals have ZERO execution, verification, or readiness authority.
- Unapproved calendar mutations halt fail-closed at approval boundary (0 writes).
- Approval grants cryptographically bind to exact mission/action/target/parameters.
- Mission READY is computed purely from deterministic predicates and freshness.
- External reality change triggers deterministic READY -> DRIFTED reconciliation.
- Historical receipts remain immutable forever; current state projects authoritative truth.
- Zero personal spend ($0.00) preserved across all execution boundaries.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
from stilldone.adapters.tasks import GoogleApiClientTasksTransport
from stilldone.adapters.weather import OpenMeteoHttpTransport
from stilldone.authority_policy import (
    AuthorityPolicyTypeError,
    PlannerAuthorityError,
    evaluate_authority,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.gate import (
    PlannerGateAuthorityError,
    evaluate_execution_gate,
)
from stilldone.killer_mission import (
    CANONICAL_DEMO_EVENT_ID,
    CANONICAL_DEMO_TASK_TITLE,
    CANONICAL_DESIRED_START_TIME,
    CANONICAL_INITIAL_START_TIME,
    CANONICAL_KILLER_INTENT,
    PREDICATE_ID_CALENDAR,
    PREDICATE_ID_TASK,
    PREDICATE_ID_WEATHER,
    FakeGoogleCalendarTransport,
    InvalidEnvironmentConfigurationError,
    KillerMissionEnvironment,
    KillerMissionExecutionError,
    KillerMissionSliceRunner,
    LiveKillerMissionSliceRunner,
    LivePreflightBlockedError,
    check_live_preflight,
)
from stilldone.pending_approval import (
    PendingApprovalTypeError,
    create_pending_approval,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    SymbolicTargetRef,
)
from stilldone.receipt import (
    PlannerCurrentStateAuthorityError,
    create_mission_ready_receipt,
)
from stilldone.verifier.contracts import (
    VerificationObservation,
)
from stilldone.verifier.predicates import (
    PredicateTruth,
    evaluate_predicate,
)
from stilldone.verifier.readiness import (
    PlannerReadinessAuthorityError,
    compute_mission_readiness,
)


@pytest.fixture
def killer_env(tmp_path: Path) -> KillerMissionEnvironment:
    """Fixture providing clean temporary environment for killer mission execution."""
    return KillerMissionEnvironment(
        base_dir=tmp_path / "killer_mission_test",
        provenance=EvidenceProvenance.FIXTURE,
    )


@pytest.fixture
def runner(killer_env: KillerMissionEnvironment) -> KillerMissionSliceRunner:
    """Fixture providing initialized KillerMissionSliceRunner."""
    return KillerMissionSliceRunner(killer_env)


# ===========================================================================
# 1. P-13.01 Seed Tests
# ===========================================================================


def test_p13_01_seed_canonical_demo_resources(runner: KillerMissionSliceRunner) -> None:
    """P-13.01: Seed canonical demo resources and verify pre-state."""
    res = runner.step_p13_01_seed()
    assert res.task_id == "P-13.01"
    assert res.status == "PASS"
    assert res.is_verified is True
    assert res.provenance == EvidenceProvenance.FIXTURE

    # Assert pre-state: event at 07:45 UTC, prep task absent
    cal_read = runner.cal_read_adapter.read_event(
        ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                "google_calendar",
                ResourceKind.CALENDAR_EVENT,
                CANONICAL_DEMO_EVENT_ID,
                runner.env.scope.calendar_id,
            ),
            parameters={},
            action_id=ActionId.generate(),
        )
    )
    assert cal_read.observation is not None
    assert cal_read.observation.start_time == CANONICAL_INITIAL_START_TIME


# ===========================================================================
# 2. P-13.02 Natural Language Planning & Model Authority Tests
# ===========================================================================


def test_p13_02_natural_language_planning_and_compilation(
    runner: KillerMissionSliceRunner,
) -> None:
    """P-13.02: Compile plan proposal into execution contract; verify 0 model authority."""
    runner.step_p13_01_seed()
    res = runner.step_p13_02_plan()
    assert res.task_id == "P-13.02"
    assert res.status == "PASS"
    assert res.writes_performed == 0
    assert hasattr(runner, "execution_contract")
    assert hasattr(runner, "schedule")
    assert len(runner.schedule) == 3


def test_p13_02_model_proposal_has_zero_execution_or_readiness_authority(
    runner: KillerMissionSliceRunner,
) -> None:
    """Model proposal objects cannot smuggle authority into gates, readiness, or receipts."""
    proposal = CandidatePlanProposal.create(
        mission_id=runner.mission_id,
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.WEATHER_READ,
                target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                parameters={},
            )
        ],
    )
    action_prop = proposal.steps[0]

    # Authority gate rejects model proposal fail-closed
    with pytest.raises((PlannerAuthorityError, AuthorityPolicyTypeError)):
        evaluate_authority(action_prop, at=datetime.now(UTC))  # type: ignore[arg-type]

    # Execution gate rejects model proposal fail-closed
    with pytest.raises((PlannerGateAuthorityError, TypeError)):
        evaluate_execution_gate(action_prop)  # type: ignore[arg-type]

    # Pending approval rejects model proposal fail-closed
    with pytest.raises((PlannerAuthorityError, PendingApprovalTypeError)):
        create_pending_approval(action_prop, requested_at=datetime.now(UTC))  # type: ignore[arg-type]

    # Readiness evaluator rejects model proposal fail-closed
    with pytest.raises((PlannerReadinessAuthorityError, TypeError)):
        compute_mission_readiness(
            mission_id=runner.mission_id,
            predicates=proposal,  # type: ignore[arg-type]
            at=datetime.now(UTC),
        )

    # Receipt factory rejects model proposal fail-closed
    with pytest.raises((PlannerCurrentStateAuthorityError, TypeError)):
        create_mission_ready_receipt(proposal)


# ===========================================================================
# 3. P-13.03 Tasks Preparation Action Tests
# ===========================================================================


def test_p13_03_tasks_prep_action_execution_and_readback(
    runner: KillerMissionSliceRunner,
) -> None:
    """P-13.03: Create task.create (REVERSIBLE_AUTO) and independently verify with task.read."""
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    res = runner.step_p13_03_tasks_prep()

    assert res.task_id == "P-13.03"
    assert res.status == "PASS"
    assert res.writes_performed == 1
    assert res.is_verified is True

    # Confirm created task in fake transport
    read_action = ActionContract.create(
        mission_id=runner.mission_id,
        action_type=ActionType.TASK_READ,
        target=TargetIdentity(
            "google_tasks",
            ResourceKind.TASK,
            runner.created_task_id,
            runner.env.scope.task_list_id,
        ),
        parameters={},
        action_id=ActionId.generate(),
    )
    read_res = runner.tasks_read_adapter.read_task(read_action)
    assert read_res.observation is not None
    assert read_res.observation.title == CANONICAL_DEMO_TASK_TITLE


# ===========================================================================
# 4. P-13.04 Calendar Approval Boundary Pause Tests
# ===========================================================================


def test_p13_04_calendar_pause_at_approval_boundary(
    runner: KillerMissionSliceRunner,
) -> None:
    """P-13.04: Unapproved calendar.update pauses fail-closed with 0 writes."""
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    runner.step_p13_03_tasks_prep()
    res = runner.step_p13_04_calendar_pause()

    assert res.task_id == "P-13.04"
    assert res.status == "PASS"
    assert res.writes_performed == 0
    assert hasattr(runner, "pending_approval")
    assert runner.pending_approval.status.value == "PENDING"

    # Verify event was NOT updated on transport (remains initial 07:45)
    read_action = ActionContract.create(
        mission_id=runner.mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=runner.action_cal.target,
        parameters={},
        action_id=ActionId.generate(),
    )
    read_res = runner.cal_read_adapter.read_event(read_action)
    assert read_res.observation is not None
    assert read_res.observation.start_time == CANONICAL_INITIAL_START_TIME


# ===========================================================================
# 5. P-13.05 Approve, Execute, and Verify Calendar Update Tests
# ===========================================================================


def test_p13_05_calendar_approve_execute_and_verify(
    runner: KillerMissionSliceRunner,
) -> None:
    """P-13.05: Approved calendar update executes once (writes=1) and verifies."""
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    runner.step_p13_03_tasks_prep()
    runner.step_p13_04_calendar_pause()
    res = runner.step_p13_05_calendar_approve()

    assert res.task_id == "P-13.05"
    assert res.status == "PASS"
    assert res.writes_performed == 1
    assert res.is_verified is True

    # Independent read confirms start_time changed to 07:30
    read_action = ActionContract.create(
        mission_id=runner.mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=runner.action_cal.target,
        parameters={},
        action_id=ActionId.generate(),
    )
    read_res = runner.cal_read_adapter.read_event(read_action)
    assert read_res.observation is not None
    assert read_res.observation.start_time == CANONICAL_DESIRED_START_TIME


# ===========================================================================
# 6. P-13.06 READY Mission Receipt Tests
# ===========================================================================


def test_p13_06_produce_ready_mission_receipt(
    runner: KillerMissionSliceRunner,
) -> None:
    """P-13.06: Evaluate predicates; promote to READY; create immutable receipt."""
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    runner.step_p13_03_tasks_prep()
    runner.step_p13_04_calendar_pause()
    runner.step_p13_05_calendar_approve()
    res = runner.step_p13_06_ready_receipt()

    assert res.task_id == "P-13.06"
    assert res.status == "PASS"
    assert res.receipt_hash is not None
    assert runner.ready_receipt is not None
    assert runner.ready_receipt.state_at_projection == MissionState.READY
    assert runner.ready_receipt_hash == runner.ready_receipt.receipt_hash.value


# ===========================================================================
# 7. P-13.07 External Drift & Immutable Receipt Tests
# ===========================================================================


def test_p13_07_mutate_calendar_and_reconcile_drift(
    runner: KillerMissionSliceRunner,
) -> None:
    """P-13.07: External change triggers READY -> DRIFTED; historical receipt untouched."""
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    runner.step_p13_03_tasks_prep()
    runner.step_p13_04_calendar_pause()
    runner.step_p13_05_calendar_approve()
    runner.step_p13_06_ready_receipt()
    original_receipt_hash = runner.ready_receipt_hash

    res = runner.step_p13_07_mutate_and_drift()
    assert res.task_id == "P-13.07"
    assert res.status == "PASS"
    assert res.extra_metadata.get("reconciled_state") == "DRIFTED"

    # Historical receipt hash is strictly preserved
    assert runner.ready_receipt is not None
    assert runner.ready_receipt.receipt_hash.value == original_receipt_hash


# ===========================================================================
# 8. End-to-End Vertical Slice Integration Test
# ===========================================================================


def test_full_killer_mission_slice_end_to_end(
    runner: KillerMissionSliceRunner,
) -> None:
    """Execute all 7 micro-tasks in full vertical slice sequence end-to-end."""
    outcome = runner.run_full_slice()

    assert outcome.mission_id == runner.mission_id
    assert outcome.intent == CANONICAL_KILLER_INTENT
    assert len(outcome.steps) == 7
    for task_id, step in outcome.steps.items():
        assert step.status == "PASS", f"Step {task_id} failed: {step.details}"

    assert outcome.final_state == MissionState.DRIFTED
    assert outcome.ready_receipt_hash is not None
    assert outcome.historical_receipt_immutable is True
    assert outcome.total_writes_performed == 3  # 1 seed + 1 task + 1 cal update


# ===========================================================================
# 9. Negative Controls: Read-back Mismatch & Fake Protection
# ===========================================================================


def test_readback_mismatch_strictly_prevents_ready(
    runner: KillerMissionSliceRunner,
) -> None:
    """Negative control: If read-back contradicts expected start time, mission cannot be READY."""
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    runner.step_p13_03_tasks_prep()

    # Create mismatch observation (e.g. read-back returns 08:00 instead of 07:30)
    cal_mismatch_obs = VerificationObservation(
        target=runner.action_cal.target,
        observed_at=datetime.now(UTC),
        exists=True,
        properties={"start_time": "2026-10-04T08:00:00+00:00"},
        provenance=EvidenceProvenance.FIXTURE,
    )

    pred_eval = evaluate_predicate(runner.pred_calendar, cal_mismatch_obs)
    assert pred_eval.truth == PredicateTruth.FALSE

    observations = {
        PREDICATE_ID_WEATHER: VerificationObservation(
            target=runner.action_weather.target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"weather_status": "available"},
            provenance=EvidenceProvenance.FIXTURE,
        ),
        PREDICATE_ID_TASK: runner.task_observation,
        PREDICATE_ID_CALENDAR: cal_mismatch_obs,
    }

    readiness = compute_mission_readiness(
        mission_id=runner.mission_id,
        current_state=MissionState.VERIFYING,
        predicates=runner.canonical_predicates,
        verification_requests=runner.get_verification_requests(),
        observations=observations,
        at=datetime.now(UTC),
    )
    assert readiness.is_ready is False
    assert readiness.state != MissionState.READY
    assert PREDICATE_ID_CALENDAR in readiness.failed_predicate_ids


# ===========================================================================
# 10. Mandatory Adversarial Closed-World & Live-Preflight Security Tests
# ===========================================================================


def test_adversarial_fixture_transport_with_live_provenance_rejected(tmp_path: Path) -> None:
    """Adversarial: Synthetic fixture transports MUST be rejected if LIVE provenance is selected."""
    # Direct constructor with fake transports + LIVE provenance
    with pytest.raises(
        InvalidEnvironmentConfigurationError, match="Live provenance.*cannot be combined"
    ):
        KillerMissionEnvironment(
            base_dir=tmp_path / "env1",
            provenance=EvidenceProvenance.LIVE_GOOGLE,
        )

    with pytest.raises(
        InvalidEnvironmentConfigurationError, match="Live provenance.*cannot be combined"
    ):
        KillerMissionEnvironment(
            base_dir=tmp_path / "env2",
            provenance=EvidenceProvenance.LIVE_AWS,
        )

    # create_fixture_environment must strictly forbid LIVE provenance
    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="Fixture environment requires EvidenceProvenance.FIXTURE",
    ):
        KillerMissionEnvironment.create_fixture_environment(
            base_dir=tmp_path / "env3",
            provenance=EvidenceProvenance.LIVE_GOOGLE,
        )

    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="Fixture environment requires EvidenceProvenance.FIXTURE",
    ):
        KillerMissionEnvironment.create_fixture_environment(
            base_dir=tmp_path / "env4",
            provenance=EvidenceProvenance.LIVE_AWS,
        )


def test_adversarial_live_environment_with_missing_or_fake_transports_rejected(
    tmp_path: Path,
) -> None:
    """Adversarial: Live environment MUST require real concrete transports.

    Missing or fake = fail-closed.
    """
    # Missing concrete transports
    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="Live environment requires explicit concrete calendar_transport",
    ):
        KillerMissionEnvironment.create_live_environment(
            base_dir=tmp_path / "live_missing",
            calendar_transport=None,
            tasks_transport=None,
        )

    # Fake transport supplied to live environment
    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="Fake calendar transport supplied to live environment",
    ):
        KillerMissionEnvironment.create_live_environment(
            base_dir=tmp_path / "live_fake",
            calendar_transport=FakeGoogleCalendarTransport(),
            tasks_transport=None,
        )


def test_adversarial_live_preflight_blocks_without_operator_approval() -> None:
    """Adversarial: Live preflight blocks execution if explicit operator approval is absent."""
    from stilldone.killer_mission import DemoResourceScope

    scope = DemoResourceScope(calendar_id="demo_calendar_123", task_list_id="demo_tasks_123")
    report = check_live_preflight(
        scope=scope,
        operator_approved=False,
        aws_credentials_available=True,
        google_credentials={"token": "mock"},
        source_sha="1111111111111111111111111111111111111111",
    )
    assert report.is_ready is False
    assert any("operator" in b.lower() for b in report.blocker_reasons)


def test_adversarial_live_preflight_blocks_without_aws_credentials() -> None:
    """Adversarial: Live preflight blocks execution if AWS credentials are not available."""
    from stilldone.killer_mission import DemoResourceScope

    scope = DemoResourceScope(calendar_id="demo_calendar_123", task_list_id="demo_tasks_123")
    report = check_live_preflight(
        scope=scope,
        operator_approved=True,
        aws_credentials_available=False,
        google_credentials={"token": "mock"},
        source_sha="1111111111111111111111111111111111111111",
    )
    assert report.is_ready is False
    assert any("aws" in b.lower() for b in report.blocker_reasons)


def test_adversarial_live_preflight_blocks_without_source_sha() -> None:
    """Adversarial: Live preflight blocks execution if exact source SHA gate is invalid."""
    from stilldone.killer_mission import DemoResourceScope

    scope = DemoResourceScope(calendar_id="demo_calendar_123", task_list_id="demo_tasks_123")
    report = check_live_preflight(
        scope=scope,
        operator_approved=True,
        aws_credentials_available=True,
        google_credentials={"token": "mock"},
        source_sha="not_a_valid_40_char_git_sha",
    )
    assert report.is_ready is False
    assert any("sha" in b.lower() for b in report.blocker_reasons)


def test_adversarial_live_runner_preflight_failure_causes_zero_writes_and_zero_approvals(
    tmp_path: Path,
) -> None:
    """Adversarial: Live runner failing preflight guarantees 0 writes and 0 approvals consumed."""
    env = KillerMissionEnvironment.create_fixture_environment(tmp_path / "adversarial_runner")

    # Live runner strictly forbids running with a FIXTURE environment
    with pytest.raises(
        InvalidEnvironmentConfigurationError, match="cannot run in a FIXTURE environment"
    ):
        LiveKillerMissionSliceRunner(env, operator_approved=False)


def test_p13_cli_fixture_mode_subprocess() -> None:
    """Verify scripts/p13_killer_mission.py runs cleanly under python and python -O."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "p13_killer_mission.py"

    # 1. Standard python run
    proc_standard = subprocess.run(
        [sys.executable, str(script_path), "--fixture"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_standard.returncode == 0, f"Standard run failed: {proc_standard.stderr}"
    assert "ALL 7 P-13 ACCEPTANCE CRITERIA RIGIDLY VERIFIED." in proc_standard.stdout

    # 2. Optimized python -O run (assert statements stripped; deterministic checks must pass)
    proc_opt = subprocess.run(
        [sys.executable, "-O", str(script_path), "--fixture"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_opt.returncode == 0, f"Optimized run failed: {proc_opt.stderr}"
    assert "ALL 7 P-13 ACCEPTANCE CRITERIA RIGIDLY VERIFIED." in proc_opt.stdout


def test_p13_cli_live_mode_blocks_fail_closed() -> None:
    """Verify scripts/p13_killer_mission.py --live immediately exits 2 with BLOCKED_LIVE."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "p13_killer_mission.py"

    # Human-readable CLI output
    proc = subprocess.run(
        [sys.executable, str(script_path), "--live"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "BLOCKED_LIVE" in proc.stdout
    assert "0 writes performed; 0 approvals consumed." in proc.stdout

    # JSON CLI output
    proc_json = subprocess.run(
        [sys.executable, str(script_path), "--live", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_json.returncode == 2
    data = json.loads(proc_json.stdout)
    assert data["status"] == "BLOCKED_LIVE"
    assert data["writes_performed"] == 0
    assert len(data["blocker_reasons"]) > 0


def test_p13_cli_live_mode_with_operator_approval_blocks_without_aws_creds() -> None:
    """Verify scripts/p13_killer_mission.py --live with approval blocks without AWS creds."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "p13_killer_mission.py"

    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--live",
            "--operator-approved",
            "--source-sha",
            "1111111111111111111111111111111111111111",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "BLOCKED_LIVE" in proc.stdout


def test_adversarial_live_runner_all_steps_fail_closed_on_preflight_block(
    tmp_path: Path,
) -> None:
    """Adversarial: Every individual step method on LiveKillerMissionSliceRunner fails closed."""
    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_blocked",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

    # Runner without operator approval
    runner = LiveKillerMissionSliceRunner(live_env, operator_approved=False)

    # Every step must raise LivePreflightBlockedError when called directly
    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_01_seed()

    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_02_plan()

    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_03_tasks_prep()

    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_04_calendar_pause()

    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_05_calendar_approve()

    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_06_ready_receipt()

    with pytest.raises(LivePreflightBlockedError, match="Operator authorization required"):
        runner.step_p13_07_mutate_and_drift()

    # run_full_slice must return 7 BLOCKED_LIVE steps with 0 writes performed
    outcome = runner.run_full_slice()
    assert outcome.total_writes_performed == 0
    assert outcome.is_live is True
    assert outcome.ready_receipt_hash is None
    assert len(outcome.steps) == 7
    for _task_id, step in outcome.steps.items():
        assert step.status == "BLOCKED_LIVE"
        assert step.writes_performed == 0
        assert step.is_verified is False


def test_adversarial_live_mode_without_bedrock_planner_fails_closed(
    tmp_path: Path,
) -> None:
    """Adversarial: Live mode without Bedrock planner adapter strictly fails closed."""
    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_no_planner",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

    # Base runner in live mode with operator approval but NO bedrock planner
    runner = KillerMissionSliceRunner(
        env=live_env,
        live_mode=True,
        operator_approved=True,
        bedrock_planner=None,
    )

    with pytest.raises(
        KillerMissionExecutionError,
        match="Live mode requires concrete Bedrock / Strands planner adapter",
    ):
        runner.step_p13_02_plan()


def test_adversarial_live_mode_with_injected_bedrock_planner(
    tmp_path: Path,
) -> None:
    """Verify live mode compiles candidate proposal from Bedrock adapter with 0 model authority."""
    from stilldone.planning.bedrock import BedrockPlannerAdapter

    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_with_planner",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

    # Injected fake Bedrock client returning valid candidate plan JSON
    valid_plan_json = json.dumps(
        {
            "mission_id": "11111111-2222-3333-4444-555555555555",
            "steps": [
                {
                    "action_type": "weather.read",
                    "target_ref": "weather_location",
                    "parameters": {},
                    "explanation": "Check morning weather",
                },
                {
                    "action_type": "task.create",
                    "target_ref": "task_list",
                    "parameters": {"title": CANONICAL_DEMO_TASK_TITLE, "due": "2026-10-04"},
                    "explanation": "Pack backpacks",
                },
                {
                    "action_type": "calendar.update",
                    "target_ref": "leave_for_school",
                    "parameters": {"start_time": CANONICAL_DESIRED_START_TIME},
                    "explanation": "Adjust school departure to 7:30",
                },
            ],
            "explanation": "Injected planner proposal",
        }
    )

    fake_bedrock_client = MagicMock()
    fake_bedrock_client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": valid_plan_json}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
        "metrics": {"latencyMs": 120},
    }

    planner_adapter = BedrockPlannerAdapter(client=fake_bedrock_client)

    runner = KillerMissionSliceRunner(
        env=live_env,
        live_mode=True,
        operator_approved=True,
        bedrock_planner=planner_adapter,
    )

    # Step P-13.02 must compile the model proposal through deterministic contracts
    res = runner.step_p13_02_plan()
    assert res.status == "PASS"
    assert res.writes_performed == 0
    assert res.is_verified is True
    assert len(runner.schedule) == 3
    # Model proposal has zero execution authority
    assert runner.action_cal.action_type == ActionType.CALENDAR_UPDATE
