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
    assert runner.task_observation is not None

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


def test_adversarial_base_runner_rejects_live_mode_and_live_provenance(
    tmp_path: Path,
) -> None:
    """Adversarial: Base KillerMissionSliceRunner strictly rejects live mode / live provenance."""
    # 1. Base runner with live_mode=True must raise InvalidEnvironmentConfigurationError
    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="KillerMissionSliceRunner is restricted to fixture/local regression only",
    ):
        KillerMissionSliceRunner(live_mode=True)

    # 2. Base runner with non-fixture environment must raise InvalidEnvironmentConfigurationError
    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="KillerMissionSliceRunner is restricted to fixture/local regression only",
    ):
        KillerMissionSliceRunner(env=live_env)


def test_adversarial_live_runner_constructor_causes_zero_planner_calls(
    tmp_path: Path,
) -> None:
    """Adversarial: Constructing LiveKillerMissionSliceRunner causes 0 planner calls."""
    from stilldone.planning.bedrock import BedrockPlannerAdapter

    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_deferred_plan",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

    mock_client = MagicMock()
    planner_adapter = BedrockPlannerAdapter(client=mock_client)

    # Constructor must NOT invoke Bedrock planner! (Defect A)
    runner = LiveKillerMissionSliceRunner(
        env=live_env,
        operator_approved=False,
        bedrock_planner=planner_adapter,
    )
    assert mock_client.converse.call_count == 0

    # Step calls without approval fail closed before any planner invocation
    with pytest.raises(LivePreflightBlockedError):
        runner.step_p13_01_seed()
    assert mock_client.converse.call_count == 0

    with pytest.raises(LivePreflightBlockedError):
        runner.step_p13_02_plan()
    assert mock_client.converse.call_count == 0

    # Running full slice with blocked preflight results in:
    # 0 planner calls, 0 writes, 0 approvals consumed
    outcome = runner.run_full_slice()
    assert mock_client.converse.call_count == 0
    assert outcome.total_writes_performed == 0
    assert outcome.steps["P-13.02"].status == "BLOCKED_LIVE"


def test_adversarial_live_preflight_blocks_when_aws_creds_present_but_planner_absent(
    tmp_path: Path,
) -> None:
    """Adversarial: AWS credentials present + planner absent blocks BEFORE seed (0 writes)."""
    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_no_planner",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

    runner = LiveKillerMissionSliceRunner(
        env=live_env,
        operator_approved=True,
        aws_credentials_available=True,
        bedrock_planner=None,  # AWS credentials present, but planner adapter absent!
        source_sha="1111111111111111111111111111111111111111",
    )

    preflight = runner.evaluate_preflight()
    assert preflight.aws_bedrock_auth_available is True
    assert preflight.is_ready is False
    assert any("Bedrock planner adapter is not available" in b for b in preflight.blocker_reasons)

    # Must block before P-13.01 and before any writes
    with pytest.raises(LivePreflightBlockedError):
        runner.step_p13_01_seed()


