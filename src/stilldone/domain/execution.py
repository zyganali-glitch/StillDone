"""Provider-neutral execution recovery, idempotency, retry, resource, and reconciliation contracts.

Defines runtime-owned IdempotencyKey, bounded RetryPolicy, 1-based ExecutionAttempt,
ResourceBinding distinguishing requested from resolved concrete targets, and
immutable ReconciliationRequest contracts.
Does not execute actions, run retry loops, call providers, or evaluate predicates.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from stilldone.domain.action import ActionId, ResourceKind, TargetIdentity
from stilldone.domain.desired_state import PredicateId
from stilldone.domain.mission import MissionId

MAX_RETRY_ATTEMPTS_CEILING: int = 5


@dataclass(frozen=True)
class IdempotencyKey:
    """Opaque UUID-backed idempotency key owned by deterministic runtime code."""

    value: str

    def __post_init__(self) -> None:
        if isinstance(self.value, uuid.UUID):
            object.__setattr__(self, "value", str(self.value))
        elif isinstance(self.value, str):
            try:
                parsed = uuid.UUID(self.value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid IdempotencyKey format: {self.value!r}") from exc
            object.__setattr__(self, "value", str(parsed))
        else:
            raise TypeError("IdempotencyKey value must be a string or UUID instance")

    @classmethod
    def generate(cls) -> IdempotencyKey:
        """Generate a new idempotency key for a logical mutation lineage."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


class RetryStrategy(StrEnum):
    """Bounded vocabulary of retry strategies.

    A lost or unknown provider response MUST NOT justify blind duplicate mutation.
    """

    NO_RETRY = "NO_RETRY"
    IDEMPOTENT_RETRY = "IDEMPOTENT_RETRY"
    READ_BEFORE_RETRY = "READ_BEFORE_RETRY"


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable bounded retry policy.

    Enforces finite max_attempts bounded by MAX_RETRY_ATTEMPTS_CEILING.
    NO_RETRY strictly requires max_attempts == 1.
    """

    strategy: RetryStrategy
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.strategy, str) and not isinstance(self.strategy, RetryStrategy):
            try:
                strat = RetryStrategy(self.strategy)
                object.__setattr__(self, "strategy", strat)
            except ValueError as exc:
                raise ValueError(f"Unsupported retry strategy: {self.strategy!r}") from exc
        elif not isinstance(self.strategy, RetryStrategy):
            raise TypeError(f"strategy must be a RetryStrategy, got {type(self.strategy).__name__}")

        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            raise TypeError("max_attempts must be an integer")

        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")

        if self.max_attempts > MAX_RETRY_ATTEMPTS_CEILING:
            raise ValueError(
                f"max_attempts ({self.max_attempts}) exceeds maximum ceiling "
                f"of {MAX_RETRY_ATTEMPTS_CEILING}"
            )

        if self.strategy == RetryStrategy.NO_RETRY and self.max_attempts != 1:
            raise ValueError("NO_RETRY strategy requires max_attempts == 1")

    @classmethod
    def no_retry(cls) -> RetryPolicy:
        """Construct a NO_RETRY policy with max_attempts=1."""
        return cls(strategy=RetryStrategy.NO_RETRY, max_attempts=1)

    @classmethod
    def idempotent(cls, max_attempts: int = 3) -> RetryPolicy:
        """Construct an IDEMPOTENT_RETRY policy with bounded attempts."""
        return cls(strategy=RetryStrategy.IDEMPOTENT_RETRY, max_attempts=max_attempts)

    @classmethod
    def read_before_retry(cls, max_attempts: int = 3) -> RetryPolicy:
        """Construct a READ_BEFORE_RETRY policy requiring read-back before re-attempt."""
        return cls(strategy=RetryStrategy.READ_BEFORE_RETRY, max_attempts=max_attempts)


@dataclass(frozen=True)
class AttemptId:
    """Opaque UUID-backed attempt identifier created by deterministic runtime code."""

    value: str

    def __post_init__(self) -> None:
        if isinstance(self.value, uuid.UUID):
            object.__setattr__(self, "value", str(self.value))
        elif isinstance(self.value, str):
            try:
                parsed = uuid.UUID(self.value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid AttemptId format: {self.value!r}") from exc
            object.__setattr__(self, "value", str(parsed))
        else:
            raise TypeError("AttemptId value must be a string or UUID instance")

    @classmethod
    def generate(cls) -> AttemptId:
        """Create a new random attempt identifier via deterministic runtime code."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ExecutionAttempt:
    """Immutable attempt record binding action, idempotency key, attempt number, and timestamp.

    Attempt number is 1-based (zero and negative rejected).
    Execution result and evidence remain separate.
    """

    action_id: ActionId
    idempotency_key: IdempotencyKey
    attempt_number: int
    started_at: datetime
    attempt_id: AttemptId = field(default_factory=AttemptId.generate)

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, ActionId):
            raise TypeError(f"action_id must be an ActionId, got {type(self.action_id).__name__}")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise TypeError(
                "idempotency_key must be an IdempotencyKey, "
                f"got {type(self.idempotency_key).__name__}"
            )
        if not isinstance(self.attempt_id, AttemptId):
            raise TypeError(
                f"attempt_id must be an AttemptId, got {type(self.attempt_id).__name__}"
            )

        if not isinstance(self.attempt_number, int) or isinstance(self.attempt_number, bool):
            raise TypeError("attempt_number must be an integer")
        if self.attempt_number < 1:
            raise ValueError(f"attempt_number must be >= 1, got {self.attempt_number}")

        if not isinstance(self.started_at, datetime):
            raise TypeError("started_at must be a datetime instance")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware (UTC required)")
        if self.started_at.tzinfo != UTC:
            object.__setattr__(self, "started_at", self.started_at.astimezone(UTC))

    @classmethod
    def create(
        cls,
        *,
        action_id: ActionId,
        idempotency_key: IdempotencyKey,
        attempt_number: int = 1,
        started_at: datetime | None = None,
        attempt_id: AttemptId | None = None,
    ) -> ExecutionAttempt:
        """Helper to construct an immutable ExecutionAttempt."""
        now = started_at if started_at is not None else datetime.now(UTC)
        aid = attempt_id if attempt_id is not None else AttemptId.generate()
        return cls(
            action_id=action_id,
            idempotency_key=idempotency_key,
            attempt_number=attempt_number,
            started_at=now,
            attempt_id=aid,
        )


