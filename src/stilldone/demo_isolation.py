"""Deterministic fail-closed demo-resource isolation boundary for StillDone.

Enforces that StillDone's Google Calendar and Google Tasks actions are statically
declared to target only the dedicated disposable demo resources configured for
the competition path:
- Closed-world DemoResourceScope containing runtime calendar_id and task_list_id.
- Static TargetIdentity inspection against the supplied DemoResourceScope.
- Accepts only P-04.03 ValidatedActionContract (cannot bypass action validation).
- Exact match law: External IDs are compared with strict case-sensitive equality;
  no prefixes, suffixes, substrings, whitespace trimming, or aliases.
- Calendar actions (calendar.read, calendar.update) must declare target.parent_id
  matching the configured demo calendar_id.
- Task read action (task.read) must declare target.parent_id matching the configured
  demo task_list_id.
- Task create action (task.create) must declare target.resource_id matching the
  configured demo task_list_id, and target.parent_id must be None.
- Weather action (weather.read) returns explicit NOT_APPLICABLE status.
- Sensitive identifier safety: calendar_id and task_list_id are masked in str()
  and repr(); exception messages and result representations never echo raw
  external identifiers.
- Static-vs-live truth boundary: Static isolation does not call Google APIs,
  does not prove remote existence, does not confer authority, does not create
  approval grants, and cannot produce VERIFIED or READY state.
- Zero provider/network imports: Standard library and internal domain types only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stilldone.action_policy import ValidatedActionContract
from stilldone.domain.action import ActionType

# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class DemoIsolationError(Exception):
    """Base exception for all demo-resource isolation errors."""


class DemoIsolationTypeError(DemoIsolationError, TypeError):
    """Raised when an object or argument has an invalid type."""


class DemoScopeError(DemoIsolationError):
    """Base exception for demo resource scope configuration errors."""


class DemoScopeTypeError(DemoScopeError, TypeError):
    """Raised when a scope parameter is not a string."""


class DemoScopeValueError(DemoScopeError, ValueError):
    """Raised when a scope identifier is empty or whitespace-only."""


class MissingParentContainerError(DemoIsolationError, ValueError):
    """Raised when an action requires a parent container but none is declared."""


class UnexpectedParentContainerError(DemoIsolationError, ValueError):
    """Raised when an action declares a parent container when none is expected."""


class DemoResourceOutOfScopeError(DemoIsolationError, ValueError):
    """Raised when an action's declared target resource or parent is outside demo scope."""


class CalendarOutOfScopeError(DemoResourceOutOfScopeError):
    """Raised when a calendar action targets a calendar outside the demo calendar scope."""


class TaskOutOfScopeError(DemoResourceOutOfScopeError):
    """Raised when a task action targets a task list outside the demo task list scope."""


# ===========================================================================
# Scope and Result Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DemoResourceScope:
    """Immutable runtime configuration specifying the dedicated demo resources.

    Ensures that StillDone's Google Calendar and Google Tasks actions are statically
    bound to the disposable demo resources dedicated to the competition path.
    Does not read from environment, global state, or defaults.
    Sensitive identifiers are masked in str() and repr().
    """

    calendar_id: str
    task_list_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.calendar_id, str):
            raise DemoScopeTypeError(
                f"calendar_id must be a string, got {type(self.calendar_id).__name__}"
            )
        if not self.calendar_id.strip():
            raise DemoScopeValueError("calendar_id must not be empty or whitespace-only")

        if not isinstance(self.task_list_id, str):
            raise DemoScopeTypeError(
                f"task_list_id must be a string, got {type(self.task_list_id).__name__}"
            )
        if not self.task_list_id.strip():
            raise DemoScopeValueError("task_list_id must not be empty or whitespace-only")

    def __repr__(self) -> str:
        return "DemoResourceScope(calendar_id='***', task_list_id='***')"

    def __str__(self) -> str:
        return "DemoResourceScope(calendar_id='***', task_list_id='***')"


