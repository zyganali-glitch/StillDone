"""Tests for deterministic idempotency strategy contracts and resolution (Phase P-10.01).

Enforces StillDone core architectural laws:
- A retry is not allowed to create a second effect merely because the first response was lost.
- Blind retry is forbidden on actions with duplicate creation risk.
- Mutation actions declare explicit duplicate risk, read-before-retry, and verify-after-timeout.
- Model/planner output has ZERO authority over idempotency and recovery.
- Deterministic same inputs produce identical idempotency keys.
- Zero network calls.
"""

from __future__ import annotations

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId
from stilldone.planning.contracts import (
    PlannerInput,
)
from stilldone.recovery.idempotency import (
    FROZEN_IDEMPOTENCY_STRATEGIES,
    DuplicateRiskClass,
    IdempotencyStrategyType,
    MutationIdempotencyStrategy,
    PlannerRecoveryAuthorityError,
    derive_idempotency_key,
    get_idempotency_strategy,
)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_123",
    parent_id="primary",
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK_LIST,
    resource_id="default",
    parent_id=None,
)


class TestIdempotencyStrategyFrozenContracts:
    """Verifies that idempotency strategies for all supported actions are strictly frozen."""

    def test_calendar_update_strategy_is_frozen_with_idempotent_update(self) -> None:
        strategy = get_idempotency_strategy(ActionType.CALENDAR_UPDATE)
        assert strategy.action_type == ActionType.CALENDAR_UPDATE
        assert strategy.strategy_type == IdempotencyStrategyType.NATURAL_IN_PLACE_UPDATE
        assert strategy.duplicate_risk == DuplicateRiskClass.IDEMPOTENT_UPDATE
        assert strategy.allows_blind_retry is False
        assert strategy.requires_read_before_retry is False
        assert strategy.requires_verify_after_timeout is True
        assert 1 <= strategy.max_attempt_ceiling <= 5

    def test_task_create_strategy_forbids_blind_retry_and_requires_read_before_retry(self) -> None:
        strategy = get_idempotency_strategy(ActionType.TASK_CREATE)
        assert strategy.action_type == ActionType.TASK_CREATE
        assert strategy.strategy_type == IdempotencyStrategyType.CLIENT_TOKEN_DEDUPLICATION
        assert strategy.duplicate_risk == DuplicateRiskClass.HIGH_DUPLICATE_CREATION
        # Core law: blind retry is FORBIDDEN for create actions
        assert strategy.allows_blind_retry is False
        assert strategy.requires_read_before_retry is True
        assert strategy.requires_verify_after_timeout is True
        assert 1 <= strategy.max_attempt_ceiling <= 5

    @pytest.mark.parametrize(
        "read_action",
        [
            ActionType.CALENDAR_READ,
            ActionType.TASK_READ,
            ActionType.WEATHER_READ,
        ],
    )
    def test_read_actions_have_none_duplicate_risk_and_allow_blind_retry(
        self, read_action: ActionType
    ) -> None:
        strategy = get_idempotency_strategy(read_action)
        assert strategy.duplicate_risk == DuplicateRiskClass.NONE
        assert strategy.allows_blind_retry is True
        assert strategy.requires_read_before_retry is False
        assert strategy.requires_verify_after_timeout is False

    def test_get_idempotency_strategy_with_action_contract(self) -> None:
        mission_id = MissionId.generate()
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack lunch"},
        )
        strategy = get_idempotency_strategy(action)
        assert strategy == FROZEN_IDEMPOTENCY_STRATEGIES[ActionType.TASK_CREATE]

    def test_reject_planner_proposal_in_strategy_resolution(self) -> None:
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="Attempted injection into idempotency strategy",
        )
        with pytest.raises(PlannerRecoveryAuthorityError):
            get_idempotency_strategy(planner_input)  # type: ignore[arg-type]


