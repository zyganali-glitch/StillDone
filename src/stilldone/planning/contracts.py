"""Strict planner input/output schemas and supported action vocabulary for StillDone.

Phase P-07.01:
Freezes the deterministic boundary between non-authoritative model proposals
and StillDone's deterministic runtime authority, desired-state predicates,
and independent verification.

Laws:
- Model output is a proposal only; deterministic runtime owns facts and authority.
- The planner vocabulary contains EXACTLY the five canonical ActionType members.
- Models may NEVER fabricate provider external identifiers (calendar_id, event_id, etc.).
- Bounded symbolic target references are used instead of external IDs.
- Model prose ('verified', 'ready', 'approved') remains inert text with ZERO deterministic effect.
- Zero provider SDK imports, zero model SDK imports, zero network execution.
"""

from __future__ import annotations

import json
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stilldone.action_policy import (
    ACTION_POLICIES,
    MAX_PARAM_STRING_LENGTH,
    EmptyParameterSetError,
    InvalidParameterTypeError,
    InvalidParameterValueError,
    MissingRequiredParameterError,
    OversizedParameterError,
    UnknownParameterError,
)
from stilldone.domain.action import (
    ActionType,
    NormalizedParameters,
    NormalizedScalar,
)
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.serialization import canonical_json

# ===========================================================================
# Deterministic Planning Constants & Bounds
# ===========================================================================

PLANNER_SCHEMA_VERSION: str = "v1"
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({PLANNER_SCHEMA_VERSION})

# Small internal security bound on proposed plan step count appropriate
# to the canonical killer mission path (typically 3-4 steps).
MAX_PLAN_STEPS: int = 10

# Bounded string limits for intent and model explanation text
MAX_INTENT_STRING_LENGTH: int = 1024
MAX_EXPLANATION_STRING_LENGTH: int = 2048
MAX_SYMBOLIC_TARGET_LENGTH: int = 64

# Maximum raw JSON payload size allowed before decoding untrusted planner JSON (64 KiB)
MAX_PLANNER_JSON_BYTES: int = 64 * 1024

# Canonical Action Vocabulary: EXACTLY the five canonical ActionType members.
PLANNER_ACTION_VOCABULARY: frozenset[ActionType] = frozenset(ActionType)
assert len(PLANNER_ACTION_VOCABULARY) == 5, (
    "Planner vocabulary must have exactly 5 canonical actions"
)
assert PLANNER_ACTION_VOCABULARY == set(ActionType), (
    "Planner vocabulary must match ActionType set exactly"
)


# ===========================================================================
# Symbolic Target Vocabulary
# ===========================================================================


class SymbolicTargetRef(StrEnum):
    """Finite closed vocabulary of symbolic target references for StillDone planning.

    Prevents models from fabricating authoritative provider external IDs
    (such as calendar_id, event_id, task_list_id, task_id, resource_id, parent_id).
    Actual external identifiers remain runtime-resolved deterministic facts.
    """

    # Calendar event symbolic targets
    LEAVE_FOR_SCHOOL = "leave_for_school"
    CALENDAR_EVENT = "calendar_event"
    DEMO_EVENT = "demo_event"
    MORNING_EVENT = "morning_event"

    # Task list / Task symbolic targets
    TASK_LIST = "task_list"
    DEMO_TASK_LIST = "demo_task_list"
    FAMILY_TASKS = "family_tasks"
    TASK = "task"
    DEMO_TASK = "demo_task"
    PACK_BACKPACKS = "pack_backpacks"

    # Weather location symbolic targets
    WEATHER_LOCATION = "weather_location"
    LOCAL_WEATHER = "local_weather"
    HOME_LOCATION = "home_location"


ACTION_SYMBOLIC_TARGET_COMPATIBILITY: Mapping[ActionType, frozenset[SymbolicTargetRef]] = (
    types.MappingProxyType(
        {
            ActionType.CALENDAR_READ: frozenset(
                {
                    SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                    SymbolicTargetRef.CALENDAR_EVENT,
                    SymbolicTargetRef.DEMO_EVENT,
                    SymbolicTargetRef.MORNING_EVENT,
                }
            ),
            ActionType.CALENDAR_UPDATE: frozenset(
                {
                    SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                    SymbolicTargetRef.CALENDAR_EVENT,
                    SymbolicTargetRef.DEMO_EVENT,
                    SymbolicTargetRef.MORNING_EVENT,
                }
            ),
            ActionType.TASK_READ: frozenset(
                {
                    SymbolicTargetRef.TASK,
                    SymbolicTargetRef.DEMO_TASK,
                    SymbolicTargetRef.PACK_BACKPACKS,
                }
            ),
            ActionType.TASK_CREATE: frozenset(
                {
                    SymbolicTargetRef.TASK_LIST,
                    SymbolicTargetRef.DEMO_TASK_LIST,
                    SymbolicTargetRef.FAMILY_TASKS,
                }
            ),
            ActionType.WEATHER_READ: frozenset(
                {
                    SymbolicTargetRef.WEATHER_LOCATION,
                    SymbolicTargetRef.LOCAL_WEATHER,
                    SymbolicTargetRef.HOME_LOCATION,
                }
            ),
        }
    )
)