class DemoIsolationStatus(StrEnum):
    """Status of demo-resource isolation verification."""

    ISOLATED = "ISOLATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class DemoIsolationResult:
    """Deterministic, immutable result of a static demo-resource isolation check.

    Proves only that the declared TargetIdentity matches the configured demo-resource scope.
    Confers zero authority, creates zero approvals, performs zero provider API calls,
    and cannot produce VERIFIED or READY state.
    """

    status: DemoIsolationStatus
    action_type: ActionType

    def __repr__(self) -> str:
        return (
            f"DemoIsolationResult(status={self.status.value}, action_type={self.action_type.value})"
        )

    def __str__(self) -> str:
        return (
            f"DemoIsolationResult(status={self.status.value}, action_type={self.action_type.value})"
        )


# ===========================================================================
# Verification Function
# ===========================================================================


def verify_demo_resource_isolation(
    action: ValidatedActionContract,
    scope: DemoResourceScope,
) -> DemoIsolationResult:
    """Verify that a validated action targets only the configured demo resources.

    Performs static target-scope validation against the supplied DemoResourceScope.
    Does not call provider APIs or verify that resources exist remotely.

    Args:
        action: A ValidatedActionContract from P-04.03. Raw ActionContract is rejected.
        scope: An explicit DemoResourceScope containing the demo calendar and task list IDs.

    Returns:
        DemoIsolationResult with status ISOLATED or NOT_APPLICABLE.

    Raises:
        DemoIsolationTypeError: If action is not a ValidatedActionContract or scope
            is not DemoResourceScope.
        MissingParentContainerError: If calendar.read, calendar.update, or task.read
            lacks a non-null parent_id.
        UnexpectedParentContainerError: If task.create declares a non-null parent_id.
        CalendarOutOfScopeError: If calendar.read or calendar.update targets a non-demo calendar.
        TaskOutOfScopeError: If task.read or task.create targets a non-demo task list.
    """
    if not isinstance(action, ValidatedActionContract):
        raise DemoIsolationTypeError(
            f"action must be a ValidatedActionContract instance, got {type(action).__name__}"
        )
    if not isinstance(scope, DemoResourceScope):
        raise DemoIsolationTypeError(
            f"scope must be a DemoResourceScope instance, got {type(scope).__name__}"
        )

    action_type = action.action_type
    target = action.target

    if action_type in (ActionType.CALENDAR_READ, ActionType.CALENDAR_UPDATE):
        if target.parent_id is None:
            raise MissingParentContainerError(
                f"Action '{action_type.value}' requires a non-null target.parent_id "
                "declared under the demo calendar scope"
            )
        if target.parent_id != scope.calendar_id:
            raise CalendarOutOfScopeError(
                f"Action '{action_type.value}' target parent_id does not match "
                "the configured demo calendar scope"
            )
        return DemoIsolationResult(
            status=DemoIsolationStatus.ISOLATED,
            action_type=action_type,
        )

    if action_type == ActionType.TASK_READ:
        if target.parent_id is None:
            raise MissingParentContainerError(
                f"Action '{action_type.value}' requires a non-null target.parent_id "
                "declared under the demo task list scope"
            )
        if target.parent_id != scope.task_list_id:
            raise TaskOutOfScopeError(
                f"Action '{action_type.value}' target parent_id does not match "
                "the configured demo task list scope"
            )
        return DemoIsolationResult(
            status=DemoIsolationStatus.ISOLATED,
            action_type=action_type,
        )

    if action_type == ActionType.TASK_CREATE:
        if target.parent_id is not None:
            raise UnexpectedParentContainerError(
                f"Action '{action_type.value}' requires target.parent_id to be None, "
                "but parent_id was declared"
            )
        if target.resource_id != scope.task_list_id:
            raise TaskOutOfScopeError(
                f"Action '{action_type.value}' target resource_id does not match "
                "the configured demo task list scope"
            )
        return DemoIsolationResult(
            status=DemoIsolationStatus.ISOLATED,
            action_type=action_type,
        )

    if action_type == ActionType.WEATHER_READ:
        return DemoIsolationResult(
            status=DemoIsolationStatus.NOT_APPLICABLE,
            action_type=action_type,
        )

    raise DemoIsolationError(f"Unsupported action type for demo isolation: {action_type.value}")


check_demo_resource_isolation = verify_demo_resource_isolation
