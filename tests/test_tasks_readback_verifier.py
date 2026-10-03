"""Comprehensive unit and adversarial tests for Google Tasks read-back verification
and duplicate detection (P-06.05).

Validates:
1. create response cannot substitute for verifier read;
2. distinct exact provider get occurs;
3. matching title/due returns MATCH;
4. title mismatch returns sanitized MISMATCH;
5. due mismatch uses DATE semantics;
6. not-found explicit;
7. provider-error explicit and sanitized;
8. verifier performs zero writes;
9. external drift after creation produces MISMATCH;
10. duplicate scanner performs separate list read;
11. one matching task -> UNIQUE_MATCH;
12. two matching tasks -> DUPLICATE_DETECTED;
13. duplicate on later page is detected;
14. pagination follows page tokens;
15. scan bound exhaustion fails closed / cannot certify uniqueness;
16. completed/deleted/hidden/assigned items do not create a false active duplicate;
17. expected/result repr/str and logs leak no IDs/list IDs/private titles/due/token/provider URLs;
18. zero READY/VERIFIED promotion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.adapters.tasks import (
    MAX_DUPLICATE_SCAN_PAGES,
    MAX_TASKS_PAGE_SIZE,
    DuplicateDetectionResult,
    DuplicateDetectionStatus,
    ExpectedTaskState,
    FakeGoogleTasksTransport,
    GoogleApiClientTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksDuplicateDetector,
    GoogleTasksReadAdapter,
    GoogleTasksReadbackVerifier,
    TaskCreateStatus,
    TaskObservation,
    TaskReadbackResult,
    TaskReadbackStatus,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId

# ===========================================================================
# Fixtures
# ===========================================================================

DEMO_CALENDAR_ID = "stilldone-demo-cal-12345@group.calendar.google.com"
DEMO_TASK_LIST_ID = "stilldone-demo-tasklist-67890"


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id=DEMO_TASK_LIST_ID,
    )


@pytest.fixture
def fake_transport() -> FakeGoogleTasksTransport:
    return FakeGoogleTasksTransport()


@pytest.fixture
def read_adapter(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleTasksTransport
) -> GoogleTasksReadAdapter:
    return GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)


@pytest.fixture
def create_adapter(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleTasksTransport
) -> GoogleTasksCreateAdapter:
    return GoogleTasksCreateAdapter(scope=demo_scope, transport=fake_transport)


@pytest.fixture
def verifier(read_adapter: GoogleTasksReadAdapter) -> GoogleTasksReadbackVerifier:
    return GoogleTasksReadbackVerifier(read_adapter=read_adapter)


@pytest.fixture
def duplicate_detector(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleTasksTransport
) -> GoogleTasksDuplicateDetector:
    return GoogleTasksDuplicateDetector(scope=demo_scope, transport=fake_transport)


def _make_create_action(
    title: str = "Pack backpacks",
    due: str | None = "2026-10-04",
) -> ActionContract:
    params: dict[str, Any] = {"title": title}
    if due is not None:
        params["due"] = due
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id=DEMO_TASK_LIST_ID,
            parent_id=None,
        ),
        parameters=params,
    )


# ===========================================================================
# 1-9. Independent Read-back Verification Tests
# ===========================================================================


class TestTasksReadbackVerifier:
    def test_create_response_cannot_substitute_for_verifier_read(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        verifier: GoogleTasksReadbackVerifier,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        """Prove create response does NOT verify task; separate read is required."""
        action = _make_create_action("Pack backpacks", "2026-10-04")
        create_res = create_adapter.create_task(action)
        assert create_res.status == TaskCreateStatus.CREATED
        assert fake_transport.writes_count == 1
        assert fake_transport.reads_count == 0

        # Verifier performs a distinct fresh read
        expected = ExpectedTaskState(title="Pack backpacks", due="2026-10-04")
        assert create_res.task_id is not None
        verify_res = verifier.verify_task_state(create_res.task_id, expected)
        assert verify_res.status == TaskReadbackStatus.MATCH
        assert fake_transport.reads_count == 1

    def test_distinct_exact_provider_get_occurs(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_exact_99",
            title="Inspect uniform",
            due="2026-10-04T00:00:00.000Z",
        )
        expected = ExpectedTaskState(title="Inspect uniform", due="2026-10-04")
        res = verifier.verify_task_state("task_exact_99", expected)
        assert res.status == TaskReadbackStatus.MATCH
        assert fake_transport.reads_count == 1
        assert fake_transport.writes_count == 0

    def test_matching_title_and_due_returns_match(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_match",
            title="Set morning alarm",
            due="2026-10-04T00:00:00.000Z",
        )
        expected = ExpectedTaskState(title="Set morning alarm", due="2026-10-04")
        res = verifier.verify_task_state("task_match", expected)
        assert res.status == TaskReadbackStatus.MATCH
        assert res.mismatches == ()
        assert res.observation is not None
        assert res.observation.title == "Set morning alarm"
        assert res.observation.due == "2026-10-04"

    def test_title_mismatch_returns_sanitized_mismatch(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_wrong_title",
            title="Actual Observed Title",
            due="2026-10-04T00:00:00.000Z",
        )
        expected = ExpectedTaskState(title="Expected Target Title", due="2026-10-04")
        res = verifier.verify_task_state("task_wrong_title", expected)
        assert res.status == TaskReadbackStatus.MISMATCH
        assert res.mismatches == ("title mismatch",)
        assert "Actual Observed Title" not in res.mismatches
        assert "Expected Target Title" not in res.mismatches

    def test_due_mismatch_uses_date_semantics(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_due_check",
            title="Prepare breakfast",
            due="2026-10-05T00:00:00.000Z",
        )
        # Expected due 2026-10-04 vs observed 2026-10-05
        expected = ExpectedTaskState(title="Prepare breakfast", due="2026-10-04")
        res = verifier.verify_task_state("task_due_check", expected)
        assert res.status == TaskReadbackStatus.MISMATCH
        assert res.mismatches == ("due mismatch",)

    def test_task_not_found_is_explicit(
        self,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        expected = ExpectedTaskState(title="Any task", due=None)
        res = verifier.verify_task_state("nonexistent_task_id", expected)
        assert res.status == TaskReadbackStatus.NOT_FOUND
        assert res.mismatches == ("task not found",)

    def test_provider_error_explicit_and_sanitized(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        mock_transport = MagicMock()
        mock_transport.get_task.side_effect = RuntimeError(
            "Fatal provider crash connecting to https://tasks.googleapis.com with token ya29.secret"
        )
        read_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=mock_transport)
        verifier = GoogleTasksReadbackVerifier(read_adapter=read_adapter)

        expected = ExpectedTaskState(title="Test", due=None)
        res = verifier.verify_task_state("task_err", expected)
        assert res.status == TaskReadbackStatus.PROVIDER_ERROR
        assert res.error_message is not None
        assert "ya29.secret" not in res.error_message
        assert "https://tasks.googleapis.com" not in res.error_message

    def test_verifier_performs_zero_writes(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_zero_write",
            title="Read only task",
            due=None,
        )
        expected = ExpectedTaskState(title="Read only task", due=None)
        verifier.verify_task_state("task_zero_write", expected)
        assert fake_transport.writes_count == 0

    def test_external_drift_after_creation_produces_mismatch(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        verifier: GoogleTasksReadbackVerifier,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        """Prove that if real world drifts after create, read-back discovers mismatch."""
        action = _make_create_action("Pack backpacks", "2026-10-04")
        create_res = create_adapter.create_task(action)
        assert create_res.status == TaskCreateStatus.CREATED
        task_id = create_res.task_id
        assert task_id is not None

        # Simulate external drift by modifying stored task directly in provider
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id=task_id,
            title="Pack backpacks (MODIFIED EXTERNALLY BY OPERATOR)",
            due="2026-10-04T00:00:00.000Z",
        )

        expected = ExpectedTaskState(title="Pack backpacks", due="2026-10-04")
        verify_res = verifier.verify_task_state(task_id, expected)
        assert verify_res.status == TaskReadbackStatus.MISMATCH
        assert verify_res.mismatches == ("title mismatch",)


# ===========================================================================
# 10-16. Duplicate Detection Tests
# ===========================================================================


class TestTasksDuplicateDetector:
    def test_duplicate_scanner_performs_separate_list_read(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t1",
            title="Leave for school",
            due="2026-10-04T00:00:00.000Z",
        )
        expected = ExpectedTaskState(title="Leave for school", due="2026-10-04")
        res = duplicate_detector.detect_duplicates(expected)
        assert res.status == DuplicateDetectionStatus.UNIQUE_MATCH
        assert fake_transport.list_count == 1
        assert fake_transport.reads_count == 0
        assert fake_transport.writes_count == 0

    def test_one_matching_task_is_unique_match(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t1",
            title="Pack lunch",
            due=None,
        )
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t2",
            title="Different task",
            due=None,
        )
        expected = ExpectedTaskState(title="Pack lunch", due=None)
        res = duplicate_detector.detect_duplicates(expected)
        assert res.status == DuplicateDetectionStatus.UNIQUE_MATCH
        assert res.match_count == 1

    def test_two_matching_tasks_detected_as_duplicate(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t1",
            title="Pack lunch",
            due="2026-10-04T00:00:00.000Z",
        )
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t2",
            title="Pack lunch",
            due="2026-10-04T00:00:00.000Z",
        )
        expected = ExpectedTaskState(title="Pack lunch", due="2026-10-04")
        res = duplicate_detector.detect_duplicates(expected)
        assert res.status == DuplicateDetectionStatus.DUPLICATE_DETECTED
        assert res.match_count == 2

    def test_zero_matching_tasks_is_no_match(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t1",
            title="Other task",
            due=None,
        )
        expected = ExpectedTaskState(title="Unrelated task", due=None)
        res = duplicate_detector.detect_duplicates(expected)
        assert res.status == DuplicateDetectionStatus.NO_MATCH
        assert res.match_count == 0

    def test_duplicate_on_later_page_is_detected(
        self,
        demo_scope: DemoResourceScope,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        # Configure small page_size = 2
        detector = GoogleTasksDuplicateDetector(
            scope=demo_scope,
            transport=fake_transport,
            max_scan_pages=5,
            page_size=2,
        )
        # Page 1: item 1 (match), item 2 (no match)
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t1", "Buy milk", due="2026-10-04")
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t2", "Call school", due="2026-10-04")
        # Page 2: item 3 (match duplicate), item 4 (no match)
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t3", "Buy milk", due="2026-10-04")
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t4", "Wash clothes", due="2026-10-04")

        expected = ExpectedTaskState(title="Buy milk", due="2026-10-04")
        res = detector.detect_duplicates(expected)
        assert res.status == DuplicateDetectionStatus.DUPLICATE_DETECTED
        assert res.match_count == 2
        assert res.scanned_pages == 2
        assert res.scanned_tasks == 4

    def test_scan_bound_exhaustion_fails_closed(
        self,
        demo_scope: DemoResourceScope,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        """Prove that exceeding max_scan_pages produces SCAN_LIMIT_EXCEEDED."""
        # max_scan_pages = 2, page_size = 2
        detector = GoogleTasksDuplicateDetector(
            scope=demo_scope,
            transport=fake_transport,
            max_scan_pages=2,
            page_size=2,
        )
        # Seed 6 tasks (3 pages total)
        for i in range(6):
            fake_transport.seed_task(DEMO_TASK_LIST_ID, f"t{i}", f"Task {i}")

        expected = ExpectedTaskState(title="Nonexistent title", due=None)
        res = detector.detect_duplicates(expected)
        assert res.status == DuplicateDetectionStatus.SCAN_LIMIT_EXCEEDED
        assert res.scanned_pages == 2
        assert res.scanned_tasks == 4

    def test_completed_deleted_hidden_tasks_do_not_create_false_duplicate(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        # Active matching task
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t_active",
            title="Review homework",
            status="needsAction",
            deleted=False,
            hidden=False,
        )
        # Completed duplicate (should be ignored by active scan)
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t_completed",
            title="Review homework",
            status="completed",
            deleted=False,
            hidden=False,
        )
        # Deleted duplicate (should be ignored)
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t_deleted",
            title="Review homework",
            status="needsAction",
            deleted=True,
            hidden=False,
        )
        # Hidden duplicate (should be ignored)
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="t_hidden",
            title="Review homework",
            status="needsAction",
            deleted=False,
            hidden=True,
        )

        expected = ExpectedTaskState(title="Review homework", due=None)
        res = duplicate_detector.detect_duplicates(expected)
        # Only the 1 active non-deleted task counts
        assert res.status == DuplicateDetectionStatus.UNIQUE_MATCH
        assert res.match_count == 1


# ===========================================================================
# 17-18. Privacy & Absence of READY/VERIFIED Promotions
# ===========================================================================


class TestAdversarialPrivacyAndNoPromotion:
    SECRET_TITLE = "Super Confidential Medical Appointment Task Title 42"
    SECRET_DUE = "2026-10-04"
    SECRET_TASK_ID = "SECRET_TASK_ID_OMEGA_99"

    def test_expected_task_state_repr_str_masks_private_values(self) -> None:
        exp = ExpectedTaskState(title=self.SECRET_TITLE, due=self.SECRET_DUE)
        for rep in (repr(exp), str(exp)):
            assert self.SECRET_TITLE not in rep
            assert self.SECRET_DUE not in rep
            assert "has_title=True" in rep
            assert "has_due=True" in rep

    def test_readback_result_repr_str_masks_private_values(self) -> None:
        obs = TaskObservation(
            task_id=self.SECRET_TASK_ID,
            task_list_id=DEMO_TASK_LIST_ID,
            title=self.SECRET_TITLE,
            due=self.SECRET_DUE,
            status="needsAction",
            deleted=False,
            hidden=False,
            etag="etag99",
            observed_at=datetime.now(UTC),
        )
        res = TaskReadbackResult(
            status=TaskReadbackStatus.MISMATCH,
            mismatches=("title mismatch", "due mismatch"),
            observation=obs,
            error_message="Sanitized error",
        )
        for rep in (repr(res), str(res)):
            assert self.SECRET_TITLE not in rep
            assert self.SECRET_DUE not in rep
            assert self.SECRET_TASK_ID not in rep
            assert "title mismatch" in rep

    def test_duplicate_result_repr_str_masks_private_values(self) -> None:
        res = DuplicateDetectionResult(
            status=DuplicateDetectionStatus.DUPLICATE_DETECTED,
            match_count=2,
            scanned_pages=1,
            scanned_tasks=2,
            error_message="Sanitized duplicate error",
        )
        for rep in (repr(res), str(res)):
            assert "DUPLICATE_DETECTED" in rep
            assert "match_count=2" in rep

    def test_zero_ready_or_verified_promotion(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        """Prove that verifier and duplicate detector produce typed adapter outcomes only.

        Neither verifier nor duplicate detector can mutate mission state
        or promote to READY/VERIFIED.
        """
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t1", "Check bags", due="2026-10-04")
        expected = ExpectedTaskState(title="Check bags", due="2026-10-04")

        v_res = verifier.verify_task_state("t1", expected)
        d_res = duplicate_detector.detect_duplicates(expected)

        assert not hasattr(v_res, "mission_state")
        assert not hasattr(d_res, "mission_state")
        assert not hasattr(v_res, "is_verified")
        assert not hasattr(d_res, "is_ready")
        assert v_res.status == TaskReadbackStatus.MATCH
        assert d_res.status == DuplicateDetectionStatus.UNIQUE_MATCH


# ===========================================================================
# 19. Truthful Runtime Timestamps (P-06.05 Repair Defect A)
# ===========================================================================


class TestTruthfulRuntimeTimestamps:
    PAST_AT = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    FUTURE_AT = datetime(2099, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_verifier_verified_at_runtime_owned_not_forged_by_caller_at(
        self,
        fake_transport: FakeGoogleTasksTransport,
        verifier: GoogleTasksReadbackVerifier,
    ) -> None:
        """Prove verified_at is strictly runtime-owned and not forgeable via 'at'."""
        # 1. MATCH
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t_match", "Match title", due="2026-10-04")
        exp_match = ExpectedTaskState(title="Match title", due="2026-10-04")
        res_match = verifier.verify_task_state("t_match", exp_match, at=self.PAST_AT)
        assert res_match.status == TaskReadbackStatus.MATCH
        assert res_match.verified_at != self.PAST_AT
        assert res_match.verified_at.year >= 2026
        assert res_match.observation is not None
        assert res_match.verified_at >= res_match.observation.observed_at

        # 2. MISMATCH
        exp_mismatch = ExpectedTaskState(title="Different title", due="2026-10-04")
        res_mismatch = verifier.verify_task_state("t_match", exp_mismatch, at=self.FUTURE_AT)
        assert res_mismatch.status == TaskReadbackStatus.MISMATCH
        assert res_mismatch.verified_at != self.FUTURE_AT
        assert res_mismatch.verified_at.year >= 2026
        assert res_mismatch.observation is not None
        assert res_mismatch.verified_at >= res_mismatch.observation.observed_at

        # 3. NOT_FOUND
        res_nf = verifier.verify_task_state("nonexistent", exp_match, at=self.PAST_AT)
        assert res_nf.status == TaskReadbackStatus.NOT_FOUND
        assert res_nf.verified_at != self.PAST_AT
        assert res_nf.verified_at.year >= 2026

        # 4. PROVIDER_ERROR
        failing_transport = MagicMock(spec=FakeGoogleTasksTransport)
        failing_transport.get_task.side_effect = RuntimeError("transport network down")
        failing_read_adapter = GoogleTasksReadAdapter(
            scope=DemoResourceScope(DEMO_CALENDAR_ID, DEMO_TASK_LIST_ID),
            transport=failing_transport,
        )
        failing_verifier = GoogleTasksReadbackVerifier(read_adapter=failing_read_adapter)
        res_err = failing_verifier.verify_task_state("t_match", exp_match, at=self.PAST_AT)
        assert res_err.status == TaskReadbackStatus.PROVIDER_ERROR
        assert res_err.verified_at != self.PAST_AT
        assert res_err.verified_at.year >= 2026

    def test_duplicate_detector_evaluated_at_runtime_owned_not_forged_by_caller_at(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        """Prove evaluated_at is strictly runtime-owned and not forgeable via 'at'."""
        # 1. NO_MATCH
        exp = ExpectedTaskState(title="No match here", due=None)
        res_no = duplicate_detector.detect_duplicates(exp, at=self.PAST_AT)
        assert res_no.status == DuplicateDetectionStatus.NO_MATCH
        assert res_no.evaluated_at != self.PAST_AT
        assert res_no.evaluated_at.year >= 2026

        # 2. UNIQUE_MATCH
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t_single", "Single item")
        exp_single = ExpectedTaskState(title="Single item")
        res_unique = duplicate_detector.detect_duplicates(exp_single, at=self.FUTURE_AT)
        assert res_unique.status == DuplicateDetectionStatus.UNIQUE_MATCH
        assert res_unique.evaluated_at != self.FUTURE_AT
        assert res_unique.evaluated_at.year >= 2026

        # 3. DUPLICATE_DETECTED
        fake_transport.seed_task(DEMO_TASK_LIST_ID, "t_dup", "Single item")
        res_dup = duplicate_detector.detect_duplicates(exp_single, at=self.PAST_AT)
        assert res_dup.status == DuplicateDetectionStatus.DUPLICATE_DETECTED
        assert res_dup.evaluated_at != self.PAST_AT
        assert res_dup.evaluated_at.year >= 2026

        # 4. SCAN_LIMIT_EXCEEDED
        bounded_detector = GoogleTasksDuplicateDetector(
            scope=DemoResourceScope(DEMO_CALENDAR_ID, DEMO_TASK_LIST_ID),
            transport=fake_transport,
            max_scan_pages=1,
            page_size=1,
        )
        res_limit = bounded_detector.detect_duplicates(exp_single, at=self.PAST_AT)
        assert res_limit.status == DuplicateDetectionStatus.SCAN_LIMIT_EXCEEDED
        assert res_limit.evaluated_at != self.PAST_AT
        assert res_limit.evaluated_at.year >= 2026

        # 5. PROVIDER_ERROR
        failing_transport = MagicMock(spec=FakeGoogleTasksTransport)
        failing_transport.list_tasks.side_effect = RuntimeError("transport list failure")
        failing_detector = GoogleTasksDuplicateDetector(
            scope=DemoResourceScope(DEMO_CALENDAR_ID, DEMO_TASK_LIST_ID),
            transport=failing_transport,
        )
        res_err = failing_detector.detect_duplicates(exp_single, at=self.PAST_AT)
        assert res_err.status == DuplicateDetectionStatus.PROVIDER_ERROR
        assert res_err.evaluated_at != self.PAST_AT
        assert res_err.evaluated_at.year >= 2026


# ===========================================================================
# 20. Duplicate Scan Bounds Validation (P-06.05 Repair Defect B)
# ===========================================================================


class TestDuplicateScanBounds:
    def test_duplicate_detector_bounds_validation(
        self,
        demo_scope: DemoResourceScope,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        """Prove max_scan_pages and page_size enforce fail-closed bounds."""
        # Valid bounds
        det_min = GoogleTasksDuplicateDetector(
            scope=demo_scope, transport=fake_transport, max_scan_pages=1, page_size=1
        )
        assert det_min._max_scan_pages == 1
        assert det_min._page_size == 1

        det_max = GoogleTasksDuplicateDetector(
            scope=demo_scope,
            transport=fake_transport,
            max_scan_pages=MAX_DUPLICATE_SCAN_PAGES,
            page_size=MAX_TASKS_PAGE_SIZE,
        )
        assert det_max._max_scan_pages == MAX_DUPLICATE_SCAN_PAGES
        assert det_max._page_size == MAX_TASKS_PAGE_SIZE

        # Invalid max_scan_pages
        with pytest.raises(ValueError, match="max_scan_pages must be between 1 and 5"):
            GoogleTasksDuplicateDetector(
                scope=demo_scope, transport=fake_transport, max_scan_pages=0
            )

        with pytest.raises(ValueError, match="max_scan_pages must be between 1 and 5"):
            GoogleTasksDuplicateDetector(
                scope=demo_scope, transport=fake_transport, max_scan_pages=-1
            )

        with pytest.raises(ValueError, match="max_scan_pages must be between 1 and 5"):
            GoogleTasksDuplicateDetector(
                scope=demo_scope, transport=fake_transport, max_scan_pages=6
            )

        # Invalid page_size
        with pytest.raises(ValueError, match="page_size must be between 1 and 100"):
            GoogleTasksDuplicateDetector(scope=demo_scope, transport=fake_transport, page_size=0)

        with pytest.raises(ValueError, match="page_size must be between 1 and 100"):
            GoogleTasksDuplicateDetector(scope=demo_scope, transport=fake_transport, page_size=-5)

        with pytest.raises(ValueError, match="page_size must be between 1 and 100"):
            GoogleTasksDuplicateDetector(scope=demo_scope, transport=fake_transport, page_size=101)


# ===========================================================================
# 21. Assigned Tasks in Duplicate Scan (P-06.05 Repair Defect C)
# ===========================================================================


class TestAssignedTasksDuplicateScan:
    def test_assigned_task_excluded_from_duplicates(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        """Prove that assigned tasks do not produce false duplicate detection."""
        # Seed 1 active user task
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="active_1",
            title="Shared project item",
            due=None,
            assigned=False,
        )
        # Seed 1 assigned task (e.g. from Google Docs / Chat / Spaces)
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="assigned_1",
            title="Shared project item",
            due=None,
            assigned=True,
        )

        expected = ExpectedTaskState(title="Shared project item", due=None)
        res = duplicate_detector.detect_duplicates(expected)

        # Assigned task is excluded, exactly 1 active match found
        assert res.status == DuplicateDetectionStatus.UNIQUE_MATCH
        assert res.match_count == 1

    def test_assigned_task_with_assignment_info_excluded_from_duplicates(
        self,
        fake_transport: FakeGoogleTasksTransport,
        duplicate_detector: GoogleTasksDuplicateDetector,
    ) -> None:
        """Prove that tasks with assignmentInfo dictionary are excluded from duplicates."""
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="active_2",
            title="Space sync task",
            due=None,
        )
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="assigned_space_task",
            title="Space sync task",
            due=None,
            extra_fields={"assignmentInfo": {"link": "https://chat.google.com/space/123"}},
        )

        expected = ExpectedTaskState(title="Space sync task", due=None)
        res = duplicate_detector.detect_duplicates(expected)

        assert res.status == DuplicateDetectionStatus.UNIQUE_MATCH
        assert res.match_count == 1

    def test_production_transport_passes_show_assigned_false(self) -> None:
        """Prove GoogleApiClientTasksTransport passes showAssigned=False and clamps maxResults."""
        mock_service = MagicMock()
        mock_tasks_resource = MagicMock()
        mock_list_req = MagicMock()
        mock_service.tasks.return_value = mock_tasks_resource
        mock_tasks_resource.list.return_value = mock_list_req
        mock_list_req.execute.return_value = {"items": []}

        transport = GoogleApiClientTasksTransport(mock_service)
        items, page_token = transport.list_tasks(
            task_list_id="my_demo_list",
            max_results=50,
            show_assigned=False,
        )

        assert items == []
        assert page_token is None
        mock_tasks_resource.list.assert_called_once_with(
            tasklist="my_demo_list",
            showCompleted=False,
            showDeleted=False,
            showHidden=False,
            showAssigned=False,
            maxResults=50,
        )

        # Clamping check: > 100 clamped to 100, < 1 clamped to 1
        mock_tasks_resource.list.reset_mock()
        transport.list_tasks(task_list_id="my_demo_list", max_results=500)
        assert mock_tasks_resource.list.call_args[1]["maxResults"] == 100

        mock_tasks_resource.list.reset_mock()
        transport.list_tasks(task_list_id="my_demo_list", max_results=-10)
        assert mock_tasks_resource.list.call_args[1]["maxResults"] == 1


# ===========================================================================
# 22. Extended Hostile Privacy Sentinels (P-06.05 Repair Defect D)
# ===========================================================================


class TestExtendedHostilePrivacySentinels:
    SENTINEL_TASK_LIST_ID = "SENTINEL_DEMO_TASKLIST_ID_ALPHA_99"
    SENTINEL_TASK_ID = "SENTINEL_TASK_ID_BETA_77"
    SENTINEL_TITLE = "SENTINEL_CONFIDENTIAL_TITLE_GAMMA_55"
    SENTINEL_DUE = "2026-12-31"
    SENTINEL_TOKEN = "ya29.SENTINEL_BEARER_TOKEN_SECRET_999"
    SENTINEL_URL = "https://tasks.googleapis.com/tasks/v1/users/@me/lists/SECRET_PATH"

    def test_readback_and_duplicate_privacy_sentinels(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Prove that sentinel values never leak into repr, str, errors, mismatches, or logs."""
        import logging

        scope = DemoResourceScope(DEMO_CALENDAR_ID, self.SENTINEL_TASK_LIST_ID)
        transport = FakeGoogleTasksTransport()
        transport.seed_task(
            task_list_id=self.SENTINEL_TASK_LIST_ID,
            task_id=self.SENTINEL_TASK_ID,
            title=self.SENTINEL_TITLE,
            due=self.SENTINEL_DUE,
        )

        read_adapter = GoogleTasksReadAdapter(scope=scope, transport=transport)
        verifier = GoogleTasksReadbackVerifier(read_adapter=read_adapter)
        duplicate_detector = GoogleTasksDuplicateDetector(scope=scope, transport=transport)

        # Check verifier and duplicate detector repr/str
        for obj in (verifier, duplicate_detector):
            rep = repr(obj)
            st = str(obj)
            for sentinel in (
                self.SENTINEL_TASK_LIST_ID,
                self.SENTINEL_TASK_ID,
                self.SENTINEL_TITLE,
                self.SENTINEL_DUE,
                self.SENTINEL_TOKEN,
                self.SENTINEL_URL,
            ):
                assert sentinel not in rep
                assert sentinel not in st

        # Readback with mismatch
        expected_diff = ExpectedTaskState(title="Different Title", due="2026-01-01")
        with caplog.at_level(logging.DEBUG):
            readback_res = verifier.verify_task_state(self.SENTINEL_TASK_ID, expected_diff)

        assert readback_res.status == TaskReadbackStatus.MISMATCH
        # Mismatches list must only have generic tokens
        assert readback_res.mismatches == ("title mismatch", "due mismatch")

        for rep in (repr(readback_res), str(readback_res)):
            for sentinel in (
                self.SENTINEL_TASK_LIST_ID,
                self.SENTINEL_TASK_ID,
                self.SENTINEL_TITLE,
                self.SENTINEL_DUE,
                self.SENTINEL_TOKEN,
                self.SENTINEL_URL,
            ):
                assert sentinel not in rep

        # Duplicate detector result
        expected_dup = ExpectedTaskState(title=self.SENTINEL_TITLE, due=self.SENTINEL_DUE)
        with caplog.at_level(logging.DEBUG):
            dup_res = duplicate_detector.detect_duplicates(expected_dup)

        assert dup_res.status == DuplicateDetectionStatus.UNIQUE_MATCH
        for rep in (repr(dup_res), str(dup_res)):
            for sentinel in (
                self.SENTINEL_TASK_LIST_ID,
                self.SENTINEL_TASK_ID,
                self.SENTINEL_TITLE,
                self.SENTINEL_DUE,
                self.SENTINEL_TOKEN,
                self.SENTINEL_URL,
            ):
                assert sentinel not in rep

        # Provider error scenario with hostile exception message
        hostile_msg = f"Transport error with {self.SENTINEL_TOKEN} and {self.SENTINEL_URL}"
        failing_transport = MagicMock(spec=FakeGoogleTasksTransport)
        failing_transport.list_tasks.side_effect = RuntimeError(hostile_msg)
        failing_detector = GoogleTasksDuplicateDetector(scope=scope, transport=failing_transport)

        with caplog.at_level(logging.DEBUG):
            err_dup_res = failing_detector.detect_duplicates(expected_dup)

        assert err_dup_res.status == DuplicateDetectionStatus.PROVIDER_ERROR
        assert err_dup_res.error_message is not None
        assert self.SENTINEL_TOKEN not in err_dup_res.error_message
        assert self.SENTINEL_URL not in err_dup_res.error_message

        # Check captured logs
        log_text = caplog.text
        for sentinel in (
            self.SENTINEL_TASK_LIST_ID,
            self.SENTINEL_TASK_ID,
            self.SENTINEL_TITLE,
            self.SENTINEL_TOKEN,
            self.SENTINEL_URL,
        ):
            assert sentinel not in log_text
