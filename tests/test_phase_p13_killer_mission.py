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
    **kwargs: object,
) -> LiveKillerMissionSliceRunner:
    """Live runner over production transport classes with injected (non-network) clients."""
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.killer_mission import LivePreflightReport

    scope = DemoResourceScope("c_boundary_demo", "tl_boundary_demo")
    live_env = KillerMissionEnvironment.create_live_environment(
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    runner = LiveKillerMissionSliceRunner(
        env=live_env,
        operator_approved=True,
        aws_credentials_available=True,
        source_sha="1111111111111111111111111111111111111111",
        demo_date="2026-10-04",
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

    monkeypatch.setattr(runner, "step_p13_01_seed", lambda: _ok("P-13.01"))
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