assert set(ACTION_SYMBOLIC_TARGET_COMPATIBILITY.keys()) == set(ActionType), (
    "All ActionType members must have defined symbolic target compatibility"
)


# ===========================================================================
# Forbidden Injected Fields & Identifiers
# ===========================================================================

FORBIDDEN_PROVIDER_ID_FIELDS: frozenset[str] = frozenset(
    {
        "calendar_id",
        "event_id",
        "task_list_id",
        "task_id",
        "resource_id",
        "parent_id",
        "provider_resource_id",
        "provider_parent_id",
        "account_id",
        "oauth_token",
        "access_token",
        "refresh_token",
    }
)

FORBIDDEN_AUTHORITY_AND_FACT_FIELDS: frozenset[str] = frozenset(
    {
        "approval_grant",
        "approval_id",
        "authority_class",
        "authority_decision",
        "authorized",
        "is_authorized",
        "verified",
        "is_verified",
        "ready",
        "is_ready",
        "step_evidence_state",
        "evidence_id",
        "evidence_provenance",
        "freshness_status",
        "reconciliation_result",
        "drift_result",
        "execution_attempt",
        "status",
    }
)


# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class PlannerContractError(Exception):
    """Base exception for all StillDone planner contract and validation errors."""


class PlannerTypeError(PlannerContractError, TypeError):
    """Raised when an object or field has an invalid type."""


class PlannerValueError(PlannerContractError, ValueError):
    """Base exception for value, bounds, and schema violations in planner contracts."""


class UnsupportedSchemaVersionError(PlannerValueError):
    """Raised when the schema version is not supported."""


class UnknownActionTypeError(PlannerValueError):
    """Raised when an action type is not one of the five canonical ActionType members."""


class UnknownSymbolicTargetError(PlannerValueError):
    """Raised when a symbolic target reference is unknown or not recognized."""


class IncompatibleSymbolicTargetError(PlannerValueError):
    """Raised when a symbolic target is incompatible with the specified ActionType."""


class UnknownFieldPolicyError(PlannerValueError):
    """Raised when unknown/extra fields are detected in top-level or per-step objects."""


class ProviderIdentifierInjectionError(UnknownFieldPolicyError):
    """Raised when a proposal attempts to inject raw provider external identifiers."""


class ModelAuthorityInjectionError(UnknownFieldPolicyError):
    """Raised when a proposal attempts to inject authority, verification, or evidence states."""


class OversizedStringError(PlannerValueError):
    """Raised when a string field exceeds maximum length bounds."""


class InvalidIntentError(PlannerValueError):
    """Raised when mission intent text is empty, whitespace-only, or invalid."""


class OversizedIntentError(OversizedStringError):
    """Raised when mission intent text exceeds MAX_INTENT_STRING_LENGTH."""


class EmptyPlanError(PlannerValueError):
    """Raised when a candidate plan proposal contains zero steps."""


class OversizedPlanError(PlannerValueError):
    """Raised when a candidate plan proposal exceeds MAX_PLAN_STEPS."""


class MissingRequiredFieldError(PlannerValueError):
    """Raised when a required top-level or per-step field is missing."""


class DuplicateKeyError(PlannerValueError):
    """Raised when duplicate keys are encountered in JSON parsing."""


class OversizedJsonPayloadError(PlannerValueError):
    """Raised when raw JSON payload exceeds MAX_PLANNER_JSON_BYTES before decoding."""


class PlannerMissionBindingError(PlannerValueError):
    """Raised when candidate plan mission_id does not match planner_input.mission_id."""


# ===========================================================================
# JSON Helper: Duplicate Key Prevention & Raw Payload Bounds
# ===========================================================================


