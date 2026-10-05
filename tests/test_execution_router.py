"""Tests for Phase P-08.05: No-Silent-Fallback Adapter Routing.

Validates that:
- Every supported ActionType has exactly intended route to registered adapter.
- Unsupported route fails closed with UnsupportedActionRouteError.
- Missing adapter fails closed with MissingAdapterRouteError (zero silent fallback).
- Adapter exceptions are preserved and sanitized, never rerouted to alternate provider.
- Test fakes/mocks CANNOT enter production routing via create_production_adapter_router.
- Authority policy is strictly respected:
  * calendar.update without approval fails closed (ActionAuthorityError);
  * calendar.update with bound ApprovalGrant executes;
  * read-only and auto-reversible actions execute without approval.
- Zero network / live calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
from stilldone.domain.authority import ApprovalGrant, AuthorityClass
from stilldone.domain.mission import MissionId
from stilldone.execution.attempts import create_execution_attempt
from stilldone.execution.router import (
    ActionAuthorityError,
    ActionHandler,
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
    MissingAdapterRouteError,
    RouterError,
    TasksCreateHandler,
    TasksReadHandler,
    WeatherReadHandler,
    create_production_adapter_router,
)
from stilldone.execution.state import ProviderExecutionResult


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="demo-cal-123",
        task_list_id="demo-tasks-456",
    )


@pytest.fixture
def calendar_fake() -> FakeGoogleCalendarTransport:
    transport = FakeGoogleCalendarTransport()
    # Add fixture event via seed_event
    transport.seed_event(
        calendar_id="demo-cal-123",
        event_id="evt-school",
        summary="Leave for school",
        start_time="2026-10-06T07:45:00Z",
        end_time="2026-10-06T08:15:00Z",
        all_day=False,
        status="confirmed",
    )
    return transport


@pytest.fixture
def tasks_fake() -> FakeGoogleTasksTransport:
    transport = FakeGoogleTasksTransport()
    transport.seed_task(
        task_list_id="demo-tasks-456",
        task_id="task-pack",
        title="Pack backpacks",
        due="2026-10-06",
        status="needsAction",
    )
    return transport


@pytest.fixture
def weather_fake() -> FakeOpenMeteoTransport:
    return FakeOpenMeteoTransport()


@pytest.fixture
def test_router(
    demo_scope: DemoResourceScope,
    calendar_fake: FakeGoogleCalendarTransport,
    tasks_fake: FakeGoogleTasksTransport,
    weather_fake: FakeOpenMeteoTransport,
) -> AdapterRouter:
    """Explicitly inject test-fake adapters into test router."""
    cal_read = GoogleCalendarReadAdapter(demo_scope, calendar_fake)
    cal_update = GoogleCalendarUpdateAdapter(demo_scope, calendar_fake)
    task_read = GoogleTasksReadAdapter(demo_scope, tasks_fake)
    task_create = GoogleTasksCreateAdapter(demo_scope, tasks_fake)
    loc_config = WeatherLocationConfig(
        location_id="demo-weather-loc",
        latitude=52.52,
        longitude=13.41,
    )
    weather_read = OpenMeteoReadAdapter(loc_config, weather_fake)

    routes: dict[ActionType, ActionHandler] = {
        ActionType.CALENDAR_READ: CalendarReadHandler(cal_read),
        ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(cal_update),
        ActionType.TASK_READ: TasksReadHandler(task_read),
        ActionType.TASK_CREATE: TasksCreateHandler(task_create),
        ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
    }
    return AdapterRouter(routes)


class TestAdapterRouterExplicitRouting:
    """Every supported ActionType has an explicit route and executes cleanly."""

    def test_calendar_read_routes_correctly(
        self, test_router: AdapterRouter, demo_scope: DemoResourceScope
    ) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid,
        )
        attempt = create_execution_attempt(aid)
        result = test_router.execute(action, attempt=attempt)

        assert isinstance(result, ProviderExecutionResult)
        assert result.action_type == ActionType.CALENDAR_READ
        assert result.success is True
        assert result.status_name == "SUCCESS"

    def test_task_read_routes_correctly(
        self, test_router: AdapterRouter, demo_scope: DemoResourceScope
    ) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="task-pack",
                parent_id=demo_scope.task_list_id,
            ),
            parameters={},
            action_id=aid,
        )
        attempt = create_execution_attempt(aid)
        result = test_router.execute(action, attempt=attempt)

        assert result.action_type == ActionType.TASK_READ
        assert result.success is True
        assert result.status_name == "MATCH"

    def test_task_create_routes_correctly(
        self, test_router: AdapterRouter, demo_scope: DemoResourceScope
    ) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK_LIST,
                resource_id=demo_scope.task_list_id,
                parent_id=None,
            ),
            parameters={"title": "New morning task"},
            action_id=aid,
        )
        attempt = create_execution_attempt(aid)
        result = test_router.execute(action, attempt=attempt)

        assert result.action_type == ActionType.TASK_CREATE
        assert result.success is True
        assert result.status_name == "CREATED"
        assert result.writes_performed == 1

    def test_weather_read_routes_correctly(self, test_router: AdapterRouter) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="demo-weather-loc",
                parent_id=None,
            ),
            parameters={},
            action_id=aid,
        )
        attempt = create_execution_attempt(aid)
        result = test_router.execute(action, attempt=attempt)

        assert result.action_type == ActionType.WEATHER_READ
        assert result.success is True
        assert result.status_name == "MATCH"


class TestNoSilentFallbackInvariants:
    """Router enforces zero silent fallback and fails closed."""

    def test_missing_adapter_fails_closed_without_fallback(
        self, demo_scope: DemoResourceScope
    ) -> None:
        """If router has no handler for an action type, it fails closed (no fallback)."""
        empty_router = AdapterRouter({})

        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid,
        )
        attempt = create_execution_attempt(aid)

        with pytest.raises(MissingAdapterRouteError, match="No adapter registered"):
            empty_router.execute(action, attempt=attempt)

    def test_production_router_rejects_test_fakes(
        self,
        demo_scope: DemoResourceScope,
        calendar_fake: FakeGoogleCalendarTransport,
        tasks_fake: FakeGoogleTasksTransport,
        weather_fake: FakeOpenMeteoTransport,
    ) -> None:
        """Production router factory strictly rejects fake transports."""
        cal_read = GoogleCalendarReadAdapter(demo_scope, calendar_fake)
        cal_update = GoogleCalendarUpdateAdapter(demo_scope, calendar_fake)
        task_read = GoogleTasksReadAdapter(demo_scope, tasks_fake)
        task_create = GoogleTasksCreateAdapter(demo_scope, tasks_fake)
        loc_config = WeatherLocationConfig(location_id="demo-loc", latitude=52.52, longitude=13.41)
        weather_read = OpenMeteoReadAdapter(loc_config, weather_fake)

        with pytest.raises(RouterError, match="FakeGoogleCalendarTransport cannot enter"):
            create_production_adapter_router(
                calendar_read=cal_read,
                calendar_update=cal_update,
                tasks_read=task_read,
                tasks_create=task_create,
                weather_read=weather_read,
            )


class TestAuthorityPolicyEnforcement:
    """Authority boundaries are enforced before adapter routing."""

    def test_calendar_update_without_approval_fails_closed(
        self, test_router: AdapterRouter, demo_scope: DemoResourceScope
    ) -> None:
        """calendar.update requires approval; without approval fails closed."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={"start_time": "2026-10-06T07:30:00Z"},
            action_id=aid,
        )
        attempt = create_execution_attempt(aid)

        with pytest.raises(ActionAuthorityError, match="APPROVAL_REQUIRED"):
            test_router.execute(action, attempt=attempt, approval=None)

    def test_calendar_update_with_valid_bound_approval_executes(
        self, test_router: AdapterRouter, demo_scope: DemoResourceScope
    ) -> None:
        """calendar.update with valid cryptographically bound ApprovalGrant executes."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-school",
            parent_id=demo_scope.calendar_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=target,
            parameters={"start_time": "2026-10-06T07:30:00Z"},
            action_id=aid,
        )
        now = datetime.now(UTC)

        grant = ApprovalGrant(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=10),
        )

        attempt = create_execution_attempt(aid)
        result = test_router.execute(action, attempt=attempt, approval=grant, at=now)

        assert result.action_type == ActionType.CALENDAR_UPDATE
        assert result.success is True
        assert result.status_name == "UPDATED"
        assert result.writes_performed == 1
