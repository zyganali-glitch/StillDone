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
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from stilldone.adapters.calendar import CalendarTransportEvent
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
from stilldone.redaction import redact_text

logger = logging.getLogger(__name__)

# Canonical confirmation string prefix for teardown
CANONICAL_TEARDOWN_CONFIRMATION: str = "CONFIRM_TEARDOWN"


def make_scope_bound_teardown_confirmation(calendar_id: str, task_list_id: str) -> str:
    """Format required target-bound confirmation token for teardown mutations."""
    return f"{CANONICAL_TEARDOWN_CONFIRMATION}:{calendar_id.strip()}:{task_list_id.strip()}"


def sanitize_tooling_text(text: str | None) -> str:
    """Sanitize provider-supplied text, removing emails, tokens, IDs, and filesystem paths."""
    if not text:
        return ""
    # 1. Redact standard secrets, tokens, emails, identifiers via StillDone redaction engine
    redacted = redact_text(text)
    # 2. Redact Windows absolute filesystem paths (e.g. C:\Users\... or C:/...)
    redacted = re.sub(r"[a-zA-Z]:[\\/][^\s\"'<>|]+", "[REDACTED_PATH]", redacted)
    # 3. Redact POSIX absolute filesystem paths
    redacted = re.sub(
        r"/(?:Users|home|root|var|tmp|etc|opt)/[^\s\"'<>|]+", "[REDACTED_PATH]", redacted
    )
    return redacted


