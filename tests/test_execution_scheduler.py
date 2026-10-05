"""Tests for Phase P-08.02: Deterministic Action Scheduler.

Validates that:
- Scheduler produces deterministic, dependency-safe execution ordering.
- Stable behavior across repeated scheduling runs.
- Missing dependencies fail closed with MissingDependencyError.
- Dependency cycles fail closed with DependencyCycleError.
- Independent actions use canonical deterministic tie-breaking (original plan index).
- Zero model involvement, zero randomness, zero implicit parallelism.
- Pure function: zero provider calls, zero evidence artifacts, zero state mutations.
"""

from __future__ import annotations

import pytest

from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import ActionId, ActionType
from stilldone.domain.mission import MissionId
from stilldone.execution.compiler import compile_candidate_plan
from stilldone.execution.contracts import (
    DependencyCycleError,
    ExecutionContractTypeError,
    MissingDependencyError,
    MissionExecutionContract,
    SymbolicTargetResolver,
)
from stilldone.execution.scheduler import ExecutionSchedule, schedule_execution
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    SymbolicTargetRef,
)


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="demo-cal-12345",
        task_list_id="demo-tasks-67890",
    )


@pytest.fixture
def resolver(demo_scope: DemoResourceScope) -> SymbolicTargetResolver:
    return SymbolicTargetResolver(scope=demo_scope)


@pytest.fixture
def sequential_two_step_contract(
    resolver: SymbolicTargetResolver,
) -> MissionExecutionContract:
    mid = MissionId.generate()
    p = CandidatePlanProposal.create(
        mission_id=mid,
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.CALENDAR_READ,
                target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
            ),
            CandidateActionProposal.create(
                action_type=ActionType.TASK_CREATE,
                target_ref=SymbolicTargetRef.TASK_LIST,
                parameters={"title": "Pack bags"},
            ),
        ],
    )
    return compile_candidate_plan(p, resolver)


class TestActionSchedulerBasicOrdering:
    """Basic deterministic topological ordering."""

    def test_simple_sequential_two_step_plan(
        self, sequential_two_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(sequential_two_step_contract)

        assert isinstance(schedule, ExecutionSchedule)
        assert schedule.mission_id == sequential_two_step_contract.mission_id
        assert len(schedule) == 2

        # Step 0 must precede Step 1
        expected_first = sequential_two_step_contract.actions[0].action_id
        expected_second = sequential_two_step_contract.actions[1].action_id
        assert schedule.ordered_action_ids == (expected_first, expected_second)

    def test_stable_ordering_across_repeated_scheduling(
        self, sequential_two_step_contract: MissionExecutionContract
    ) -> None:
        first_run = schedule_execution(sequential_two_step_contract)

        for _ in range(50):
            repeated_run = schedule_execution(sequential_two_step_contract)
            assert repeated_run.ordered_action_ids == first_run.ordered_action_ids

    def test_type_validation_fails_closed(self) -> None:
        with pytest.raises(ExecutionContractTypeError, match="MissionExecutionContract"):
            schedule_execution(None)  # type: ignore[arg-type]

        with pytest.raises(ExecutionContractTypeError, match="MissionExecutionContract"):
            schedule_execution("invalid")  # type: ignore[arg-type]


class TestActionSchedulerFailClosed:
    """Cycle detection and missing dependency handling."""

    def test_missing_dependency_fails_closed(
        self, sequential_two_step_contract: MissionExecutionContract
    ) -> None:
        # Construct contract with unknown dependency
        a0 = sequential_two_step_contract.actions[0].action_id
        a1 = sequential_two_step_contract.actions[1].action_id
        unknown = ActionId.generate()

        with pytest.raises(MissingDependencyError, match="unknown ActionId"):
            MissionExecutionContract(
                mission_id=sequential_two_step_contract.mission_id,
                actions=sequential_two_step_contract.actions,
                dependencies={a0: frozenset(), a1: frozenset({unknown})},
            )

    def test_self_dependency_fails_closed(
        self, sequential_two_step_contract: MissionExecutionContract
    ) -> None:
        a0 = sequential_two_step_contract.actions[0].action_id
        a1 = sequential_two_step_contract.actions[1].action_id

        with pytest.raises(DependencyCycleError, match="cannot depend on itself"):
            MissionExecutionContract(
                mission_id=sequential_two_step_contract.mission_id,
                actions=sequential_two_step_contract.actions,
                dependencies={a0: frozenset({a0}), a1: frozenset()},
            )

    def test_mutual_dependency_cycle_fails_closed(
        self, sequential_two_step_contract: MissionExecutionContract
    ) -> None:
        a0 = sequential_two_step_contract.actions[0].action_id
        a1 = sequential_two_step_contract.actions[1].action_id

        with pytest.raises(DependencyCycleError, match="cycle detected"):
            MissionExecutionContract(
                mission_id=sequential_two_step_contract.mission_id,
                actions=sequential_two_step_contract.actions,
                dependencies={a0: frozenset({a1}), a1: frozenset({a0})},
            )

    def test_three_node_cycle_fails_closed(self, resolver: SymbolicTargetResolver) -> None:
        mid = MissionId.generate()
        p = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.WEATHER_READ,
                    target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.TASK_CREATE,
                    target_ref=SymbolicTargetRef.TASK_LIST,
                    parameters={"title": "Check weather and calendar"},
                ),
            ],
        )
        compiled = compile_candidate_plan(p, resolver)
        a0, a1, a2 = [a.action_id for a in compiled.actions]

        # Cycle: a0 -> a1 -> a2 -> a0
        cycle_deps = {
            a0: frozenset({a2}),
            a1: frozenset({a0}),
            a2: frozenset({a1}),
        }

        with pytest.raises(DependencyCycleError, match="cycle detected"):
            MissionExecutionContract(
                mission_id=mid,
                actions=compiled.actions,
                dependencies=cycle_deps,
            )