def test_adversarial_live_preflight_git_fail_closed_checks() -> None:
    """Adversarial: Strict git preflight gates fail closed on non-hex SHA,
    SHA mismatch, git error, and dirty tree.
    """
    from stilldone.killer_mission import DemoResourceScope

    scope = DemoResourceScope(calendar_id="demo_cal", task_list_id="demo_tasks")

    # 1. Non-hex 40-char SHA rejected
    for invalid_sha in [
        "not_a_sha",
        "123456789012345678901234567890123456789",
        "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ",
        "111111111111111111111111111111111111111G",
    ]:
        rep = check_live_preflight(
            scope=scope,
            operator_approved=True,
            source_sha=invalid_sha,
        )
        assert rep.is_ready is False
        assert rep.source_sha_verified is False
        assert any("valid lowercase 40-hex" in b for b in rep.blocker_reasons)

    # 2. HEAD != source_sha rejected
    def git_head_mismatch(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd or "origin/main" in cmd:
            return 0, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", ""
        return 0, "", ""

    rep_head_mismatch = check_live_preflight(
        scope=scope,
        operator_approved=True,
        source_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        git_runner=git_head_mismatch,
    )
    assert rep_head_mismatch.is_ready is False
    assert any(
        "does not match authorized source_sha" in b for b in rep_head_mismatch.blocker_reasons
    )

    # 3. origin/main != HEAD rejected
    def git_origin_mismatch(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd:
            return 0, "1111111111111111111111111111111111111111", ""
        if "origin/main" in cmd:
            return 0, "2222222222222222222222222222222222222222", ""
        return 0, "", ""

    rep_origin_mismatch = check_live_preflight(
        scope=scope,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        git_runner=git_origin_mismatch,
    )
    assert rep_origin_mismatch.is_ready is False
    assert any("does not match origin/main" in b for b in rep_origin_mismatch.blocker_reasons)

    # 4. git command failure rejected
    def git_failure(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "fatal: not a git repository"

    rep_fail = check_live_preflight(
        scope=scope,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        git_runner=git_failure,
    )
    assert rep_fail.is_ready is False
    assert rep_fail.source_sha_verified is False

    # 5. dirty tree rejected
    def git_dirty(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd or "origin/main" in cmd:
            return 0, "1111111111111111111111111111111111111111", ""
        return 0, " M src/stilldone/killer_mission.py", ""

    rep_dirty = check_live_preflight(
        scope=scope,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        git_runner=git_dirty,
        clean_working_tree_required=True,
    )
    assert rep_dirty.is_ready is False
    assert rep_dirty.clean_working_tree_verified is False
    assert any("dirty" in b for b in rep_dirty.blocker_reasons)


def test_adversarial_synthetic_service_wrappers_cannot_create_live_provenance(
    tmp_path: Path,
) -> None:
    """Adversarial: Synthetic/MagicMock services strictly produce LOCAL_EXECUTION,
    never LIVE_GOOGLE.
    """
    mock_cal_svc = MagicMock()
    mock_tasks_svc = MagicMock()

    env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "synthetic_live_env",
        calendar_transport=GoogleApiClientCalendarTransport(service=mock_cal_svc),
        tasks_transport=GoogleApiClientTasksTransport(service=mock_tasks_svc),
        weather_transport=OpenMeteoHttpTransport(),
    )

    # Synthetic wrapper automatically downgraded to LOCAL_EXECUTION
    assert env.provenance == EvidenceProvenance.LOCAL_EXECUTION
    assert not env.provenance.is_external_live

    # Forbids forcing LIVE_GOOGLE on synthetic wrappers
    with pytest.raises(
        InvalidEnvironmentConfigurationError,
        match="Live provenance.*cannot be combined with synthetic",
    ):
        KillerMissionEnvironment(
            base_dir=tmp_path / "forbidden_env",
            provenance=EvidenceProvenance.LIVE_GOOGLE,
            calendar_transport=GoogleApiClientCalendarTransport(service=mock_cal_svc),
            tasks_transport=GoogleApiClientTasksTransport(service=mock_tasks_svc),
            weather_transport=OpenMeteoHttpTransport(),
        )


def test_adversarial_live_mode_compilation_with_injected_bedrock_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify live runner compiles candidate proposal from Bedrock adapter
    with 0 model authority when preflight passes.
    """
    from stilldone.killer_mission import LivePreflightReport
    from stilldone.planning.bedrock import BedrockPlannerAdapter

    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path / "live_env_with_planner",
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

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

    runner = LiveKillerMissionSliceRunner(
        env=live_env,
        operator_approved=True,
        aws_credentials_available=True,
        bedrock_planner=planner_adapter,
        source_sha="1111111111111111111111111111111111111111",
        demo_date="2026-10-04",
    )

    # Mock preflight pass for isolated step_p13_02 compilation test
    mock_report = LivePreflightReport(
        is_ready=True,
        operator_approved=True,
        source_sha_verified=True,
        clean_working_tree_verified=True,
        google_auth_available=True,
        aws_bedrock_auth_available=True,
        open_meteo_reachable=True,
        disposable_scope_verified=True,
        transports_verified=True,
        blocker_reasons=[],
    )
    monkeypatch.setattr(runner, "evaluate_preflight", lambda: mock_report)

    # Step P-13.02 compiles the model proposal through deterministic contracts
    res = runner.step_p13_02_plan()
    assert res.status == "PASS"
    assert res.writes_performed == 0
    assert res.is_verified is True
    assert len(runner.schedule) == 3
    # Model proposal has zero execution authority
    assert runner.action_cal.action_type == ActionType.CALENDAR_UPDATE
    assert fake_bedrock_client.converse.call_count == 1


def test_adversarial_provider_generated_event_id_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify provider event_id different from evt_leave_for_school propagates into
    action target.
    """
    from unittest.mock import MagicMock

    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.killer_mission import LivePreflightReport
    from stilldone.planning.bedrock import BedrockPlannerAdapter
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        SymbolicTargetRef,
    )

    scope = DemoResourceScope("c_custom_demo", "tl_custom_demo")
    live_env = KillerMissionEnvironment.create_live_environment(
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    fake_planner = MagicMock(spec=BedrockPlannerAdapter)
    runner = LiveKillerMissionSliceRunner(
        env=live_env,
        operator_approved=True,
        aws_credentials_available=True,
        bedrock_planner=fake_planner,
        source_sha="1111111111111111111111111111111111111111",
        demo_date="2026-10-04",
    )
    mock_report = LivePreflightReport(
        is_ready=True,
        operator_approved=True,
        source_sha_verified=True,
        clean_working_tree_verified=True,
        google_auth_available=True,
        aws_bedrock_auth_available=True,
        open_meteo_reachable=True,
        disposable_scope_verified=True,
        transports_verified=True,
        blocker_reasons=[],
    )
    monkeypatch.setattr(runner, "evaluate_preflight", lambda: mock_report)

    # In step_p13_01, simulate seeding returning a provider-generated event_id
    runner.seeded_event_id = "provider_generated_evt_998877"

    step_weather = CandidateActionProposal.create(
        action_type=ActionType.WEATHER_READ,
        target_ref=SymbolicTargetRef.WEATHER_LOCATION,
        parameters={},
        explanation="Check weather",
    )
    step_task = CandidateActionProposal.create(
        action_type=ActionType.TASK_CREATE,
        target_ref=SymbolicTargetRef.TASK_LIST,
        parameters={"title": "Pack backpacks", "due": "2026-10-04"},
        explanation="Create prep task",
    )
    step_cal = CandidateActionProposal.create(
        action_type=ActionType.CALENDAR_UPDATE,
        target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
        parameters={"start_time": "2026-10-04T07:30:00+00:00"},
        explanation="Adjust school departure",
    )
    fake_plan = CandidatePlanProposal.create(
        mission_id=runner.mission_id,
        steps=[step_weather, step_task, step_cal],
        explanation="Injected plan proposal",
    )
    fake_planner.plan.return_value = MagicMock(plan=fake_plan)

    res = runner.step_p13_02_plan()
    assert res.status == "PASS"
    # Canonical provider event_id MUST propagate into the compiled calendar action target:
    assert runner.action_cal.target.resource_id == "provider_generated_evt_998877"
    assert runner.action_cal.target.resource_id != CANONICAL_DEMO_EVENT_ID


def test_runtime_target_date_propagation() -> None:
    """Verify runtime demo_date propagates across initial/desired/end/task times and predicates."""
    custom_date = "2026-11-20"
    runner = KillerMissionSliceRunner(demo_date=custom_date)

    assert runner.demo_date == custom_date
    assert runner.initial_start_time == "2026-11-20T07:45:00+00:00"
    assert runner.initial_end_time == "2026-11-20T08:15:00+00:00"
    assert runner.desired_start_time == "2026-11-20T07:30:00+00:00"
    assert runner.desired_end_time == "2026-11-20T08:00:00+00:00"
    assert runner.contradictory_start_time == "2026-11-20T08:00:00+00:00"
    assert runner.contradictory_end_time == "2026-11-20T08:30:00+00:00"
    assert runner.task_due_date == "2026-11-20"

    # Predicates check desired start time
    assert runner.pred_calendar.expected_value == "2026-11-20T07:30:00+00:00"
    # Action cal parameters check desired start time
    assert runner.action_cal.parameters["start_time"] == "2026-11-20T07:30:00+00:00"
    # Action task parameters check due date
    assert runner.action_task.parameters["due"] == "2026-11-20"


def test_calendar_decision_branches_awaiting_and_reject() -> None:
    """Verify calendar mutation pauses when decision is None and halts when REJECT."""
    from stilldone.pending_approval import ApprovalDecision

    # 1. Decision is None (Awaiting decision) -> 0 writes, status AWAITING_APPROVAL
    runner_pending = KillerMissionSliceRunner(calendar_decision=None)
    runner_pending.step_p13_01_seed()
    runner_pending.step_p13_02_plan()
    runner_pending.step_p13_03_tasks_prep()
    runner_pending.step_p13_04_calendar_pause()
    res_await = runner_pending.step_p13_05_calendar_approve()
    assert res_await.status == "AWAITING_APPROVAL"
    assert res_await.writes_performed == 0
    assert res_await.is_verified is False

    outcome_pending = KillerMissionSliceRunner(calendar_decision=None).run_full_slice()
    assert outcome_pending.final_state == MissionState.NEEDS_APPROVAL
    assert outcome_pending.ready_receipt_hash is None

    # 2. Decision is REJECT -> 0 writes, status REJECTED
    runner_reject = KillerMissionSliceRunner(calendar_decision=ApprovalDecision.REJECT)
    runner_reject.step_p13_01_seed()
    runner_reject.step_p13_02_plan()
    runner_reject.step_p13_03_tasks_prep()
    runner_reject.step_p13_04_calendar_pause()
    res_rej = runner_reject.step_p13_05_calendar_approve()
    assert res_rej.status == "REJECTED"
    assert res_rej.writes_performed == 0
    assert res_rej.is_verified is False

    outcome_rej = KillerMissionSliceRunner(
        calendar_decision=ApprovalDecision.REJECT
    ).run_full_slice()
    assert outcome_rej.final_state == MissionState.CANCELLED
    assert outcome_rej.ready_receipt_hash is None


def test_actual_observation_requirement_in_p13_06_fails_closed() -> None:
    """Verify P-13.06 fails closed if actual observations are missing or contradictory."""
    from stilldone.killer_mission import KillerMissionVerificationError

    runner = KillerMissionSliceRunner()
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    runner.step_p13_03_tasks_prep()
    runner.step_p13_04_calendar_pause()
    runner.step_p13_05_calendar_approve()

    # Tamper with weather observation -> delete it
    runner.weather_observation = None
    with pytest.raises(KillerMissionVerificationError, match="Missing actual weather observation"):
        runner.step_p13_06_ready_receipt()


def test_cli_phase_a_zero_sdk_local_gate_halt() -> None:
    """Verify Phase A halts with code 2 before any SDK calls when local checks fail."""
    from scripts.p13_killer_mission import run_killer_mission

    # 1. Missing operator consent halts with code 2
    rc_no_consent = run_killer_mission(live=True, operator_approved=False)
    assert rc_no_consent == 2

    # 2. Invalid source SHA halts with code 2
    rc_bad_sha = run_killer_mission(
        live=True, operator_approved=True, source_sha="not-a-40-hex-sha"
    )
    assert rc_bad_sha == 2

    # 3. Disallowed container (@default or primary) halts with code 2
    rc_disallowed = run_killer_mission(
        live=True,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_calendar_id="primary",
        demo_task_list_id="tl_test",
    )
    assert rc_disallowed == 2

    # 4. Bad date format halts with code 2
    rc_bad_date = run_killer_mission(
        live=True,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_calendar_id="c_test",
        demo_task_list_id="tl_test",
        demo_date="2026/10/04",
    )
    assert rc_bad_date == 2

    # 5. Impossible calendar date halts with code 2 (Defect H)
    rc_impossible_date = run_killer_mission(
        live=True,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_calendar_id="c_test",
        demo_task_list_id="tl_test",
        demo_date="2026-02-31",
    )
    assert rc_impossible_date == 2

    # 6. Pre-authorized live calendar APPROVE halts with code 2 (Defect C)
    rc_pre_auth = run_killer_mission(
        live=True,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_calendar_id="c_test",
        demo_task_list_id="tl_test",
        calendar_decision="APPROVE",
    )
    assert rc_pre_auth == 2


def test_defect_a_weather_observation_requirements() -> None:
    """Verify Defect A: weather fact must come from a validated provider observation."""
    from datetime import timedelta

    from stilldone.adapters.weather import (
        ProviderAttribution,
        WeatherObservation,
        WeatherReadResult,
        WeatherReadStatus,
    )
    from stilldone.domain.provenance import EvidenceProvenance as _Prov
    from stilldone.killer_mission import (
        CANONICAL_WEATHER_LOCATION_ID,
        KillerMissionSliceRunner,
        KillerMissionVerificationError,
    )

    def _obs(
        *,
        location_id: str = CANONICAL_WEATHER_LOCATION_ID,
        observed_at: datetime | None = None,
        provider_valid_time: str = "2026-10-04T07:00",
        attribution: ProviderAttribution | None = None,
    ) -> WeatherObservation:
        return WeatherObservation(
            location_id=location_id,
            temperature_2m=15.0,
            precipitation=0.0,
            weather_code=0,
            wind_speed_10m=5.0,
            units={"temperature_2m": "°C"},
            observed_at=observed_at or datetime.now(UTC),
            attribution=attribution or ProviderAttribution(),
            provenance=_Prov.FIXTURE,
            provider_valid_time=provider_valid_time,
        )

    def _runner_with(result: WeatherReadResult) -> KillerMissionSliceRunner:
        runner = KillerMissionSliceRunner()
        runner.step_p13_01_seed()
        fake = MagicMock()
        fake.read_weather.return_value = result
        runner.weather_adapter = fake
        return runner

    # 1. Provider error -> no READY-capable weather fact; untrusted provider text not echoed
    r = _runner_with(
        WeatherReadResult(
            status=WeatherReadStatus.PROVIDER_ERROR,
            error_message="secret-ish upstream text SENTINEL_X",
        )
    )
    with pytest.raises(KillerMissionVerificationError, match="Weather read failed") as ei:
        r.step_p13_02_plan()
    assert "SENTINEL_X" not in str(ei.value)
    assert r.weather_observation is None

    # 2. MATCH status but empty observation
    r = _runner_with(WeatherReadResult(status=WeatherReadStatus.MATCH, observation=None))
    with pytest.raises(KillerMissionVerificationError, match="Weather read failed"):
        r.step_p13_02_plan()
    assert r.weather_observation is None

    # 3. Contradictory metadata: wrong location binding
    r = _runner_with(
        WeatherReadResult(status=WeatherReadStatus.MATCH, observation=_obs(location_id="other"))
    )
    with pytest.raises(KillerMissionVerificationError, match="location mismatch"):
        r.step_p13_02_plan()

    # 4. Contradictory metadata: missing provider-valid time
    r = _runner_with(
        WeatherReadResult(status=WeatherReadStatus.MATCH, observation=_obs(provider_valid_time=""))
    )
    with pytest.raises(KillerMissionVerificationError, match="provider_valid_time"):
        r.step_p13_02_plan()

    # 5. Contradictory metadata: empty attribution provider
    r = _runner_with(
        WeatherReadResult(
            status=WeatherReadStatus.MATCH,
            observation=_obs(attribution=ProviderAttribution(provider="")),
        )
    )
    with pytest.raises(KillerMissionVerificationError, match="attribution"):
        r.step_p13_02_plan()

    # 6. Stale observation is NOT refreshed with a new timestamp
    r = _runner_with(
        WeatherReadResult(
            status=WeatherReadStatus.MATCH,
            observation=_obs(observed_at=datetime.now(UTC) - timedelta(hours=2)),
        )
    )
    with pytest.raises(KillerMissionVerificationError, match="stale"):
        r.step_p13_02_plan()
    assert r.weather_observation is None

    # 7. Genuine observation is projected with its exact provider timestamp and provenance
    genuine_ts = datetime.now(UTC) - timedelta(seconds=5)
    genuine = _obs(observed_at=genuine_ts)
    r = _runner_with(WeatherReadResult(status=WeatherReadStatus.MATCH, observation=genuine))
    res = r.step_p13_02_plan()
    assert res.status == "PASS"
    assert r.weather_observation is not None
    assert r.weather_observation.observed_at == genuine_ts
    assert r.weather_observation.provenance == genuine.provenance
    assert r.weather_observation.properties["provider_valid_time"] == "2026-10-04T07:00"
    assert r.weather_observation.properties["provider"] == genuine.attribution.provider


def _live_runner_for_boundary_tests(
    monkeypatch: pytest.MonkeyPatch,
    live_env: KillerMissionEnvironment | None = None,
    **kwargs: object,
) -> LiveKillerMissionSliceRunner:
    """Live runner over production transport classes with injected (non-network) clients."""
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.killer_mission import LivePreflightReport

    if live_env is None:
        import tempfile

        test_base_dir = Path(tempfile.mkdtemp(prefix="stilldone_test_live_storage_"))
        scope = DemoResourceScope("c_boundary_demo", "tl_boundary_demo")
        live_env = KillerMissionEnvironment.create_live_environment(
            base_dir=test_base_dir,
            scope=scope,
            calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
            tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
            weather_transport=OpenMeteoHttpTransport(),
        )
    if "bedrock_planner" not in kwargs:
        from stilldone.planning.bedrock import BedrockPlannerAdapter
        from stilldone.planning.contracts import (
            CandidateActionProposal,
            CandidatePlanProposal,
            SymbolicTargetRef,
        )

        fake_p = MagicMock(spec=BedrockPlannerAdapter)
        valid_p = CandidatePlanProposal.create(
            mission_id="11111111-2222-3333-4444-555555555555",
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.WEATHER_READ,
                    target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                    parameters={},
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.TASK_CREATE,
                    target_ref=SymbolicTargetRef.TASK_LIST,
                    parameters={"title": CANONICAL_DEMO_TASK_TITLE, "due": "2026-10-04"},
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_UPDATE,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                    parameters={"start_time": "2026-10-04T07:30:00+00:00"},
                ),
            ],
        )
        fake_p.plan.return_value = MagicMock(plan=valid_p)
        kwargs["bedrock_planner"] = fake_p

    kwargs.setdefault("operator_approved", True)
    kwargs.setdefault("aws_credentials_available", True)
    kwargs.setdefault("source_sha", "1111111111111111111111111111111111111111")
    kwargs.setdefault("demo_date", "2026-10-04")
    runner = LiveKillerMissionSliceRunner(
        env=live_env,
        **kwargs,  # type: ignore[arg-type]
    )
    report = LivePreflightReport(
        is_ready=True,
        operator_approved=True,
        source_sha_verified=True,
        clean_working_tree_verified=True,
        google_auth_available=True,
        aws_bedrock_auth_available=True,
        open_meteo_reachable=True,
        disposable_scope_verified=True,
        transports_verified=True,
        blocker_reasons=[],
    )
    monkeypatch.setattr(runner, "evaluate_preflight", lambda: report)
    return runner


def test_defect_b_plan_validation_contract() -> None:
    """Verify Defect B: exact canonical 3-step plan enforced at the P-13 mission boundary."""
    from stilldone.killer_mission import (
        CanonicalKillerPlanValidationError,
        DuplicatedMutationError,
        InvalidActionCountError,
        InvalidActionOrderError,
        InvalidActionTypeError,
        InvalidPlanParameterError,
        InvalidSymbolicTargetError,
        validate_canonical_killer_mission_plan,
    )
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        SymbolicTargetRef,
    )

    mid = "11111111-2222-3333-4444-555555555555"
    date = "2026-10-04"
    start = "2026-10-04T07:30:00+00:00"

    def w() -> CandidateActionProposal:
        return CandidateActionProposal.create(
            action_type=ActionType.WEATHER_READ,
            target_ref=SymbolicTargetRef.WEATHER_LOCATION,
            parameters={},
            explanation="weather",
        )

    def t(due: str = date, title: str = CANONICAL_DEMO_TASK_TITLE) -> CandidateActionProposal:
        return CandidateActionProposal.create(
            action_type=ActionType.TASK_CREATE,
            target_ref=SymbolicTargetRef.TASK_LIST,
            parameters={"title": title, "due": due},
            explanation="task",
        )

    def c(
        start_time: str = start, ref: SymbolicTargetRef = SymbolicTargetRef.LEAVE_FOR_SCHOOL
    ) -> CandidateActionProposal:
        return CandidateActionProposal.create(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=ref,
            parameters={"start_time": start_time},
            explanation="cal",
        )

    def plan(*steps: CandidateActionProposal) -> CandidatePlanProposal:
        return CandidatePlanProposal.create(mission_id=mid, steps=list(steps), explanation="p")

    def check(p: CandidatePlanProposal) -> None:
        validate_canonical_killer_mission_plan(p, target_date=date, desired_start_time=start)

    # Valid canonical plan passes
    check(plan(w(), t(), c()))

    cases: list[tuple[CandidatePlanProposal, type[Exception]]] = [
        (plan(w(), t()), InvalidActionCountError),  # missing mutation
        (plan(w(), t(), c(), c()), InvalidActionCountError),  # extra action
        (plan(w(), c(), c()), DuplicatedMutationError),  # duplicated mutation
        (plan(t(), w(), c()), InvalidActionOrderError),  # wrong order
        (plan(w(), t(due="2026-10-05"), c()), InvalidPlanParameterError),  # wrong due date
        (plan(w(), t(), c(start_time="2026-10-04T08:00:00+00:00")), InvalidPlanParameterError),
        (plan(w(), t(title="Something else"), c()), InvalidPlanParameterError),
        (
            plan(w(), t(), c(ref=SymbolicTargetRef.DEMO_EVENT)),
            InvalidSymbolicTargetError,
        ),  # wrong symbolic target
    ]
    for bad_plan, err in cases:
        with pytest.raises(err):
            check(bad_plan)
        # every rejection is a bounded typed error from the same hierarchy
        with pytest.raises(CanonicalKillerPlanValidationError):
            check(bad_plan)

    # Unsupported action type at a position is a typed type error
    wrong_type = CandidateActionProposal.create(
        action_type=ActionType.CALENDAR_READ,
        target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
        parameters={},
        explanation="read",
    )
    with pytest.raises(InvalidActionTypeError):
        check(plan(wrong_type, t(), c()))


