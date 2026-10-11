"""Adversarial fail-closed tests verifying runtime invariants under python -O.

Tests that critical authority, provider, state machine, and telemetry checks
raise typed exceptions even when assert statements are stripped by python -O.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.authority_policy import (
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    verify_approval_grant,
)
from stilldone.aws_builder import (
    CloudWatchEMFTelemetryEmitter,
    InvalidEMFRecordError,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import ApprovalGrant, AuthorityClass
from stilldone.domain.mission import MissionId
from stilldone.execution.compiler import compile_candidate_plan
from stilldone.execution.contracts import (
    ExecutionDependencyError,
    ExecutionTransitionError,
    SymbolicTargetResolver,
)
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
)
from stilldone.killer_mission import (
    KillerMissionEnvironment,
    KillerMissionSequenceError,
    KillerMissionSliceRunner,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    SymbolicTargetRef,
)


def _make_calendar_action(mission_id: MissionId, calendar_id: str = "cal-demo") -> ActionContract:
    return ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="event-1",
            parent_id=calendar_id,
        ),
        parameters={"start_time": "2026-10-04T07:30:00+00:00"},
    )


def test_invalid_emf_record_fails_closed_without_assert() -> None:
    """EMF telemetry emitter raises InvalidEMFRecordError on schema violations."""
    emitter = CloudWatchEMFTelemetryEmitter()

    # Missing _aws directive
    with pytest.raises(InvalidEMFRecordError):
        emitter.serialize_record({})

    # Missing Timestamp in _aws
    with pytest.raises(InvalidEMFRecordError):
        emitter.serialize_record({"_aws": {}})

    # Missing top-level property for declared dimension
    bad_dim_record = {
        "_aws": {
            "Timestamp": 123456789,
            "CloudWatchMetrics": [
                {
                    "Namespace": "StillDone/Test",
                    "Dimensions": [["Environment"]],
                    "Metrics": [{"Name": "Count", "Unit": "Count"}],
                }
            ],
        },
        "Count": 1,
        # Missing "Environment"
    }
    with pytest.raises(InvalidEMFRecordError):
        emitter.serialize_record(bad_dim_record)

    # Non-numeric metric value
    bad_metric_record = {
        "_aws": {
            "Timestamp": 123456789,
            "CloudWatchMetrics": [
                {
                    "Namespace": "StillDone/Test",
                    "Dimensions": [],
                    "Metrics": [{"Name": "Count", "Unit": "Count"}],
                }
            ],
        },
        "Count": "not-a-number",
    }
    with pytest.raises(InvalidEMFRecordError):
        emitter.serialize_record(bad_metric_record)


def test_invalid_authority_state_fails_closed_without_assert() -> None:
    """Authority verification raises typed exceptions without relying on asserts."""
    mission_id = MissionId.generate()
    action = _make_calendar_action(mission_id)
    validated = validate_action_contract(action)
    now = datetime.now(UTC)

    # 1. Expired approval
    expired_grant = ApprovalGrant(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now - timedelta(minutes=30),
        expires_at=now - timedelta(minutes=1),
    )
    with pytest.raises(ApprovalExpiredError):
        verify_approval_grant(
            validated,
            expired_grant,
            expected_authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            at=now,
        )

    # 2. Action ID mismatch
    other_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=action.target,
        parameters=action.parameters,
    )
    other_validated = validate_action_contract(other_action)
    with pytest.raises(ApprovalBindingMismatchError):
        verify_approval_grant(
            other_validated,
            expired_grant,
            expected_authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            at=now - timedelta(minutes=15),
        )


def test_invalid_not_run_state_fails_closed_without_assert() -> None:
    """State tracker transitions enforce NOT_RUN prerequisite checks with typed exceptions."""
    scope = DemoResourceScope(
        calendar_id="cal-demo",
        task_list_id="tasks-demo",
    )
    resolver = SymbolicTargetResolver(scope=scope)
    mid = MissionId.generate()
    proposal = CandidatePlanProposal.create(
        mission_id=mid,
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.CALENDAR_READ,
                target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
            ),
            CandidateActionProposal.create(
                action_type=ActionType.TASK_CREATE,
                target_ref=SymbolicTargetRef.TASK_LIST,
                parameters={"title": "Pack backpacks"},
            ),
        ],
    )
    contract = compile_candidate_plan(proposal, resolver)
    schedule = schedule_execution(contract)
    a0, a1 = schedule.ordered_action_ids

    tracker = ExecutionStateTracker(contract, schedule)

    # Prerequisite a0 is NOT_RUN -> a1 cannot run; raises ExecutionDependencyError
    with pytest.raises(ExecutionDependencyError):
        tracker.mark_in_progress(a1)

    # Transition a0 to IN_PROGRESS
    tracker.mark_in_progress(a0)
    if tracker.snapshot().step_records[a0].status != ActionExecutionStatus.IN_PROGRESS:
        raise AssertionError("Action should be IN_PROGRESS")

    # Already IN_PROGRESS action to IN_PROGRESS -> raises ExecutionTransitionError
    with pytest.raises(ExecutionTransitionError):
        tracker.mark_in_progress(a0)


def test_killer_mission_sequence_fails_closed_without_assert(tmp_path: Path) -> None:
    """KillerMissionSliceRunner sequence checks raise typed exceptions fail-closed."""
    env = KillerMissionEnvironment.create_fixture_environment(base_dir=tmp_path)
    runner = KillerMissionSliceRunner(env=env)

    # Calling P-13.03 before prerequisite step 0 (calendar read) raises ExecutionDependencyError
    with pytest.raises(ExecutionDependencyError):
        runner.step_p13_03_tasks_prep()

    # Calling P-13.05 before P-13.04 approval checkpoint raises KillerMissionSequenceError
    with pytest.raises(KillerMissionSequenceError):
        runner.step_p13_05_calendar_approve()


def test_adversarial_subprocess_execution_under_python_optimized() -> None:
    """Spawns python -O to prove that fail-closed checks remain active when asserts are stripped."""
    script = "import sys\nassert False, 'Assert was not stripped!'\n"
    # Under python -O, assert False will be stripped and exit code is 0
    res_stripped = subprocess.run(
        [sys.executable, "-O", "-c", script], capture_output=True, text=True
    )
    if res_stripped.returncode != 0:
        raise AssertionError("python -O must strip assert statements")

    # Now run an adversarial fail-closed check under python -O and verify it raises typed exception
    adversarial_script = (
        "import sys\n"
        "from stilldone.aws_builder import CloudWatchEMFTelemetryEmitter, InvalidEMFRecordError\n"
        "emitter = CloudWatchEMFTelemetryEmitter()\n"
        "try:\n"
        "    emitter.serialize_record({})\n"
        "    sys.exit(1)\n"
        "except InvalidEMFRecordError:\n"
        "    sys.exit(0)\n"
    )
    res_check = subprocess.run(
        [sys.executable, "-O", "-c", adversarial_script],
        capture_output=True,
        text=True,
    )
    if res_check.returncode != 0:
        raise AssertionError(f"Fail-closed check failed under python -O: {res_check.stderr}")
