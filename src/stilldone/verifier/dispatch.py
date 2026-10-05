"""Deterministic independent verifier dispatch layer.

Phase P-09.01:
Dispatches verification requests to dedicated READ adapters to obtain fresh,
independent read-back observations.

Strict Laws:
- Verification NEVER trusts execution result payloads.
- execution result payload != verification observation.
- ProviderExecutionResult cannot substitute for independent read-back.
- Verification is strictly read-only; zero mutation routes exist.
- No model / planner involvement.
- Fails closed on:
  * unsupported verification target;
  * missing verifier route;
  * mismatched target/action identity;
  * malformed observation;
  * attempted execute-result substitution.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from stilldone.adapters.calendar import (
    CalendarReadStatus,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
    TaskReadStatus,
)
from stilldone.adapters.weather import (
    OpenMeteoReadAdapter,
    WeatherReadStatus,
)
from stilldone.domain.action import ActionContract, ActionType, ResourceKind
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.state import ProviderExecutionResult
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    MalformedObservationError,
    MissingVerifierRouteError,
    UnsupportedVerificationTargetError,
    VerificationObservation,
    VerificationRequest,
    VerifierError,
    VerifierReadError,
    VerifierTargetMismatchError,
)

# ===========================================================================
# Verifier Read Port Protocol
# ===========================================================================


@runtime_checkable
class ReadAdapterPort(Protocol):
    """Protocol for an independent read-back port resolving external truth."""

    def read(self, request: VerificationRequest) -> VerificationObservation: ...


# ===========================================================================
# Canonical Verification Read Ports
# ===========================================================================


class CalendarVerificationPort:
    """Dispatches independent read-back to GoogleCalendarReadAdapter.

    Strictly read-only: wraps GoogleCalendarReadAdapter; cannot perform mutations.
    """

    def __init__(self, adapter: GoogleCalendarReadAdapter) -> None:
        if not isinstance(adapter, GoogleCalendarReadAdapter):
            raise VerifierError(
                f"adapter must be GoogleCalendarReadAdapter, got {type(adapter).__name__}"
            )
        self._adapter = adapter

    def read(self, request: VerificationRequest) -> VerificationObservation:
        # Validate request target
        if (
            request.target.system != "google_calendar"
            or request.target.resource_kind != ResourceKind.CALENDAR_EVENT
        ):
            raise VerifierTargetMismatchError("Verification target system/resource kind mismatch")

        # Formulate independent read action
        read_action = ActionContract.create(
            mission_id=request.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=request.target,
            parameters={},
        )

        read_failed = False
        try:
            result = self._adapter.read_event(read_action)
        except Exception:
            read_failed = True

        if read_failed:
            raise VerifierReadError("Calendar provider error during read-back")

        # Determine provenance from transport
        provenance = (
            EvidenceProvenance.FIXTURE
            if isinstance(self._adapter._transport, FakeGoogleCalendarTransport)
            else EvidenceProvenance.LIVE_GOOGLE
        )

        if result.status == CalendarReadStatus.SUCCESS and result.observation is not None:
            obs = result.observation
            props: dict[str, Any] = {
                "summary": obs.summary,
                "start_time": obs.start_time,
                "end_time": obs.end_time,
                "all_day": obs.all_day,
                "status": obs.status,
                "etag": obs.etag,
            }
            return VerificationObservation(
                target=request.target,
                observed_at=obs.observed_at,
                exists=True,
                properties=props,
                provenance=provenance,
                raw_observation=obs,
            )
        elif result.status == CalendarReadStatus.NOT_FOUND:
            return VerificationObservation(
                target=request.target,
                observed_at=result.read_at,
                exists=False,
                properties={},
                provenance=provenance,
                raw_observation=result,
            )
        else:
            raise VerifierReadError("Calendar provider error during read-back")


class TasksVerificationPort:
    """Dispatches independent read-back to GoogleTasksReadAdapter.

    Strictly read-only: wraps GoogleTasksReadAdapter; cannot perform mutations.
    """

    def __init__(self, adapter: GoogleTasksReadAdapter) -> None:
        if not isinstance(adapter, GoogleTasksReadAdapter):
            raise VerifierError(
                f"adapter must be GoogleTasksReadAdapter, got {type(adapter).__name__}"
            )
        self._adapter = adapter

    def read(self, request: VerificationRequest) -> VerificationObservation:
        # Validate request target
        if (
            request.target.system != "google_tasks"
            or request.target.resource_kind != ResourceKind.TASK
        ):
            raise VerifierTargetMismatchError("Verification target system/resource kind mismatch")

        # Formulate independent read action
        read_action = ActionContract.create(
            mission_id=request.mission_id,
            action_type=ActionType.TASK_READ,
            target=request.target,
            parameters={},
        )

        read_failed = False
        try:
            result = self._adapter.read_task(read_action)
        except Exception:
            read_failed = True

        if read_failed:
            raise VerifierReadError("Tasks provider error during read-back")

        # Determine provenance from transport
        provenance = (
            EvidenceProvenance.FIXTURE
            if isinstance(self._adapter._transport, FakeGoogleTasksTransport)
            else EvidenceProvenance.LIVE_GOOGLE
        )

        if result.status == TaskReadStatus.MATCH and result.observation is not None:
            obs = result.observation
            props: dict[str, Any] = {
                "title": obs.title,
                "due": obs.due,
                "status": obs.status,
                "deleted": obs.deleted,
                "hidden": obs.hidden,
                "etag": obs.etag,
            }
            # An active, non-deleted task exists
            exists = not obs.deleted
            return VerificationObservation(
                target=request.target,
                observed_at=obs.observed_at,
                exists=exists,
                properties=props,
                provenance=provenance,
                raw_observation=obs,
            )
        elif result.status == TaskReadStatus.NOT_FOUND:
            return VerificationObservation(
                target=request.target,
                observed_at=result.observed_at,
                exists=False,
                properties={},
                provenance=provenance,
                raw_observation=result,
            )
        else:
            raise VerifierReadError("Tasks provider error during read-back")


class WeatherVerificationPort:
    """Dispatches independent read-back to OpenMeteoReadAdapter.

    Strictly read-only: wraps OpenMeteoReadAdapter.
    """

    def __init__(self, adapter: OpenMeteoReadAdapter) -> None:
        if not isinstance(adapter, OpenMeteoReadAdapter):
            raise VerifierError(
                f"adapter must be OpenMeteoReadAdapter, got {type(adapter).__name__}"
            )
        self._adapter = adapter

    def read(self, request: VerificationRequest) -> VerificationObservation:
        # Validate request target
        if (
            request.target.system != "open_meteo"
            or request.target.resource_kind != ResourceKind.WEATHER_LOCATION
        ):
            raise VerifierTargetMismatchError("Verification target system/resource kind mismatch")

        read_action = ActionContract.create(
            mission_id=request.mission_id,
            action_type=ActionType.WEATHER_READ,
            target=request.target,
            parameters={},
        )

        read_failed = False
        try:
            result = self._adapter.read_weather(read_action)
        except Exception:
            read_failed = True

        if read_failed:
            raise VerifierReadError("Weather provider error during read-back")

        provenance = self._adapter._transport.provenance

        if result.status == WeatherReadStatus.MATCH and result.observation is not None:
            obs = result.observation
            props: dict[str, Any] = {
                "location_id": obs.location_id,
                "temperature_2m": obs.temperature_2m,
                "precipitation": obs.precipitation,
                "weather_code": obs.weather_code,
                "wind_speed_10m": obs.wind_speed_10m,
            }
            return VerificationObservation(
                target=request.target,
                observed_at=obs.observed_at,
                exists=True,
                properties=props,
                provenance=provenance,
                raw_observation=obs,
            )
        else:
            raise VerifierReadError("Weather provider error during read-back")


# ===========================================================================
# Deterministic Verifier Dispatcher
# ===========================================================================


class VerifierDispatcher:
    """Deterministic verifier dispatch layer.

    Routes VerificationRequests to registered independent read ports.
    Strictly forbids accepting ProviderExecutionResult as verification proof.
    """

    def __init__(
        self,
        routes: Mapping[tuple[str, ResourceKind], ReadAdapterPort],
    ) -> None:
        if not isinstance(routes, Mapping):
            raise TypeError("routes must be a Mapping")

        self._routes: dict[tuple[str, ResourceKind], ReadAdapterPort] = {}
        for (sys_name, kind), port in routes.items():
            if not isinstance(sys_name, str) or not isinstance(kind, ResourceKind):
                raise UnsupportedVerificationTargetError(
                    f"Route key must be (str, ResourceKind), got {(sys_name, kind)!r}"
                )
            if not isinstance(port, ReadAdapterPort):
                raise TypeError(f"Port must implement ReadAdapterPort, got {type(port).__name__}")
            self._routes[(sys_name, kind)] = port

    def has_route(self, system: str, resource_kind: ResourceKind) -> bool:
        """Check if dispatcher has an independent read port for (system, resource_kind)."""
        return (system, resource_kind) in self._routes

    def dispatch(self, request: VerificationRequest) -> VerificationObservation:
        """Dispatch a VerificationRequest to its registered independent read port.

        Enforces:
        - request is a VerificationRequest instance (rejects execution payloads).
        - target identity matches action contract lineage.
        - registered route exists for (system, resource_kind).
        - observation returned is independent and valid.

        Args:
            request: Canonical VerificationRequest.

        Returns:
            VerificationObservation with independent read-back facts.

        Raises:
            ExecutionPayloadSubstitutionError: If ProviderExecutionResult or
                ExecutionAttempt is passed.
            VerifierTargetMismatchError: If request target contradicts action contract.
            MissingVerifierRouteError: If no read port is registered.
            VerifierReadError: If read-back fails at provider level.
        """
        # Strict enforcement: reject execution payloads
        if isinstance(request, (ProviderExecutionResult, ExecutionAttempt)):
            raise ExecutionPayloadSubstitutionError(
                f"Execution payload {type(request).__name__} cannot substitute "
                "for VerificationRequest in verifier dispatch"
            )
        if not isinstance(request, VerificationRequest):
            raise TypeError(f"request must be VerificationRequest, got {type(request).__name__}")

        # Enforce action <-> target lineage
        self._validate_action_target_lineage(request)

        route_key = (request.target.system, request.target.resource_kind)
        port = self._routes.get(route_key)
        if port is None:
            raise MissingVerifierRouteError(
                "No independent verifier route registered for "
                f"{request.target.system}:{request.target.resource_kind.value}"
            )

        obs = port.read(request)
        if not isinstance(obs, VerificationObservation):
            raise MalformedObservationError(
                f"Read port returned {type(obs).__name__}, expected VerificationObservation"
            )
        return obs

    @staticmethod
    def _validate_action_target_lineage(request: VerificationRequest) -> None:
        """Enforce strict lineage between request.action and request.target."""
        action = request.action
        target = request.target

        if action.action_type in (ActionType.CALENDAR_READ, ActionType.CALENDAR_UPDATE):
            if (
                target.system != "google_calendar"
                or target.resource_kind != ResourceKind.CALENDAR_EVENT
            ):
                raise VerifierTargetMismatchError(
                    "Verification target system/resource kind mismatch"
                )
            if target.resource_id != action.target.resource_id:
                raise VerifierTargetMismatchError(
                    "Verification target resource_id does not match action target resource_id"
                )
            if target.parent_id != action.target.parent_id:
                raise VerifierTargetMismatchError(
                    "Verification target parent container does not match "
                    "action target parent container"
                )

        elif action.action_type == ActionType.TASK_READ:
            if target.system != "google_tasks" or target.resource_kind != ResourceKind.TASK:
                raise VerifierTargetMismatchError(
                    "Verification target system/resource kind mismatch"
                )
            if target.resource_id != action.target.resource_id:
                raise VerifierTargetMismatchError(
                    "Verification target resource_id does not match action target resource_id"
                )
            if target.parent_id != action.target.parent_id:
                raise VerifierTargetMismatchError(
                    "Verification target parent container does not match "
                    "action target parent container"
                )

        elif action.action_type == ActionType.TASK_CREATE:
            # Action targeted TASK_LIST container; verification targets the concrete TASK child
            if target.system != "google_tasks" or target.resource_kind != ResourceKind.TASK:
                raise VerifierTargetMismatchError(
                    "Verification target system/resource kind mismatch"
                )
            # Child task's parent_id must match the task list targeted during creation
            if target.parent_id != action.target.resource_id:
                raise VerifierTargetMismatchError(
                    "Verification target parent container does not match "
                    "action target parent container"
                )

        elif action.action_type == ActionType.WEATHER_READ:
            if (
                target.system != "open_meteo"
                or target.resource_kind != ResourceKind.WEATHER_LOCATION
            ):
                raise VerifierTargetMismatchError(
                    "Verification target system/resource kind mismatch"
                )
            if target.resource_id != action.target.resource_id:
                raise VerifierTargetMismatchError(
                    "Verification target resource_id does not match action target resource_id"
                )


# ===========================================================================
# Verifier Factory (Strictly Read-Only)
# ===========================================================================


def create_verifier_dispatcher(
    *,
    calendar_read: GoogleCalendarReadAdapter,
    tasks_read: GoogleTasksReadAdapter,
    weather_read: OpenMeteoReadAdapter | None = None,
) -> VerifierDispatcher:
    """Construct a VerifierDispatcher binding canonical read adapters.

    Strictly refuses any mutation adapter (GoogleCalendarUpdateAdapter, GoogleTasksCreateAdapter).
    """
    # Enforce that mutation adapters cannot masquerade as read adapters
    if isinstance(calendar_read, GoogleCalendarUpdateAdapter):
        raise VerifierError(
            "Mutation adapter GoogleCalendarUpdateAdapter cannot be registered in verifier"
        )
    if isinstance(tasks_read, GoogleTasksCreateAdapter):
        raise VerifierError(
            "Mutation adapter GoogleTasksCreateAdapter cannot be registered in verifier"
        )

    routes: dict[tuple[str, ResourceKind], ReadAdapterPort] = {
        ("google_calendar", ResourceKind.CALENDAR_EVENT): CalendarVerificationPort(calendar_read),
        ("google_tasks", ResourceKind.TASK): TasksVerificationPort(tasks_read),
    }

    if weather_read is not None:
        routes[("open_meteo", ResourceKind.WEATHER_LOCATION)] = WeatherVerificationPort(
            weather_read
        )

    return VerifierDispatcher(routes)