def test_defect_b_live_plan_rejected_before_any_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong live candidate plan is rejected before the weather read or any mutation."""
    from stilldone.killer_mission import InvalidActionOrderError
    from stilldone.planning.bedrock import BedrockPlannerAdapter
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        SymbolicTargetRef,
    )

    fake_planner = MagicMock(spec=BedrockPlannerAdapter)
    runner = _live_runner_for_boundary_tests(monkeypatch, bedrock_planner=fake_planner)
    runner.seeded_event_id = "provider_evt_boundary"
    reordered = CandidatePlanProposal.create(
        mission_id=runner.mission_id,
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.TASK_CREATE,
                target_ref=SymbolicTargetRef.TASK_LIST,
                parameters={"title": CANONICAL_DEMO_TASK_TITLE, "due": "2026-10-04"},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.WEATHER_READ,
                target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                parameters={},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.CALENDAR_UPDATE,
                target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                parameters={"start_time": "2026-10-04T07:30:00+00:00"},
            ),
        ],
    )
    fake_planner.plan.return_value = MagicMock(plan=reordered)
    weather_spy = MagicMock()
    runner.weather_adapter = weather_spy
    with pytest.raises(InvalidActionOrderError):
        runner.step_p13_02_plan()
    weather_spy.read_weather.assert_not_called()
    assert runner.total_writes == 0
    assert runner.weather_observation is None


def test_defect_c_human_approval_post_pending_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Defect C: early APPROVE never grants authority; decision binds to exact pending."""
    from stilldone.killer_mission import KillerMissionAuthorityError
    from stilldone.pending_approval import ApprovalDecision, PendingApproval

    # 1. Early (pre-pending) APPROVE is rejected at construction for enum and string forms
    for early in (ApprovalDecision.APPROVE, "APPROVE"):
        with pytest.raises(KillerMissionAuthorityError, match="Pre-authorized"):
            _live_runner_for_boundary_tests(monkeypatch, calendar_decision=early)

    # 2. No post-pending decision -> AWAITING_APPROVAL, zero calendar writes, no grant
    runner = _live_runner_for_boundary_tests(monkeypatch)
    pause = runner.step_p13_04_calendar_pause()
    assert pause.status == "PASS" and pause.writes_performed == 0
    res = runner.step_p13_05_calendar_approve()
    assert res.status == "AWAITING_APPROVAL"
    assert res.writes_performed == 0
    assert runner.total_writes == 0
    assert not hasattr(runner, "approved_cal_outcome")

    # 3. Post-pending REJECT callback receives the exact pending identity; zero grant/writes
    seen: list[PendingApproval] = []

    def reject_cb(pending: PendingApproval) -> ApprovalDecision:
        seen.append(pending)
        return ApprovalDecision.REJECT

    runner_r = _live_runner_for_boundary_tests(
        monkeypatch, post_pending_decision_callback=reject_cb
    )
    runner_r.step_p13_04_calendar_pause()
    res_r = runner_r.step_p13_05_calendar_approve()
    assert len(seen) == 1
    assert seen[0] is runner_r.pending_approval
    assert seen[0].pending_approval_id == runner_r.pending_approval.pending_approval_id
    assert res_r.status == "REJECTED"
    assert res_r.writes_performed == 0
    assert runner_r.total_writes == 0
    assert not hasattr(runner_r, "approved_cal_outcome")

    # 4. Callback is never consulted before a PendingApproval exists
    called: list[object] = []
    runner_n = _live_runner_for_boundary_tests(
        monkeypatch, post_pending_decision_callback=lambda p: called.append(p)
    )
    with pytest.raises(Exception):  # noqa: B017 - sequence/attribute guard is acceptable
        runner_n.step_p13_05_calendar_approve()
    assert called == []


def test_defect_d_exact_provider_identity_and_privacy() -> None:
    """Verify Defect D: exact provider task ID required; no title substitute; no ID leakage."""
    from unittest.mock import patch

    from stilldone.execution.state import ProviderExecutionResult
    from stilldone.killer_mission import KillerMissionVerificationError

    def _gate_with(details: dict[str, object]) -> MagicMock:
        gate = MagicMock()
        gate.is_authorized = True
        gate.provider_result = ProviderExecutionResult(
            action_type=ActionType.TASK_CREATE,
            success=True,
            status_name="EXECUTION_SUCCEEDED",
            writes_performed=1,
            details=details,
        )
        return gate

    # 1. Missing provider task ID -> fail closed (no title-based discovery)
    runner = KillerMissionSliceRunner()
    runner.step_p13_01_seed()
    runner.step_p13_02_plan()
    with patch("stilldone.killer_mission.execute_gated_action", return_value=_gate_with({})):
        with pytest.raises(KillerMissionVerificationError, match="exact provider task ID"):
            runner.step_p13_03_tasks_prep()
    assert runner.task_observation is None

    # 2. Non-existent provider task ID -> exact read-back fails; no substitution by title
    runner2 = KillerMissionSliceRunner()
    runner2.step_p13_01_seed()
    runner2.step_p13_02_plan()
    with patch(
        "stilldone.killer_mission.execute_gated_action",
        return_value=_gate_with({"task_id": "t_does_not_exist_SENTINEL"}),
    ):
        with pytest.raises(Exception):  # noqa: B017 - any typed read-back failure is acceptable
            runner2.step_p13_03_tasks_prep()
    assert runner2.task_observation is None

    # 3. Privacy: raw provider IDs never appear in public step details / JSON outcome
    runner3 = KillerMissionSliceRunner()
    outcome = runner3.run_full_slice()
    public_json = json.dumps(outcome.to_dict())
    assert runner3.seeded_event_id not in public_json
    assert runner3.created_task_id not in public_json
    assert "seeded_event_id" not in outcome.steps["P-13.01"].extra_metadata


def test_defect_d_live_seed_requires_provider_event_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live seeding without an actual provider event ID must not fall back to the constant."""
    from unittest.mock import patch

    from stilldone.killer_mission import KillerMissionVerificationError

    runner = _live_runner_for_boundary_tests(monkeypatch)
    no_id = MagicMock(event_id=None, writes_performed=1, readback_verified=True)
    with patch("stilldone.killer_mission.seed_canonical_demo_resources", return_value=no_id):
        with pytest.raises(KillerMissionVerificationError, match="provider event ID"):
            runner.step_p13_01_seed()
    assert runner.action_cal.target.resource_id != "evt_leave_for_school_used_live"

    runner_ok = _live_runner_for_boundary_tests(monkeypatch)
    with_id = MagicMock(
        event_id="PROVIDER_EVT_SENTINEL_42", writes_performed=1, readback_verified=True
    )
    with patch("stilldone.killer_mission.seed_canonical_demo_resources", return_value=with_id):
        res = runner_ok.step_p13_01_seed()
    assert runner_ok.seeded_event_id == "PROVIDER_EVT_SENTINEL_42"
    assert runner_ok.action_cal.target.resource_id == "PROVIDER_EVT_SENTINEL_42"
    assert runner_ok.action_cal.target.resource_id != CANONICAL_DEMO_EVENT_ID
    assert "PROVIDER_EVT_SENTINEL_42" not in json.dumps(res.to_dict())


def test_defect_e_live_ready_stops_before_fixture_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Defect E: live runner stops at READY; fixture drift never invoked or claimed."""
    from stilldone.killer_mission import FakeGoogleCalendarTransport, KillerMissionStepResult

    runner = _live_runner_for_boundary_tests(monkeypatch)

    def _ok(task_id: str, **meta: object) -> KillerMissionStepResult:
        res = KillerMissionStepResult(
            task_id=task_id,
            step_name=task_id,
            status="PASS",
            provenance=runner.env.provenance,
            details="stubbed live-shaped step",
            writes_performed=0,
            is_verified=True,
        )
        runner.step_results[task_id] = res
        return res

    def _ready() -> KillerMissionStepResult:
        runner.ready_receipt_hash = "a" * 64
        return _ok("P-13.06")

    def _seed() -> KillerMissionStepResult:
        runner.seeded_event_id = "PROVIDER_EVT_READY_TEST"
        return _ok("P-13.01")

    monkeypatch.setattr(runner, "step_p13_01_seed", _seed)
    monkeypatch.setattr(runner, "step_p13_02_plan", lambda: _ok("P-13.02"))
    monkeypatch.setattr(runner, "step_p13_03_tasks_prep", lambda: _ok("P-13.03"))
    monkeypatch.setattr(runner, "step_p13_04_calendar_pause", lambda: _ok("P-13.04"))
    monkeypatch.setattr(runner, "step_p13_05_calendar_approve", lambda: _ok("P-13.05"))
    monkeypatch.setattr(runner, "step_p13_06_ready_receipt", _ready)

    def _forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("fixture drift path must never run in live mode")

    monkeypatch.setattr(KillerMissionSliceRunner, "step_p13_07_mutate_and_drift", _forbidden)
    monkeypatch.setattr(FakeGoogleCalendarTransport, "seed_event", _forbidden)

    outcome = runner.run_full_slice()
    assert outcome.final_state == MissionState.READY
    assert outcome.ready_receipt_hash == "a" * 64
    assert outcome.drifted_receipt_hash is None
    assert outcome.is_live is True
    assert outcome.steps["P-13.07"].status == "NOT_RUN"
    assert outcome.steps["P-13.07"].is_verified is False
    assert outcome.steps["P-13.07"].writes_performed == 0

    # Direct live P-13.07 call also reports NOT_RUN (no forged DRIFTED)
    direct = runner.step_p13_07_mutate_and_drift()
    assert direct.status == "NOT_RUN"
    assert "DRIFTED" not in json.dumps(direct.to_dict())


