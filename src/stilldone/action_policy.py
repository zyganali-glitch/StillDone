"""Closed-world supported action allowlist and parameter validation boundary.

Enforces StillDone's fail-closed action security boundary:
- Finite allowable action vocabulary (ActionType: 5 canonical actions).
- Target system and ResourceKind compatibility matrix.
- Closed-world action-specific parameter schemas.
- Explicit deterministic bounds on string parameters.
- Strict type checking (e.g. bool is not int; no string-to-number coercions).
- No unknown, misspelled, or alias parameter keys.
- Complete error message safety (sensitive parameter plaintext is never echoed).
- Pure validation only: no provider imports, no network imports, no execution side effects,
  and no authority classification or approval grant creation.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId

# ===========================================================================
# Internal Deterministic Bounds
# ===========================================================================

# Small explicit internal security bound to prevent unbounded memory allocation
# or denial-of-service via massive parameter values.
# Note: This is an internal StillDone security boundary, not a provider API limit.
MAX_PARAM_STRING_LENGTH: int = 1024


# ===========================================================================
# Policy Exception Hierarchy
# ===========================================================================


class ActionPolicyError(Exception):
    """Base exception for all StillDone action policy and validation errors."""


class ActionPolicyTypeError(ActionPolicyError, TypeError):
    """Raised when an object or parameter has an unsupported or invalid type."""


class UnsupportedActionTypeError(ActionPolicyError, ValueError):
    """Raised when an action type is not supported by StillDone's closed-world policy."""


class ActionTargetCompatibilityError(ActionPolicyError, ValueError):
    """Raised when an action type is incompatible with its target system or resource kind."""


class ActionParameterPolicyError(ActionPolicyError, ValueError):
    """Base exception for action parameter schema and bounds violations."""


class UnknownParameterError(ActionParameterPolicyError):
    """Raised when an unknown, misspelled, or alias parameter key is supplied."""


class MissingRequiredParameterError(ActionParameterPolicyError):
    """Raised when a required action parameter is missing."""


class InvalidParameterTypeError(ActionParameterPolicyError, TypeError):
    """Raised when a parameter value violates the declared type for that action."""


class InvalidParameterValueError(ActionParameterPolicyError):
    """Raised when a parameter value violates content rules (e.g. empty or whitespace-only)."""


class OversizedParameterError(ActionParameterPolicyError):
    """Raised when a parameter string value exceeds the maximum allowable length."""


class EmptyParameterSetError(ActionParameterPolicyError):
    """Raised when an action requires parameters (e.g. calendar.update) but none were provided."""


# ===========================================================================
# Action Policy Model
# ===========================================================================


