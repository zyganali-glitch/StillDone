"""Domain contracts for machine-checkable desired-state predicates and freshness.

Defines typed immutable desired-state predicates, bounded operator vocabulary,
and deterministic freshness contracts without evaluation or provider logic.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import StrEnum

from stilldone.domain.mission import MissionId


@dataclass(frozen=True)
class PredicateId:
    """Opaque UUID-backed predicate identifier created by deterministic runtime code."""

    value: str

    def __post_init__(self) -> None:
        if isinstance(self.value, uuid.UUID):
            object.__setattr__(self, "value", str(self.value))
        elif isinstance(self.value, str):
            try:
                parsed = uuid.UUID(self.value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid PredicateId format: {self.value!r}") from exc
            object.__setattr__(self, "value", str(parsed))
        else:
            raise TypeError("PredicateId value must be a string or UUID instance")

    @classmethod
    def generate(cls) -> PredicateId:
        """Create a new random predicate identifier via deterministic runtime code."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


class PredicateOperator(StrEnum):
    """Bounded vocabulary of deterministic comparison operators.

    Arbitrary expressions, model-generated code, and eval() are strictly forbidden.
    """

    EQUALS = "=="
    NOT_EQUALS = "!="
    EXISTS = "exists"
    DOES_NOT_EXIST = "does_not_exist"
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="


class FreshnessMode(StrEnum):
    """Freshness requirement modes for desired-state evaluation."""

    CURRENT = "CURRENT"
    MAX_AGE = "MAX_AGE"


@dataclass(frozen=True)
class FreshnessContract:
    """Deterministic contract defining how fresh an observation must be.

    Rejects contradictory, negative, or zero duration configurations.
    """

    mode: FreshnessMode
    max_age_seconds: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, FreshnessMode):
            raise TypeError("mode must be a FreshnessMode instance")

        if self.mode == FreshnessMode.CURRENT:
            if self.max_age_seconds is not None:
                raise ValueError("FreshnessMode.CURRENT does not allow max_age_seconds")
        elif self.mode == FreshnessMode.MAX_AGE:
            if self.max_age_seconds is None:
                raise ValueError("FreshnessMode.MAX_AGE requires max_age_seconds")
            if not isinstance(self.max_age_seconds, int) or isinstance(self.max_age_seconds, bool):
                raise TypeError("max_age_seconds must be an integer")
            if self.max_age_seconds <= 0:
                raise ValueError(
                    f"max_age_seconds must be strictly positive, got {self.max_age_seconds}"
                )

    @classmethod
    def current(cls) -> FreshnessContract:
        """Require fresh observation during predicate evaluation."""
        return cls(mode=FreshnessMode.CURRENT)

    @classmethod
    def max_age(cls, seconds: int) -> FreshnessContract:
        """Require observation age to be within bounded positive seconds."""
        return cls(mode=FreshnessMode.MAX_AGE, max_age_seconds=seconds)


ExpectedValueType = str | int | float | bool | None


@dataclass(frozen=True)
class DesiredStatePredicate:
    """Immutable contract defining a single machine-checkable fact.

    Enforces explicit required vs optional semantics and bounded freshness.
    Does not evaluate predicates or invoke external providers.
    """

    predicate_id: PredicateId
    mission_id: MissionId
    subject: str
    operator: PredicateOperator
    expected_value: ExpectedValueType
    required: bool
    freshness: FreshnessContract

    def __post_init__(self) -> None:
        if not isinstance(self.predicate_id, PredicateId):
            raise TypeError("predicate_id must be a PredicateId instance")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be a MissionId instance")

        if not isinstance(self.subject, str):
            raise TypeError("subject must be a string")
        if not self.subject.strip():
            raise ValueError("subject cannot be blank or whitespace-only")

        if isinstance(self.operator, str) and not isinstance(self.operator, PredicateOperator):
            try:
                op = PredicateOperator(self.operator)
                object.__setattr__(self, "operator", op)
            except ValueError as exc:
                raise ValueError(f"Unsupported predicate operator: {self.operator!r}") from exc
        elif not isinstance(self.operator, PredicateOperator):
            raise TypeError(
                f"operator must be a PredicateOperator instance, got {type(self.operator).__name__}"
            )

        if not isinstance(self.required, bool):
            raise TypeError(f"required must be a bool, got {type(self.required).__name__}")

        if not isinstance(self.freshness, FreshnessContract):
            actual_type = type(self.freshness).__name__
            raise TypeError(f"freshness must be a FreshnessContract instance, got {actual_type}")

        # Validate expected_value is a JSON-like scalar and finite
        if not isinstance(self.expected_value, (str, int, float, bool, type(None))):
            raise TypeError(
                f"expected_value must be a JSON-like scalar (str, int, float, bool, None), "
                f"got {type(self.expected_value).__name__}"
            )
        if isinstance(self.expected_value, float) and (
            math.isnan(self.expected_value) or math.isinf(self.expected_value)
        ):
            raise ValueError("expected_value float must be finite (NaN and Infinity forbidden)")

    @classmethod
    def create(
        cls,
        *,
        mission_id: MissionId,
        subject: str,
        operator: PredicateOperator | str,
        expected_value: ExpectedValueType,
        required: bool = True,
        freshness: FreshnessContract | None = None,
        predicate_id: PredicateId | None = None,
    ) -> DesiredStatePredicate:
        """Helper to construct a validated desired-state predicate."""
        pid = predicate_id if predicate_id is not None else PredicateId.generate()
        fc = freshness if freshness is not None else FreshnessContract.current()
        try:
            op = (
                operator if isinstance(operator, PredicateOperator) else PredicateOperator(operator)
            )
        except ValueError as exc:
            raise ValueError(f"Unsupported predicate operator: {operator!r}") from exc
        return cls(
            predicate_id=pid,
            mission_id=mission_id,
            subject=subject,
            operator=op,
            expected_value=expected_value,
            required=required,
            freshness=fc,
        )
