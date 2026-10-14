"""Deterministic operator tooling for StillDone dedicated disposable demo resources.

Provides narrowly scoped, idempotent, safe operator commands for:
1. INSPECT: Read-only inspection of dedicated demo resources (0 writes).
2. SETUP: Idempotent seeding/reset of canonical initial demo event (0 writes if already set).
3. VERIFY: Independent read-back and predicate verification of pre-mission readiness (0 writes).
4. TEARDOWN: Narrowly scoped, confirmed cleanup of disposable demo mission artifacts.

Governing Laws:
- Default is DRY_RUN / NO_MUTATION (`permit_mutation=False`).
- Existing DemoResourceScope isolation strictly mandatory; primary and default calendars/lists
  are rejected fail-closed.
- Container creation and container deletion are strictly forbidden.
- Teardown requires explicit target-bound confirmation token to prevent unintended data loss.
- Never targets unrelated calendars, tasks, or resources outside DemoResourceScope.
- Provider write success does NOT imply verification; independent read-back is mandatory.
- All CLI outputs, logs, exceptions, and representations are sanitized (no raw IDs, tokens,
  or secrets).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stilldone.demo_isolation import (
    DemoResourceScope,
    DemoScopeTypeError,
)
from stilldone.demo_seeding import (
    DEFAULT_DEMO_CALENDAR_TITLE,
    DEFAULT_DEMO_TASK_LIST_TITLE,
    DEFAULT_PREPARATION_TASK_TITLE,
    FORBIDDEN_CALENDAR_IDS,
    FORBIDDEN_TASK_LIST_IDS,
    CalendarSeedTransport,
    CanonicalEventSpec,
    DemoSeedingProvenanceError,
    FakeCalendarSeedTransport,
    SeedOperationStatus,
    TasksSeedTransport,
    are_datetimes_equal,
    create_canonical_event_spec,
    sanitize_error_message,
    seed_canonical_demo_resources,
)
from stilldone.domain.provenance import EvidenceProvenance

logger = logging.getLogger(__name__)

# Canonical confirmation string for teardown
CANONICAL_TEARDOWN_CONFIRMATION: str = "CONFIRM_TEARDOWN"


# ===========================================================================
# Operation Modes & Statuses
# ===========================================================================


class DemoOperationMode(StrEnum):
    """Operation mode for demo resource operator tooling."""

    INSPECT = "INSPECT"
    SETUP = "SETUP"
    VERIFY = "VERIFY"
    TEARDOWN = "TEARDOWN"


class DemoToolingStatus(StrEnum):
    """Execution status of demo resource operation."""

    INSPECTED = "INSPECTED"
    VERIFIED_READY = "VERIFIED_READY"
    VERIFIED_EXISTING = "VERIFIED_EXISTING"
    MUTATION_EXECUTED = "MUTATION_EXECUTED"
    TEARDOWN_COMPLETED = "TEARDOWN_COMPLETED"
    ALREADY_CLEAN = "ALREADY_CLEAN"
    BLOCKED_DRY_RUN = "BLOCKED_DRY_RUN"
    BLOCKED_UNAUTHORIZED = "BLOCKED_UNAUTHORIZED"
    BLOCKED_PREFLIGHT = "BLOCKED_PREFLIGHT"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    WRONG_TARGET_REJECTED = "WRONG_TARGET_REJECTED"
    CONTRADICTORY_STATE = "CONTRADICTORY_STATE"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


# ===========================================================================
# Result Model
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DemoToolingResult:
    """Sanitized, immutable result of demo resource operator action.

    Guarantees:
    - Zero raw external IDs or credentials leaked in str() or repr().
    - Accurately tracks writes_performed and readback_verified.
    """

    mode: DemoOperationMode
    status: DemoToolingStatus
    provenance: EvidenceProvenance
    calendar_id: str | None = None
    task_list_id: str | None = None
    writes_performed: int = 0
    readback_verified: bool = False
    is_success: bool = False
    details: str = ""
    error_message: str | None = None
    items_inspected: int = 0
    items_modified: int = 0
    items_deleted: int = 0

    def __repr__(self) -> str:
        cal_masked = "***" if self.calendar_id else None
        tl_masked = "***" if self.task_list_id else None
        return (
            f"DemoToolingResult(mode={self.mode.value}, "
            f"status={self.status.value}, "
            f"provenance={self.provenance.value}, "
            f"calendar_id={cal_masked!r}, "
            f"task_list_id={tl_masked!r}, "
            f"writes_performed={self.writes_performed}, "
            f"readback_verified={self.readback_verified}, "
            f"is_success={self.is_success}, "
            f"items_inspected={self.items_inspected}, "
            f"items_modified={self.items_modified}, "
            f"items_deleted={self.items_deleted})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_sanitized_dict(self) -> dict[str, Any]:
        """Produce sanitized dictionary representation safe for CLI and logs."""
        return {
            "mode": self.mode.value,
            "status": self.status.value,
            "provenance": self.provenance.value,
            "calendar_id": "[REDACTED]" if self.calendar_id else None,
            "task_list_id": "[REDACTED]" if self.task_list_id else None,
            "writes_performed": self.writes_performed,
            "readback_verified": self.readback_verified,
            "is_success": self.is_success,
            "details": self.details,
            "error_message": self.error_message,
            "items_inspected": self.items_inspected,
            "items_modified": self.items_modified,
            "items_deleted": self.items_deleted,
        }


# ===========================================================================
# Core Operator Tooling Engine
# ===========================================================================


def execute_demo_resource_operation(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    *,
    mode: DemoOperationMode = DemoOperationMode.INSPECT,
    permit_mutation: bool = False,
    teardown_confirmation: str | None = None,
    event_spec: CanonicalEventSpec | None = None,
    provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
) -> DemoToolingResult:
    """Execute a safe, scoped operator operation on dedicated demo resources.

    Args:
        scope: DemoResourceScope containing dedicated calendar and task list IDs.
        calendar_transport: CalendarSeedTransport implementation.
        tasks_transport: TasksSeedTransport implementation.
        mode: DemoOperationMode (INSPECT, SETUP, VERIFY, TEARDOWN). Default: INSPECT.
        permit_mutation: Strict boolean. Default: False (DRY_RUN / NO_MUTATION).
        teardown_confirmation: Required confirmation token for TEARDOWN mode mutations.
        event_spec: Optional CanonicalEventSpec; defaults to canonical demo event if None.
        provenance: EvidenceProvenance. Default: FIXTURE.

    Returns:
        Sanitized DemoToolingResult.
    """
    if not isinstance(scope, DemoResourceScope):
        raise DemoScopeTypeError(
            f"scope must be a DemoResourceScope instance, got {type(scope).__name__}"
        )

    if permit_mutation is not True and permit_mutation is not False:
        raise ValueError("permit_mutation must be a strict boolean (True or False)")

    # Provenance capability check
    if (
        isinstance(calendar_transport, FakeCalendarSeedTransport)
        and provenance == EvidenceProvenance.LIVE_GOOGLE
    ):
        raise DemoSeedingProvenanceError("Fake transport cannot claim LIVE_GOOGLE provenance.")

    if event_spec is None:
        event_spec = create_canonical_event_spec()

    # 1. Target scope validation
    cal_id_lower = scope.calendar_id.strip().lower()
    if cal_id_lower in FORBIDDEN_CALENDAR_IDS:
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details="Forbidden calendar ID; primary/default substitution rejected fail-closed.",
            error_message="WRONG_TARGET_CALENDAR",
        )

    tl_id_lower = scope.task_list_id.strip().lower()
    if tl_id_lower in FORBIDDEN_TASK_LIST_IDS:
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details="Forbidden task list ID; default substitution rejected fail-closed.",
            error_message="WRONG_TARGET_TASK_LIST",
        )

    # 2. Container preflight validation
    try:
        cal_meta = calendar_transport.get_calendar(scope.calendar_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Provider calendar preflight probe failed: {sanitized}",
            error_message=sanitized,
        )

    if cal_meta is None:
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                "Dedicated demo calendar does not exist on provider. "
                "Container creation is forbidden."
            ),
            error_message="DEMO_CALENDAR_NOT_FOUND",
        )

    if cal_meta.get("primary") is True:
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details="Primary calendar detected on provider; substitution rejected.",
            error_message="WRONG_TARGET_CALENDAR",
        )

    if cal_meta.get("summary") != DEFAULT_DEMO_CALENDAR_TITLE:
        cal_summary = cal_meta.get("summary")
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Demo calendar summary '{cal_summary}' does not match "
                f"expected '{DEFAULT_DEMO_CALENDAR_TITLE}'."
            ),
            error_message="WRONG_TARGET_CALENDAR",
        )

    try:
        tl_meta = tasks_transport.get_task_list(scope.task_list_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Provider task list preflight probe failed: {sanitized}",
            error_message=sanitized,
        )

    if tl_meta is None:
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                "Dedicated demo task list does not exist on provider. "
                "Container creation is forbidden."
            ),
            error_message="DEMO_TASK_LIST_NOT_FOUND",
        )

    if tl_meta.get("title") != DEFAULT_DEMO_TASK_LIST_TITLE:
        tl_title = tl_meta.get("title")
        return DemoToolingResult(
            mode=mode,
            status=DemoToolingStatus.WRONG_TARGET_REJECTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Demo task list title '{tl_title}' does not match "
                f"expected '{DEFAULT_DEMO_TASK_LIST_TITLE}'."
            ),
            error_message="WRONG_TARGET_TASK_LIST",
        )

    # 3. Branch by operation mode
    if mode == DemoOperationMode.INSPECT:
        return _execute_inspect(scope, calendar_transport, tasks_transport, event_spec, provenance)
    if mode == DemoOperationMode.SETUP:
        return _execute_setup(
            scope, calendar_transport, tasks_transport, event_spec, permit_mutation, provenance
        )
    if mode == DemoOperationMode.VERIFY:
        return _execute_verify(scope, calendar_transport, tasks_transport, event_spec, provenance)
    if mode == DemoOperationMode.TEARDOWN:
        return _execute_teardown(
            scope,
            calendar_transport,
            tasks_transport,
            event_spec,
            permit_mutation,
            teardown_confirmation,
            provenance,
        )

    raise ValueError(f"Unsupported operation mode: {mode}")


# ===========================================================================
# Internal Mode Handlers
# ===========================================================================


def _execute_inspect(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    event_spec: CanonicalEventSpec,
    provenance: EvidenceProvenance,
) -> DemoToolingResult:
    """Inspect dedicated demo resources without mutation (0 writes)."""
    try:
        events = calendar_transport.list_events_by_title(scope.calendar_id, event_spec.title)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.INSPECT,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Calendar event listing failed: {sanitized}",
            error_message=sanitized,
        )

    try:
        tasks = tasks_transport.list_tasks(scope.task_list_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.INSPECT,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Task listing failed: {sanitized}",
            error_message=sanitized,
        )

    prep_tasks = [
        t
        for t in tasks
        if t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
    ]

    event_notes = (
        f"Found {len(events)} event(s) titled '{event_spec.title}'."
        if events
        else f"Canonical event '{event_spec.title}' is ABSENT."
    )
    task_notes = (
        f"Found {len(tasks)} total task(s); prep task '{DEFAULT_PREPARATION_TASK_TITLE}' is "
        f"{'PRESENT (' + str(len(prep_tasks)) + ')' if prep_tasks else 'ABSENT (clean)'}."
    )

    details = (
        f"Inspection complete. 0 writes performed. Calendar: {event_notes} Tasks: {task_notes}"
    )

    return DemoToolingResult(
        mode=DemoOperationMode.INSPECT,
        status=DemoToolingStatus.INSPECTED,
        provenance=provenance,
        calendar_id=scope.calendar_id,
        task_list_id=scope.task_list_id,
        writes_performed=0,
        readback_verified=False,
        is_success=True,
        details=details,
        items_inspected=len(events) + len(tasks),
        items_modified=0,
        items_deleted=0,
    )


def _execute_setup(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    event_spec: CanonicalEventSpec,
    permit_mutation: bool,
    provenance: EvidenceProvenance,
) -> DemoToolingResult:
    """Idempotently seed or reset canonical initial event state."""
    seed_res = seed_canonical_demo_resources(
        scope=scope,
        calendar_transport=calendar_transport,
        tasks_transport=tasks_transport,
        event_spec=event_spec,
        permit_mutation=permit_mutation,
        provenance=provenance,
    )

    if seed_res.status == SeedOperationStatus.VERIFIED_EXISTING:
        return DemoToolingResult(
            mode=DemoOperationMode.SETUP,
            status=DemoToolingStatus.VERIFIED_EXISTING,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=True,
            is_success=True,
            details=seed_res.details,
            items_inspected=1,
            items_modified=0,
            items_deleted=0,
        )

    if seed_res.status == SeedOperationStatus.MUTATION_EXECUTED:
        return DemoToolingResult(
            mode=DemoOperationMode.SETUP,
            status=DemoToolingStatus.MUTATION_EXECUTED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=seed_res.writes_performed,
            readback_verified=seed_res.readback_verified,
            is_success=seed_res.readback_verified,
            details=seed_res.details,
            items_inspected=1,
            items_modified=seed_res.writes_performed,
            items_deleted=0,
        )

    if seed_res.status == SeedOperationStatus.BLOCKED_UNAUTHORIZED:
        status = (
            DemoToolingStatus.BLOCKED_DRY_RUN
            if not permit_mutation
            else DemoToolingStatus.BLOCKED_UNAUTHORIZED
        )
        return DemoToolingResult(
            mode=DemoOperationMode.SETUP,
            status=status,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                "DRY RUN: Mutation required to reach canonical state, "
                f"but permit_mutation=False (0 writes performed). {seed_res.details}"
            ),
            error_message="MUTATION_UNAUTHORIZED",
            items_inspected=1,
        )

    # All other states (contradiction, verification failure, preflight blocked, etc.)
    failed_status = (
        DemoToolingStatus.VERIFICATION_FAILED
        if "VERIFICATION" in seed_res.status.value
        else DemoToolingStatus.CONTRADICTORY_STATE
    )
    return DemoToolingResult(
        mode=DemoOperationMode.SETUP,
        status=failed_status,
        provenance=provenance,
        calendar_id=scope.calendar_id,
        task_list_id=scope.task_list_id,
        writes_performed=seed_res.writes_performed,
        readback_verified=seed_res.readback_verified,
        is_success=False,
        details=seed_res.details,
        error_message=seed_res.error_message,
        items_inspected=1,
    )


def _execute_verify(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    event_spec: CanonicalEventSpec,
    provenance: EvidenceProvenance,
) -> DemoToolingResult:
    """Verify through independent read-back whether resources satisfy canonical pre-state."""
    # 1. Inspect tasks: preparation task must be absent
    try:
        tasks = tasks_transport.list_tasks(scope.task_list_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.VERIFY,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Task listing failed: {sanitized}",
            error_message=sanitized,
        )

    matching_tasks = [
        t
        for t in tasks
        if t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
    ]
    if matching_tasks:
        return DemoToolingResult(
            mode=DemoOperationMode.VERIFY,
            status=DemoToolingStatus.CONTRADICTORY_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Contradictory state: task '{DEFAULT_PREPARATION_TASK_TITLE}' is present on "
                f"demo task list ({len(matching_tasks)} found); clean pre-state required."
            ),
            error_message="PREPARATION_TASK_PRESENT",
            items_inspected=len(tasks),
        )

    # 2. Inspect events: exactly one confirmed event at canonical start time
    try:
        events = calendar_transport.list_events_by_title(scope.calendar_id, event_spec.title)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.VERIFY,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Calendar listing failed: {sanitized}",
            error_message=sanitized,
        )

    if not events:
        return DemoToolingResult(
            mode=DemoOperationMode.VERIFY,
            status=DemoToolingStatus.CONTRADICTORY_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Canonical demo event '{event_spec.title}' is ABSENT from demo calendar.",
            error_message="CANONICAL_EVENT_ABSENT",
            items_inspected=len(tasks),
        )

    if len(events) > 1:
        return DemoToolingResult(
            mode=DemoOperationMode.VERIFY,
            status=DemoToolingStatus.CONTRADICTORY_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Duplicate contradiction: found {len(events)} events titled '{event_spec.title}'."
            ),
            error_message="DUPLICATE_EVENTS_FOUND",
            items_inspected=len(events) + len(tasks),
        )

    # Independent read-back of single event
    candidate = events[0]
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
        found_start = getattr(readback, "start_time", "None")
        return DemoToolingResult(
            mode=DemoOperationMode.VERIFY,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Event '{event_spec.title}' does not match canonical start time "
                f"(found {found_start}, expected {event_spec.start_time})."
            ),
            error_message="EVENT_READBACK_MISMATCH",
            items_inspected=len(events) + len(tasks),
        )

    return DemoToolingResult(
        mode=DemoOperationMode.VERIFY,
        status=DemoToolingStatus.VERIFIED_READY,
        provenance=provenance,
        calendar_id=scope.calendar_id,
        task_list_id=scope.task_list_id,
        writes_performed=0,
        readback_verified=True,
        is_success=True,
        details=(
            f"Pre-state verified: canonical event '{event_spec.title}' confirmed at "
            f"{readback.start_time}; prep task '{DEFAULT_PREPARATION_TASK_TITLE}' absent; "
            "0 writes performed."
        ),
        items_inspected=len(events) + len(tasks),
    )


def _execute_teardown(
    scope: DemoResourceScope,
    calendar_transport: CalendarSeedTransport,
    tasks_transport: TasksSeedTransport,
    event_spec: CanonicalEventSpec,
    permit_mutation: bool,
    teardown_confirmation: str | None,
    provenance: EvidenceProvenance,
) -> DemoToolingResult:
    """Safely tear down disposable demo run artifacts with exact confirmation."""
    # 1. Discover demo artifacts to clean up
    # Task list: tasks titled DEFAULT_PREPARATION_TASK_TITLE
    try:
        tasks = tasks_transport.list_tasks(scope.task_list_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Task listing failed during teardown scan: {sanitized}",
            error_message=sanitized,
        )

    tasks_to_delete = [
        t
        for t in tasks
        if t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
    ]

    # Calendar: duplicate events titled event_spec.title
    try:
        events = calendar_transport.list_events_by_title(scope.calendar_id, event_spec.title)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.BLOCKED_PREFLIGHT,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=f"Calendar listing failed during teardown scan: {sanitized}",
            error_message=sanitized,
        )

    # If there are duplicates, extra events should be removed
    extra_events_to_delete = events[1:] if len(events) > 1 else []

    total_items_to_clean = len(tasks_to_delete) + len(extra_events_to_delete)

    # If already completely clean:
    if total_items_to_clean == 0:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.ALREADY_CLEAN,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=True,
            is_success=True,
            details=(
                "Demo resources are already clean (0 matching demo artifacts to remove). "
                "0 writes performed."
            ),
            items_inspected=len(tasks) + len(events),
            items_modified=0,
            items_deleted=0,
        )

    # 2. Check mutation authorization (default is DRY RUN)
    if not permit_mutation:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.BLOCKED_DRY_RUN,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"DRY RUN: Found {len(tasks_to_delete)} demo task(s) and "
                f"{len(extra_events_to_delete)} extra event(s) to clean. "
                "No mutations executed (permit_mutation=False, 0 writes performed)."
            ),
            error_message="MUTATION_UNAUTHORIZED",
            items_inspected=len(tasks) + len(events),
        )

    # 3. Check exact target-bound confirmation token
    # Requires CANONICAL_TEARDOWN_CONFIRMATION or exact scope confirmation string
    valid_confirmations = {
        CANONICAL_TEARDOWN_CONFIRMATION,
        f"{CANONICAL_TEARDOWN_CONFIRMATION}:{scope.calendar_id}:{scope.task_list_id}",
    }
    if not teardown_confirmation or teardown_confirmation.strip() not in valid_confirmations:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.CONFIRMATION_REQUIRED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                "Teardown mutation requires exact confirmation token ('CONFIRM_TEARDOWN'). "
                "Execution halted fail-closed (0 writes performed)."
            ),
            error_message="CONFIRMATION_REQUIRED",
            items_inspected=len(tasks) + len(events),
        )

    # 4. Execute deletion of demo tasks
    writes_count = 0
    deleted_tasks_count = 0
    for task in tasks_to_delete:
        task_id = task.get("id")
        if task_id:
            tasks_transport.delete_task(scope.task_list_id, task_id)
            writes_count += 1
            deleted_tasks_count += 1

    # 5. Execute deletion of extra duplicate events
    deleted_events_count = 0
    for ev in extra_events_to_delete:
        calendar_transport.delete_event(scope.calendar_id, ev.id)
        writes_count += 1
        deleted_events_count += 1

    # 6. INDEPENDENT READ-BACK VERIFICATION
    # Verify tasks are no longer present on task list
    try:
        post_tasks = tasks_transport.list_tasks(scope.task_list_id)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details=f"Read-back task verification failed after teardown writes: {sanitized}",
            error_message="READBACK_PROBE_FAILED",
            items_deleted=deleted_tasks_count + deleted_events_count,
        )

    still_present_tasks = [
        t
        for t in post_tasks
        if t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
    ]
    if still_present_tasks:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details="Teardown read-back mismatch: demo prep task is still observed on provider.",
            error_message="TEARDOWN_READBACK_TASK_STILL_PRESENT",
            items_deleted=deleted_tasks_count + deleted_events_count,
        )

    # Verify duplicate events are no longer present
    try:
        post_events = calendar_transport.list_events_by_title(scope.calendar_id, event_spec.title)
    except Exception as exc:
        sanitized = sanitize_error_message(exc)
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details=f"Read-back calendar verification failed after teardown writes: {sanitized}",
            error_message="READBACK_PROBE_FAILED",
            items_deleted=deleted_tasks_count + deleted_events_count,
        )

    if len(post_events) > 1:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details="Teardown read-back mismatch: duplicate events still observed on provider.",
            error_message="TEARDOWN_READBACK_DUPLICATE_EVENTS_REMAIN",
            items_deleted=deleted_tasks_count + deleted_events_count,
        )

    return DemoToolingResult(
        mode=DemoOperationMode.TEARDOWN,
        status=DemoToolingStatus.TEARDOWN_COMPLETED,
        provenance=provenance,
        calendar_id=scope.calendar_id,
        task_list_id=scope.task_list_id,
        writes_performed=writes_count,
        readback_verified=True,
        is_success=True,
        details=(
            f"Teardown completed and verified. Deleted {deleted_tasks_count} demo task(s) "
            f"and {deleted_events_count} extra event(s). Writes: {writes_count}."
        ),
        items_inspected=len(tasks) + len(events),
        items_modified=0,
        items_deleted=deleted_tasks_count + deleted_events_count,
    )
