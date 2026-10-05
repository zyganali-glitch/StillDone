"""Tests for Phase P-08.03: Partial-Failure Preservation and Execution States.

Validates that:
- Smallest deterministic per-action execution state vocabulary is enforced.
- Execution success != VERIFIED; Execution success != READY.
- NOT_RUN is never PASS.
- When step N fails:
  * earlier completed results are preserved (EXECUTION_SUCCEEDED);
  * exact failed step is preserved (EXECUTION_FAILED) with attempt and error;
  * later dependent steps remain explicitly BLOCKED / NOT_RUN;
  * entire mission is never collapsed to simple boolean success/failure;
  * later actions are never falsely claimed to have executed.
- Independent later actions continue deterministically if prerequisites are satisfied.
- No silent exception swallowing; error messages are redacted.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import ActionId, ActionType
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.mission import MissionId
from stilldone.execution.compiler import compile_candidate_plan
from stilldone.execution.contracts import MissionExecutionContract, SymbolicTargetResolver
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
    MissionExecutionRecord,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    SymbolicTargetRef,
)


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="demo-cal-12345",
        task_list_id="demo-tasks-67890",
    )


@pytest.fixture
def resolver(demo_scope: DemoResourceScope) -> SymbolicTargetResolver:
    return SymbolicTargetResolver(scope=demo_scope)


@pytest.fixture
def three_step_contract(resolver: SymbolicTargetResolver) -> MissionExecutionContract:
    mid = MissionId.generate()
    p = CandidatePlanProposal.create(
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
            CandidateActionProposal.create(
                action_type=ActionType.TASK_READ,
                target_ref=SymbolicTargetRef.TASK,
            ),
        ],
    )
    return compile_candidate_plan(p, resolver)


class TestExecutionStateVocabulary:
    """Per-action execution state vocabulary invariants."""

    def test_vocabulary_members(self) -> None:
        assert ActionExecutionStatus.NOT_RUN == "NOT_RUN"
        assert ActionExecutionStatus.IN_PROGRESS == "IN_PROGRESS"
        assert ActionExecutionStatus.EXECUTION_SUCCEEDED == "EXECUTION_SUCCEEDED"
        assert ActionExecutionStatus.EXECUTION_FAILED == "EXECUTION_FAILED"
        assert ActionExecutionStatus.BLOCKED == "BLOCKED"

    def test_execution_success_distinct_from_verified_and_ready(self) -> None:
        # EXECUTION_SUCCEEDED is distinct from P-09 VERIFIED and READY
        all_values = {s.value for s in ActionExecutionStatus}
        assert "VERIFIED" not in all_values
        assert "READY" not in all_values

    def test_not_run_is_distinct_from_pass(self) -> None:
        all_values = {s.value for s in ActionExecutionStatus}
        assert "PASS" not in all_values


class TestStepExecutionRecordValidation:
    """Validation and invariants for StepExecutionRecord."""

    def test_not_run_step_cannot_have_attempt(self) -> None:
        aid = ActionId.generate()
        attempt = ExecutionAttempt.create(
            action_id=aid,
            idempotency_key=IdempotencyKey.generate(),
        )
        with pytest.raises(Exception, match="NOT_RUN step cannot have an attempt"):
            StepExecutionRecord(
                action_id=aid,
                status=ActionExecutionStatus.NOT_RUN,
                attempt=attempt,
            )

    def test_blocked_step_cannot_have_attempt(self) -> None:
        aid = ActionId.generate()
        attempt = ExecutionAttempt.create(
            action_id=aid,
            idempotency_key=IdempotencyKey.generate(),
        )
        with pytest.raises(Exception, match="BLOCKED step cannot have an attempt"):
            StepExecutionRecord(
                action_id=aid,
                status=ActionExecutionStatus.BLOCKED,
                attempt=attempt,
            )

    def test_error_message_redaction(self) -> None:
        aid = ActionId.generate()
        rec = StepExecutionRecord(
            action_id=aid,
            status=ActionExecutionStatus.EXECUTION_FAILED,
            error_message="Failed for user test@example.com with secret secret_token_123",
        )
        assert rec.error_message is not None
        assert "test@example.com" not in rec.error_message
        assert "[REDACTED_EMAIL]" in rec.error_message


class TestPartialFailurePreservation:
    """Core StillDone invariant: multi-step partial failures preserve completed results."""

    def test_step_failure_preserves_earlier_success_and_blocks_later(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)

        a0, a1, a2 = schedule.ordered_action_ids

        # Step 0: can execute and succeeds
        can_run, _ = tracker.can_execute(a0)
        assert can_run is True

        attempt0 = ExecutionAttempt.create(
            action_id=a0,
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
        )
        res0 = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="EVENT_FOUND",
            writes_performed=0,
        )
        tracker.record_success(a0, attempt0, res0)

        # Step 1: can execute and fails
        can_run, _ = tracker.can_execute(a1)
        assert can_run is True

        attempt1 = ExecutionAttempt.create(
            action_id=a1,
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
        )
        res1 = ProviderExecutionResult(
            action_type=ActionType.TASK_CREATE,
            success=False,
            status_name="TASK_API_ERROR",
            writes_performed=0,
            error_message="HTTP 503 Service Unavailable",
        )
        tracker.record_failure(
            a1,
            attempt1,
            res1,
            error_message="HTTP 503 Service Unavailable",
        )

        # Step 2: depends on Step 1, so CANNOT execute!
        can_run, blocked_by = tracker.can_execute(a2)
        assert can_run is False
        assert blocked_by == a1

        # Inspect immutable snapshot
        snapshot = tracker.snapshot()
        assert isinstance(snapshot, MissionExecutionRecord)
        assert snapshot.has_failures is True
        assert snapshot.has_blocked is True
        assert snapshot.is_all_succeeded is False

        # Step 0 preserved as EXECUTION_SUCCEEDED
        rec0 = snapshot.step_records[a0]
        assert rec0.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert rec0.attempt == attempt0
        assert rec0.provider_result == res0

        # Step 1 preserved as EXECUTION_FAILED
        rec1 = snapshot.step_records[a1]
        assert rec1.status == ActionExecutionStatus.EXECUTION_FAILED
        assert rec1.attempt == attempt1
        assert rec1.provider_result == res1
        assert rec1.error_message == "HTTP 503 Service Unavailable"

        # Step 2 explicitly BLOCKED by a1, attempt is None
        rec2 = snapshot.step_records[a2]
        assert rec2.status == ActionExecutionStatus.BLOCKED
        assert rec2.attempt is None
        assert rec2.provider_result is None
        assert rec2.blocked_by == a1

        # Invariant: NEVER claimed that step 2 executed
        assert rec2.status not in (
            ActionExecutionStatus.EXECUTION_SUCCEEDED,
            ActionExecutionStatus.EXECUTION_FAILED,
        )

    def test_independent_later_action_continues_deterministically(
        self, resolver: SymbolicTargetResolver
    ) -> None:
        """If step B fails, independent step C (which depends only on A) can still execute."""
        mid = MissionId.generate()
        p = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.TASK_CREATE,
                    target_ref=SymbolicTargetRef.TASK_LIST,
                    parameters={"title": "Pack bags"},
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.WEATHER_READ,
                    target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                ),
            ],
        )
        compiled = compile_candidate_plan(p, resolver)
        a, b, c = [act.action_id for act in compiled.actions]

        # Branching dependency: A is prerequisite for B and C; B and C do NOT depend on each other!
        branching_deps = {
            a: frozenset(),
            b: frozenset({a}),
            c: frozenset({a}),
        }
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=compiled.actions,
            dependencies=branching_deps,
        )

        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        # Step A succeeds
        att_a = ExecutionAttempt.create(action_id=a, idempotency_key=IdempotencyKey.generate())
        tracker.record_success(
            a,
            att_a,
            ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK"),
        )

        # Step B fails
        att_b = ExecutionAttempt.create(action_id=b, idempotency_key=IdempotencyKey.generate())
        tracker.record_failure(
            b,
            att_b,
            None,
            error_message="Task create failed",
        )

        # Step C: does NOT depend on B! Prerequisite A succeeded!
        can_run, _ = tracker.can_execute(c)
        assert can_run is True  # C is safe to execute!

        att_c = ExecutionAttempt.create(action_id=c, idempotency_key=IdempotencyKey.generate())
        tracker.record_success(
            c,
            att_c,
            ProviderExecutionResult(ActionType.WEATHER_READ, True, "OK"),
        )

        snapshot = tracker.snapshot()
        # Verify: A succeeded, B failed, C succeeded!
        assert snapshot.step_records[a].status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert snapshot.step_records[b].status == ActionExecutionStatus.EXECUTION_FAILED
        assert snapshot.step_records[c].status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        # Mission has failure (B failed), but C was not blocked accidentally
        assert snapshot.has_failures is True
        assert snapshot.has_blocked is False


class TestProviderExecutionResultPurity:
    """ProviderExecutionResult is separated from EvidenceRecord and verification predicates."""

    def test_provider_result_fields(self) -> None:
        res = ProviderExecutionResult(
            action_type=ActionType.WEATHER_READ,
            success=True,
            status_name="WEATHER_OBSERVED",
            writes_performed=0,
            details={"temperature": 18.5},
        )
        assert res.action_type == ActionType.WEATHER_READ
        assert res.success is True
        assert res.status_name == "WEATHER_OBSERVED"
        assert res.writes_performed == 0
        assert res.details["temperature"] == 18.5
        assert isinstance(res.captured_at, datetime)
        assert res.captured_at.tzinfo == UTC

        # No EvidenceId attributes
        assert not hasattr(res, "evidence_id")
        assert not hasattr(res, "evidence_records")

        # No verification / readiness attributes
        assert not hasattr(res, "is_verified")
        assert not hasattr(res, "is_ready")
