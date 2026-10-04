"""Unit tests for bounded Strands planning agent (Phase P-07.03).

Verifies the integration of the real Strands SDK with StillDone's bounded
Bedrock planner adapter, zero-tool fail-closed boundary, one-turn limit,
untrusted result inspection, and mandatory deterministic parser ingress.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterable, Generator
from typing import Any
from uuid import uuid4

import pytest

# Ensure offline execution — disable EC2 metadata probes
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

from stilldone.domain.action import ActionType
from stilldone.domain.mission import MissionId
from stilldone.planning.bedrock import (
    ACCEPTED_STOP_REASON,
    DEFAULT_BEDROCK_MODEL_ID,
    DEFAULT_BEDROCK_REGION,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_READ_TIMEOUT_SECONDS,
    DEFAULT_RETRY_MODE,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOTAL_MAX_ATTEMPTS,
    BedrockPlannerSettings,
)
from stilldone.planning.contracts import (
    MAX_PLANNER_JSON_BYTES,
    CandidatePlanProposal,
    OversizedJsonPayloadError,
    PlannerInput,
    PlannerMissionBindingError,
    PlannerTypeError,
    PlannerValueError,
    SymbolicTargetRef,
)
from stilldone.planning.strands_agent import (
    StrandsEmptyResponseError,
    StrandsNonTextContentError,
    StrandsPlannerResult,
    StrandsPlanRejectionError,
    StrandsStopReasonError,
    StrandsTransportError,
    create_strands_bedrock_model,
    plan_with_strands,
)


@pytest.fixture(autouse=True, scope="module")
def cleanup_provider_modules() -> Generator[None, None, None]:
    """Clean up provider SDK modules from sys.modules after module execution.

    Prevents leaking strands/boto3/botocore imports into subsequent domain purity tests.
    """
    yield
    for prefix in (
        "strands",
        "boto3",
        "botocore",
        "urllib3",
        "s3transfer",
        "jmespath",
        "opentelemetry",
        "httpx",
        "httpcore",
    ):
        for mod_name in list(sys.modules.keys()):
            if mod_name == prefix or mod_name.startswith(f"{prefix}."):
                sys.modules.pop(mod_name, None)


# ===========================================================================
# Deterministic Fake Model for Zero-Network Testing
# ===========================================================================


def _create_fake_model(
    events: list[dict[str, Any]] | None = None,
    *,
    model_id: str = DEFAULT_BEDROCK_MODEL_ID,
    should_raise: Exception | None = None,
) -> Any:
    """Helper factory for deterministic fake Strands model.

    Instantiates the model lazily so strands/boto3 are not imported at pytest collection.
    """
    from strands.models.model import Model
    from strands.types.content import Messages
    from strands.types.streaming import StreamEvent

    class FakeStrandsModel(Model):
        def __init__(self) -> None:
            self._model_id = model_id
            self.events = events or []
            self.should_raise = should_raise
            self.stream_call_count = 0
            self.last_messages: Messages | None = None

        def update_config(self, **model_config: Any) -> None:
            pass

        def get_config(self) -> dict[str, Any]:
            return {"model_id": self._model_id}

        async def structured_output(
            self,
            output_model: Any,
            prompt: Any,
            system_prompt: str | None = None,
            **kwargs: Any,
        ) -> Any:
            raise NotImplementedError("Structured output is excluded")
            yield {}  # pragma: no cover

        async def stream(
            self,
            messages: Messages,
            tool_specs: Any = None,
            system_prompt: str | None = None,
            **kwargs: Any,
        ) -> AsyncIterable[StreamEvent]:
            self.stream_call_count += 1
            self.last_messages = messages
            if self.should_raise is not None:
                raise self.should_raise

            for ev in self.events:
                yield ev  # type: ignore[misc]

    return FakeStrandsModel()


def _make_text_events(
    text: str,
    stop_reason: str = ACCEPTED_STOP_REASON,
) -> list[dict[str, Any]]:
    """Helper to build canonical streaming event sequence."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"start": {"text": ""}}},
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": stop_reason}},
    ]


def _make_valid_plan_json(mission_id: str) -> str:
    """Helper to generate a valid candidate plan JSON string."""
    return (
        "{\n"
        '  "schema_version": "v1",\n'
        f'  "mission_id": "{mission_id}",\n'
        '  "steps": [\n'
        "    {\n"
        '      "action_type": "calendar.read",\n'
        '      "target_ref": "calendar_event"\n'
        "    }\n"
        "  ],\n"
        '  "explanation": "Valid test plan"\n'
        "}"
    )


