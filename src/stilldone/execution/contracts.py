"""Deterministic execution contracts and symbolic target resolution.

Phase P-08.01:
Defines the immutable execution-contract aggregate produced by the mission
compiler, deterministic symbolic target resolution, and fail-closed validation.

Laws:
- Model output is a proposal only; runtime owns execution contracts and identities.
- ActionIds are runtime-owned opaque identities; models cannot inject them.
- Target resolution maps bounded SymbolicTargetRef to canonical TargetIdentity.
- Unsupported actions, incompatible targets, or missing scopes fail closed.
- Zero provider calls, zero EvidenceIds, zero ApprovalGrants, zero VERIFIED/READY truth.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field

from stilldone.action_policy import validate_action_contract
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.execution import ResourceBinding
from stilldone.domain.mission import MissionId
from stilldone.planning.contracts import (
    ACTION_SYMBOLIC_TARGET_COMPATIBILITY,
    SymbolicTargetRef,
)

# ===========================================================================
# Execution Contract Exceptions
# ===========================================================================


class ExecutionContractError(Exception):
    """Base exception for all execution contract and compilation errors."""


class ExecutionContractTypeError(ExecutionContractError, TypeError):
    """Raised when an object or field has an invalid type."""


class ExecutionContractValueError(ExecutionContractError, ValueError):
    """Raised when a field value violates constraints."""


class TargetResolutionError(ExecutionContractError, ValueError):
    """Raised when a symbolic target reference cannot be resolved."""


class UnsupportedActionError(ExecutionContractError, ValueError):
    """Raised when an action is unsupported by execution engine."""


class MissingDependencyError(ExecutionContractError, ValueError):
    """Raised when an action dependency references an unknown ActionId."""


class DependencyCycleError(ExecutionContractError, ValueError):
    """Raised when a cycle is detected in the action dependency graph."""


class UnknownActionIdError(ExecutionContractValueError):
    """Raised when an ActionId is not recognized in the execution contract or schedule."""


class ExecutionTransitionError(ExecutionContractValueError):
    """Raised when an invalid step execution state transition is attempted."""


class ExecutionLineageError(ExecutionContractValueError):
    """Raised when an execution attempt or provider result does not match action lineage."""


# ===========================================================================
# Deterministic Symbolic Target Resolver
# ===========================================================================


class SymbolicTargetResolver:
    """Deterministic resolver translating SymbolicTargetRef to canonical TargetIdentity.

    Reuses DemoResourceScope to ensure Google Calendar and Google Tasks targets
    bind to the configured disposable demo resources.
    """

    def __init__(
        self,
        *,
        scope: DemoResourceScope | None = None,
        weather_location_id: str = "demo_weather_location",
        event_id_mappings: Mapping[SymbolicTargetRef | str, str] | None = None,
        task_id_mappings: Mapping[SymbolicTargetRef | str, str] | None = None,
        custom_targets: (
            Mapping[tuple[ActionType, SymbolicTargetRef], TargetIdentity] | None
        ) = None,
    ) -> None:
        if scope is not None and not isinstance(scope, DemoResourceScope):
            raise ExecutionContractTypeError(
                f"scope must be a DemoResourceScope instance or None, got {type(scope).__name__}"
            )
        if not isinstance(weather_location_id, str) or not weather_location_id.strip():
            raise ExecutionContractValueError("weather_location_id must be a non-empty string")

        self._scope = scope
        self._weather_location_id = weather_location_id.strip()

        # Build normalized event ID mappings
        self._event_ids: dict[SymbolicTargetRef, str] = {}
        if event_id_mappings:
            for k, v in event_id_mappings.items():
                ref = k if isinstance(k, SymbolicTargetRef) else SymbolicTargetRef(k)
                if not isinstance(v, str) or not v.strip():
                    raise ExecutionContractValueError(
                        f"Event ID mapping for {ref.value!r} must be a non-empty string"
                    )
                self._event_ids[ref] = v.strip()

        # Build normalized task ID mappings
        self._task_ids: dict[SymbolicTargetRef, str] = {}
        if task_id_mappings:
            for k, v in task_id_mappings.items():
                ref = k if isinstance(k, SymbolicTargetRef) else SymbolicTargetRef(k)
                if not isinstance(v, str) or not v.strip():
                    raise ExecutionContractValueError(
                        f"Task ID mapping for {ref.value!r} must be a non-empty string"
                    )
                self._task_ids[ref] = v.strip()

        # Build custom targets mapping
        self._custom_targets: dict[tuple[ActionType, SymbolicTargetRef], TargetIdentity] = {}
        if custom_targets:
            for (at, tr), ti in custom_targets.items():
                if not isinstance(at, ActionType) or not isinstance(tr, SymbolicTargetRef):
                    raise ExecutionContractTypeError(
                        "custom_targets keys must be (ActionType, SymbolicTargetRef)"
                    )
                if not isinstance(ti, TargetIdentity):
                    raise ExecutionContractTypeError("custom_targets values must be TargetIdentity")
                self._custom_targets[(at, tr)] = ti

    @property
    def scope(self) -> DemoResourceScope | None:
        """The configured demo resource scope, if any."""
        return self._scope

    def resolve(
        self,
        action_type: ActionType,
        target_ref: SymbolicTargetRef,
    ) -> tuple[TargetIdentity, ResourceBinding]:
        """Resolve a symbolic target reference for a given action type.

        Returns:
            A tuple of (canonical TargetIdentity, canonical ResourceBinding).

        Raises:
            ExecutionContractTypeError: If action_type or target_ref has invalid type.
            TargetResolutionError: If target cannot be resolved or is incompatible.
        """
        if not isinstance(action_type, ActionType):
            raise ExecutionContractTypeError(
                f"action_type must be an ActionType instance, got {type(action_type).__name__}"
            )
        if not isinstance(target_ref, SymbolicTargetRef):
            raise ExecutionContractTypeError(
                f"target_ref must be a SymbolicTargetRef instance, got {type(target_ref).__name__}"
            )

        # Check action-to-symbolic-target compatibility
        allowed_targets = ACTION_SYMBOLIC_TARGET_COMPATIBILITY.get(action_type, frozenset())
        if target_ref not in allowed_targets:
            msg = (
                f"Symbolic target {target_ref.value!r} is incompatible "
                f"with action {action_type.value!r}"
            )
            raise TargetResolutionError(msg)

        # Check explicit custom target mappings first
        if (action_type, target_ref) in self._custom_targets:
            concrete = self._custom_targets[(action_type, target_ref)]
            requested = TargetIdentity(
                system=concrete.system,
                resource_kind=concrete.resource_kind,
                resource_id=target_ref.value,
                parent_id=concrete.parent_id,
            )
            binding = ResourceBinding(requested_target=requested, resolved_target=concrete)
            return concrete, binding

        # Google Calendar actions
        if action_type in (ActionType.CALENDAR_READ, ActionType.CALENDAR_UPDATE):
            if self._scope is None:
                raise TargetResolutionError(
                    f"DemoResourceScope is required to resolve target for {action_type.value!r}"
                )
            event_id = self._event_ids.get(target_ref, target_ref.value)
            concrete = TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=event_id,
                parent_id=self._scope.calendar_id,
            )
            requested = TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=target_ref.value,
                parent_id=self._scope.calendar_id,
            )
            binding = ResourceBinding(requested_target=requested, resolved_target=concrete)
            return concrete, binding

        # Google Tasks create action
        if action_type == ActionType.TASK_CREATE:
            if self._scope is None:
                raise TargetResolutionError(
                    f"DemoResourceScope is required to resolve target for {action_type.value!r}"
                )
            concrete = TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK_LIST,
                resource_id=self._scope.task_list_id,
                parent_id=None,
            )
            requested = TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK_LIST,
                resource_id=self._scope.task_list_id,
                parent_id=None,
            )
            # Before creation, resolved child task is None
            binding = ResourceBinding(requested_target=requested, resolved_target=None)
            return concrete, binding

        # Google Tasks read action
        if action_type == ActionType.TASK_READ:
            if self._scope is None:
                raise TargetResolutionError(
                    f"DemoResourceScope is required to resolve target for {action_type.value!r}"
                )
            task_id = self._task_ids.get(target_ref, target_ref.value)
            concrete = TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id=task_id,
                parent_id=self._scope.task_list_id,
            )
            requested = TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id=target_ref.value,
                parent_id=self._scope.task_list_id,
            )
            binding = ResourceBinding(requested_target=requested, resolved_target=concrete)
            return concrete, binding

        # Open-Meteo weather read action
        if action_type == ActionType.WEATHER_READ:
            concrete = TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id=self._weather_location_id,
                parent_id=None,
            )
            requested = TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id=target_ref.value,
                parent_id=None,
            )
            binding = ResourceBinding(requested_target=requested, resolved_target=concrete)
            return concrete, binding

        raise TargetResolutionError(
            f"Unsupported action type for target resolution: {action_type.value!r}"
        )


# ===========================================================================
# Immutable Mission Execution Contract Aggregate
# ===========================================================================


@dataclass(frozen=True)
class MissionExecutionContract:
    """Immutable deterministic execution contract aggregate.

    Represents a compiled, validated plan ready for deterministic scheduling
    and execution.
    Contains runtime-owned ActionContracts, ActionIds, and dependency metadata.
    Does NOT contain provider execution facts, EvidenceIds, ApprovalGrants,
    or VERIFIED/READY states.
    """

    mission_id: MissionId
    actions: tuple[ActionContract, ...]
    dependencies: Mapping[ActionId, frozenset[ActionId]]
    resource_bindings: Mapping[ActionId, ResourceBinding] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise ExecutionContractTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )

        if not isinstance(self.actions, tuple):
            raise ExecutionContractTypeError(
                f"actions must be a tuple of ActionContract, got {type(self.actions).__name__}"
            )

        if len(self.actions) == 0:
            raise ExecutionContractValueError("actions tuple cannot be empty")

        action_ids: set[ActionId] = set()
        for i, action in enumerate(self.actions):
            if not isinstance(action, ActionContract):
                raise ExecutionContractTypeError(
                    f"Step {i} must be an ActionContract instance, got {type(action).__name__}"
                )
            if action.mission_id != self.mission_id:
                raise ExecutionContractValueError(
                    f"Action {action.action_id} mission_id {action.mission_id} does not "
                    f"match contract mission_id {self.mission_id}"
                )
            if action.action_id in action_ids:
                raise ExecutionContractValueError(f"Duplicate action_id: {action.action_id}")
            action_ids.add(action.action_id)

            # Validate each action against closed-world policy
            validate_action_contract(action)

        if not isinstance(self.dependencies, Mapping):
            raise ExecutionContractTypeError(
                f"dependencies must be a Mapping, got {type(self.dependencies).__name__}"
            )

        # Validate all dependencies reference known actions
        frozen_deps: dict[ActionId, frozenset[ActionId]] = {}
        for aid, deps in self.dependencies.items():
            if not isinstance(aid, ActionId):
                raise ExecutionContractTypeError(
                    f"Dependency key must be ActionId, got {type(aid).__name__}"
                )
            if aid not in action_ids:
                raise MissingDependencyError(
                    f"Dependency key {aid} is not an action in this contract"
                )

            if not isinstance(deps, (set, frozenset)):
                raise ExecutionContractTypeError(
                    f"Dependencies for {aid} must be a set or frozenset, got {type(deps).__name__}"
                )

            frozen_set = frozenset(deps)
            for dep in frozen_set:
                if not isinstance(dep, ActionId):
                    raise ExecutionContractTypeError(
                        f"Dependency entry for {aid} must be ActionId, got {type(dep).__name__}"
                    )
                if dep not in action_ids:
                    raise MissingDependencyError(f"Action {aid} depends on unknown ActionId {dep}")
                if dep == aid:
                    raise DependencyCycleError(f"Action {aid} cannot depend on itself")

            frozen_deps[aid] = frozen_set

        # Verify dependency graph is a valid DAG (cycle detection)
        _verify_no_cycles(frozen_deps, action_ids)

        # Canonicalize dependencies to read-only MappingProxyType
        object.__setattr__(self, "dependencies", types.MappingProxyType(frozen_deps))

        # Validate resource_bindings
        if not isinstance(self.resource_bindings, Mapping):
            raise ExecutionContractTypeError("resource_bindings must be a Mapping")
        frozen_bindings: dict[ActionId, ResourceBinding] = {}
        for aid, binding in self.resource_bindings.items():
            if not isinstance(aid, ActionId):
                raise ExecutionContractTypeError("resource_bindings key must be ActionId")
            if not isinstance(binding, ResourceBinding):
                raise ExecutionContractTypeError("resource_bindings value must be ResourceBinding")
            if aid not in action_ids:
                raise ExecutionContractValueError(
                    f"resource_bindings references unknown ActionId: {aid}"
                )
            frozen_bindings[aid] = binding
        object.__setattr__(self, "resource_bindings", types.MappingProxyType(frozen_bindings))


def _verify_no_cycles(
    dependencies: Mapping[ActionId, frozenset[ActionId]],
    action_ids: set[ActionId],
) -> None:
    """Verify that the dependency graph contains no cycles."""
    visited: set[ActionId] = set()
    rec_stack: set[ActionId] = set()

    def dfs(node: ActionId) -> None:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in dependencies.get(node, frozenset()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                raise DependencyCycleError(f"Dependency cycle detected involving action {neighbor}")

        rec_stack.remove(node)

    for aid in action_ids:
        if aid not in visited:
            dfs(aid)
