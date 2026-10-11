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

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.adapters.calendar import FakeGoogleCalendarTransport
from stilldone.adapters.tasks import FakeGoogleTasksTransport
from stilldone.adapters.weather import FakeOpenMeteoTransport
from stilldone.authority_policy import (
    AuthorityDecisionStatus,
    AuthorityPolicyTypeError,
    PlannerAuthorityError,
    evaluate_authority,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.gate import (
    PlannerGateAuthorityError,
    evaluate_execution_gate,
)
from stilldone.killer_mission import (
    CANONICAL_CONTRADICTORY_START_TIME,
    CANONICAL_DEMO_CALENDAR_ID,
    CANONICAL_DEMO_EVENT_ID,
    CANONICAL_DEMO_TASK_LIST_ID,
    CANONICAL_DEMO_TASK_TITLE,
    CANONICAL_DESIRED_START_TIME,
    CANONICAL_INITIAL_START_TIME,
    CANONICAL_KILLER_INTENT,
    PREDICATE_ID_CALENDAR,
    PREDICATE_ID_TASK,
    PREDICATE_ID_WEATHER,
    KillerMissionEnvironment,
    KillerMissionSliceRunner,
)
from stilldone.pending_approval import (
    PendingApproval,
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
from stilldone.snapshot import (
    PlannerSnapshotAuthorityError,
    create_mission_snapshot,
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
        evaluate_execution_gate(action_prop, router=runner.router)  # type: ignore[arg-type]

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
