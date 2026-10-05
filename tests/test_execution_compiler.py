"""Tests for Phase P-08.01: Mission Compiler.

Validates that:
- Input boundary accepts validated CandidatePlanProposal ONLY (rejects raw dict, str, JSON).
- Runtime owns ActionId generation (model cannot supply ActionId, AttemptId, IdempotencyKey).
- Target resolution translates SymbolicTargetRef to canonical TargetIdentity and fails closed.
- Mission ID remains strictly bound.
- Ordered runtime-owned ActionContracts are created with NormalizedParameters.
- Sequential dependencies are deterministically bound.
- Zero provider calls, zero EvidenceIds, zero ApprovalGrants, zero VERIFIED/READY truth.
"""

from __future__ import annotations

import pytest

from stilldone.action_policy import ValidatedActionContract
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import ActionId, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.execution import ResourceBinding
from stilldone.domain.mission import MissionId
from stilldone.execution.compiler import compile_candidate_plan
from stilldone.execution.contracts import (
    DependencyCycleError,
    ExecutionContractTypeError,
    ExecutionContractValueError,
    MissingDependencyError,
    MissionExecutionContract,
    SymbolicTargetResolver,
    TargetResolutionError,
)
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
    return SymbolicTargetResolver(
        scope=demo_scope,
        weather_location_id="demo-weather-loc",
    )


@pytest.fixture
def canonical_two_step_plan() -> CandidatePlanProposal:
    """Canonical two-step plan: calendar.read -> task.create."""
    mid = MissionId.generate()
    step1 = CandidateActionProposal.create(
        action_type=ActionType.CALENDAR_READ,
        target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
    )
    step2 = CandidateActionProposal.create(
        action_type=ActionType.TASK_CREATE,
        target_ref=SymbolicTargetRef.TASK_LIST,
        parameters={"title": "Pack backpacks for tomorrow"},
    )
    return CandidatePlanProposal.create(
        mission_id=mid,
        steps=[step1, step2],
    )


class TestMissionCompilerInputBoundary:
    """Input boundary strictly requires validated CandidatePlanProposal."""

    def test_raw_dict_rejected(self, resolver: SymbolicTargetResolver) -> None:
        with pytest.raises(ExecutionContractTypeError, match="CandidatePlanProposal"):
            compile_candidate_plan({"mission_id": "test", "steps": []}, resolver)  # type: ignore[arg-type]

    def test_raw_json_string_rejected(self, resolver: SymbolicTargetResolver) -> None:
        with pytest.raises(ExecutionContractTypeError, match="CandidatePlanProposal"):
            compile_candidate_plan('{"mission_id": "test"}', resolver)  # type: ignore[arg-type]

    def test_raw_text_rejected(self, resolver: SymbolicTargetResolver) -> None:
        with pytest.raises(ExecutionContractTypeError, match="CandidatePlanProposal"):
            compile_candidate_plan("Get my family ready", resolver)  # type: ignore[arg-type]

    def test_none_rejected(self, resolver: SymbolicTargetResolver) -> None:
        with pytest.raises(ExecutionContractTypeError, match="CandidatePlanProposal"):
            compile_candidate_plan(None, resolver)  # type: ignore[arg-type]

    def test_resolver_type_enforced(self, canonical_two_step_plan: CandidatePlanProposal) -> None:
        with pytest.raises(ExecutionContractTypeError, match="SymbolicTargetResolver"):
            compile_candidate_plan(canonical_two_step_plan, None)  # type: ignore[arg-type]


