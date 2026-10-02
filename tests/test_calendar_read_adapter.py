"""Tests for Google Calendar Read Adapter (P-06.01).

Validates:
- Exact dedicated-demo-calendar targeting (target.parent_id == demo calendar ID).
- Rejection of out-of-scope calendar IDs via fail-closed DemoIsolation.
- Rejection of 'primary' and 'default' calendar IDs (no silent fallback).
- Exact event identity preservation (no search/fuzzy matching).
- Event-not-found and cancelled event mapped to NOT_FOUND.
- Provider errors gracefully mapped to PROVIDER_ERROR without crashing.
- Masked repr and string representations (sensitive external IDs not leaked).
- Zero mission state mutation and zero READY/VERIFIED promotions.
- Pluggable FakeGoogleCalendarTransport and GoogleApiClientCalendarTransport behavior.
- Strictly zero network calls required in CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import (
    ActionTargetCompatibilityError,
    UnknownParameterError,
)
from stilldone.adapters.calendar import (
    CalendarApiError,
    CalendarAuthenticationError,
    CalendarRateLimitError,
    CalendarReadStatus,
    CalendarScopeError,
    CalendarTargetError,
    FakeGoogleCalendarTransport,
    GoogleApiClientCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.demo_isolation import (
    CalendarOutOfScopeError,
    DemoResourceScope,
    MissingParentContainerError,
)
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId

DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_TASKLIST_ID = "MDExMTI0ZGVtbw"
VALID_EVENT_ID = "evt_leave_for_school_001"


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id=DEMO_TASKLIST_ID,
    )


@pytest.fixture
def fake_transport() -> FakeGoogleCalendarTransport:
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=VALID_EVENT_ID,
        summary="Leave for school",
        start_time="2026-10-03T07:45:00+03:00",
        end_time="2026-10-03T08:15:00+03:00",
        all_day=False,
        etag='"etag_version_1"',
    )
    return transport


@pytest.fixture
def read_adapter(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarReadAdapter:
    return GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)


def _make_calendar_read_contract(
    calendar_id: str = DEMO_CALENDAR_ID,
    event_id: str = VALID_EVENT_ID,
    parameters: dict[str, str] | None = None,
    system: str = "google_calendar",
    resource_kind: ResourceKind = ResourceKind.CALENDAR_EVENT,
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system=system,
            resource_kind=resource_kind,
            resource_id=event_id,
            parent_id=calendar_id,
        ),
        parameters=parameters or {},
    )


# ===========================================================================
# 1. Exact Dedicated Demo Calendar Targeting & Scoping
# ===========================================================================


class TestDemoCalendarScoping:
    def test_successful_read_against_exact_demo_calendar(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_read_contract()
        result = read_adapter.read_event(action)

        assert result.status == CalendarReadStatus.SUCCESS
        assert result.event_id == VALID_EVENT_ID
        assert result.observation is not None
        assert result.observation.summary == "Leave for school"
        assert result.observation.start_time == "2026-10-03T07:45:00+03:00"
        assert result.observation.end_time == "2026-10-03T08:15:00+03:00"
        assert not result.observation.all_day
        assert result.observation.etag == '"etag_version_1"'
        assert result.observation.status == "confirmed"
        assert fake_transport.reads_count == 1

    def test_out_of_scope_calendar_id_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_read_contract(
            calendar_id="other_calendar@group.calendar.google.com"
        )
        with pytest.raises(CalendarOutOfScopeError):
            read_adapter.read_event(action)
        assert fake_transport.reads_count == 0

    def test_missing_parent_id_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=VALID_EVENT_ID,
                parent_id=None,
            ),
            parameters={},
        )
        with pytest.raises(MissingParentContainerError):
            read_adapter.read_event(action)
        assert fake_transport.reads_count == 0

    @pytest.mark.parametrize("forbidden_id", ["primary", "PRIMARY", "default", "Default"])
    def test_adapter_rejects_primary_and_default_calendar_scope(
        self,
        forbidden_id: str,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        scope = DemoResourceScope(calendar_id=forbidden_id, task_list_id=DEMO_TASKLIST_ID)
        with pytest.raises(CalendarScopeError, match="Dedicated demo calendar required"):
            GoogleCalendarReadAdapter(scope=scope, transport=fake_transport)

    def test_adapter_rejects_primary_in_action_target(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_read_contract(calendar_id="primary")
        with pytest.raises(CalendarOutOfScopeError):
            read_adapter.read_event(action)
        assert fake_transport.reads_count == 0


# ===========================================================================
# 2. Exact Event Identity & Target Validation
# ===========================================================================


class TestEventIdentityAndValidation:
    def test_exact_event_identity_required(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_read_contract(event_id="different_event_id")
        result = read_adapter.read_event(action)

        assert result.status == CalendarReadStatus.NOT_FOUND
        assert result.event_id == "different_event_id"
        assert result.observation is None
        assert fake_transport.reads_count == 1

    def test_empty_resource_id_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        with pytest.raises(ValueError, match="resource_id must be a non-empty string"):
            _make_calendar_read_contract(event_id="")

    def test_wrong_action_type_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.TASK_READ,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="task1",
                parent_id=DEMO_TASKLIST_ID,
            ),
            parameters={},
        )
        with pytest.raises(CalendarTargetError, match="GoogleCalendarReadAdapter handles"):
            read_adapter.read_event(action)

    def test_wrong_system_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = _make_calendar_read_contract(system="microsoft_calendar")
        with pytest.raises(ActionTargetCompatibilityError):
            read_adapter.read_event(action)

    def test_wrong_resource_kind_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = _make_calendar_read_contract(resource_kind=ResourceKind.TASK)
        with pytest.raises(ActionTargetCompatibilityError):
            read_adapter.read_event(action)

    def test_read_action_with_parameters_rejected(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = _make_calendar_read_contract(parameters={"unexpected": "value"})
        with pytest.raises(UnknownParameterError):
            read_adapter.read_event(action)


# ===========================================================================
# 3. Read Semantics: Event Status, Not Found, Cancelled
# ===========================================================================


class TestReadSemantics:
    def test_all_day_event_normalized_correctly(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        fake_transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="all_day_001",
            summary="Spring Vacation",
            start_time="2026-10-04",
            end_time="2026-10-05",
            all_day=True,
        )
        action = _make_calendar_read_contract(event_id="all_day_001")
        result = read_adapter.read_event(action)

        assert result.status == CalendarReadStatus.SUCCESS
        assert result.observation is not None
        assert result.observation.all_day is True
        assert result.observation.start_time == "2026-10-04"
        assert result.observation.end_time == "2026-10-05"

    def test_cancelled_event_returns_not_found(
        self,
        read_adapter: GoogleCalendarReadAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        fake_transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="cancelled_001",
            summary="Cancelled Meeting",
            start_time="2026-10-03T10:00:00Z",
            status="cancelled",
        )
        action = _make_calendar_read_contract(event_id="cancelled_001")
        result = read_adapter.read_event(action)

        assert result.status == CalendarReadStatus.NOT_FOUND
        assert result.observation is None

    def test_provider_error_mapped_to_provider_error_status(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        broken_transport = MagicMock()
        broken_transport.get_event.side_effect = CalendarApiError("Google Calendar API 503")
        adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=broken_transport)

        action = _make_calendar_read_contract()
        result = adapter.read_event(action)

        assert result.status == CalendarReadStatus.PROVIDER_ERROR
        assert result.error_message is not None
        assert "503" in result.error_message
        assert result.observation is None


# ===========================================================================
# 4. Privacy, Sanitization & Truth Boundaries
# ===========================================================================


class TestPrivacyAndTruthBoundaries:
    def test_calendar_observation_repr_masks_identifiers(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = _make_calendar_read_contract()
        result = read_adapter.read_event(action)
        assert result.observation is not None

        obs_repr = repr(result.observation)
        obs_str = str(result.observation)

        assert DEMO_CALENDAR_ID not in obs_repr
        assert VALID_EVENT_ID not in obs_repr
        assert DEMO_CALENDAR_ID not in obs_str
        assert VALID_EVENT_ID not in obs_str

    def test_calendar_read_result_repr_masks_identifiers(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = _make_calendar_read_contract()
        result = read_adapter.read_event(action)

        res_repr = repr(result)
        assert VALID_EVENT_ID not in res_repr

    def test_no_verified_or_ready_attributes_on_observation_or_result(
        self,
        read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        action = _make_calendar_read_contract()
        result = read_adapter.read_event(action)
        assert result.observation is not None

        for obj in (result, result.observation):
            attrs = dir(obj)
            for forbidden in ("verified", "ready", "is_verified", "is_ready"):
                assert forbidden not in attrs, (
                    f"Forbidden attribute {forbidden} found on {type(obj)}"
                )


# ===========================================================================
# 5. Pluggable GoogleApiClientCalendarTransport Coverage
# ===========================================================================


class _HttpErrorLike(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.resp = MagicMock()
        self.resp.status = status


class TestGoogleApiClientTransport:
    def test_google_api_client_transport_get_event_success(self) -> None:
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_get = MagicMock()
        mock_service.events.return_value = mock_events
        mock_events.get.return_value = mock_get
        mock_get.execute.return_value = {
            "id": "mock_evt_1",
            "summary": "Mock Event",
            "etag": '"etag_mock"',
            "status": "confirmed",
            "start": {"dateTime": "2026-10-03T07:45:00Z"},
            "end": {"dateTime": "2026-10-03T08:15:00Z"},
        }

        transport = GoogleApiClientCalendarTransport(mock_service)
        event = transport.get_event("cal_1", "mock_evt_1")

        assert event is not None
        assert event.id == "mock_evt_1"
        assert event.summary == "Mock Event"
        assert event.etag == '"etag_mock"'
        assert event.start_time == "2026-10-03T07:45:00Z"

    def test_google_api_client_transport_handles_404(self) -> None:
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_get = MagicMock()
        mock_service.events.return_value = mock_events
        mock_events.get.return_value = mock_get

        err = _HttpErrorLike("Not found", status=404)
        mock_get.execute.side_effect = err

        transport = GoogleApiClientCalendarTransport(mock_service)
        event = transport.get_event("cal_1", "missing_evt")
        assert event is None

    def test_google_api_client_transport_handles_401_auth_error(self) -> None:
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_get = MagicMock()
        mock_service.events.return_value = mock_events
        mock_events.get.return_value = mock_get

        err = _HttpErrorLike("Unauthorized", status=401)
        mock_get.execute.side_effect = err

        transport = GoogleApiClientCalendarTransport(mock_service)
        with pytest.raises(CalendarAuthenticationError):
            transport.get_event("cal_1", "evt_1")

    def test_google_api_client_transport_handles_429_rate_limit(self) -> None:
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_get = MagicMock()
        mock_service.events.return_value = mock_events
        mock_events.get.return_value = mock_get

        err = _HttpErrorLike("Rate limit exceeded", status=429)
        mock_get.execute.side_effect = err

        transport = GoogleApiClientCalendarTransport(mock_service)
        with pytest.raises(CalendarRateLimitError):
            transport.get_event("cal_1", "evt_1")
