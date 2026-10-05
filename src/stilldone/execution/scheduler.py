"""Deterministic action scheduler and dependency ordering.

Phase P-08.02:
Schedules actions from an immutable MissionExecutionContract in deterministic,
dependency-safe order.

Laws:
- Deterministic topological ordering with stable tie-breaking.
- Dependency-safe execution order; dependencies must be satisfied before dependents.
- Cycles or impossible dependencies FAIL CLOSED immediately.
- Zero model involvement, zero randomness, zero implicit parallelism.
- Pure function: zero provider calls, zero evidence artifacts, zero state mutations.
- Output references canonical existing ActionIds.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from stilldone.domain.action import ActionId
from stilldone.domain.mission import MissionId
from stilldone.execution.contracts import (
    DependencyCycleError,
    ExecutionContractTypeError,
    ExecutionContractValueError,
    MissingDependencyError,
    MissionExecutionContract,
)


@dataclass(frozen=True)
class ExecutionSchedule:
    """Immutable deterministic schedule of action execution order.

    Binds mission identity and ordered tuple of canonical ActionIds.
    """

    mission_id: MissionId
    ordered_action_ids: tuple[ActionId, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise ExecutionContractTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.ordered_action_ids, tuple):
            raise ExecutionContractTypeError(
                f"ordered_action_ids must be a tuple, got {type(self.ordered_action_ids).__name__}"
            )
        if len(self.ordered_action_ids) == 0:
            raise ExecutionContractValueError("ordered_action_ids cannot be empty")
        for i, aid in enumerate(self.ordered_action_ids):
            if not isinstance(aid, ActionId):
                raise ExecutionContractTypeError(
                    f"Schedule item {i} must be an ActionId, got {type(aid).__name__}"
                )

    def __iter__(self) -> Iterator[ActionId]:
        return iter(self.ordered_action_ids)

    def __len__(self) -> int:
        return len(self.ordered_action_ids)

    def __getitem__(self, index: int) -> ActionId:
        return self.ordered_action_ids[index]


def schedule_execution(contract: MissionExecutionContract) -> ExecutionSchedule:
    """Deterministically schedule actions from an immutable execution contract.

    Uses topological sorting with deterministic tie-breaking based on the
    action's original compilation index in the contract.

    Args:
        contract: An immutable MissionExecutionContract.

    Returns:
        Immutable ExecutionSchedule containing ordered ActionIds.

    Raises:
        ExecutionContractTypeError: If contract is not a MissionExecutionContract.
        MissingDependencyError: If a dependency references an unknown ActionId.
        DependencyCycleError: If a dependency cycle is detected.
    """
    if not isinstance(contract, MissionExecutionContract):
        raise ExecutionContractTypeError(
            f"contract must be a MissionExecutionContract instance, got {type(contract).__name__}"
        )

    action_ids = [action.action_id for action in contract.actions]
    index_map: dict[ActionId, int] = {aid: idx for idx, aid in enumerate(action_ids)}
    known_ids: set[ActionId] = set(action_ids)

    # In-degree tracking and adjacency graph
    in_degree: dict[ActionId, int] = {}
    dependents: dict[ActionId, list[ActionId]] = {aid: [] for aid in action_ids}

    for aid in action_ids:
        deps = contract.dependencies.get(aid, frozenset())
        for dep in deps:
            if dep not in known_ids:
                raise MissingDependencyError(f"Action {aid} depends on unknown ActionId {dep}")
            if dep == aid:
                raise DependencyCycleError(f"Action {aid} cannot depend on itself")
            dependents[dep].append(aid)

        in_degree[aid] = len(deps)

    # Ready list: actions with zero unscheduled dependencies
    ready: list[ActionId] = [aid for aid in action_ids if in_degree[aid] == 0]
    # Deterministic tie-breaking: sort by original compilation order
    ready.sort(key=lambda a: index_map[a])

    ordered_action_ids: list[ActionId] = []

    while ready:
        # Pop lowest index item
        current = ready.pop(0)
        ordered_action_ids.append(current)

        for dep_action in dependents[current]:
            in_degree[dep_action] -= 1
            if in_degree[dep_action] == 0:
                ready.append(dep_action)
                # Maintain deterministic order
                ready.sort(key=lambda a: index_map[a])

    if len(ordered_action_ids) < len(action_ids):
        raise DependencyCycleError(
            "Dependency cycle detected in execution contract: not all actions could be scheduled"
        )

    return ExecutionSchedule(
        mission_id=contract.mission_id,
        ordered_action_ids=tuple(ordered_action_ids),
    )
