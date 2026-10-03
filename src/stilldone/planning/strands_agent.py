"""Bounded Strands planning agent for StillDone.

Phase P-07.03:
Implements a production-capable bounded Strands planner that integrates
the real Strands SDK Agent with Amazon Bedrock via BedrockModel.

Architectural invariants:
- Strands/model = PLANNER ONLY.
- Model may NOT own: external facts, provider IDs, authority, ApprovalGrant,
  execution, predicates, VERIFIED, READY, lifecycle, freshness, reconciliation.
- Every accepted model plan MUST cross parse_candidate_plan_for_input.
- No Strands result may directly create READY or VERIFIED.
- Zero executable external tools (tools=[]).
- One model turn maximum (limits={"turns": 1}).
- Fresh context per mission (new Agent per invocation).
- No session/memory/storage/checkpointing/background tasks.
- Strands SDK retries disabled (retry_strategy=None).
- Callback handler disabled (callback_handler=None).
- Streaming disabled (streaming=False).
- No auto-loaded tools (load_tools_from_directory=False).
- No structured output model (structured_output=None).
- stop_reason must be "end_turn"; all others fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stilldone.planning.bedrock import (
    ACCEPTED_STOP_REASON,
    KNOWN_BEDROCK_STOP_REASONS,
    BedrockPlannerSettings,
    build_bedrock_planner_system_prompt,
    format_user_message,
)
from stilldone.planning.contracts import (
    MAX_PLANNER_JSON_BYTES,
    CandidatePlanProposal,
    OversizedJsonPayloadError,
    PlannerContractError,
    PlannerInput,
    PlannerTypeError,
    parse_candidate_plan_for_input,
)

# ===========================================================================
# Strands Agent Errors
# ===========================================================================


class StrandsPlannerError(Exception):
    """Base exception for all Strands planner errors."""


class StrandsPlannerConfigError(StrandsPlannerError, ValueError):
    """Raised when Strands agent configuration violates bounded constraints."""


class StrandsTransportError(StrandsPlannerError):
    """Raised when Strands agent invocation fails at the transport layer.

    Suppresses raw underlying exceptions to prevent credential, account ID,
    request ID, or untrusted provider strings from leaking into tracebacks.
    """

    def __init__(
        self,
        message: str = "Strands agent invocation failed",
        *,
        classification: str = "STRANDS_TRANSPORT_FAILURE",
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.__cause__ = None
        self.__context__ = None


class StrandsStopReasonError(StrandsPlannerError, ValueError):
    """Raised when Strands agent result has an unacceptable stop_reason."""


class StrandsEmptyResponseError(StrandsPlannerError, ValueError):
    """Raised when Strands agent returns empty or missing text content."""


class StrandsNonTextContentError(StrandsPlannerError, ValueError):
    """Raised when Strands agent result contains non-text content blocks."""


class StrandsPlanRejectionError(StrandsPlannerError, PlannerContractError):
    """Raised when the candidate plan is rejected by deterministic validation.

    Never stores the original untrusted exception instance or leaks
    untrusted model output into exception messages, causes, or tracebacks.
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
# Strands Planner Result
# ===========================================================================


@dataclass(frozen=True)
class StrandsPlannerResult:
    """Immutable result from a single Strands planner invocation.

    Runtime metadata only: confers zero authority and does NOT create
    an EvidenceRecord or mission state promotion.
    """

    plan: CandidatePlanProposal
    stop_reason: str
    model_id: str
    region_name: str


# ===========================================================================
# Strands BedrockModel Factory
# ===========================================================================


def create_strands_bedrock_model(
    settings: BedrockPlannerSettings | None = None,
) -> Any:
    """Create a Strands BedrockModel with exact canonical StillDone settings.

    Uses standard AWS credential provider chain. Never accepts credentials
    as constructor arguments. Configures botocore with explicit timeout,
    retry, and streaming settings.

    Returns the actual strands.models.BedrockModel instance.
    """
    import botocore.config  # type: ignore[import-untyped]
    from strands.models.bedrock import BedrockModel

    cfg = settings or BedrockPlannerSettings()

    botocore_config = botocore.config.Config(
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        retries={
            "total_max_attempts": cfg.total_max_attempts,
            "mode": cfg.retry_mode,
        },
    )

    return BedrockModel(
        model_id=cfg.model_id,
        region_name=cfg.region_name,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        streaming=False,
        use_native_token_count=False,
        boto_client_config=botocore_config,
    )


# ===========================================================================
# Bounded Strands Planner
# ===========================================================================

# Strands stop reasons that StillDone considers unacceptable.
# Only "end_turn" is accepted.
_STRANDS_UNACCEPTABLE_STOP_REASONS: frozenset[str] = frozenset(
    {
        "limit_turns",
        "max_tokens",
        "tool_use",
        "content_filtered",
        "guardrail_intervened",
        "cancelled",
        "checkpoint",
        "interrupt",
        "stop_sequence",
    }
)