@dataclass(frozen=True)
class ActionPolicy:
    """Immutable policy defining the closed-world constraints for a canonical ActionType."""

    action_type: ActionType
    allowed_system: str
    allowed_resource_kind: ResourceKind
    supported_parameters: frozenset[str]
    required_parameters: frozenset[str]
    allow_empty_parameters: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, ActionType):
            raise TypeError(
                f"action_type must be an ActionType instance, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.allowed_system, str) or not self.allowed_system.strip():
            raise ValueError("allowed_system must be a non-empty string")
        if not isinstance(self.allowed_resource_kind, ResourceKind):
            raise TypeError(
                "allowed_resource_kind must be a ResourceKind instance, "
                f"got {type(self.allowed_resource_kind).__name__}"
            )
        if not isinstance(self.supported_parameters, frozenset):
            object.__setattr__(self, "supported_parameters", frozenset(self.supported_parameters))
        if not isinstance(self.required_parameters, frozenset):
            object.__setattr__(self, "required_parameters", frozenset(self.required_parameters))
        if not self.required_parameters.issubset(self.supported_parameters):
            raise ValueError("required_parameters must be a subset of supported_parameters")


# ===========================================================================
# Canonical Action Policy Table
# ===========================================================================

_POLICY_ENTRIES: dict[ActionType, ActionPolicy] = {
    ActionType.CALENDAR_READ: ActionPolicy(
        action_type=ActionType.CALENDAR_READ,
        allowed_system="google_calendar",
        allowed_resource_kind=ResourceKind.CALENDAR_EVENT,
        supported_parameters=frozenset(),
        required_parameters=frozenset(),
        allow_empty_parameters=True,
    ),
    ActionType.CALENDAR_UPDATE: ActionPolicy(
        action_type=ActionType.CALENDAR_UPDATE,
        allowed_system="google_calendar",
        allowed_resource_kind=ResourceKind.CALENDAR_EVENT,
        supported_parameters=frozenset({"summary", "start_time", "all_day"}),
        required_parameters=frozenset(),
        allow_empty_parameters=False,
    ),
    ActionType.TASK_READ: ActionPolicy(
        action_type=ActionType.TASK_READ,
        allowed_system="google_tasks",
        allowed_resource_kind=ResourceKind.TASK,
        supported_parameters=frozenset(),
        required_parameters=frozenset(),
        allow_empty_parameters=True,
    ),
    ActionType.TASK_CREATE: ActionPolicy(
        action_type=ActionType.TASK_CREATE,
        allowed_system="google_tasks",
        allowed_resource_kind=ResourceKind.TASK_LIST,
        supported_parameters=frozenset({"title", "due"}),
        required_parameters=frozenset({"title"}),
        allow_empty_parameters=False,
    ),
    ActionType.WEATHER_READ: ActionPolicy(
        action_type=ActionType.WEATHER_READ,
        allowed_system="open_meteo",
        allowed_resource_kind=ResourceKind.WEATHER_LOCATION,
        supported_parameters=frozenset(),
        required_parameters=frozenset(),
        allow_empty_parameters=True,
    ),
}

# Module-level invariant: exact 1:1 mapping with ActionType
assert set(_POLICY_ENTRIES.keys()) == set(ActionType), (
    "ACTION_POLICIES must cover all canonical ActionType members"
)
assert len(_POLICY_ENTRIES) == len(ActionType) == 5, "ACTION_POLICIES must have exactly 5 entries"

ACTION_POLICIES: Mapping[ActionType, ActionPolicy] = types.MappingProxyType(_POLICY_ENTRIES)


# ===========================================================================
# Action-Specific Parameter Validators
# ===========================================================================


def _validate_calendar_read_parameters(action: ActionContract) -> None:
    if len(action.parameters) > 0:
        offending_key = next(iter(action.parameters))
        raise UnknownParameterError(
            f"Action '{action.action_type.value}' does not accept parameters, "
            f"but parameter '{offending_key}' was provided"
        )


def _validate_calendar_update_parameters(action: ActionContract) -> None:
    params = action.parameters
    if len(params) == 0:
        raise EmptyParameterSetError(
            f"Action '{action.action_type.value}' requires at least one supported update parameter"
        )

    supported = {"summary", "start_time", "all_day"}
    for key, val in params.items():
        if key not in supported:
            raise UnknownParameterError(
                f"Action '{action.action_type.value}' does not accept parameter '{key}'. "
                f"Supported parameters: {sorted(supported)}"
            )

        if key in ("summary", "start_time"):
            if type(val) is not str:
                raise InvalidParameterTypeError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    f"must be of type str, got {type(val).__name__}"
                )
            if not val.strip():
                raise InvalidParameterValueError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    "cannot be empty or whitespace-only"
                )
            if len(val) > MAX_PARAM_STRING_LENGTH:
                raise OversizedParameterError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    f"exceeds maximum allowed length of {MAX_PARAM_STRING_LENGTH} characters "
                    f"(actual length: {len(val)})"
                )
        elif key == "all_day":
            if type(val) is not bool:
                raise InvalidParameterTypeError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    f"must be of type bool, got {type(val).__name__}"
                )


def _validate_task_read_parameters(action: ActionContract) -> None:
    if len(action.parameters) > 0:
        offending_key = next(iter(action.parameters))
        raise UnknownParameterError(
            f"Action '{action.action_type.value}' does not accept parameters, "
            f"but parameter '{offending_key}' was provided"
        )


def _validate_task_create_parameters(action: ActionContract) -> None:
    params = action.parameters
    if "title" not in params:
        raise MissingRequiredParameterError(
            f"Action '{action.action_type.value}' missing required parameter 'title'"
        )

    supported = {"title", "due"}
    for key, val in params.items():
        if key not in supported:
            raise UnknownParameterError(
                f"Action '{action.action_type.value}' does not accept parameter '{key}'. "
                f"Supported parameters: {sorted(supported)}"
            )

        if key in ("title", "due"):
            if type(val) is not str:
                raise InvalidParameterTypeError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    f"must be of type str, got {type(val).__name__}"
                )
            if not val.strip():
                raise InvalidParameterValueError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    "cannot be empty or whitespace-only"
                )
            if len(val) > MAX_PARAM_STRING_LENGTH:
                raise OversizedParameterError(
                    f"Parameter '{key}' for action '{action.action_type.value}' "
                    f"exceeds maximum allowed length of {MAX_PARAM_STRING_LENGTH} characters "
                    f"(actual length: {len(val)})"
                )


def _validate_weather_read_parameters(action: ActionContract) -> None:
    if len(action.parameters) > 0:
        offending_key = next(iter(action.parameters))
        raise UnknownParameterError(
            f"Action '{action.action_type.value}' does not accept parameters, "
            f"but parameter '{offending_key}' was provided"
        )


_PARAMETER_VALIDATORS: dict[ActionType, Callable[[ActionContract], None]] = {
    ActionType.CALENDAR_READ: _validate_calendar_read_parameters,
    ActionType.CALENDAR_UPDATE: _validate_calendar_update_parameters,
    ActionType.TASK_READ: _validate_task_read_parameters,
    ActionType.TASK_CREATE: _validate_task_create_parameters,
    ActionType.WEATHER_READ: _validate_weather_read_parameters,
}

assert set(_PARAMETER_VALIDATORS.keys()) == set(ActionType), (
    "All ActionType members must have a dedicated parameter validator"
)


