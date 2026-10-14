"""Deterministic disposable demo resource seeding and verification engine for StillDone.

Provides bounded, fail-closed seeding and pre-state verification for the canonical
killer mission demo resources:
- Dedicated disposable Google Calendar ('StillDone Demo')
- Dedicated disposable Google Task List ('StillDone Demo')
- Canonical initial demo event ('Leave for school' at 07:45)
- Verification that required prep task is absent

Guarantees:
- Enforces DemoResourceScope; strictly forbids 'primary', 'default', or out-of-scope targets.
- Fail-closed mutation boundary: permit_mutation must be explicitly True to mutate;
  otherwise halts with BLOCKED_UNAUTHORIZED or BLOCKED_PREFLIGHT.
- Idempotency & duplicate detection: if canonical resources/events already exist in
  the expected pre-state, performs 0 writes and returns VERIFIED_EXISTING.
- Duplicate contradiction: if multiple candidate events exist, fails closed without guessing.
- Distinct read-back: provider write success does NOT imply verification; a separate
  independent read-back is strictly executed before declaring readback_verified=True.
- Provenance separation: accurately distinguishes LIVE_GOOGLE, FIXTURE, RECORDED_LIVE, NOT_RUN.
- Zero secrets/PII: external resource IDs, tokens, and credentials are redacted in str()/repr().
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from stilldone.adapters.calendar import CalendarTransportEvent
from stilldone.demo_isolation import (
    DemoResourceScope,
    DemoScopeTypeError,
)
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.redaction import redact_text

logger = logging.getLogger(__name__)

# ===========================================================================
# Canonical Constants
# ===========================================================================

DEFAULT_DEMO_CALENDAR_TITLE: str = "StillDone Demo"
DEFAULT_DEMO_TASK_LIST_TITLE: str = "StillDone Demo"
DEFAULT_DEMO_EVENT_TITLE: str = "Leave for school"
DEFAULT_PREPARATION_TASK_TITLE: str = "Pack backpacks"

FORBIDDEN_CALENDAR_IDS: frozenset[str] = frozenset({"primary", "default"})
FORBIDDEN_TASK_LIST_IDS: frozenset[str] = frozenset({"default", "@default"})
DEFAULT_DISCOVERY_MAX_PAGES: int = 10

# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class DemoSeedingError(Exception):
    """Base exception for all demo seeding operations."""


class DemoSeedingScopeError(DemoSeedingError, ValueError):
    """Raised when target IDs violate DemoResourceScope or use forbidden primary/default aliases."""


class DemoSeedingUnauthorizedError(DemoSeedingError, PermissionError):
    """Raised when a mutation is required but permit_mutation is False."""


class DemoSeedingPreflightError(DemoSeedingError):
    """Raised when preflight checks detect missing containers or misconfigured scope."""


class DemoSeedingDuplicateError(DemoSeedingError):
    """Raised when multiple candidate events or contradictory resources exist."""


class DemoSeedingVerificationError(DemoSeedingError):
    """Raised when post-write independent read-back fails to confirm expected state."""


class DemoSeedingTransportError(DemoSeedingError):
    """Raised when transport/network errors occur during seeding operations."""


class DemoSeedingIncompleteDiscoveryError(DemoSeedingError):
    """Raised when container pagination exceeds safety bounds or discovery is incomplete."""


class DemoSeedingProvenanceError(DemoSeedingError, ValueError):
    """Raised when transport capability contradicts claimed evidence provenance."""


class DemoSeedingContradictionError(DemoSeedingError):
    """Raised when external pre-state contradicts canonical preconditions."""


# ===========================================================================
# Operation Status & Data Models
# ===========================================================================


class SeedOperationStatus(StrEnum):
    """Status of a demo seeding / pre-state verification operation."""

    VERIFIED_EXISTING = "VERIFIED_EXISTING"
    MUTATION_EXECUTED = "MUTATION_EXECUTED"
    BLOCKED_UNAUTHORIZED = "BLOCKED_UNAUTHORIZED"
    BLOCKED_PREFLIGHT = "BLOCKED_PREFLIGHT"
    BLOCKED_LIVE = "BLOCKED_LIVE"
    DUPLICATE_CONTRADICTION = "DUPLICATE_CONTRADICTION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    WRONG_TARGET_REJECTED = "WRONG_TARGET_REJECTED"
    CONTRADICTORY_PRE_STATE = "CONTRADICTORY_PRE_STATE"
    INCOMPLETE_DISCOVERY = "INCOMPLETE_DISCOVERY"


@dataclass(frozen=True, slots=True)
class CanonicalEventSpec:
    """Specification of the canonical initial demo event."""

    title: str
    start_time: str
    end_time: str
    description: str = "StillDone canonical demo event"

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(self.start_time, str) or not self.start_time.strip():
            raise ValueError("start_time must be a non-empty ISO-8601 string")
        if not isinstance(self.end_time, str) or not self.end_time.strip():
            raise ValueError("end_time must be a non-empty ISO-8601 string")


def create_canonical_event_spec(
    target_date: date | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    title: str = DEFAULT_DEMO_EVENT_TITLE,
    description: str = "StillDone canonical demo event",
) -> CanonicalEventSpec:
    """Create a CanonicalEventSpec with canonical defaults.

    Defaults to tomorrow morning at 07:45 - 08:15 UTC if start/end times are omitted.
    """
    if start_time and end_time:
        return CanonicalEventSpec(
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
        )
    if target_date is None:
        target_date = (datetime.now(UTC) + timedelta(days=1)).date()
    computed_start = f"{target_date.isoformat()}T07:45:00Z"
    computed_end = f"{target_date.isoformat()}T08:15:00Z"
    return CanonicalEventSpec(
        title=title,
        start_time=computed_start,
        end_time=computed_end,
        description=description,
    )


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    """Sanitized, immutable result of demo resource seeding / pre-state verification.

    Zero secrets, tokens, or raw external identifiers leaked in str/repr.
    """

    status: SeedOperationStatus
    provenance: EvidenceProvenance
    calendar_id: str | None = None
    task_list_id: str | None = None
    event_id: str | None = None
    event_start_time: str | None = None
    writes_performed: int = 0
    readback_verified: bool = False
    is_seed_complete: bool = False
    details: str = ""
    error_message: str | None = None

    def __repr__(self) -> str:
        cal_masked = "***" if self.calendar_id else None
        tl_masked = "***" if self.task_list_id else None
        ev_masked = "***" if self.event_id else None
        return (
            f"DemoSeedResult(status={self.status.value}, "
            f"provenance={self.provenance.value}, "
            f"calendar_id={cal_masked!r}, "
            f"task_list_id={tl_masked!r}, "
            f"event_id={ev_masked!r}, "
            f"writes_performed={self.writes_performed}, "
            f"readback_verified={self.readback_verified}, "
            f"is_seed_complete={self.is_seed_complete})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_sanitized_dict(self) -> dict[str, Any]:
        """Produce sanitized dictionary representation for logging/CLI output."""
        return {
            "status": self.status.value,
            "provenance": self.provenance.value,
            "calendar_id": "[REDACTED]" if self.calendar_id else None,
            "task_list_id": "[REDACTED]" if self.task_list_id else None,
            "event_id": "[REDACTED]" if self.event_id else None,
            "event_start_time": self.event_start_time,
            "writes_performed": self.writes_performed,
            "readback_verified": self.readback_verified,
            "is_seed_complete": self.is_seed_complete,
            "details": self.details,
            "error_message": self.error_message,
        }


# ===========================================================================
# Transport Protocols
# ===========================================================================


@runtime_checkable
class CalendarSeedTransport(Protocol):
    """Protocol for Calendar seed transport operations."""

    def get_calendar(self, calendar_id: str) -> dict[str, Any] | None:
        """Fetch calendar metadata, or None if not found."""
        ...

    def list_events_by_title(
        self,
        calendar_id: str,
        title: str,
        max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES,
    ) -> list[CalendarTransportEvent]:
        """Fetch active events matching the given summary/title across pages."""
        ...

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        """Fetch an event by ID, or None if not found/cancelled."""
        ...

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> CalendarTransportEvent:
        """Insert a new event resource."""
        ...

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        if_match: str | None = None,
    ) -> CalendarTransportEvent:
        """Update an existing event resource."""
        ...

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete an event resource."""
        ...


