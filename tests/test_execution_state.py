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
from stilldone.execution.contracts import (
    ExecutionContractTypeError,
    ExecutionContractValueError,
    ExecutionLineageError,
    ExecutionTransitionError,
    MissionExecutionContract,
    SymbolicTargetResolver,
    UnknownActionIdError,
)
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

        tracker.mark_in_progress(a0)
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

        tracker.mark_in_progress(a1)
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
        tracker.mark_in_progress(a)
        att_a = ExecutionAttempt.create(action_id=a, idempotency_key=IdempotencyKey.generate())
        tracker.record_success(
            a,
            att_a,
            ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK"),
        )

        # Step B fails
        tracker.mark_in_progress(b)
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

        tracker.mark_in_progress(c)
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


class TestUnknownActionIdFailClosed:
    """Defect 1: Unknown ActionIds must fail closed across all tracker APIs."""

    def test_unknown_action_id_rejected_by_every_tracker_api(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        foreign_aid = ActionId.generate()
        valid_aid = schedule.ordered_action_ids[0]

        # 1. can_execute
        with pytest.raises(UnknownActionIdError, match="does not belong to mission contract"):
            tracker.can_execute(foreign_aid)

        # 2. mark_in_progress
        with pytest.raises(UnknownActionIdError, match="does not belong to mission contract"):
            tracker.mark_in_progress(foreign_aid)

        # 3. record_success
        attempt = ExecutionAttempt.create(
            action_id=foreign_aid, idempotency_key=IdempotencyKey.generate()
        )
        res = ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK")
        with pytest.raises(UnknownActionIdError, match="does not belong to mission contract"):
            tracker.record_success(foreign_aid, attempt, res)

        # 4. record_failure
        with pytest.raises(UnknownActionIdError, match="does not belong to mission contract"):
            tracker.record_failure(foreign_aid, attempt, None, error_message="fail")

        # 5. record_blocked (target action is foreign)
        with pytest.raises(UnknownActionIdError, match="does not belong to mission contract"):
            tracker.record_blocked(foreign_aid, blocked_by=valid_aid)

        # 6. record_blocked (blocked_by is foreign)
        with pytest.raises(UnknownActionIdError, match="does not belong to mission contract"):
            tracker.record_blocked(valid_aid, blocked_by=foreign_aid)

        # 7. Snapshot key set remains exactly equal to scheduled action IDs
        snapshot = tracker.snapshot()
        assert set(snapshot.step_records.keys()) == set(schedule.ordered_action_ids)
        assert foreign_aid not in snapshot.step_records

        # 8. snapshot get_status with foreign action_id
        with pytest.raises(UnknownActionIdError, match="not in execution record"):
            snapshot.get_status(foreign_aid)

    def test_invalid_action_id_type_fails_closed(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        with pytest.raises(ExecutionContractTypeError, match="action_id must be an ActionId"):
            tracker.can_execute("invalid-id")  # type: ignore[arg-type]
        with pytest.raises(ExecutionContractTypeError, match="action_id must be an ActionId"):
            tracker.mark_in_progress(123)  # type: ignore[arg-type]
        with pytest.raises(ExecutionContractTypeError, match="blocked_by must be an ActionId"):
            tracker.record_blocked(
                schedule.ordered_action_ids[0],
                blocked_by="invalid-id",  # type: ignore[arg-type]
            )


class TestMonotonicExecutionStateMachine:
    """Defect 2: Monotonic execution state machine and comprehensive transition matrix."""

    def test_legal_and_illegal_transitions_matrix(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        a0, a1, a2 = schedule.ordered_action_ids

        # Fresh tracker: all steps are NOT_RUN
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        assert tracker.snapshot().step_records[a0].status == ActionExecutionStatus.NOT_RUN

        # NOT_RUN -> EXECUTION_SUCCEEDED directly is FORBIDDEN
        att0 = ExecutionAttempt.create(action_id=a0, idempotency_key=IdempotencyKey.generate())
        res0 = ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK")
        with pytest.raises(ExecutionTransitionError, match="must be in IN_PROGRESS state"):
            tracker.record_success(a0, att0, res0)

        # NOT_RUN -> EXECUTION_FAILED directly is FORBIDDEN
        with pytest.raises(ExecutionTransitionError, match="must be in IN_PROGRESS state"):
            tracker.record_failure(a0, att0, None, error_message="early fail")

        # Legal: NOT_RUN -> IN_PROGRESS
        tracker.mark_in_progress(a0)
        assert tracker.snapshot().step_records[a0].status == ActionExecutionStatus.IN_PROGRESS

        # IN_PROGRESS -> IN_PROGRESS is FORBIDDEN
        with pytest.raises(ExecutionTransitionError, match="only NOT_RUN"):
            tracker.mark_in_progress(a0)

        # IN_PROGRESS -> BLOCKED is FORBIDDEN
        with pytest.raises(ExecutionTransitionError, match="only NOT_RUN"):
            tracker.record_blocked(a0, blocked_by=a1)

        # Legal: IN_PROGRESS -> EXECUTION_SUCCEEDED
        tracker.record_success(a0, att0, res0)
        assert (
            tracker.snapshot().step_records[a0].status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        )

        # EXECUTION_SUCCEEDED is terminal:
        # Cannot transition to IN_PROGRESS
        with pytest.raises(ExecutionTransitionError):
            tracker.mark_in_progress(a0)
        # Cannot transition to EXECUTION_FAILED
        with pytest.raises(ExecutionTransitionError):
            tracker.record_failure(a0, att0, None, error_message="overwrite fail")
        # Cannot transition to BLOCKED
        with pytest.raises(ExecutionTransitionError):
            tracker.record_blocked(a0, blocked_by=a1)
        # Repeated same-terminal write fails closed
        with pytest.raises(ExecutionTransitionError):
            tracker.record_success(a0, att0, res0)

        # Now test Step 1 failure path:
        # Legal: NOT_RUN -> IN_PROGRESS
        tracker.mark_in_progress(a1)
        att1 = ExecutionAttempt.create(action_id=a1, idempotency_key=IdempotencyKey.generate())
        # Legal: IN_PROGRESS -> EXECUTION_FAILED
        tracker.record_failure(a1, att1, None, error_message="step 1 failed")
        assert tracker.snapshot().step_records[a1].status == ActionExecutionStatus.EXECUTION_FAILED

        # EXECUTION_FAILED is terminal:
        # Cannot transition to IN_PROGRESS
        with pytest.raises(ExecutionTransitionError):
            tracker.mark_in_progress(a1)
        # Cannot transition to EXECUTION_SUCCEEDED
        res1 = ProviderExecutionResult(ActionType.TASK_CREATE, True, "OK")
        with pytest.raises(ExecutionTransitionError):
            tracker.record_success(a1, att1, res1)
        # Cannot transition to BLOCKED
        with pytest.raises(ExecutionTransitionError):
            tracker.record_blocked(a1, blocked_by=a0)
        # Repeated same-terminal write fails closed
        with pytest.raises(ExecutionTransitionError):
            tracker.record_failure(a1, att1, None, error_message="step 1 failed again")

        # Step 2 was automatically marked BLOCKED because it depended on Step 1:
        assert tracker.snapshot().step_records[a2].status == ActionExecutionStatus.BLOCKED

        # BLOCKED is terminal:
        att2 = ExecutionAttempt.create(action_id=a2, idempotency_key=IdempotencyKey.generate())
        # Cannot transition to IN_PROGRESS
        with pytest.raises(ExecutionTransitionError):
            tracker.mark_in_progress(a2)
        # Cannot transition to EXECUTION_SUCCEEDED
        res2 = ProviderExecutionResult(ActionType.TASK_READ, True, "OK")
        with pytest.raises(ExecutionTransitionError):
            tracker.record_success(a2, att2, res2)
        # Cannot transition to EXECUTION_FAILED
        with pytest.raises(ExecutionTransitionError):
            tracker.record_failure(a2, att2, None, error_message="fail blocked")
        # Repeated same-terminal write fails closed
        with pytest.raises(ExecutionTransitionError):
            tracker.record_blocked(a2, blocked_by=a1)


class TestActionAttemptLineage:
    """Defect 3: ActionId <-> ExecutionAttempt lineage enforcement."""

    def test_step_execution_record_rejects_mismatched_attempt(self) -> None:
        aid_a = ActionId.generate()
        aid_b = ActionId.generate()
        attempt_b = ExecutionAttempt.create(
            action_id=aid_b, idempotency_key=IdempotencyKey.generate()
        )

        with pytest.raises(ExecutionLineageError, match="does not match StepExecutionRecord"):
            StepExecutionRecord(
                action_id=aid_a,
                status=ActionExecutionStatus.EXECUTION_FAILED,
                attempt=attempt_b,
                error_message="failed",
            )

    def test_step_execution_record_accepts_matching_attempt(self) -> None:
        aid = ActionId.generate()
        attempt = ExecutionAttempt.create(action_id=aid, idempotency_key=IdempotencyKey.generate())
        rec = StepExecutionRecord(
            action_id=aid,
            status=ActionExecutionStatus.EXECUTION_FAILED,
            attempt=attempt,
            error_message="failed",
        )
        assert rec.attempt == attempt

    def test_tracker_record_success_rejects_mismatched_attempt(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        a0 = schedule.ordered_action_ids[0]
        a1 = schedule.ordered_action_ids[1]

        tracker.mark_in_progress(a0)
        # Attempt belongs to a1, not a0!
        mismatched_attempt = ExecutionAttempt.create(
            action_id=a1, idempotency_key=IdempotencyKey.generate()
        )
        res = ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK")

        with pytest.raises(ExecutionLineageError, match="does not match action_id"):
            tracker.record_success(a0, mismatched_attempt, res)

    def test_tracker_record_failure_rejects_mismatched_attempt(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        a0 = schedule.ordered_action_ids[0]
        a1 = schedule.ordered_action_ids[1]

        tracker.mark_in_progress(a0)
        mismatched_attempt = ExecutionAttempt.create(
            action_id=a1, idempotency_key=IdempotencyKey.generate()
        )

        with pytest.raises(ExecutionLineageError, match="does not match action_id"):
            tracker.record_failure(a0, mismatched_attempt, None, error_message="failed")


class TestActionProviderResultLineage:
    """Defect 4: ActionType <-> ProviderExecutionResult lineage and success consistency."""

    def test_tracker_record_success_rejects_mismatched_action_type(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        a0 = schedule.ordered_action_ids[0]  # CALENDAR_READ
        tracker.mark_in_progress(a0)

        attempt = ExecutionAttempt.create(action_id=a0, idempotency_key=IdempotencyKey.generate())
        # Wrong action_type: WEATHER_READ instead of CALENDAR_READ
        wrong_res = ProviderExecutionResult(
            action_type=ActionType.WEATHER_READ,
            success=True,
            status_name="WEATHER_OK",
        )
        with pytest.raises(ExecutionLineageError, match="does not match expected action_type"):
            tracker.record_success(a0, attempt, wrong_res)

    def test_tracker_record_failure_rejects_mismatched_action_type(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        a0 = schedule.ordered_action_ids[0]  # CALENDAR_READ
        tracker.mark_in_progress(a0)

        attempt = ExecutionAttempt.create(action_id=a0, idempotency_key=IdempotencyKey.generate())
        wrong_res = ProviderExecutionResult(
            action_type=ActionType.TASK_CREATE,
            success=False,
            status_name="TASK_ERR",
        )
        with pytest.raises(ExecutionLineageError, match="does not match expected action_type"):
            tracker.record_failure(a0, attempt, wrong_res, error_message="failed")

    def test_tracker_record_success_rejects_success_false(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        a0 = schedule.ordered_action_ids[0]
        tracker.mark_in_progress(a0)

        attempt = ExecutionAttempt.create(action_id=a0, idempotency_key=IdempotencyKey.generate())
        res_fail = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=False,
            status_name="ERROR",
        )
        with pytest.raises(
            ExecutionContractValueError, match="requires provider_result.success to be True"
        ):
            tracker.record_success(a0, attempt, res_fail)

    def test_tracker_record_failure_rejects_success_true(
        self, three_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(three_step_contract)
        tracker = ExecutionStateTracker(three_step_contract, schedule)
        a0 = schedule.ordered_action_ids[0]
        tracker.mark_in_progress(a0)

        attempt = ExecutionAttempt.create(action_id=a0, idempotency_key=IdempotencyKey.generate())
        res_succ = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="OK",
        )
        with pytest.raises(
            ExecutionContractValueError, match="requires provider_result.success to be False"
        ):
            tracker.record_failure(a0, attempt, res_succ, error_message="failed")

    def test_step_execution_record_direct_rejects_contradictions(self) -> None:
        aid = ActionId.generate()
        att = ExecutionAttempt.create(action_id=aid, idempotency_key=IdempotencyKey.generate())
        succ_res = ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK")
        fail_res = ProviderExecutionResult(ActionType.CALENDAR_READ, False, "ERR")

        # EXECUTION_SUCCEEDED + success=False -> rejected
        with pytest.raises(
            ExecutionContractValueError, match="cannot have provider_result with success=False"
        ):
            StepExecutionRecord(
                action_id=aid,
                status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
                attempt=att,
                provider_result=fail_res,
            )

        # EXECUTION_FAILED + success=True -> rejected
        with pytest.raises(
            ExecutionContractValueError, match="cannot have provider_result with success=True"
        ):
            StepExecutionRecord(
                action_id=aid,
                status=ActionExecutionStatus.EXECUTION_FAILED,
                attempt=att,
                provider_result=succ_res,
                error_message="inconsistent",
            )

        # EXECUTION_SUCCEEDED without provider_result -> rejected
        with pytest.raises(ExecutionContractValueError, match="requires a provider_result"):
            StepExecutionRecord(
                action_id=aid,
                status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
                attempt=att,
                provider_result=None,
            )