@dataclass(frozen=True)
class ResourceBinding:
    """Immutable resource binding contract distinguishing requested/parent target

    from an externally resolved concrete resource identity.
    Preserves TargetIdentity as canonical vocabulary.
    """

    requested_target: TargetIdentity
    resolved_target: TargetIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.requested_target, TargetIdentity):
            raise TypeError(
                "requested_target must be a TargetIdentity instance, "
                f"got {type(self.requested_target).__name__}"
            )
        if self.resolved_target is not None:
            if not isinstance(self.resolved_target, TargetIdentity):
                raise TypeError(
                    "resolved_target must be None or a TargetIdentity instance, "
                    f"got {type(self.resolved_target).__name__}"
                )
            # Parent container cannot masquerade as the resolved child resource
            if (
                self.requested_target.resource_kind == ResourceKind.TASK_LIST
                and self.resolved_target.resource_kind == ResourceKind.TASK_LIST
            ):
                raise ValueError(
                    "Parent task list cannot be treated as the resolved child task resource"
                )
            # Resolved target system must match requested system
            if self.resolved_target.system != self.requested_target.system:
                raise ValueError(
                    f"Resolved target system {self.resolved_target.system!r} does not "
                    f"match requested target system {self.requested_target.system!r}"
                )

    @property
    def is_resolved(self) -> bool:
        """Return True if concrete resource identity has been resolved."""
        return self.resolved_target is not None

    def with_resolved(self, concrete_target: TargetIdentity) -> ResourceBinding:
        """Return a new ResourceBinding with the concrete resolved target identity."""
        if not isinstance(concrete_target, TargetIdentity):
            raise TypeError(
                "concrete_target must be a TargetIdentity instance, "
                f"got {type(concrete_target).__name__}"
            )
        return ResourceBinding(
            requested_target=self.requested_target, resolved_target=concrete_target
        )

    @classmethod
    def unresolved(cls, target: TargetIdentity) -> ResourceBinding:
        """Construct an unresolved resource binding for a target or parent container."""
        return cls(requested_target=target, resolved_target=None)

    @classmethod
    def resolved(cls, target: TargetIdentity, resolved_target: TargetIdentity) -> ResourceBinding:
        """Construct an immediately resolved resource binding."""
        return cls(requested_target=target, resolved_target=resolved_target)