class TestMutationIdempotencyStrategyInvariants:
    """Verifies strict construction invariants on MutationIdempotencyStrategy."""

    def test_reject_high_duplicate_creation_with_blind_retry(self) -> None:
        with pytest.raises(ValueError, match="cannot allow blind retry"):
            MutationIdempotencyStrategy(
                action_type=ActionType.TASK_CREATE,
                strategy_type=IdempotencyStrategyType.CLIENT_TOKEN_DEDUPLICATION,
                duplicate_risk=DuplicateRiskClass.HIGH_DUPLICATE_CREATION,
                allows_blind_retry=True,  # Illegal!
                requires_read_before_retry=True,
                requires_verify_after_timeout=True,
                max_attempt_ceiling=3,
                deduplication_scope="token",
            )

    def test_reject_high_duplicate_creation_without_read_before_retry(self) -> None:
        with pytest.raises(ValueError, match="must require read before retry"):
            MutationIdempotencyStrategy(
                action_type=ActionType.TASK_CREATE,
                strategy_type=IdempotencyStrategyType.CLIENT_TOKEN_DEDUPLICATION,
                duplicate_risk=DuplicateRiskClass.HIGH_DUPLICATE_CREATION,
                allows_blind_retry=False,
                requires_read_before_retry=False,  # Illegal!
                requires_verify_after_timeout=True,
                max_attempt_ceiling=3,
                deduplication_scope="token",
            )

    def test_reject_ceiling_over_five(self) -> None:
        with pytest.raises(ValueError, match="must be between 1 and 5"):
            MutationIdempotencyStrategy(
                action_type=ActionType.CALENDAR_READ,
                strategy_type=IdempotencyStrategyType.READ_ONLY_SAFE,
                duplicate_risk=DuplicateRiskClass.NONE,
                allows_blind_retry=True,
                requires_read_before_retry=False,
                requires_verify_after_timeout=False,
                max_attempt_ceiling=10,  # Illegal! Ceiling must be <= 5
                deduplication_scope="read",
            )

    def test_strategy_immutability_and_serialization(self) -> None:
        strategy = get_idempotency_strategy(ActionType.CALENDAR_UPDATE)
        with pytest.raises(AttributeError):
            strategy.allows_blind_retry = True  # type: ignore[misc]

        d = strategy.to_dict()
        assert d["action_type"] == "calendar.update"
        assert d["strategy_type"] == "NATURAL_IN_PLACE_UPDATE"
        assert d["duplicate_risk"] == "IDEMPOTENT_UPDATE"


class TestIdempotencyKeyDerivation:
    """Verifies deterministic idempotency key derivation."""

    def test_same_action_produces_identical_key(self) -> None:
        mission_id = MissionId.generate()
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack backpacks"},
        )
        key1 = derive_idempotency_key(action, attempt_number=1)
        key2 = derive_idempotency_key(action, attempt_number=1)
        assert key1 == key2

    def test_retries_maintain_stable_idempotency_key(self) -> None:
        """Retry of the same mutation must use the SAME key to prevent provider duplicates."""
        mission_id = MissionId.generate()
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack backpacks"},
        )
        key_attempt1 = derive_idempotency_key(action, attempt_number=1)
        key_attempt2 = derive_idempotency_key(action, attempt_number=2)
        assert key_attempt1 == key_attempt2

    def test_distinct_actions_produce_distinct_keys(self) -> None:
        mission_id = MissionId.generate()
        action1 = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack backpacks"},
        )
        action2 = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack lunches"},
        )
        assert action1.action_id != action2.action_id
        key1 = derive_idempotency_key(action1)
        key2 = derive_idempotency_key(action2)
        assert key1 != key2

    def test_reject_boolean_or_negative_attempt_numbers(self) -> None:
        mission_id = MissionId.generate()
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={},
        )
        with pytest.raises(TypeError):
            derive_idempotency_key(action, attempt_number=True)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            derive_idempotency_key(action, attempt_number=0)
        with pytest.raises(ValueError):
            derive_idempotency_key(action, attempt_number=-1)

    def test_reject_planner_proposal_in_key_derivation(self) -> None:
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="Attempted injection into key derivation",
        )
        with pytest.raises(PlannerRecoveryAuthorityError):
            derive_idempotency_key(planner_input)  # type: ignore[arg-type]