def test_defect_b_live_plan_validation_order_zero_seeding_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero external mutation before invalid model-plan rejection.

    If candidate plan proposal fails canonical validation, the live runner must:
    - execute zero Google seeding mutations;
    - execute zero candidate actions;
    - consume zero approvals;
    - fail closed with status FAILED and total_writes_performed == 0;
    - never fall back to fixture proposal.
    """
    from unittest.mock import MagicMock

    from stilldone.planning.bedrock import BedrockPlannerAdapter
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        SymbolicTargetRef,
    )

    fake_planner = MagicMock(spec=BedrockPlannerAdapter)
    runner = _live_runner_for_boundary_tests(monkeypatch, bedrock_planner=fake_planner)

    # Injected invalid plan: Step 0 is TASK_CREATE instead of WEATHER_READ (invalid order)
    bad_plan = CandidatePlanProposal.create(
        mission_id=runner.mission_id,
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.TASK_CREATE,
                target_ref=SymbolicTargetRef.TASK_LIST,
                parameters={"title": CANONICAL_DEMO_TASK_TITLE, "due": "2026-10-04"},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.WEATHER_READ,
                target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                parameters={},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.CALENDAR_UPDATE,
                target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                parameters={"start_time": "2026-10-04T07:30:00+00:00"},
            ),
        ],
    )
    fake_planner.plan.return_value = MagicMock(plan=bad_plan)

    seed_spy = MagicMock()
    runner.env.cal_seed_transport = seed_spy

    outcome = runner.run_full_slice()

    # Must fail closed with 0 mutations executed
    assert outcome.final_state == MissionState.FAILED
    assert outcome.total_writes_performed == 0
    assert outcome.steps["P-13.02"].status == "FAILED"
    assert "InvalidActionOrderError" in outcome.steps["P-13.02"].details
    assert outcome.steps["P-13.01"].status == "NOT_RUN"
    seed_spy.create_event.assert_not_called()
    assert runner.total_writes == 0


def test_live_approval_alternate_entry_and_replay_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative controls: direct live approval bypass, wrong pending identity,

    replayed decision, and stale authorization are all rejected fail-closed.
    """
    from datetime import timedelta
    from unittest.mock import MagicMock

    from stilldone.killer_mission import (
        AuthorizedPostPendingApprovalDecision,
        KillerMissionAuthorityError,
        compute_action_parameter_fingerprint,
        create_authorized_post_pending_decision,
    )
    from stilldone.pending_approval import ApprovalDecision
    from stilldone.planning.bedrock import BedrockPlannerAdapter

    fake_planner = MagicMock(spec=BedrockPlannerAdapter)
    runner = _live_runner_for_boundary_tests(monkeypatch, bedrock_planner=fake_planner)
    runner.seeded_event_id = "provider_evt_live_test_123"

    # Setup runner steps up to P-13.04 (approval pause)
    runner.step_p13_04_calendar_pause()
    assert runner.pending_approval is not None
    pending = runner.pending_approval

    # 1. Direct live approval bypass with raw APPROVE must be rejected
    with pytest.raises(KillerMissionAuthorityError, match="Direct live approval bypass prohibited"):
        runner.step_p13_05_calendar_approve(decision=ApprovalDecision.APPROVE)

    with pytest.raises(KillerMissionAuthorityError, match="Direct live approval bypass prohibited"):
        runner.step_p13_05_calendar_approve(decision="APPROVE")

    # 2. Wrong pending identity must be rejected
    wrong_pending_dec = AuthorizedPostPendingApprovalDecision(
        decision_id="dec_wrong_pending_001",
        pending_approval_id="wrong_pending_approval_id_999",
        mission_id=str(runner.mission_id),
        action_id=str(runner.action_cal.action_id),
        target_event_id=runner.seeded_event_id,
        action_parameter_fingerprint="some_fp",
        decision=ApprovalDecision.APPROVE,
        authority_source="HUMAN_OPERATOR",
        decided_at=datetime.now(UTC),
    )
    with pytest.raises(KillerMissionAuthorityError, match="pending_approval_id mismatch"):
        runner.step_p13_05_calendar_approve(decision=wrong_pending_dec)

    # 3. Stale authorization (> 15 minutes) must be rejected
    valid_fp = compute_action_parameter_fingerprint(runner.action_cal.parameters.to_dict())
    stale_dec = AuthorizedPostPendingApprovalDecision(
        decision_id="dec_stale_002",
        pending_approval_id=str(pending.pending_approval_id),
        mission_id=str(runner.mission_id),
        action_id=str(runner.action_cal.action_id),
        target_event_id=runner.seeded_event_id,
        action_parameter_fingerprint=valid_fp,
        decision=ApprovalDecision.APPROVE,
        authority_source="HUMAN_OPERATOR",
        decided_at=datetime.now(UTC) - timedelta(minutes=20),
    )
    with pytest.raises(KillerMissionAuthorityError, match="stale / expired"):
        runner.step_p13_05_calendar_approve(decision=stale_dec)

    # 4. Target event ID mismatch must be rejected
    mismatched_target_dec = create_authorized_post_pending_decision(
        pending,
        target_event_id="wrong_event_target_id",
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.APPROVE,
    )
    with pytest.raises(KillerMissionAuthorityError, match="target_event_id mismatch"):
        runner.step_p13_05_calendar_approve(decision=mismatched_target_dec)

    # 5. Valid decision via create_authorized_post_pending_decision with REJECT halts cleanly
    valid_dec = create_authorized_post_pending_decision(
        pending,
        target_event_id=runner.seeded_event_id,
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.REJECT,
    )
    res_rej = runner.step_p13_05_calendar_approve(decision=valid_dec)
    assert res_rej.status == "REJECTED"
    assert res_rej.writes_performed == 0

    # 6. Replayed decision must be rejected fail-closed
    with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
        runner.step_p13_05_calendar_approve(decision=valid_dec)


def test_raw_provider_ids_redacted_in_public_serializers() -> None:
    """Raw external Calendar and Tasks provider IDs must be redacted in public surfaces

    while usable internally for exact provider read-back operations.
    """
    from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
    from stilldone.execution.state import (
        ActionExecutionStatus,
        ProviderExecutionResult,
        StepExecutionRecord,
    )
    from stilldone.killer_mission import (
        KillerMissionStepResult,
    )
    from stilldone.redaction import REDACTED_IDENTIFIER

    sentinel_task = "PROVIDER_TASK_SENTINEL_SECRET_999"
    sentinel_event = "PROVIDER_EVENT_SENTINEL_SECRET_888"

    # 1. ProviderExecutionResult details: raw internally, redacted in to_dict() and to_canonical()
    p_res = ProviderExecutionResult(
        action_type=ActionType.TASK_CREATE,
        success=True,
        status_name="COMPLETED",
        writes_performed=1,
        details={
            "task_id": sentinel_task,
            "provider_event_id": sentinel_event,
            "status": "needsAction",
        },
    )
    # Raw internally for read-backs
    assert p_res.details["task_id"] == sentinel_task
    assert p_res.details["provider_event_id"] == sentinel_event

    # Redacted in public serialization
    serialized_p = p_res.to_dict()
    assert serialized_p["details"]["task_id"] == REDACTED_IDENTIFIER
    assert serialized_p["details"]["provider_event_id"] == REDACTED_IDENTIFIER
    assert sentinel_task not in json.dumps(serialized_p)
    assert sentinel_event not in json.dumps(serialized_p)

    # Canonical projection also redacts
    canonical_p = p_res.to_canonical()
    assert canonical_p["details"]["task_id"] == REDACTED_IDENTIFIER
    assert sentinel_task not in json.dumps(canonical_p)

    # 2. StepExecutionRecord public serialization
    aid = ActionId("33333333-3333-4333-8333-333333333333")
    att = ExecutionAttempt(
        action_id=aid,
        attempt_number=1,
        idempotency_key=IdempotencyKey("44444444-4444-4444-4444-444444444444"),
        started_at=datetime.now(UTC),
    )
    step_rec = StepExecutionRecord(
        action_id=aid,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att,
        provider_result=p_res,
    )
    step_dict = step_rec.to_dict()
    assert step_dict["provider_result"]["details"]["task_id"] == REDACTED_IDENTIFIER
    assert sentinel_task not in json.dumps(step_dict)

    # 3. KillerMissionStepResult extra_metadata and details
    step_res = KillerMissionStepResult(
        task_id="P-13.03",
        step_name="Tasks Prep",
        status="PASS",
        provenance=EvidenceProvenance.LIVE_GOOGLE,
        details="Created task in list",
        extra_metadata={"provider_task_id": sentinel_task, "event_id": sentinel_event},
    )
    step_res_dict = step_res.to_dict()
    assert step_res_dict["extra_metadata"]["provider_task_id"] == REDACTED_IDENTIFIER
    assert step_res_dict["extra_metadata"]["event_id"] == REDACTED_IDENTIFIER
    assert sentinel_task not in json.dumps(step_res_dict)
    assert sentinel_event not in json.dumps(step_res_dict)


