"""Tests for Phase P-09.01: Independent Verifier Dispatch.

Validates that:
- Verification obtains an independent read-back observation rather than trusting
  execution result payloads.
- Verifier input references canonical mission/action/desired-state contracts.
- Verifier MUST NOT accept ProviderExecutionResult as proof of desired state.
- Strict independence law: execution result payload != verification observation.
- A mutation adapter's returned object cannot be passed directly into predicate
  evaluation as if it were independent read-back.
- Flow: ActionContract / desired-state verification request -> verifier dispatch
  -> appropriate READ adapter -> fresh bounded observation.
- Reuses existing canonical read adapters: Calendar read, Tasks read, Weather read.
- Zero mutations performed; verifier rejects mutation adapters.
- Zero planner / model involvement.
- Fails closed on:
  * unsupported verification target;
  * missing verifier route;
  * mismatched target/action identity;
  * malformed observation;
  * attempted execute-result substitution.
- Tests prove execution payload substitution is rejected or structurally impossible.
"""

from __future__ import annotations

import traceback
from datetime import UTC, datetime
from typing import Any

import pytest

from stilldone.action_policy import ValidatedActionContract
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
    WeatherLocationConfig,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.state import ProviderExecutionResult
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    MalformedObservationError,
    MissingVerifierRouteError,
    VerificationObservation,
    VerificationRequest,
    VerifierError,
    VerifierTargetMismatchError,
)
from stilldone.verifier.dispatch import (
    CalendarVerificationPort,
    VerifierDispatcher,
    create_verifier_dispatcher,
)

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="demo-cal-p0901",
        task_list_id="demo-tasks-p0901",
    )


@pytest.fixture
def cal_transport(demo_scope: DemoResourceScope) -> FakeGoogleCalendarTransport:
    t = FakeGoogleCalendarTransport()
    t.seed_event(
        calendar_id=demo_scope.calendar_id,
        event_id="evt-school-101",
        summary="School drop-off",
        start_time="2026-10-06T07:30:00Z",
        end_time="2026-10-06T08:00:00Z",
        all_day=False,
        status="confirmed",
    )
    return t


@pytest.fixture
def tasks_transport(demo_scope: DemoResourceScope) -> FakeGoogleTasksTransport:
    t = FakeGoogleTasksTransport()
    t.seed_task(
        task_list_id=demo_scope.task_list_id,
        task_id="task-pack-202",
        title="Pack backpacks",
        due="2026-10-06",
        status="needsAction",
    )
    return t


@pytest.fixture
def weather_transport() -> FakeOpenMeteoTransport:
    return FakeOpenMeteoTransport()


