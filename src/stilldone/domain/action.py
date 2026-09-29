"""Bounded action contracts and deterministic parameter normalization.

Defines the finite provider-neutral action vocabulary for the StillDone killer path,
typed target identities, and immutable parameter normalization.
Does not perform execution, authority classification, or approval binding.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stilldone.domain.mission import MissionId


@dataclass(frozen=True)
class ActionId:
    """Opaque UUID-backed action identifier created by deterministic runtime code."""

    value: str

    def __post_init__(self) -> None:
        if isinstance(self.value, uuid.UUID):
            object.__setattr__(self, "value", str(self.value))
        elif isinstance(self.value, str):
            try:
                parsed = uuid.UUID(self.value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid ActionId format: {self.value!r}") from exc
            object.__setattr__(self, "value", str(parsed))
        else:
            raise TypeError("ActionId value must be a string or UUID instance")

    @classmethod
    def generate(cls) -> ActionId:
        """Create a new random action identifier via deterministic runtime code."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


class ActionType(StrEnum):
    """Finite allowable action vocabulary for the StillDone core path.

    Arbitrary execution, shell, network, filesystem, delete, and model-extended actions
    are strictly prohibited.
    """

    CALENDAR_READ = "calendar.read"
    CALENDAR_UPDATE = "calendar.update"
    TASK_READ = "task.read"
    TASK_CREATE = "task.create"
    WEATHER_READ = "weather.read"


class ResourceKind(StrEnum):
    """Resource kind for target identification."""

    CALENDAR_EVENT = "calendar_event"
    TASK_LIST = "task_list"
    TASK = "task"
    WEATHER_LOCATION = "weather_location"


@dataclass(frozen=True)
class TargetIdentity:
    """Provider-neutral identity identifying a target resource or parent container.

    Distinguishes system namespace, resource kind, and target identifier.
    Does not import provider SDK object types.
    """

    system: str
    resource_kind: ResourceKind
    resource_id: str
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.system, str) or not self.system.strip():
            raise ValueError("system must be a non-empty string")

        if isinstance(self.resource_kind, str) and not isinstance(self.resource_kind, ResourceKind):
            try:
                rk = ResourceKind(self.resource_kind)
                object.__setattr__(self, "resource_kind", rk)
            except ValueError as exc:
                raise ValueError(f"Unsupported resource kind: {self.resource_kind!r}") from exc
        elif not isinstance(self.resource_kind, ResourceKind):
            raise TypeError("resource_kind must be a ResourceKind instance")

        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("resource_id must be a non-empty string")

        if self.parent_id is not None:
            if not isinstance(self.parent_id, str) or not self.parent_id.strip():
                raise ValueError("parent_id must be None or a non-empty string")


NormalizedScalar = str | int | float | bool | None


@dataclass(frozen=True)
class NormalizedParameters:
    """Immutable, deterministically sorted parameters for an action contract.

    Enforces stable key sorting, rejects unsupported nested or non-scalar types,
    rejects non-finite floats, and preserves string semantics.
    Self-validating regardless of construction path.
    """

    _items: tuple[tuple[str, NormalizedScalar], ...]

    def __post_init__(self) -> None:
        if not isinstance(self._items, tuple):
            raise TypeError(f"_items must be a tuple, got {type(self._items).__name__}")

        seen_keys: set[str] = set()
        validated: list[tuple[str, NormalizedScalar]] = []

        for entry in self._items:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError(
                    f"Each item in _items must be a 2-tuple (key, value), got {entry!r}"
                )
            key, val = entry

            if not isinstance(key, str):
                raise TypeError(f"Parameter key must be a string, got {type(key).__name__}")
            if not key.strip():
                raise ValueError("Parameter key cannot be blank or whitespace-only")

            if key in seen_keys:
                raise ValueError(f"Duplicate parameter key: {key!r}")
            seen_keys.add(key)

            if not isinstance(val, (str, int, float, bool, type(None))):
                raise TypeError(
                    f"Unsupported parameter value type for key {key!r}: {type(val).__name__}. "
                    f"Only JSON-like scalars (str, int, float, bool, None) are permitted."
                )

            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                raise ValueError(f"Non-finite float value for parameter key {key!r} is forbidden")

            validated.append((key, val))

        # Canonicalize to deterministic lexicographical order
        canonical_items = tuple(sorted(validated, key=lambda kv: kv[0]))
        object.__setattr__(self, "_items", canonical_items)

    @classmethod
    def from_dict(cls, params: Mapping[str, Any]) -> NormalizedParameters:
        """Construct normalized parameters from a key-value mapping."""
        if not isinstance(params, Mapping):
            raise TypeError(f"params must be a mapping, got {type(params).__name__}")

        # Validate all keys are strings and non-blank before sorting
        for key in params.keys():
            if not isinstance(key, str):
                raise TypeError(f"Parameter key must be a string, got {type(key).__name__}")
            if not key.strip():
                raise ValueError("Parameter key cannot be blank or whitespace-only")

        items = tuple((k, params[k]) for k in sorted(params.keys()))
        return cls(_items=items)

    def to_dict(self) -> dict[str, NormalizedScalar]:
        """Convert normalized parameters to a standard dictionary."""
        return dict(self._items)

    def get(self, key: str, default: NormalizedScalar = None) -> NormalizedScalar:
        """Lookup a parameter by key."""
        return dict(self._items).get(key, default)

    def __getitem__(self, key: str) -> NormalizedScalar:
        return dict(self._items)[key]

    def __iter__(self) -> Iterator[str]:
        for k, _ in self._items:
            yield k

    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> tuple[tuple[str, NormalizedScalar], ...]:
        """Return the immutable sorted tuple of parameter key-value pairs."""
        return self._items


@dataclass(frozen=True)
class ActionContract:
    """Immutable bounded action contract binding target and normalized parameters.

    Action IDs are runtime-owned opaque identities.
    Does not perform execution or authority verification.
    """

    action_id: ActionId
    mission_id: MissionId
    action_type: ActionType
    target: TargetIdentity
    parameters: NormalizedParameters

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, ActionId):
            raise TypeError("action_id must be an ActionId instance")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be a MissionId instance")

        if isinstance(self.action_type, str) and not isinstance(self.action_type, ActionType):
            try:
                at = ActionType(self.action_type)
                object.__setattr__(self, "action_type", at)
            except ValueError as exc:
                raise ValueError(f"Unsupported action type: {self.action_type!r}") from exc
        elif not isinstance(self.action_type, ActionType):
            raise TypeError("action_type must be an ActionType instance")

        if not isinstance(self.target, TargetIdentity):
            raise TypeError("target must be a TargetIdentity instance")
        if not isinstance(self.parameters, NormalizedParameters):
            raise TypeError("parameters must be a NormalizedParameters instance")

    @classmethod
    def create(
        cls,
        *,
        mission_id: MissionId,
        action_type: ActionType | str,
        target: TargetIdentity,
        parameters: Mapping[str, Any] | NormalizedParameters,
        action_id: ActionId | None = None,
    ) -> ActionContract:
        """Helper to construct an immutable ActionContract."""
        aid = action_id if action_id is not None else ActionId.generate()
        try:
            at = action_type if isinstance(action_type, ActionType) else ActionType(action_type)
        except ValueError as exc:
            raise ValueError(f"Unsupported action type: {action_type!r}") from exc

        norm_params = (
            parameters
            if isinstance(parameters, NormalizedParameters)
            else NormalizedParameters.from_dict(parameters)
        )
        return cls(
            action_id=aid,
            mission_id=mission_id,
            action_type=at,
            target=target,
            parameters=norm_params,
        )