def _validate_raw_json_payload(json_str: str) -> None:
    """Strictly enforce raw JSON payload size ceiling before decoding."""
    if type(json_str) is not str:
        raise PlannerTypeError(f"json_str must be a string, got {type(json_str).__name__}")
    encoded_len = len(json_str.encode("utf-8"))
    if encoded_len > MAX_PLANNER_JSON_BYTES:
        raise OversizedJsonPayloadError(
            f"Raw JSON payload size ({encoded_len} bytes) exceeds maximum "
            f"allowed limit of {MAX_PLANNER_JSON_BYTES} bytes"
        )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Strict JSON object pairs hook rejecting duplicate keys fail-closed."""
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in seen:
            raise DuplicateKeyError(f"Duplicate key in JSON input: {k!r}")
        seen.add(k)
        result[k] = v
    return result


# ===========================================================================
# Proposal Parameter Validation (Reuses Canonical Policy Without Fabricated IDs)
# ===========================================================================


def validate_candidate_action_parameters(
    action_type: ActionType,
    parameters: Mapping[str, Any] | NormalizedParameters,
) -> NormalizedParameters:
    """Validate proposal action parameters against canonical ActionPolicy rules.

    Reuses ACTION_POLICIES and MAX_PARAM_STRING_LENGTH directly from the canonical
    action policy module without fabricating provider TargetIdentity or ActionId.
    Enforces strict types (rejects bool-as-int and string-to-numeric coercions).
    """
    if not isinstance(action_type, ActionType):
        raise UnknownActionTypeError(
            f"action_type must be an ActionType instance, got {type(action_type).__name__}"
        )

    if isinstance(parameters, NormalizedParameters):
        raw_dict: dict[str, NormalizedScalar] = parameters.to_dict()
    elif isinstance(parameters, Mapping):
        # Validate all keys are non-empty strings
        for k in parameters.keys():
            if type(k) is not str:
                raise PlannerTypeError(f"Parameter key must be a string, got {type(k).__name__}")
            if not k.strip():
                raise PlannerValueError("Parameter key cannot be blank or whitespace-only")
        raw_dict = dict(parameters)
    else:
        err_msg = (
            f"parameters must be a Mapping or NormalizedParameters instance, "
            f"got {type(parameters).__name__}"
        )
        raise PlannerTypeError(err_msg)

    # 1. Parameter presence and emptiness rules
    if action_type in (
        ActionType.CALENDAR_READ,
        ActionType.TASK_READ,
        ActionType.WEATHER_READ,
    ):
        if len(raw_dict) > 0:
            offending_key = next(iter(raw_dict))
            raise UnknownParameterError(
                f"Action '{action_type.value}' does not accept parameters, "
                f"but parameter '{offending_key}' was provided"
            )

    elif action_type == ActionType.CALENDAR_UPDATE:
        if len(raw_dict) == 0:
            raise EmptyParameterSetError(
                f"Action '{action_type.value}' requires at least one supported update parameter"
            )
        supported = ACTION_POLICIES[ActionType.CALENDAR_UPDATE].supported_parameters
        for key, val in raw_dict.items():
            if key not in supported:
                raise UnknownParameterError(
                    f"Action '{action_type.value}' does not accept parameter '{key}'. "
                    f"Supported parameters: {sorted(supported)}"
                )
            if key in ("summary", "start_time"):
                if type(val) is not str:
                    raise InvalidParameterTypeError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        f"must be of type str, got {type(val).__name__}"
                    )
                if not val.strip():
                    raise InvalidParameterValueError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        "cannot be empty or whitespace-only"
                    )
                if len(val) > MAX_PARAM_STRING_LENGTH:
                    raise OversizedParameterError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        f"exceeds maximum allowed length of {MAX_PARAM_STRING_LENGTH} characters "
                        f"(actual length: {len(val)})"
                    )
            elif key == "all_day":
                # Strict bool check: reject int (1, 0)
                if type(val) is not bool:
                    raise InvalidParameterTypeError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        f"must be of type bool, got {type(val).__name__}"
                    )

    elif action_type == ActionType.TASK_CREATE:
        if "title" not in raw_dict:
            raise MissingRequiredParameterError(
                f"Action '{action_type.value}' missing required parameter 'title'"
            )
        supported = ACTION_POLICIES[ActionType.TASK_CREATE].supported_parameters
        for key, val in raw_dict.items():
            if key not in supported:
                raise UnknownParameterError(
                    f"Action '{action_type.value}' does not accept parameter '{key}'. "
                    f"Supported parameters: {sorted(supported)}"
                )
            if key in ("title", "due"):
                if type(val) is not str:
                    raise InvalidParameterTypeError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        f"must be of type str, got {type(val).__name__}"
                    )
                if not val.strip():
                    raise InvalidParameterValueError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        "cannot be empty or whitespace-only"
                    )
                if len(val) > MAX_PARAM_STRING_LENGTH:
                    raise OversizedParameterError(
                        f"Parameter '{key}' for action '{action_type.value}' "
                        f"exceeds maximum allowed length of {MAX_PARAM_STRING_LENGTH} characters "
                        f"(actual length: {len(val)})"
                    )

    # Convert to canonical immutable NormalizedParameters
    return NormalizedParameters.from_dict(raw_dict)


# ===========================================================================
# Planner Input Contract
# ===========================================================================


@dataclass(frozen=True)
class PlannerInput:
    """Immutable, minimal planner input contract for StillDone.

    Binds schema version, mission identity, and bounded natural-language intent.
    Contains strictly runtime-supplied context, confers zero authority, and
    carries zero provider credentials or model SDK objects.
    """

    mission_id: MissionId
    intent: str
    schema_version: str = PLANNER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str:
            raise PlannerTypeError(
                f"schema_version must be a string, got {type(self.schema_version).__name__}"
            )
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(
                f"Unsupported schema version: {self.schema_version!r}. "
                f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        if not isinstance(self.mission_id, MissionId):
            raise PlannerTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )

        if type(self.intent) is not str:
            raise PlannerTypeError(f"intent must be a string, got {type(self.intent).__name__}")
        if not self.intent.strip():
            raise InvalidIntentError("Mission intent cannot be blank or whitespace-only")
        if len(self.intent) > MAX_INTENT_STRING_LENGTH:
            raise OversizedIntentError(
                f"intent exceeds maximum allowed length of {MAX_INTENT_STRING_LENGTH} characters "
                f"(actual length: {len(self.intent)})"
            )

    @classmethod
    def from_mission(cls, mission: MissionContract) -> PlannerInput:
        """Create a PlannerInput snapshot directly from a canonical MissionContract."""
        if not isinstance(mission, MissionContract):
            raise PlannerTypeError(
                f"mission must be a MissionContract instance, got {type(mission).__name__}"
            )
        return cls(
            mission_id=mission.mission_id,
            intent=mission.intent.text,
            schema_version=PLANNER_SCHEMA_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert input contract to a deterministic serializable dictionary."""
        return {
            "schema_version": self.schema_version,
            "mission_id": str(self.mission_id),
            "intent": self.intent,
        }

    def to_json(self) -> str:
        """Serialize input contract into canonical JSON."""
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlannerInput:
        """Strictly deserialize and validate a PlannerInput mapping.

        Rejects unknown fields, malformed types, missing required fields, and oversized strings.
        """
        if not isinstance(data, Mapping):
            raise PlannerTypeError(f"Planner input must be a mapping, got {type(data).__name__}")

        allowed_keys = {"schema_version", "mission_id", "intent"}
        for k in data.keys():
            if type(k) is not str:
                raise PlannerTypeError(f"Key must be a string, got {type(k).__name__}")
            if k not in allowed_keys:
                raise UnknownFieldPolicyError(f"Unknown field in planner input: {k!r}")

        if "mission_id" not in data:
            raise MissingRequiredFieldError("Missing required field 'mission_id' in planner input")
        if "intent" not in data:
            raise MissingRequiredFieldError("Missing required field 'intent' in planner input")

        raw_sv = data.get("schema_version", PLANNER_SCHEMA_VERSION)
        if type(raw_sv) is not str:
            raise PlannerTypeError(f"schema_version must be a string, got {type(raw_sv).__name__}")
        if raw_sv not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(f"Unsupported schema version: {raw_sv!r}")

        raw_mid = data["mission_id"]
        if isinstance(raw_mid, MissionId):
            mid = raw_mid
        elif isinstance(raw_mid, str):
            try:
                mid = MissionId(raw_mid)
            except (ValueError, TypeError) as exc:
                raise PlannerValueError(f"Invalid mission_id: {raw_mid!r}") from exc
        else:
            raise PlannerTypeError(
                f"mission_id must be a string or MissionId, got {type(raw_mid).__name__}"
            )

        raw_intent = data["intent"]
        if type(raw_intent) is not str:
            raise PlannerTypeError(f"intent must be a string, got {type(raw_intent).__name__}")

        return cls(
            schema_version=raw_sv,
            mission_id=mid,
            intent=raw_intent,
        )

    @classmethod
    def from_json(cls, json_str: str) -> PlannerInput:
        """Parse PlannerInput from JSON with raw size bounds and duplicate key detection."""
        _validate_raw_json_payload(json_str)
        try:
            data = json.loads(json_str, object_pairs_hook=_reject_duplicate_json_keys)
        except json.JSONDecodeError as exc:
            raise PlannerValueError(f"Malformed JSON: {exc}") from exc
        return cls.from_dict(data)