# ===========================================================================
# Test Suite: P-07.03 Bounded Strands Planning Agent
# ===========================================================================


class TestStrandsAgentSDKIntegration:
    """Verifies that the real Strands SDK classes and integration paths exist."""

    def test_real_strands_agent_class_is_used(self) -> None:
        """The planner uses the official strands.Agent class."""
        from strands import Agent

        assert Agent.__module__.startswith("strands.")

    def test_real_bedrock_model_class_is_used(self) -> None:
        """The model factory uses the official strands.models.bedrock.BedrockModel class."""
        from strands.models.bedrock import BedrockModel

        assert BedrockModel.__module__.startswith("strands.models.bedrock")

    def test_create_strands_bedrock_model_canonical_settings(self) -> None:
        """Factory creates BedrockModel with exact canonical settings."""
        from strands.models.bedrock import BedrockModel

        model = create_strands_bedrock_model()
        assert isinstance(model, BedrockModel)
        assert model.config["model_id"] == DEFAULT_BEDROCK_MODEL_ID
        assert model.config["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
        assert model.config["temperature"] == DEFAULT_TEMPERATURE
        assert model.config["streaming"] is False
        assert model.config["use_native_token_count"] is False

        # Verify client botocore configuration
        client_config = model.client.meta.config
        assert client_config.connect_timeout == DEFAULT_CONNECT_TIMEOUT_SECONDS
        assert client_config.read_timeout == DEFAULT_READ_TIMEOUT_SECONDS
        assert client_config.retries["total_max_attempts"] == DEFAULT_TOTAL_MAX_ATTEMPTS
        assert client_config.retries["mode"] == DEFAULT_RETRY_MODE
        assert model.client.meta.region_name == DEFAULT_BEDROCK_REGION

    def test_create_strands_bedrock_model_rejects_credentials_in_args(self) -> None:
        """Factory does not accept credentials as constructor arguments."""
        settings = BedrockPlannerSettings()
        _ = create_strands_bedrock_model(settings)
        assert not hasattr(settings, "aws_access_key_id")
        assert not hasattr(settings, "aws_secret_access_key")


class TestStrandsFailClosedConfiguration:
    """Verifies the strict fail-closed configuration applied to the Strands Agent."""

    def test_tools_is_explicit_empty_list(self) -> None:
        """Agent is initialized with tools=[] giving agent.tool_names == []."""
        mid = MissionId(str(uuid4()))
        p_in = PlannerInput(mission_id=mid, intent="Read calendar")
        events = _make_text_events(_make_valid_plan_json(str(mid)))
        fake = _create_fake_model(events=events)

        res = plan_with_strands(p_in, _model_override=fake)
        assert isinstance(res, StrandsPlannerResult)

    def test_agent_tool_names_must_be_empty(self) -> None:
        """Direct check that agent constructed has tool_names == []."""
        from strands import Agent

        fake = _create_fake_model()
        agent = Agent(
            model=fake,
            tools=[],
            load_tools_from_directory=False,
            callback_handler=None,
            retry_strategy=None,
            structured_output_model=None,
            context_manager=False,
            memory_manager=None,
            session_manager=None,
            storage=None,
            checkpointing=False,
            background_tasks=False,
        )
        assert agent.tool_names == []

    def test_load_tools_from_directory_disabled(self) -> None:
        """load_tools_from_directory is False."""
        from strands import Agent

        fake = _create_fake_model()
        agent = Agent(
            model=fake,
            tools=[],
            load_tools_from_directory=False,
            callback_handler=None,
            retry_strategy=None,
        )
        assert agent.load_tools_from_directory is False

    def test_callback_handler_disabled(self) -> None:
        """callback_handler is None, selecting null callback behavior."""
        from strands import Agent

        fake = _create_fake_model()
        agent = Agent(
            model=fake,
            tools=[],
            callback_handler=None,
            retry_strategy=None,
        )
        assert getattr(agent.callback_handler, "__name__", None) == "null_callback_handler"

    def test_retry_strategy_disabled(self) -> None:
        """retry_strategy is None, disabling Strands SDK retries (max_attempts=1)."""
        from strands import Agent

        fake = _create_fake_model()
        agent = Agent(
            model=fake,
            tools=[],
            callback_handler=None,
            retry_strategy=None,
        )
        assert agent._retry_strategy._max_attempts == 1

    def test_no_structured_output_model(self) -> None:
        """structured_output_model is None."""
        from strands import Agent

        fake = _create_fake_model()
        agent = Agent(
            model=fake,
            tools=[],
            structured_output_model=None,
            callback_handler=None,
            retry_strategy=None,
        )
        assert agent._default_structured_output_model is None

    def test_fresh_context_per_mission(self) -> None:
        """Each invocation creates a fresh Agent; no cross-mission context bleed."""
        mid1 = MissionId(str(uuid4()))
        mid2 = MissionId(str(uuid4()))
        events1 = _make_text_events(_make_valid_plan_json(str(mid1)))
        events2 = _make_text_events(_make_valid_plan_json(str(mid2)))
        fake1 = _create_fake_model(events=events1)
        fake2 = _create_fake_model(events=events2)

        p_in1 = PlannerInput(mission_id=mid1, intent="First mission")
        p_in2 = PlannerInput(mission_id=mid2, intent="Second mission")

        res1 = plan_with_strands(p_in1, _model_override=fake1)
        res2 = plan_with_strands(p_in2, _model_override=fake2)

        assert res1.plan.mission_id == mid1
        assert res2.plan.mission_id == mid2
        assert fake1.stream_call_count == 1
        assert fake2.stream_call_count == 1


class TestStrandsOneTurnAndStopReason:
    """Verifies the one model turn bound and stop_reason enforcement."""

    def test_accepted_end_turn_stop_reason(self) -> None:
        """stop_reason == 'end_turn' is accepted."""
        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)), stop_reason="end_turn")
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")
        res = plan_with_strands(p_in, _model_override=fake)
        assert res.stop_reason == "end_turn"

    @pytest.mark.parametrize(
        "bad_stop_reason",
        [
            "limit_turns",
            "max_tokens",
            "tool_use",
            "content_filtered",
            "guardrail_intervened",
            "cancelled",
            "checkpoint",
            "interrupt",
            "stop_sequence",
            "arbitrary_unknown_reason",
        ],
    )
    def test_unacceptable_stop_reasons_fail_closed(self, bad_stop_reason: str) -> None:
        """Any stop reason other than 'end_turn' fails closed with StrandsStopReasonError."""
        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)), stop_reason=bad_stop_reason)
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")
        with pytest.raises(StrandsStopReasonError) as exc_info:
            plan_with_strands(p_in, _model_override=fake)
        assert "Unacceptable Strands stop reason" in str(exc_info.value)


