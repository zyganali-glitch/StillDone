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
    ExecutionDependencyError,
    ExecutionLineageError,
    ExecutionTransitionError,
    MissingDependencyError,
    MissionExecutionContract,
    SymbolicTargetResolver,
    TargetResolutionError,
    UnknownActionIdError,
    UnsupportedActionError,
)
from stilldone.execution.gate import (
    ApprovedActionReceipt,
    ApprovedCalendarUpdateOutcome,
    ApprovedExecutionPersistenceError,
    CalendarMutationSpy,
    ConflictingReadbackObservationError,
    ExecutionGateDecision,
    ExecutionGateError,
    ExecutionGateTypeError,
    ExecutionGateValueError,
    PendingApprovalBindingMismatchError,
    PlannerGateAuthorityError,
    ProviderMutationObservation,
    UnapprovedActionReceipt,
    UnapprovedMutationBlockedError,
    UnexpectedApprovalGrantError,
    create_approved_action_receipt,
    create_unapproved_action_receipt,
    evaluate_execution_gate,
    execute_approved_calendar_update,
    execute_gated_action,
)
from stilldone.execution.router import (
    ActionAuthorityError,
    ActionHandler,
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
    MissingAdapterRouteError,
    RouterError,
    RouterLineageError,
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
    "ApprovedActionReceipt",
    "ApprovedCalendarUpdateOutcome",
    "ApprovedExecutionPersistenceError",
    "CalendarMutationSpy",
    "CalendarReadHandler",
    "CalendarUpdateHandler",
    "ConflictingReadbackObservationError",
    "DependencyCycleError",
    "ExecutionContractError",
    "ExecutionContractTypeError",
    "ExecutionContractValueError",
    "ExecutionDependencyError",
    "ExecutionGateDecision",
    "ExecutionGateError",
    "ExecutionGateTypeError",
    "ExecutionGateValueError",
    "ExecutionLineageError",
    "ExecutionSchedule",
    "ExecutionStateTracker",
    "ExecutionTransitionError",
    "MissingAdapterRouteError",
    "MissingDependencyError",
    "MissionExecutionContract",
    "MissionExecutionRecord",
    "PendingApprovalBindingMismatchError",
    "PlannerGateAuthorityError",
    "ProviderExecutionResult",
    "ProviderMutationObservation",
    "RouterError",
    "RouterLineageError",
    "StepExecutionRecord",
    "SymbolicTargetResolver",
    "TargetResolutionError",
    "TasksCreateHandler",
    "TasksReadHandler",
    "UnapprovedActionReceipt",
    "UnapprovedMutationBlockedError",
    "UnexpectedApprovalGrantError",
    "UnknownActionIdError",
    "UnsupportedActionError",
    "UnsupportedActionRouteError",
    "WeatherReadHandler",
    "compile_candidate_plan",
    "create_approved_action_receipt",
    "create_execution_attempt",
    "create_production_adapter_router",
    "create_unapproved_action_receipt",
    "evaluate_execution_gate",
    "execute_approved_calendar_update",
    "execute_gated_action",
    "record_calendar_read_result",
    "record_calendar_update_result",
    "record_provider_exception",
    "record_provider_result",
    "record_task_create_result",
    "record_task_read_result",
    "record_weather_read_result",
    "schedule_execution",
]
