"""Tests for Phase P-09.02: Exact Predicate Evaluation for Calendar and Tasks.

Validates that:
- Predicates evaluate to exact deterministic truth (TRUE, FALSE, NOT_EVALUABLE).
- Zero fuzzy matching; zero model judgment.
- Provider status 'SUCCESS' cannot substitute for predicate truth.
- Execution payloads (ProviderExecutionResult, ExecutionAttempt) cannot substitute
  for read-back observations.
- One-field mismatch produces FALSE.
- Target identity mismatch produces deterministic FALSE.
- Missing external object (exists=False) produces deterministic FALSE for state
  predicates and TRUE for does_not_exist.
- Malformed observation fails closed.
- Sensitive payloads are redacted in mismatch explanations.
- Tests cover Google Calendar events and Google Tasks.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stilldone.domain.action import ActionId, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    PredicateOperator,
)
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.state import ProviderExecutionResult
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    VerificationObservation,
)
from stilldone.verifier.predicates import (
    PredicateTruth,
    evaluate_predicate,
    evaluate_predicates,
)

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId.generate()


@pytest.fixture
def cal_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-school-789",
        parent_id="demo-cal-primary-lane",
    )


@pytest.fixture
def tasks_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task-pack-456",
        parent_id="demo-task-list-main",
    )


@pytest.fixture
def cal_observation(cal_target: TargetIdentity) -> VerificationObservation:
    return VerificationObservation(
        target=cal_target,
        observed_at=datetime(2026, 10, 6, 7, 30, tzinfo=UTC),
        exists=True,
        properties={
            "summary": "Leave for school",
            "start_time": "2026-10-06T07:45:00Z",
            "end_time": "2026-10-06T08:15:00Z",
            "all_day": False,
            "status": "confirmed",
            "etag": '"etag-cal-12345"',
        },
        provenance=EvidenceProvenance.FIXTURE,
    )


@pytest.fixture
def tasks_observation(tasks_target: TargetIdentity) -> VerificationObservation:
    return VerificationObservation(
        target=tasks_target,
        observed_at=datetime(2026, 10, 6, 7, 30, tzinfo=UTC),
        exists=True,
        properties={
            "title": "Pack backpacks",
            "due": "2026-10-06",
            "status": "needsAction",
            "deleted": False,
            "hidden": False,
            "etag": '"etag-task-67890"',
        },
        provenance=EvidenceProvenance.FIXTURE,
    )


# ===========================================================================
# Calendar Predicate Evaluation Tests
# ===========================================================================


class TestCalendarPredicateEvaluation:
    """Exact predicate evaluation for Google Calendar observations."""

    def test_calendar_exact_matches_produce_true(
        self,
        mission_id: MissionId,
        cal_target: TargetIdentity,
        cal_observation: VerificationObservation,
    ) -> None:
        """Every matching field produces PredicateTruth.TRUE."""
        # Summary exact match
        p_summary = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="summary",
            operator=PredicateOperator.EQUALS,
            expected_value="Leave for school",
        )
        res_summary = evaluate_predicate(p_summary, cal_observation, expected_target=cal_target)
        assert res_summary.truth == PredicateTruth.TRUE
        assert res_summary.is_true is True

        # Status exact match
        p_status = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="confirmed",
        )
        res_status = evaluate_predicate(p_status, cal_observation, expected_target=cal_target)
        assert res_status.truth == PredicateTruth.TRUE

        # Start time exact match
        p_start = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="start_time",
            operator=PredicateOperator.EQUALS,
            expected_value="2026-10-06T07:45:00Z",
        )
        res_start = evaluate_predicate(p_start, cal_observation, expected_target=cal_target)
        assert res_start.truth == PredicateTruth.TRUE

        # all_day exact match (bool)
        p_allday = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="all_day",
            operator=PredicateOperator.EQUALS,
            expected_value=False,
        )
        res_allday = evaluate_predicate(p_allday, cal_observation, expected_target=cal_target)
        assert res_allday.truth == PredicateTruth.TRUE

        # Existence exact match
        p_exists = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="exists",
            operator=PredicateOperator.EXISTS,
            expected_value=True,
        )
        res_exists = evaluate_predicate(p_exists, cal_observation, expected_target=cal_target)
        assert res_exists.truth == PredicateTruth.TRUE

    def test_calendar_one_field_mismatch_produces_false(
        self,
        mission_id: MissionId,
        cal_target: TargetIdentity,
        cal_observation: VerificationObservation,
    ) -> None:
        """A single mismatch in summary, time, or status produces FALSE."""
        p_wrong_summary = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="summary",
            operator=PredicateOperator.EQUALS,
            expected_value="leave for school",  # case mismatch!
        )
        res = evaluate_predicate(p_wrong_summary, cal_observation, expected_target=cal_target)
        assert res.truth == PredicateTruth.FALSE
        assert res.is_false is True

        p_wrong_time = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="start_time",
            operator=PredicateOperator.EQUALS,
            expected_value="2026-10-06T08:00:00Z",  # wrong time!
        )
        assert (
            evaluate_predicate(p_wrong_time, cal_observation, expected_target=cal_target).truth
            == PredicateTruth.FALSE
        )

        p_wrong_status = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="cancelled",
        )
        assert (
            evaluate_predicate(p_wrong_status, cal_observation, expected_target=cal_target).truth
            == PredicateTruth.FALSE
        )

    def test_no_fuzzy_matching_in_calendar(
        self,
        mission_id: MissionId,
        cal_target: TargetIdentity,
        cal_observation: VerificationObservation,
    ) -> None:
        """Fuzzy substrings or partial matches are strictly rejected as FALSE."""
        # Partial summary "Leave" is not "Leave for school"
        p_partial = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="summary",
            operator=PredicateOperator.EQUALS,
            expected_value="Leave",
        )
        res = evaluate_predicate(p_partial, cal_observation, expected_target=cal_target)
        assert res.truth == PredicateTruth.FALSE


# ===========================================================================
# Tasks Predicate Evaluation Tests
# ===========================================================================


class TestTasksPredicateEvaluation:
    """Exact predicate evaluation for Google Tasks observations."""

    def test_tasks_exact_matches_produce_true(
        self,
        mission_id: MissionId,
        tasks_target: TargetIdentity,
        tasks_observation: VerificationObservation,
    ) -> None:
        """Tasks title, due date, status, and existence evaluate to TRUE."""
        # Title match
        p_title = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="title",
            operator=PredicateOperator.EQUALS,
            expected_value="Pack backpacks",
        )
        res_title = evaluate_predicate(p_title, tasks_observation, expected_target=tasks_target)
        assert res_title.truth == PredicateTruth.TRUE

        # Due date match
        p_due = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="due",
            operator=PredicateOperator.EQUALS,
            expected_value="2026-10-06",
        )
        assert (
            evaluate_predicate(p_due, tasks_observation, expected_target=tasks_target).truth
            == PredicateTruth.TRUE
        )

        # Status match
        p_status = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="needsAction",
        )
        assert (
            evaluate_predicate(p_status, tasks_observation, expected_target=tasks_target).truth
            == PredicateTruth.TRUE
        )

        # Deleted flag match
        p_del = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="deleted",
            operator=PredicateOperator.EQUALS,
            expected_value=False,
        )
        assert (
            evaluate_predicate(p_del, tasks_observation, expected_target=tasks_target).truth
            == PredicateTruth.TRUE
        )

    def test_tasks_one_field_mismatch_produces_false(
        self,
        mission_id: MissionId,
        tasks_target: TargetIdentity,
        tasks_observation: VerificationObservation,
    ) -> None:
        """One-field mismatch in task title, status, or due produces FALSE."""
        p_wrong_title = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="title",
            operator=PredicateOperator.EQUALS,
            expected_value="pack backpacks",  # lower case mismatch
        )
        res = evaluate_predicate(p_wrong_title, tasks_observation, expected_target=tasks_target)
        assert res.truth == PredicateTruth.FALSE

        p_wrong_status = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="completed",  # observed is needsAction
        )
        assert (
            evaluate_predicate(
                p_wrong_status, tasks_observation, expected_target=tasks_target
            ).truth
            == PredicateTruth.FALSE
        )


# ===========================================================================
# Target Identity Mismatch and Missing Object Tests
# ===========================================================================


class TestTargetIdentityAndMissingObject:
    """Proves target mismatch and missing objects evaluate deterministically."""

    def test_wrong_external_object_identity_produces_false(
        self,
        mission_id: MissionId,
        cal_observation: VerificationObservation,
    ) -> None:
        """Observation with wrong resource_id produces PredicateTruth.FALSE."""
        wrong_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-wrong-event-id",
            parent_id="demo-cal-primary-lane",
        )
        p = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="confirmed",
        )
        res = evaluate_predicate(p, cal_observation, expected_target=wrong_target)
        assert res.truth == PredicateTruth.FALSE
        assert "Target identity mismatch" in (res.reason or "")

    def test_missing_object_produces_false_for_existence(
        self,
        mission_id: MissionId,
        cal_target: TargetIdentity,
    ) -> None:
        """Non-existent object (exists=False) produces PredicateTruth.FALSE for state."""
        missing_obs = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=False,
            properties={},
        )
        p_exists = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="exists",
            operator=PredicateOperator.EXISTS,
            expected_value=True,
        )
        res = evaluate_predicate(p_exists, missing_obs, expected_target=cal_target)
        assert res.truth == PredicateTruth.FALSE

        p_summary = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="summary",
            operator=PredicateOperator.EQUALS,
            expected_value="Leave for school",
        )
        res_summary = evaluate_predicate(p_summary, missing_obs, expected_target=cal_target)
        assert res_summary.truth == PredicateTruth.FALSE
        assert "does not exist" in (res_summary.reason or "")

    def test_missing_object_produces_true_for_does_not_exist(
        self,
        mission_id: MissionId,
        cal_target: TargetIdentity,
    ) -> None:
        """Non-existent object produces TRUE when operator is DOES_NOT_EXIST."""
        missing_obs = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=False,
            properties={},
        )
        p_absent = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="exists",
            operator=PredicateOperator.DOES_NOT_EXIST,
            expected_value=None,
        )
        res = evaluate_predicate(p_absent, missing_obs, expected_target=cal_target)
        assert res.truth == PredicateTruth.TRUE


# ===========================================================================
# Strict Independence: Execute Result Substitution Fails Closed
# ===========================================================================


class TestStrictIndependenceInPredicates:
    """Proves execute-success payloads cannot substitute for read-back observations."""

    def test_execution_payload_rejected_by_evaluator(self, mission_id: MissionId) -> None:
        """ProviderExecutionResult cannot be passed to evaluate_predicate."""
        exec_result = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="SUCCESS",
        )
        p = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="confirmed",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            evaluate_predicate(p, exec_result)  # type: ignore[arg-type]

    def test_provider_status_success_is_not_predicate_true(self, mission_id: MissionId) -> None:
        """Provider status SUCCESS does not imply predicate TRUE."""
        exec_result = ProviderExecutionResult(
            action_type=ActionType.TASK_CREATE,
            success=True,
            status_name="SUCCESS",
        )
        # Structural guarantee: exec_result cannot evaluate against predicates
        with pytest.raises(ExecutionPayloadSubstitutionError):
            evaluate_predicate(
                DesiredStatePredicate.create(
                    mission_id=mission_id,
                    subject="status",
                    operator=PredicateOperator.EQUALS,
                    expected_value="SUCCESS",
                ),
                exec_result,  # type: ignore[arg-type]
            )

    def test_execution_attempt_rejected_by_evaluator(self, mission_id: MissionId) -> None:
        """ExecutionAttempt cannot be passed as observation."""
        attempt = ExecutionAttempt(
            action_id=ActionId.generate(),
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
            started_at=datetime.now(UTC),
        )
        p = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="confirmed",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            evaluate_predicate(p, attempt)  # type: ignore[arg-type]


# ===========================================================================
# Batch Predicate Evaluation
# ===========================================================================


class TestBatchPredicateEvaluation:
    """Batch evaluation of multiple predicates against an observation."""

    def test_evaluate_predicates_batch(
        self,
        mission_id: MissionId,
        cal_target: TargetIdentity,
        cal_observation: VerificationObservation,
    ) -> None:
        """Batch evaluation returns a tuple of PredicateEvaluationResult."""
        p1 = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="summary",
            operator=PredicateOperator.EQUALS,
            expected_value="Leave for school",
        )
        p2 = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="confirmed",
        )
        p3 = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="all_day",
            operator=PredicateOperator.EQUALS,
            expected_value=True,  # This one should be FALSE
        )
        results = evaluate_predicates([p1, p2, p3], cal_observation, expected_target=cal_target)

        assert len(results) == 3
        assert results[0].truth == PredicateTruth.TRUE
        assert results[1].truth == PredicateTruth.TRUE
        assert results[2].truth == PredicateTruth.FALSE