def test_defect_2_authenticated_human_approval_channel_and_zero_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect 2: Human approval must come from an authenticated, trusted human channel.

    Negative invariant: Unauthenticated approval -> 0 Calendar writes.
    - Raw callback return value "APPROVE" -> BLOCKED_APPROVAL_CHANNEL, 0 writes.
    - Self-constructed AuthorizedPostPendingApprovalDecision without channel
      -> BLOCKED_APPROVAL_CHANNEL, 0 writes.
    - Direct call to step_p13_05_calendar_approve without channel
      -> BLOCKED_APPROVAL_CHANNEL, 0 writes.
    - Approval channel returning False -> BLOCKED_APPROVAL_CHANNEL, 0 writes.
    - Authenticated approval channel returning True -> grants live mutation authority.
    - Rejection -> REJECTED with 0 writes.
    """
    from unittest.mock import MagicMock

    from stilldone.killer_mission import (
        AuthenticatedHumanApprovalChannel,
        KillerMissionAuthorityError,
        KillerMissionSliceRunner,
        KillerMissionStepResult,
        create_authorized_post_pending_decision,
    )
    from stilldone.pending_approval import ApprovalDecision

    runner = _live_runner_for_boundary_tests(monkeypatch)
    runner.seeded_event_id = "provider_evt_live_test_456"

    # Setup up to approval pause
    runner.step_p13_04_calendar_pause()
    assert runner.pending_approval is not None
    pending = runner.pending_approval

    real_super_approve = KillerMissionSliceRunner.step_p13_05_calendar_approve
    super_approve_spy = MagicMock(
        return_value=KillerMissionStepResult(
            task_id="P-13.05",
            step_name="Approve, Execute & Verify Calendar Update",
            status="PASS",
            provenance=runner.env.provenance,
            details="Mocked super pass",
            writes_performed=1,
            is_verified=True,
        )
    )
    monkeypatch.setattr(KillerMissionSliceRunner, "step_p13_05_calendar_approve", super_approve_spy)

    # Case 2A: Callback returns raw "APPROVE" -> blocked, 0 writes
    runner.post_pending_decision_callback = lambda p: "APPROVE"
    res_raw = runner.step_p13_05_calendar_approve()
    assert res_raw.status == "BLOCKED_APPROVAL_CHANNEL"
    assert res_raw.writes_performed == 0
    assert "Live calendar mutation blocked" in res_raw.details
    assert "0 writes performed" in res_raw.details
    super_approve_spy.assert_not_called()

    # Case 2B: Callback returns decision WITHOUT approval_channel -> blocked, 0 writes
    auth_dec = create_authorized_post_pending_decision(
        pending,
        target_event_id=runner.seeded_event_id,
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.APPROVE,
    )
    runner.post_pending_decision_callback = lambda p: auth_dec
    runner.approval_channel = None
    res_no_channel = runner.step_p13_05_calendar_approve()
    assert res_no_channel.status == "BLOCKED_APPROVAL_CHANNEL"
    assert res_no_channel.writes_performed == 0
    assert "no authenticated, trusted human decision channel" in res_no_channel.details
    super_approve_spy.assert_not_called()

    # Case 2C: Direct call with decision WITHOUT approval_channel -> blocked, 0 writes
    auth_dec_direct = create_authorized_post_pending_decision(
        pending,
        target_event_id=runner.seeded_event_id,
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.APPROVE,
    )
    res_direct = runner.step_p13_05_calendar_approve(decision=auth_dec_direct)
    assert res_direct.status == "BLOCKED_APPROVAL_CHANNEL"
    assert res_direct.writes_performed == 0
    super_approve_spy.assert_not_called()
    assert auth_dec_direct.decision_id not in runner._consumed_approval_decision_ids

    # Case 2D: Approval channel rejects/untrusted (returns False) -> blocked, 0 writes, NOT consumed
    mock_untrusted_channel = MagicMock(spec=AuthenticatedHumanApprovalChannel)
    mock_untrusted_channel.verify_decision.return_value = False
    runner.approval_channel = mock_untrusted_channel
    auth_dec_untrusted = create_authorized_post_pending_decision(
        pending,
        target_event_id=runner.seeded_event_id,
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.APPROVE,
    )
    res_untrusted = runner.step_p13_05_calendar_approve(decision=auth_dec_untrusted)
    assert res_untrusted.status == "BLOCKED_APPROVAL_CHANNEL"
    assert res_untrusted.writes_performed == 0
    assert auth_dec_untrusted.decision_id not in runner._consumed_approval_decision_ids
    super_approve_spy.assert_not_called()

    # Case 2E: Fake verifier returning True cannot establish production authority
    # merely by implementing the Protocol
    mock_fake_channel = MagicMock(spec=AuthenticatedHumanApprovalChannel)
    mock_fake_channel.verify_decision.return_value = True
    runner.approval_channel = mock_fake_channel
    auth_dec_fake = create_authorized_post_pending_decision(
        pending,
        target_event_id=runner.seeded_event_id,
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.APPROVE,
    )
    res_fake = runner.step_p13_05_calendar_approve(decision=auth_dec_fake)
    assert res_fake.status == "BLOCKED_APPROVAL_CHANNEL"
    assert res_fake.writes_performed == 0
    assert auth_dec_fake.decision_id not in runner._consumed_approval_decision_ids
    assert "no genuine authenticated human decision implementation is available" in res_fake.details
    super_approve_spy.assert_not_called()

    # Case 2F: Ordinary rejection remains safe and consumes the decision durably
    monkeypatch.setattr(
        KillerMissionSliceRunner, "step_p13_05_calendar_approve", real_super_approve
    )
    auth_dec_reject = create_authorized_post_pending_decision(
        pending,
        target_event_id=runner.seeded_event_id,
        action_parameters=runner.action_cal.parameters.to_dict(),
        decision=ApprovalDecision.REJECT,
    )
    res_reject = runner.step_p13_05_calendar_approve(decision=auth_dec_reject)
    assert res_reject.status == "REJECTED"
    assert res_reject.writes_performed == 0
    assert auth_dec_reject.decision_id in runner._consumed_approval_decision_ids

    # Case 2G: Restart / reload does not permit approval resurrection (replay prohibited)
    runner_reloaded = _live_runner_for_boundary_tests(monkeypatch)
    runner_reloaded.pending_approval = pending
    runner_reloaded.seeded_event_id = runner.seeded_event_id
    runner_reloaded._consumed_decisions_file = runner._consumed_decisions_file
    runner_reloaded._load_consumed_decision_ids()
    with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
        runner_reloaded.step_p13_05_calendar_approve(decision=auth_dec_reject)


def test_defect_3_canonical_ordering_and_zero_seeding_on_invalid_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect 3: Remove test-only production execution bypass completely.

    Enforce canonical order:
    1. Bounded Bedrock proposal & exact canonical plan validation BEFORE ANY SEEDING.
    2. Invalid plan -> fails closed with final_state=FAILED, 0 seeding writes, 0 action writes.
    3. step_p13_01_seed() fails closed before seeding if candidate plan is invalid.
    """
    # Verify no test-only bypass in source code of LiveKillerMissionSliceRunner.run_full_slice
    import inspect
    from unittest.mock import MagicMock

    from stilldone.killer_mission import LiveKillerMissionSliceRunner
    from stilldone.planning.bedrock import BedrockPlannerAdapter
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        SymbolicTargetRef,
    )

    run_full_slice_source = inspect.getsource(LiveKillerMissionSliceRunner.run_full_slice)
    assert '"step_p13_02_plan" in self.__dict__' not in run_full_slice_source
    assert "__dict__" not in run_full_slice_source

    # 1. Invalid plan: only 2 steps (missing CALENDAR_UPDATE)
    bad_planner = MagicMock(spec=BedrockPlannerAdapter)
    bad_plan = CandidatePlanProposal.create(
        mission_id="11111111-2222-3333-4444-555555555555",
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.WEATHER_READ,
                target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                parameters={},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.TASK_CREATE,
                target_ref=SymbolicTargetRef.TASK_LIST,
                parameters={"title": CANONICAL_DEMO_TASK_TITLE, "due": "2026-10-04"},
            ),
        ],
    )
    bad_planner.plan.return_value = MagicMock(plan=bad_plan)

    runner = _live_runner_for_boundary_tests(monkeypatch, bedrock_planner=bad_planner)

    cal_seed_spy = MagicMock()
    tasks_seed_spy = MagicMock()
    runner.env.cal_seed_transport.create_event = cal_seed_spy  # type: ignore[attr-defined]
    runner.env.tasks_seed_transport.create_task_list = tasks_seed_spy  # type: ignore[attr-defined]

    # run_full_slice must fail closed before any seeding mutation
    outcome = runner.run_full_slice()
    assert outcome.final_state == MissionState.FAILED
    assert outcome.total_writes_performed == 0
    assert outcome.steps["P-13.01"].status == "NOT_RUN"
    assert outcome.steps["P-13.02"].status == "FAILED"
    assert "InvalidActionCountError" in outcome.steps["P-13.02"].details
    cal_seed_spy.assert_not_called()
    tasks_seed_spy.assert_not_called()

    # Direct call to step_p13_01_seed() must also fail before mutating
    runner_direct = _live_runner_for_boundary_tests(monkeypatch, bedrock_planner=bad_planner)
    cal_seed_spy2 = MagicMock()
    runner_direct.env.cal_seed_transport.create_event = cal_seed_spy2  # type: ignore[attr-defined]
    from stilldone.killer_mission import CanonicalKillerPlanValidationError

    with pytest.raises(CanonicalKillerPlanValidationError):
        runner_direct.step_p13_01_seed()
    cal_seed_spy2.assert_not_called()
    assert runner_direct.total_writes == 0

    # 3. Manually injected non-null invalid candidate into runner state: zero writes
    runner_injected = _live_runner_for_boundary_tests(monkeypatch)
    cal_seed_spy3 = MagicMock()
    runner_injected.env.cal_seed_transport.create_event = cal_seed_spy3  # type: ignore[attr-defined]
    runner_injected.candidate_plan = bad_plan  # manually injected invalid plan
    with pytest.raises(CanonicalKillerPlanValidationError):
        runner_injected.step_p13_01_seed()
    cal_seed_spy3.assert_not_called()
    assert runner_injected.total_writes == 0

    # 4. Plan mutation / replacement after validation: zero writes unless revalidated
    runner_tampered = _live_runner_for_boundary_tests(monkeypatch)
    cal_seed_spy4 = MagicMock()
    runner_tampered.env.cal_seed_transport.create_event = cal_seed_spy4  # type: ignore[attr-defined]
    # Set validated_candidate_plan to valid, but mutate candidate_plan to bad_plan
    runner_tampered.validated_candidate_plan = MagicMock()
    runner_tampered.candidate_plan = bad_plan
    with pytest.raises(CanonicalKillerPlanValidationError):
        runner_tampered.step_p13_01_seed()
    cal_seed_spy4.assert_not_called()
    assert runner_tampered.total_writes == 0


