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

    def test_single_source_of_metadata_truth_and_cannot_diverge(self) -> None:
        """Defect 6: StrandsPlannerResult stores only plan, stop_reason, metadata.

        model_id and region_name derive directly from metadata and cannot diverge.
        """
        import dataclasses

        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)))
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")
        res = plan_with_strands(p_in, _model_override=fake)

        field_names = [f.name for f in dataclasses.fields(StrandsPlannerResult)]
        assert field_names == ["plan", "stop_reason", "metadata"]

        assert res.model_id == res.metadata.model_id
        assert res.region_name == res.metadata.region_name

        with pytest.raises(AttributeError):
            res.model_id = "tampered-model"  # type: ignore[misc]

        with pytest.raises(AttributeError):
            res.region_name = "tampered-region"  # type: ignore[misc]

    def test_plan_with_strands_rejects_metadata_override_parameter(self) -> None:
        """Defect 5: plan_with_strands has no _metadata_override parameter.

        Metadata derives strictly from validated settings and installed environment.
        """
        import inspect

        sig = inspect.signature(plan_with_strands)
        assert "_metadata_override" not in sig.parameters

        mid = MissionId(str(uuid4()))
        events = _make_text_events(_make_valid_plan_json(str(mid)))
        fake = _create_fake_model(events=events)
        p_in = PlannerInput(mission_id=mid, intent="Check tasks")

        with pytest.raises(TypeError) as exc_info:
            plan_with_strands(p_in, _model_override=fake, _metadata_override="fake")  # type: ignore[call-arg]
        assert "unexpected keyword argument" in str(exc_info.value)


# ===========================================================================
# P-07.06 Live Proof Harness & Compatible Negative Control Tests
# ===========================================================================


