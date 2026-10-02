"""Google Calendar service adapter for StillDone.

Provides bounded, fail-closed integration with Google Calendar API v3:
- Enforces dedicated disposable demo-resource scoping (DemoResourceScope).
- Reuses P-04 action validation (ValidatedActionContract) and authority policy.
- Strictly forbids 'primary', default, or fuzzy-matched calendar substitution.
- Exact event identity required; summary matching as identity is strictly rejected.
- Pluggable transport boundary (CalendarTransport Protocol) supporting official
  Google API client or deterministic in-memory fakes.
- Minimizes persisted data; strips unrelated attendee/personal information.
- Provider success does NOT imply VERIFIED or READY.
- Zero secrets, tokens, or external IDs leaked into str/repr/logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from stilldone.action_policy import (
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.demo_isolation import (
    DemoIsolationError,
    DemoResourceScope,
    verify_demo_resource_isolation,
)
from stilldone.domain.action import ActionContract, ActionType, ResourceKind

logger = logging.getLogger(__name__)

# ===========================================================================
# Canonical Constants
# ===========================================================================

CANONICAL_CALENDAR_SYSTEM = "google_calendar"
CANONICAL_CALENDAR_RESOURCE_KIND = ResourceKind.CALENDAR_EVENT
FORBIDDEN_CALENDAR_IDS = frozenset({"primary", "default"})

# ===========================================================================
# Adapter Exception Hierarchy
# ===========================================================================


class CalendarAdapterError(Exception):
    """Base exception for all Calendar adapter operations."""


class CalendarScopeError(CalendarAdapterError, ValueError):
    """Raised when calendar scope configuration violates StillDone isolation rules."""


class CalendarTargetError(CalendarAdapterError, ValueError):
    """Raised when an action target identity or parameters violate Calendar requirements."""


class CalendarTransportError(CalendarAdapterError):
    """Base exception for transport/network/API failures communicating with Google Calendar."""


class CalendarEventNotFoundError(CalendarTransportError):
    """Raised when the requested event does not exist on the specified calendar."""


class CalendarPreconditionFailedError(CalendarTransportError):
    """Raised when an ETag mismatch or HTTP 412 precondition check fails."""


class CalendarAuthenticationError(CalendarTransportError):
    """Raised when credentials or OAuth tokens are rejected by Google APIs."""


class CalendarRateLimitError(CalendarTransportError):
    """Raised when Google Calendar rate limits (HTTP 429) are encountered."""


class CalendarApiError(CalendarTransportError):
    """Raised when Google Calendar API returns an unhandled error response."""


# ===========================================================================
# Transport Protocol & Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class CalendarTransportEvent:
    """Raw provider event representation observed at the transport layer."""

    id: str
    etag: str | None
    summary: str
    start_time: str
    end_time: str | None
    all_day: bool
    status: str = "confirmed"
    raw_resource: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"CalendarTransportEvent(id='***', summary='{self.summary}', "
            f"start_time='{self.start_time}', all_day={self.all_day}, status='{self.status}')"
        )

    def __str__(self) -> str:
        return self.__repr__()


@runtime_checkable
class CalendarTransport(Protocol):
    """Protocol for Google Calendar API transport operations."""

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        """Fetch an event by calendar ID and event ID.

        Returns CalendarTransportEvent if found and active, None if not found or cancelled.
        """
        ...

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        if_match: str,
        send_updates: str = "none",
    ) -> CalendarTransportEvent:
        """Update an event resource conditionally using If-Match ETag."""
        ...


# ===========================================================================
# Fake Transport for Deterministic Testing & CI
# ===========================================================================


class FakeGoogleCalendarTransport:
    """In-memory fake implementing CalendarTransport for deterministic CI testing.

    Faithfully emulates Google Calendar API v3 behaviors:
    - 404 when event is absent or has status 'cancelled'.
    - 412 Precondition Failed when If-Match does not match the current ETag.
    - ETag generation and update on modification.
    - Preserves existing event fields across full resource updates.
    - Tracks call counts, last headers, and parameters for test assertion.
    """

    def __init__(self) -> None:
        # Key: (calendar_id, event_id) -> raw dict
        self._events: dict[tuple[str, str], dict[str, Any]] = {}
        self.reads_count: int = 0
        self.writes_count: int = 0
        self.last_if_match: str | None = None
        self.last_send_updates: str | None = None
        self._etag_counter: int = 1000

    def seed_event(
        self,
        calendar_id: str,
        event_id: str,
        summary: str,
        start_time: str,
        *,
        all_day: bool = False,
        end_time: str | None = None,
        etag: str | None = None,
        status: str = "confirmed",
        extra_fields: dict[str, Any] | None = None,
    ) -> CalendarTransportEvent:
        """Seed an event in the fake store for test setups."""
        self._etag_counter += 1
        assigned_etag = etag or f'"{self._etag_counter}"'

        raw: dict[str, Any] = {
            "kind": "calendar#event",
            "id": event_id,
            "etag": assigned_etag,
            "status": status,
            "summary": summary,
        }
        if all_day:
            raw["start"] = {"date": start_time}
            raw["end"] = {"date": end_time or start_time}
        else:
            raw["start"] = {"dateTime": start_time}
            raw["end"] = {"dateTime": end_time or start_time}

        if extra_fields:
            for k, v in extra_fields.items():
                if k not in raw:
                    raw[k] = v

        self._events[(calendar_id, event_id)] = raw
        return self._to_transport_event(raw)

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        """Emulate GET /calendars/{calendarId}/events/{eventId}."""
        self.reads_count += 1
        event = self._events.get((calendar_id, event_id))
        if event is None:
            return None
        if event.get("status") == "cancelled":
            return None
        return self._to_transport_event(event)

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        if_match: str,
        send_updates: str = "none",
    ) -> CalendarTransportEvent:
        """Emulate PUT /calendars/{calendarId}/events/{eventId} with If-Match."""
        self.writes_count += 1
        self.last_if_match = if_match
        self.last_send_updates = send_updates

        key = (calendar_id, event_id)
        existing = self._events.get(key)
        if existing is None or existing.get("status") == "cancelled":
            raise CalendarEventNotFoundError(f"Event '{event_id}' not found in calendar")

        current_etag = existing.get("etag")
        if if_match != current_etag:
            raise CalendarPreconditionFailedError(
                f"ETag mismatch for event '{event_id}': expected {if_match}, actual {current_etag}"
            )

        self._etag_counter += 1
        new_etag = f'"{self._etag_counter}"'

        updated = dict(payload)
        updated["id"] = event_id
        updated["etag"] = new_etag
        if "status" not in updated:
            updated["status"] = existing.get("status", "confirmed")

        self._events[key] = updated
        return self._to_transport_event(updated)

    @staticmethod
    def _to_transport_event(raw: dict[str, Any]) -> CalendarTransportEvent:
        event_id = str(raw.get("id", ""))
        etag = raw.get("etag")
        summary = str(raw.get("summary", ""))
        status = str(raw.get("status", "confirmed"))

        start = raw.get("start", {})
        end = raw.get("end", {})

        if "date" in start:
            all_day = True
            start_time = str(start["date"])
            end_time = str(end.get("date", start_time)) if end else None
        else:
            all_day = False
            start_time = str(start.get("dateTime", ""))
            end_time = str(end.get("dateTime", "")) if end else None

        return CalendarTransportEvent(
            id=event_id,
            etag=etag,
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            status=status,
            raw_resource=dict(raw),
        )


# ===========================================================================
# Pluggable Google API Client Transport
# ===========================================================================


class GoogleApiClientCalendarTransport:
    """Transport wrapping an official google-api-python-client Resource object."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        try:
            req = self._service.events().get(calendarId=calendar_id, eventId=event_id)
            resp = req.execute()
            if not resp or resp.get("status") == "cancelled":
                return None
            return FakeGoogleCalendarTransport._to_transport_event(resp)
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                return None
            if status_code in (401, 403):
                raise CalendarAuthenticationError(f"Google Calendar auth error: {exc}") from exc
            if status_code == 429:
                raise CalendarRateLimitError(f"Google Calendar rate limit exceeded: {exc}") from exc
            raise CalendarApiError(f"Google Calendar API get_event failed: {exc}") from exc

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        if_match: str,
        send_updates: str = "none",
    ) -> CalendarTransportEvent:
        try:
            req = self._service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=payload,
                sendUpdates=send_updates,
                headers={"If-Match": if_match},
            )
            resp = req.execute()
            return FakeGoogleCalendarTransport._to_transport_event(resp)
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                raise CalendarEventNotFoundError(f"Event '{event_id}' not found") from exc
            if status_code == 412:
                raise CalendarPreconditionFailedError(
                    f"ETag mismatch for event '{event_id}'"
                ) from exc
            if status_code in (401, 403):
                raise CalendarAuthenticationError(f"Google Calendar auth error: {exc}") from exc
            if status_code == 429:
                raise CalendarRateLimitError(f"Google Calendar rate limit exceeded: {exc}") from exc
            raise CalendarApiError(f"Google Calendar API update_event failed: {exc}") from exc