@runtime_checkable
class TasksSeedTransport(Protocol):
    """Protocol for Tasks seed transport operations."""

    def get_task_list(self, task_list_id: str) -> dict[str, Any] | None:
        """Fetch task list metadata, or None if not found."""
        ...

    def list_tasks(
        self,
        task_list_id: str,
        max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """List tasks on the specified task list across pages."""
        ...

    def delete_task(self, task_list_id: str, task_id: str) -> None:
        """Delete a task resource."""
        ...


# ===========================================================================
# Helper Utilities
# ===========================================================================


def sanitize_error_message(exc: Any) -> str:
    """Sanitize provider error messages without token/secret/path leakage."""
    if exc is None:
        return "UNKNOWN_ERROR"
    raw = str(exc)
    raw_lower = raw.lower()
    if "404" in raw or "notfound" in raw_lower or "not found" in raw_lower:
        return "RESOURCE_NOT_FOUND"
    if "401" in raw or "403" in raw or "unauthorized" in raw_lower or "forbidden" in raw_lower:
        return "AUTHENTICATION_OR_PERMISSION_FAILED"
    if "429" in raw or "ratelimit" in raw_lower or "quota" in raw_lower:
        return "RATE_LIMIT_OR_QUOTA_EXCEEDED"
    if "500" in raw or "502" in raw or "503" in raw or "504" in raw or "unavailable" in raw_lower:
        return "PROVIDER_TEMPORARILY_UNAVAILABLE"

    # Redact raw secrets, emails, URLs, and local file paths
    cleaned = redact_text(raw)
    cleaned = re.sub(r"https?://[^\s]+", "[REDACTED_URL]", cleaned)
    cleaned = re.sub(r"[a-zA-Z0-9_\-\.\\]+[/\\][a-zA-Z0-9_\-\.\\]+", "[REDACTED_PATH]", cleaned)
    if len(cleaned) > 160:
        cleaned = cleaned[:157] + "..."
    return cleaned


def are_datetimes_equal(dt1: str | None, dt2: str | None) -> bool:
    """Compare two ISO-8601 datetime strings with strict timezone awareness."""
    if not dt1 or not dt2:
        return False
    if dt1 == dt2:
        return True
    try:
        norm1 = dt1.replace("Z", "+00:00")
        norm2 = dt2.replace("Z", "+00:00")
        p1 = datetime.fromisoformat(norm1)
        p2 = datetime.fromisoformat(norm2)
        if p1.tzinfo is None or p2.tzinfo is None:
            return False
        return p1.astimezone(UTC) == p2.astimezone(UTC)
    except Exception:
        return False


# ===========================================================================
# In-Memory Fake Transports for Deterministic Testing
# ===========================================================================


class FakeCalendarSeedTransport:
    """In-memory fake implementing CalendarSeedTransport for testing."""

    def __init__(self) -> None:
        self._calendars: dict[str, dict[str, Any]] = {}
        self._events: dict[tuple[str, str], dict[str, Any]] = {}
        self.reads_count: int = 0
        self.writes_count: int = 0
        self.list_count: int = 0
        self._etag_counter: int = 1000
        self._id_counter: int = 5000
        self.fail_readback: bool = False
        self.inconsistent_readback_event: CalendarTransportEvent | None = None
        self.simulate_incomplete_discovery: bool = False

    def add_calendar(self, calendar_id: str, title: str = DEFAULT_DEMO_CALENDAR_TITLE) -> None:
        self._calendars[calendar_id] = {"id": calendar_id, "summary": title}

    def add_event(
        self,
        calendar_id: str,
        event_id: str,
        summary: str,
        start_time: str,
        end_time: str,
        etag: str = '"1001"',
        status: str = "confirmed",
        description: str = "",
    ) -> CalendarTransportEvent:
        raw: dict[str, Any] = {
            "id": event_id,
            "etag": etag,
            "summary": summary,
            "status": status,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
            "description": description,
        }
        self._events[(calendar_id, event_id)] = raw
        return self._to_transport_event(raw)

    def get_calendar(self, calendar_id: str) -> dict[str, Any] | None:
        self.reads_count += 1
        return self._calendars.get(calendar_id)

    def list_events_by_title(
        self,
        calendar_id: str,
        title: str,
        max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES,
    ) -> list[CalendarTransportEvent]:
        self.list_count += 1
        if self.simulate_incomplete_discovery:
            raise DemoSeedingIncompleteDiscoveryError(
                f"Calendar discovery exceeded maximum page limit ({max_pages}); failing closed."
            )
        matches: list[CalendarTransportEvent] = []
        for (c_id, _), raw in self._events.items():
            if c_id == calendar_id and raw.get("status") != "cancelled":
                if raw.get("summary") == title:
                    matches.append(self._to_transport_event(raw))
        return matches

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        self.reads_count += 1
        if self.fail_readback:
            return None
        if self.inconsistent_readback_event is not None:
            return self.inconsistent_readback_event
        raw = self._events.get((calendar_id, event_id))
        if raw is None or raw.get("status") == "cancelled":
            return None
        return self._to_transport_event(raw)

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> CalendarTransportEvent:
        self.writes_count += 1
        self._id_counter += 1
        self._etag_counter += 1
        event_id = body.get("id") or f"ev_{self._id_counter}"
        raw: dict[str, Any] = {
            "id": event_id,
            "etag": f'"{self._etag_counter}"',
            "status": "confirmed",
            "summary": body.get("summary", ""),
            "start": body.get("start", {}),
            "end": body.get("end", {}),
            "description": body.get("description", ""),
        }
        self._events[(calendar_id, event_id)] = raw
        return self._to_transport_event(raw)

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        if_match: str | None = None,
    ) -> CalendarTransportEvent:
        self.writes_count += 1
        raw = self._events.get((calendar_id, event_id))
        if raw is None:
            raise DemoSeedingTransportError(f"Event {event_id} not found on calendar")
        self._etag_counter += 1
        raw["etag"] = f'"{self._etag_counter}"'
        if "summary" in body:
            raw["summary"] = body["summary"]
        if "start" in body:
            raw["start"] = body["start"]
        if "end" in body:
            raw["end"] = body["end"]
        if "description" in body:
            raw["description"] = body["description"]
        return self._to_transport_event(raw)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.writes_count += 1
        raw = self._events.get((calendar_id, event_id))
        if raw is not None:
            raw["status"] = "cancelled"

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
            end_time = str(end.get("date")) if end else None
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


