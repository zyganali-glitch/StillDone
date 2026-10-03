"""Comprehensive unit tests for StillDone Google Tasks read and create adapters (P-06.04).

Validates:
- Exact TASK_READ and TASK_CREATE action contracts, authority policy, and demo isolation.
- Provider interaction counts and strict payload boundaries.
- Due date normalization (bare date, RFC3339, time discard, malformed dates).
- Hostile adversarial privacy sentinels (no leakage in str, repr, logs, errors).
- Sanitized error handling across all transport failure modes.
- Absence of VERIFIED / READY promotions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stilldone.action_policy import (
    MissingRequiredParameterError,
    UnknownParameterError,
)
from stilldone.adapters.tasks import (
    CANONICAL_TASK_LIST_RESOURCE_KIND,
    CANONICAL_TASK_RESOURCE_KIND,
    CANONICAL_TASKS_SYSTEM,
    FakeGoogleTasksTransport,
    GoogleApiClientTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
    TaskAuthenticationError,
    TaskCreateResult,
    TaskCreateStatus,
    TaskDueFormatError,
    TaskObservation,
    TaskRateLimitError,
    TaskReadResult,
    TaskReadStatus,
    TaskScopeError,
    TaskTargetError,
    format_due_for_provider,
    normalize_task_due,
)
from stilldone.authority_policy import (
    UnexpectedApprovalGrantError,
)
from stilldone.demo_isolation import (
    DemoResourceScope,
    MissingParentContainerError,
    TaskOutOfScopeError,
    UnexpectedParentContainerError,
)
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    AuthorityClass,
)
from stilldone.domain.mission import MissionId

# ===========================================================================
# Fixtures & Helpers
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


def _make_task_read_contract(
    task_list_id: str | None = DEMO_TASK_LIST_ID,
    task_id: str = "task_123",
    parameters: dict[str, Any] | None = None,
    system: str = CANONICAL_TASKS_SYSTEM,
    resource_kind: ResourceKind = CANONICAL_TASK_RESOURCE_KIND,
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_READ,
        target=TargetIdentity(
            system=system,
            resource_kind=resource_kind,
            resource_id=task_id,
            parent_id=task_list_id,
        ),
        parameters=parameters or {},
    )


def _make_task_create_contract(
    task_list_id: str = DEMO_TASK_LIST_ID,
    parent_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    system: str = CANONICAL_TASKS_SYSTEM,
    resource_kind: ResourceKind = CANONICAL_TASK_LIST_RESOURCE_KIND,
) -> ActionContract:
    params = {"title": "Default title"} if parameters is None else parameters
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TargetIdentity(
            system=system,
            resource_kind=resource_kind,
            resource_id=task_list_id,
            parent_id=parent_id,
        ),
        parameters=params,
    )


# ===========================================================================
# Due Normalization Tests
# ===========================================================================


class TestDueNormalization:
    def test_none_due_returns_none(self) -> None:
        assert normalize_task_due(None) is None
        assert format_due_for_provider(None) is None

    def test_bare_date_normalization(self) -> None:
        norm = normalize_task_due("2026-10-04")
        assert norm == "2026-10-04"
        provider_fmt = format_due_for_provider(norm)
        assert provider_fmt == "2026-10-04T00:00:00.000Z"

    def test_rfc3339_z_accepted(self) -> None:
        norm = normalize_task_due("2026-10-04T15:30:00Z")
        assert norm == "2026-10-04"
        norm_frac = normalize_task_due("2026-10-04T15:30:00.123456Z")
        assert norm_frac == "2026-10-04"
        provider_fmt = format_due_for_provider(norm)
        assert provider_fmt == "2026-10-04T00:00:00.000Z"

    def test_rfc3339_explicit_offset_accepted(self) -> None:
        norm_pos = normalize_task_due("2026-10-04T23:59:59.123+03:00")
        assert norm_pos == "2026-10-04"
        norm_neg = normalize_task_due("2026-10-04T00:15:00-05:00")
        assert norm_neg == "2026-10-04"

    def test_timezone_less_datetime_rejected(self) -> None:
        with pytest.raises(TaskDueFormatError, match="strict RFC3339 timestamp with timezone"):
            normalize_task_due("2026-10-04T15:30:00")
        with pytest.raises(TaskDueFormatError, match="strict RFC3339 timestamp with timezone"):
            normalize_task_due("2026-10-04T15:30:00.500")

    def test_compact_offset_rejected(self) -> None:
        # Compact timezone offsets lacking colon (e.g. +0300) must be rejected
        with pytest.raises(TaskDueFormatError, match="strict RFC3339 timestamp with timezone"):
            normalize_task_due("2026-10-04T15:30:00+0300")
        with pytest.raises(TaskDueFormatError, match="strict RFC3339 timestamp with timezone"):
            normalize_task_due("2026-10-04T15:30:00-0500")

    def test_provider_returned_midnight_normalizes_to_same_date(self) -> None:
        # Provider returns RFC3339 UTC midnight
        provider_val = "2026-10-04T00:00:00.000Z"
        obs_norm = normalize_task_due(provider_val)
        assert obs_norm == "2026-10-04"

    def test_timezone_offset_never_shifts_canonical_requested_date(self) -> None:
        # User requested date in late evening or early morning with large timezone offsets
        # Must preserve requested calendar DATE directly without UTC day-shifting
        norm_late = normalize_task_due("2026-10-04T23:59:00-08:00")
        assert norm_late == "2026-10-04"
        norm_early = normalize_task_due("2026-10-04T00:01:00+10:00")
        assert norm_early == "2026-10-04"

    def test_malformed_due_fails_closed(self) -> None:
        with pytest.raises(TaskDueFormatError):
            normalize_task_due("not-a-date")

        with pytest.raises(TaskDueFormatError):
            normalize_task_due("")

        with pytest.raises(TaskDueFormatError):
            normalize_task_due("   ")

        # Invalid calendar dates (e.g. Feb 30 or month 13)
        with pytest.raises(TaskDueFormatError):
            normalize_task_due("2026-02-30")

        with pytest.raises(TaskDueFormatError):
            normalize_task_due("2026-13-01")

        # Impossible time values
        with pytest.raises(TaskDueFormatError):
            normalize_task_due("2026-10-04T25:00:00Z")

        with pytest.raises(TaskDueFormatError):
            normalize_task_due("2026-10-04T12:60:00Z")

        with pytest.raises(TaskDueFormatError):
            normalize_task_due("2026-10-04T12:00:00+25:00")

        with pytest.raises(TaskDueFormatError):
            normalize_task_due("2026-10-04T12:00:00+03:99")


# ===========================================================================
# GoogleTasksReadAdapter Tests
# ===========================================================================


class TestGoogleTasksReadAdapter:
    def test_scope_validation_rejects_forbidden_ids(self) -> None:
        for forbidden in ("@default", "default", "primary"):
            scope = DemoResourceScope(calendar_id=DEMO_CALENDAR_ID, task_list_id=forbidden)
            with pytest.raises(TaskScopeError, match="Dedicated demo task list required"):
                GoogleTasksReadAdapter(scope=scope, transport=FakeGoogleTasksTransport())

    def test_exact_task_read_performs_one_get(
        self,
        read_adapter: GoogleTasksReadAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_123",
            title="Buy groceries",
            due="2026-10-04T00:00:00.000Z",
        )

        action = _make_task_read_contract(task_id="task_123")

        result = read_adapter.read_task(action)
        assert result.status == TaskReadStatus.MATCH
        assert result.observation is not None
        assert result.observation.task_id == "task_123"
        assert result.observation.title == "Buy groceries"
        assert result.observation.due == "2026-10-04"
        assert fake_transport.reads_count == 1
        assert fake_transport.writes_count == 0

    def test_read_task_not_found(
        self,
        read_adapter: GoogleTasksReadAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_read_contract(task_id="nonexistent_task")
        result = read_adapter.read_task(action)
        assert result.status == TaskReadStatus.NOT_FOUND
        assert result.observation is None
        assert fake_transport.reads_count == 1

    def test_read_deleted_task_returns_not_found(
        self,
        read_adapter: GoogleTasksReadAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="deleted_task",
            title="Archived",
            deleted=True,
        )
        action = _make_task_read_contract(task_id="deleted_task")
        result = read_adapter.read_task(action)
        assert result.status == TaskReadStatus.NOT_FOUND

    def test_wrong_task_list_parent_fails_before_provider_call(
        self,
        read_adapter: GoogleTasksReadAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_read_contract(task_list_id="rogue-task-list")
        with pytest.raises(TaskOutOfScopeError):
            read_adapter.read_task(action)
        assert fake_transport.reads_count == 0

    def test_missing_task_read_parent_fails_before_provider_call(
        self,
        read_adapter: GoogleTasksReadAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_read_contract(task_list_id=None)
        with pytest.raises(MissingParentContainerError):
            read_adapter.read_task(action)
        assert fake_transport.reads_count == 0

    def test_task_read_rejects_unexpected_approval_grant(
        self,
        read_adapter: GoogleTasksReadAdapter,
    ) -> None:
        action = _make_task_read_contract()
        now = datetime.now(UTC)
        grant = ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.READ_ONLY,
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=10),
        )
        with pytest.raises(UnexpectedApprovalGrantError):
            read_adapter.read_task(action, approval=grant)

    def test_wrong_action_type_or_system_fails(
        self,
        read_adapter: GoogleTasksReadAdapter,
    ) -> None:
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="ev_1",
                parent_id=DEMO_CALENDAR_ID,
            ),
            parameters={},
        )
        with pytest.raises(TaskTargetError):
            read_adapter.read_task(action)

    def test_read_task_timestamps_runtime_owned_not_forged_by_authority_at(
        self,
        read_adapter: GoogleTasksReadAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        fake_transport.seed_task(
            task_list_id=DEMO_TASK_LIST_ID,
            task_id="task_time_test",
            title="Timestamp test task",
        )
        action = _make_task_read_contract(task_id="task_time_test")
        historical_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = read_adapter.read_task(action, at=historical_at)
        assert result.status == TaskReadStatus.MATCH
        assert result.observation is not None
        # Observed timestamps must be runtime-owned and not forged by historical caller `at`
        assert result.observed_at > datetime(2026, 1, 1, tzinfo=UTC)
        assert result.observation.observed_at > datetime(2026, 1, 1, tzinfo=UTC)
        assert result.observed_at != historical_at
        assert result.observation.observed_at != historical_at

    def test_read_task_not_found_timestamp_runtime_owned(
        self,
        read_adapter: GoogleTasksReadAdapter,
    ) -> None:
        action = _make_task_read_contract(task_id="nonexistent_task")
        historical_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = read_adapter.read_task(action, at=historical_at)
        assert result.status == TaskReadStatus.NOT_FOUND
        assert result.observed_at > datetime(2026, 1, 1, tzinfo=UTC)
        assert result.observed_at != historical_at

    def test_read_task_provider_error_timestamp_runtime_owned(
        self,
        read_adapter: GoogleTasksReadAdapter,
    ) -> None:
        action = _make_task_read_contract(task_id="task_err")
        historical_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)

        with patch.object(
            read_adapter._transport, "get_task", side_effect=Exception("Network fail")
        ):
            result = read_adapter.read_task(action, at=historical_at)

        assert result.status == TaskReadStatus.PROVIDER_ERROR
        assert result.observed_at > datetime(2026, 1, 1, tzinfo=UTC)
        assert result.observed_at != historical_at


# ===========================================================================
# GoogleTasksCreateAdapter Tests
# ===========================================================================


class TestGoogleTasksCreateAdapter:
    def test_task_create_resource_id_must_equal_demo_task_list(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(task_list_id="rogue_list")
        with pytest.raises(TaskOutOfScopeError):
            create_adapter.create_task(action)
        assert fake_transport.writes_count == 0

    def test_task_create_parent_must_be_none(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(parent_id="unexpected_parent")
        with pytest.raises(UnexpectedParentContainerError):
            create_adapter.create_task(action)
        assert fake_transport.writes_count == 0

    def test_create_requires_canonical_title(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(parameters={"due": "2026-10-04"})
        with pytest.raises(MissingRequiredParameterError):
            create_adapter.create_task(action)
        assert fake_transport.writes_count == 0

    def test_create_rejects_unexpected_parameters(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(
            parameters={"title": "Valid title", "notes": "Hacked field"}
        )
        with pytest.raises(UnknownParameterError):
            create_adapter.create_task(action)
        assert fake_transport.writes_count == 0

    def test_create_rejects_unexpected_approval_grant(
        self,
        create_adapter: GoogleTasksCreateAdapter,
    ) -> None:
        action = _make_task_create_contract(parameters={"title": "Pack lunch"})
        now = datetime.now(UTC)
        grant = ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_AUTO,
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=10),
        )
        with pytest.raises(UnexpectedApprovalGrantError):
            create_adapter.create_task(action, approval=grant)

    def test_create_successful_single_write_attempt(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(
            parameters={"title": "Pack backpacks", "due": "2026-10-04"}
        )

        result = create_adapter.create_task(action)
        assert result.status == TaskCreateStatus.CREATED
        assert result.writes_performed == 1
        assert result.title == "Pack backpacks"
        assert result.due == "2026-10-04"
        assert result.task_id is not None
        assert fake_transport.writes_count == 1
        assert fake_transport.reads_count == 0

        # Only title and due reach provider body
        assert fake_transport.last_insert_body == {
            "title": "Pack backpacks",
            "due": "2026-10-04T00:00:00.000Z",
        }

    def test_create_without_due_reaches_provider_with_title_only(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(parameters={"title": "Prepare outfits"})

        result = create_adapter.create_task(action)
        assert result.status == TaskCreateStatus.CREATED
        assert result.writes_performed == 1
        assert result.due is None
        assert fake_transport.last_insert_body == {"title": "Prepare outfits"}

    def test_create_malformed_due_fails_closed_before_provider_write(
        self,
        create_adapter: GoogleTasksCreateAdapter,
        fake_transport: FakeGoogleTasksTransport,
    ) -> None:
        action = _make_task_create_contract(
            parameters={"title": "Check weather", "due": "invalid-date-format"}
        )
        with pytest.raises(TaskDueFormatError):
            create_adapter.create_task(action)
        assert fake_transport.writes_count == 0

    def test_create_task_created_at_runtime_owned_not_forged_by_authority_at(
        self,
        create_adapter: GoogleTasksCreateAdapter,
    ) -> None:
        action = _make_task_create_contract(parameters={"title": "Runtime time create task"})
        historical_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)

        result = create_adapter.create_task(action, at=historical_at)
        assert result.status == TaskCreateStatus.CREATED
        assert result.created_at > datetime(2026, 1, 1, tzinfo=UTC)
        assert result.created_at != historical_at

    def test_create_task_provider_error_timestamp_runtime_owned(
        self,
        create_adapter: GoogleTasksCreateAdapter,
    ) -> None:
        action = _make_task_create_contract(parameters={"title": "Error create task"})
        historical_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)

        with patch.object(
            create_adapter._transport, "insert_task", side_effect=Exception("Insert fail")
        ):
            result = create_adapter.create_task(action, at=historical_at)

        assert result.status == TaskCreateStatus.PROVIDER_ERROR
        assert result.created_at > datetime(2026, 1, 1, tzinfo=UTC)
        assert result.created_at != historical_at


# ===========================================================================
# Production GoogleApiClientTasksTransport Error Handling Tests
# ===========================================================================


class _MockHttpError(Exception):
    resp: Any


class TestGoogleApiClientTasksTransport:
    def test_transport_get_task_404_returns_none(self) -> None:
        mock_service = MagicMock()
        mock_execute = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_err = _MockHttpError("Not Found")
        mock_err.resp = mock_resp
        mock_execute.side_effect = mock_err
        mock_service.tasks().get.return_value.execute = mock_execute

        transport = GoogleApiClientTasksTransport(mock_service)
        assert transport.get_task("list_1", "task_1") is None

    def test_transport_get_task_401_maps_to_auth_error(self) -> None:
        mock_service = MagicMock()
        mock_execute = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_err = _MockHttpError("Unauthorized")
        mock_err.resp = mock_resp
        mock_execute.side_effect = mock_err
        mock_service.tasks().get.return_value.execute = mock_execute

        transport = GoogleApiClientTasksTransport(mock_service)
        with pytest.raises(TaskAuthenticationError):
            transport.get_task("list_1", "task_1")

    def test_transport_insert_task_429_maps_to_rate_limit(self) -> None:
        mock_service = MagicMock()
        mock_execute = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 429
        mock_err = _MockHttpError("Rate Limit Exceeded")
        mock_err.resp = mock_resp
        mock_execute.side_effect = mock_err
        mock_service.tasks().insert.return_value.execute = mock_execute

        transport = GoogleApiClientTasksTransport(mock_service)
        with pytest.raises(TaskRateLimitError):
            transport.insert_task("list_1", {"title": "Test"})


# ===========================================================================
# Hostile Privacy Sentinel Tests
# ===========================================================================


class TestPrivacySentinels:
    SECRET_TASK_LIST = "SECRET_TASK_LIST_ID_ALPHA_77"
    SECRET_TASK_ID = "SECRET_TASK_ID_BRAVO_88"
    SECRET_TITLE = "Extremely Private Personal Medical Task Title 99"
    SECRET_DUE = "2026-10-04"
    SECRET_TOKEN = "ya29.a0AfH6SMB_SECRET_OAUTH_TOKEN_VALUE"
    SECRET_URL = "https://tasks.googleapis.com/tasks/v1/lists/private_list/tasks/private_task"

    def test_repr_and_str_mask_all_sensitive_sentinels(self) -> None:
        obs = TaskObservation(
            task_id=self.SECRET_TASK_ID,
            task_list_id=self.SECRET_TASK_LIST,
            title=self.SECRET_TITLE,
            due=self.SECRET_DUE,
            status="needsAction",
            deleted=False,
            hidden=False,
            etag="etag123",
            observed_at=datetime.now(UTC),
        )

        for rep in (repr(obs), str(obs)):
            assert self.SECRET_TASK_LIST not in rep
            assert self.SECRET_TASK_ID not in rep
            assert self.SECRET_TITLE not in rep
            assert self.SECRET_DUE not in rep

        read_res = TaskReadResult(status=TaskReadStatus.MATCH, observation=obs)
        for rep in (repr(read_res), str(read_res)):
            assert self.SECRET_TASK_LIST not in rep
            assert self.SECRET_TASK_ID not in rep
            assert self.SECRET_TITLE not in rep
            assert self.SECRET_DUE not in rep

        create_res = TaskCreateResult(
            status=TaskCreateStatus.CREATED,
            task_id=self.SECRET_TASK_ID,
            task_list_id=self.SECRET_TASK_LIST,
            title=self.SECRET_TITLE,
            due=self.SECRET_DUE,
            writes_performed=1,
        )
        for rep in (repr(create_res), str(create_res)):
            assert self.SECRET_TASK_LIST not in rep
            assert self.SECRET_TASK_ID not in rep
            assert self.SECRET_TITLE not in rep
            assert self.SECRET_DUE not in rep

    def test_provider_error_sanitization_masks_sentinels(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_transport = MagicMock()
        mock_transport.get_task.side_effect = Exception(
            f"Failed calling {self.SECRET_URL} with "
            f"token {self.SECRET_TOKEN} for {self.SECRET_TASK_ID}"
        )

        scope = DemoResourceScope(
            calendar_id=DEMO_CALENDAR_ID,
            task_list_id=self.SECRET_TASK_LIST,
        )
        adapter = GoogleTasksReadAdapter(scope=scope, transport=mock_transport)

        action = _make_task_read_contract(
            task_list_id=self.SECRET_TASK_LIST,
            task_id=self.SECRET_TASK_ID,
        )

        with caplog.at_level(logging.WARNING):
            res = adapter.read_task(action)

        assert res.status == TaskReadStatus.PROVIDER_ERROR
        assert res.error_message is not None
        assert self.SECRET_TOKEN not in res.error_message
        assert self.SECRET_URL not in res.error_message
        assert self.SECRET_TASK_ID not in res.error_message
        assert self.SECRET_TASK_LIST not in res.error_message

        # Check logs as well
        log_text = caplog.text
        assert self.SECRET_TOKEN not in log_text
        assert self.SECRET_URL not in log_text
        assert self.SECRET_TASK_ID not in log_text
        assert self.SECRET_TASK_LIST not in log_text