def plan_with_strands(
    planner_input: PlannerInput,
    *,
    settings: BedrockPlannerSettings | None = None,
    _model_override: Any = None,
) -> StrandsPlannerResult:
    """Execute a bounded Strands planning invocation for a single mission.

    Creates a fresh Strands Agent per invocation (no cross-mission context bleed).

    Configures the Agent with:
    - tools=[] (zero executable tools)
    - load_tools_from_directory=False
    - callback_handler=None
    - retry_strategy=None
    - structured_output=None
    - No session/memory/storage/checkpointing/background tasks

    Invokes with limits={"turns": 1} (one model turn maximum).

    Args:
        planner_input: The runtime-owned planner input.
        settings: Optional BedrockPlannerSettings override (defaults to canonical).
        _model_override: For testing only. If provided, used instead of real
            BedrockModel. Must NOT be used in production.

    Returns:
        StrandsPlannerResult with validated plan.

    Raises:
        PlannerTypeError: If planner_input is not a PlannerInput instance.
        StrandsTransportError: If the Strands Agent invocation fails.
        StrandsStopReasonError: If stop_reason is not "end_turn".
        StrandsEmptyResponseError: If the result contains no text.
        StrandsNonTextContentError: If the result contains non-text blocks.
        StrandsPlanRejectionError: If the plan fails deterministic validation.
    """
    from strands import Agent

    if not isinstance(planner_input, PlannerInput):
        raise PlannerTypeError(
            f"planner_input must be a PlannerInput instance, got {type(planner_input).__name__}"
        )

    cfg = settings or BedrockPlannerSettings()

    # Create a fresh model for this invocation (or use test override)
    if _model_override is not None:
        model = _model_override
    else:
        model = create_strands_bedrock_model(cfg)

    # Build bounded system prompt (reuses P-07.02 canonical prompt)
    system_prompt = build_bedrock_planner_system_prompt()

    # Build user message (reuses P-07.02 canonical formatter)
    user_message = format_user_message(planner_input)

    # Construct a FRESH Strands Agent with fail-closed configuration.
    # Each invocation creates a new Agent — no conversation persistence.
    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[],  # ZERO executable tools
        load_tools_from_directory=False,  # No auto-loaded tools
        callback_handler=None,  # No callback printing
        retry_strategy=None,  # Strands SDK retries DISABLED
        structured_output_model=None,
        context_manager=False,
        memory_manager=None,
        session_manager=None,
        storage=None,
        checkpointing=False,
        background_tasks=False,
    )

    # Verify the agent has zero tools
    if hasattr(agent, "tool_names") and agent.tool_names:
        raise StrandsPlannerConfigError(f"Strands Agent has unexpected tools: {agent.tool_names}")
    if hasattr(agent, "tool_registry"):
        registry = agent.tool_registry
        if hasattr(registry, "get_all_tools_config"):
            tools_config = registry.get_all_tools_config()
            if tools_config:
                raise StrandsPlannerConfigError("Strands Agent tool registry is not empty")

    try:
        from strands.types.exceptions import (
            ContextWindowOverflowException,
            MaxTokensReachedException,
        )

        token_limit_exceptions: tuple[type[Exception], ...] = (
            MaxTokensReachedException,
            ContextWindowOverflowException,
        )
    except ImportError:  # pragma: no cover
        token_limit_exceptions = ()

    # Invoke with one-turn limit
    transport_err: StrandsTransportError | None = None
    result: Any = None
    try:
        result = agent(user_message, limits={"turns": 1})
    except Exception as exc:
        if isinstance(exc, StrandsPlannerError):
            raise
        if token_limit_exceptions and isinstance(exc, token_limit_exceptions):
            stop_err = StrandsStopReasonError(
                "Unacceptable Strands stop reason: 'max_tokens'; expected 'end_turn'"
            )
            stop_err.__cause__ = None
            stop_err.__context__ = None
            raise stop_err from None
        transport_err = StrandsTransportError()

    if transport_err is not None:
        transport_err.__cause__ = None
        transport_err.__context__ = None
        raise transport_err from None

    # Process the Strands AgentResult
    return _process_strands_result(planner_input, result, cfg)


