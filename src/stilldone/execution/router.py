"""Deterministic no-silent-fallback adapter routing.

Phase P-08.05:
Routes canonical ActionContracts to registered provider adapters with zero fallback.

Laws:
- Every supported ActionType resolves to exactly one canonical adapter, or fails closed.
- Absolutely forbidden:
  * live provider -> mock fallback;
  * live provider -> fixture fallback;
  * Google -> local simulation fallback;
  * weather live -> fixture fallback;
  * unknown action -> "best effort" generic adapter;
  * provider exception -> alternate provider;
  * missing credentials -> simulation;
  * unsupported action -> model improvisation.
- Mocks/fakes are test dependencies only and cannot be auto-selected in production.
- Respects authority policy: Calendar update requires bound ApprovalGrant;
  unauthorized mutations cannot execute merely because scheduler reached them.
- Adapter exceptions are preserved and sanitized, never rerouted.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.adapters.calendar import (
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
)
from stilldone.adapters.weather import (
    FakeOpenMeteoTransport,
    OpenMeteoReadAdapter,
)
from stilldone.authority_policy import (
    AuthorityDecisionStatus,
    evaluate_authority,
)
from stilldone.domain.action import ActionContract, ActionType
from stilldone.domain.authority import ApprovalGrant
from stilldone.domain.execution import ExecutionAttempt
from stilldone.execution.attempts import (
    record_calendar_read_result,
    record_calendar_update_result,
    record_provider_exception,
    record_task_create_result,
    record_task_read_result,
    record_weather_read_result,
)
from stilldone.execution.contracts import (
    ExecutionContractError,
    ExecutionContractTypeError,
    ExecutionContractValueError,
    ExecutionLineageError,
)
from stilldone.execution.state import ProviderExecutionResult

# ===========================================================================
# Router Exceptions
# ===========================================================================


class RouterError(ExecutionContractError):
    """Base exception for adapter routing errors."""


class UnsupportedActionRouteError(RouterError, ValueError):
    """Raised when an action type is unsupported by the router."""


class MissingAdapterRouteError(RouterError, KeyError):
    """Raised when no adapter is registered for a requested action type."""


class ActionAuthorityError(RouterError):
    """Raised when an action cannot execute due to authority policy rejection."""


class RouterLineageError(RouterError, ExecutionLineageError):
    """Raised when an execution attempt does not match the target action."""


# ===========================================================================
# Adapter Handler Protocol
# ===========================================================================


class ActionHandler(Protocol):
    """Protocol for an execution handler dispatching an action to a provider adapter."""

    def execute(
        self,
        action: ValidatedActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult: ...


# ===========================================================================
# Concrete Handlers Wrapping Canonical Adapters
# ===========================================================================


class CalendarReadHandler:
    """Dispatches calendar.read to GoogleCalendarReadAdapter."""

    def __init__(self, adapter: GoogleCalendarReadAdapter) -> None:
        if not isinstance(adapter, GoogleCalendarReadAdapter):
            raise ExecutionContractTypeError("adapter must be GoogleCalendarReadAdapter")
        self._adapter = adapter

    def execute(
        self,
        action: ValidatedActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult:
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action.action_id:
            raise RouterLineageError(
                f"ExecutionAttempt action_id {attempt.action_id} does not match "
                f"action.action_id {action.action_id}"
            )
        try:
            raw_result = self._adapter.read_event(action)
            return record_calendar_read_result(raw_result)
        except Exception as exc:
            return record_provider_exception(action.action_type, exc)


class CalendarUpdateHandler:
    """Dispatches calendar.update to GoogleCalendarUpdateAdapter."""

    def __init__(self, adapter: GoogleCalendarUpdateAdapter) -> None:
        if not isinstance(adapter, GoogleCalendarUpdateAdapter):
            raise ExecutionContractTypeError("adapter must be GoogleCalendarUpdateAdapter")
        self._adapter = adapter

    def execute(
        self,
        action: ValidatedActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult:
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action.action_id:
            raise RouterLineageError(
                f"ExecutionAttempt action_id {attempt.action_id} does not match "
                f"action.action_id {action.action_id}"
            )
        if approval is None:
            raise ActionAuthorityError(
                "calendar.update requires a cryptographically bound ApprovalGrant"
            )
        try:
            raw_result = self._adapter.update_event(action, approval=approval, at=at)
            return record_calendar_update_result(raw_result)
        except Exception as exc:
            return record_provider_exception(action.action_type, exc)


class TasksReadHandler:
    """Dispatches task.read to GoogleTasksReadAdapter."""

    def __init__(self, adapter: GoogleTasksReadAdapter) -> None:
        if not isinstance(adapter, GoogleTasksReadAdapter):
            raise ExecutionContractTypeError("adapter must be GoogleTasksReadAdapter")
        self._adapter = adapter

    def execute(
        self,
        action: ValidatedActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult:
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action.action_id:
            raise RouterLineageError(
                f"ExecutionAttempt action_id {attempt.action_id} does not match "
                f"action.action_id {action.action_id}"
            )
        try:
            raw_result = self._adapter.read_task(action, at=at)
            return record_task_read_result(raw_result)
        except Exception as exc:
            return record_provider_exception(action.action_type, exc)


class TasksCreateHandler:
    """Dispatches task.create to GoogleTasksCreateAdapter."""

    def __init__(self, adapter: GoogleTasksCreateAdapter) -> None:
        if not isinstance(adapter, GoogleTasksCreateAdapter):
            raise ExecutionContractTypeError("adapter must be GoogleTasksCreateAdapter")
        self._adapter = adapter

    def execute(
        self,
        action: ValidatedActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult:
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action.action_id:
            raise RouterLineageError(
                f"ExecutionAttempt action_id {attempt.action_id} does not match "
                f"action.action_id {action.action_id}"
            )
        try:
            raw_result = self._adapter.create_task(action, at=at)
            return record_task_create_result(raw_result)
        except Exception as exc:
            return record_provider_exception(action.action_type, exc)


class WeatherReadHandler:
    """Dispatches weather.read to OpenMeteoReadAdapter."""

    def __init__(self, adapter: OpenMeteoReadAdapter) -> None:
        if not isinstance(adapter, OpenMeteoReadAdapter):
            raise ExecutionContractTypeError("adapter must be OpenMeteoReadAdapter")
        self._adapter = adapter

    def execute(
        self,
        action: ValidatedActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult:
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action.action_id:
            raise RouterLineageError(
                f"ExecutionAttempt action_id {attempt.action_id} does not match "
                f"action.action_id {action.action_id}"
            )
        try:
            raw_result = self._adapter.read_weather(action, at=at)
            return record_weather_read_result(raw_result)
        except Exception as exc:
            return record_provider_exception(action.action_type, exc)


# ===========================================================================
# Deterministic Adapter Router
# ===========================================================================


class AdapterRouter:
    """Deterministic adapter router with NO silent fallback.

    Enforces:
    - Every supported ActionType routes to its one registered handler.
    - Missing handler fails closed with MissingAdapterRouteError.
    - Unsupported action fails closed with UnsupportedActionRouteError.
    - Authority policy evaluated before mutation; unauthorized actions fail closed.
    - Provider exceptions are preserved/sanitized, NEVER rerouted to an alternate provider.
    - Zero fallback routes.
    """

    def __init__(
        self,
        routes: Mapping[ActionType, ActionHandler],
    ) -> None:
        if not isinstance(routes, Mapping):
            raise ExecutionContractTypeError("routes must be a Mapping")

        self._routes: dict[ActionType, ActionHandler] = {}
        for at, handler in routes.items():
            if not isinstance(at, ActionType):
                raise UnsupportedActionRouteError(f"Route key must be ActionType, got {at!r}")
            self._routes[at] = handler

    @property
    def registered_action_types(self) -> frozenset[ActionType]:
        """Set of ActionTypes with registered handlers."""
        return frozenset(self._routes.keys())

    def has_route(self, action_type: ActionType) -> bool:
        """Check if router has an explicit route for action_type."""
        return action_type in self._routes

    def execute(
        self,
        action: ActionContract,
        *,
        attempt: ExecutionAttempt,
        approval: ApprovalGrant | None = None,
        at: datetime | None = None,
    ) -> ProviderExecutionResult:
        """Route and execute an ActionContract against its registered adapter.

        Args:
            action: Canonical ActionContract to execute.
            attempt: Canonical ExecutionAttempt.
            approval: Optional ApprovalGrant for approval-required actions.
            at: Optional evaluation timestamp (defaults to UTC now).

        Returns:
            ProviderExecutionResult preserving execution facts.

        Raises:
            ExecutionContractTypeError: If action or attempt has invalid type.
            ExecutionContractValueError: If attempt_number != 1.
            RouterLineageError: If attempt.action_id does not match action.action_id.
            UnsupportedActionRouteError: If action_type is unsupported.
            MissingAdapterRouteError: If no adapter is registered for action_type.
            ActionAuthorityError: If authority policy rejects execution.
        """
        # Enforce attempt type, attempt_number==1, and action<->attempt lineage
        # strictly BEFORE authority evaluation or execution
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if isinstance(attempt.attempt_number, bool) or attempt.attempt_number != 1:
            raise ExecutionContractValueError(
                f"P-08 router only allows attempt_number=1, got {attempt.attempt_number}"
            )
        if not isinstance(action, ActionContract):
            raise ExecutionContractTypeError(
                f"action must be an ActionContract, got {type(action).__name__}"
            )
        if attempt.action_id != action.action_id:
            raise RouterLineageError(
                f"ExecutionAttempt action_id {attempt.action_id} does not match "
                f"action.action_id {action.action_id}"
            )

        # Validate action contract
        validated = validate_action_contract(action)

        # Enforce authority policy before execution
        now = at or datetime.now(UTC)
        auth_decision = evaluate_authority(validated, approval=approval, at=now)

        if auth_decision.status not in (
            AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED,
            AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL,
        ):
            raise ActionAuthorityError(
                f"Action {action.action_id} of type {action.action_type.value} "
                f"is not authorized: {auth_decision.status.value}"
            )

        # Check explicit route
        if action.action_type not in ActionType:
            raise UnsupportedActionRouteError(f"Unsupported action type: {action.action_type}")

        handler = self._routes.get(action.action_type)
        if handler is None:
            raise MissingAdapterRouteError(
                f"No adapter registered for action type: {action.action_type.value}"
            )

        # Execute ONLY via resolved handler (ZERO silent fallback)
        return handler.execute(
            validated,
            attempt=attempt,
            approval=approval,
            at=now,
        )


# ===========================================================================
# Production Router Factory (Strictly Rejects Fakes/Mocks)
# ===========================================================================


def create_production_adapter_router(
    *,
    calendar_read: GoogleCalendarReadAdapter,
    calendar_update: GoogleCalendarUpdateAdapter,
    tasks_read: GoogleTasksReadAdapter,
    tasks_create: GoogleTasksCreateAdapter,
    weather_read: OpenMeteoReadAdapter,
) -> AdapterRouter:
    """Create production AdapterRouter enforcing that fakes/mocks CANNOT be registered.

    Rejects FakeGoogleCalendarTransport, FakeGoogleTasksTransport, FakeOpenMeteoTransport.
    Fakes are test dependencies only and must be explicitly injected in tests.
    """
    # Reject test fakes in calendar adapters
    if isinstance(calendar_read._transport, FakeGoogleCalendarTransport):
        raise RouterError("FakeGoogleCalendarTransport cannot enter production routing")
    if isinstance(calendar_update._transport, FakeGoogleCalendarTransport):
        raise RouterError("FakeGoogleCalendarTransport cannot enter production routing")

    # Reject test fakes in tasks adapters
    if isinstance(tasks_read._transport, FakeGoogleTasksTransport):
        raise RouterError("FakeGoogleTasksTransport cannot enter production routing")
    if isinstance(tasks_create._transport, FakeGoogleTasksTransport):
        raise RouterError("FakeGoogleTasksTransport cannot enter production routing")

    # Reject test fakes in weather adapter
    if isinstance(weather_read._transport, FakeOpenMeteoTransport):
        raise RouterError("FakeOpenMeteoTransport cannot enter production routing")

    routes: dict[ActionType, ActionHandler] = {
        ActionType.CALENDAR_READ: CalendarReadHandler(calendar_read),
        ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(calendar_update),
        ActionType.TASK_READ: TasksReadHandler(tasks_read),
        ActionType.TASK_CREATE: TasksCreateHandler(tasks_create),
        ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
    }

    return AdapterRouter(routes)