# ===========================================================================
# Candidate Action Proposal Contract
# ===========================================================================


@dataclass(frozen=True)
class CandidateActionProposal:
    """Immutable single action proposal produced by a model or planner.

    PROPOSAL ONLY: Confers zero authority, creates zero approval grants,
    and cannot assert fact or verification state.
    Uses bounded symbolic target references instead of raw provider IDs.
    """

    action_type: ActionType
    target_ref: SymbolicTargetRef
    parameters: NormalizedParameters
    explanation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, ActionType):
            raise UnknownActionTypeError(
                f"action_type must be an ActionType instance, got {type(self.action_type).__name__}"
            )

        if not isinstance(self.target_ref, SymbolicTargetRef):
            msg = (
                f"target_ref must be a SymbolicTargetRef instance, "
                f"got {type(self.target_ref).__name__}"
            )
            raise UnknownSymbolicTargetError(msg)

        # Enforce action-to-symbolic-target compatibility
        allowed_targets = ACTION_SYMBOLIC_TARGET_COMPATIBILITY.get(self.action_type, frozenset())
        if self.target_ref not in allowed_targets:
            msg = (
                f"Symbolic target '{self.target_ref.value}' is incompatible with "
                f"action '{self.action_type.value}'. "
                f"Allowed targets: {sorted([t.value for t in allowed_targets])}"
            )
            raise IncompatibleSymbolicTargetError(msg)

        if not isinstance(self.parameters, NormalizedParameters):
            msg = (
                f"parameters must be a NormalizedParameters instance, "
                f"got {type(self.parameters).__name__}"
            )
            raise PlannerTypeError(msg)

        # Re-validate candidate parameters structurally
        validate_candidate_action_parameters(self.action_type, self.parameters)

        if self.explanation is not None:
            if type(self.explanation) is not str:
                raise PlannerTypeError(
                    f"explanation must be a string or None, got {type(self.explanation).__name__}"
                )
            if len(self.explanation) > MAX_EXPLANATION_STRING_LENGTH:
                msg = (
                    f"explanation exceeds maximum length of {MAX_EXPLANATION_STRING_LENGTH} "
                    f"characters (actual length: {len(self.explanation)})"
                )
                raise OversizedStringError(msg)

    @classmethod
    def create(
        cls,
        *,
        action_type: ActionType | str,
        target_ref: SymbolicTargetRef | str,
        parameters: Mapping[str, Any] | NormalizedParameters | None = None,
        explanation: str | None = None,
    ) -> CandidateActionProposal:
        """Safe constructor validating string inputs and normalizing parameters."""
        if isinstance(action_type, ActionType):
            at = action_type
        elif type(action_type) is str:
            try:
                at = ActionType(action_type)
            except ValueError as exc:
                raise UnknownActionTypeError(f"Unsupported action type: {action_type!r}") from exc
        else:
            raise PlannerTypeError(
                f"action_type must be an ActionType or string, got {type(action_type).__name__}"
            )

        if isinstance(target_ref, SymbolicTargetRef):
            tr = target_ref
        elif type(target_ref) is str:
            try:
                tr = SymbolicTargetRef(target_ref)
            except ValueError as exc:
                raise UnknownSymbolicTargetError(
                    f"Unknown symbolic target reference: {target_ref!r}"
                ) from exc
        else:
            raise PlannerTypeError(
                f"target_ref must be a SymbolicTargetRef or string, got {type(target_ref).__name__}"
            )

        params_in = parameters if parameters is not None else {}
        norm_params = validate_candidate_action_parameters(at, params_in)

        return cls(
            action_type=at,
            target_ref=tr,
            parameters=norm_params,
            explanation=explanation,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert action proposal to a deterministic dictionary."""
        result: dict[str, Any] = {
            "action_type": self.action_type.value,
            "target_ref": self.target_ref.value,
            "parameters": self.parameters.to_dict(),
        }
        if self.explanation is not None:
            result["explanation"] = self.explanation
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidateActionProposal:
        """Strictly deserialize and validate a single action proposal mapping.

        Rejects unknown fields, raw provider ID injection, authority injection,
        verification injection, unsupported actions, and malformed types.
        """
        if not isinstance(data, Mapping):
            raise PlannerTypeError(f"Action proposal must be a mapping, got {type(data).__name__}")

        allowed_keys = {"action_type", "target_ref", "parameters", "explanation"}
        for k in data.keys():
            if type(k) is not str:
                raise PlannerTypeError(f"Proposal key must be a string, got {type(k).__name__}")
            if k not in allowed_keys:
                if k in FORBIDDEN_PROVIDER_ID_FIELDS:
                    raise ProviderIdentifierInjectionError(
                        f"Attempt to inject raw provider identifier {k!r} is forbidden; "
                        "use symbolic target references"
                    )
                if k in FORBIDDEN_AUTHORITY_AND_FACT_FIELDS:
                    raise ModelAuthorityInjectionError(
                        f"Attempt to inject authority/fact field {k!r} is forbidden; "
                        "model output is proposal only"
                    )
                raise UnknownFieldPolicyError(f"Unknown field in action proposal: {k!r}")

        if "action_type" not in data:
            raise MissingRequiredFieldError(
                "Missing required field 'action_type' in action proposal"
            )
        if "target_ref" not in data:
            raise MissingRequiredFieldError(
                "Missing required field 'target_ref' in action proposal"
            )

        raw_action = data["action_type"]
        if type(raw_action) is not str and not isinstance(raw_action, ActionType):
            raise PlannerTypeError(f"action_type must be a string, got {type(raw_action).__name__}")
        try:
            at = ActionType(raw_action)
        except ValueError as exc:
            raise UnknownActionTypeError(f"Unsupported action type: {raw_action!r}") from exc

        raw_target = data["target_ref"]
        if type(raw_target) is not str and not isinstance(raw_target, SymbolicTargetRef):
            raise PlannerTypeError(f"target_ref must be a string, got {type(raw_target).__name__}")
        try:
            target_ref = SymbolicTargetRef(raw_target)
        except ValueError as exc:
            raise UnknownSymbolicTargetError(
                f"Unknown symbolic target reference: {raw_target!r}"
            ) from exc

        raw_params = data.get("parameters", {})
        norm_params = validate_candidate_action_parameters(at, raw_params)

        raw_explanation = data.get("explanation")
        if raw_explanation is not None and type(raw_explanation) is not str:
            raise PlannerTypeError(
                f"explanation must be a string, got {type(raw_explanation).__name__}"
            )

        return cls(
            action_type=at,
            target_ref=target_ref,
            parameters=norm_params,
            explanation=raw_explanation,
        )


# ===========================================================================
# Candidate Plan Proposal Contract
# ===========================================================================


@dataclass(frozen=True)
class CandidatePlanProposal:
    """Immutable candidate plan output proposal containing ordered action proposals.

    The model output is a PROPOSAL ONLY.
    Preserves exact step ordering as proposed.
    Enforces minimum 1 step and maximum MAX_PLAN_STEPS.
    Empty plans fail closed.
    """

    mission_id: MissionId
    steps: tuple[CandidateActionProposal, ...]
    schema_version: str = PLANNER_SCHEMA_VERSION
    explanation: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str:
            raise PlannerTypeError(
                f"schema_version must be a string, got {type(self.schema_version).__name__}"
            )
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(
                f"Unsupported schema version: {self.schema_version!r}"
            )

        if not isinstance(self.mission_id, MissionId):
            raise PlannerTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )

        if not isinstance(self.steps, tuple):
            raise PlannerTypeError(f"steps must be a tuple, got {type(self.steps).__name__}")

        if len(self.steps) == 0:
            raise EmptyPlanError(
                "Candidate plan proposal must contain at least one step (empty plans fail closed)"
            )
        if len(self.steps) > MAX_PLAN_STEPS:
            raise OversizedPlanError(
                f"Candidate plan proposal exceeds maximum of {MAX_PLAN_STEPS} steps "
                f"(actual: {len(self.steps)})"
            )

        for i, step in enumerate(self.steps):
            if not isinstance(step, CandidateActionProposal):
                msg = (
                    f"Step {i} must be a CandidateActionProposal instance, "
                    f"got {type(step).__name__}"
                )
                raise PlannerTypeError(msg)

        if self.explanation is not None:
            if type(self.explanation) is not str:
                raise PlannerTypeError(
                    f"explanation must be a string or None, got {type(self.explanation).__name__}"
                )
            if len(self.explanation) > MAX_EXPLANATION_STRING_LENGTH:
                msg = (
                    f"explanation exceeds maximum length of {MAX_EXPLANATION_STRING_LENGTH} "
                    f"characters (actual length: {len(self.explanation)})"
                )
                raise OversizedStringError(msg)

    @classmethod
    def create(
        cls,
        *,
        mission_id: MissionId | str,
        steps: Sequence[CandidateActionProposal],
        explanation: str | None = None,
        schema_version: str = PLANNER_SCHEMA_VERSION,
    ) -> CandidatePlanProposal:
        """Safe constructor preserving sequence ordering into an immutable tuple."""
        mid = mission_id if isinstance(mission_id, MissionId) else MissionId(str(mission_id))
        if not isinstance(steps, Sequence):
            raise PlannerTypeError(
                f"steps must be a sequence of CandidateActionProposal, got {type(steps).__name__}"
            )
        return cls(
            mission_id=mid,
            steps=tuple(steps),
            schema_version=schema_version,
            explanation=explanation,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert candidate plan to a deterministic dictionary."""
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "mission_id": str(self.mission_id),
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.explanation is not None:
            result["explanation"] = self.explanation
        return result

    def to_json(self) -> str:
        """Serialize candidate plan into canonical JSON."""
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidatePlanProposal:
        """Strictly deserialize and validate a CandidatePlanProposal mapping.

        Rejects unknown top-level fields, provider ID injections, authority injections,
        empty plans, oversized plans, and preserves proposed step order.
        """
        if not isinstance(data, Mapping):
            raise PlannerTypeError(
                f"Candidate plan proposal must be a mapping, got {type(data).__name__}"
            )

        allowed_keys = {"schema_version", "mission_id", "steps", "explanation"}
        for k in data.keys():
            if type(k) is not str:
                raise PlannerTypeError(f"Plan key must be a string, got {type(k).__name__}")
            if k not in allowed_keys:
                if k in FORBIDDEN_PROVIDER_ID_FIELDS:
                    msg = (
                        f"Attempt to inject raw provider identifier {k!r} into "
                        "top-level plan is forbidden"
                    )
                    raise ProviderIdentifierInjectionError(msg)
                if k in FORBIDDEN_AUTHORITY_AND_FACT_FIELDS:
                    msg = (
                        f"Attempt to inject authority/fact field {k!r} into "
                        "top-level plan is forbidden"
                    )
                    raise ModelAuthorityInjectionError(msg)
                raise UnknownFieldPolicyError(f"Unknown top-level field in candidate plan: {k!r}")

        if "mission_id" not in data:
            raise MissingRequiredFieldError("Missing required field 'mission_id' in candidate plan")
        if "steps" not in data:
            raise MissingRequiredFieldError("Missing required field 'steps' in candidate plan")

        raw_sv = data.get("schema_version", PLANNER_SCHEMA_VERSION)
        if type(raw_sv) is not str:
            raise PlannerTypeError(f"schema_version must be a string, got {type(raw_sv).__name__}")
        if raw_sv not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(f"Unsupported schema version: {raw_sv!r}")

        raw_mid = data["mission_id"]
        if isinstance(raw_mid, MissionId):
            mid = raw_mid
        elif isinstance(raw_mid, str):
            try:
                mid = MissionId(raw_mid)
            except (ValueError, TypeError) as exc:
                raise PlannerValueError(f"Invalid mission_id: {raw_mid!r}") from exc
        else:
            raise PlannerTypeError(
                f"mission_id must be a string or MissionId, got {type(raw_mid).__name__}"
            )

        raw_steps = data["steps"]
        if not isinstance(raw_steps, (list, tuple)):
            raise PlannerTypeError(f"steps must be a list or tuple, got {type(raw_steps).__name__}")

        if len(raw_steps) == 0:
            raise EmptyPlanError(
                "Candidate plan proposal must contain at least one step (empty plans fail closed)"
            )
        if len(raw_steps) > MAX_PLAN_STEPS:
            raise OversizedPlanError(
                f"Candidate plan proposal exceeds maximum of {MAX_PLAN_STEPS} steps "
                f"(actual: {len(raw_steps)})"
            )

        parsed_steps: list[CandidateActionProposal] = []
        for i, step_data in enumerate(raw_steps):
            if isinstance(step_data, CandidateActionProposal):
                parsed_steps.append(step_data)
            elif isinstance(step_data, Mapping):
                parsed_steps.append(CandidateActionProposal.from_dict(step_data))
            else:
                msg = (
                    f"Step {i} must be a Mapping or CandidateActionProposal, "
                    f"got {type(step_data).__name__}"
                )
                raise PlannerTypeError(msg)

        raw_explanation = data.get("explanation")
        if raw_explanation is not None and type(raw_explanation) is not str:
            raise PlannerTypeError(
                f"explanation must be a string, got {type(raw_explanation).__name__}"
            )

        return cls(
            schema_version=raw_sv,
            mission_id=mid,
            steps=tuple(parsed_steps),
            explanation=raw_explanation,
        )

    @classmethod
    def from_json(cls, json_str: str) -> CandidatePlanProposal:
        """Parse CandidatePlanProposal from JSON.

        Enforces raw size bounds and duplicate key detection.
        """
        _validate_raw_json_payload(json_str)
        try:
            data = json.loads(json_str, object_pairs_hook=_reject_duplicate_json_keys)
        except json.JSONDecodeError as exc:
            raise PlannerValueError(f"Malformed JSON: {exc}") from exc
        return cls.from_dict(data)


# ===========================================================================
# Bound Untrusted Model Plan Parsing
# ===========================================================================


def parse_candidate_plan_for_input(
    planner_input: PlannerInput,
    model_output_json: str,
) -> CandidatePlanProposal:
    """Parse untrusted model output JSON and strictly bind it to planner input.

    Fails closed if:
    - planner_input is not a PlannerInput instance;
    - model_output_json is not a string;
    - model_output_json exceeds MAX_PLANNER_JSON_BYTES;
    - JSON is malformed or contains duplicate keys;
    - candidate plan violates CandidatePlanProposal schema/bounds;
    - plan.mission_id != planner_input.mission_id (raises PlannerMissionBindingError).

    The model CANNOT redirect execution to another mission by returning a different UUID.
    Never mutates state, never confers authority.
    """
    if not isinstance(planner_input, PlannerInput):
        raise PlannerTypeError(
            f"planner_input must be a PlannerInput instance, got {type(planner_input).__name__}"
        )
    if type(model_output_json) is not str:
        raise PlannerTypeError(
            f"model_output_json must be a string, got {type(model_output_json).__name__}"
        )

    # CandidatePlanProposal.from_json validates MAX_PLANNER_JSON_BYTES,
    # duplicate keys, and all candidate plan structural invariants.
    plan = CandidatePlanProposal.from_json(model_output_json)

    if plan.mission_id != planner_input.mission_id:
        raise PlannerMissionBindingError(
            f"Candidate plan mission_id {str(plan.mission_id)!r} does not match "
            f"planner input mission_id {str(planner_input.mission_id)!r}"
        )

    return plan


# ===========================================================================
# Canonical Parameter Schemas & JSON Schema Generation
# ===========================================================================

# Minimal private parameter schema metadata mapping for supported action parameters.
# ActionPolicy defines supported parameter keys and string length bounds; this mapping
# supplies JSON Schema primitive types (string vs boolean) for those exact parameter keys.
_CANONICAL_PARAM_JSON_SCHEMAS: Mapping[str, dict[str, Any]] = types.MappingProxyType(
    {
        "summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PARAM_STRING_LENGTH,
        },
        "start_time": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PARAM_STRING_LENGTH,
        },
        "all_day": {
            "type": "boolean",
        },
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PARAM_STRING_LENGTH,
        },
        "due": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PARAM_STRING_LENGTH,
        },
    }
)