# ===========================================================================
# Normalized Read Models
# ===========================================================================


class CalendarReadStatus(StrEnum):
    """Result status of a Calendar read operation."""

    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class CalendarEventObservation:
    """Normalized, sanitized observation of an event from Google Calendar.

    Persists only the narrow fields StillDone requires.
    Sensitive identifiers are masked in repr/str.
    Does NOT assert or imply VERIFIED or READY.
    """

    event_id: str
    calendar_id: str
    summary: str
    start_time: str
    end_time: str | None
    all_day: bool
    etag: str | None
    status: str
    observed_at: datetime
    raw_event_payload: dict[str, Any]

    def __repr__(self) -> str:
        return (
            f"CalendarEventObservation(event_id='***', calendar_id='***', "
            f"summary='{self.summary}', start_time='{self.start_time}', "
            f"all_day={self.all_day}, status='{self.status}')"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True, slots=True)
class CalendarReadResult:
    """Result of a Google Calendar read attempt.

    Contains observation if found, or explicit NOT_FOUND / PROVIDER_ERROR status.
    Does NOT confer authority and cannot produce VERIFIED or READY state.
    """

    status: CalendarReadStatus
    event_id: str
    observation: CalendarEventObservation | None = None
    error_message: str | None = None
    read_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __repr__(self) -> str:
        return (
            f"CalendarReadResult(status={self.status.value}, "
            f"event_id='***', has_observation={self.observation is not None})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ===========================================================================
# Google Calendar Read Adapter
# ===========================================================================


class GoogleCalendarReadAdapter:
    """Bounded, fail-closed Google Calendar read adapter.

    Restricted strictly to the dedicated demo calendar configured in DemoResourceScope.
    Never falls back to 'primary', defaults, or name search.
    """

    def __init__(self, scope: DemoResourceScope, transport: CalendarTransport) -> None:
        if not isinstance(scope, DemoResourceScope):
            raise CalendarScopeError(
                f"scope must be a DemoResourceScope instance, got {type(scope).__name__}"
            )
        cal_id_lower = scope.calendar_id.strip().lower()
        if cal_id_lower in FORBIDDEN_CALENDAR_IDS:
            raise CalendarScopeError(
                f"Demo calendar scope cannot be '{scope.calendar_id}'. "
                "Dedicated demo calendar required."
            )
        self._scope = scope
        self._transport = transport

    @property
    def scope(self) -> DemoResourceScope:
        """The bound demo resource scope."""
        return self._scope

    def read_event(
        self,
        action: ValidatedActionContract | ActionContract,
    ) -> CalendarReadResult:
        """Read an exact calendar event according to the canonical action contract.

        Validates the action contract, enforces demo isolation against the configured scope,
        and retrieves the exact event from the transport.

        Args:
            action: Either a ValidatedActionContract or raw ActionContract.

        Returns:
            CalendarReadResult with SUCCESS, NOT_FOUND, or PROVIDER_ERROR.

        Raises:
            CalendarScopeError / CalendarOutOfScopeError: If targeting outside demo calendar.
            CalendarTargetError / ActionPolicyError: If target identity is malformed.
        """
        # Step 1: Ensure ValidatedActionContract
        if isinstance(action, ActionContract):
            validated = validate_action_contract(action)
        elif isinstance(action, ValidatedActionContract):
            validated = action
        else:
            raise TypeError(
                f"action must be ActionContract or ValidatedActionContract, "
                f"got {type(action).__name__}"
            )

        # Step 2: Validate ActionType
        if validated.action_type != ActionType.CALENDAR_READ:
            raise CalendarTargetError(
                f"GoogleCalendarReadAdapter handles '{ActionType.CALENDAR_READ.value}', "
                f"got '{validated.action_type.value}'"
            )

        # Step 3: Validate Target System & ResourceKind
        if validated.target.system != CANONICAL_CALENDAR_SYSTEM:
            raise CalendarTargetError(
                f"Target system must be '{CANONICAL_CALENDAR_SYSTEM}', "
                f"got '{validated.target.system}'"
            )
        if validated.target.resource_kind != CANONICAL_CALENDAR_RESOURCE_KIND:
            raise CalendarTargetError(
                f"Target resource_kind must be '{CANONICAL_CALENDAR_RESOURCE_KIND.value}', "
                f"got '{validated.target.resource_kind.value}'"
            )

        # Step 4: Strict Demo Isolation Check
        # verify_demo_resource_isolation checks target.parent_id == scope.calendar_id
        try:
            verify_demo_resource_isolation(validated, self._scope)
        except DemoIsolationError as exc:
            logger.warning("Calendar demo isolation rejected: %s", exc)
            raise

        # Step 5: Exact Event ID Extraction (never match by summary or search)
        event_id = validated.target.resource_id
        if not event_id or not event_id.strip():
            raise CalendarTargetError("Target resource_id (event_id) must be non-empty")

        # Step 6: Execute provider read via transport
        now = datetime.now(tz=UTC)
        try:
            transport_event = self._transport.get_event(
                calendar_id=self._scope.calendar_id,
                event_id=event_id,
            )
        except CalendarTransportError as exc:
            logger.error("Transport error reading event: %s", exc)
            return CalendarReadResult(
                status=CalendarReadStatus.PROVIDER_ERROR,
                event_id=event_id,
                error_message=str(exc),
                read_at=now,
            )
        except Exception as exc:
            logger.error("Unexpected error reading event: %s", exc)
            return CalendarReadResult(
                status=CalendarReadStatus.PROVIDER_ERROR,
                event_id=event_id,
                error_message=f"Unexpected transport failure: {type(exc).__name__}",
                read_at=now,
            )

        if transport_event is None or transport_event.status == "cancelled":
            return CalendarReadResult(
                status=CalendarReadStatus.NOT_FOUND,
                event_id=event_id,
                read_at=now,
            )

        # Step 7: Construct normalized observation (persisting only necessary fields)
        observation = CalendarEventObservation(
            event_id=transport_event.id,
            calendar_id=self._scope.calendar_id,
            summary=transport_event.summary,
            start_time=transport_event.start_time,
            end_time=transport_event.end_time,
            all_day=transport_event.all_day,
            etag=transport_event.etag,
            status=transport_event.status,
            observed_at=now,
            raw_event_payload=dict(transport_event.raw_resource),
        )

        return CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=event_id,
            observation=observation,
            read_at=now,
        )