class FakeTasksSeedTransport:
    """In-memory fake implementing TasksSeedTransport for testing."""

    def __init__(self) -> None:
        self._task_lists: dict[str, dict[str, Any]] = {}
        self._tasks: dict[tuple[str, str], dict[str, Any]] = {}
        self.reads_count: int = 0
        self.writes_count: int = 0
        self.list_count: int = 0
        self.simulate_incomplete_discovery: bool = False

    def add_task_list(self, task_list_id: str, title: str = DEFAULT_DEMO_TASK_LIST_TITLE) -> None:
        self._task_lists[task_list_id] = {"id": task_list_id, "title": title}

    def add_task(
        self,
        task_list_id: str,
        task_id: str,
        title: str,
        status: str = "needsAction",
    ) -> None:
        self._tasks[(task_list_id, task_id)] = {
            "id": task_id,
            "title": title,
            "status": status,
        }

    def get_task_list(self, task_list_id: str) -> dict[str, Any] | None:
        self.reads_count += 1
        return self._task_lists.get(task_list_id)

    def list_tasks(
        self,
        task_list_id: str,
        max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES,
    ) -> list[dict[str, Any]]:
        self.list_count += 1
        if self.simulate_incomplete_discovery:
            raise DemoSeedingIncompleteDiscoveryError(
                f"Tasks discovery exceeded maximum page limit ({max_pages}); failing closed."
            )
        return [t for (tl_id, _), t in self._tasks.items() if tl_id == task_list_id]

    def delete_task(self, task_list_id: str, task_id: str) -> None:
        self.writes_count += 1
        self._tasks.pop((task_list_id, task_id), None)


