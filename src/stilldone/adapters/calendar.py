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

import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from stilldone.action_policy import (
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.authority_policy import (
    evaluate_authority,
)
from stilldone.demo_isolation import (
    DemoIsolationError,
    DemoResourceScope,
    verify_demo_resource_isolation,
)
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import ApprovalGrant
from stilldone.domain.mission import MissionId
from stilldone.redaction import redact_text

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

    def __init__(
        self,
        message: str = "Calendar transport error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class CalendarEventNotFoundError(CalendarTransportError):
    """Raised when the requested event does not exist on the specified calendar."""

    def __init__(
        self,
        message: str = "Calendar event not found",
        status_code: int | None = 404,
    ) -> None:
        super().__init__(message, status_code=status_code)


class CalendarPreconditionFailedError(CalendarTransportError):
    """Raised when an ETag mismatch or HTTP 412 precondition check fails."""

    def __init__(
        self,
        message: str = "ETag mismatch: precondition check failed for calendar event",
        status_code: int | None = 412,
    ) -> None:
        super().__init__(message, status_code=status_code)


class CalendarAuthenticationError(CalendarTransportError):
    """Raised when credentials or OAuth tokens are rejected by Google APIs."""

    def __init__(
        self,
        message: str = "Google Calendar authentication/authorization error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)


class CalendarRateLimitError(CalendarTransportError):
    """Raised when Google Calendar rate limits (HTTP 429) are encountered."""

    def __init__(
        self,
        message: str = "Google Calendar rate limit exceeded",
        status_code: int | None = 429,
    ) -> None:
        super().__init__(message, status_code=status_code)


class CalendarApiError(CalendarTransportError):
    """Raised when Google Calendar API returns an unhandled error response."""

    def __init__(
        self,
        message: str = "Google Calendar API error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)


def _sanitize_calendar_transport_error(exc: Exception) -> str:
    """Map transport/provider exceptions to bounded sanitized error messages.

    Guarantees that raw provider error payloads, URLs, tokens, calendar IDs,
    event IDs, and private details are never exposed in error messages.
    """
    status_code: int | None = getattr(exc, "status_code", None)
    if status_code is None:
        resp = getattr(exc, "resp", None)
        if resp is not None:
            status_code = getattr(resp, "status", None)

    if status_code is None:
        match = re.search(r"\b([45]\d\d)\b", str(exc))
        if match:
            try:
                status_code = int(match.group(1))
            except Exception:
                status_code = None

    code_suffix = f" (status {status_code})" if status_code is not None else ""

    if isinstance(exc, CalendarAuthenticationError):
        msg = f"Calendar authentication/authorization failed{code_suffix}"
    elif isinstance(exc, CalendarRateLimitError):
        msg = f"Calendar rate limit exceeded{code_suffix}"
    elif isinstance(exc, CalendarPreconditionFailedError):
        msg = f"Calendar event update conflict (ETag mismatch){code_suffix}"
    elif isinstance(exc, CalendarEventNotFoundError):
        msg = f"Calendar event not found{code_suffix}"
    elif isinstance(exc, CalendarApiError):
        msg = f"Calendar provider API error{code_suffix}"
    elif isinstance(exc, CalendarTransportError):
        msg = f"Calendar provider transport error{code_suffix}"
    else:
        msg = f"Unexpected calendar transport failure: {type(exc).__name__}"

    return redact_text(msg)


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
            f"CalendarTransportEvent(id='***', summary='***', "
            f"start_time='***', all_day={self.all_day}, status='{self.status}')"
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
        timezone: str | None = None,
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
            if end_time:
                raw["end"] = {"date": end_time}
            else:
                try:
                    s_d = date.fromisoformat(start_time.split("T")[0])
                    raw["end"] = {"date": (s_d + timedelta(days=1)).isoformat()}
                except Exception:
                    raw["end"] = {"date": start_time}
        else:
            raw["start"] = {"dateTime": start_time}
            raw["end"] = {"dateTime": end_time or start_time}

        if timezone:
            if "start" in raw and isinstance(raw["start"], dict):
                raw["start"]["timeZone"] = timezone
            if "end" in raw and isinstance(raw["end"], dict):
                raw["end"]["timeZone"] = timezone

        if extra_fields:
            for k, v in extra_fields.items():
                if k in ("start", "end") and isinstance(v, dict) and isinstance(raw.get(k), dict):
                    raw[k].update(v)
                elif k not in raw:
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
        if not if_match or if_match.strip() == "*":
            raise CalendarTargetError(
                "Unconditional overwrite (If-Match: *) is strictly forbidden; exact ETag required"
            )

        self.writes_count += 1
        self.last_if_match = if_match
        self.last_send_updates = send_updates

        key = (calendar_id, event_id)
        existing = self._events.get(key)
        if existing is None or existing.get("status") == "cancelled":
            raise CalendarEventNotFoundError("Calendar event not found")

        current_etag = existing.get("etag")
        if if_match != current_etag:
            raise CalendarPreconditionFailedError(
                "ETag mismatch: precondition check failed for calendar event"
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
        end_time: str | None = None

        if "date" in start:
            all_day = True
            start_time = str(start["date"])
            if end and "date" in end:
                end_time = str(end["date"])
            else:
                try:
                    s_d = date.fromisoformat(start_time.split("T")[0])
                    end_time = (s_d + timedelta(days=1)).isoformat()
                except Exception:
                    end_time = start_time
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
                raise CalendarAuthenticationError(
                    f"Google Calendar auth error (status {status_code})",
                    status_code=status_code,
                ) from exc
            if status_code == 429:
                raise CalendarRateLimitError(
                    "Google Calendar rate limit exceeded (status 429)",
                    status_code=429,
                ) from exc
            if status_code is not None:
                raise CalendarApiError(
                    f"Google Calendar API get_event failed (status {status_code})",
                    status_code=status_code,
                ) from exc
            raise CalendarApiError("Google Calendar API get_event failed") from exc

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        if_match: str,
        send_updates: str = "none",
    ) -> CalendarTransportEvent:
        if not if_match or if_match.strip() == "*":
            raise CalendarTargetError(
                "Unconditional overwrite (If-Match: *) is strictly forbidden; exact ETag required"
            )

        try:
            req = self._service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=payload,
                sendUpdates=send_updates,
            )
            if getattr(req, "headers", None) is None:
                req.headers = {}
            req.headers["If-Match"] = if_match
            resp = req.execute()
            return FakeGoogleCalendarTransport._to_transport_event(resp)
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                raise CalendarEventNotFoundError(
                    "Calendar event not found (status 404)",
                    status_code=404,
                ) from exc
            if status_code == 412:
                raise CalendarPreconditionFailedError(
                    "ETag mismatch: precondition check failed for calendar event (status 412)",
                    status_code=412,
                ) from exc
            if status_code in (401, 403):
                raise CalendarAuthenticationError(
                    f"Google Calendar auth error (status {status_code})",
                    status_code=status_code,
                ) from exc
            if status_code == 429:
                raise CalendarRateLimitError(
                    "Google Calendar rate limit exceeded (status 429)",
                    status_code=429,
                ) from exc
            if status_code is not None:
                raise CalendarApiError(
                    f"Google Calendar API update_event failed (status {status_code})",
                    status_code=status_code,
                ) from exc
            raise CalendarApiError("Google Calendar API update_event failed") from exc


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

    Persists only the narrow bounded fields StillDone requires.
    Sensitive identifiers and private details are masked in repr/str.
    Does NOT retain unrelated provider fields (attendees, description, etc.).
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

    def __repr__(self) -> str:
        return (
            f"CalendarEventObservation(event_id='***', calendar_id='***', "
            f"summary='***', start_time='***', "
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
            logger.warning("Calendar demo isolation rejected: %s", type(exc).__name__)
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
            logger.error("Transport error reading event: %s", type(exc).__name__)
            return CalendarReadResult(
                status=CalendarReadStatus.PROVIDER_ERROR,
                event_id=event_id,
                error_message=_sanitize_calendar_transport_error(exc),
                read_at=now,
            )
        except Exception as exc:
            logger.error("Unexpected error reading event: %s", type(exc).__name__)
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
        )

        return CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=event_id,
            observation=observation,
            read_at=now,
        )


# ===========================================================================
# Datetime / Idempotency Normalization Helpers
# ===========================================================================


def _normalize_iso_time(time_str: str) -> tuple[int, datetime | None]:
    """Parse time string into comparable form.

    Returns (0, dt_utc) for datetime, (1, dt_date) for date, or (2, None) if unparseable.
    """
    clean = time_str.strip()
    if "T" not in clean and " " not in clean:
        try:
            d = date.fromisoformat(clean)
            return (1, datetime(d.year, d.month, d.day, tzinfo=UTC))
        except Exception:
            return (2, None)
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (0, dt.astimezone(UTC))
    except Exception:
        return (2, None)


def _is_time_equal(t1: str, t2: str) -> bool:
    """Deterministically check if two time strings represent the same point in time or date."""
    if t1.strip() == t2.strip():
        return True
    kind1, dt1 = _normalize_iso_time(t1)
    kind2, dt2 = _normalize_iso_time(t2)
    if kind1 == kind2 and dt1 is not None and dt2 is not None:
        return dt1 == dt2
    return False


# ===========================================================================
# Normalized Update Models
# ===========================================================================


class CalendarUpdateStatus(StrEnum):
    """Result status of a Calendar update operation."""

    UPDATED = "UPDATED"
    NOOP_ALREADY_APPLIED = "NOOP_ALREADY_APPLIED"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class CalendarUpdateResult:
    """Result of a Google Calendar update attempt.

    Contains writes_performed counter and observation.
    Does NOT assert or imply VERIFIED or READY state.
    """

    status: CalendarUpdateStatus
    event_id: str
    writes_performed: int
    observation: CalendarEventObservation | None = None
    applied_parameters: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __repr__(self) -> str:
        return (
            f"CalendarUpdateResult(status={self.status.value}, "
            f"event_id='***', writes_performed={self.writes_performed})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ===========================================================================
# Google Calendar Bounded Update Adapter with Idempotency
# ===========================================================================


class GoogleCalendarUpdateAdapter:
    """Bounded, fail-closed Google Calendar update adapter.

    Enforces:
    - Dedicated demo calendar scope (DemoResourceScope).
    - P-04 action validation (ValidatedActionContract).
    - P-04 authority evaluation with bound ApprovalGrant.
    - Read-before-write against exact target event.
    - Adapter-level idempotency strategy: checks if requested state is already true.
      If so, returns NOOP_ALREADY_APPLIED with writes_performed=0.
    - Conditional mutation using currently observed ETag with If-Match (never '*').
    - Preserves unrelated valid event fields.
    - Bounded parameters only: summary, start_time, all_day.
    - Avoids attendee notification side effects (sendUpdates='none').
    - Precondition conflict (412) handled gracefully without blind overwrite.
    - Zero mission state mutation and zero READY/VERIFIED promotions.
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

    def update_event(
        self,
        action: ValidatedActionContract | ActionContract,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> CalendarUpdateResult:
        """Update an exact calendar event according to the canonical action contract.

        Fails closed before any provider read/write if action validation, demo isolation,
        or bound approval is missing or invalid.
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
        if validated.action_type != ActionType.CALENDAR_UPDATE:
            raise CalendarTargetError(
                f"GoogleCalendarUpdateAdapter handles '{ActionType.CALENDAR_UPDATE.value}', "
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
        try:
            verify_demo_resource_isolation(validated, self._scope)
        except DemoIsolationError as exc:
            logger.warning("Calendar demo isolation rejected for update: %s", type(exc).__name__)
            raise

        # Step 5: Authority Policy Evaluation (Fail-closed BEFORE any provider call)
        eval_at = at if at is not None else datetime.now(tz=UTC)
        authority_decision = evaluate_authority(validated, approval=approval, at=eval_at)
        authority_decision.raise_for_status()

        # Step 6: Target Event ID
        event_id = validated.target.resource_id
        if not event_id or not event_id.strip():
            raise CalendarTargetError("Target resource_id (event_id) must be non-empty")

        # Step 7: Read-before-write
        now = datetime.now(tz=UTC)
        try:
            current_transport_event = self._transport.get_event(
                calendar_id=self._scope.calendar_id,
                event_id=event_id,
            )
        except CalendarTransportError as exc:
            logger.error("Transport error reading event for update: %s", type(exc).__name__)
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.PROVIDER_ERROR,
                event_id=event_id,
                writes_performed=0,
                error_message=_sanitize_calendar_transport_error(exc),
                updated_at=now,
            )
        except Exception as exc:
            logger.error("Unexpected error reading event for update: %s", type(exc).__name__)
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.PROVIDER_ERROR,
                event_id=event_id,
                writes_performed=0,
                error_message=f"Unexpected transport failure: {type(exc).__name__}",
                updated_at=now,
            )

        if current_transport_event is None or current_transport_event.status == "cancelled":
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.NOT_FOUND,
                event_id=event_id,
                writes_performed=0,
                error_message="Event not found on demo calendar",
                updated_at=now,
            )

        # Build current observation
        current_obs = CalendarEventObservation(
            event_id=current_transport_event.id,
            calendar_id=self._scope.calendar_id,
            summary=current_transport_event.summary,
            start_time=current_transport_event.start_time,
            end_time=current_transport_event.end_time,
            all_day=current_transport_event.all_day,
            etag=current_transport_event.etag,
            status=current_transport_event.status,
            observed_at=now,
        )

        # Step 8: Deterministic Idempotency Check
        params = validated.parameters.to_dict()
        already_matches = True

        if "summary" in params:
            if current_obs.summary != params["summary"]:
                already_matches = False

        if "all_day" in params:
            if current_obs.all_day != params["all_day"]:
                already_matches = False

        if "start_time" in params:
            if not _is_time_equal(current_obs.start_time, str(params["start_time"])):
                already_matches = False

        if already_matches:
            # Desired state is already true! Zero provider write performed.
            logger.info("Calendar event already in desired state; skipping write.")
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.NOOP_ALREADY_APPLIED,
                event_id=event_id,
                writes_performed=0,
                observation=current_obs,
                applied_parameters=dict(params),
                updated_at=now,
            )

        # Step 9: Prepare updated full event resource (preserving unrelated provider fields)
        if not current_transport_event.etag:
            raise CalendarTargetError("Cannot conditionally update event without provider ETag")
        if current_transport_event.etag.strip() == "*":
            raise CalendarTargetError(
                "Unconditional overwrite (If-Match: *) is strictly forbidden; exact ETag required"
            )

        raw_payload = copy.deepcopy(current_transport_event.raw_resource)

        if "summary" in params:
            raw_payload["summary"] = str(params["summary"])

        # Determine whether temporal fields genuinely require rebuilding.
        # If neither start_time nor all_day is being changed (e.g. summary-only update),
        # do NOT reconstruct start/end at all; preserve original provider
        # start/end byte-for-structure.
        start_time_in_params = "start_time" in params
        all_day_in_params = "all_day" in params

        temporal_changed = False
        if all_day_in_params and bool(params["all_day"]) != current_obs.all_day:
            temporal_changed = True
        elif start_time_in_params and (
            str(params["start_time"]).strip() != current_obs.start_time.strip()
            or not _is_time_equal(current_obs.start_time, str(params["start_time"]))
        ):
            temporal_changed = True

        if temporal_changed:
            new_all_day = bool(params.get("all_day", current_obs.all_day))
            new_start = str(params.get("start_time", current_obs.start_time))

            # Retrieve existing provider start and end dicts to preserve metadata (such as timeZone)
            start_dict = (
                dict(raw_payload["start"]) if isinstance(raw_payload.get("start"), dict) else {}
            )
            end_dict = dict(raw_payload["end"]) if isinstance(raw_payload.get("end"), dict) else {}

            if new_all_day:
                start_date_str = new_start.split("T")[0].strip()
                try:
                    new_start_d = date.fromisoformat(start_date_str)
                except Exception as exc:
                    raise CalendarTargetError(
                        f"Invalid date for all-day event: {new_start}"
                    ) from exc

                # Determine day-span: preserve existing span if previously all-day, else 1 day
                if current_obs.all_day and current_obs.end_time:
                    try:
                        curr_s = date.fromisoformat(current_obs.start_time.split("T")[0].strip())
                        curr_e = date.fromisoformat(current_obs.end_time.split("T")[0].strip())
                        span = (curr_e - curr_s).days
                        span_days = span if span > 0 else 1
                    except Exception:
                        span_days = 1
                    new_end_d = new_start_d + timedelta(days=span_days)
                else:
                    new_end_d = new_start_d + timedelta(days=1)

                if new_end_d <= new_start_d:
                    new_end_d = new_start_d + timedelta(days=1)

                start_dict["date"] = new_start_d.isoformat()
                end_dict["date"] = new_end_d.isoformat()
                start_dict.pop("dateTime", None)
                end_dict.pop("dateTime", None)

                raw_payload["start"] = start_dict
                raw_payload["end"] = end_dict
            else:
                # Timed event
                clean_start = new_start.strip()
                if "T" not in clean_start and " " not in clean_start:
                    raise CalendarTargetError(
                        "Timed event start_time must include time component and timezone "
                        "(RFC3339), got bare date"
                    )
                try:
                    new_s_dt = datetime.fromisoformat(clean_start)
                except Exception as exc:
                    raise CalendarTargetError(
                        f"Invalid RFC3339 datetime for timed event start_time: {new_start}"
                    ) from exc

                if new_s_dt.tzinfo is None:
                    raise CalendarTargetError(
                        "Timed event start_time must include timezone offset or 'Z' (RFC3339)"
                    )

                if not current_obs.all_day and current_obs.end_time:
                    try:
                        orig_s_dt = datetime.fromisoformat(current_obs.start_time)
                        orig_e_dt = datetime.fromisoformat(current_obs.end_time)
                        duration = orig_e_dt - orig_s_dt
                        if duration <= timedelta(0):
                            duration = timedelta(minutes=30)
                    except Exception:
                        duration = timedelta(minutes=30)
                    new_e_dt = new_s_dt + duration
                else:
                    # Transition from all-day (no timed duration) -> deterministic default 30 mins
                    new_e_dt = new_s_dt + timedelta(minutes=30)

                if new_e_dt <= new_s_dt:
                    raise CalendarTargetError(
                        "Timed event end_time must be strictly after start_time"
                    )

                start_dict["dateTime"] = new_s_dt.isoformat()
                end_dict["dateTime"] = new_e_dt.isoformat()
                start_dict.pop("date", None)
                end_dict.pop("date", None)

                # Ensure end_dict preserves timeZone if present on start_dict
                if "timeZone" in start_dict and "timeZone" not in end_dict:
                    end_dict["timeZone"] = start_dict["timeZone"]

                raw_payload["start"] = start_dict
                raw_payload["end"] = end_dict

        # Step 10: Execute conditional update with observed ETag
        try:
            updated_transport_event = self._transport.update_event(
                calendar_id=self._scope.calendar_id,
                event_id=event_id,
                payload=raw_payload,
                if_match=current_transport_event.etag,
                send_updates="none",
            )
        except CalendarPreconditionFailedError as exc:
            logger.warning("ETag precondition conflict updating event: %s", type(exc).__name__)
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.CONFLICT,
                event_id=event_id,
                writes_performed=0,
                error_message=_sanitize_calendar_transport_error(exc),
                updated_at=now,
            )
        except CalendarTransportError as exc:
            logger.error("Transport error executing event update: %s", type(exc).__name__)
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.PROVIDER_ERROR,
                event_id=event_id,
                writes_performed=0,
                error_message=_sanitize_calendar_transport_error(exc),
                updated_at=now,
            )
        except Exception as exc:
            logger.error("Unexpected error executing event update: %s", type(exc).__name__)
            return CalendarUpdateResult(
                status=CalendarUpdateStatus.PROVIDER_ERROR,
                event_id=event_id,
                writes_performed=0,
                error_message=f"Unexpected update failure: {type(exc).__name__}",
                updated_at=now,
            )

        updated_obs = CalendarEventObservation(
            event_id=updated_transport_event.id,
            calendar_id=self._scope.calendar_id,
            summary=updated_transport_event.summary,
            start_time=updated_transport_event.start_time,
            end_time=updated_transport_event.end_time,
            all_day=updated_transport_event.all_day,
            etag=updated_transport_event.etag,
            status=updated_transport_event.status,
            observed_at=now,
        )

        return CalendarUpdateResult(
            status=CalendarUpdateStatus.UPDATED,
            event_id=event_id,
            writes_performed=1,
            observation=updated_obs,
            applied_parameters=dict(params),
            updated_at=now,
        )


