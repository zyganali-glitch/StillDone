"""Tests for Google Calendar Bounded Update Adapter with Idempotency (P-06.02).

Validates:
- Authority fail-closed: missing, invalid, expired, or mismatched
  ApprovalGrant causes zero provider write.
- Demo isolation fail-closed: wrong calendar ID causes zero provider write.
- Action validation fail-closed: unsupported parameters cause zero provider write.

- Read-before-write semantics: current event is read before any mutation attempt.
- Adapter-level idempotency strategy:
  - If requested state already matches current event state, zero provider write is performed.
  - Returns explicit NOOP_ALREADY_APPLIED status with writes_performed=0.
- Legitimate bounded update:
  - Updates only canonical summary, start_time, all_day.
  - Performs exactly one conditional write using currently observed ETag.
  - Sends sendUpdates='none' to avoid attendee notification side effects.
  - Preserves unrelated provider fields from the original event resource.
- Repeated identical invocation:
  - First call updates event (writes_performed=1).
  - Second identical call detects state already applied (writes_performed=0).
- ETag / Conditional modification:
  - If-Match is sent with exact ETag (never '*').
  - Stale ETag / 412 Precondition Failed produces CONFLICT result with zero blind overwrite.
- Truth boundaries:
  - CalendarUpdateResult has zero VERIFIED / READY attributes.
  - Zero mission state mutation occurs.
  - Zero live Google calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stilldone.action_policy import (
    UnknownParameterError,
    validate_action_contract,
)
from stilldone.adapters.calendar import (
    CalendarPreconditionFailedError,
    CalendarTargetError,
    CalendarTransportEvent,
    CalendarUpdateStatus,
    FakeGoogleCalendarTransport,
    GoogleApiClientCalendarTransport,
    GoogleCalendarUpdateAdapter,
    _is_time_equal,
)
from stilldone.authority_policy import (
    ApprovalExpiredError,
    ApprovalRequiredError,
)
from stilldone.demo_isolation import (
    CalendarOutOfScopeError,
    DemoResourceScope,
    MissingParentContainerError,
)
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    AuthorityClass,
)
from stilldone.domain.mission import MissionId

DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_TASKLIST_ID = "MDExMTI0ZGVtbw"
VALID_EVENT_ID = "evt_leave_for_school_001"
INITIAL_START = "2026-10-03T07:45:00+03:00"
INITIAL_END = "2026-10-03T08:15:00+03:00"
UPDATED_START = "2026-10-03T07:30:00+03:00"


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
        start_time=INITIAL_START,
        end_time=INITIAL_END,
        all_day=False,
        etag='"etag_initial_1"',
        extra_fields={
            "description": "Original description that must be preserved",
            "location": "Family Home",
            "transparency": "opaque",
        },
    )
    return transport


@pytest.fixture
def update_adapter(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarUpdateAdapter:
    return GoogleCalendarUpdateAdapter(scope=demo_scope, transport=fake_transport)


def _make_calendar_update_contract(
    calendar_id: str = DEMO_CALENDAR_ID,
    event_id: str = VALID_EVENT_ID,
    parameters: dict[str, str | bool] | None = None,
    system: str = "google_calendar",
    resource_kind: ResourceKind = ResourceKind.CALENDAR_EVENT,
) -> ActionContract:
    params = parameters if parameters is not None else {"start_time": UPDATED_START}
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system=system,
            resource_kind=resource_kind,
            resource_id=event_id,
            parent_id=calendar_id,
        ),
        parameters=params,
    )


def _make_valid_approval(
    action: ActionContract,
    valid_window_minutes: int = 60,
    issued_at: datetime | None = None,
) -> ApprovalGrant:
    now = issued_at or datetime.now(tz=UTC)
    return ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now,
        expires_at=now + timedelta(minutes=valid_window_minutes),
    )


# ===========================================================================
# 1. Authority Enforcement & Fail-Closed Behavior
# ===========================================================================


class TestAuthorityEnforcement:
    def test_missing_approval_fails_closed_zero_writes(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract()
        with pytest.raises(ApprovalRequiredError):
            update_adapter.update_event(action, approval=None)

        assert fake_transport.reads_count == 0
        assert fake_transport.writes_count == 0

    def test_expired_approval_fails_closed_zero_writes(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract()
        past = datetime.now(tz=UTC) - timedelta(hours=2)
        expired_approval = _make_valid_approval(action, valid_window_minutes=30, issued_at=past)

        with pytest.raises(ApprovalExpiredError):
            update_adapter.update_event(action, approval=expired_approval)

        assert fake_transport.reads_count == 0
        assert fake_transport.writes_count == 0

    def test_approval_bound_to_different_action_fails_closed(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action1 = _make_calendar_update_contract(parameters={"summary": "New Title 1"})
        action2 = _make_calendar_update_contract(parameters={"summary": "New Title 2"})
        approval_for_action1 = _make_valid_approval(action1)

        from stilldone.authority_policy import ApprovalBindingMismatchError

        with pytest.raises(ApprovalBindingMismatchError):
            update_adapter.update_event(action2, approval=approval_for_action1)

        assert fake_transport.reads_count == 0
        assert fake_transport.writes_count == 0


# ===========================================================================
# 2. Demo Scope & Action Validation
# ===========================================================================


class TestDemoScopeAndActionValidation:
    def test_wrong_calendar_scope_fails_closed_zero_writes(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(
            calendar_id="unrelated_cal@group.calendar.google.com"
        )
        approval = _make_valid_approval(action)

        with pytest.raises(CalendarOutOfScopeError):
            update_adapter.update_event(action, approval=approval)

        assert fake_transport.reads_count == 0
        assert fake_transport.writes_count == 0

    def test_missing_parent_id_fails_closed(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_UPDATE,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=VALID_EVENT_ID,
                parent_id=None,
            ),
            parameters={"start_time": UPDATED_START},
        )
        approval = _make_valid_approval(action)

        with pytest.raises(MissingParentContainerError):
            update_adapter.update_event(action, approval=approval)

        assert fake_transport.writes_count == 0

    def test_unsupported_parameter_fails_closed(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(parameters={"arbitrary_injected_payload": "hack"})
        with pytest.raises(UnknownParameterError):
            update_adapter.update_event(action)

        assert fake_transport.writes_count == 0


# ===========================================================================
# 3. Legitimate Bounded Update & Field Preservation
# ===========================================================================


class TestLegitimateBoundedUpdate:
    def test_successful_start_time_update(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(parameters={"start_time": UPDATED_START})
        approval = _make_valid_approval(action)

        result = update_adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.writes_performed == 1
        assert result.event_id == VALID_EVENT_ID
        assert result.observation is not None
        assert result.observation.start_time == UPDATED_START
        # Original duration was 30 mins (07:45 -> 08:15). New start 07:30 -> new end 08:00
        assert "08:00:00" in (result.observation.end_time or "")

        # Provider interaction assertions
        assert fake_transport.reads_count == 1
        assert fake_transport.writes_count == 1
        assert fake_transport.last_if_match == '"etag_initial_1"'
        assert fake_transport.last_send_updates == "none"

        # Verify preserved fields in transport
        updated_event = fake_transport.get_event(DEMO_CALENDAR_ID, VALID_EVENT_ID)
        assert updated_event is not None
        assert updated_event.summary == "Leave for school"
        assert (
            updated_event.raw_resource["description"]
            == "Original description that must be preserved"
        )
        assert updated_event.raw_resource["location"] == "Family Home"

    def test_successful_summary_update(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(
            parameters={"summary": "Leave for School (Updated)"}
        )
        approval = _make_valid_approval(action)

        result = update_adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.writes_performed == 1
        assert result.observation is not None
        assert result.observation.summary == "Leave for School (Updated)"
        assert result.observation.start_time == INITIAL_START
        assert fake_transport.writes_count == 1


# ===========================================================================
# 4. Adapter-Level Idempotency Strategy
# ===========================================================================


class TestIdempotencyStrategy:
    def test_already_applied_state_performs_zero_writes(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        # Event is already at INITIAL_START
        action = _make_calendar_update_contract(parameters={"start_time": INITIAL_START})
        approval = _make_valid_approval(action)

        result = update_adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.NOOP_ALREADY_APPLIED
        assert result.writes_performed == 0
        assert result.observation is not None
        assert result.observation.start_time == INITIAL_START
        assert fake_transport.reads_count == 1
        assert fake_transport.writes_count == 0

    def test_repeated_identical_invocation_performs_zero_second_write(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(parameters={"start_time": UPDATED_START})
        approval = _make_valid_approval(action)

        # First call: legitimate change from 07:45 to 07:30
        res1 = update_adapter.update_event(action, approval=approval)
        assert res1.status == CalendarUpdateStatus.UPDATED
        assert res1.writes_performed == 1
        assert fake_transport.writes_count == 1

        # Second call: repeated identical invocation with same action/approval
        res2 = update_adapter.update_event(action, approval=approval)
        assert res2.status == CalendarUpdateStatus.NOOP_ALREADY_APPLIED
        assert res2.writes_performed == 0
        # Exactly one total write across both calls
        assert fake_transport.writes_count == 1


# ===========================================================================
# 5. Conditional Mutation, ETag & 412 Conflict Handling
# ===========================================================================


class TestConditionalMutationAndConflict:
    def test_etag_mismatch_produces_conflict_zero_overwrite(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(parameters={"summary": "New Title"})
        approval = _make_valid_approval(action)

        # External change occurs between read and write
        # Mutate the event directly in the fake transport with a new ETag
        fake_transport._events[(DEMO_CALENDAR_ID, VALID_EVENT_ID)]["etag"] = (
            '"concurrent_external_change"'
        )

        # In order to simulate conflict at write time:
        # Wrap transport get_event to return stale ETag
        orig_get_event = fake_transport.get_event

        def stale_get_event(calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
            evt = orig_get_event(calendar_id, event_id)

            if evt:
                return FakeGoogleCalendarTransport._to_transport_event(
                    {
                        **evt.raw_resource,
                        "etag": '"stale_etag_old"',
                    }
                )
            return None

        fake_transport.get_event = stale_get_event  # type: ignore[method-assign]

        result = update_adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.CONFLICT
        assert result.writes_performed == 0
        assert "ETag mismatch" in (result.error_message or "")

    def test_nonexistent_event_returns_not_found(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_contract(event_id="nonexistent_event_id")
        approval = _make_valid_approval(action)

        result = update_adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.NOT_FOUND
        assert result.writes_performed == 0
        assert fake_transport.writes_count == 0


# ===========================================================================
# 6. Privacy & Truth Boundaries
# ===========================================================================


class TestUpdatePrivacyAndTruthBoundaries:
    def test_update_result_repr_masks_identifiers(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
    ) -> None:
        action = _make_calendar_update_contract(parameters={"summary": "New Title"})
        approval = _make_valid_approval(action)
        result = update_adapter.update_event(action, approval=approval)

        res_repr = repr(result)
        res_str = str(result)

        assert VALID_EVENT_ID not in res_repr
        assert VALID_EVENT_ID not in res_str

    def test_no_verified_or_ready_attributes_on_update_result(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
    ) -> None:
        action = _make_calendar_update_contract(parameters={"summary": "New Title"})
        approval = _make_valid_approval(action)
        result = update_adapter.update_event(action, approval=approval)

        attrs = dir(result)
        for forbidden in ("verified", "ready", "is_verified", "is_ready"):
            assert forbidden not in attrs, (
                f"Forbidden attribute {forbidden} found on CalendarUpdateResult"
            )


# ===========================================================================
# 7. Production GoogleApiClient Transport Contract
# ===========================================================================


class _StrictCalendarRequestStub:
    """Strict request stub mimicking googleapiclient.http.HttpRequest.

    Records headers and execution calls; rejects missing or invalid preconditions.
    """

    def __init__(self, response_payload: dict[str, Any], status_code: int = 200) -> None:
        self.headers: dict[str, str] = {}
        self.execute_count: int = 0
        self.headers_at_execute: dict[str, str] = {}
        self._response_payload = response_payload
        self._status_code = status_code

    def execute(self) -> dict[str, Any]:
        self.execute_count += 1
        self.headers_at_execute = dict(self.headers)
        if self._status_code == 412:
            exc = Exception("Precondition Failed")
            resp_mock = MagicMock()
            resp_mock.status = 412
            exc.resp = resp_mock  # type: ignore[attr-defined]
            raise exc
        return self._response_payload


class _StrictEventsResourceStub:
    """Strict resource stub mimicking Google Calendar Python client events() resource.

    Rejects unsupported keyword arguments (like headers={...}) to events().update(...).
    """

    def __init__(self, request_stub: _StrictCalendarRequestStub) -> None:
        self.request_stub = request_stub
        self.received_kwargs: dict[str, Any] = {}

    def update(self, **kwargs: Any) -> _StrictCalendarRequestStub:
        # Generated google-api-python-client events.update does NOT accept headers as a kwarg!
        allowed_params = {
            "calendarId",
            "eventId",
            "body",
            "sendUpdates",
            "alwaysIncludeEmail",
            "maxAttendees",
            "supportsAttachments",
        }
        for k in kwargs:
            if k not in allowed_params:
                raise TypeError(
                    f"events().update got an unexpected keyword argument '{k}'. "
                    f"Passing '{k}' directly to Google API client method is unsupported."
                )
        self.received_kwargs = kwargs
        return self.request_stub


class _StrictServiceStub:
    def __init__(self, events_stub: _StrictEventsResourceStub) -> None:
        self._events_stub = events_stub

    def events(self) -> _StrictEventsResourceStub:
        return self._events_stub


class TestGoogleApiClientTransportContract:
    def test_client_transport_attaches_exact_etag_as_if_match_header(self) -> None:
        sample_response = {
            "id": VALID_EVENT_ID,
            "etag": '"etag_updated_strict"',
            "summary": "Updated Title",
            "start": {"dateTime": INITIAL_START},
            "end": {"dateTime": INITIAL_END},
            "status": "confirmed",
        }
        request_stub = _StrictCalendarRequestStub(sample_response)
        events_stub = _StrictEventsResourceStub(request_stub)
        service_stub = _StrictServiceStub(events_stub)
        transport = GoogleApiClientCalendarTransport(service=service_stub)

        payload = {"summary": "Updated Title"}
        result_event = transport.update_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id=VALID_EVENT_ID,
            payload=payload,
            if_match='"etag_strict_123"',
            send_updates="none",
        )

        # 1. No unsupported headers= kwarg was passed to events().update
        assert "headers" not in events_stub.received_kwargs
        assert events_stub.received_kwargs["calendarId"] == DEMO_CALENDAR_ID
        assert events_stub.received_kwargs["eventId"] == VALID_EVENT_ID
        assert events_stub.received_kwargs["body"] == payload
        assert events_stub.received_kwargs["sendUpdates"] == "none"

        # 2. Exact observed ETag was attached to req.headers before execute
        assert request_stub.headers_at_execute.get("If-Match") == '"etag_strict_123"'
        assert request_stub.headers_at_execute.get("If-Match") != "*"

        # 3. Request executed exactly once
        assert request_stub.execute_count == 1

        # 4. Result parsed correctly
        assert result_event.id == VALID_EVENT_ID
        assert result_event.etag == '"etag_updated_strict"'

    def test_client_transport_rejects_wildcard_if_match(self) -> None:
        request_stub = _StrictCalendarRequestStub({})
        events_stub = _StrictEventsResourceStub(request_stub)
        service_stub = _StrictServiceStub(events_stub)
        transport = GoogleApiClientCalendarTransport(service=service_stub)

        with pytest.raises(
            CalendarTargetError, match="Unconditional overwrite.*strictly forbidden"
        ):
            transport.update_event(
                calendar_id=DEMO_CALENDAR_ID,
                event_id=VALID_EVENT_ID,
                payload={"summary": "Title"},
                if_match="*",
            )

        assert request_stub.execute_count == 0

    def test_client_transport_rejects_empty_if_match(self) -> None:
        request_stub = _StrictCalendarRequestStub({})
        events_stub = _StrictEventsResourceStub(request_stub)
        service_stub = _StrictServiceStub(events_stub)
        transport = GoogleApiClientCalendarTransport(service=service_stub)

        with pytest.raises(
            CalendarTargetError, match="Unconditional overwrite.*strictly forbidden"
        ):
            transport.update_event(
                calendar_id=DEMO_CALENDAR_ID,
                event_id=VALID_EVENT_ID,
                payload={"summary": "Title"},
                if_match="",
            )

        assert request_stub.execute_count == 0

    def test_client_transport_maps_412_to_precondition_failed_error(self) -> None:
        request_stub = _StrictCalendarRequestStub({}, status_code=412)
        events_stub = _StrictEventsResourceStub(request_stub)
        service_stub = _StrictServiceStub(events_stub)
        transport = GoogleApiClientCalendarTransport(service=service_stub)

        with pytest.raises(CalendarPreconditionFailedError) as exc_info:
            transport.update_event(
                calendar_id=DEMO_CALENDAR_ID,
                event_id=VALID_EVENT_ID,
                payload={"summary": "Title"},
                if_match='"stale_etag"',
            )

        assert exc_info.value.status_code == 412
        assert request_stub.execute_count == 1
        assert request_stub.headers_at_execute.get("If-Match") == '"stale_etag"'


# ===========================================================================
# 8. All-Day and Timed Semantics
# ===========================================================================


class TestAllDayAndTimedSemantics:
    def test_timed_to_oneday_allday_exclusive_end(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        # Original event is timed (INITIAL_START)
        action = _make_calendar_update_contract(
            parameters={"all_day": True, "start_time": "2026-10-05"}
        )
        approval = _make_valid_approval(action)

        result = update_adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.writes_performed == 1
        assert result.observation is not None
        assert result.observation.all_day is True
        assert result.observation.start_time == "2026-10-05"
        # Google Calendar requires exclusive end date (+1 day for single-day event)
        assert result.observation.end_time == "2026-10-06"

        # Check payload hygiene on stored raw resource
        stored = fake_transport._events[(DEMO_CALENDAR_ID, VALID_EVENT_ID)]
        assert "date" in stored["start"]
        assert "dateTime" not in stored["start"]
        assert stored["start"]["date"] == "2026-10-05"
        assert "date" in stored["end"]
        assert "dateTime" not in stored["end"]
        assert stored["end"]["date"] == "2026-10-06"

    def test_multiday_allday_move_preserves_span(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        transport = FakeGoogleCalendarTransport()
        # Seed a 4-day all-day event: 2026-10-10 to 2026-10-14 (span: 4 days)
        transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="multiday_evt_1",
            summary="Multi-day camp",
            start_time="2026-10-10",
            end_time="2026-10-14",
            all_day=True,
            etag='"etag_multi_1"',
        )
        adapter = GoogleCalendarUpdateAdapter(scope=demo_scope, transport=transport)

        # Move starting date to 2026-10-20
        action = _make_calendar_update_contract(
            event_id="multiday_evt_1",
            parameters={"start_time": "2026-10-20"},
        )
        approval = _make_valid_approval(action)

        result = adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.writes_performed == 1
        assert result.observation is not None
        assert result.observation.start_time == "2026-10-20"
        # 4-day span preserved: 2026-10-20 + 4 days = 2026-10-24
        assert result.observation.end_time == "2026-10-24"

    def test_zero_length_allday_rejected_fails_closed(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        transport = FakeGoogleCalendarTransport()
        transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="zero_len_evt",
            summary="Zero length event",
            start_time="2026-10-05",
            end_time="2026-10-05",
            all_day=True,
            etag='"etag_zero_1"',
        )
        adapter = GoogleCalendarUpdateAdapter(scope=demo_scope, transport=transport)

        # 1. Prevention: When moving an existing event that had zero length in provider,
        # adapter must prevent zero-length and enforce end.date > start.date
        action = _make_calendar_update_contract(
            event_id="zero_len_evt",
            parameters={"start_time": "2026-10-10"},
        )
        approval = _make_valid_approval(action)
        result = adapter.update_event(action, approval=approval)
        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.observation is not None
        assert result.observation.start_time == "2026-10-10"
        assert result.observation.end_time == "2026-10-11"
        assert result.observation.end_time > result.observation.start_time

        # 2. Rejection: If parameters specify end_time <= start_time,
        # fail-closed with CalendarTargetError before any provider write
        real_action = _make_calendar_update_contract(
            event_id="zero_len_evt",
            parameters={"all_day": True, "start_time": "2026-10-15"},
        )
        approval_grant = _make_valid_approval(real_action)
        validated = validate_action_contract(real_action)

        with patch("stilldone.adapters.calendar.evaluate_authority") as mock_auth:
            mock_auth.return_value.raise_for_status.return_value = None
            with patch.object(
                NormalizedParameters,
                "to_dict",
                return_value={
                    "all_day": True,
                    "start_time": "2026-10-15",
                    "end_time": "2026-10-15",
                },
            ):
                with pytest.raises(
                    CalendarTargetError, match="zero-length all-day events are forbidden"
                ):
                    adapter.update_event(validated, approval=approval_grant)

    def test_allday_to_timed_valid_rfc3339_with_timezone_and_duration(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        transport = FakeGoogleCalendarTransport()
        transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="allday_to_timed_evt",
            summary="All day planning",
            start_time="2026-10-05",
            end_time="2026-10-06",
            all_day=True,
            etag='"etag_plan_1"',
        )
        adapter = GoogleCalendarUpdateAdapter(scope=demo_scope, transport=transport)

        # Transition to timed with valid RFC3339 datetime
        action = _make_calendar_update_contract(
            event_id="allday_to_timed_evt",
            parameters={
                "all_day": False,
                "start_time": "2026-10-05T09:00:00+03:00",
            },
        )
        approval = _make_valid_approval(action)

        result = adapter.update_event(action, approval=approval)

        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.writes_performed == 1
        assert result.observation is not None
        assert result.observation.all_day is False
        assert result.observation.start_time == "2026-10-05T09:00:00+03:00"
        # Deterministic default duration of 30 minutes applied
        assert result.observation.end_time == "2026-10-05T09:30:00+03:00"

        # Check payload hygiene
        stored = transport._events[(DEMO_CALENDAR_ID, "allday_to_timed_evt")]
        assert "dateTime" in stored["start"]
        assert "date" not in stored["start"]
        assert stored["start"]["dateTime"] == "2026-10-05T09:00:00+03:00"
        assert "dateTime" in stored["end"]
        assert "date" not in stored["end"]
        assert stored["end"]["dateTime"] == "2026-10-05T09:30:00+03:00"

    def test_allday_to_timed_bare_date_fails_closed(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        transport = FakeGoogleCalendarTransport()
        transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="allday_bare_evt",
            summary="All day planning",
            start_time="2026-10-05",
            end_time="2026-10-06",
            all_day=True,
            etag='"etag_plan_2"',
        )
        adapter = GoogleCalendarUpdateAdapter(scope=demo_scope, transport=transport)

        # Transition to timed but passing bare date without time component
        action = _make_calendar_update_contract(
            event_id="allday_bare_evt",
            parameters={
                "all_day": False,
                "start_time": "2026-10-05",
            },
        )
        approval = _make_valid_approval(action)

        with pytest.raises(CalendarTargetError, match="must include time component and timezone"):
            adapter.update_event(action, approval=approval)

        assert transport.writes_count == 0

    def test_idempotency_does_not_conflate_bare_date_with_midnight_utc_datetime(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        transport = FakeGoogleCalendarTransport()
        transport.seed_event(
            calendar_id=DEMO_CALENDAR_ID,
            event_id="date_vs_dt_evt",
            summary="Planning day",
            start_time="2026-10-05",
            end_time="2026-10-06",
            all_day=True,
            etag='"etag_dvdt_1"',
        )
        adapter = GoogleCalendarUpdateAdapter(scope=demo_scope, transport=transport)

        # Transition to timed event at midnight UTC on the same date
        action = _make_calendar_update_contract(
            event_id="date_vs_dt_evt",
            parameters={
                "all_day": False,
                "start_time": "2026-10-05T00:00:00Z",
            },
        )
        approval = _make_valid_approval(action)

        result = adapter.update_event(action, approval=approval)

        # 1. First call: must NOT be detected as NOOP_ALREADY_APPLIED!
        assert result.status == CalendarUpdateStatus.UPDATED
        assert result.writes_performed == 1
        assert result.observation is not None
        assert result.observation.all_day is False
        assert _is_time_equal(result.observation.start_time, "2026-10-05T00:00:00Z")
        assert result.observation.start_time != "2026-10-05"
        assert transport.writes_count == 1

        # 2. Second call: once in timed state, identical request IS detected as NOOP
        second_result = adapter.update_event(action, approval=approval)
        assert second_result.status == CalendarUpdateStatus.NOOP_ALREADY_APPLIED
        assert second_result.writes_performed == 0
        assert transport.writes_count == 1
