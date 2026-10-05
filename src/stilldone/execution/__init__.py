"""Deterministic mission execution engine for StillDone.

Phase P-08:
Executes compiled candidate plans without letting planner prose own execution truth.

Submodules:
- contracts: Immutable execution contracts and symbolic target resolver.
- compiler: Mission compiler from validated CandidatePlanProposal to MissionExecutionContract.
- scheduler: Deterministic action scheduler and dependency ordering.
- state: Partial-failure preservation and per-step execution states.
- attempts: Execution attempts and provider-result recording.
- router: No-silent-fallback adapter routing.
- engine: Unified deterministic mission execution engine.
"""

from __future__ import annotations

from stilldone.execution.attempts import (
    create_execution_attempt,
    record_calendar_read_result,
    record_calendar_update_result,
    record_provider_exception,
    record_provider_result,
    record_task_create_result,
    record_task_read_result,
    record_weather_read_result,
)
from stilldone.execution.compiler import compile_candidate_plan
from stilldone.execution.contracts import (
    DependencyCycleError,
    ExecutionContractError,
    ExecutionContractTypeError,
    ExecutionContractValueError,
    MissingDependencyError,
    MissionExecutionContract,
    SymbolicTargetResolver,
    TargetResolutionError,
    UnsupportedActionError,
)
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
    UnsupportedActionRouteError,
    WeatherReadHandler,
    create_production_adapter_router,
)
from stilldone.execution.scheduler import ExecutionSchedule, schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
    MissionExecutionRecord,
    ProviderExecutionResult,
    StepExecutionRecord,
)

__all__ = [
    "ActionAuthorityError",
    "ActionExecutionStatus",
    "ActionHandler",
    "AdapterRouter",
    "CalendarReadHandler",
    "CalendarUpdateHandler",
    "DependencyCycleError",
    "ExecutionContractError",
    "ExecutionContractTypeError",
    "ExecutionContractValueError",
    "ExecutionSchedule",
    "ExecutionStateTracker",
    "MissingAdapterRouteError",
    "MissingDependencyError",
    "MissionExecutionContract",
    "MissionExecutionRecord",
    "ProviderExecutionResult",
    "RouterError",
    "StepExecutionRecord",
    "SymbolicTargetResolver",
    "TargetResolutionError",
    "TasksCreateHandler",
    "TasksReadHandler",
    "UnsupportedActionError",
    "UnsupportedActionRouteError",
    "WeatherReadHandler",
    "compile_candidate_plan",
    "create_execution_attempt",
    "create_production_adapter_router",
    "record_calendar_read_result",
    "record_calendar_update_result",
    "record_provider_exception",
    "record_provider_result",
    "record_task_create_result",
    "record_task_read_result",
    "record_weather_read_result",
    "schedule_execution",
]