class TestActionSchedulerDeterministicTieBreaking:
    """Independent actions use original compilation index for tie-breaking."""

    def test_independent_actions_preserve_compilation_order(
        self, resolver: SymbolicTargetResolver
    ) -> None:
        mid = MissionId.generate()
        p = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.WEATHER_READ,
                    target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.TASK_CREATE,
                    target_ref=SymbolicTargetRef.TASK_LIST,
                    parameters={"title": "Pack lunch"},
                ),
            ],
        )
        compiled = compile_candidate_plan(p, resolver)
        a0, a1, a2 = [a.action_id for a in compiled.actions]

        # Make all 3 actions independent (0 dependencies each)
        independent_contract = MissionExecutionContract(
            mission_id=mid,
            actions=compiled.actions,
            dependencies={a0: frozenset(), a1: frozenset(), a2: frozenset()},
        )

        schedule = schedule_execution(independent_contract)
        # Must tie-break exactly to original compilation index: a0, a1, a2
        assert schedule.ordered_action_ids == (a0, a1, a2)

    def test_diamond_dependency_graph_ordered_correctly(
        self, resolver: SymbolicTargetResolver
    ) -> None:
        """Diamond: A -> B, A -> C; D -> B and C."""
        mid = MissionId.generate()
        p = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.WEATHER_READ,
                    target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.CALENDAR_EVENT,
                ),
                CandidateActionProposal.create(
                    action_type=ActionType.TASK_CREATE,
                    target_ref=SymbolicTargetRef.TASK_LIST,
                    parameters={"title": "Final task"},
                ),
            ],
        )
        compiled = compile_candidate_plan(p, resolver)
        a, b, c, d = [act.action_id for act in compiled.actions]

        diamond_deps = {
            a: frozenset(),
            b: frozenset({a}),
            c: frozenset({a}),
            d: frozenset({b, c}),
        }

        contract = MissionExecutionContract(
            mission_id=mid,
            actions=compiled.actions,
            dependencies=diamond_deps,
        )

        schedule = schedule_execution(contract)
        # a must be first; b and c follow (b before c by original index); d is last
        assert schedule.ordered_action_ids == (a, b, c, d)


class TestActionSchedulerPurity:
    """Scheduler creates zero provider/evidence/state artifacts."""

    def test_scheduler_purity_invariants(
        self, sequential_two_step_contract: MissionExecutionContract
    ) -> None:
        schedule = schedule_execution(sequential_two_step_contract)

        # Output is strictly an ExecutionSchedule
        assert isinstance(schedule, ExecutionSchedule)
        assert hasattr(schedule, "ordered_action_ids")
        assert hasattr(schedule, "mission_id")

        # Zero evidence / provider / state attributes
        assert not hasattr(schedule, "evidence_id")
        assert not hasattr(schedule, "evidence_records")
        assert not hasattr(schedule, "provider_results")
        assert not hasattr(schedule, "status")
        assert not hasattr(schedule, "is_verified")
        assert not hasattr(schedule, "is_ready")
