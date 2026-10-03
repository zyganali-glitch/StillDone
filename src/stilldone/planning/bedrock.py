"""Production-capable Bedrock planner adapter for StillDone.

Phase P-07.02:
Implements the real Amazon Bedrock Runtime Converse API adapter with immutable
bounded planner settings, strict zero-retry botocore configuration, prompt trust
separation, and mandatory deterministic candidate plan validation.

Architectural invariants:
- Model output is untrusted and non-authoritative (proposal only).
- It cannot confer authority, create ApprovalGrant, create VERIFIED or READY.
- Nova Micro native Structured Outputs: NOT SUPPORTED.
- Bedrock structured-output docs explicitly list minLength/maxLength as unsupported.
- `pattern` is not in the documented supported subset.
- StillDone schema role: local deterministic validation + model prompt guidance.
- System prompt instructions are kept strictly separate from user mission intent.
- Model response must cross parse_candidate_plan_for_input before acceptance.
- Exactly one total provider attempt (total_max_attempts=1, zero retries).
- Zero fallback model, zero fallback region.
- Client instantiated lazily; never accepts credentials as constructor arguments.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from stilldone.planning.contracts import (
    MAX_PLANNER_JSON_BYTES,
    CandidatePlanProposal,
    OversizedJsonPayloadError,
    PlannerContractError,
    PlannerInput,
    PlannerTypeError,
    get_candidate_plan_json_schema,
    parse_candidate_plan_for_input,
)
from stilldone.serialization import canonical_json

# ===========================================================================
# Canonical Bedrock Planner Defaults & Bounds
# ===========================================================================

DEFAULT_BEDROCK_REGION: str = "us-east-1"
DEFAULT_BEDROCK_MODEL_ID: str = "amazon.nova-micro-v1:0"
DEFAULT_CONNECT_TIMEOUT_SECONDS: float = 5.0
DEFAULT_READ_TIMEOUT_SECONDS: float = 30.0
DEFAULT_TOTAL_MAX_ATTEMPTS: int = 1
DEFAULT_RETRY_MODE: str = "standard"
DEFAULT_MAX_OUTPUT_TOKENS: int = 2048
DEFAULT_TEMPERATURE: float = 0.00001

# The sole accepted terminal stop reason from Bedrock Converse for successful completion
ACCEPTED_STOP_REASON: str = "end_turn"

# Known canonical Bedrock Converse stop reasons safe for bounded diagnostic classification
KNOWN_BEDROCK_STOP_REASONS: frozenset[str] = frozenset(
    {
        "end_turn",
        "stop_sequence",
        "max_tokens",
        "content_filtered",
        "tool_use",
        "guardrail_intervened",
    }
)

# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class BedrockPlannerError(Exception):
    """Base exception for all Bedrock planner adapter errors."""


class BedrockPlannerSettingsError(BedrockPlannerError, ValueError):
    """Raised when planner settings violate bounded constraints or invariants."""


class BedrockTransportError(BedrockPlannerError):
    """Raised when AWS Bedrock transport fails. Sanitizes raw error details.

    Suppresses raw underlying exceptions to prevent credential, account ID,
    request ID, or untrusted provider strings from leaking into tracebacks.
    """

    def __init__(
        self,
        message: str = "Bedrock converse transport failed",
        *,
        classification: str = "BEDROCK_TRANSPORT_FAILURE",
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.__cause__ = None
        self.__context__ = None


class BedrockResponseEnvelopeError(BedrockPlannerError, ValueError):
    """Raised when Bedrock Converse response envelope is malformed or missing required structure."""


class BedrockEmptyResponseError(BedrockResponseEnvelopeError):
    """Raised when model returns missing or blank text content."""


class BedrockStopReasonError(BedrockPlannerError, ValueError):
    """Raised when Bedrock Converse stopReason is unacceptable (e.g. max_tokens)."""


class BedrockUsageMetadataError(BedrockPlannerError, ValueError):
    """Raised when token usage metadata returned by Bedrock is malformed or negative."""


class BedrockPlanRejectionError(BedrockPlannerError, PlannerContractError):
    """Raised when the candidate plan proposal is rejected by deterministic validation.

    Preserves the underlying deterministic P-07.01 rejection class in `rejection_class`.
    Never stores the original untrusted exception instance or leaks untrusted model
    output text, action types, targets, or mission intent into exception messages,
    causes, or tracebacks.
    """

    def __init__(
        self,
        message: str = "Candidate plan proposal rejected by deterministic validation",
        *,
        rejection_class: type[PlannerContractError] | None = None,
    ) -> None:
        super().__init__(message)
        self.rejection_class: type[PlannerContractError] | None = rejection_class
        self.__cause__ = None
        self.__context__ = None


# ===========================================================================
# Settings & Metadata Models
# ===========================================================================


@dataclass(frozen=True)
class BedrockPlannerSettings:
    """Immutable bounded planner settings for Amazon Bedrock.

    Enforces strict security, cost, and architecture boundaries:
    - Canonical model: amazon.nova-micro-v1:0 (strictly enforced; no fallback)
    - Canonical region: us-east-1 (strictly enforced; no fallback)
    - Bounded timeouts: connect <= 5s, read <= 30s
    - Exactly 1 total provider attempt (zero automatic retries)
    - Retry mode: standard
    - Max tokens: 0 < max_tokens <= 2048
    - Temperature: 0.0 <= temp <= 0.00001 (canonical: 0.00001; may only become stricter)
    """

    region_name: str = DEFAULT_BEDROCK_REGION
    model_id: str = DEFAULT_BEDROCK_MODEL_ID
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    total_max_attempts: int = DEFAULT_TOTAL_MAX_ATTEMPTS
    retry_mode: str = DEFAULT_RETRY_MODE
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    temperature: float = DEFAULT_TEMPERATURE

    def __post_init__(self) -> None:
        if type(self.region_name) is not str or self.region_name != DEFAULT_BEDROCK_REGION:
            raise BedrockPlannerSettingsError(
                f"region_name must be exactly {DEFAULT_BEDROCK_REGION!r}; "
                f"got {self.region_name!r}. No fallback region allowed."
            )
        if type(self.model_id) is not str or self.model_id != DEFAULT_BEDROCK_MODEL_ID:
            raise BedrockPlannerSettingsError(
                f"model_id must be exactly {DEFAULT_BEDROCK_MODEL_ID!r}; "
                f"got {self.model_id!r}. No fallback model allowed."
            )

        if type(self.connect_timeout) not in (float, int) or type(self.connect_timeout) is bool:
            raise BedrockPlannerSettingsError("connect_timeout must be a float or int, not bool")
        if math.isnan(self.connect_timeout) or math.isinf(self.connect_timeout):
            raise BedrockPlannerSettingsError("connect_timeout cannot be NaN or infinity")
        if self.connect_timeout <= 0:
            raise BedrockPlannerSettingsError(
                f"connect_timeout must be positive, got {self.connect_timeout}"
            )
        if self.connect_timeout > DEFAULT_CONNECT_TIMEOUT_SECONDS:
            msg = (
                f"connect_timeout cannot exceed canonical maximum of "
                f"{DEFAULT_CONNECT_TIMEOUT_SECONDS}s; got {self.connect_timeout}s"
            )
            raise BedrockPlannerSettingsError(msg)

        if type(self.read_timeout) not in (float, int) or type(self.read_timeout) is bool:
            raise BedrockPlannerSettingsError("read_timeout must be a float or int, not bool")
        if math.isnan(self.read_timeout) or math.isinf(self.read_timeout):
            raise BedrockPlannerSettingsError("read_timeout cannot be NaN or infinity")
        if self.read_timeout <= 0:
            raise BedrockPlannerSettingsError(
                f"read_timeout must be positive, got {self.read_timeout}"
            )
        if self.read_timeout > DEFAULT_READ_TIMEOUT_SECONDS:
            msg = (
                f"read_timeout cannot exceed canonical maximum of "
                f"{DEFAULT_READ_TIMEOUT_SECONDS}s; got {self.read_timeout}s"
            )
            raise BedrockPlannerSettingsError(msg)

        if type(self.total_max_attempts) is not int or type(self.total_max_attempts) is bool:
            raise BedrockPlannerSettingsError("total_max_attempts must be an integer, not bool")
        if self.total_max_attempts != DEFAULT_TOTAL_MAX_ATTEMPTS:
            raise BedrockPlannerSettingsError(
                f"total_max_attempts must be exactly {DEFAULT_TOTAL_MAX_ATTEMPTS}; "
                f"got {self.total_max_attempts}. Automatic retries are strictly forbidden."
            )

        if type(self.retry_mode) is not str or self.retry_mode != DEFAULT_RETRY_MODE:
            raise BedrockPlannerSettingsError(
                f"retry_mode must be {DEFAULT_RETRY_MODE!r}; got {self.retry_mode!r}"
            )

        if type(self.max_tokens) is not int or type(self.max_tokens) is bool:
            raise BedrockPlannerSettingsError("max_tokens must be an integer, not bool")
        if self.max_tokens <= 0:
            raise BedrockPlannerSettingsError(f"max_tokens must be positive, got {self.max_tokens}")
        if self.max_tokens > DEFAULT_MAX_OUTPUT_TOKENS:
            raise BedrockPlannerSettingsError(
                f"max_tokens cannot exceed canonical maximum of {DEFAULT_MAX_OUTPUT_TOKENS}; "
                f"got {self.max_tokens}"
            )

        if type(self.temperature) not in (float, int) or type(self.temperature) is bool:
            raise BedrockPlannerSettingsError("temperature must be a float or int, not bool")
        if math.isnan(self.temperature) or math.isinf(self.temperature):
            raise BedrockPlannerSettingsError("temperature cannot be NaN or infinity")
        if not (0.0 <= self.temperature <= DEFAULT_TEMPERATURE):
            raise BedrockPlannerSettingsError(
                f"temperature must be between 0.0 and {DEFAULT_TEMPERATURE}; got {self.temperature}"
            )


@dataclass(frozen=True)
class BedrockTokenUsage:
    """Non-negative token usage metadata returned by Amazon Bedrock."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class BedrockPlannerResult:
    """Immutable result object from a single Bedrock planner invocation.

    Runtime metadata only: confers zero authority and does NOT create
    an EvidenceRecord or mission state promotion.
    """

    plan: CandidatePlanProposal
    stop_reason: str
    usage: BedrockTokenUsage | None = None
    model_id: str = DEFAULT_BEDROCK_MODEL_ID
    region_name: str = DEFAULT_BEDROCK_REGION