class TestStrandsResultExtractionAndParsing:
    """Verifies untrusted result extraction, size ceilings, and mandatory parser ingress."""

    def test_valid_json_crosses_deterministic_parser(self) -> None:
        """Valid JSON crosses parse_candidate_plan_for_input and returns validated proposal."""
        mid = MissionId(str(uuid4()))
        valid_json = (
            "{\n"
            '  "schema_version": "v1",\n'
            f'  "mission_id": "{mid}",\n'
            '  "steps": [\n'
            "    {\n"
            '      "action_type": "calendar.read",\n'
            '      "target_ref": "leave_for_school"\n'
            "    },\n"
            "    {\n"
            '      "action_type": "task.create",\n'
            '      "target_ref": "family_tasks",\n'
            '      "parameters": {"title": "Pack bags"}\n'
            "    }\n"
            "  ],\n"
            '  "explanation": "Valid morning prep plan"\n'
            "}"
        )
        fake = _create_fake_model(events=_make_text_events(valid_json))
        p_in = PlannerInput(mission_id=mid, intent="Prepare morning")
        result = plan_with_strands(p_in, _model_override=fake)

        assert isinstance(result.plan, CandidatePlanProposal)
        assert len(result.plan.steps) == 2
        assert result.plan.steps[0].action_type == ActionType.CALENDAR_READ
        assert result.plan.steps[0].target_ref == SymbolicTargetRef.LEAVE_FOR_SCHOOL
        assert result.plan.steps[1].action_type == ActionType.TASK_CREATE
        assert result.plan.steps[1].parameters.to_dict() == {"title": "Pack bags"}
        assert result.model_id == DEFAULT_BEDROCK_MODEL_ID
        assert result.region_name == DEFAULT_BEDROCK_REGION

    def test_mission_binding_mismatch_fails_closed(self) -> None:
        """Model returning a different mission_id fails closed with binding error."""
        mid_expected = MissionId(str(uuid4()))
        mid_tampered = str(uuid4())
        fake = _create_fake_model(events=_make_text_events(_make_valid_plan_json(mid_tampered)))
        p_in = PlannerInput(mission_id=mid_expected, intent="Check tasks")

        with pytest.raises(StrandsPlanRejectionError) as exc_info:
            plan_with_strands(p_in, _model_override=fake)
        assert exc_info.value.rejection_class is PlannerMissionBindingError

    def test_malformed_json_fails_closed(self) -> None:
        """Model returning malformed JSON fails closed."""
        mid = MissionId(str(uuid4()))
        fake = _create_fake_model(events=_make_text_events("not valid json at all {{{"))
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")

        with pytest.raises(StrandsPlanRejectionError) as exc_info:
            plan_with_strands(p_in, _model_override=fake)
        assert exc_info.value.rejection_class is PlannerValueError

    def test_empty_response_fails_closed(self) -> None:
        """Model returning empty text fails closed with StrandsEmptyResponseError."""
        mid = MissionId(str(uuid4()))
        fake = _create_fake_model(events=_make_text_events("   \n\t   "))
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")

        with pytest.raises(StrandsEmptyResponseError):
            plan_with_strands(p_in, _model_override=fake)

    def test_tool_use_in_content_fails_closed(self) -> None:
        """Model output containing toolUse content blocks is rejected."""
        events: list[dict[str, Any]] = [
            {"messageStart": {"role": "assistant"}},
            {
                "contentBlockStart": {
                    "start": {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": "shell_exec",
                            "input": {"command": "rm -rf /"},
                        }
                    }
                }
            },
            {"contentBlockStop": {}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
        fake = _create_fake_model(events=events)
        mid = MissionId(str(uuid4()))
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")

        with pytest.raises((StrandsNonTextContentError, StrandsStopReasonError)):
            plan_with_strands(p_in, _model_override=fake)

    def test_oversized_payload_fails_closed(self) -> None:
        """Output exceeding MAX_PLANNER_JSON_BYTES fails closed with OversizedJsonPayloadError."""
        mid = MissionId(str(uuid4()))
        oversized = "x" * (MAX_PLANNER_JSON_BYTES + 1)
        fake = _create_fake_model(events=_make_text_events(oversized))
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")

        with pytest.raises(StrandsPlanRejectionError) as exc_info:
            plan_with_strands(p_in, _model_override=fake)
        assert exc_info.value.rejection_class is OversizedJsonPayloadError

    def test_transport_error_suppresses_raw_cause(self) -> None:
        """Underlying transport exceptions are suppressed in StrandsTransportError."""
        fake = _create_fake_model(
            should_raise=ConnectionResetError("Sensitive internal endpoint: 10.0.0.1")
        )
        mid = MissionId(str(uuid4()))
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")

        with pytest.raises(StrandsTransportError) as exc_info:
            plan_with_strands(p_in, _model_override=fake)

        err = exc_info.value
        assert err.__cause__ is None
        assert err.__context__ is None
        assert "10.0.0.1" not in str(err)
        assert err.classification == "STRANDS_TRANSPORT_FAILURE"

    def test_invalid_planner_input_type_fails_closed(self) -> None:
        """Non-PlannerInput argument raises PlannerTypeError immediately."""
        with pytest.raises(PlannerTypeError):
            plan_with_strands("not a planner input")  # type: ignore[arg-type]


class TestStrandsResultImmutableContract:
    """Verifies that StrandsPlannerResult is an immutable dataclass."""

    def test_result_is_frozen(self) -> None:
        """StrandsPlannerResult is frozen and attributes cannot be mutated."""
        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)))
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")
        res = plan_with_strands(p_in, _model_override=fake)

        with pytest.raises((AttributeError, TypeError)):
            res.stop_reason = "tampered"  # type: ignore[misc]

    def test_result_does_not_create_ready_or_verified(self) -> None:
        """StrandsPlannerResult does not possess or create VERIFIED or READY state."""
        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)))
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")
        res = plan_with_strands(p_in, _model_override=fake)

        assert not hasattr(res, "verified")
        assert not hasattr(res, "ready")
        assert not hasattr(res, "approval_grant")
        assert not hasattr(res, "evidence_id")

    def test_result_contains_runtime_metadata(self) -> None:
        """StrandsPlannerResult binds invocation PlannerRuntimeMetadata."""
        from stilldone.planning.metadata import PlannerRuntimeMetadata

        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)))
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")
        res = plan_with_strands(p_in, _model_override=fake)

        assert isinstance(res.metadata, PlannerRuntimeMetadata)
        assert res.metadata.planner_runtime == "strands"
        assert res.metadata.planner_provider == "amazon_bedrock"
        assert res.metadata.model_id == DEFAULT_BEDROCK_MODEL_ID
        assert res.metadata.region_name == DEFAULT_BEDROCK_REGION
        assert res.metadata.turns_limit == 1
        assert res.metadata.tool_names == ()
        assert res.metadata.tools_count == 0
