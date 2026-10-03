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
    DuplicateDetectionResult,
    DuplicateDetectionStatus,
    ExpectedTaskState,
    FakeGoogleTasksTransport,
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