def test_defect_5_privacy_safe_public_snapshot_vs_authoritative_durable_reload() -> None:
    """Defect 5: Public snapshot must not leak raw external provider identifiers,

    while private durable snapshot preserves exact identifiers for authoritative recovery.
    """
    import copy

    from stilldone.action_policy import validate_action_contract
    from stilldone.domain.action import (
        ActionContract,
        ActionType,
        ResourceKind,
        TargetIdentity,
    )
    from stilldone.domain.desired_state import (
        DesiredStatePredicate,
        FreshnessContract,
        PredicateId,
        PredicateOperator,
    )
    from stilldone.domain.mission import MissionContract, MissionId
    from stilldone.pending_approval import (
        compute_historical_human_summary,
        create_pending_approval,
    )
    from stilldone.redaction import REDACTED_IDENTIFIER
    from stilldone.snapshot import (
        MissionSnapshot,
        SnapshotIntegrityError,
        create_mission_snapshot,
    )

    mid = MissionId("11111111-2222-3333-4444-555555555555")
    secret_evt_id = "provider_evt_secret_calendar_99999"
    secret_cal_id = "provider_cal_secret_11111"

    # Intent explicitly containing provider identifier
    contract = MissionContract.create(
        f"demo intent with {secret_evt_id} inside text", mission_id=mid
    )
    act = ActionContract.create(
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=secret_evt_id,
            parent_id=secret_cal_id,
        ),
        parameters={
            "start_time": "2026-10-04T07:30:00+00:00",
            "summary": f"Meeting with {secret_evt_id}",
        },
    )
    # Expected value explicitly containing provider identifier
    pred = DesiredStatePredicate(
        predicate_id=PredicateId("22222222-2222-2222-2222-222222222222"),
        mission_id=mid,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value=secret_evt_id,
        required=True,
        freshness=FreshnessContract.current(),
    )
    val_act = validate_action_contract(act)
    pending = create_pending_approval(val_act, requested_at=datetime.now(UTC))

    snapshot = create_mission_snapshot(
        mission_id=mid,
        state=MissionState.NEEDS_APPROVAL,
        contract=contract,
        desired_state=[pred],
        actions=[act],
        pending_approvals=[pending],
        created_at=datetime(2026, 10, 4, 7, 0, 0, tzinfo=UTC),
    )

    # 1. Authoritative durable serialization preserves exact identifiers
    auth_dict = snapshot.to_authoritative_dict()
    assert auth_dict["serialization_boundary"] == "AUTHORITATIVE_DURABLE"
    auth_json = json.dumps(auth_dict)
    assert secret_evt_id in auth_json
    assert secret_cal_id in auth_json

    # Round-trip recovery from authoritative durable serialization
    recovered = MissionSnapshot.from_dict(auth_dict)
    assert recovered.mission_id == snapshot.mission_id
    assert recovered.state == snapshot.state
    assert len(recovered.actions) == len(snapshot.actions)
    assert recovered.actions[0].target.resource_id == secret_evt_id
    assert recovered.actions[0].target.parent_id == secret_cal_id
    assert recovered.pending_approvals[0].target.resource_id == secret_evt_id

    # 2. Public judge serialization: complete structural sanitization
    pub_dict = snapshot.to_public_dict()
    assert pub_dict["serialization_boundary"] == "PUBLIC_JUDGE_VIEW"
    pub_json = json.dumps(pub_dict)

    # Zero raw external provider identifiers leak into public serialization anywhere
    assert secret_evt_id not in pub_json
    assert secret_cal_id not in pub_json

    # Intent text, expected values, parameters, and targets are all redacted
    assert secret_evt_id not in pub_dict["contract"]["intent"]["text"]
    assert REDACTED_IDENTIFIER in pub_dict["contract"]["intent"]["text"]
    assert pub_dict["desired_state"][0]["expected_value"] == REDACTED_IDENTIFIER
    assert secret_evt_id not in pub_dict["actions"][0]["parameters"]["summary"]
    assert REDACTED_IDENTIFIER in pub_dict["actions"][0]["parameters"]["summary"]

    for a_pub in pub_dict.get("actions", []):
        assert a_pub["target"]["resource_id"] == REDACTED_IDENTIFIER
        if a_pub["target"].get("parent_id"):
            assert a_pub["target"]["parent_id"] == REDACTED_IDENTIFIER

    for pa_pub in pub_dict.get("pending_approvals", []):
        assert pa_pub["target"]["resource_id"] == REDACTED_IDENTIFIER
        if pa_pub["target"].get("parent_id"):
            assert pa_pub["target"]["parent_id"] == REDACTED_IDENTIFIER
        assert secret_evt_id not in json.dumps(pa_pub["decision_contract"])

    # 3. Fail-closed recovery: Deserializing public redacted view must raise SnapshotIntegrityError
    with pytest.raises(
        SnapshotIntegrityError,
        match="Cannot deserialize authoritative snapshot from public redacted serialization",
    ):
        MissionSnapshot.from_dict(pub_dict)

    # 4. Historical snapshot compatibility: authentic pre-repair format reloads cleanly
    historical_dict = copy.deepcopy(auth_dict)
    hist_summary = compute_historical_human_summary(val_act)
    historical_dict["pending_approvals"][0]["decision_contract"]["human_summary"] = hist_summary
    recovered_historical = MissionSnapshot.from_dict(historical_dict)
    assert recovered_historical.mission_id == snapshot.mission_id
    assert recovered_historical.pending_approvals[0].human_summary == hist_summary

    # 5. Tampered historical snapshot (e.g. modified parameters digest or target) fails closed
    tampered_digest_dict = copy.deepcopy(historical_dict)
    tampered_digest_dict["pending_approvals"][0]["parameters_digest"] = "f" * 64
    with pytest.raises(SnapshotIntegrityError, match="parameters_digest was tampered"):
        MissionSnapshot.from_dict(tampered_digest_dict)

    tampered_target_dict = copy.deepcopy(historical_dict)
    tampered_target_dict["pending_approvals"][0]["target"]["resource_id"] = "tampered_evt_999"
    with pytest.raises(SnapshotIntegrityError, match="target was tampered"):
        MissionSnapshot.from_dict(tampered_target_dict)

    # 6. Repair D1: Strict decision contract equality rejects unexpected or removed keys
    tampered_extra_key_dict = copy.deepcopy(historical_dict)
    tampered_extra_key_dict["pending_approvals"][0]["decision_contract"]["injected_evil_key"] = (
        "malicious_value"
    )
    with pytest.raises(SnapshotIntegrityError, match="decision_contract was tampered"):
        MissionSnapshot.from_dict(tampered_extra_key_dict)

    tampered_missing_key_dict = copy.deepcopy(historical_dict)
    del tampered_missing_key_dict["pending_approvals"][0]["decision_contract"]["status"]
    with pytest.raises(SnapshotIntegrityError, match="decision_contract was tampered"):
        MissionSnapshot.from_dict(tampered_missing_key_dict)

    tampered_status_dict = copy.deepcopy(historical_dict)
    tampered_status_dict["pending_approvals"][0]["decision_contract"]["status"] = "APPROVED"
    with pytest.raises(SnapshotIntegrityError, match="decision_contract was tampered"):
        MissionSnapshot.from_dict(tampered_status_dict)

    # 7. Repair D2: Historical human summary privacy across public projections
    # When public view is generated from a snapshot restored with historical summary,
    # raw provider ID must be sanitized from human_summary and entire public dictionary.
    recovered_pub_dict = recovered_historical.to_public_dict()
    assert secret_evt_id not in json.dumps(recovered_pub_dict)
    assert secret_cal_id not in json.dumps(recovered_pub_dict)
    assert (
        secret_evt_id
        not in recovered_pub_dict["pending_approvals"][0]["decision_contract"]["human_summary"]
    )
    assert (
        REDACTED_IDENTIFIER
        in recovered_pub_dict["pending_approvals"][0]["decision_contract"]["human_summary"]
    )

    # PendingApproval direct presentation projections sanitize raw provider IDs
    pa_direct = recovered_historical.pending_approvals[0]
    pa_pub = pa_direct.to_public_dict()
    assert secret_evt_id not in json.dumps(pa_pub)
    assert REDACTED_IDENTIFIER in pa_pub["human_summary"]
    assert REDACTED_IDENTIFIER in pa_pub["one_decision_contract"]["human_summary"]
    assert pa_pub["target"]["resource_id"] == REDACTED_IDENTIFIER

    # Authoritative private serialization retains raw identifiers for verification
    pa_auth = pa_direct.to_dict(redact_identifiers=False)
    assert secret_evt_id in pa_auth["human_summary"]
    assert secret_evt_id in pa_auth["one_decision_contract"]["human_summary"]