_ALL_SUPPORTED_PARAM_KEYS: frozenset[str] = frozenset.union(
    *(policy.supported_parameters for policy in ACTION_POLICIES.values())
)
assert set(_CANONICAL_PARAM_JSON_SCHEMAS.keys()) == _ALL_SUPPORTED_PARAM_KEYS, (
    "Parameter JSON schemas must exactly match union of canonical supported parameters"
)


def _build_action_proposal_json_schema(action_type: ActionType) -> dict[str, Any]:
    """Build an action-specific JSON Schema branch for one canonical ActionType.

    Derives strictly from:
    - canonical ActionType value (exact const);
    - ACTION_SYMBOLIC_TARGET_COMPATIBILITY[action_type] (compatible symbolic target enum);
    - ACTION_POLICIES[action_type] (supported parameter names);
    - canonical parameter presence and bound rules:
      * read actions: parameters absent or strict empty object only (maxProperties=0);
      * calendar.update: parameters required, minProperties=1, only supported fields;
      * task.create: parameters required, title required, due optional.
    """
    policy = ACTION_POLICIES[action_type]
    compatible_targets = sorted(
        [t.value for t in ACTION_SYMBOLIC_TARGET_COMPATIBILITY[action_type]]
    )

    action_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action_type", "target_ref"],
        "properties": {
            "action_type": {
                "type": "string",
                "const": action_type.value,
                "description": f"Exact canonical action type: {action_type.value}",
            },
            "target_ref": {
                "type": "string",
                "enum": compatible_targets,
                "description": f"Compatible symbolic target references for {action_type.value}",
            },
            "explanation": {
                "type": "string",
                "maxLength": MAX_EXPLANATION_STRING_LENGTH,
                "description": "Non-authoritative explanation/rationale",
            },
        },
    }

    if action_type in (
        ActionType.CALENDAR_READ,
        ActionType.TASK_READ,
        ActionType.WEATHER_READ,
    ):
        action_schema["properties"]["parameters"] = {
            "type": "object",
            "maxProperties": 0,
            "additionalProperties": False,
            "description": f"Parameters absent or strict empty object only for {action_type.value}",
        }
    elif action_type == ActionType.CALENDAR_UPDATE:
        action_schema["required"].append("parameters")
        param_props = {
            k: dict(_CANONICAL_PARAM_JSON_SCHEMAS[k]) for k in sorted(policy.supported_parameters)
        }
        action_schema["properties"]["parameters"] = {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": False,
            "properties": param_props,
            "description": "At least one supported update parameter is required",
        }
    elif action_type == ActionType.TASK_CREATE:
        action_schema["required"].append("parameters")
        param_props = {
            k: dict(_CANONICAL_PARAM_JSON_SCHEMAS[k]) for k in sorted(policy.supported_parameters)
        }
        action_schema["properties"]["parameters"] = {
            "type": "object",
            "required": ["title"],
            "additionalProperties": False,
            "properties": param_props,
            "description": "Task creation parameters requiring 'title'",
        }
    else:
        raise ValueError(f"Unhandled action type: {action_type}")

    return action_schema