# ===========================================================================
# Typed Client Port & Boto3 Factory
# ===========================================================================


@runtime_checkable
class BedrockConverseClient(Protocol):
    """Minimal typed client protocol for Bedrock Runtime Converse API."""

    def converse(
        self,
        *,
        modelId: str,
        messages: Sequence[Mapping[str, Any]],
        system: Sequence[Mapping[str, Any]] | None = None,
        inferenceConfig: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        """Invoke the Converse API on Amazon Bedrock."""
        ...


def create_bedrock_runtime_client(
    settings: BedrockPlannerSettings | None = None,
) -> BedrockConverseClient:
    """Create a production boto3 bedrock-runtime client with exact canonical settings.

    Uses standard AWS credential provider chain. Never accepts credentials as arguments.
    Configures botocore with explicit connect_timeout, read_timeout, and exactly 1
    total attempt (total_max_attempts=1, zero retries).
    """
    import boto3  # type: ignore[import-untyped]
    import botocore.config  # type: ignore[import-untyped]

    cfg = settings or BedrockPlannerSettings()
    botocore_config = botocore.config.Config(
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        retries={
            "total_max_attempts": cfg.total_max_attempts,
            "mode": cfg.retry_mode,
        },
    )
    return boto3.client(  # type: ignore[no-any-return]
        "bedrock-runtime",
        region_name=cfg.region_name,
        config=botocore_config,
    )


# ===========================================================================
# Prompt Construction & Trust Separation
# ===========================================================================


def build_bedrock_planner_system_prompt() -> str:
    """Build StillDone-owned deterministic planner system instructions.

    Enforces all planner boundary invariants:
    - proposal only, zero authority;
    - exactly five canonical action types;
    - symbolic targets only (no raw provider external IDs);
    - zero approval or verification assertions;
    - return exactly one JSON object with no markdown fences or surrounding prose;
    - exact mission_id echo;
    - candidate plan JSON schema included as prompt guidance only.
    """
    schema_guidance = canonical_json(get_candidate_plan_json_schema())
    return (
        "You are the StillDone Mission Planning Assistant.\n"
        "Your task is to analyze user mission intent and produce a candidate plan proposal.\n\n"
        "STRICT INVARIANTS AND RULES:\n"
        "1. PROPOSAL ONLY: Your output is strictly a proposal. You possess no fact authority, "
        "no execution permissions, and cannot verify outcomes.\n"
        "2. CANONICAL ACTION VOCABULARY: You may ONLY propose actions from the following exact "
        "five canonical action types:\n"
        "   - calendar.read\n"
        "   - calendar.update\n"
        "   - task.read\n"
        "   - task.create\n"
        "   - weather.read\n"
        "   Any other action type is strictly forbidden and will be rejected.\n"
        "3. SYMBOLIC TARGETS ONLY: Use ONLY predefined symbolic target references "
        "(e.g., leave_for_school, calendar_event, task_list, family_tasks, weather_location). "
        "Do NOT invent or fabricate raw provider IDs.\n"
        "4. NO RAW PROVIDER IDENTIFIERS: Never output fields such as calendar_id, event_id, "
        "task_list_id, task_id, resource_id, parent_id, account_id, or oauth_token.\n"
        "5. NO APPROVAL OR AUTHORITY ASSERTIONS: Never output fields such as approval_grant, "
        "approval_id, authority_class, authorized, or is_authorized.\n"
        "6. NO VERIFIED OR READY ASSERTIONS: Never output fields such as verified, is_verified, "
        "ready, is_ready, step_evidence_state, or status.\n"
        "7. EXACT MISSION ID: You MUST echo the exact mission_id provided in the user input.\n"
        "8. OUTPUT FORMAT: Return EXACTLY ONE single valid JSON object conforming to the "
        "schema below. Do NOT include markdown formatting (no ``` or ```json code fences). "
        "Do NOT include any explanatory prose or comments before or after the JSON.\n\n"
        "CANDIDATE PLAN SCHEMA GUIDANCE (PROMPT GUIDANCE ONLY):\n"
        f"{schema_guidance}"
    )


def format_user_message(planner_input: PlannerInput) -> str:
    """Format user message containing canonical PlannerInput representation.

    Intent remains user content and is NEVER concatenated into system instructions.
    """
    if not isinstance(planner_input, PlannerInput):
        raise PlannerTypeError(
            f"planner_input must be a PlannerInput instance, got {type(planner_input).__name__}"
        )
    return canonical_json(planner_input.to_dict())


# ===========================================================================
# Bedrock Planner Adapter
# ===========================================================================


class BedrockPlannerAdapter:
    """Bounded, non-authoritative Bedrock planner adapter for StillDone.

    Invariants:
    - Non-authoritative: output is a proposal only; cannot establish authority,
      approval, or verification.
    - Nova Micro native Structured Outputs: NOT SUPPORTED.
    - Exactly one total provider attempt (zero automatic retries).
    - Client instantiated lazily via standard AWS credential chain or injected via protocol.
    - All model plans must cross parse_candidate_plan_for_input before acceptance.
    """

    def __init__(
        self,
        settings: BedrockPlannerSettings | None = None,
        *,
        client: BedrockConverseClient | None = None,
    ) -> None:
        if settings is not None and not isinstance(settings, BedrockPlannerSettings):
            raise BedrockPlannerSettingsError(
                f"settings must be a BedrockPlannerSettings instance, got {type(settings).__name__}"
            )
        self._settings = settings or BedrockPlannerSettings()
        self._client = client
        self._system_prompt = build_bedrock_planner_system_prompt()

    @property
    def settings(self) -> BedrockPlannerSettings:
        """The immutable planner settings."""
        return self._settings

    @property
    def system_prompt(self) -> str:
        """The deterministic StillDone system prompt."""
        return self._system_prompt

    def _get_client(self) -> BedrockConverseClient:
        """Obtain client, instantiating lazily if not injected."""
        if self._client is None:
            self._client = create_bedrock_runtime_client(self._settings)
        return self._client

    def plan(self, planner_input: PlannerInput) -> BedrockPlannerResult:
        """Request a candidate plan proposal for the given mission input.

        Executes at most one Bedrock Converse call (zero retries).
        Fails closed on any schema, envelope, stop reason, or plan validation violation.
        """
        if not isinstance(planner_input, PlannerInput):
            raise PlannerTypeError(
                f"planner_input must be a PlannerInput instance, got {type(planner_input).__name__}"
            )

        client = self._get_client()

        # Build exact Converse request shape
        messages = [
            {
                "role": "user",
                "content": [{"text": format_user_message(planner_input)}],
            }
        ]
        system = [{"text": self._system_prompt}]
        inference_config = {
            "maxTokens": self._settings.max_tokens,
            "temperature": self._settings.temperature,
        }

        # Exactly one call, zero retries
        transport_err: BedrockTransportError | None = None
        try:
            response = client.converse(
                modelId=self._settings.model_id,
                system=system,
                messages=messages,
                inferenceConfig=inference_config,
            )
        except Exception as exc:
            if isinstance(exc, BedrockPlannerError):
                raise
            transport_err = BedrockTransportError()

        if transport_err is not None:
            transport_err.__cause__ = None
            transport_err.__context__ = None
            raise transport_err from None

        # Treat response as untrusted provider data
        return self._process_converse_response(planner_input, response)

    def _process_converse_response(
        self,
        planner_input: PlannerInput,
        response: Any,
    ) -> BedrockPlannerResult:
        """Validate response envelope, enforce bounds, and execute deterministic parsing."""
        if not isinstance(response, Mapping):
            raise BedrockResponseEnvelopeError(
                f"Converse response must be a Mapping, got {type(response).__name__}"
            )

        if "output" not in response:
            raise BedrockResponseEnvelopeError("Converse response missing required 'output' field")
        output = response["output"]
        if not isinstance(output, Mapping):
            raise BedrockResponseEnvelopeError(
                f"Converse response 'output' must be a Mapping, got {type(output).__name__}"
            )

        if "message" not in output:
            raise BedrockResponseEnvelopeError(
                "Converse response 'output' missing required 'message' field"
            )
        message = output["message"]
        if not isinstance(message, Mapping):
            raise BedrockResponseEnvelopeError(
                f"Converse response 'message' must be a Mapping, got {type(message).__name__}"
            )

        if "role" not in message:
            raise BedrockResponseEnvelopeError(
                "Converse response 'message' missing required 'role' field"
            )
        role = message["role"]
        if not isinstance(role, str):
            raise BedrockResponseEnvelopeError(
                f"Converse message 'role' must be a string, got {type(role).__name__}"
            )
        if role != "assistant":
            raise BedrockResponseEnvelopeError("Converse message 'role' must be 'assistant'")

        if "content" not in message:
            raise BedrockResponseEnvelopeError(
                "Converse response 'message' missing required 'content' field"
            )
        content = message["content"]
        if not isinstance(content, (list, tuple)):
            raise BedrockResponseEnvelopeError(
                f"Converse message 'content' must be a list or tuple, got {type(content).__name__}"
            )

        if len(content) == 0:
            raise BedrockEmptyResponseError("Converse message 'content' sequence is empty")

        # Inspect complete content sequence; reject non-text or unsupported blocks
        text_parts: list[str] = []
        for idx, block in enumerate(content):
            if not isinstance(block, Mapping):
                raise BedrockResponseEnvelopeError(
                    f"Converse content block at index {idx} must be a Mapping, "
                    f"got {type(block).__name__}"
                )
            if "text" not in block:
                raise BedrockResponseEnvelopeError(
                    f"Converse content block at index {idx} missing required 'text' field"
                )
            block_text = block["text"]
            if not isinstance(block_text, str):
                raise BedrockResponseEnvelopeError(
                    f"Converse content 'text' at index {idx} must be a string, "
                    f"got {type(block_text).__name__}"
                )
            text_parts.append(block_text)

        combined_text = "".join(text_parts)
        if not combined_text.strip():
            raise BedrockEmptyResponseError(
                "Converse response contains empty or whitespace-only text"
            )

        if "stopReason" not in response:
            raise BedrockResponseEnvelopeError(
                "Converse response missing required 'stopReason' field"
            )
        stop_reason = response["stopReason"]
        if not isinstance(stop_reason, str):
            raise BedrockResponseEnvelopeError(
                f"Converse response 'stopReason' must be a string, got {type(stop_reason).__name__}"
            )

        if stop_reason != ACCEPTED_STOP_REASON:
            clean_reason = (
                stop_reason if stop_reason in KNOWN_BEDROCK_STOP_REASONS else "unrecognized"
            )
            msg = (
                f"Unacceptable Bedrock stop reason: {clean_reason!r}; "
                f"expected {ACCEPTED_STOP_REASON!r}"
            )
            raise BedrockStopReasonError(msg)

        # Usage metadata validation
        usage: BedrockTokenUsage | None = None
        if "usage" in response:
            raw_usage = response["usage"]
            if not isinstance(raw_usage, Mapping):
                raise BedrockUsageMetadataError(
                    f"Usage metadata must be a Mapping, got {type(raw_usage).__name__}"
                )
            in_tokens = raw_usage.get("inputTokens")
            out_tokens = raw_usage.get("outputTokens")
            tot_tokens = raw_usage.get("totalTokens")

            for field_name, val in (
                ("inputTokens", in_tokens),
                ("outputTokens", out_tokens),
                ("totalTokens", tot_tokens),
            ):
                if val is not None:
                    if type(val) is not int or type(val) is bool:
                        msg = (
                            f"Usage field '{field_name}' must be an integer, not bool, "
                            f"got {type(val).__name__}"
                        )
                        raise BedrockUsageMetadataError(msg)
                    if val < 0:
                        raise BedrockUsageMetadataError(
                            f"Usage field '{field_name}' cannot be negative"
                        )

            usage = BedrockTokenUsage(
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                total_tokens=tot_tokens,
            )

        # Enforce MAX_PLANNER_JSON_BYTES ceiling on combined UTF-8 text
        raw_bytes_len = len(combined_text.encode("utf-8"))
        if raw_bytes_len > MAX_PLANNER_JSON_BYTES:
            msg = (
                "Candidate plan proposal rejected by deterministic validation: "
                "OversizedJsonPayloadError"
            )
            err = BedrockPlanRejectionError(msg, rejection_class=OversizedJsonPayloadError)
            err.__cause__ = None
            err.__context__ = None
            raise err from None

        # Invoke mandatory deterministic boundary
        parsed_plan: CandidatePlanProposal | None = None
        rejection_err: BedrockPlanRejectionError | None = None
        try:
            parsed_plan = parse_candidate_plan_for_input(planner_input, combined_text)
        except PlannerContractError as exc:
            cls = type(exc)
            msg = f"Candidate plan proposal rejected by deterministic validation: {cls.__name__}"
            rejection_err = BedrockPlanRejectionError(msg, rejection_class=cls)

        if rejection_err is not None:
            rejection_err.__cause__ = None
            rejection_err.__context__ = None
            raise rejection_err from None

        assert parsed_plan is not None
        return BedrockPlannerResult(
            plan=parsed_plan,
            stop_reason=stop_reason,
            usage=usage,
            model_id=self._settings.model_id,
            region_name=self._settings.region_name,
        )