# ===========================================================================
# Ownership & Provenance Manifest
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DemoResourceOwnershipRecord:
    """Proven ownership record for a disposable demo resource.

    Binds a specific resource ID to its dedicated parent scope, resource kind,
    and verified provenance evidence.
    """

    resource_id: str
    resource_kind: str  # "task" or "event"
    scope_id: str  # matches DemoResourceScope.task_list_id or calendar_id
    provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE
    created_by: str = "StillDone:DemoTooling"
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class DemoArtifactManifest:
    """Explicit ownership and provenance manifest for disposable demo artifacts.

    Guarantees:
    - Destructive operations strictly require proven ownership of specific resource IDs.
    - Matching title or container display name alone NEVER confers deletion authority.
    - Preserves unrelated user-created tasks or calendar events sharing the same title.
    - Bound to dedicated demo scope (calendar_id and task_list_id).
    - CLI-provided IDs alone never confer deletion authority on live transports.
    """

    calendar_id: str | None = None
    task_list_id: str | None = None
    owned_task_ids: frozenset[str] = field(default_factory=frozenset)
    owned_event_ids: frozenset[str] = field(default_factory=frozenset)
    canonical_event_id: str | None = None
    records: tuple[DemoResourceOwnershipRecord, ...] = field(default_factory=tuple)
    is_cli_untrusted: bool = False

    def __init__(
        self,
        owned_task_ids: Sequence[str] | set[str] | frozenset[str] | None = None,
        owned_event_ids: Sequence[str] | set[str] | frozenset[str] | None = None,
        canonical_event_id: str | None = None,
        scope: DemoResourceScope | None = None,
        records: Sequence[DemoResourceOwnershipRecord] | None = None,
        is_cli_untrusted: bool = False,
        calendar_id: str | None = None,
        task_list_id: str | None = None,
    ) -> None:
        rec_list = list(records) if records is not None else []
        task_ids = set(owned_task_ids) if owned_task_ids is not None else set()
        event_ids = set(owned_event_ids) if owned_event_ids is not None else set()

        # If records provided, extract resource IDs
        for r in rec_list:
            if r.resource_kind.lower() == "task":
                task_ids.add(r.resource_id)
            elif r.resource_kind.lower() == "event":
                event_ids.add(r.resource_id)

        cal_id = calendar_id if calendar_id is not None else (scope.calendar_id if scope else None)
        tl_id = (
            task_list_id if task_list_id is not None else (scope.task_list_id if scope else None)
        )

        object.__setattr__(self, "calendar_id", cal_id)
        object.__setattr__(self, "task_list_id", tl_id)
        object.__setattr__(self, "owned_task_ids", frozenset(task_ids))
        object.__setattr__(self, "owned_event_ids", frozenset(event_ids))
        object.__setattr__(self, "canonical_event_id", canonical_event_id)
        object.__setattr__(self, "records", tuple(rec_list))
        object.__setattr__(self, "is_cli_untrusted", is_cli_untrusted)


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
    - Details and error messages are rigorously sanitized against emails, tokens, and paths.
    - Accurately tracks writes_performed and readback_verified.
    - Distinguishes unresolved deletion attempts as AMBIGUOUS/UNKNOWN rather than 0 writes.
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
    is_ambiguous_outcome: bool = False
    unresolved_attempts: int = 0
    known_resource_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        sanitized_details = sanitize_tooling_text(self.details)
        if self.calendar_id and self.calendar_id in sanitized_details:
            sanitized_details = sanitized_details.replace(self.calendar_id, "[REDACTED]")
        if self.task_list_id and self.task_list_id in sanitized_details:
            sanitized_details = sanitized_details.replace(self.task_list_id, "[REDACTED]")
        for rid in self.known_resource_ids:
            if rid and rid in sanitized_details:
                sanitized_details = sanitized_details.replace(rid, "[REDACTED]")
        object.__setattr__(self, "details", sanitized_details)

        if self.error_message:
            sanitized_err = sanitize_tooling_text(self.error_message)
            if self.calendar_id and self.calendar_id in sanitized_err:
                sanitized_err = sanitized_err.replace(self.calendar_id, "[REDACTED]")
            if self.task_list_id and self.task_list_id in sanitized_err:
                sanitized_err = sanitized_err.replace(self.task_list_id, "[REDACTED]")
            for rid in self.known_resource_ids:
                if rid and rid in sanitized_err:
                    sanitized_err = sanitized_err.replace(rid, "[REDACTED]")
            object.__setattr__(self, "error_message", sanitized_err)

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
            f"items_deleted={self.items_deleted}, "
            f"is_ambiguous_outcome={self.is_ambiguous_outcome})"
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
            "is_ambiguous_outcome": self.is_ambiguous_outcome,
            "unresolved_attempts": self.unresolved_attempts,
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
    manifest: DemoArtifactManifest | None = None,
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
            manifest=manifest,
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
    manifest: DemoArtifactManifest | None = None,
) -> DemoToolingResult:
    """Safely tear down disposable demo run artifacts with exact confirmation and ownership."""
    # 0. Scope & Provenance Authority Checks (B1)
    if manifest is not None:
        if manifest.calendar_id and manifest.calendar_id != scope.calendar_id:
            return DemoToolingResult(
                mode=DemoOperationMode.TEARDOWN,
                status=DemoToolingStatus.WRONG_TARGET_REJECTED,
                provenance=provenance,
                calendar_id=scope.calendar_id,
                task_list_id=scope.task_list_id,
                writes_performed=0,
                readback_verified=False,
                is_success=False,
                details=(
                    "Manifest calendar scope does not match target demo scope; "
                    "rejected fail-closed."
                ),
                error_message="MISMATCHED_MANIFEST_SCOPE",
            )
        if manifest.task_list_id and manifest.task_list_id != scope.task_list_id:
            return DemoToolingResult(
                mode=DemoOperationMode.TEARDOWN,
                status=DemoToolingStatus.WRONG_TARGET_REJECTED,
                provenance=provenance,
                calendar_id=scope.calendar_id,
                task_list_id=scope.task_list_id,
                writes_performed=0,
                readback_verified=False,
                is_success=False,
                details=(
                    "Manifest task list scope does not match target demo scope; "
                    "rejected fail-closed."
                ),
                error_message="MISMATCHED_MANIFEST_SCOPE",
            )
        if manifest.is_cli_untrusted and provenance in (
            EvidenceProvenance.LIVE_GOOGLE,
            EvidenceProvenance.LIVE_AWS,
            EvidenceProvenance.LIVE_EXTERNAL,
        ):
            return DemoToolingResult(
                mode=DemoOperationMode.TEARDOWN,
                status=DemoToolingStatus.BLOCKED_UNAUTHORIZED,
                provenance=provenance,
                calendar_id=scope.calendar_id,
                task_list_id=scope.task_list_id,
                writes_performed=0,
                readback_verified=False,
                is_success=False,
                details=(
                    "CLI-provided IDs alone cannot authorize destructive deletion "
                    "on live transport."
                ),
                error_message="CLI_OWNERSHIP_UNAUTHORIZED_FOR_LIVE",
            )

    # 1. Discover demo artifacts to clean up
    # Task list discovery
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

    # Calendar discovery
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

    # Collect known resource IDs to sanitize in all result outputs (B4)
    known_ids: set[str] = set()
    if manifest:
        if manifest.canonical_event_id:
            known_ids.add(manifest.canonical_event_id)
        known_ids.update(manifest.owned_task_ids)
        known_ids.update(manifest.owned_event_ids)
        for r in manifest.records:
            known_ids.add(r.resource_id)
    for t in tasks:
        tid = t.get("id")
        if tid:
            known_ids.add(tid)
    for ev in events:
        known_ids.add(ev.id)

    # 2. Deterministic Canonical Event Selection (do NOT infer canonical event from list ordering)
    canonical_event: CalendarTransportEvent | None = None
    if manifest and manifest.canonical_event_id:
        for ev in events:
            if ev.id == manifest.canonical_event_id:
                if (
                    are_datetimes_equal(ev.start_time, event_spec.start_time)
                    and are_datetimes_equal(ev.end_time, event_spec.end_time)
                    and ev.status == "confirmed"
                    and not ev.all_day
                    and ev.summary == event_spec.title
                ):
                    canonical_event = ev
                break
    else:
        # Search for unique event matching canonical pre-state spec
        matching_spec_events = [
            ev
            for ev in events
            if (
                are_datetimes_equal(ev.start_time, event_spec.start_time)
                and are_datetimes_equal(ev.end_time, event_spec.end_time)
                and ev.status == "confirmed"
                and not ev.all_day
                and ev.summary == event_spec.title
            )
        ]
        if len(matching_spec_events) == 1:
            canonical_event = matching_spec_events[0]
        elif len(matching_spec_events) > 1 and manifest:
            # Disambiguate if extra events are explicitly declared in owned_event_ids
            candidates = [
                ev for ev in matching_spec_events if ev.id not in manifest.owned_event_ids
            ]
            if len(candidates) == 1:
                canonical_event = candidates[0]

    # B2 INVARIANT: Canonical event MUST exist and pass verification.
    # Missing, corrupted, ambiguous, or mismatched canonical event fails closed (0 writes).
    # Missing canonical event CANNOT report ALREADY_CLEAN.
    if canonical_event is None:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.CONTRADICTORY_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                "Canonical demo event could not be deterministically verified on demo calendar."
            ),
            error_message="CANONICAL_EVENT_CORRUPTED_OR_MISSING",
            items_inspected=len(tasks) + len(events),
            known_resource_ids=tuple(known_ids),
        )

    # B1 INVARIANT: Check for contradictory claimed tasks on provider
    # If any task on the provider is claimed by manifest, but its title does not match
    # the StillDone demo prep task, it is an unrelated user task falsely claimed as demo artifact:
    if manifest and manifest.owned_task_ids:
        for claimed_tid in manifest.owned_task_ids:
            found_task = next((t for t in tasks if t.get("id") == claimed_tid), None)
            if found_task is not None and found_task.get("title") != DEFAULT_PREPARATION_TASK_TITLE:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.CONTRADICTORY_STATE,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=0,
                    readback_verified=False,
                    is_success=False,
                    details=(
                        "Claimed owned task does not match StillDone preparation task "
                        "specification; teardown rejected fail-closed."
                    ),
                    error_message="CONTRADICTORY_OWNERSHIP_RECORD",
                    items_inspected=len(tasks) + len(events),
                    known_resource_ids=tuple(known_ids),
                )

    # 3. Candidate Discovery
    tasks_matching_title = [
        t
        for t in tasks
        if t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
    ]
    extra_events = [ev for ev in events if ev.id != canonical_event.id]

    total_candidates = len(tasks_matching_title) + len(extra_events)

    # 4. If already completely clean (with verified canonical event present):
    if total_candidates == 0:
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
                "Demo resources are already clean and in canonical pre-state "
                "(canonical event verified, 0 matching demo artifacts to remove). "
                "0 writes performed."
            ),
            items_inspected=len(tasks) + len(events),
            items_modified=0,
            items_deleted=0,
            known_resource_ids=tuple(known_ids),
        )

    # 5. Check mutation authorization (default is DRY RUN)
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
                f"DRY RUN: Found {len(tasks_matching_title)} demo task(s) and "
                f"{len(extra_events)} extra event(s) to clean. "
                "No mutations executed (permit_mutation=False, 0 writes performed)."
            ),
            error_message="MUTATION_UNAUTHORIZED",
            items_inspected=len(tasks) + len(events),
            known_resource_ids=tuple(known_ids),
        )

    # 6. Exact Target-Bound Confirmation Enforcement
    # Bare 'CONFIRM_TEARDOWN' is strictly rejected; exact scope-bound token mandatory
    expected_confirmation = make_scope_bound_teardown_confirmation(
        scope.calendar_id, scope.task_list_id
    )
    if not teardown_confirmation or teardown_confirmation.strip() != expected_confirmation:
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
                "Teardown mutation requires exact scope-bound confirmation token "
                "('CONFIRM_TEARDOWN:***:***'). "
                "Unbound 'CONFIRM_TEARDOWN' or mismatched scope confirmation is "
                "rejected fail-closed (0 writes performed)."
            ),
            error_message="CONFIRMATION_REQUIRED",
            items_inspected=len(tasks) + len(events),
            known_resource_ids=tuple(known_ids),
        )

    # 7. Deep Ownership & Provenance Verification Before Destructive Writes (B1)
    # A. Validate claimed owned task IDs: must exist on provider and match prep task title
    if manifest and manifest.owned_task_ids:
        for claimed_tid in manifest.owned_task_ids:
            found_task = next((t for t in tasks if t.get("id") == claimed_tid), None)
            if found_task is None:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.CONTRADICTORY_STATE,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=0,
                    readback_verified=False,
                    is_success=False,
                    details=(
                        "Claimed owned task is absent or stale on provider; "
                        "teardown rejected fail-closed."
                    ),
                    error_message="STALE_OR_ABSENT_OWNERSHIP_RECORD",
                    items_inspected=len(tasks) + len(events),
                    known_resource_ids=tuple(known_ids),
                )
            if found_task.get("title") != DEFAULT_PREPARATION_TASK_TITLE:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.CONTRADICTORY_STATE,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=0,
                    readback_verified=False,
                    is_success=False,
                    details=(
                        "Claimed owned task does not match StillDone preparation task "
                        "specification; teardown rejected fail-closed."
                    ),
                    error_message="CONTRADICTORY_OWNERSHIP_RECORD",
                    items_inspected=len(tasks) + len(events),
                    known_resource_ids=tuple(known_ids),
                )

    # B. Validate claimed owned extra event IDs: must exist and not be the canonical event
    if manifest and manifest.owned_event_ids:
        for claimed_eid in manifest.owned_event_ids:
            if claimed_eid == canonical_event.id:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.CONTRADICTORY_STATE,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=0,
                    readback_verified=False,
                    is_success=False,
                    details=(
                        "Claimed owned extra event contradicts canonical event identity; "
                        "teardown rejected fail-closed."
                    ),
                    error_message="CONTRADICTORY_OWNERSHIP_RECORD",
                    items_inspected=len(tasks) + len(events),
                    known_resource_ids=tuple(known_ids),
                )
            found_event = next((e for e in events if e.id == claimed_eid), None)
            if found_event is None:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.CONTRADICTORY_STATE,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=0,
                    readback_verified=False,
                    is_success=False,
                    details=(
                        "Claimed owned event is absent or stale on provider; "
                        "teardown rejected fail-closed."
                    ),
                    error_message="STALE_OR_ABSENT_OWNERSHIP_RECORD",
                    items_inspected=len(tasks) + len(events),
                    known_resource_ids=tuple(known_ids),
                )

    # C. Preserve unowned candidate tasks
    owned_tasks_to_delete: list[dict[str, Any]] = []
    unowned_tasks: list[dict[str, Any]] = []
    for t in tasks_matching_title:
        tid = t.get("id")
        if tid and manifest and tid in manifest.owned_task_ids:
            owned_tasks_to_delete.append(t)
        else:
            unowned_tasks.append(t)

    # If unowned tasks with the demo title exist, preserve them and fail closed (0 writes)
    if unowned_tasks:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.CONTRADICTORY_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Unproven ownership: found {len(unowned_tasks)} task(s) titled "
                f"'{DEFAULT_PREPARATION_TASK_TITLE}' without explicit demo ownership manifest. "
                "Refusing destructive deletion of potential user data (0 writes performed)."
            ),
            error_message="UNPROVEN_RESOURCE_OWNERSHIP",
            items_inspected=len(tasks) + len(events),
            known_resource_ids=tuple(known_ids),
        )

    # D. Preserve unowned extra events
    owned_events_to_delete: list[CalendarTransportEvent] = []
    unowned_extra_events: list[CalendarTransportEvent] = []
    for ev in extra_events:
        if manifest and ev.id in manifest.owned_event_ids:
            owned_events_to_delete.append(ev)
        else:
            unowned_extra_events.append(ev)

    # If unowned events with the demo title exist, preserve them and fail closed (0 writes)
    if unowned_extra_events:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.CONTRADICTORY_STATE,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=0,
            readback_verified=False,
            is_success=False,
            details=(
                f"Unproven ownership: found {len(unowned_extra_events)} extra event(s) sharing "
                "demo title without explicit demo ownership manifest. Refusing destructive "
                "deletion of potential user data (0 writes performed)."
            ),
            error_message="UNPROVEN_RESOURCE_OWNERSHIP",
            items_inspected=len(tasks) + len(events),
            known_resource_ids=tuple(known_ids),
        )

    # 8. Execute Deletions with Bounded Ambiguity Handling (B3 & B4)
    writes_count = 0
    deleted_task_ids: list[str] = []
    deleted_event_ids: list[str] = []

    # A: Delete owned demo tasks
    for task in owned_tasks_to_delete:
        task_id = task.get("id")
        if not task_id:
            continue
        try:
            tasks_transport.delete_task(scope.task_list_id, task_id)
            writes_count += 1
            deleted_task_ids.append(task_id)
        except Exception as exc:
            # Ambiguous write probe: did delete commit despite exception/timeout?
            probe_failed = False
            try:
                post_probe = tasks_transport.list_tasks(scope.task_list_id)
                if not any(t.get("id") == task_id for t in post_probe):
                    writes_count += 1
                    deleted_task_ids.append(task_id)
            except Exception:
                probe_failed = True

            if probe_failed:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.VERIFICATION_FAILED,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=writes_count,
                    readback_verified=False,
                    is_success=False,
                    is_ambiguous_outcome=True,
                    unresolved_attempts=1,
                    details=(
                        "Teardown halted: delete outcome is AMBIGUOUS/UNKNOWN "
                        f"(acknowledgment lost and read-back probe unavailable; "
                        f"{writes_count} confirmed write(s)). "
                        "Halting without blind retry."
                    ),
                    error_message="AMBIGUOUS_DELETION_OUTCOME",
                    items_inspected=len(tasks) + len(events),
                    items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
                    known_resource_ids=tuple(known_ids),
                )
            else:
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
                    is_ambiguous_outcome=False,
                    details=(
                        "Teardown halted after task deletion failure "
                        f"({writes_count} confirmed write(s) performed): {sanitized}"
                    ),
                    error_message="PARTIAL_MUTATION_FAILURE",
                    items_inspected=len(tasks) + len(events),
                    items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
                    known_resource_ids=tuple(known_ids),
                )

    # B: Delete owned duplicate events
    for ev in owned_events_to_delete:
        try:
            calendar_transport.delete_event(scope.calendar_id, ev.id)
            writes_count += 1
            deleted_event_ids.append(ev.id)
        except Exception as exc:
            # Ambiguous write probe: did delete commit despite exception/timeout?
            probe_failed = False
            try:
                post_ev = calendar_transport.get_event(scope.calendar_id, ev.id)
                if post_ev is None or post_ev.status == "cancelled":
                    writes_count += 1
                    deleted_event_ids.append(ev.id)
            except Exception:
                probe_failed = True

            if probe_failed:
                return DemoToolingResult(
                    mode=DemoOperationMode.TEARDOWN,
                    status=DemoToolingStatus.VERIFICATION_FAILED,
                    provenance=provenance,
                    calendar_id=scope.calendar_id,
                    task_list_id=scope.task_list_id,
                    writes_performed=writes_count,
                    readback_verified=False,
                    is_success=False,
                    is_ambiguous_outcome=True,
                    unresolved_attempts=1,
                    details=(
                        "Teardown halted: delete outcome is AMBIGUOUS/UNKNOWN "
                        f"(acknowledgment lost and read-back probe unavailable; "
                        f"{writes_count} confirmed write(s)). "
                        "Halting without blind retry."
                    ),
                    error_message="AMBIGUOUS_DELETION_OUTCOME",
                    items_inspected=len(tasks) + len(events),
                    items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
                    known_resource_ids=tuple(known_ids),
                )
            else:
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
                    is_ambiguous_outcome=False,
                    details=(
                        "Teardown halted after event deletion failure "
                        f"({writes_count} confirmed write(s) performed): {sanitized}"
                    ),
                    error_message="PARTIAL_MUTATION_FAILURE",
                    items_inspected=len(tasks) + len(events),
                    items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
                    known_resource_ids=tuple(known_ids),
                )

    # 9. INDEPENDENT READ-BACK VERIFICATION (B2)
    # Verify task list state: deleted tasks absent, prep task absent
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
            items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
            known_resource_ids=tuple(known_ids),
        )

    if any(t.get("id") in deleted_task_ids for t in post_tasks) or any(
        t.get("title") == DEFAULT_PREPARATION_TASK_TITLE and t.get("status") != "completed"
        for t in post_tasks
    ):
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
            items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
            known_resource_ids=tuple(known_ids),
        )

    # Verify calendar state: deleted events absent, canonical event intact, exactly 1 matching event
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
            items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
            known_resource_ids=tuple(known_ids),
        )

    if any(e.id in deleted_event_ids for e in post_events):
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details=(
                "Teardown read-back mismatch: deleted duplicate event is still "
                "observed on provider."
            ),
            error_message="TEARDOWN_READBACK_DUPLICATE_EVENTS_REMAIN",
            items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
            known_resource_ids=tuple(known_ids),
        )

    if len(post_events) != 1:
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details=(
                "Teardown read-back mismatch: expected exactly 1 canonical event, "
                f"found {len(post_events)}."
            ),
            error_message="TEARDOWN_READBACK_COUNT_MISMATCH",
            items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
            known_resource_ids=tuple(known_ids),
        )

    remaining_ev = post_events[0]
    if (
        remaining_ev.id != canonical_event.id
        or not are_datetimes_equal(remaining_ev.start_time, event_spec.start_time)
        or not are_datetimes_equal(remaining_ev.end_time, event_spec.end_time)
        or remaining_ev.status != "confirmed"
        or remaining_ev.all_day
        or remaining_ev.summary != event_spec.title
    ):
        return DemoToolingResult(
            mode=DemoOperationMode.TEARDOWN,
            status=DemoToolingStatus.VERIFICATION_FAILED,
            provenance=provenance,
            calendar_id=scope.calendar_id,
            task_list_id=scope.task_list_id,
            writes_performed=writes_count,
            readback_verified=False,
            is_success=False,
            details="Teardown read-back mismatch: remaining event does not match canonical spec.",
            error_message="TEARDOWN_READBACK_CANONICAL_EVENT_INVALID",
            items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
            known_resource_ids=tuple(known_ids),
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
            f"Teardown completed and verified. Deleted {len(deleted_task_ids)} demo task(s) "
            f"and {len(deleted_event_ids)} duplicate event(s). Canonical event verified."
        ),
        items_inspected=len(tasks) + len(events),
        items_modified=0,
        items_deleted=len(deleted_task_ids) + len(deleted_event_ids),
        known_resource_ids=tuple(known_ids),
    )