def get_candidate_plan_json_schema() -> dict[str, Any]:
    """Generate action-specific JSON Schema for candidate plan structured output.

    Guarantees:
    - steps.items uses oneOf with one mutually exclusive branch per canonical ActionType.
    - Each action branch enforces exact ActionType const and compatible SymbolicTargetRef enums.
    - Calendar read, task read, and weather read disallow parameters
      (absent or strict empty object only).
    - Calendar update requires at least one supported update parameter (minProperties=1).
    - Task create requires title parameter (due optional, no other fields).
    - additionalProperties is False at every closed object boundary.
    - Explicit min/max bounds on arrays and strings.
    - Zero provider external identifier fields permitted.
    - ActionType, target compatibility, and parameter constraints derive from canonical sources.
    - Parameter schemas are bounded by _CANONICAL_PARAM_JSON_SCHEMAS, which is asserted to
      match the exact union of supported parameters from ACTION_POLICIES.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CandidatePlanProposal",
        "description": "StillDone candidate plan proposal. Proposal only.",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "mission_id", "steps"],
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": sorted(list(SUPPORTED_SCHEMA_VERSIONS)),
            },
            "mission_id": {
                "type": "string",
                "format": "uuid",
                "description": "Deterministic runtime-owned mission identifier",
            },
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_PLAN_STEPS,
                "description": "Ordered sequence of candidate action proposals",
                "items": {
                    "oneOf": [
                        _build_action_proposal_json_schema(action_type)
                        for action_type in sorted(ActionType, key=lambda a: a.value)
                    ],
                },
            },
            "explanation": {
                "type": "string",
                "maxLength": MAX_EXPLANATION_STRING_LENGTH,
                "description": "Overall non-authoritative plan rationale",
            },
        },
    }


__all__ = [
    "ACTION_SYMBOLIC_TARGET_COMPATIBILITY",
    "FORBIDDEN_AUTHORITY_AND_FACT_FIELDS",
    "FORBIDDEN_PROVIDER_ID_FIELDS",
    "MAX_EXPLANATION_STRING_LENGTH",
    "MAX_INTENT_STRING_LENGTH",
    "MAX_PLAN_STEPS",
    "MAX_PLANNER_JSON_BYTES",
    "MAX_SYMBOLIC_TARGET_LENGTH",
    "PLANNER_ACTION_VOCABULARY",
    "PLANNER_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "CandidateActionProposal",
    "CandidatePlanProposal",
    "DuplicateKeyError",
    "EmptyPlanError",
    "IncompatibleSymbolicTargetError",
    "InvalidIntentError",
    "MissingRequiredFieldError",
    "ModelAuthorityInjectionError",
    "OversizedIntentError",
    "OversizedJsonPayloadError",
    "OversizedPlanError",
    "OversizedStringError",
    "PlannerContractError",
    "PlannerInput",
    "PlannerMissionBindingError",
    "PlannerTypeError",
    "PlannerValueError",
    "ProviderIdentifierInjectionError",
    "SymbolicTargetRef",
    "UnknownActionTypeError",
    "UnknownFieldPolicyError",
    "UnknownSymbolicTargetError",
    "UnsupportedSchemaVersionError",
    "get_candidate_plan_json_schema",
    "parse_candidate_plan_for_input",
    "validate_candidate_action_parameters",
]