# ===========================================================================
# Google API Client Production Seed Transports
# ===========================================================================


class GoogleApiClientCalendarSeedTransport:
    """Production Calendar seed transport wrapping googleapiclient.discovery.Resource."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def get_calendar(self, calendar_id: str) -> dict[str, Any] | None:
        try:
            req = self._service.calendarList().get(calendarId=calendar_id)
            return req.execute()  # type: ignore[no-any-return]
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                return None
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(
                f"Failed to get calendar metadata: {sanitized}"
            ) from None

    def list_events_by_title(
        self,
        calendar_id: str,
        title: str,
        max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES,
    ) -> list[CalendarTransportEvent]:
        try:
            matches: list[CalendarTransportEvent] = []
            page_token = None
            page_count = 0
            while True:
                page_count += 1
                if page_count > max_pages:
                    raise DemoSeedingIncompleteDiscoveryError(
                        f"Calendar discovery exceeded maximum page limit ({max_pages}); "
                        "failing closed."
                    )
                kwargs: dict[str, Any] = {
                    "calendarId": calendar_id,
                    "maxResults": 50,
                    "singleEvents": True,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                req = self._service.events().list(**kwargs)
                resp = req.execute()
                items = resp.get("items", [])
                for item in items:
                    if item.get("summary") == title and item.get("status") != "cancelled":
                        matches.append(FakeCalendarSeedTransport._to_transport_event(item))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            return matches
        except DemoSeedingIncompleteDiscoveryError:
            raise
        except Exception as exc:
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to list events: {sanitized}") from None

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        try:
            req = self._service.events().get(calendarId=calendar_id, eventId=event_id)
            resp = req.execute()
            if not resp or resp.get("status") == "cancelled":
                return None
            return FakeCalendarSeedTransport._to_transport_event(resp)
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                return None
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to get event: {sanitized}") from None

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> CalendarTransportEvent:
        try:
            req = self._service.events().insert(calendarId=calendar_id, body=body)
            resp = req.execute()
            return FakeCalendarSeedTransport._to_transport_event(resp)
        except Exception as exc:
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to insert event: {sanitized}") from None

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        if_match: str | None = None,
    ) -> CalendarTransportEvent:
        try:
            req = self._service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates="none",
            )
            if if_match and if_match != "*":
                if getattr(req, "headers", None) is None:
                    req.headers = {}
                req.headers["If-Match"] = if_match
            resp = req.execute()
            return FakeCalendarSeedTransport._to_transport_event(resp)
        except Exception as exc:
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to update event: {sanitized}") from None

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        try:
            req = self._service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendUpdates="none",
            )
            req.execute()
        except Exception as exc:
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to delete event: {sanitized}") from None


class GoogleApiClientTasksSeedTransport:
    """Production Tasks seed transport wrapping googleapiclient.discovery.Resource."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def get_task_list(self, task_list_id: str) -> dict[str, Any] | None:
        try:
            req = self._service.tasklists().get(tasklist=task_list_id)
            return req.execute()  # type: ignore[no-any-return]
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                return None
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to get task list: {sanitized}") from None

    def list_tasks(
        self,
        task_list_id: str,
        max_pages: int = DEFAULT_DISCOVERY_MAX_PAGES,
    ) -> list[dict[str, Any]]:
        try:
            all_items: list[dict[str, Any]] = []
            page_token = None
            page_count = 0
            while True:
                page_count += 1
                if page_count > max_pages:
                    raise DemoSeedingIncompleteDiscoveryError(
                        f"Tasks discovery exceeded maximum page limit ({max_pages}); "
                        "failing closed."
                    )
                kwargs: dict[str, Any] = {
                    "tasklist": task_list_id,
                    "maxResults": 100,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                req = self._service.tasks().list(**kwargs)
                resp = req.execute()
                items = resp.get("items", [])
                all_items.extend(items)
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            return all_items
        except DemoSeedingIncompleteDiscoveryError:
            raise
        except Exception as exc:
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to list tasks: {sanitized}") from None

    def delete_task(self, task_list_id: str, task_id: str) -> None:
        try:
            req = self._service.tasks().delete(tasklist=task_list_id, task=task_id)
            req.execute()
        except Exception as exc:
            sanitized = sanitize_error_message(exc)
            raise DemoSeedingTransportError(f"Failed to delete task: {sanitized}") from None


# ===========================================================================
# Core Seeding & Preflight Logic
# ===========================================================================


def seed_canonical_demo_resources(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    *,
    event_spec: CanonicalEventSpec,
    permit_mutation: bool = False,
    provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
) -> DemoSeedResult:
    """Seed or verify canonical disposable demo resources reproducibly.

    1. Enforces DemoResourceScope bounds and strictly forbids primary/default.
    2. Performs provider read-only preflight on calendar and task list containers.
    3. Scans calendar for events matching event_spec.title across pages.
    4. Evaluates event pre-state:
       - If matching event exists with exact start/end time, confirmed status, and non-all-day:
         performs independent read-back; if verified, returns VERIFIED_EXISTING (0 writes).
       - If matching event exists with different time/status: requires mutation. If
         permit_mutation is False, returns BLOCKED_UNAUTHORIZED (0 writes). If
          permit_mutation is True,
         updates event and performs independent read-back.
       - If no matching event exists: requires mutation. If permit_mutation is False,
         returns BLOCKED_UNAUTHORIZED (0 writes). If permit_mutation is True, inserts event and
         performs independent read-back.
       - If multiple matching events exist: fails closed with DUPLICATE_CONTRADICTION.
    5. Evaluates tasks state (detects whether preparation task is present/absent).
       - In canonical pre-state, the preparation task must NOT be present; fails closed with
         CONTRADICTORY_PRE_STATE if already present.
    6. Ensures provider write success never substitutes for independent read-back.
    7. Accurately reports attempted writes even if read-back verification fails.

    Args:
        scope: DemoResourceScope containing dedicated calendar and task list IDs.
        calendar_transport: CalendarSeedTransport implementation.
        tasks_transport: TasksSeedTransport implementation.
        event_spec: CanonicalEventSpec defining canonical initial event.
        permit_mutation: Explicit authorization boolean. Default False (fail-closed).
        provenance: EvidenceProvenance classification.

    Returns:
        Sanitized DemoSeedResult.
    """
    if not isinstance(scope, DemoResourceScope):
        raise DemoScopeTypeError(
            f"scope must be a DemoResourceScope instance, got {type(scope).__name__}"
        )

    # Strict boolean validation
    if permit_mutation is not True and permit_mutation is not False:
        raise DemoSeedingUnauthorizedError(
            "permit_mutation must be a strict boolean (True or False)"
        )

    # Provenance capability check: fixture fake transport cannot claim LIVE_GOOGLE
    if (
        isinstance(calendar_transport, FakeCalendarSeedTransport)
        and provenance == EvidenceProvenance.LIVE_GOOGLE
    ):
        raise DemoSeedingProvenanceError(
            "Fixture fake transport cannot claim LIVE_GOOGLE provenance."
        )

    # 1. Scope / target validation
    cal_id_lower = scope.calendar_id.strip().lower()
    if cal_id_lower in FORBIDDEN_CALENDAR_IDS:
        return DemoSeedResult(
            status=SeedOperationStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                f"Forbidden calendar ID '{scope.calendar_id}'; "
                "primary/default substitution rejected."
            ),
            error_message="WRONG_TARGET_CALENDAR",
        )

    tl_id_lower = scope.task_list_id.strip().lower()
    if tl_id_lower in FORBIDDEN_TASK_LIST_IDS:
        return DemoSeedResult(
            status=SeedOperationStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                f"Forbidden task list ID '{scope.task_list_id}'; default substitution rejected."
            ),
            error_message="WRONG_TARGET_TASK_LIST",
        )

    # 2. Container discovery / read-only preflight
    try:
        cal_meta = calendar_transport.get_calendar(scope.calendar_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=f"Provider calendar preflight probe failed: {sanitized}",
            error_message=sanitized,
        )

    if cal_meta is None:
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                "Dedicated demo calendar does not exist on provider. "
                "Container creation is strictly prohibited."
            ),
            error_message="DEMO_CALENDAR_NOT_FOUND",
        )

    # Dedicated resource identity verification
    if cal_meta.get("primary") is True:
        return DemoSeedResult(
            status=SeedOperationStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details="Primary calendar detected on provider; primary/default substitution rejected.",
            error_message="WRONG_TARGET_CALENDAR",
        )

    if cal_meta.get("summary") != DEFAULT_DEMO_CALENDAR_TITLE:
        return DemoSeedResult(
            status=SeedOperationStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                "Dedicated demo calendar summary does not match expected title "
                f"'{DEFAULT_DEMO_CALENDAR_TITLE}'. "
                "Friendly title alone is insufficient for ownership."
            ),
            error_message="WRONG_TARGET_CALENDAR",
        )

    try:
        tl_meta = tasks_transport.get_task_list(scope.task_list_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=f"Provider task list preflight probe failed: {sanitized}",
            error_message=sanitized,
        )

    if tl_meta is None:
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                "Dedicated demo task list does not exist on provider. "
                "Container creation is strictly prohibited."
            ),
            error_message="DEMO_TASK_LIST_NOT_FOUND",
        )

    if tl_meta.get("title") != DEFAULT_DEMO_TASK_LIST_TITLE:
        return DemoSeedResult(
            status=SeedOperationStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                "Dedicated demo task list title does not match expected title "
                f"'{DEFAULT_DEMO_TASK_LIST_TITLE}'. "
                "Friendly title alone is insufficient for ownership."
            ),
            error_message="WRONG_TARGET_TASK_LIST",
        )

    # 3. Tasks state inspection
    try:
        tasks = tasks_transport.list_tasks(scope.task_list_id)
    except DemoSeedingIncompleteDiscoveryError as exc:
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=str(exc),
            error_message="INCOMPLETE_DISCOVERY",
        )
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=f"Provider task listing failed: {sanitized}",
            error_message=sanitized,
        )

    matching_tasks = [
        t
        for t in tasks
        if t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
    ]
    if len(matching_tasks) > 0:
        return DemoSeedResult(
            status=SeedOperationStatus.CONTRADICTORY_PRE_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                f"Canonical preparation task '{DEFAULT_PREPARATION_TASK_TITLE}' is already present "
                f"on demo task list ({len(matching_tasks)} found); "
                "clean initial pre-state required."
            ),
            error_message="CONTRADICTORY_PRE_STATE_TASK_EXISTS",
        )

    tasks_note = (
        f"Demo task list inspected: {len(tasks)} tasks found; "
        f"'{DEFAULT_PREPARATION_TASK_TITLE}' absent (clean pre-state verified)."
    )

    # 4. Calendar event pre-state inspection
    try:
        matching_events = calendar_transport.list_events_by_title(
            scope.calendar_id, event_spec.title
        )
    except DemoSeedingIncompleteDiscoveryError as exc:
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=str(exc),
            error_message="INCOMPLETE_DISCOVERY",
        )
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=f"Provider event listing failed: {sanitized}",
            error_message=sanitized,
        )

    if len(matching_events) > 1:
        return DemoSeedResult(
            status=SeedOperationStatus.DUPLICATE_CONTRADICTION,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                f"Duplicate contradiction: found {len(matching_events)} events titled "
                f"'{event_spec.title}' on dedicated calendar; refusing ambiguous resolution."
            ),
            error_message="DUPLICATE_EVENTS_CONTRADICTION",
        )

    if len(matching_events) == 1:
        candidate = matching_events[0]
        # Complete pre-state verification: title, start_time, end_time, status, all_day
        time_matches = are_datetimes_equal(
            candidate.start_time, event_spec.start_time
        ) and are_datetimes_equal(candidate.end_time, event_spec.end_time)
        status_matches = (
            (candidate.status == "confirmed")
            and (not candidate.all_day)
            and (candidate.summary == event_spec.title)
        )

        if time_matches and status_matches:
            # Already in canonical pre-state -> execute INDEPENDENT READ-BACK
            readback = calendar_transport.get_event(scope.calendar_id, candidate.id)
            if (
                readback is None
                or not are_datetimes_equal(readback.start_time, event_spec.start_time)
                or not are_datetimes_equal(readback.end_time, event_spec.end_time)
                or readback.id != candidate.id
                or readback.status != "confirmed"
                or readback.all_day
                or readback.summary != event_spec.title
            ):
                return DemoSeedResult(
                    status=SeedOperationStatus.VERIFICATION_FAILED,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    event_id=candidate.id,
                    writes_performed=0,
                    readback_verified=False,
                    is_seed_complete=False,
                    details="Independent read-back verification failed on existing event.",
                    error_message="READBACK_MISMATCH_ON_EXISTING",
                )
            return DemoSeedResult(
                status=SeedOperationStatus.VERIFIED_EXISTING,
                provenance=provenance,
                calendar_id=scope.calendar_id,
                task_list_id=scope.task_list_id,
                event_id=candidate.id,
                event_start_time=readback.start_time,
                writes_performed=0,
                readback_verified=True,
                is_seed_complete=True,
                details=(
                    f"Canonical demo event '{event_spec.title}' already exists at "
                    f"canonical start time {readback.start_time}; 0 writes performed. {tasks_note}"
                ),
            )

        # Candidate exists but fields differ -> requires mutation
        if not permit_mutation:
            return DemoSeedResult(
                status=SeedOperationStatus.BLOCKED_UNAUTHORIZED,
                provenance=provenance,
                calendar_id=scope.calendar_id,
                task_list_id=scope.task_list_id,
                event_id=candidate.id,
                event_start_time=candidate.start_time,
                writes_performed=0,
                readback_verified=False,
                is_seed_complete=False,
                details=(
                    f"Canonical event '{event_spec.title}' exists at start time "
                    f"{candidate.start_time}, differing from target {event_spec.start_time}. "
                    "Mutation required but permit_mutation=False."
                ),
                error_message="MUTATION_UNAUTHORIZED",
            )

        # Mutate existing event back to pre-state with If-Match precondition
        update_body: dict[str, Any] = {
            "summary": event_spec.title,
            "start": {"dateTime": event_spec.start_time},
            "end": {"dateTime": event_spec.end_time},
            "description": event_spec.description,
        }
        calendar_transport.update_event(
            scope.calendar_id,
            candidate.id,
            update_body,
            if_match=candidate.etag,
        )

        # INDEPENDENT READ-BACK
        readback = calendar_transport.get_event(scope.calendar_id, candidate.id)
        if (
            readback is None
            or not are_datetimes_equal(readback.start_time, event_spec.start_time)
            or not are_datetimes_equal(readback.end_time, event_spec.end_time)
            or readback.id != candidate.id
            or readback.status != "confirmed"
            or readback.all_day
            or readback.summary != event_spec.title
        ):
            return DemoSeedResult(
                status=SeedOperationStatus.VERIFICATION_FAILED,
                provenance=provenance,
                calendar_id=scope.calendar_id,
                task_list_id=scope.task_list_id,
                event_id=candidate.id,
                writes_performed=1,
                readback_verified=False,
                is_seed_complete=False,
                details="Independent read-back failed after update mutation.",
                error_message="READBACK_MISMATCH_AFTER_UPDATE",
            )

        return DemoSeedResult(
            status=SeedOperationStatus.MUTATION_EXECUTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            event_id=candidate.id,
            event_start_time=readback.start_time,
            writes_performed=1,
            readback_verified=True,
            is_seed_complete=True,
            details=(
                f"Existing event '{event_spec.title}' updated to pre-state start time "
                f"{readback.start_time} and independently verified. {tasks_note}"
            ),
        )

    # 0 matching events -> creation required
    if not permit_mutation:
        return DemoSeedResult(
            status=SeedOperationStatus.BLOCKED_UNAUTHORIZED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_seed_complete=False,
            details=(
                f"Canonical demo event '{event_spec.title}' is absent. "
                "Creation required but permit_mutation=False."
            ),
            error_message="MUTATION_UNAUTHORIZED",
        )

    insert_body: dict[str, Any] = {
        "summary": event_spec.title,
        "start": {"dateTime": event_spec.start_time},
        "end": {"dateTime": event_spec.end_time},
        "description": event_spec.description,
    }
    created = calendar_transport.insert_event(scope.calendar_id, insert_body)

    # INDEPENDENT READ-BACK
    readback = calendar_transport.get_event(scope.calendar_id, created.id)
    if (
        readback is None
        or not are_datetimes_equal(readback.start_time, event_spec.start_time)
        or not are_datetimes_equal(readback.end_time, event_spec.end_time)
        or readback.id != created.id
        or readback.status != "confirmed"
        or readback.all_day
        or readback.summary != event_spec.title
    ):
        return DemoSeedResult(
            status=SeedOperationStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            event_id=created.id,
            writes_performed=1,
            readback_verified=False,
            is_seed_complete=False,
            details="Independent read-back failed after event creation mutation.",
            error_message="READBACK_MISMATCH_AFTER_INSERT",
        )

    return DemoSeedResult(
        status=SeedOperationStatus.MUTATION_EXECUTED,
        provenance=provenance,
        calendar_id=scope.calendar_id,
        task_list_id=scope.task_list_id,
        event_id=created.id,
        event_start_time=readback.start_time,
        writes_performed=1,
        readback_verified=True,
        is_seed_complete=True,
        details=(
            f"Canonical demo event '{event_spec.title}' created at start time "
            f"{readback.start_time} and independently verified. {tasks_note}"
        ),
    )


def check_demo_resources_preflight(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    *,
    event_spec: CanonicalEventSpec,
    provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
) -> DemoSeedResult:
    """Perform read-only preflight inspection without mutation (permit_mutation=False)."""
    return seed_canonical_demo_resources(
        scope=scope,
        calendar_transport=calendar_transport,
        tasks_transport=tasks_transport,
        event_spec=event_spec,
        permit_mutation=False,
        provenance=provenance,
    )