# ===========================================================================
# Internal Core Validation
# ===========================================================================


def _validate_contract_internal(action: ActionContract) -> None:
    """Validate action contract against policy table and parameter schemas.

    Performs validation only. Does not confer authority, create approval grants,
    or execute actions.
    """
    if not isinstance(action, ActionContract):
        raise ActionPolicyTypeError(
            f"action must be an ActionContract instance, got {type(action).__name__}"
        )

    # 1. ActionType validation
    if not isinstance(action.action_type, ActionType):
        raise UnsupportedActionTypeError(
            f"Unsupported action type: {getattr(action, 'action_type', None)!r}"
        )

    policy = ACTION_POLICIES.get(action.action_type)
    if policy is None:
        raise UnsupportedActionTypeError(
            f"No policy defined for action type: {action.action_type!r}"
        )

    # 2. Target compatibility validation
    if not isinstance(action.target, TargetIdentity):
        raise ActionPolicyTypeError(
            f"action.target must be a TargetIdentity instance, got {type(action.target).__name__}"
        )

    if action.target.system != policy.allowed_system:
        raise ActionTargetCompatibilityError(
            f"Action '{action.action_type.value}' requires target system "
            f"'{policy.allowed_system}', got '{action.target.system}'"
        )

    if action.target.resource_kind != policy.allowed_resource_kind:
        raise ActionTargetCompatibilityError(
            f"Action '{action.action_type.value}' requires target resource kind "
            f"'{policy.allowed_resource_kind.value}', got '{action.target.resource_kind.value}'"
        )

    if not isinstance(action.target.resource_id, str) or not action.target.resource_id.strip():
        raise ActionTargetCompatibilityError(
            f"Action '{action.action_type.value}' target resource_id must be a non-empty string"
        )

    # 3. Parameters type validation
    if not isinstance(action.parameters, NormalizedParameters):
        raise ActionPolicyTypeError(
            "action.parameters must be a NormalizedParameters instance, "
            f"got {type(action.parameters).__name__}"
        )

    # 4. Action-specific parameter schema validation
    validator = _PARAMETER_VALIDATORS.get(action.action_type)
    if validator is None:
        raise UnsupportedActionTypeError(
            f"No parameter validator registered for action type: {action.action_type!r}"
        )
    validator(action)


# ===========================================================================
# Validated Action Contract & Public API
# ===========================================================================


@dataclass(frozen=True)
class ValidatedActionContract:
    """Explicitly validated action contract passing StillDone's closed-world action policy.

    Confirms the action is supported and parameters conform to closed-world action schema.
    Does NOT confer authority, create approval grants, or indicate execution permission.
    Self-validating on construction to prevent bypass.
    """

    action: ActionContract

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActionContract):
            raise ActionPolicyTypeError(
                f"action must be an ActionContract instance, got {type(self.action).__name__}"
            )
        _validate_contract_internal(self.action)

    @property
    def action_id(self) -> ActionId:
        """Runtime-owned opaque action identifier."""
        return self.action.action_id

    @property
    def mission_id(self) -> MissionId:
        """Mission identifier."""
        return self.action.mission_id

    @property
    def action_type(self) -> ActionType:
        """Canonical action type."""
        return self.action.action_type

    @property
    def target(self) -> TargetIdentity:
        """Target resource identity."""
        return self.action.target

    @property
    def parameters(self) -> NormalizedParameters:
        """Normalized action parameters."""
        return self.action.parameters


def validate_action_contract(action: ActionContract) -> ValidatedActionContract:
    """Validate an ActionContract against StillDone's closed-world policy.

    Args:
        action: The ActionContract to validate.

    Returns:
        ValidatedActionContract wrapping the validated action contract.

    Raises:
        ActionPolicyTypeError: If the input object or its fields have invalid types.
        UnsupportedActionTypeError: If the action type is not supported.
        ActionTargetCompatibilityError: If target system or resource kind is incompatible.
        EmptyParameterSetError: If required parameter set is empty.
        MissingRequiredParameterError: If a required parameter is missing.
        UnknownParameterError: If an unknown parameter key is present.
        InvalidParameterTypeError: If a parameter value has an unexpected type.
        InvalidParameterValueError: If a string parameter is empty or whitespace-only.
        OversizedParameterError: If a string parameter exceeds MAX_PARAM_STRING_LENGTH.
    """
    _validate_contract_internal(action)
    return ValidatedActionContract(action=action)


__all__ = [
    "ACTION_POLICIES",
    "MAX_PARAM_STRING_LENGTH",
    "ActionParameterPolicyError",
    "ActionPolicy",
    "ActionPolicyError",
    "ActionPolicyTypeError",
    "ActionTargetCompatibilityError",
    "EmptyParameterSetError",
    "InvalidParameterTypeError",
    "InvalidParameterValueError",
    "MissingRequiredParameterError",
    "OversizedParameterError",
    "UnknownParameterError",
    "UnsupportedActionTypeError",
    "ValidatedActionContract",
    "validate_action_contract",
]
