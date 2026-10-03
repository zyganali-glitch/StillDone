"""Google Tasks service adapter for StillDone.

Provides bounded, fail-closed integration with Google Tasks API v1:
- Enforces dedicated disposable demo-resource scoping (DemoResourceScope).
- Reuses P-04 action validation (ValidatedActionContract) and authority policy.
- Strictly forbids '@default', default, or fuzzy-matched task list substitution.
- Exact task identity required for reads; title matching as identity is strictly rejected.
- Single top-level task creation in dedicated demo task list; user-unrequested fields forbidden.
- Strict Google Tasks due date normalization: calendar DATE semantics with RFC3339 compatibility;
  discards time component without unexpected timezone-induced date shifting.
- Pluggable transport boundary (TaskTransport Protocol) supporting official
  Google API client or deterministic in-memory fakes.
- Minimizes persisted data; strips unrelated provider fields.
- Provider execution success does NOT imply VERIFIED or READY.
- Zero secrets, tokens, or external IDs leaked into str/repr/logs.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from stilldone.action_policy import (
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.authority_policy import (
    AuthorityDecisionStatus,
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
)
from stilldone.domain.authority import ApprovalGrant
from stilldone.redaction import redact_text

logger = logging.getLogger(__name__)

# ===========================================================================
# Canonical Constants
# ===========================================================================

CANONICAL_TASKS_SYSTEM = "google_tasks"
CANONICAL_TASK_RESOURCE_KIND = ResourceKind.TASK
CANONICAL_TASK_LIST_RESOURCE_KIND = ResourceKind.TASK_LIST
FORBIDDEN_TASK_LIST_IDS = frozenset({"@default", "default", "primary"})

# ===========================================================================
# Adapter Exception Hierarchy
# ===========================================================================


class TaskAdapterError(Exception):
    """Base exception for all Task adapter operations."""


class TaskScopeError(TaskAdapterError, ValueError):
    """Raised when task list scope configuration violates StillDone isolation rules."""


class TaskTargetError(TaskAdapterError, ValueError):
    """Raised when an action target identity or parameters violate Tasks requirements."""


class TaskDueFormatError(TaskTargetError):
    """Raised when a task due date string is malformed, invalid, or impossible."""


class TaskTransportError(TaskAdapterError):
    """Base exception for transport/network/API failures communicating with Google Tasks."""

    def __init__(
        self,
        message: str = "Tasks transport error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class TaskNotFoundError(TaskTransportError):
    """Raised when the requested task does not exist on the specified task list."""

    def __init__(
        self,
        message: str = "Task not found",
        status_code: int | None = 404,
    ) -> None:
        super().__init__(message, status_code=status_code)


class TaskAuthenticationError(TaskTransportError):
    """Raised when credentials or OAuth tokens are rejected by Google Tasks APIs."""

    def __init__(
        self,
        message: str = "Google Tasks authentication/authorization error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)


class TaskRateLimitError(TaskTransportError):
    """Raised when Google Tasks rate limits (HTTP 429) are encountered."""

    def __init__(
        self,
        message: str = "Google Tasks rate limit exceeded",
        status_code: int | None = 429,
    ) -> None:
        super().__init__(message, status_code=status_code)


class TaskApiError(TaskTransportError):
    """Raised when Google Tasks API returns an unhandled error response."""

    def __init__(
        self,
        message: str = "Google Tasks API error",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)


def _sanitize_tasks_transport_error(exc: Exception) -> str:
    """Map transport/provider exceptions to bounded sanitized error messages.

    Guarantees that raw provider error payloads, URLs, tokens, task list IDs,
    task IDs, and private details are never exposed in error messages.
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

    if isinstance(exc, TaskAuthenticationError):
        msg = f"Tasks authentication/authorization failed{code_suffix}"
    elif isinstance(exc, TaskRateLimitError):
        msg = f"Tasks rate limit exceeded{code_suffix}"
    elif isinstance(exc, TaskNotFoundError):
        msg = f"Task not found{code_suffix}"
    elif isinstance(exc, TaskApiError):
        msg = f"Tasks provider API error{code_suffix}"
    elif isinstance(exc, TaskTransportError):
        msg = f"Tasks provider transport error{code_suffix}"
    else:
        msg = f"Unexpected tasks transport failure: {type(exc).__name__}"

    return redact_text(msg)