class ReconciliationReason(StrEnum):
    """Bounded reasons for initiating a reconciliation request."""

    POST_EXECUTION_VERIFY = "POST_EXECUTION_VERIFY"
    EXPLICIT_USER_CHECK = "EXPLICIT_USER_CHECK"
    FRESHNESS_REFRESH = "FRESHNESS_REFRESH"


@dataclass(frozen=True)
class PredicateScope:
    """Immutable predicate scope for reconciliation.

    Specifies either all required predicates (all_required=True, selected_predicates=())
    or an explicit unique non-empty tuple of PredicateId values (all_required=False).
    """

    all_required: bool = True
    selected_predicates: tuple[PredicateId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.all_required, bool):
            raise TypeError(f"all_required must be a bool, got {type(self.all_required).__name__}")
        if not isinstance(self.selected_predicates, tuple):
            raise TypeError(
                "selected_predicates must be a tuple, "
                f"got {type(self.selected_predicates).__name__}"
            )

        if self.all_required:
            if len(self.selected_predicates) > 0:
                raise ValueError("selected_predicates must be empty when all_required is True")
        else:
            if len(self.selected_predicates) == 0:
                raise ValueError("selected_predicates must be non-empty when all_required is False")
            seen: set[str] = set()
            for pid in self.selected_predicates:
                if not isinstance(pid, PredicateId):
                    raise TypeError(
                        "selected_predicates must contain PredicateId instances, "
                        f"got {type(pid).__name__}"
                    )
                if pid.value in seen:
                    raise ValueError(f"Duplicate PredicateId in selected_predicates: {pid.value!r}")
                seen.add(pid.value)

    @classmethod
    def all(cls) -> PredicateScope:
        """Scope covering all required predicates of the mission."""
        return cls(all_required=True, selected_predicates=())

    @classmethod
    def selective(cls, predicates: Iterable[PredicateId]) -> PredicateScope:
        """Scope covering an explicit non-empty set/sequence of PredicateIds."""
        if isinstance(predicates, (str, bytes)):
            raise TypeError("predicates must be an iterable of PredicateId instances")
        items = tuple(predicates)
        return cls(all_required=False, selected_predicates=items)


@dataclass(frozen=True)
class ReconciliationRequest:
    """Pure immutable reconciliation request contract.

    Binds mission identity, request timestamp, reason, and predicate scope.
    Does not evaluate predicates or invoke external providers.
    """

    mission_id: MissionId
    reason: ReconciliationReason
    requested_at: datetime
    scope: PredicateScope = field(default_factory=PredicateScope.all)

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be a MissionId, got {type(self.mission_id).__name__}")

        if isinstance(self.reason, str) and not isinstance(self.reason, ReconciliationReason):
            try:
                r = ReconciliationReason(self.reason)
                object.__setattr__(self, "reason", r)
            except ValueError as exc:
                raise ValueError(f"Unsupported reconciliation reason: {self.reason!r}") from exc
        elif not isinstance(self.reason, ReconciliationReason):
            raise TypeError(
                f"reason must be a ReconciliationReason, got {type(self.reason).__name__}"
            )

        if not isinstance(self.requested_at, datetime):
            raise TypeError(
                f"requested_at must be a datetime instance, got {type(self.requested_at).__name__}"
            )
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware (UTC required)")
        if self.requested_at.tzinfo != UTC:
            object.__setattr__(self, "requested_at", self.requested_at.astimezone(UTC))

        if not isinstance(self.scope, PredicateScope):
            raise TypeError(f"scope must be a PredicateScope, got {type(self.scope).__name__}")

    @classmethod
    def create(
        cls,
        *,
        mission_id: MissionId,
        reason: ReconciliationReason | str,
        requested_at: datetime | None = None,
        scope: PredicateScope | None = None,
    ) -> ReconciliationRequest:
        """Helper to construct an immutable ReconciliationRequest."""
        now = requested_at if requested_at is not None else datetime.now(UTC)
        s = scope if scope is not None else PredicateScope.all()
        try:
            r = reason if isinstance(reason, ReconciliationReason) else ReconciliationReason(reason)
        except ValueError as exc:
            raise ValueError(f"Unsupported reconciliation reason: {reason!r}") from exc
        return cls(mission_id=mission_id, reason=r, requested_at=now, scope=s)