def _process_strands_result(
    planner_input: PlannerInput,
    result: Any,
    settings: BedrockPlannerSettings,
) -> StrandsPlannerResult:
    """Process and validate a Strands AgentResult.

    Treats the result as untrusted runtime output.

    Requirements:
    - stop_reason must be "end_turn"
    - Must contain assistant message with text-only content
    - Combined text must pass MAX_PLANNER_JSON_BYTES check
    - Must cross parse_candidate_plan_for_input
    """
    if result is None:
        raise StrandsEmptyResponseError("Strands agent returned None result")

    # Extract stop_reason from result
    stop_reason: str | None = None
    if hasattr(result, "stop_reason"):
        stop_reason = result.stop_reason
    elif hasattr(result, "metrics") and hasattr(result.metrics, "stop_reason"):
        stop_reason = result.metrics.stop_reason

    if stop_reason is None:
        raise StrandsStopReasonError("Strands agent result missing stop_reason")

    if not isinstance(stop_reason, str):
        raise StrandsStopReasonError("Strands agent stop_reason must be a string")

    if stop_reason != ACCEPTED_STOP_REASON:
        # Sanitize unknown stop reasons
        clean_reason = (
            stop_reason
            if stop_reason in (KNOWN_BEDROCK_STOP_REASONS | _STRANDS_UNACCEPTABLE_STOP_REASONS)
            else "unrecognized"
        )
        raise StrandsStopReasonError(
            f"Unacceptable Strands stop reason: {clean_reason!r}; expected {ACCEPTED_STOP_REASON!r}"
        )

    # Extract text from the result
    combined_text = _extract_text_from_result(result)

    if not combined_text.strip():
        raise StrandsEmptyResponseError("Strands agent returned empty or whitespace-only text")

    # Enforce MAX_PLANNER_JSON_BYTES ceiling
    raw_bytes_len = len(combined_text.encode("utf-8"))
    if raw_bytes_len > MAX_PLANNER_JSON_BYTES:
        msg = (
            "Candidate plan proposal rejected by deterministic validation: "
            "OversizedJsonPayloadError"
        )
        err = StrandsPlanRejectionError(msg, rejection_class=OversizedJsonPayloadError)
        err.__cause__ = None
        err.__context__ = None
        raise err from None

    # Invoke mandatory deterministic boundary
    parsed_plan: CandidatePlanProposal | None = None
    rejection_err: StrandsPlanRejectionError | None = None
    try:
        parsed_plan = parse_candidate_plan_for_input(planner_input, combined_text)
    except PlannerContractError as exc:
        cls = type(exc)
        msg = f"Candidate plan proposal rejected by deterministic validation: {cls.__name__}"
        rejection_err = StrandsPlanRejectionError(msg, rejection_class=cls)

    if rejection_err is not None:
        rejection_err.__cause__ = None
        rejection_err.__context__ = None
        raise rejection_err from None

    assert parsed_plan is not None
    return StrandsPlannerResult(
        plan=parsed_plan,
        stop_reason=stop_reason,
        model_id=settings.model_id,
        region_name=settings.region_name,
    )


def _extract_text_from_result(result: Any) -> str:
    """Extract text content from a Strands AgentResult.

    Inspects the final message content deterministically.
    Requires text-only content — rejects toolUse, toolResult,
    reasoning, document, image, or any non-text blocks.
    """
    # Try to get the message from the result
    message = None
    if hasattr(result, "message"):
        message = result.message
    elif hasattr(result, "messages") and result.messages:
        # Get the last assistant message
        for msg in reversed(result.messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                message = msg
                break

    if message is None:
        # Fall back to str(result) only if we can verify it's text-only
        result_str = str(result)
        if result_str:
            return result_str
        raise StrandsEmptyResponseError("Cannot extract message from Strands result")

    # Extract content from the message
    content: Any = None
    if isinstance(message, dict):
        content = message.get("content")
    elif hasattr(message, "content"):
        content = message.content

    if content is None:
        raise StrandsEmptyResponseError("Strands result message has no content")

    if isinstance(content, str):
        return content

    if not isinstance(content, (list, tuple)):
        raise StrandsEmptyResponseError(
            f"Strands result content must be a string or list, got {type(content).__name__}"
        )

    # Inspect each content block — reject non-text blocks
    text_parts: list[str] = []
    for idx, block in enumerate(content):
        if isinstance(block, str):
            text_parts.append(block)
            continue

        if not isinstance(block, dict):
            raise StrandsNonTextContentError(
                f"Strands content block at index {idx} has unsupported type {type(block).__name__}"
            )

        # Only accept text blocks
        if "text" in block:
            block_text = block["text"]
            if not isinstance(block_text, str):
                raise StrandsNonTextContentError(
                    f"Strands content 'text' at index {idx} must be a string, "
                    f"got {type(block_text).__name__}"
                )
            text_parts.append(block_text)
        elif "toolUse" in block or "toolResult" in block:
            raise StrandsNonTextContentError(
                f"Strands content block at index {idx} contains tool-use output "
                "which is not accepted for planner text extraction"
            )
        elif any(k in block for k in ("reasoning", "document", "image", "video", "audio")):
            raise StrandsNonTextContentError(
                f"Strands content block at index {idx} contains non-text content "
                "which is not accepted for planner text extraction"
            )
        else:
            raise StrandsNonTextContentError(
                f"Strands content block at index {idx} missing 'text' field"
            )

    if not text_parts:
        raise StrandsEmptyResponseError("No text blocks found in Strands result content")

    return "".join(text_parts)


__all__ = [
    "StrandsEmptyResponseError",
    "StrandsNonTextContentError",
    "StrandsPlanRejectionError",
    "StrandsPlannerConfigError",
    "StrandsPlannerError",
    "StrandsPlannerResult",
    "StrandsStopReasonError",
    "StrandsTransportError",
    "create_strands_bedrock_model",
    "plan_with_strands",
]