# ===========================================================================
# Google Tasks Due Semantics & Normalization
# ===========================================================================


def normalize_task_due(due: str | None) -> str | None:
    """Normalize a task due date to a canonical YYYY-MM-DD date string.

    Google Tasks accepts RFC3339 timestamps for `due` but discards any time
    component, preserving solely the calendar date. This helper validates
    the input syntax, ensures the date is calendar-valid (rejecting impossible
    dates such as 2026-02-30), and extracts the calendar date directly from
    the date component without unexpected timezone conversions altering the day.

    Args:
        due: Date string in 'YYYY-MM-DD' or RFC3339 format, or None.

    Returns:
        Normalized 'YYYY-MM-DD' string, or None if due is None.

    Raises:
        TaskDueFormatError: If due is malformed, invalid, impossible, or empty.
    """
    if due is None:
        return None
    if not isinstance(due, str) or not due.strip():
        raise TaskDueFormatError("Task due date must be a non-empty string or None")

    raw = due.strip()

    # 1. Bare date format: YYYY-MM-DD
    if re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            d = date.fromisoformat(raw)
            return d.isoformat()
        except ValueError as err:
            raise TaskDueFormatError("Invalid calendar date in due parameter") from err

    # 2. RFC 3339 timestamp format: YYYY-MM-DDTHH:MM:SS...
    # Extracts the calendar date part (raw[:10]) directly to avoid timezone
    # shifting the user-intended calendar date, while verifying timestamp validity.
    iso_pattern = r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:?\d{2})?$"
    if re.fullmatch(iso_pattern, raw):
        date_part = raw[:10]
        try:
            d = date.fromisoformat(date_part)
        except ValueError as err:
            raise TaskDueFormatError("Invalid calendar date in due timestamp") from err

        # Validate time component syntax and values
        norm_time = raw.replace("Z", "+00:00").replace("z", "+00:00")
        try:
            datetime.fromisoformat(norm_time)
        except ValueError as err:
            raise TaskDueFormatError("Invalid RFC3339 time format in due parameter") from err

        return d.isoformat()

    raise TaskDueFormatError("Task due date must be formatted as YYYY-MM-DD or RFC3339 timestamp")


def format_due_for_provider(normalized_due: str | None) -> str | None:
    """Format a normalized YYYY-MM-DD date into Google Tasks RFC3339 provider format."""
    if normalized_due is None:
        return None
    return f"{normalized_due}T00:00:00.000Z"


# ===========================================================================
# Transport Protocol & Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class TaskTransportItem:
    """Raw provider task representation observed at the transport layer."""

    id: str
    title: str
    status: str = "needsAction"
    due: str | None = None
    deleted: bool = False
    hidden: bool = False
    etag: str | None = None
    raw_resource: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"TaskTransportItem(id='***', title='***', "
            f"status='{self.status}', due={'***' if self.due else None}, "
            f"deleted={self.deleted}, hidden={self.hidden})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@runtime_checkable
class TaskTransport(Protocol):
    """Protocol for Google Tasks API transport operations."""

    def get_task(self, task_list_id: str, task_id: str) -> TaskTransportItem | None:
        """Fetch a task by task list ID and task ID.

        Returns TaskTransportItem if found and not deleted, None if not found or deleted.
        """
        ...

    def insert_task(self, task_list_id: str, body: dict[str, Any]) -> TaskTransportItem:
        """Insert a top-level task in the specified task list."""
        ...

    def list_tasks(
        self,
        task_list_id: str,
        show_completed: bool = False,
        show_deleted: bool = False,
        show_hidden: bool = False,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[TaskTransportItem], str | None]:
        """List tasks in the specified task list with optional filtering and pagination."""
        ...


