"""Tests for Phase P-08.06: Mixed Mission Outcomes and Test Hardening.

Validates the 10 canonical mission-level deterministic execution scenarios:
1. earlier success -> later failure -> downstream NOT_RUN/BLOCKED.
2. independent branch may continue after sibling failure when dependencies allow.
3. provider execution success does NOT create VERIFIED.
4. provider execution success does NOT create READY.
5. blocked action has zero attempt.
6. NOT_RUN action has zero attempt/provider result.
7. failed action preserves exact attempted action and provider failure.
8. no action executes twice.
9. no foreign ActionId enters the mission record.
10. no silent fallback is triggered during mixed failures.

Strict laws:
- Zero live/network calls; deterministic test fakes only.
- P-08 engine is test-hardened without redesigning P-08 contracts.
- P-08 does not implement verifier/predicate logic (owned by P-09).
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId
from stilldone.execution.attempts import create_execution_attempt
from stilldone.execution.contracts import (
    ExecutionContractValueError,
    ExecutionTransitionError,
    MissionExecutionContract,
    UnknownActionIdError,
)
from stilldone.execution.router import (
    ActionHandler,
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
    MissingAdapterRouteError,
    TasksCreateHandler,
    TasksReadHandler,
    WeatherReadHandler,
)
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
    MissionExecutionRecord,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.transitions import IllegalStatePromotionError, assert_can_promote_to_ready

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="demo-cal-batch-p0806",
        task_list_id="demo-tasks-batch-p0806",
    )


@pytest.fixture
def calendar_fake(demo_scope: DemoResourceScope) -> FakeGoogleCalendarTransport:
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=demo_scope.calendar_id,
        event_id="evt-school-bus",
        summary="Leave for school",
        start_time="2026-10-06T07:45:00Z",
        end_time="2026-10-06T08:15:00Z",
        all_day=False,
        status="confirmed",
    )
    return transport


@pytest.fixture
def tasks_fake(demo_scope: DemoResourceScope) -> FakeGoogleTasksTransport:
    transport = FakeGoogleTasksTransport()
    transport.seed_task(
        task_list_id=demo_scope.task_list_id,
        task_id="task-backpacks",
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
    cal_read = GoogleCalendarReadAdapter(demo_scope, calendar_fake)
    cal_update = GoogleCalendarUpdateAdapter(demo_scope, calendar_fake)
    tasks_read = GoogleTasksReadAdapter(demo_scope, tasks_fake)
    tasks_create = GoogleTasksCreateAdapter(demo_scope, tasks_fake)
    loc_config = WeatherLocationConfig(
        location_id="loc-test-p0806",
        latitude=52.52,
        longitude=13.41,
    )
    weather_read = OpenMeteoReadAdapter(loc_config, weather_fake)

    routes: dict[ActionType, ActionHandler] = {
        ActionType.CALENDAR_READ: CalendarReadHandler(cal_read),
        ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(cal_update),
        ActionType.TASK_READ: TasksReadHandler(tasks_read),
        ActionType.TASK_CREATE: TasksCreateHandler(tasks_create),
        ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
    }
    return AdapterRouter(routes)


def execute_mission_pipeline(
    contract: MissionExecutionContract,
    router: AdapterRouter,
    *,
    injected_failures: dict[ActionId, Exception | str] | None = None,
) -> MissionExecutionRecord:
    """Deterministic mission runner driving the scheduled steps through tracker and router."""
    failures = injected_failures or {}
    schedule = schedule_execution(contract)
    tracker = ExecutionStateTracker(contract, schedule)
    now = datetime.now(UTC)

    action_map = {act.action_id: act for act in contract.actions}

    for action_id in schedule.ordered_action_ids:
        can_run, _ = tracker.can_execute(action_id)
        if not can_run:
            # Step cannot run (e.g. dependency blocked or not yet satisfied)
            continue

        tracker.mark_in_progress(action_id)
        action = action_map[action_id]
        attempt = create_execution_attempt(action_id)

        # Injected failure for testing
        if action_id in failures:
            fail_val = failures[action_id]
            err_msg = str(fail_val) if isinstance(fail_val, Exception) else fail_val
            fake_res = ProviderExecutionResult(
                action_type=action.action_type,
                success=False,
                status_name="INJECTED_FAILURE",
                captured_at=now,
                error_message=err_msg,
            )
            tracker.record_failure(
                action_id,
                attempt=attempt,
                provider_result=fake_res,
                error_message=err_msg,
            )
            continue

        try:
            result = router.execute(action, attempt=attempt, at=now)
            if result.success:
                tracker.record_success(action_id, attempt=attempt, provider_result=result)
            else:
                tracker.record_failure(
                    action_id,
                    attempt=attempt,
                    provider_result=result,
                    error_message=result.error_message or "Provider returned failure",
                )
        except Exception as exc:
            tracker.record_failure(
                action_id,
                attempt=attempt,
                provider_result=None,
                error_message=f"Router error: {exc}",
            )

    return tracker.snapshot()


# ===========================================================================
# 10 Required Scenarios
# ===========================================================================


class TestP0806MixedMissionScenarios:
    """The 10 mandatory mixed success/failure/not-run mission test scenarios."""

    def test_scenario_01_earlier_success_later_failure_downstream_blocked(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 1: earlier success -> later failure -> downstream NOT_RUN/BLOCKED.

        Chain: A (CALENDAR_READ) -> B (TASK_CREATE) -> C (TASK_READ).
        A succeeds. B fails. C is BLOCKED.
        """
        mid = MissionId.generate()
        aid_a = ActionId.generate()
        aid_b = ActionId.generate()
        aid_c = ActionId.generate()

        action_a = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school-bus",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid_a,
        )
        action_b = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK_LIST,
                resource_id=demo_scope.task_list_id,
                parent_id=None,
            ),
            parameters={"title": "Pack lunch"},
            action_id=aid_b,
        )
        action_c = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="task-backpacks",
                parent_id=demo_scope.task_list_id,
            ),
            parameters={},
            action_id=aid_c,
        )

        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action_a, action_b, action_c),
            dependencies={
                aid_a: frozenset(),
                aid_b: frozenset({aid_a}),
                aid_c: frozenset({aid_b}),
            },
        )

        snapshot = execute_mission_pipeline(
            contract,
            test_router,
            injected_failures={aid_b: "Simulated task creation outage"},
        )

        # A succeeded
        rec_a = snapshot.step_records[aid_a]
        assert rec_a.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert rec_a.attempt is not None
        assert rec_a.provider_result is not None
        assert rec_a.provider_result.success is True

        # B failed
        rec_b = snapshot.step_records[aid_b]
        assert rec_b.status == ActionExecutionStatus.EXECUTION_FAILED
        assert rec_b.attempt is not None
        assert rec_b.provider_result is not None
        assert rec_b.provider_result.success is False
        assert "Simulated task creation outage" in (rec_b.error_message or "")

        # C is BLOCKED by B
        rec_c = snapshot.step_records[aid_c]
        assert rec_c.status == ActionExecutionStatus.BLOCKED
        assert rec_c.blocked_by == aid_b
        assert rec_c.attempt is None
        assert rec_c.provider_result is None

        # Aggregate invariants
        assert snapshot.has_failures is True
        assert snapshot.has_blocked is True
        assert snapshot.is_all_succeeded is False

    def test_scenario_02_independent_branch_continues_after_sibling_failure(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 2: independent branch may continue after sibling failure.

        Branch 1: A (CALENDAR_READ) -> C (TASK_CREATE depends on A)
        Branch 2: B (WEATHER_READ) -> D (TASK_READ depends on B)
        A fails -> C blocked.
        B succeeds -> D succeeds.
        """
        mid = MissionId.generate()
        aid_a = ActionId.generate()
        aid_b = ActionId.generate()
        aid_c = ActionId.generate()
        aid_d = ActionId.generate()

        action_a = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school-bus",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid_a,
        )
        action_b = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="loc-test-p0806",
                parent_id=None,
            ),
            parameters={},
            action_id=aid_b,
        )
        action_c = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK_LIST,
                resource_id=demo_scope.task_list_id,
                parent_id=None,
            ),
            parameters={"title": "Action depending on A"},
            action_id=aid_c,
        )
        action_d = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="task-backpacks",
                parent_id=demo_scope.task_list_id,
            ),
            parameters={},
            action_id=aid_d,
        )

        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action_a, action_b, action_c, action_d),
            dependencies={
                aid_a: frozenset(),
                aid_b: frozenset(),
                aid_c: frozenset({aid_a}),
                aid_d: frozenset({aid_b}),
            },
        )

        snapshot = execute_mission_pipeline(
            contract,
            test_router,
            injected_failures={aid_a: "Calendar 500 internal error"},
        )

        # Branch 1 failed and blocked
        assert snapshot.get_status(aid_a) == ActionExecutionStatus.EXECUTION_FAILED
        assert snapshot.get_status(aid_c) == ActionExecutionStatus.BLOCKED
        assert snapshot.step_records[aid_c].blocked_by == aid_a

        # Branch 2 completed cleanly despite sibling failure
        assert snapshot.get_status(aid_b) == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert snapshot.get_status(aid_d) == ActionExecutionStatus.EXECUTION_SUCCEEDED

    def test_scenario_03_provider_execution_success_does_not_create_verified(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 3: provider execution success does NOT create VERIFIED."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school-bus",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid,
        )
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action,),
            dependencies={aid: frozenset()},
        )
        snapshot = execute_mission_pipeline(contract, test_router)

        rec = snapshot.step_records[aid]
        assert rec.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert rec.status.value != "VERIFIED"
        assert not hasattr(rec, "verified")

        # ActionExecutionStatus vocabulary strictly excludes VERIFIED
        allowed_statuses = {s.value for s in ActionExecutionStatus}
        assert "VERIFIED" not in allowed_statuses
        assert StepEvidenceState.VERIFIED.value not in allowed_statuses

    def test_scenario_04_provider_execution_success_does_not_create_ready(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 4: provider execution success does NOT create READY."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="loc-test-p0806",
                parent_id=None,
            ),
            parameters={},
            action_id=aid,
        )
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action,),
            dependencies={aid: frozenset()},
        )
        snapshot = execute_mission_pipeline(contract, test_router)

        # is_all_succeeded refers strictly to execution level, NOT mission readiness
        assert snapshot.is_all_succeeded is True
        assert not hasattr(snapshot, "state")
        assert not hasattr(snapshot, "ready")

        # In transitions.py: promotion to READY directly from EXECUTED_UNVERIFIED
        # or non-VERIFYING state is strictly forbidden
        with pytest.raises(IllegalStatePromotionError):
            assert_can_promote_to_ready(
                current_state=MissionState.EXECUTING,
                step_evidence_states=[StepEvidenceState.EXECUTED_UNVERIFIED],
            )

    def test_scenario_05_blocked_action_has_zero_attempt(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 5: blocked action has zero attempt."""
        mid = MissionId.generate()
        aid1 = ActionId.generate()
        aid2 = ActionId.generate()

        action1 = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="loc-test-p0806",
                parent_id=None,
            ),
            parameters={},
            action_id=aid1,
        )
        action2 = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="task-backpacks",
                parent_id=demo_scope.task_list_id,
            ),
            parameters={},
            action_id=aid2,
        )

        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action1, action2),
            dependencies={aid1: frozenset(), aid2: frozenset({aid1})},
        )

        snapshot = execute_mission_pipeline(
            contract,
            test_router,
            injected_failures={aid1: "Weather service unavailable"},
        )

        blocked_rec = snapshot.step_records[aid2]
        assert blocked_rec.status == ActionExecutionStatus.BLOCKED
        assert blocked_rec.attempt is None

        # Structural impossibility to attach attempt to BLOCKED step
        attempt = create_execution_attempt(aid2)
        with pytest.raises(
            ExecutionContractValueError, match="BLOCKED step cannot have an attempt"
        ):
            StepExecutionRecord(
                action_id=aid2,
                status=ActionExecutionStatus.BLOCKED,
                attempt=attempt,
                blocked_by=aid1,
            )

    def test_scenario_06_not_run_action_has_zero_attempt_or_provider_result(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Scenario 6: NOT_RUN action has zero attempt/provider result."""
        mid = MissionId.generate()
        aid1 = ActionId.generate()
        aid2 = ActionId.generate()

        action1 = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="loc-test-p0806",
                parent_id=None,
            ),
            parameters={},
            action_id=aid1,
        )
        action2 = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school-bus",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid2,
        )

        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action1, action2),
            dependencies={aid1: frozenset(), aid2: frozenset()},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        # Before any execution, both actions are NOT_RUN
        snapshot = tracker.snapshot()
        for aid in (aid1, aid2):
            rec = snapshot.step_records[aid]
            assert rec.status == ActionExecutionStatus.NOT_RUN
            assert rec.attempt is None
            assert rec.provider_result is None
            assert rec.blocked_by is None

        # Attaching attempt or provider_result to NOT_RUN step fails closed
        attempt = create_execution_attempt(aid1)
        with pytest.raises(
            ExecutionContractValueError, match="NOT_RUN step cannot have an attempt"
        ):
            StepExecutionRecord(
                action_id=aid1,
                status=ActionExecutionStatus.NOT_RUN,
                attempt=attempt,
            )

        dummy_res = ProviderExecutionResult(
            action_type=ActionType.WEATHER_READ,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(
            ExecutionContractValueError, match="NOT_RUN step cannot have a provider_result"
        ):
            StepExecutionRecord(
                action_id=aid1,
                status=ActionExecutionStatus.NOT_RUN,
                provider_result=dummy_res,
            )

    def test_scenario_07_failed_action_preserves_exact_attempt_and_provider_failure(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 7: failed action preserves exact attempted action and provider failure."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school-bus",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid,
        )
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action,),
            dependencies={aid: frozenset()},
        )

        error_text = "Google Calendar API rate limit exceeded 429"
        snapshot = execute_mission_pipeline(
            contract,
            test_router,
            injected_failures={aid: error_text},
        )

        rec = snapshot.step_records[aid]
        assert rec.status == ActionExecutionStatus.EXECUTION_FAILED
        assert rec.attempt is not None
        assert rec.attempt.action_id == aid
        assert rec.provider_result is not None
        assert rec.provider_result.action_type == ActionType.CALENDAR_READ
        assert rec.provider_result.success is False
        assert rec.provider_result.status_name == "INJECTED_FAILURE"
        assert error_text in (rec.error_message or "")

    def test_scenario_08_no_action_executes_twice(
        self,
        demo_scope: DemoResourceScope,
        test_router: AdapterRouter,
    ) -> None:
        """Scenario 8: no action executes twice."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="loc-test-p0806",
                parent_id=None,
            ),
            parameters={},
            action_id=aid,
        )
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action,),
            dependencies={aid: frozenset()},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        # First run transitions cleanly
        tracker.mark_in_progress(aid)
        attempt = create_execution_attempt(aid)
        res = test_router.execute(action, attempt=attempt)
        tracker.record_success(aid, attempt=attempt, provider_result=res)

        # Attempting to re-execute fails closed
        with pytest.raises(ExecutionTransitionError, match="Cannot transition action"):
            tracker.mark_in_progress(aid)

        with pytest.raises(ExecutionTransitionError, match="action must be in IN_PROGRESS"):
            tracker.record_success(aid, attempt=attempt, provider_result=res)

        with pytest.raises(ExecutionTransitionError, match="action must be in IN_PROGRESS"):
            tracker.record_failure(aid, attempt=attempt, provider_result=None, error_message="err")

    def test_scenario_09_no_foreign_action_id_enters_mission_record(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        """Scenario 9: no foreign ActionId enters the mission record."""
        mid = MissionId.generate()
        aid = ActionId.generate()
        foreign_aid = ActionId.generate()

        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id="loc-test-p0806",
                parent_id=None,
            ),
            parameters={},
            action_id=aid,
        )
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action,),
            dependencies={aid: frozenset()},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        # All operations with foreign_aid fail closed
        with pytest.raises(UnknownActionIdError):
            tracker.can_execute(foreign_aid)

        with pytest.raises(UnknownActionIdError):
            tracker.mark_in_progress(foreign_aid)

        foreign_attempt = create_execution_attempt(foreign_aid)
        dummy_res = ProviderExecutionResult(
            action_type=ActionType.WEATHER_READ,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(UnknownActionIdError):
            tracker.record_success(foreign_aid, foreign_attempt, dummy_res)

        with pytest.raises(UnknownActionIdError):
            tracker.record_failure(foreign_aid, foreign_attempt, None, "err")

        with pytest.raises(UnknownActionIdError):
            tracker.record_blocked(foreign_aid, blocked_by=aid)

        snapshot = tracker.snapshot()
        with pytest.raises(UnknownActionIdError):
            snapshot.get_status(foreign_aid)

        assert set(snapshot.step_records.keys()) == {aid}

    def test_scenario_10_no_silent_fallback_during_mixed_failures(
        self,
        demo_scope: DemoResourceScope,
        calendar_fake: FakeGoogleCalendarTransport,
        tasks_fake: FakeGoogleTasksTransport,
        weather_fake: FakeOpenMeteoTransport,
    ) -> None:
        """Scenario 10: no silent fallback is triggered during mixed failures."""
        # Create a router missing CALENDAR_READ route
        tasks_read = GoogleTasksReadAdapter(demo_scope, tasks_fake)
        loc_config = WeatherLocationConfig(
            location_id="loc-test-p0806",
            latitude=52.52,
            longitude=13.41,
        )
        weather_read = OpenMeteoReadAdapter(loc_config, weather_fake)

        partial_routes: dict[ActionType, ActionHandler] = {
            ActionType.TASK_READ: TasksReadHandler(tasks_read),
            ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
        }
        partial_router = AdapterRouter(partial_routes)

        mid = MissionId.generate()
        aid_cal = ActionId.generate()
        cal_action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-school-bus",
                parent_id=demo_scope.calendar_id,
            ),
            parameters={},
            action_id=aid_cal,
        )
        cal_attempt = create_execution_attempt(aid_cal)

        # Fails closed with MissingAdapterRouteError rather than falling back silently
        with pytest.raises(MissingAdapterRouteError, match="No adapter registered for action type"):
            partial_router.execute(cal_action, attempt=cal_attempt)