class TestMissionCompilerRuntimeOwnership:
    """Runtime owns ActionIds, parameters, and contracts."""

    def test_compilation_creates_runtime_action_ids(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)

        assert isinstance(contract, MissionExecutionContract)
        assert contract.mission_id == canonical_two_step_plan.mission_id
        assert len(contract.actions) == 2

        # Each action has a valid runtime ActionId
        aid1 = contract.actions[0].action_id
        aid2 = contract.actions[1].action_id
        assert isinstance(aid1, ActionId)
        assert isinstance(aid2, ActionId)
        assert aid1 != aid2

        # Actions are validated ActionContracts
        for action in contract.actions:
            assert action.mission_id == canonical_two_step_plan.mission_id
            assert isinstance(action.target, TargetIdentity)
            validated = ValidatedActionContract(action)
            assert validated.action_id == action.action_id

    def test_model_cannot_inject_action_ids(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        # CandidateActionProposal has no action_id attribute
        step = canonical_two_step_plan.steps[0]
        assert not hasattr(step, "action_id")

        # Compiler generates fresh ActionIds independently
        c1 = compile_candidate_plan(canonical_two_step_plan, resolver)
        c2 = compile_candidate_plan(canonical_two_step_plan, resolver)
        assert c1.actions[0].action_id != c2.actions[0].action_id

    def test_deterministic_action_id_generator_supported(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        fixed_ids = [
            ActionId("00000000-0000-0000-0000-000000000001"),
            ActionId("00000000-0000-0000-0000-000000000002"),
        ]
        iter_ids = iter(fixed_ids)
        contract = compile_candidate_plan(
            canonical_two_step_plan,
            resolver,
            action_id_generator=lambda: next(iter_ids),
        )
        assert contract.actions[0].action_id == fixed_ids[0]
        assert contract.actions[1].action_id == fixed_ids[1]


class TestMissionCompilerTargetResolution:
    """Symbolic target resolution maps to canonical TargetIdentity and fails closed."""

    def test_google_calendar_resolution(
        self, resolver: SymbolicTargetResolver, demo_scope: DemoResourceScope
    ) -> None:
        mid = MissionId.generate()
        plan = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                )
            ],
        )
        contract = compile_candidate_plan(plan, resolver)
        target = contract.actions[0].target
        assert target.system == "google_calendar"
        assert target.resource_kind == ResourceKind.CALENDAR_EVENT
        assert target.parent_id == demo_scope.calendar_id
        assert target.resource_id == SymbolicTargetRef.LEAVE_FOR_SCHOOL.value

    def test_google_tasks_create_resolution(
        self, resolver: SymbolicTargetResolver, demo_scope: DemoResourceScope
    ) -> None:
        mid = MissionId.generate()
        plan = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.TASK_CREATE,
                    target_ref=SymbolicTargetRef.TASK_LIST,
                    parameters={"title": "Buy groceries"},
                )
            ],
        )
        contract = compile_candidate_plan(plan, resolver)
        target = contract.actions[0].target
        assert target.system == "google_tasks"
        assert target.resource_kind == ResourceKind.TASK_LIST
        assert target.parent_id is None
        assert target.resource_id == demo_scope.task_list_id

        # ResourceBinding for task.create has unresolved child task
        binding = contract.resource_bindings[contract.actions[0].action_id]
        assert isinstance(binding, ResourceBinding)
        assert not binding.is_resolved

    def test_weather_read_resolution(self, resolver: SymbolicTargetResolver) -> None:
        mid = MissionId.generate()
        plan = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.WEATHER_READ,
                    target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                )
            ],
        )
        contract = compile_candidate_plan(plan, resolver)
        target = contract.actions[0].target
        assert target.system == "open_meteo"
        assert target.resource_kind == ResourceKind.WEATHER_LOCATION
        assert target.resource_id == "demo-weather-loc"
        assert target.parent_id is None

    def test_missing_scope_for_calendar_fails_closed(self) -> None:
        unscoped_resolver = SymbolicTargetResolver(scope=None)
        mid = MissionId.generate()
        plan = CandidatePlanProposal.create(
            mission_id=mid,
            steps=[
                CandidateActionProposal.create(
                    action_type=ActionType.CALENDAR_READ,
                    target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                )
            ],
        )
        with pytest.raises(TargetResolutionError, match="DemoResourceScope is required"):
            compile_candidate_plan(plan, unscoped_resolver)

    def test_incompatible_symbolic_target_fails_closed(self, demo_scope: DemoResourceScope) -> None:
        resolver = SymbolicTargetResolver(scope=demo_scope)
        # Directly invoke resolver with incompatible pair
        with pytest.raises(TargetResolutionError, match="incompatible"):
            resolver.resolve(
                ActionType.CALENDAR_READ,
                SymbolicTargetRef.TASK_LIST,  # incompatible with calendar
            )


