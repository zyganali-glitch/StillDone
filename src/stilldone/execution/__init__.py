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

__all__ = [
    "DependencyCycleError",
    "ExecutionContractError",
    "ExecutionContractTypeError",
    "ExecutionContractValueError",
    "MissingDependencyError",
    "MissionExecutionContract",
    "SymbolicTargetResolver",
    "TargetResolutionError",
    "UnsupportedActionError",
    "compile_candidate_plan",
]