@pytest.fixture
def cal_read_adapter(
    demo_scope: DemoResourceScope, cal_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarReadAdapter:
    return GoogleCalendarReadAdapter(demo_scope, cal_transport)


@pytest.fixture
def tasks_read_adapter(
    demo_scope: DemoResourceScope, tasks_transport: FakeGoogleTasksTransport
) -> GoogleTasksReadAdapter:
    return GoogleTasksReadAdapter(demo_scope, tasks_transport)


@pytest.fixture
def weather_read_adapter(
    weather_transport: FakeOpenMeteoTransport,
) -> OpenMeteoReadAdapter:
    cfg = WeatherLocationConfig(
        location_id="loc-p0901",
        latitude=52.52,
        longitude=13.41,
    )
    return OpenMeteoReadAdapter(cfg, weather_transport)


@pytest.fixture
def dispatcher(
    cal_read_adapter: GoogleCalendarReadAdapter,
    tasks_read_adapter: GoogleTasksReadAdapter,
    weather_read_adapter: OpenMeteoReadAdapter,
) -> VerifierDispatcher:
    return create_verifier_dispatcher(
        calendar_read=cal_read_adapter,
        tasks_read=tasks_read_adapter,
        weather_read=weather_read_adapter,
    )


# ===========================================================================
# Strict Independence Law: Execution Payload != Verification Observation
# ===========================================================================


class TestStrictIndependenceLaw:
    """Proves execution payload substitution is rejected or structurally impossible."""

    def test_provider_execution_result_rejected_as_verification_request(
        self, dispatcher: VerifierDispatcher
    ) -> None:
        """ProviderExecutionResult cannot be passed to dispatcher.dispatch."""
        exec_result = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            dispatcher.dispatch(exec_result)  # type: ignore[arg-type]

    def test_provider_execution_result_rejected_as_action_in_request(
        self, demo_scope: DemoResourceScope
    ) -> None:
        """ProviderExecutionResult cannot substitute for ActionContract in VerificationRequest."""
        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        exec_result = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            VerificationRequest(
                mission_id=mid,
                action=exec_result,  # type: ignore[arg-type]
                target=target,
            )

    def test_provider_execution_result_rejected_in_request_create(
        self, demo_scope: DemoResourceScope
    ) -> None:
        """ProviderExecutionResult cannot be passed to VerificationRequest.create."""
        exec_result = ProviderExecutionResult(
            action_type=ActionType.TASK_CREATE,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            VerificationRequest.create(action=exec_result)  # type: ignore[arg-type]

    def test_provider_execution_result_rejected_as_raw_observation(
        self, demo_scope: DemoResourceScope
    ) -> None:
        """ProviderExecutionResult cannot be raw_observation in VerificationObservation."""
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        exec_result = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            VerificationObservation(
                target=target,
                observed_at=datetime.now(UTC),
                exists=True,
                properties={},
                raw_observation=exec_result,
            )

    def test_execution_attempt_rejected_in_verification_structures(
        self, demo_scope: DemoResourceScope
    ) -> None:
        """ExecutionAttempt cannot substitute for action or raw_observation."""
        aid = ActionId.generate()
        attempt = ExecutionAttempt(
            action_id=aid,
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
            started_at=datetime.now(UTC),
        )
        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            VerificationRequest(
                mission_id=mid,
                action=attempt,  # type: ignore[arg-type]
                target=target,
            )

    def test_verifier_refuses_mutation_adapters_at_factory(
        self,
        demo_scope: DemoResourceScope,
        cal_transport: FakeGoogleCalendarTransport,
        tasks_transport: FakeGoogleTasksTransport,
    ) -> None:
        """create_verifier_dispatcher strictly refuses mutation adapters."""
        cal_update = GoogleCalendarUpdateAdapter(demo_scope, cal_transport)
        tasks_create = GoogleTasksCreateAdapter(demo_scope, tasks_transport)
        tasks_read = GoogleTasksReadAdapter(demo_scope, tasks_transport)
        cal_read = GoogleCalendarReadAdapter(demo_scope, cal_transport)

        with pytest.raises(VerifierError, match="Mutation adapter"):
            create_verifier_dispatcher(
                calendar_read=cal_update,  # type: ignore[arg-type]
                tasks_read=tasks_read,
            )

        with pytest.raises(VerifierError, match="Mutation adapter"):
            create_verifier_dispatcher(
                calendar_read=cal_read,
                tasks_read=tasks_create,  # type: ignore[arg-type]
            )


# ===========================================================================
# Verifier Dispatch to Independent Read Ports
# ===========================================================================


class TestVerifierDispatchExecution:
    """Dispatches verification requests to canonical independent read ports."""

    def test_calendar_read_verification_dispatch(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Dispatches calendar verification and returns independent read-back observation."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=target,
            parameters={},
            action_id=aid,
        )
        req = VerificationRequest.create(action=action)
        obs = dispatcher.dispatch(req)

        assert isinstance(obs, VerificationObservation)
        assert obs.target == target
        assert obs.exists is True
        assert obs.provenance == EvidenceProvenance.FIXTURE
        assert obs.properties["summary"] == "School drop-off"
        assert obs.properties["status"] == "confirmed"
        assert obs.properties["all_day"] is False
        assert obs.observed_at.tzinfo == UTC

    def test_calendar_mutation_verification_dispatches_read_not_mutation(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Verification of CALENDAR_UPDATE dispatches an independent read rather than mutating."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        # Action was a mutation
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=target,
            parameters={"summary": "Updated school drop-off"},
            action_id=aid,
        )
        req = VerificationRequest.create(action=action)
        obs = dispatcher.dispatch(req)

        assert isinstance(obs, VerificationObservation)
        assert obs.target == target
        assert obs.exists is True
        # Read-back observes actual state from transport (not the unapplied parameter!)
        assert obs.properties["summary"] == "School drop-off"

    def test_tasks_read_verification_dispatch(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Dispatches tasks read verification and observes external task."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-pack-202",
            parent_id=demo_scope.task_list_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=target,
            parameters={},
            action_id=aid,
        )
        req = VerificationRequest.create(action=action)
        obs = dispatcher.dispatch(req)

        assert isinstance(obs, VerificationObservation)
        assert obs.target == target
        assert obs.exists is True
        assert obs.properties["title"] == "Pack backpacks"
        assert obs.properties["status"] == "needsAction"
        assert obs.properties["deleted"] is False

    def test_tasks_create_verification_dispatches_concrete_task_read(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Verification of TASK_CREATE targets the concrete created TASK child."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        # Action targeted the parent list
        action_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id=demo_scope.task_list_id,
            parent_id=None,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=action_target,
            parameters={"title": "Pack backpacks"},
            action_id=aid,
        )
        # Verification targets the concrete resolved child task
        concrete_task_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-pack-202",
            parent_id=demo_scope.task_list_id,
        )
        req = VerificationRequest.create(action=action, target=concrete_task_target)
        obs = dispatcher.dispatch(req)

        assert isinstance(obs, VerificationObservation)
        assert obs.target == concrete_task_target
        assert obs.exists is True
        assert obs.properties["title"] == "Pack backpacks"

    def test_weather_read_verification_dispatch(
        self,
        dispatcher: VerifierDispatcher,
    ) -> None:
        """Dispatches weather verification and observes weather readings."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        target = TargetIdentity(
            system="open_meteo",
            resource_kind=ResourceKind.WEATHER_LOCATION,
            resource_id="loc-p0901",
            parent_id=None,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=target,
            parameters={},
            action_id=aid,
        )
        req = VerificationRequest.create(action=action)
        obs = dispatcher.dispatch(req)

        assert isinstance(obs, VerificationObservation)
        assert obs.target == target
        assert obs.exists is True
        assert "temperature_2m" in obs.properties

    def test_missing_object_observed_as_exists_false(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Non-existent external object returns exists=False observation, not crash."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-non-existent-999",
            parent_id=demo_scope.calendar_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=target,
            parameters={},
            action_id=aid,
        )
        req = VerificationRequest.create(action=action)
        obs = dispatcher.dispatch(req)

        assert isinstance(obs, VerificationObservation)
        assert obs.exists is False
        assert len(obs.properties) == 0


# ===========================================================================
# Fail-Closed Invariants: Target Mismatch & Missing Routes
# ===========================================================================


class TestVerifierFailClosedInvariants:
    """Verifies strict fail-closed behavior on invalid requests."""

    def test_missing_verifier_route_fails_closed(
        self,
        cal_read_adapter: GoogleCalendarReadAdapter,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Dispatcher without tasks route fails closed with MissingVerifierRouteError."""
        # Create dispatcher with only calendar route
        routes = {
            ("google_calendar", ResourceKind.CALENDAR_EVENT): CalendarVerificationPort(
                cal_read_adapter
            ),
        }
        partial_dispatcher = VerifierDispatcher(routes)

        mid = MissionId.generate()
        aid = ActionId.generate()
        tasks_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-pack-202",
            parent_id=demo_scope.task_list_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=tasks_target,
            parameters={},
            action_id=aid,
        )
        req = VerificationRequest.create(action=action)

        with pytest.raises(MissingVerifierRouteError, match="No independent verifier route"):
            partial_dispatcher.dispatch(req)

    def test_mismatched_target_resource_id_fails_closed(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Mismatched resource_id between action and target fails closed."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        wrong_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-different-id",
            parent_id=demo_scope.calendar_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=action_target,
            parameters={},
            action_id=aid,
        )
        req = VerificationRequest(
            mission_id=mid,
            action=action,
            target=wrong_target,
        )
        with pytest.raises(VerifierTargetMismatchError, match="does not match"):
            dispatcher.dispatch(req)

    def test_mismatched_task_create_parent_fails_closed(
        self,
        dispatcher: VerifierDispatcher,
        demo_scope: DemoResourceScope,
    ) -> None:
        """TASK_CREATE child verification with mismatched parent_id fails closed."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id=demo_scope.task_list_id,
            parent_id=None,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=action_target,
            parameters={"title": "Pack backpacks"},
            action_id=aid,
        )
        wrong_child_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-pack-202",
            parent_id="wrong-task-list-id",
        )
        req = VerificationRequest(
            mission_id=mid,
            action=action,
            target=wrong_child_target,
        )
        with pytest.raises(
            VerifierTargetMismatchError,
            match="parent container does not match",
        ):
            dispatcher.dispatch(req)

    def test_naive_datetime_in_observation_fails_closed(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        """VerificationObservation rejects naive datetime."""
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school-101",
            parent_id=demo_scope.calendar_id,
        )
        naive_dt = datetime.now()  # no tzinfo!
        with pytest.raises(MalformedObservationError, match="timezone-aware"):
            VerificationObservation(
                target=target,
                observed_at=naive_dt,
                exists=True,
            )


# ===========================================================================
# Adversarial Sentinel Tests: Error Secrecy (Phase P-09.01 Repair)
# ===========================================================================


class TestVerifierDispatchErrorSecrecy:
    """Proves that raw identifiers, secrets, and provider exceptions never leak.

    Enforces:
    - No raw resource_id or parent_id in str(exc) or repr(exc)
    - No provider error text / tokens in str(exc) or repr(exc)
    - Exception chaining broke (__cause__ is None, __context__ is None)
    - Formatted tracebacks do not leak raw sentinels
    """

    SECRET_RES_ID = "SECRET_EVENT_ID_XYZ_776655"
    SECRET_OTHER_RES_ID = "SECRET_OTHER_EVENT_ID_XYZ_112233"
    SECRET_PARENT_ID = "SECRET_PARENT_CONTAINER_445566"
    SECRET_OTHER_PARENT_ID = "SECRET_OTHER_PARENT_CONTAINER_998877"
    SECRET_PROVIDER_TOKEN = "PROVIDER_INTERNAL_SECRET_LEAK_TOKEN_9999"

    def test_target_resource_id_mismatch_never_echoes_raw_ids(
        self, dispatcher: VerifierDispatcher
    ) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=self.SECRET_RES_ID,
            parent_id=self.SECRET_PARENT_ID,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=action_target,
            parameters={},
            action_id=aid,
        )
        mismatched_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=self.SECRET_OTHER_RES_ID,
            parent_id=self.SECRET_PARENT_ID,
        )
        req = VerificationRequest(
            mission_id=mid,
            action=action,
            target=mismatched_target,
        )

        with pytest.raises(VerifierTargetMismatchError) as exc_info:
            dispatcher.dispatch(req)

        exc = exc_info.value
        exc_str = str(exc)
        exc_repr = repr(exc)
        tb_str = "".join(traceback.format_exception(exc))

        assert self.SECRET_RES_ID not in exc_str
        assert self.SECRET_OTHER_RES_ID not in exc_str
        assert self.SECRET_RES_ID not in exc_repr
        assert self.SECRET_OTHER_RES_ID not in exc_repr
        assert self.SECRET_RES_ID not in tb_str
        assert self.SECRET_OTHER_RES_ID not in tb_str
        assert exc_str == "Verification target resource_id does not match action target resource_id"

    def test_target_parent_container_mismatch_never_echoes_raw_ids(
        self, dispatcher: VerifierDispatcher
    ) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=self.SECRET_RES_ID,
            parent_id=self.SECRET_PARENT_ID,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=action_target,
            parameters={},
            action_id=aid,
        )
        mismatched_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=self.SECRET_RES_ID,
            parent_id=self.SECRET_OTHER_PARENT_ID,
        )
        req = VerificationRequest(
            mission_id=mid,
            action=action,
            target=mismatched_target,
        )

        with pytest.raises(VerifierTargetMismatchError) as exc_info:
            dispatcher.dispatch(req)

        exc = exc_info.value
        exc_str = str(exc)
        exc_repr = repr(exc)
        tb_str = "".join(traceback.format_exception(exc))

        assert self.SECRET_PARENT_ID not in exc_str
        assert self.SECRET_OTHER_PARENT_ID not in exc_str
        assert self.SECRET_PARENT_ID not in exc_repr
        assert self.SECRET_OTHER_PARENT_ID not in exc_repr
        assert self.SECRET_PARENT_ID not in tb_str
        assert self.SECRET_OTHER_PARENT_ID not in tb_str
        assert (
            exc_str
            == "Verification target parent container does not match action target parent container"
        )

    def test_provider_exception_does_not_leak_into_read_error(self) -> None:
        class CrashingCalendarAdapter(GoogleCalendarReadAdapter):
            def read_event(self, action: ValidatedActionContract | ActionContract) -> Any:
                raise RuntimeError(
                    f"CRASH with secret token: "
                    f"{TestVerifierDispatchErrorSecrecy.SECRET_PROVIDER_TOKEN}"
                )

        crashing_adapter = CrashingCalendarAdapter(
            transport=FakeGoogleCalendarTransport(),
            scope=DemoResourceScope(calendar_id="demo-cal", task_list_id="demo-tasks"),
        )
        port = CalendarVerificationPort(crashing_adapter)

        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-normal-1",
            parent_id="demo-cal",
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=target,
            parameters={},
        )
        req = VerificationRequest(
            mission_id=mid,
            action=action,
            target=target,
        )

        with pytest.raises(VerifierError) as exc_info:
            port.read(req)

        exc = exc_info.value
        exc_str = str(exc)
        exc_repr = repr(exc)
        tb_str = "".join(traceback.format_exception(exc))

        assert self.SECRET_PROVIDER_TOKEN not in exc_str
        assert self.SECRET_PROVIDER_TOKEN not in exc_repr
        assert exc.__cause__ is None
        assert exc.__context__ is None
        assert self.SECRET_PROVIDER_TOKEN not in tb_str
        assert exc_str == "Calendar provider error during read-back"