# ===========================================================================
# Fake Transport for Deterministic Testing & CI
# ===========================================================================


class FakeGoogleTasksTransport:
    """In-memory fake implementing TaskTransport for deterministic CI testing.

    Faithfully emulates Google Tasks API v1 behaviors:
    - 404 when task is absent or deleted.
    - ETag generation and tracking.
    - Tracks call counts, last inserted body, and parameters for assertion.
    """

    def __init__(self) -> None:
        # Key: (task_list_id, task_id) -> raw dict
        self._tasks: dict[tuple[str, str], dict[str, Any]] = {}
        # Key: task_list_id -> list of task_ids preserving insertion order
        self._list_order: dict[str, list[str]] = {}
        self.reads_count: int = 0
        self.writes_count: int = 0
        self.list_count: int = 0
        self.last_insert_body: dict[str, Any] | None = None
        self._id_counter: int = 5000
        self._etag_counter: int = 1000

    def seed_task(
        self,
        task_list_id: str,
        task_id: str,
        title: str,
        *,
        due: str | None = None,
        status: str = "needsAction",
        deleted: bool = False,
        hidden: bool = False,
        etag: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> TaskTransportItem:
        """Seed a task in the fake store for test setups."""
        self._etag_counter += 1
        assigned_etag = etag or f'"{self._etag_counter}"'
        raw: dict[str, Any] = {
            "kind": "tasks#task",
            "id": task_id,
            "etag": assigned_etag,
            "title": title,
            "status": status,
            "deleted": deleted,
            "hidden": hidden,
        }
        if due:
            raw["due"] = due
        if extra_fields:
            raw.update(extra_fields)

        self._tasks[(task_list_id, task_id)] = raw
        if task_list_id not in self._list_order:
            self._list_order[task_list_id] = []
        if task_id not in self._list_order[task_list_id]:
            self._list_order[task_list_id].append(task_id)
        return self._to_transport_item(raw)

    def get_task(self, task_list_id: str, task_id: str) -> TaskTransportItem | None:
        """Emulate GET /tasks/v1/lists/{tasklist}/tasks/{task}."""
        self.reads_count += 1
        raw = self._tasks.get((task_list_id, task_id))
        if raw is None:
            return None
        if raw.get("deleted", False):
            return None
        return self._to_transport_item(raw)

    def insert_task(self, task_list_id: str, body: dict[str, Any]) -> TaskTransportItem:
        """Emulate POST /tasks/v1/lists/{tasklist}/tasks."""
        self.writes_count += 1
        self.last_insert_body = copy.deepcopy(body)
        self._id_counter += 1
        self._etag_counter += 1
        task_id = f"task_{self._id_counter}"
        assigned_etag = f'"{self._etag_counter}"'

        raw: dict[str, Any] = {
            "kind": "tasks#task",
            "id": task_id,
            "etag": assigned_etag,
            "title": body.get("title", ""),
            "status": "needsAction",
            "deleted": False,
            "hidden": False,
        }
        if "due" in body and body["due"] is not None:
            raw["due"] = body["due"]

        self._tasks[(task_list_id, task_id)] = raw
        if task_list_id not in self._list_order:
            self._list_order[task_list_id] = []
        self._list_order[task_list_id].append(task_id)
        return self._to_transport_item(raw)

    def list_tasks(
        self,
        task_list_id: str,
        show_completed: bool = False,
        show_deleted: bool = False,
        show_hidden: bool = False,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[TaskTransportItem], str | None]:
        """Emulate GET /tasks/v1/lists/{tasklist}/tasks with filtering and pagination."""
        self.list_count += 1
        task_ids = self._list_order.get(task_list_id, [])
        all_items: list[dict[str, Any]] = []
        for tid in task_ids:
            raw = self._tasks.get((task_list_id, tid))
            if raw is None:
                continue
            if not show_completed and raw.get("status") == "completed":
                continue
            if not show_deleted and raw.get("deleted", False):
                continue
            if not show_hidden and raw.get("hidden", False):
                continue
            all_items.append(raw)

        start_idx = 0
        if page_token is not None:
            try:
                start_idx = int(page_token)
            except ValueError:
                start_idx = 0

        end_idx = start_idx + max_results
        slice_items = all_items[start_idx:end_idx]
        next_token = str(end_idx) if end_idx < len(all_items) else None
        return [self._to_transport_item(x) for x in slice_items], next_token

    @staticmethod
    def _to_transport_item(raw: dict[str, Any]) -> TaskTransportItem:
        return TaskTransportItem(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            status=raw.get("status", "needsAction"),
            due=raw.get("due"),
            deleted=bool(raw.get("deleted", False)),
            hidden=bool(raw.get("hidden", False)),
            etag=raw.get("etag"),
            raw_resource=raw,
        )


# ===========================================================================
# Production Google API Client Transport
# ===========================================================================


class GoogleApiClientTasksTransport:
    """Production Google Tasks transport using official google-api-python-client.

    Wraps the discovery resource returned by `googleapiclient.discovery.build('tasks', 'v1', ...)`.
    Maps raw provider responses to normalized `TaskTransportItem`.
    Converts API and HTTP errors into typed, sanitized `TaskTransportError` hierarchy.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def get_task(self, task_list_id: str, task_id: str) -> TaskTransportItem | None:
        """Fetch a task via Google Tasks API."""
        try:
            req = self._service.tasks().get(tasklist=task_list_id, task=task_id)
            resp = req.execute()
            item = FakeGoogleTasksTransport._to_transport_item(resp)
            if item.deleted:
                return None
            return item
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code == 404:
                return None
            if status_code in (401, 403):
                raise TaskAuthenticationError(
                    f"Google Tasks auth error (status {status_code})",
                    status_code=status_code,
                ) from exc
            if status_code == 429:
                raise TaskRateLimitError(
                    "Google Tasks rate limit exceeded (status 429)",
                    status_code=429,
                ) from exc
            if status_code is not None:
                raise TaskApiError(
                    f"Google Tasks API get_task failed (status {status_code})",
                    status_code=status_code,
                ) from exc
            raise TaskApiError("Google Tasks API get_task failed") from exc

    def insert_task(self, task_list_id: str, body: dict[str, Any]) -> TaskTransportItem:
        """Insert a task via Google Tasks API."""
        try:
            req = self._service.tasks().insert(tasklist=task_list_id, body=body)
            resp = req.execute()
            return FakeGoogleTasksTransport._to_transport_item(resp)
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code in (401, 403):
                raise TaskAuthenticationError(
                    f"Google Tasks auth error (status {status_code})",
                    status_code=status_code,
                ) from exc
            if status_code == 429:
                raise TaskRateLimitError(
                    "Google Tasks rate limit exceeded (status 429)",
                    status_code=429,
                ) from exc
            if status_code is not None:
                raise TaskApiError(
                    f"Google Tasks API insert_task failed (status {status_code})",
                    status_code=status_code,
                ) from exc
            raise TaskApiError("Google Tasks API insert_task failed") from exc

    def list_tasks(
        self,
        task_list_id: str,
        show_completed: bool = False,
        show_deleted: bool = False,
        show_hidden: bool = False,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[TaskTransportItem], str | None]:
        """List tasks via Google Tasks API."""
        try:
            kwargs: dict[str, Any] = {
                "tasklist": task_list_id,
                "showCompleted": show_completed,
                "showDeleted": show_deleted,
                "showHidden": show_hidden,
                "maxResults": max_results,
            }
            if page_token is not None:
                kwargs["pageToken"] = page_token
            req = self._service.tasks().list(**kwargs)
            resp = req.execute()
            items_raw = resp.get("items", [])
            items = [FakeGoogleTasksTransport._to_transport_item(x) for x in items_raw]
            next_token = resp.get("nextPageToken")
            return items, next_token
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code in (401, 403):
                raise TaskAuthenticationError(
                    f"Google Tasks auth error (status {status_code})",
                    status_code=status_code,
                ) from exc
            if status_code == 429:
                raise TaskRateLimitError(
                    "Google Tasks rate limit exceeded (status 429)",
                    status_code=429,
                ) from exc
            if status_code is not None:
                raise TaskApiError(
                    f"Google Tasks API list_tasks failed (status {status_code})",
                    status_code=status_code,
                ) from exc
            raise TaskApiError("Google Tasks API list_tasks failed") from exc


# ===========================================================================
# Normalized Read Models & Adapter
# ===========================================================================


class TaskReadStatus(StrEnum):
    """Result status of a Google Tasks read operation."""

    MATCH = "MATCH"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class TaskObservation:
    """Normalized, sanitized observation of a task from Google Tasks.

    Persists only the narrow bounded fields StillDone requires.
    Sensitive identifiers and private details are masked in repr/str.
    Does NOT retain unrelated raw provider payloads.
    Does NOT assert or imply VERIFIED or READY.
    """

    task_id: str
    task_list_id: str
    title: str
    due: str | None
    status: str
    deleted: bool
    hidden: bool
    etag: str | None
    observed_at: datetime

    def __repr__(self) -> str:
        return (
            f"TaskObservation(task_id='***', task_list_id='***', "
            f"title='***', due={'***' if self.due else None}, "
            f"status='{self.status}', deleted={self.deleted}, hidden={self.hidden})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True, slots=True)
class TaskReadResult:
    """Outcome of a Google Tasks read adapter operation."""

    status: TaskReadStatus
    observation: TaskObservation | None = None
    error_message: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"TaskReadResult(status='{self.status.value}', "
            f"observation={self.observation is not None}, "
            f"error_message={redact_text(self.error_message) if self.error_message else None})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class GoogleTasksReadAdapter:
    """Bounded, fail-closed Google Tasks read adapter.

    Restricted strictly to the dedicated demo task list configured in DemoResourceScope.
    Never falls back to '@default', defaults, or title search.
    """

    def __init__(self, scope: DemoResourceScope, transport: TaskTransport) -> None:
        if not isinstance(scope, DemoResourceScope):
            raise TaskScopeError(
                f"scope must be a DemoResourceScope instance, got {type(scope).__name__}"
            )
        tl_id_lower = scope.task_list_id.strip().lower()
        if tl_id_lower in FORBIDDEN_TASK_LIST_IDS:
            raise TaskScopeError(
                f"Demo task list scope cannot be '{scope.task_list_id}'. "
                "Dedicated demo task list required."
            )
        self._scope = scope
        self._transport = transport

    @property
    def scope(self) -> DemoResourceScope:
        """The bound demo resource scope."""
        return self._scope

    def read_task(
        self,
        action: ValidatedActionContract | ActionContract,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> TaskReadResult:
        """Read an exact task according to the canonical action contract.

        Validates the action contract, enforces demo isolation against the configured scope,
        evaluates authority policy, and retrieves the exact task from the transport.

        Args:
            action: Either a ValidatedActionContract or raw ActionContract.
            approval: Must be None. Any unexpected ApprovalGrant fails closed.
            at: Optional evaluation timestamp.

        Returns:
            TaskReadResult with MATCH, NOT_FOUND, or PROVIDER_ERROR.

        Raises:
            TaskScopeError / TaskOutOfScopeError: If targeting outside demo task list.
            TaskTargetError / ActionPolicyError: If target identity or parameters are malformed.
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
        if validated.action_type != ActionType.TASK_READ:
            raise TaskTargetError(
                f"GoogleTasksReadAdapter handles '{ActionType.TASK_READ.value}', "
                f"got '{validated.action_type.value}'"
            )

        # Step 3: Validate Target System & ResourceKind
        if validated.target.system != CANONICAL_TASKS_SYSTEM:
            raise TaskTargetError(
                f"Target system must be '{CANONICAL_TASKS_SYSTEM}', got '{validated.target.system}'"
            )
        if validated.target.resource_kind != CANONICAL_TASK_RESOURCE_KIND:
            raise TaskTargetError(
                f"Target resource_kind must be '{CANONICAL_TASK_RESOURCE_KIND.value}', "
                f"got '{validated.target.resource_kind.value}'"
            )

        # Step 4: Strict Demo Isolation Check
        # verify_demo_resource_isolation checks target.parent_id == scope.task_list_id
        try:
            verify_demo_resource_isolation(validated, self._scope)
        except DemoIsolationError as exc:
            logger.warning("Tasks demo isolation rejected: %s", type(exc).__name__)
            raise

        # Step 5: Authority policy evaluation
        # TASK_READ is READ_ONLY and requires approval=None
        eval_time = at or datetime.now(UTC)
        decision = evaluate_authority(
            validated,
            approval=approval,
            at=eval_time,
            raise_on_rejection=True,
        )
        if decision.status != AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED:
            raise TaskTargetError("TASK_READ authority evaluation failed")

        evaluation_time = eval_time

        # Step 6: Exact Task Retrieval from Transport
        try:
            item = self._transport.get_task(
                self._scope.task_list_id,
                validated.target.resource_id,
            )
            if item is None or item.deleted:
                return TaskReadResult(
                    status=TaskReadStatus.NOT_FOUND,
                    observed_at=evaluation_time,
                )

            norm_due = normalize_task_due(item.due)
            obs = TaskObservation(
                task_id=item.id,
                task_list_id=self._scope.task_list_id,
                title=item.title,
                due=norm_due,
                status=item.status,
                deleted=item.deleted,
                hidden=item.hidden,
                etag=item.etag,
                observed_at=evaluation_time,
            )
            return TaskReadResult(
                status=TaskReadStatus.MATCH,
                observation=obs,
                observed_at=evaluation_time,
            )
        except Exception as exc:
            error_msg = _sanitize_tasks_transport_error(exc)
            logger.warning("Tasks read provider failure: %s", error_msg)
            return TaskReadResult(
                status=TaskReadStatus.PROVIDER_ERROR,
                error_message=error_msg,
                observed_at=evaluation_time,
            )


# ===========================================================================
# Create Models & Adapter
# ===========================================================================


class TaskCreateStatus(StrEnum):
    """Result status of a Google Tasks create operation."""

    CREATED = "CREATED"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class TaskCreateResult:
    """Outcome of a Google Tasks create adapter operation.

    Execution success alone does NOT confer VERIFIED or READY state.
    """

    status: TaskCreateStatus
    task_id: str | None = None
    task_list_id: str | None = None
    title: str | None = None
    due: str | None = None
    writes_performed: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"TaskCreateResult(status='{self.status.value}', "
            f"task_id='***', task_list_id='***', "
            f"writes_performed={self.writes_performed}, "
            f"error_message={redact_text(self.error_message) if self.error_message else None})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class GoogleTasksCreateAdapter:
    """Bounded, fail-closed Google Tasks create adapter.

    Creates only top-level tasks in the dedicated demo task list configured
    in DemoResourceScope. Enforces strict parameter boundaries (canonical title
    required, optional due date normalized to date semantics).
    Performs exactly one provider create attempt without retries.
    """

    def __init__(self, scope: DemoResourceScope, transport: TaskTransport) -> None:
        if not isinstance(scope, DemoResourceScope):
            raise TaskScopeError(
                f"scope must be a DemoResourceScope instance, got {type(scope).__name__}"
            )
        tl_id_lower = scope.task_list_id.strip().lower()
        if tl_id_lower in FORBIDDEN_TASK_LIST_IDS:
            raise TaskScopeError(
                f"Demo task list scope cannot be '{scope.task_list_id}'. "
                "Dedicated demo task list required."
            )
        self._scope = scope
        self._transport = transport

    @property
    def scope(self) -> DemoResourceScope:
        """The bound demo resource scope."""
        return self._scope

    def create_task(
        self,
        action: ValidatedActionContract | ActionContract,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> TaskCreateResult:
        """Create a top-level task in the dedicated demo task list.

        Args:
            action: Either a ValidatedActionContract or raw ActionContract.
            approval: Must be None (TASK_CREATE is REVERSIBLE_AUTO).
                Unexpected ApprovalGrant fails closed.
            at: Optional execution timestamp.

        Returns:
            TaskCreateResult with CREATED or PROVIDER_ERROR.

        Raises:
            TaskScopeError / TaskOutOfScopeError: If targeting outside demo task list.
            TaskTargetError / ActionPolicyError: If target identity or parameters are malformed.
            TaskDueFormatError: If due date format is invalid.
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
        if validated.action_type != ActionType.TASK_CREATE:
            raise TaskTargetError(
                f"GoogleTasksCreateAdapter handles '{ActionType.TASK_CREATE.value}', "
                f"got '{validated.action_type.value}'"
            )

        # Step 3: Validate Target System & ResourceKind
        if validated.target.system != CANONICAL_TASKS_SYSTEM:
            raise TaskTargetError(
                f"Target system must be '{CANONICAL_TASKS_SYSTEM}', got '{validated.target.system}'"
            )
        if validated.target.resource_kind != CANONICAL_TASK_LIST_RESOURCE_KIND:
            raise TaskTargetError(
                f"Target resource_kind must be '{CANONICAL_TASK_LIST_RESOURCE_KIND.value}', "
                f"got '{validated.target.resource_kind.value}'"
            )

        # Step 4: Strict Demo Isolation Check
        # verify_demo_resource_isolation checks target.resource_id == scope.task_list_id
        # and parent_id is None
        try:
            verify_demo_resource_isolation(validated, self._scope)
        except DemoIsolationError as exc:
            logger.warning("Tasks demo isolation rejected: %s", type(exc).__name__)
            raise

        # Step 5: Authority policy evaluation
        # TASK_CREATE is REVERSIBLE_AUTO and requires approval=None
        eval_time = at or datetime.now(UTC)
        decision = evaluate_authority(
            validated,
            approval=approval,
            at=eval_time,
            raise_on_rejection=True,
        )
        if decision.status != AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED:
            raise TaskTargetError("TASK_CREATE authority evaluation failed")

        # Step 6: Parameter extraction and due normalization
        title_param = validated.parameters["title"]
        if not isinstance(title_param, str):
            raise TaskTargetError("title parameter must be a string")
        title = title_param

        raw_due = validated.parameters.get("due")
        if raw_due is not None and not isinstance(raw_due, str):
            raise TaskDueFormatError("due parameter must be a string or None")
        normalized_due = normalize_task_due(raw_due)

        # Step 7: Construct Provider Request Payload
        # ONLY title and optional provider-formatted due are permitted.
        # No parent, previous, notes, status, links, or hidden metadata.
        payload: dict[str, Any] = {"title": title}
        if normalized_due is not None:
            payload["due"] = format_due_for_provider(normalized_due)

        execution_time = eval_time

        # Step 8: Execute Single Provider Mutation
        try:
            item = self._transport.insert_task(self._scope.task_list_id, payload)
            return TaskCreateResult(
                status=TaskCreateStatus.CREATED,
                task_id=item.id,
                task_list_id=self._scope.task_list_id,
                title=item.title,
                due=normalized_due,
                writes_performed=1,
                created_at=execution_time,
            )
        except Exception as exc:
            error_msg = _sanitize_tasks_transport_error(exc)
            logger.warning("Tasks create provider failure: %s", error_msg)
            return TaskCreateResult(
                status=TaskCreateStatus.PROVIDER_ERROR,
                writes_performed=0,
                error_message=error_msg,
                created_at=execution_time,
            )
