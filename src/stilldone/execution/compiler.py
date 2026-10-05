"""Deterministic mission compiler from validated candidate plan to execution contract.

Phase P-08.01:
Compiles a validated CandidatePlanProposal into an immutable MissionExecutionContract.

Laws:
- Input boundary: validated CandidatePlanProposal ONLY.
- Model cannot supply or inject ActionId, AttemptId, or IdempotencyKey.
- Runtime generates all ActionIds via deterministic code.
- Target resolution fails closed on unsupported or incompatible targets.
- Preserves exact plan step sequence and binds sequential dependencies.
- Confers zero authority, creates zero approvals, zero EvidenceIds, zero VERIFIED/READY truth.
- Zero shell/filesystem/network execution.
"""

from __future__ import annotations

from collections.abc import Callable

from stilldone.action_policy import validate_action_contract
from stilldone.domain.action import ActionContract, ActionId
from stilldone.domain.execution import ResourceBinding
from stilldone.execution.contracts import (
    ExecutionContractTypeError,
    MissionExecutionContract,
    SymbolicTargetResolver,
)
from stilldone.planning.contracts import CandidatePlanProposal


def compile_candidate_plan(
    plan: CandidatePlanProposal,
    target_resolver: SymbolicTargetResolver,
    *,
    action_id_generator: Callable[[], ActionId] | None = None,
) -> MissionExecutionContract:
    """Compile a validated CandidatePlanProposal into an immutable execution contract.

    Args:
        plan: A validated CandidatePlanProposal from Phase P-07. Raw JSON/dicts fail closed.
        target_resolver: Deterministic SymbolicTargetResolver to map symbolic targets
            to TargetIdentities.
        action_id_generator: Optional runtime generator for ActionId
            (defaults to ActionId.generate).

    Returns:
        Immutable MissionExecutionContract aggregate ready for scheduling and execution.

    Raises:
        ExecutionContractTypeError: If plan or target_resolver has invalid type.
        TargetResolutionError: If any symbolic target cannot be resolved or is incompatible.
        ExecutionContractValueError: If the plan or any compiled contract violates invariants.
    """
    if not isinstance(plan, CandidatePlanProposal):
        raise ExecutionContractTypeError(
            f"plan must be a CandidatePlanProposal instance, got {type(plan).__name__}"
        )
    if not isinstance(target_resolver, SymbolicTargetResolver):
        msg = (
            f"target_resolver must be a SymbolicTargetResolver instance, "
            f"got {type(target_resolver).__name__}"
        )
        raise ExecutionContractTypeError(msg)

    gen = action_id_generator or ActionId.generate

    actions: list[ActionContract] = []
    bindings: dict[ActionId, ResourceBinding] = {}
    dependencies: dict[ActionId, frozenset[ActionId]] = {}

    for i, step in enumerate(plan.steps):
        # Runtime-owned ActionId (model CANNOT supply ActionId)
        action_id = gen()

        # Deterministic symbolic target resolution
        concrete_target, resource_binding = target_resolver.resolve(
            step.action_type,
            step.target_ref,
        )

        # Build canonical ActionContract
        contract = ActionContract.create(
            mission_id=plan.mission_id,
            action_type=step.action_type,
            target=concrete_target,
            parameters=step.parameters,
            action_id=action_id,
        )

        # Self-validate against closed-world action policy
        validate_action_contract(contract)

        actions.append(contract)
        bindings[action_id] = resource_binding

        # Deterministic sequential dependency interpretation:
        # Step i depends on Step i-1 (step 0 has empty dependencies)
        if i == 0:
            dependencies[action_id] = frozenset()
        else:
            dependencies[action_id] = frozenset({actions[i - 1].action_id})

    return MissionExecutionContract(
        mission_id=plan.mission_id,
        actions=tuple(actions),
        dependencies=dependencies,
        resource_bindings=bindings,
    )