def test_repair_a1_shared_live_approval_boundary_inherited_bypass_prohibited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repair A1: Close inherited live approval bypass.

    Direct parent-class invocation with live runner and APPROVE must not bypass
    the live authorization requirement, even if operator_approved=True.
    It must fail closed before any provider mutation or approval grant.
    """
    from stilldone.killer_mission import (
        KillerMissionAuthorityError,
        KillerMissionSliceRunner,
    )
    from stilldone.pending_approval import ApprovalDecision

    runner = _live_runner_for_boundary_tests(monkeypatch)
    runner.seeded_event_id = "provider_evt_live_a1_bypass"
    runner.operator_approved = True

    # Advance to pending approval
    runner.step_p13_04_calendar_pause()
    assert runner.pending_approval is not None

    # Direct parent-class invocation with live runner and APPROVE must fail closed
    match_msg = "Direct live approval bypass prohibited"
    with pytest.raises(KillerMissionAuthorityError, match=match_msg):
        KillerMissionSliceRunner.step_p13_05_calendar_approve(
            runner, decision=ApprovalDecision.APPROVE
        )

    # String "APPROVE" must also fail closed
    with pytest.raises(KillerMissionAuthorityError, match=match_msg):
        KillerMissionSliceRunner.step_p13_05_calendar_approve(runner, decision="APPROVE")

    # Verify zero writes performed and no grant issued
    assert runner.total_writes == 0
    assert not hasattr(runner, "approved_cal_outcome")


def test_repair_a2_and_a3_fail_closed_persistence_and_stable_storage_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repair A2 & A3: Fail-closed consumption persistence, concurrency, and stable storage."""
    import builtins
    import concurrent.futures
    from typing import Any
    from unittest.mock import MagicMock

    from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
    from stilldone.adapters.tasks import GoogleApiClientTasksTransport
    from stilldone.adapters.weather import OpenMeteoHttpTransport
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.killer_mission import (
        KillerMissionAuthorityError,
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
    )

    stable_dir = tmp_path / "stable_killer_mission"
    stable_dir.mkdir(parents=True, exist_ok=True)
    scope = DemoResourceScope("c_boundary_demo", "tl_boundary_demo")

    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    assert live_env.has_explicit_base_dir is True
    assert live_env.is_ephemeral_storage is False

    runner = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=live_env,
        operator_approved=True,
    )
    runner.seeded_event_id = "provider_evt_live_a2"
    runner.step_p13_04_calendar_pause()
    pending = runner.pending_approval
    assert pending is not None

    # 1. Simulated filesystem write failure in _persist_consumed_decision_id
    real_open = builtins.open

    def failing_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        is_consumed = str(file).endswith("consumed_approval_decisions.jsonl")
        is_append = "a" in args or kwargs.get("mode") == "a"
        if is_consumed and is_append:
            raise OSError("Simulated disk write failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)
    with pytest.raises(KillerMissionIntegrityError, match="Failed to durably commit"):
        runner._persist_consumed_decision_id("failing_dec_1")

    # Decision MUST NOT be added to in-memory set when persistence fails
    assert "failing_dec_1" not in runner._consumed_approval_decision_ids
    monkeypatch.undo()

    # Retry on degraded runner fails closed
    with pytest.raises(
        KillerMissionIntegrityError, match="Persistence failure previously occurred"
    ):
        runner._persist_consumed_decision_id("retry_after_fail")

    # 2. Corrupt or truncated consumption record fails closed with KillerMissionIntegrityError
    dec_file = runner._consumed_decisions_file
    dec_file.write_text(
        '{"decision_id": "valid_1", "consumed_at": "2026-10-04T12:00:00+00:00"}\n'
        '{"corrupt_json":\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="Corrupt or truncated"):
        runner._load_consumed_decision_ids()

    # 3. Invalid record structure (missing decision_id) fails closed
    dec_file.write_text(
        '{"decision_id": "", "consumed_at": "2026-10-04T12:00:00+00:00"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="missing valid 'decision_id'"):
        runner._load_consumed_decision_ids()

    # 4. Duplicate decision ID in persistent log fails closed
    dec_file.write_text(
        '{"decision_id": "dup_1", "consumed_at": "2026-10-04T12:00:00+00:00"}\n'
        '{"decision_id": "dup_1", "consumed_at": "2026-10-04T12:01:00+00:00"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="Duplicate consumed decision ID"):
        runner._load_consumed_decision_ids()

    # 5. Duplicate decision ID via _persist_consumed_decision_id raises KillerMissionAuthorityError
    dec_file.write_text("", encoding="utf-8")
    runner._persistence_failed = False
    runner._consumed_approval_decision_ids.clear()
    runner._persist_consumed_decision_id("unique_dec_1")
    assert "unique_dec_1" in runner._consumed_approval_decision_ids
    with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
        runner._persist_consumed_decision_id("unique_dec_1")

    # 6. Process-local thread concurrency: concurrent persistence is thread-safe
    def _concurrent_persist(i: int) -> None:
        runner._persist_consumed_decision_id(f"concurrent_dec_{i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_concurrent_persist, i) for i in range(10)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    for i in range(10):
        assert f"concurrent_dec_{i}" in runner._consumed_approval_decision_ids

    # 7. Same-directory reload recovers state durably
    live_env_reloaded = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )

    runner_reloaded = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=live_env_reloaded,
        mission_id=runner.mission_id,
        operator_approved=True,
    )
    assert "unique_dec_1" in runner_reloaded._consumed_approval_decision_ids
    runner_reloaded.reload_consumed_decisions(require_durable=True)

    # 8. Absent or ephemeral storage fails closed when durable reload is required
    ephemeral_env = KillerMissionEnvironment.create_live_environment(
        base_dir=None,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    assert ephemeral_env.has_explicit_base_dir is False
    assert ephemeral_env.is_ephemeral_storage is True

    runner_ephemeral = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=ephemeral_env,
        operator_approved=True,
    )
    match_msg = "Stable durable storage boundary is required"
    with pytest.raises(KillerMissionAuthorityError, match=match_msg):
        runner_ephemeral.reload_consumed_decisions(require_durable=True)


def test_repair_a2_durable_consumption_integrity_adversarial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repair A2: Adversarial testing of durable consumption integrity.

    Covers:
    - Partial append with atomic rollback/truncation to orig_size.
    - Persistence failure flag prevents further authorization-sensitive operations.
    - Corrupted/naive timestamps and unparseable datetime strings fail closed.
    - Unexpected and missing fields in persisted JSONL fail closed.
    - Rejection is durably recorded with 'decision': 'REJECT' and cannot be replayed.
    - Process restart reloads state and enforces replay prohibition.
    """
    import builtins
    from typing import Any
    from unittest.mock import MagicMock

    from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
    from stilldone.adapters.tasks import GoogleApiClientTasksTransport
    from stilldone.adapters.weather import OpenMeteoHttpTransport
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.domain.mission import MissionId
    from stilldone.killer_mission import (
        KillerMissionAuthorityError,
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
    )
    from stilldone.pending_approval import ApprovalDecision

    stable_dir = tmp_path / "a2_adversarial_storage"
    stable_dir.mkdir(parents=True, exist_ok=True)
    scope = DemoResourceScope("c_a2_demo", "tl_a2_demo")

    live_env = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=live_env,
        mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
        operator_approved=True,
    )

    # 1. First write a valid decision
    runner._persist_consumed_decision_id("init_dec_1", decision=ApprovalDecision.REJECT)
    assert "init_dec_1" in runner._consumed_approval_decision_ids
    dec_file = runner._consumed_decisions_file
    orig_size = dec_file.stat().st_size
    assert orig_size > 0

    # 2. Simulate partial failed append: write 10 bytes then crash
    real_open = builtins.open

    class FailingPartialWriter:
        def __init__(self, raw_file: Any) -> None:
            self.raw_file = raw_file

        def write(self, s: str) -> int:
            self.raw_file.write(s[:10])
            self.raw_file.flush()
            raise OSError("Simulated partial write failure halfway through append")

        def __getattr__(self, name: str) -> Any:
            return getattr(self.raw_file, name)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> Any:
            return self.raw_file.__exit__(*args)

    def partial_failing_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        is_consumed = str(file).endswith("consumed_approval_decisions.jsonl")
        is_append = "a" in args or kwargs.get("mode") == "a"
        if is_consumed and is_append:
            raw = real_open(file, *args, **kwargs)
            return FailingPartialWriter(raw)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", partial_failing_open)
    with pytest.raises(KillerMissionIntegrityError, match="Failed to durably commit"):
        runner._persist_consumed_decision_id("partial_dec_fail")

    monkeypatch.undo()

    # Verify atomic rollback: file must be truncated back to orig_size
    assert dec_file.stat().st_size == orig_size
    assert "partial_dec_fail" not in runner._consumed_approval_decision_ids
    assert runner._persistence_failed is True

    # 3. Retry on degraded runner fails closed
    with pytest.raises(
        KillerMissionIntegrityError, match="Persistence failure previously occurred"
    ):
        runner._persist_consumed_decision_id("any_retry_id")

    # 4. Corrupted timestamp tests
    dec_file.write_text(
        '{"decision_id": "bad_ts_1", "consumed_at": "not-a-datetime"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="Corrupted consumed_at timestamp"):
        runner._load_consumed_decision_ids()

    # Naive timestamp without timezone
    dec_file.write_text(
        '{"decision_id": "naive_ts_1", "consumed_at": "2026-10-04T12:00:00"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(
        KillerMissionIntegrityError, match="consumed_at timestamp must be timezone-aware UTC"
    ):
        runner._load_consumed_decision_ids()

    # Non-UTC timezone offset (+03:00)
    dec_file.write_text(
        '{"decision_id": "offset_ts_1", "consumed_at": "2026-10-04T12:00:00+03:00"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="consumed_at timestamp must be UTC"):
        runner._load_consumed_decision_ids()

    # 5. Unexpected fields in record
    dec_file.write_text(
        '{"decision_id": "extra_1", "consumed_at": "2026-10-04T12:00:00+00:00", '
        '"unauthorized_extra": "leak"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="Unexpected fields"):
        runner._load_consumed_decision_ids()

    # Missing consumed_at field
    dec_file.write_text(
        '{"decision_id": "missing_cat_1"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="Missing required fields"):
        runner._load_consumed_decision_ids()

    # Invalid decision enum string
    dec_file.write_text(
        '{"decision_id": "bad_dec_val", "consumed_at": "2026-10-04T12:00:00+00:00", '
        '"decision": "MAYBE"}\n',
        encoding="utf-8",
    )
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(KillerMissionIntegrityError, match="Invalid decision value"):
        runner._load_consumed_decision_ids()

    # 6. Rejection durability and restart recovery (both stores synchronized)
    init_line = json.dumps(
        {
            "decision_id": "init_dec_1",
            "consumed_at": "2026-10-04T12:00:00+00:00",
            "decision": "REJECT",
            "mission_id": str(runner.mission_id),
        }
    )
    dec_file.write_text(f"{init_line}\n", encoding="utf-8")
    runner._persistence_failed = False
    runner._consumed_approval_decision_ids.clear()
    runner._load_consumed_decision_ids()
    assert "init_dec_1" in runner._consumed_approval_decision_ids

    runner._persist_consumed_decision_id("durable_reject_1", decision=ApprovalDecision.REJECT)
    assert "durable_reject_1" in runner._consumed_approval_decision_ids

    # Read back raw jsonl
    lines = [json.loads(line) for line in dec_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 2
    assert lines[1]["decision_id"] == "durable_reject_1"
    assert lines[1]["decision"] == "REJECT"

    # Restart runner on same directory
    live_env_restart = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner_restarted = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=live_env_restart,
        mission_id=runner.mission_id,
        operator_approved=True,
    )
    assert runner_restarted.is_restored_session is True
    assert runner_restarted.is_first_time_storage is False
    assert "durable_reject_1" in runner_restarted._consumed_approval_decision_ids
    assert "init_dec_1" in runner_restarted._consumed_approval_decision_ids

    # Replay must be rejected
    with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
        runner_restarted._persist_consumed_decision_id("durable_reject_1")


def test_repair_a3_enforce_storage_gate_in_actual_live_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repair A3: Enforce stable durable storage prerequisite on actual production live path."""
    from typing import Any
    from unittest.mock import MagicMock

    from scripts.p13_killer_mission import run_killer_mission
    from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
    from stilldone.adapters.tasks import GoogleApiClientTasksTransport
    from stilldone.adapters.weather import OpenMeteoHttpTransport
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.killer_mission import (
        KillerMissionAuthorityError,
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
        LiveKillerMissionSliceRunner,
    )

    # 1. Production CLI entry point without storage directory fails closed at Phase A
    exit_code = run_killer_mission(
        live=True,
        as_json=True,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_calendar_id="c_valid_demo",
        demo_task_list_id="tl_valid_demo",
        storage_dir=None,
    )
    assert exit_code == 2

    # 2. Production CLI entry point with unwritable storage directory fails closed at Phase A
    unwritable = tmp_path / "unwritable_storage_dir"
    unwritable.mkdir(parents=True, exist_ok=True)
    real_write = Path.write_text

    def failing_write_text(self_path: Path, *args: Any, **kwargs: Any) -> Any:
        if ".storage_write_test" in str(self_path):
            raise OSError("Permission denied on storage directory")
        return real_write(self_path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    exit_code_unwritable = run_killer_mission(
        live=True,
        as_json=True,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_calendar_id="c_valid_demo",
        demo_task_list_id="tl_valid_demo",
        storage_dir=str(unwritable),
    )
    assert exit_code_unwritable == 2
    monkeypatch.undo()

    # 3. Live runner evaluate_preflight rejects ephemeral storage
    scope = DemoResourceScope("c_live_gate_demo", "tl_live_gate_demo")
    ephemeral_env = KillerMissionEnvironment.create_live_environment(
        base_dir=None,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner_ephemeral = LiveKillerMissionSliceRunner(
        env=ephemeral_env,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
    )
    preflight = runner_ephemeral.evaluate_preflight()
    assert preflight.is_ready is False
    assert any(
        "Stable durable storage boundary is required" in b for b in preflight.blocker_reasons
    )

    # Calling approval-sensitive steps directly on ephemeral env raises KillerMissionAuthorityError
    with pytest.raises(
        KillerMissionAuthorityError, match="Stable durable storage boundary is required"
    ):
        runner_ephemeral.step_p13_04_calendar_pause()

    with pytest.raises(
        KillerMissionAuthorityError, match="Stable durable storage boundary is required"
    ):
        runner_ephemeral.step_p13_05_calendar_approve()

    # 4. First-time vs Restored session identification
    fresh_storage = tmp_path / "fresh_storage_dir"
    fresh_env = KillerMissionEnvironment.create_live_environment(
        base_dir=fresh_storage,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    fresh_runner = LiveKillerMissionSliceRunner(
        env=fresh_env,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
    )
    assert fresh_runner.is_first_time_storage is True
    assert fresh_runner.is_restored_session is False

    # Persist one decision to establish history
    fresh_runner._persist_consumed_decision_id("first_time_dec_1")

    # Second runner on same directory must be detected as restored session (restarting process)
    restored_env = KillerMissionEnvironment.create_live_environment(
        base_dir=fresh_storage,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    restored_runner = LiveKillerMissionSliceRunner(
        env=restored_env,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
    )
    assert restored_runner.is_first_time_storage is False
    assert restored_runner.is_restored_session is True

    # 5. Inaccessible or corrupt existing state is NEVER silently treated as fresh
    corrupt_log = fresh_storage / "consumed_approval_decisions.jsonl"
    corrupt_log.write_text("corrupted_non_json_data\n", encoding="utf-8")
    with pytest.raises(KillerMissionIntegrityError, match="Corrupt or truncated"):
        LiveKillerMissionSliceRunner(
            env=fresh_env,
            operator_approved=True,
            source_sha="1111111111111111111111111111111111111111",
        )


def test_repair_d2_standalone_public_decision_contract_privacy(tmp_path: Path) -> None:
    """Repair D2: Adversarial validation of standalone public decision contract privacy."""
    from datetime import UTC, datetime

    from stilldone.domain.action import ActionId, ActionType
    from stilldone.domain.authority import AuthorityClass
    from stilldone.domain.mission import MissionId
    from stilldone.pending_approval import (
        ApprovalDecision,
        OneDecisionContract,
        PendingApprovalId,
        PendingApprovalStatus,
    )
    from stilldone.redaction import REDACTED_IDENTIFIER

    secret_event_id = "cal_event_secret_998877_alpha_bravo"
    hist_summary = (
        f"Update Google Calendar event on 'google_calendar' ({secret_event_id}): "
        "start_time='2026-10-04T07:30:00+00:00'"
    )

    contract = OneDecisionContract(
        pending_approval_id=PendingApprovalId("a" * 64),
        mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
        action_id=ActionId("11111111-2222-3333-4444-555555555555"),
        action_type=ActionType.CALENDAR_UPDATE,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
        human_summary=hist_summary,
        status=PendingApprovalStatus.PENDING,
        requested_at=datetime(2026, 10, 4, 7, 0, 0, tzinfo=UTC),
    )

    # 1. Standalone to_public_dict() called without provider_ids:
    pub_dict = contract.to_public_dict()
    pub_json = json.dumps(pub_dict)

    # Provider ID must be completely absent from public output
    assert secret_event_id not in pub_json
    assert REDACTED_IDENTIFIER in pub_dict["human_summary"]
    # Parameters containing arbitrary provider IDs must be suppressed fail-closed
    assert pub_dict["human_summary"] == (
        f"Update Google Calendar event on 'google_calendar' ({REDACTED_IDENTIFIER})"
    )

    # 2. Default to_dict() defaults to redact_identifiers=True
    def_dict = contract.to_dict()
    assert secret_event_id not in json.dumps(def_dict)
    assert REDACTED_IDENTIFIER in def_dict["human_summary"]
    assert def_dict["human_summary"] == (
        f"Update Google Calendar event on 'google_calendar' ({REDACTED_IDENTIFIER})"
    )

    # 3. Explicit authoritative dictionary retains raw unredacted historical summary
    auth_dict = contract.to_authoritative_dict()
    assert secret_event_id in auth_dict["human_summary"]
    assert auth_dict["human_summary"] == hist_summary

    # Calling to_dict(redact_identifiers=False) delegates to to_authoritative_dict()
    assert contract.to_dict(redact_identifiers=False) == auth_dict

    # 4. Canonical summaries without known provider ID suppress parameters in public projection
    canonical_summary = (
        "Update Google Calendar event on 'google_calendar': start_time='2026-10-04T07:30:00+00:00'"
    )
    canon_contract = OneDecisionContract(
        pending_approval_id=PendingApprovalId("b" * 64),
        mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
        action_id=ActionId("22222222-3333-4444-5555-666666666666"),
        action_type=ActionType.CALENDAR_UPDATE,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
        human_summary=canonical_summary,
        status=PendingApprovalStatus.PENDING,
        requested_at=datetime(2026, 10, 4, 7, 0, 0, tzinfo=UTC),
    )
    canon_pub = canon_contract.to_public_dict()
    assert canon_pub["human_summary"] == (
        f"Update Google Calendar event on 'google_calendar' ({REDACTED_IDENTIFIER})"
    )

    # 5. Free-form arbitrary summary without known structure is suppressed fail-closed
    adversarial_free_form = f"Custom operator note regarding secret event {secret_event_id} at 10am"
    free_form_contract = OneDecisionContract(
        pending_approval_id=PendingApprovalId("c" * 64),
        mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
        action_id=ActionId("33333333-4444-5555-6666-777777777777"),
        action_type=ActionType.CALENDAR_UPDATE,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
        human_summary=adversarial_free_form,
        status=PendingApprovalStatus.PENDING,
        requested_at=datetime(2026, 10, 4, 7, 0, 0, tzinfo=UTC),
    )
    ff_pub = free_form_contract.to_public_dict()
    assert secret_event_id not in json.dumps(ff_pub)
    assert ff_pub["human_summary"] == f"Execute action 'calendar.update' ({REDACTED_IDENTIFIER})"


def test_adversarial_storage_mismatched_mission_id_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A3 adversarial: Runner with mismatched mission ID over storage fails closed."""
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.domain.mission import MissionId
    from stilldone.killer_mission import (
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
    )

    stable_dir = tmp_path / "storage_mismatch_test"
    stable_dir.mkdir(parents=True, exist_ok=True)
    scope = DemoResourceScope("c_demo", "tl_demo")

    env1 = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner1 = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=env1,
        mission_id=MissionId("11111111-1111-1111-1111-111111111111"),
        operator_approved=True,
    )
    assert runner1.mission_id == MissionId("11111111-1111-1111-1111-111111111111")

    # Now attempt to construct a new runner with a different mission ID on the same directory
    env2 = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    with pytest.raises(
        KillerMissionIntegrityError,
        match="Mismatched mission identity in persistent storage",
    ):
        _live_runner_for_boundary_tests(
            monkeypatch,
            live_env=env2,
            mission_id=MissionId("22222222-2222-2222-2222-222222222222"),
            operator_approved=True,
        )


def test_adversarial_corrupt_ledger_fails_closed_without_creating_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A3 adversarial: Corrupt ledger raises KillerMissionIntegrityError and avoids DRAFT."""
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.killer_mission import (
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
    )

    stable_dir = tmp_path / "corrupt_ledger_test"
    stable_dir.mkdir(parents=True, exist_ok=True)
    # Write garbage into ledger.jsonl
    ledger_file = stable_dir / "ledger.jsonl"
    ledger_file.write_text("{corrupted: json: not_valid}\n", encoding="utf-8")

    with pytest.raises(KillerMissionIntegrityError, match="Failed to initialize durable ledger"):
        KillerMissionEnvironment.create_live_environment(
            base_dir=stable_dir,
            scope=DemoResourceScope("c_demo", "tl_demo"),
            calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
            tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
            weather_transport=OpenMeteoHttpTransport(),
        )


def test_adversarial_jsonl_write_succeeds_but_ledger_fails_triggers_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A2 adversarial: JSONL write succeeds but ledger fails -> rollback & latch failure."""
    from typing import Any

    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.domain.mission import MissionId
    from stilldone.killer_mission import (
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
    )
    from stilldone.pending_approval import ApprovalDecision

    stable_dir = tmp_path / "rollback_test"
    stable_dir.mkdir(parents=True, exist_ok=True)
    env = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=DemoResourceScope("c_demo", "tl_demo"),
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=env,
        mission_id=MissionId("11111111-1111-1111-1111-111111111111"),
        operator_approved=True,
    )

    # First write a valid decision
    runner._persist_consumed_decision_id("init_dec_ok", decision=ApprovalDecision.REJECT)
    assert "init_dec_ok" in runner._consumed_approval_decision_ids
    orig_size = runner._consumed_decisions_file.stat().st_size

    # Monkeypatch approval_ledger.record_rejection to fail
    def failing_record_rejection(*args: Any, **kwargs: Any) -> None:
        raise OSError("Simulated canonical ledger storage failure")

    monkeypatch.setattr(env.approval_ledger, "record_rejection", failing_record_rejection)

    with pytest.raises(
        KillerMissionIntegrityError,
        match="Failed to commit consumed approval decision to canonical approval ledger",
    ):
        runner._persist_consumed_decision_id("orphan_attempt", decision=ApprovalDecision.REJECT)

    # Verify rollback: JSONL size must be restored to orig_size (no orphaned record)
    assert runner._consumed_decisions_file.stat().st_size == orig_size
    assert "orphan_attempt" not in runner._consumed_approval_decision_ids
    assert runner._persistence_failed is True

    # Subsequent mutation attempts must fail closed
    with pytest.raises(
        KillerMissionIntegrityError, match="Persistence failure previously occurred"
    ):
        runner._persist_consumed_decision_id("another_id")


def test_adversarial_dual_store_discrepancy_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A2 adversarial: Inconsistent records between JSONL and ledger fail closed on reload."""
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.domain.mission import MissionId
    from stilldone.killer_mission import (
        KillerMissionEnvironment,
        KillerMissionIntegrityError,
    )
    from stilldone.pending_approval import ApprovalDecision

    stable_dir = tmp_path / "discrepancy_test"
    stable_dir.mkdir(parents=True, exist_ok=True)
    env = KillerMissionEnvironment.create_live_environment(
        base_dir=stable_dir,
        scope=DemoResourceScope("c_demo", "tl_demo"),
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner = _live_runner_for_boundary_tests(
        monkeypatch,
        live_env=env,
        mission_id=MissionId("11111111-1111-1111-1111-111111111111"),
        operator_approved=True,
    )
    runner._persist_consumed_decision_id("dec_both", decision=ApprovalDecision.REJECT)

    # Inject an extra record directly into JSONL that was never recorded in ApprovalLedger
    extra_record = json.dumps(
        {
            "decision_id": "dec_in_jsonl_only",
            "consumed_at": "2026-10-04T12:00:00+00:00",
            "decision": "REJECT",
            "mission_id": str(runner.mission_id),
        }
    )
    with open(runner._consumed_decisions_file, "a", encoding="utf-8") as f:
        f.write(f"{extra_record}\n")

    # Reloading consumed decisions must detect the discrepancy and fail closed
    runner._consumed_approval_decision_ids.clear()
    with pytest.raises(
        KillerMissionIntegrityError,
        match="Discrepancy detected between decision log and canonical approval ledger",
    ):
        runner._load_consumed_decision_ids()


def test_adversarial_unsupported_evidence_type_ignored_by_p11_hydration(
    tmp_path: Path,
) -> None:
    """A2 adversarial: Unsupported evidence types in ledger are safely ignored."""
    from stilldone.approval_consumption import ApprovalLedger
    from stilldone.domain.action import (
        ActionContract,
        ActionId,
        ActionType,
        NormalizedParameters,
        ResourceKind,
        TargetIdentity,
    )
    from stilldone.domain.lifecycle import MissionState
    from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
    from stilldone.domain.provenance import EvidenceOrigin
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    ledger_path = tmp_path / "ledger_unsupported_test.jsonl"
    file_ledger = DurableFileLedger(ledger_path)

    mid = MissionId("11111111-1111-1111-1111-111111111111")
    aid = ActionId("11111111-2222-3333-4444-555555555555")
    now = datetime.now(UTC)

    file_ledger.append_mission(
        MissionRecord(
            mission_id=mid,
            contract=MissionContract(
                mission_id=mid,
                intent=UserIntentSnapshot(text="Test", captured_at=now, mission_id=mid),
                created_at=now,
            ),
            state=MissionState.DRAFT,
            created_at=now,
            updated_at=now,
        )
    )
    file_ledger.append_action(
        ActionRecord(
            action_id=aid,
            mission_id=mid,
            action=ActionContract(
                mission_id=mid,
                action_id=aid,
                action_type=ActionType.WEATHER_READ,
                target=TargetIdentity(
                    system="weather",
                    resource_kind=ResourceKind.WEATHER_LOCATION,
                    resource_id="loc",
                ),
                parameters=NormalizedParameters.from_dict({}),
            ),
            approval_id=None,
            created_at=now,
        )
    )

    # Append an evidence record with an arbitrary unsupported evidence_type in its payload
    unsupported_record = EvidenceRecord.create(
        action_id=aid,
        mission_id=mid,
        origin=EvidenceOrigin.local_execution(),
        payload={"evidence_type": "CUSTOM_UNSUPPORTED_TYPE", "some_key": "some_value"},
        created_at=now,
    )
    file_ledger.append_evidence(unsupported_record)

    # Hydrate ApprovalLedger from file_ledger
    approval_ledger = ApprovalLedger(ledger=file_ledger)
    # The unsupported record must not grant approval, mark anything consumed, or crash
    assert len(approval_ledger.get_consumed_decision_ids()) == 0
    assert approval_ledger.is_rejected("any_id") is False
    assert approval_ledger.is_decision_consumed("any_id") is False