class TestMissionCompilerDependencies:
    """Sequential dependency ordering and contract integrity."""

    def test_sequential_dependencies_bound(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)
        a0 = contract.actions[0].action_id
        a1 = contract.actions[1].action_id

        # Step 0 has no dependencies
        assert contract.dependencies[a0] == frozenset()
        # Step 1 depends on Step 0
        assert contract.dependencies[a1] == frozenset({a0})

    def test_contract_rejects_empty_actions(self) -> None:
        with pytest.raises(ExecutionContractValueError, match="actions tuple cannot be empty"):
            MissionExecutionContract(
                mission_id=MissionId.generate(),
                actions=(),
                dependencies={},
            )

    def test_contract_rejects_mismatched_mission_id(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)
        different_mission_id = MissionId.generate()
        with pytest.raises(ExecutionContractValueError, match="does not match contract mission_id"):
            MissionExecutionContract(
                mission_id=different_mission_id,
                actions=contract.actions,
                dependencies=contract.dependencies,
            )

    def test_contract_rejects_duplicate_action_ids(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)
        dup_action = contract.actions[0]
        with pytest.raises(ExecutionContractValueError, match="Duplicate action_id"):
            MissionExecutionContract(
                mission_id=contract.mission_id,
                actions=(dup_action, dup_action),
                dependencies={dup_action.action_id: frozenset()},
            )

    def test_contract_rejects_missing_dependency(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)
        a0 = contract.actions[0].action_id
        a1 = contract.actions[1].action_id
        unknown_aid = ActionId.generate()
        with pytest.raises(MissingDependencyError, match="unknown ActionId"):
            MissionExecutionContract(
                mission_id=contract.mission_id,
                actions=contract.actions,
                dependencies={a0: frozenset(), a1: frozenset({unknown_aid})},
            )

    def test_contract_rejects_self_dependency(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)
        a0 = contract.actions[0].action_id
        a1 = contract.actions[1].action_id
        with pytest.raises(DependencyCycleError, match="cannot depend on itself"):
            MissionExecutionContract(
                mission_id=contract.mission_id,
                actions=contract.actions,
                dependencies={a0: frozenset({a0}), a1: frozenset()},
            )

    def test_contract_rejects_dependency_cycle(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)
        a0 = contract.actions[0].action_id
        a1 = contract.actions[1].action_id
        with pytest.raises(DependencyCycleError, match="cycle detected"):
            MissionExecutionContract(
                mission_id=contract.mission_id,
                actions=contract.actions,
                dependencies={a0: frozenset({a1}), a1: frozenset({a0})},
            )


class TestMissionCompilerNoTruthFabrication:
    """Compiler produces zero provider results, zero EvidenceIds, zero VERIFIED/READY truth."""

    def test_compiler_has_zero_side_effects(
        self,
        canonical_two_step_plan: CandidatePlanProposal,
        resolver: SymbolicTargetResolver,
    ) -> None:
        contract = compile_candidate_plan(canonical_two_step_plan, resolver)

        # No EvidenceId attributes
        assert not hasattr(contract, "evidence_id")
        assert not hasattr(contract, "evidence_records")

        # No ApprovalGrant attributes
        assert not hasattr(contract, "approval_grant")
        assert not hasattr(contract, "is_approved")

        # No state promotion to VERIFIED or READY
        assert not hasattr(contract, "status")
        assert not hasattr(contract, "is_verified")
        assert not hasattr(contract, "is_ready")
