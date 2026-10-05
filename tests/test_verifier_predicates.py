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


# ===========================================================================
# Adversarial & Boundary Tests: Exact Numeric Comparison (Phase P-09.02 Repair)
# ===========================================================================


class TestExactNumericComparison:
    """Proves exact numeric comparison without lossy float coercion.

    Enforces:
    - 2**53 + 1 > 2**53 is True (native arbitrary-precision integer comparison)
    - 2**63 and very large positive/negative integers compare exactly
    - Mixed int and finite float compare natively without float coercion rounding
    - Non-finite floats (NaN, +inf, -inf) reject fail-closed
    - bool is strictly excluded from numeric comparison
    """

    def test_large_integer_boundaries(
        self, mission_id: MissionId, cal_target: TargetIdentity
    ) -> None:
        val_2_53 = 2**53
        val_2_53_plus_1 = 2**53 + 1

        # In standard 64-bit float, float(2**53 + 1) == float(2**53).
        # Our exact integer comparison must yield True for >
        p_gt = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="seq",
            operator=PredicateOperator.GREATER_THAN,
            expected_value=val_2_53,
        )
        obs = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"seq": val_2_53_plus_1},
        )
        res_gt = evaluate_predicate(p_gt, obs, expected_target=cal_target)
        assert res_gt.truth == PredicateTruth.TRUE

        # 2**53 + 1 == 2**53 must be FALSE
        p_eq = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="seq",
            operator=PredicateOperator.EQUALS,
            expected_value=val_2_53,
        )
        res_eq = evaluate_predicate(p_eq, obs, expected_target=cal_target)
        assert res_eq.truth == PredicateTruth.FALSE

    def test_2_63_and_very_large_integers(
        self, mission_id: MissionId, cal_target: TargetIdentity
    ) -> None:
        val_63 = 2**63
        val_huge_pos = 10**30 + 5
        val_huge_neg = -(10**30 + 5)

        p_63 = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="seq",
            operator=PredicateOperator.LESS_THAN,
            expected_value=val_63 + 10,
        )
        obs_63 = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"seq": val_63},
        )
        assert (
            evaluate_predicate(p_63, obs_63, expected_target=cal_target).truth
            == PredicateTruth.TRUE
        )

        p_huge = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="seq",
            operator=PredicateOperator.GREATER_THAN,
            expected_value=val_huge_neg,
        )
        obs_huge = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"seq": val_huge_pos},
        )
        assert (
            evaluate_predicate(p_huge, obs_huge, expected_target=cal_target).truth
            == PredicateTruth.TRUE
        )

    def test_mixed_int_and_finite_float(
        self, mission_id: MissionId, cal_target: TargetIdentity
    ) -> None:
        val_int = 2**53 + 1
        val_flt = float(2**53)

        p = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="count",
            operator=PredicateOperator.GREATER_THAN,
            expected_value=val_flt,
        )
        obs = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"count": val_int},
        )
        res = evaluate_predicate(p, obs, expected_target=cal_target)
        assert res.truth == PredicateTruth.TRUE

    def test_non_finite_float_rejected_fail_closed(
        self, mission_id: MissionId, cal_target: TargetIdentity
    ) -> None:
        nan_val = float("nan")
        inf_val = float("inf")
        neg_inf_val = float("-inf")

        for bad_val in (nan_val, inf_val, neg_inf_val):
            obs = VerificationObservation(
                target=cal_target,
                observed_at=datetime.now(UTC),
                exists=True,
                properties={"temp": bad_val},
            )
            for op in (
                PredicateOperator.EQUALS,
                PredicateOperator.GREATER_THAN,
                PredicateOperator.LESS_THAN,
                PredicateOperator.GREATER_THAN_OR_EQUAL,
                PredicateOperator.LESS_THAN_OR_EQUAL,
            ):
                p = DesiredStatePredicate.create(
                    mission_id=mission_id,
                    subject="temp",
                    operator=op,
                    expected_value=25.0,
                )
                res = evaluate_predicate(p, obs, expected_target=cal_target)
                assert res.truth == PredicateTruth.FALSE

    def test_bool_strictly_excluded_from_numeric_comparison(
        self, mission_id: MissionId, cal_target: TargetIdentity
    ) -> None:
        # True is not > 0 numerically in predicates
        p_gt = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="flag",
            operator=PredicateOperator.GREATER_THAN,
            expected_value=0,
        )
        obs = VerificationObservation(
            target=cal_target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"flag": True},
        )
        assert (
            evaluate_predicate(p_gt, obs, expected_target=cal_target).truth == PredicateTruth.FALSE
        )

        # True == 1 is FALSE
        p_eq = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="flag",
            operator=PredicateOperator.EQUALS,
            expected_value=1,
        )
        assert (
            evaluate_predicate(p_eq, obs, expected_target=cal_target).truth == PredicateTruth.FALSE
        )


# ===========================================================================
# Adversarial Sentinel Tests: Predicate Privacy (Phase P-09.02 Repair)
# ===========================================================================


class TestPredicateResultPrivacy:
    """Proves that predicate mismatch diagnostics never leak sensitive payloads or IDs.

    Enforces:
    - Reason does not echo raw target resource IDs, parent IDs, event/task titles,
      or sensitive values
    - observed_value is None on mismatch and target mismatch
    """

    SECRET_TITLE = "TOP_SECRET_MISSION_BRIEFING_99"
    SECRET_TASK_ID = "SECRET_TASK_IDENTIFIER_7788"
    SECRET_LIST_ID = "SECRET_LIST_IDENTIFIER_1122"

    def test_mismatch_reason_never_echoes_sensitive_values(self, mission_id: MissionId) -> None:
        target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id=self.SECRET_TASK_ID,
            parent_id=self.SECRET_LIST_ID,
        )
        obs = VerificationObservation(
            target=target,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"title": self.SECRET_TITLE, "status": "needsAction"},
        )
        p = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="title",
            operator=PredicateOperator.EQUALS,
            expected_value="PUBLIC_EXPECTED_TITLE",
        )
        res = evaluate_predicate(p, obs, expected_target=target)

        assert res.truth == PredicateTruth.FALSE
        assert res.observed_value is None
        reason = res.reason or ""
        assert self.SECRET_TITLE not in reason
        assert "PUBLIC_EXPECTED_TITLE" not in reason
        assert self.SECRET_TASK_ID not in reason
        assert self.SECRET_LIST_ID not in reason
        assert reason == "Exact predicate mismatch for subject 'title'"

    def test_target_mismatch_reason_never_echoes_raw_ids(self, mission_id: MissionId) -> None:
        target_actual = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id=self.SECRET_TASK_ID,
            parent_id=self.SECRET_LIST_ID,
        )
        target_expected = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="ANOTHER_SECRET_TASK_4455",
            parent_id=self.SECRET_LIST_ID,
        )
        obs = VerificationObservation(
            target=target_actual,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={"status": "needsAction"},
        )
        p = DesiredStatePredicate.create(
            mission_id=mission_id,
            subject="status",
            operator=PredicateOperator.EQUALS,
            expected_value="needsAction",
        )
        res = evaluate_predicate(p, obs, expected_target=target_expected)

        assert res.truth == PredicateTruth.FALSE
        assert res.observed_value is None
        reason = res.reason or ""
        assert self.SECRET_TASK_ID not in reason
        assert "ANOTHER_SECRET_TASK_4455" not in reason
        assert reason == "Target identity mismatch"