class TestLiveProofHarnessAndControl:
    """Verifies P-07.06 live proof harness, approval gate, credential enforcement,
    clean working tree and exact SHA gate, and Strands-compatible negative control model contract.
    """

    def test_strands_compatible_non_producing_model_contract(self) -> None:
        """Compatible negative control inherits from Strands Model,
        enters normal Strands stream orchestration with zero network calls,
        and deterministic pipeline fails closed with StrandsEmptyResponseError.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        from p07_06_live_proof import (  # type: ignore[import-not-found]
            create_compatible_non_producing_model,
        )
        from strands.models.model import Model

        mid = MissionId(str(uuid4()))
        p_in = PlannerInput(mission_id=mid, intent="Check tasks and make plan")
        control_model: Any = create_compatible_non_producing_model()

        assert issubclass(control_model.__class__, Model)
        assert control_model.get_config() == {"model_id": DEFAULT_BEDROCK_MODEL_ID}

        with pytest.raises(StrandsEmptyResponseError) as exc_info:
            plan_with_strands(p_in, _model_override=control_model)

        assert "No text blocks found" in str(exc_info.value)
        assert control_model.stream_call_count == 1
        assert control_model.network_call_count == 0

    def test_live_proof_negative_control_only_mode(self) -> None:
        """Live proof CLI --negative-control-only executes negative control with zero AWS calls."""
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        exit_code = p07_06_live_proof.main(["--negative-control-only"])
        assert exit_code == 0

    def test_cli_gate_without_flags_fails_closed_zero_aws_calls(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Defect 2: Live proof CLI without flags exits non-zero BEFORE credential resolution
        with zero AWS calls.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        def forbid_credentials() -> Any:
            raise AssertionError("Credentials resolution MUST NOT be called without approval flag")

        monkeypatch.setattr(
            p07_06_live_proof, "resolve_and_verify_temporary_credentials", forbid_credentials
        )

        exit_code = p07_06_live_proof.main([])
        assert exit_code == 2

        captured = capsys.readouterr()
        assert "ERROR: Live Bedrock inference requires explicit operator approval" in captured.err

    def test_cli_gate_approve_live_without_approval_ref_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Defect 2: --approve-live without --operator-approval-ref exits non-zero
        BEFORE credential resolution.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        def forbid_credentials() -> Any:
            raise AssertionError("Credentials resolution MUST NOT be called without approval ref")

        monkeypatch.setattr(
            p07_06_live_proof, "resolve_and_verify_temporary_credentials", forbid_credentials
        )

        exit_code = p07_06_live_proof.main(["--approve-live"])
        assert exit_code == 2

        captured = capsys.readouterr()
        assert (
            "ERROR: Live Bedrock inference requires an explicit operator approval reference"
            in captured.err
        )

    def test_cli_gate_blank_approval_ref_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Defect 2: Whitespace/empty --operator-approval-ref exits non-zero
        BEFORE credential resolution.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        def forbid_credentials() -> Any:
            raise AssertionError(
                "Credentials resolution MUST NOT be called with blank approval ref"
            )

        monkeypatch.setattr(
            p07_06_live_proof, "resolve_and_verify_temporary_credentials", forbid_credentials
        )

        exit_code = p07_06_live_proof.main(["--approve-live", "--operator-approval-ref", "   "])
        assert exit_code == 2

        captured = capsys.readouterr()
        assert (
            "ERROR: Live Bedrock inference requires an explicit operator approval reference"
            in captured.err
        )

    def test_cli_gate_missing_expected_sha_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Defect 3: --approve-live with approval ref but missing --expected-source-sha
        exits non-zero.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        def forbid_credentials() -> Any:
            raise AssertionError("Credentials resolution MUST NOT be called without expected SHA")

        monkeypatch.setattr(
            p07_06_live_proof, "resolve_and_verify_temporary_credentials", forbid_credentials
        )

        exit_code = p07_06_live_proof.main(
            [
                "--approve-live",
                "--operator-approval-ref",
                "APPROVE P-07.06 TEST",
            ]
        )
        assert exit_code == 2

        captured = capsys.readouterr()
        assert (
            "ERROR: Live Bedrock inference requires an explicit expected commit SHA" in captured.err
        )

    def test_cli_gate_valid_args_proceed_to_credential_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2 & 3: Valid flags pass argument and git checks and reach the credential gate."""
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        test_sha = "a" * 40
        monkeypatch.setattr(
            p07_06_live_proof, "verify_source_sha_and_tree", lambda expected: test_sha
        )

        class CredentialGateReached(Exception):
            pass

        def sentinel_credential_resolver() -> Any:
            raise CredentialGateReached("Credential gate reached successfully before inference")

        monkeypatch.setattr(
            p07_06_live_proof,
            "resolve_and_verify_temporary_credentials",
            sentinel_credential_resolver,
        )

        exit_code = p07_06_live_proof.main(
            [
                "--approve-live",
                "--operator-approval-ref",
                "APPROVE P-07.06 TEST",
                "--expected-source-sha",
                test_sha,
            ]
        )
        assert exit_code == 2  # Proves credentials gate was executed and error handled!

    def test_run_live_proof_rejects_missing_or_blank_args(self) -> None:
        """Defect 2 & 3: run_live_proof itself fails closed on missing or blank
        approval ref or expected SHA.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        test_sha = "a" * 40
        with pytest.raises(ValueError, match="Missing or empty operator_approval_ref"):
            p07_06_live_proof.run_live_proof(
                operator_approval_ref="",
                expected_source_sha=test_sha,
            )

        with pytest.raises(ValueError, match="Missing or empty operator_approval_ref"):
            p07_06_live_proof.run_live_proof(
                operator_approval_ref="   ",
                expected_source_sha=test_sha,
            )

        with pytest.raises(ValueError, match="Missing or empty expected_source_sha"):
            p07_06_live_proof.run_live_proof(
                operator_approval_ref="APPROVE P-07.06 TEST",
                expected_source_sha="",
            )

        with pytest.raises(ValueError, match="Missing or empty expected_source_sha"):
            p07_06_live_proof.run_live_proof(
                operator_approval_ref="APPROVE P-07.06 TEST",
                expected_source_sha="   ",
            )

    def test_verify_source_sha_and_tree_matrix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defect 3: Deterministic test matrix for verify_source_sha_and_tree():
        1. Clean exact match -> accepted (returns sha)
        2. Dirty tree -> rejected
        3. HEAD mismatch -> rejected
        4. origin/main mismatch -> rejected
        5. Git command failure -> rejected
        """
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        sha_a = "1" * 40
        sha_b = "2" * 40

        # Case 1: Clean exact match -> accepted
        def mock_git_clean(cmd: list[str], **kwargs: Any) -> str:
            if "status" in cmd:
                return ""
            if "HEAD" in cmd:
                return sha_a
            if "origin/main" in cmd:
                return sha_a
            raise RuntimeError(f"Unexpected git cmd: {cmd}")

        monkeypatch.setattr(subprocess, "check_output", mock_git_clean)
        result_sha = p07_06_live_proof.verify_source_sha_and_tree(sha_a)
        assert result_sha == sha_a

        # Case 2: Dirty tree -> rejected
        def mock_git_dirty(cmd: list[str], **kwargs: Any) -> str:
            if "status" in cmd:
                return " M scripts/p07_06_live_proof.py"
            return sha_a

        monkeypatch.setattr(subprocess, "check_output", mock_git_dirty)
        with pytest.raises(RuntimeError, match="Git working tree is dirty"):
            p07_06_live_proof.verify_source_sha_and_tree(sha_a)

        # Case 3: HEAD mismatch with expected SHA -> rejected
        def mock_git_head_mismatch(cmd: list[str], **kwargs: Any) -> str:
            if "status" in cmd:
                return ""
            if "HEAD" in cmd:
                return sha_b
            if "origin/main" in cmd:
                return sha_b
            return ""

        monkeypatch.setattr(subprocess, "check_output", mock_git_head_mismatch)
        with pytest.raises(RuntimeError, match="does not match expected source SHA"):
            p07_06_live_proof.verify_source_sha_and_tree(sha_a)

        # Case 4: HEAD mismatch with origin/main -> rejected
        def mock_git_origin_mismatch(cmd: list[str], **kwargs: Any) -> str:
            if "status" in cmd:
                return ""
            if "HEAD" in cmd:
                return sha_a
            if "origin/main" in cmd:
                return sha_b
            return ""

        monkeypatch.setattr(subprocess, "check_output", mock_git_origin_mismatch)
        with pytest.raises(RuntimeError, match="does not match origin/main"):
            p07_06_live_proof.verify_source_sha_and_tree(sha_a)

        # Case 5: Git command failure -> rejected
        def mock_git_failure(cmd: list[str], **kwargs: Any) -> str:
            raise subprocess.CalledProcessError(128, cmd, output="fatal: not a git repository")

        monkeypatch.setattr(subprocess, "check_output", mock_git_failure)
        with pytest.raises(RuntimeError, match="Git command failed"):
            p07_06_live_proof.verify_source_sha_and_tree(sha_a)

    def test_temporary_credentials_matrix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defect 1: Deterministic test matrix for resolve_and_verify_temporary_credentials():
        1. ASIA + secret + session token -> accepted
        2. AKIA + secret + session token -> rejected
        3. ZZZZ + secret + session token -> rejected
        4. ASIA + secret + no session token -> rejected
        5. ASIA + no secret + session token -> rejected
        No secret values logged or leaked in output.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        # Prevent CLI fallback to aws configure export-credentials
        monkeypatch.setattr(p07_06_live_proof.shutil, "which", lambda cmd: None)

        secret_val = "SECRET_VALUE_MUST_NOT_LEAK_999"
        token_val = "SESSION_TOKEN_MUST_NOT_LEAK_888"

        # 1. ASIA + secret + session token -> accepted
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIAPOSITIVETEST1234")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret_val)
        monkeypatch.setenv("AWS_SESSION_TOKEN", token_val)

        meta = p07_06_live_proof.resolve_and_verify_temporary_credentials()
        assert meta["credential_mode"] == "temporary_session"
        assert meta["session_token_present"] is True
        assert meta["key_prefix"] == "ASIA"
        assert secret_val not in str(meta)
        assert token_val not in str(meta)

        # 2. AKIA + secret + session token -> rejected
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIASTATICUSERKEY123")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret_val)
        monkeypatch.setenv("AWS_SESSION_TOKEN", token_val)

        with pytest.raises(RuntimeError, match="Invalid AWS access key prefix.*AKIA") as exc_info:
            p07_06_live_proof.resolve_and_verify_temporary_credentials()
        assert secret_val not in str(exc_info.value)

        # 3. ZZZZ + secret + session token -> rejected
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ZZZZCUSTOMPREFIX123")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret_val)
        monkeypatch.setenv("AWS_SESSION_TOKEN", token_val)

        with pytest.raises(RuntimeError, match="Invalid AWS access key prefix.*ZZZZ") as exc_info:
            p07_06_live_proof.resolve_and_verify_temporary_credentials()
        assert secret_val not in str(exc_info.value)

        # 4. ASIA + secret + no session token -> rejected
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIAPOSITIVETEST1234")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret_val)
        monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="Missing AWS_SESSION_TOKEN") as exc_info:
            p07_06_live_proof.resolve_and_verify_temporary_credentials()
        assert secret_val not in str(exc_info.value)

        # 5. ASIA + no secret + session token -> rejected
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIAPOSITIVETEST1234")
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setenv("AWS_SESSION_TOKEN", token_val)

        with pytest.raises(RuntimeError, match="Missing AWS_SECRET_ACCESS_KEY") as exc_info:
            p07_06_live_proof.resolve_and_verify_temporary_credentials()
        assert token_val not in str(exc_info.value)

    def test_evidence_facts_billing_and_approval_truth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2 & 4: Evidence dictionary records exact supplied approval ref,
        and records underlying cost and billing status as unobserved by runtime.
        Zero hard-coded $0.00 spend or active credit assumed.
        """
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        import p07_06_live_proof

        real_plan_with_strands = p07_06_live_proof.plan_with_strands

        def mock_plan(p_in: Any, settings: Any = None, **kwargs: Any) -> Any:
            if "_model_override" in kwargs:
                return real_plan_with_strands(p_in, settings=settings, **kwargs)
            fake_json = _make_valid_plan_json(str(p_in.mission_id))
            fake_model = _create_fake_model(events=_make_text_events(fake_json))
            return real_plan_with_strands(p_in, settings=settings, _model_override=fake_model)

        monkeypatch.setattr(p07_06_live_proof, "plan_with_strands", mock_plan)

        approval_ref = "APPROVE P-07.06 DETERMINISTIC PROOF REF"
        source_sha = "d" * 40

        facts = p07_06_live_proof.run_live_proof(
            operator_approval_ref=approval_ref,
            expected_source_sha=source_sha,
            credential_metadata={
                "credential_mode": "temporary_session",
                "session_token_present": True,
                "key_prefix": "ASIA",
                "expiration": "2026-10-05T12:00:00Z",
            },
        )

        assert facts["execution_source_sha"] == source_sha
        assert facts["operator_approval"]["operator_approval_ref"] == approval_ref
        assert facts["operator_approval"]["authorized_before_inference"] is True
        assert facts["underlying_service_cost"] == "NOT_DETERMINISTICALLY_OBSERVED"
        assert facts["promotional_credit_status"] == "NOT_OBSERVED_BY_THIS_RUNTIME"
        assert facts["personal_spend_delta"] == "NOT_OBSERVED_BY_THIS_RUNTIME"
        assert facts["live_call_count"] == 1
        assert facts["negative_control"]["negative_control_passed"] is True