# ===========================================================================
# Read-back Verification Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ExpectedCalendarState:
    """Bounded expected calendar state for independent read-back verification.

    Contains only the canonical parameters that can be verified for calendar events.
    At least one expected attribute must be specified.
    """

    summary: str | None = None
    start_time: str | None = None
    all_day: bool | None = None

    def __post_init__(self) -> None:
        if self.summary is None and self.start_time is None and self.all_day is None:
            raise ValueError("ExpectedCalendarState requires at least one expected field")

    def __repr__(self) -> str:
        return (
            f"ExpectedCalendarState(has_summary={self.summary is not None}, "
            f"has_start_time={self.start_time is not None}, "
            f"has_all_day={self.all_day is not None})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class CalendarReadbackStatus(StrEnum):
    """Result status of an independent Calendar read-back verification."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class CalendarReadbackResult:
    """Immutable, typed result of an independent Calendar read-back verification.

    Proves only whether the freshly observed external calendar state deterministically
    matches the expected state at verified_at.
    Does NOT assert or imply mission VERIFIED or READY.
    """

    status: CalendarReadbackStatus
    event_id: str
    expected: ExpectedCalendarState
    observation: CalendarEventObservation | None = None
    mismatches: tuple[str, ...] = ()
    error_message: str | None = None
    verified_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_match(self) -> bool:
        """True if and only if freshly read provider state matched all expected fields."""
        return self.status == CalendarReadbackStatus.MATCH

    def __repr__(self) -> str:
        return (
            f"CalendarReadbackResult(status={self.status.value}, "
            f"event_id='***', is_match={self.is_match}, "
            f"mismatches_count={len(self.mismatches)})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# ===========================================================================
# Google Calendar Independent Read-Back Verifier
# ===========================================================================


class GoogleCalendarReadbackVerifier:
    """Independent read-back verifier for Google Calendar events.

    Independence Law:
    - Initiates a fresh provider read through GoogleCalendarReadAdapter.
    - NEVER accepts an execution/update response payload as proof.
    - NEVER accepts provider-write success alone as verification.
    - Evaluates freshly observed external state deterministically against ExpectedCalendarState.
    - Performs ZERO mutations (read-only).
    - Produces typed CalendarReadbackResult; does NOT promote mission state to READY.
    """

    def __init__(self, read_adapter: GoogleCalendarReadAdapter) -> None:
        if not isinstance(read_adapter, GoogleCalendarReadAdapter):
            raise TypeError(
                f"read_adapter must be a GoogleCalendarReadAdapter instance, "
                f"got {type(read_adapter).__name__}"
            )
        self._read_adapter = read_adapter

    @property
    def read_adapter(self) -> GoogleCalendarReadAdapter:
        return self._read_adapter

    @property
    def scope(self) -> DemoResourceScope:
        return self._read_adapter.scope

    def verify(
        self,
        target: TargetIdentity | ActionContract | ValidatedActionContract,
        expected: ExpectedCalendarState,
    ) -> CalendarReadbackResult:
        """Perform an independent read-back and compare against expected state.

        Args:
            target: The TargetIdentity, ActionContract, or ValidatedActionContract
                    specifying the exact event to read back.
            expected: The ExpectedCalendarState containing expected field values.

        Returns:
            CalendarReadbackResult with MATCH, MISMATCH, NOT_FOUND, or PROVIDER_ERROR.
        """
        if not isinstance(expected, ExpectedCalendarState):
            raise TypeError(
                f"expected must be an ExpectedCalendarState instance, got {type(expected).__name__}"
            )

        # Extract target identity and event ID
        if isinstance(target, TargetIdentity):
            target_id = target
        elif isinstance(target, ValidatedActionContract):
            target_id = target.target
        elif isinstance(target, ActionContract):
            target_id = target.target
        else:
            raise TypeError(
                f"target must be TargetIdentity, ActionContract, or ValidatedActionContract, "
                f"got {type(target).__name__}"
            )

        event_id = target_id.resource_id

        # Build canonical calendar.read contract for independent read
        read_action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system=target_id.system,
                resource_kind=target_id.resource_kind,
                resource_id=event_id,
                parent_id=target_id.parent_id,
            ),
            parameters={},
        )

        # Execute fresh read through the read adapter (this performs an actual provider read!)
        read_result = self._read_adapter.read_event(read_action)

        if read_result.status == CalendarReadStatus.NOT_FOUND:
            verified_at = datetime.now(tz=UTC)
            return CalendarReadbackResult(
                status=CalendarReadbackStatus.NOT_FOUND,
                event_id=event_id,
                expected=expected,
                error_message="Event not found on calendar during read-back",
                verified_at=verified_at,
            )

        if read_result.status == CalendarReadStatus.PROVIDER_ERROR:
            verified_at = datetime.now(tz=UTC)
            return CalendarReadbackResult(
                status=CalendarReadbackStatus.PROVIDER_ERROR,
                event_id=event_id,
                expected=expected,
                error_message=read_result.error_message or "Provider error during read-back",
                verified_at=verified_at,
            )

        observation = read_result.observation
        if observation is None:
            verified_at = datetime.now(tz=UTC)
            return CalendarReadbackResult(
                status=CalendarReadbackStatus.NOT_FOUND,
                event_id=event_id,
                expected=expected,
                verified_at=verified_at,
            )

        # Deterministic comparison against expected state
        mismatches: list[str] = []

        if expected.summary is not None:
            if observation.summary != expected.summary:
                mismatches.append("summary mismatch")

        if expected.all_day is not None:
            if observation.all_day != expected.all_day:
                mismatches.append("all_day mismatch")

        if expected.start_time is not None:
            if not _is_time_equal(observation.start_time, expected.start_time):
                mismatches.append("start_time mismatch")

        verified_at = datetime.now(tz=UTC)

        if mismatches:
            return CalendarReadbackResult(
                status=CalendarReadbackStatus.MISMATCH,
                event_id=event_id,
                expected=expected,
                observation=observation,
                mismatches=tuple(mismatches),
                verified_at=verified_at,
            )

        return CalendarReadbackResult(
            status=CalendarReadbackStatus.MATCH,
            event_id=event_id,
            expected=expected,
            observation=observation,
            mismatches=(),
            verified_at=verified_at,
        )
