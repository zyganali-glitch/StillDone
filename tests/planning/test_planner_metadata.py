"""Tests for Planner Runtime Metadata and Evidence Binding (Phase P-07.05).

Verifies:
- PlannerRuntimeMetadata is an immutable frozen dataclass.
- All 18 canonical stored metadata fields are present and strictly typed.
- tools_count is a derived read-only property matching len(tool_names).
- Package versions are resolved deterministically from installed environment.
- Missing package raises PackageVersionError.
- bind_planner_runtime_metadata creates a new dict under "planner_runtime".
- Original payload is deep-detached and never mutated.
- Key collision on "planner_runtime" raises ReservedKeyCollisionError.
- Metadata binds cleanly into a REAL EvidenceRecord.create(...).
- Changing ANY of the 18 serialized metadata fields produces a distinct EvidenceId.
- No fabricated ActionId or planner pseudo action exists.
- Zero network calls during metadata creation or binding.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Generator
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import patch

import pytest

from stilldone.application.ports.ledger_port import EvidenceRecord
from stilldone.domain.action import ActionId, ActionType
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceOrigin
from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.planning.bedrock import BedrockPlannerSettings
from stilldone.planning.metadata import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_ID,
    DEFAULT_READ_TIMEOUT_SECONDS,
    DEFAULT_REGION_NAME,
    DEFAULT_RETRY_MODE,
    DEFAULT_SCHEMA_VERSION,
    DEFAULT_STRANDS_SDK_RETRIES,
    DEFAULT_STREAMING,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOOL_NAMES,
    DEFAULT_TOOLS_COUNT,
    DEFAULT_TOTAL_MAX_ATTEMPTS,
    DEFAULT_TURNS_LIMIT,
    PLANNER_PROVIDER_AMAZON_BEDROCK,
    PLANNER_RUNTIME_PAYLOAD_KEY,
    PLANNER_RUNTIME_STRANDS,
    PackageVersionError,
    PlannerMetadataError,
    PlannerRuntimeMetadata,
    ReservedKeyCollisionError,
    _get_installed_version,
    bind_planner_runtime_metadata,
    create_planner_runtime_metadata,
)


@pytest.fixture(autouse=True, scope="module")
def cleanup_provider_modules() -> Generator[None, None, None]:
    """Clean up provider SDK modules from sys.modules after module execution."""
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
# Unit Tests: Package Version Resolution
# ===========================================================================


class TestPackageVersionResolution:
    """Verifies deterministic package version resolution via importlib.metadata."""

    def test_strands_version_resolves(self) -> None:
        version = _get_installed_version("strands-agents")
        assert isinstance(version, str)
        assert len(version) > 0

    def test_boto3_version_resolves(self) -> None:
        version = _get_installed_version("boto3")
        assert isinstance(version, str)
        assert len(version) > 0

    def test_botocore_version_resolves(self) -> None:
        version = _get_installed_version("botocore")
        assert isinstance(version, str)
        assert len(version) > 0

    def test_missing_package_raises_package_version_error(self) -> None:
        with pytest.raises(PackageVersionError) as exc_info:
            _get_installed_version("nonexistent-package-xyz-12345")
        assert "not installed" in str(exc_info.value)
        assert issubclass(PackageVersionError, PlannerMetadataError)


# ===========================================================================
# Unit Tests: PlannerRuntimeMetadata Immutability and Validation
# ===========================================================================


class TestPlannerRuntimeMetadata:
    """Verifies PlannerRuntimeMetadata invariants, types, and immutability."""

    @pytest.fixture
    def sample_metadata(self) -> PlannerRuntimeMetadata:
        return create_planner_runtime_metadata()

    def test_is_frozen_immutable(self, sample_metadata: PlannerRuntimeMetadata) -> None:
        with pytest.raises(FrozenInstanceError):
            sample_metadata.model_id = "other-model"  # type: ignore[misc]

    def test_all_18_required_fields_present_and_correct(
        self, sample_metadata: PlannerRuntimeMetadata
    ) -> None:
        assert sample_metadata.planner_runtime == "strands"
        assert sample_metadata.planner_provider == "amazon_bedrock"
        assert sample_metadata.model_id == "amazon.nova-micro-v1:0"
        assert sample_metadata.region_name == "us-east-1"
        assert sample_metadata.schema_version == "v1"
        assert isinstance(sample_metadata.strands_version, str)
        assert len(sample_metadata.strands_version) > 0
        assert isinstance(sample_metadata.boto3_version, str)
        assert len(sample_metadata.boto3_version) > 0
        assert isinstance(sample_metadata.botocore_version, str)
        assert len(sample_metadata.botocore_version) > 0
        assert sample_metadata.max_tokens == 2048
        assert sample_metadata.temperature == 0.00001
        assert sample_metadata.connect_timeout_seconds == 5.0
        assert sample_metadata.read_timeout_seconds == 30.0
        assert sample_metadata.total_max_attempts == 1
        assert sample_metadata.retry_mode == "standard"
        assert sample_metadata.streaming is False
        assert sample_metadata.strands_sdk_retries is False
        assert sample_metadata.turns_limit == 1
        assert sample_metadata.tool_names == ()
        # Derived property verification:
        assert sample_metadata.tools_count == 0

    def test_to_dict_contains_all_18_fields(self, sample_metadata: PlannerRuntimeMetadata) -> None:
        d = sample_metadata.to_dict()
        assert isinstance(d, dict)
        expected_keys = {
            "planner_runtime",
            "planner_provider",
            "model_id",
            "region_name",
            "schema_version",
            "strands_version",
            "boto3_version",
            "botocore_version",
            "max_tokens",
            "temperature",
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "total_max_attempts",
            "retry_mode",
            "streaming",
            "strands_sdk_retries",
            "turns_limit",
            "tool_names",
        }
        assert set(d.keys()) == expected_keys
        assert len(d) == 18

    def test_tools_count_is_derived_read_only_property(
        self, sample_metadata: PlannerRuntimeMetadata
    ) -> None:
        """Prove tools_count is a derived read-only property matching len(tool_names)."""
        assert sample_metadata.tools_count == 0
        assert sample_metadata.tools_count == len(sample_metadata.tool_names)

        # Non-empty tool_names
        kwargs = sample_metadata.to_dict()
        kwargs["tool_names"] = ("calendar.read", "tasks.read")
        meta = PlannerRuntimeMetadata(**kwargs)
        assert meta.tools_count == 2
        assert meta.tools_count == len(meta.tool_names)

        # Read-only property cannot be set
        with pytest.raises(AttributeError):
            meta.tools_count = 5  # type: ignore[misc]

        # tools_count is not accepted as an independent constructor kwarg
        kwargs_with_tools_count = sample_metadata.to_dict()
        kwargs_with_tools_count["tools_count"] = 0
        with pytest.raises(TypeError):
            PlannerRuntimeMetadata(**kwargs_with_tools_count)

    def test_temperature_boundary_contracts(self, sample_metadata: PlannerRuntimeMetadata) -> None:
        """Prove PlannerRuntimeMetadata direct construction enforces 0.0 <= temperature <= 1.0.

        Required:
        - 0.0 accepted;
        - 1.0 accepted;
        - current canonical 0.00001 accepted;
        - any value < 0.0 rejected;
        - any value > 1.0 rejected (specifically 1.000001 and 2.0);
        - bool rejected;
        - NaN rejected;
        - +inf rejected;
        - -inf rejected.
        """
        base = sample_metadata.to_dict()

        # Accepted boundaries
        for valid_temp in (0.0, 1.0, 0.00001, 0.5):
            kwargs = dict(base)
            kwargs["temperature"] = valid_temp
            meta = PlannerRuntimeMetadata(**kwargs)
            assert meta.temperature == valid_temp

        # Explicit direct-contract tests: rejected out-of-range (> 1.0)
        for high_temp in (1.000001, 2.0, 100.0):
            kwargs = dict(base)
            kwargs["temperature"] = high_temp
            with pytest.raises(ValueError, match="temperature cannot exceed 1.0"):
                PlannerRuntimeMetadata(**kwargs)

        # Rejected negative (< 0.0)
        for neg_temp in (-0.00001, -1.0, -100.0):
            kwargs = dict(base)
            kwargs["temperature"] = neg_temp
            with pytest.raises(ValueError, match="temperature cannot be negative"):
                PlannerRuntimeMetadata(**kwargs)

        # Rejected non-numeric / bool
        for non_num in (True, False):
            kwargs = dict(base)
            kwargs["temperature"] = non_num
            with pytest.raises(TypeError, match="temperature must be a float or int"):
                PlannerRuntimeMetadata(**kwargs)

        # Rejected non-finite (NaN, inf)
        for non_finite in (float("nan"), float("inf"), float("-inf")):
            kwargs = dict(base)
            kwargs["temperature"] = non_finite
            with pytest.raises(ValueError, match="temperature cannot be NaN or infinity"):
                PlannerRuntimeMetadata(**kwargs)

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("planner_runtime", 123),
            ("planner_provider", 456),
            ("model_id", None),
            ("region_name", ["us-east-1"]),
            ("schema_version", 1),
            ("strands_version", 1.57),
            ("boto3_version", None),
            ("botocore_version", True),
            ("max_tokens", "2048"),
            ("temperature", "cold"),
            ("connect_timeout_seconds", "5s"),
            ("read_timeout_seconds", None),
            ("total_max_attempts", "1"),
            ("retry_mode", 123),
            ("streaming", "false"),
            ("strands_sdk_retries", "false"),
            ("turns_limit", "1"),
            ("tool_names", "not-a-tuple"),
        ],
    )
    def test_field_type_validation_fails_closed(
        self, sample_metadata: PlannerRuntimeMetadata, field: str, bad_value: Any
    ) -> None:
        kwargs = sample_metadata.to_dict()
        kwargs[field] = bad_value
        with pytest.raises(TypeError):
            PlannerRuntimeMetadata(**kwargs)

    @pytest.mark.parametrize(
        ("field", "bad_numeric", "expected_exc"),
        [
            ("temperature", True, TypeError),
            ("temperature", False, TypeError),
            ("temperature", float("nan"), ValueError),
            ("temperature", float("inf"), ValueError),
            ("temperature", float("-inf"), ValueError),
            ("temperature", -0.001, ValueError),
            ("temperature", 1.000001, ValueError),
            ("temperature", 2.0, ValueError),
            ("connect_timeout_seconds", True, TypeError),
            ("connect_timeout_seconds", False, TypeError),
            ("connect_timeout_seconds", float("nan"), ValueError),
            ("connect_timeout_seconds", float("inf"), ValueError),
            ("connect_timeout_seconds", float("-inf"), ValueError),
            ("connect_timeout_seconds", 0.0, ValueError),
            ("connect_timeout_seconds", -5.0, ValueError),
            ("read_timeout_seconds", True, TypeError),
            ("read_timeout_seconds", False, TypeError),
            ("read_timeout_seconds", float("nan"), ValueError),
            ("read_timeout_seconds", float("inf"), ValueError),
            ("read_timeout_seconds", float("-inf"), ValueError),
            ("read_timeout_seconds", 0.0, ValueError),
            ("read_timeout_seconds", -30.0, ValueError),
            ("max_tokens", True, TypeError),
            ("max_tokens", 0, ValueError),
            ("max_tokens", -10, ValueError),
            ("total_max_attempts", True, TypeError),
            ("total_max_attempts", 0, ValueError),
            ("total_max_attempts", -1, ValueError),
            ("turns_limit", True, TypeError),
            ("turns_limit", 0, ValueError),
            ("turns_limit", -1, ValueError),
        ],
    )
    def test_strict_finite_numerics_and_ranges_fail_closed(
        self,
        sample_metadata: PlannerRuntimeMetadata,
        field: str,
        bad_numeric: Any,
        expected_exc: type[Exception],
    ) -> None:
        """Prove PlannerRuntimeMetadata direct construction rejects bool,
        NaN, inf, and invalid ranges.
        """
        kwargs = sample_metadata.to_dict()
        kwargs[field] = bad_numeric
        with pytest.raises(expected_exc):
            PlannerRuntimeMetadata(**kwargs)


# ===========================================================================
# Unit Tests: create_planner_runtime_metadata Factory
# ===========================================================================


class TestCreatePlannerRuntimeMetadata:
    """Verifies factory function behavior and defaults."""

    def test_defaults_match_canonical_settings(self) -> None:
        meta = create_planner_runtime_metadata()
        assert meta.planner_runtime == PLANNER_RUNTIME_STRANDS
        assert meta.planner_provider == PLANNER_PROVIDER_AMAZON_BEDROCK
        assert meta.model_id == DEFAULT_MODEL_ID
        assert meta.region_name == DEFAULT_REGION_NAME
        assert meta.schema_version == DEFAULT_SCHEMA_VERSION
        assert meta.max_tokens == DEFAULT_MAX_TOKENS
        assert meta.temperature == DEFAULT_TEMPERATURE
        assert meta.connect_timeout_seconds == DEFAULT_CONNECT_TIMEOUT_SECONDS
        assert meta.read_timeout_seconds == DEFAULT_READ_TIMEOUT_SECONDS
        assert meta.total_max_attempts == DEFAULT_TOTAL_MAX_ATTEMPTS
        assert meta.retry_mode == DEFAULT_RETRY_MODE
        assert meta.streaming == DEFAULT_STREAMING
        assert meta.strands_sdk_retries == DEFAULT_STRANDS_SDK_RETRIES
        assert meta.turns_limit == DEFAULT_TURNS_LIMIT
        assert meta.tool_names == DEFAULT_TOOL_NAMES
        assert meta.tools_count == DEFAULT_TOOLS_COUNT

    def test_factory_derives_from_validated_bedrock_settings(self) -> None:
        cfg = BedrockPlannerSettings(
            model_id="amazon.nova-micro-v1:0",
            region_name="us-east-1",
            connect_timeout=3.0,
            read_timeout=20.0,
        )
        meta = create_planner_runtime_metadata(cfg)
        assert meta.connect_timeout_seconds == 3.0
        assert meta.read_timeout_seconds == 20.0
        assert meta.model_id == "amazon.nova-micro-v1:0"

    def test_factory_rejects_invalid_settings_type(self) -> None:
        with pytest.raises(TypeError) as exc_info:
            create_planner_runtime_metadata("not-settings")  # type: ignore[arg-type]
        assert "settings must be BedrockPlannerSettings" in str(exc_info.value)


# ===========================================================================
# Unit Tests: Evidence Binding Surface & Deep Detachment
# ===========================================================================


class TestBindPlannerRuntimeMetadata:
    """Verifies bind_planner_runtime_metadata immutability, deep detachment, and collision rules."""

    @pytest.fixture
    def meta(self) -> PlannerRuntimeMetadata:
        return create_planner_runtime_metadata()

    def test_bind_creates_new_dict_with_reserved_key(self, meta: PlannerRuntimeMetadata) -> None:
        original = {"mission_id": "test-mission", "status": "PLANNED"}
        original_copy = copy.deepcopy(original)

        bound = bind_planner_runtime_metadata(original, meta)

        # Original payload must NOT be mutated
        assert original == original_copy
        assert PLANNER_RUNTIME_PAYLOAD_KEY not in original

        # Bound payload must contain original keys plus reserved key
        assert bound["mission_id"] == "test-mission"
        assert bound["status"] == "PLANNED"
        assert PLANNER_RUNTIME_PAYLOAD_KEY in bound
        assert bound[PLANNER_RUNTIME_PAYLOAD_KEY] == meta.to_dict()

    def test_bind_deep_detaches_nested_payload(self, meta: PlannerRuntimeMetadata) -> None:
        original: dict[str, Any] = {
            "mission_id": "test-mission",
            "nested": {"param": "value", "list": [1, 2, 3]},
        }
        bound = bind_planner_runtime_metadata(original, meta)

        # Mutate original nested objects
        original["nested"]["param"] = "mutated_value"
        original["nested"]["list"].append(4)

        # Bound object must remain isolated and unaffected
        assert bound["nested"]["param"] == "value"
        assert bound["nested"]["list"] == [1, 2, 3]

    def test_bind_rejects_non_dict_payload(self, meta: PlannerRuntimeMetadata) -> None:
        with pytest.raises(TypeError) as exc_info:
            bind_planner_runtime_metadata("not-a-dict", meta)  # type: ignore[arg-type]
        assert "payload must be a dict" in str(exc_info.value)

    def test_bind_rejects_non_metadata_instance(self) -> None:
        with pytest.raises(TypeError) as exc_info:
            bind_planner_runtime_metadata({"a": 1}, "not-metadata")  # type: ignore[arg-type]
        assert "metadata must be a PlannerRuntimeMetadata" in str(exc_info.value)

    def test_bind_rejects_reserved_key_collision(self, meta: PlannerRuntimeMetadata) -> None:
        collision_payload = {
            "mission_id": "test-mission",
            PLANNER_RUNTIME_PAYLOAD_KEY: {"injected": "fake"},
        }
        with pytest.raises(ReservedKeyCollisionError) as exc_info:
            bind_planner_runtime_metadata(collision_payload, meta)
        assert "already contains reserved key" in str(exc_info.value)
        assert issubclass(ReservedKeyCollisionError, PlannerMetadataError)


# ===========================================================================
# EvidenceRecord Integration: Binding inside REAL EvidenceRecord.create(...)
# ===========================================================================


class TestEvidenceRecordBinding:
    """Verifies that bound metadata integrates cleanly into a REAL EvidenceRecord.create(...)."""

    def test_bind_inside_real_evidence_record(self) -> None:
        from uuid import uuid4

        meta = create_planner_runtime_metadata()
        action_id = ActionId(str(uuid4()))
        mission_id = MissionId(str(uuid4()))
        origin = EvidenceOrigin.local_execution()
        raw_payload = {"plan_summary": "Test morning workflow"}
        bound_payload = bind_planner_runtime_metadata(raw_payload, meta)

        record = EvidenceRecord.create(
            action_id=action_id,
            mission_id=mission_id,
            origin=origin,
            payload=bound_payload,
        )

        assert isinstance(record, EvidenceRecord)
        assert isinstance(record.evidence_id, EvidenceId)
        assert record.action_id == action_id
        assert record.mission_id == mission_id
        assert record.origin == origin
        assert record.payload[PLANNER_RUNTIME_PAYLOAD_KEY] == meta.to_dict()

    def test_caller_action_id_provenance_and_no_planner_pseudo_action(self) -> None:
        """Strengthen ActionId provenance proof:
        - obtain legitimate caller-owned ActionId through canonical domain construction;
        - metadata helpers accept payload/metadata only and have zero API for ActionId;
        - prove bind_planner_runtime_metadata creates no ActionId;
        - prove create_planner_runtime_metadata creates no ActionId;
        - EvidenceRecord receives the existing ActionId from caller context;
        - retain proof that no planner pseudo ActionType was introduced.
        """
        import inspect
        from uuid import uuid4

        # 1. Obtain legitimate caller-owned ActionId through canonical domain construction
        caller_action_id = ActionId(str(uuid4()))
        caller_mission_id = MissionId(str(uuid4()))
        origin = EvidenceOrigin.local_execution()

        # 2. Metadata helpers accept payload/metadata only (zero ActionId API)
        meta_sig = inspect.signature(create_planner_runtime_metadata)
        assert "action_id" not in meta_sig.parameters
        assert "action" not in meta_sig.parameters

        bind_sig = inspect.signature(bind_planner_runtime_metadata)
        assert set(bind_sig.parameters.keys()) == {"payload", "metadata"}

        # 3. Prove create_planner_runtime_metadata creates no ActionId
        meta = create_planner_runtime_metadata()
        assert not hasattr(meta, "action_id")
        assert not hasattr(meta, "action_type")
        assert not hasattr(meta, "action")

        # 4. Prove bind_planner_runtime_metadata creates no ActionId
        raw_payload = {"plan_summary": "Test workflow"}
        bound_payload = bind_planner_runtime_metadata(raw_payload, meta)
        assert "action_id" not in bound_payload
        assert "action_id" not in bound_payload[PLANNER_RUNTIME_PAYLOAD_KEY]
        assert not any(isinstance(v, ActionId) for v in bound_payload.values())
        assert not any(
            isinstance(v, ActionId) for v in bound_payload[PLANNER_RUNTIME_PAYLOAD_KEY].values()
        )

        # 5. EvidenceRecord receives existing ActionId from caller context
        record = EvidenceRecord.create(
            action_id=caller_action_id,
            mission_id=caller_mission_id,
            origin=origin,
            payload=bound_payload,
        )
        assert record.action_id == caller_action_id
        assert record.mission_id == caller_mission_id
        assert record.origin == origin

        # 6. Retain proof that no planner pseudo ActionType was introduced
        forbidden_names = {"PLANNER", "PLAN", "PLANNING", "MODEL_PLAN", "STRANDS_PLAN"}
        for action_type in ActionType:
            assert action_type.name not in forbidden_names
            assert action_type.value not in forbidden_names


# ===========================================================================
# Deterministic Evidence Hashing Sensitivity: Changing Any Field Changes Hash
# ===========================================================================


class TestEvidenceHashingSensitivity:
    """Proves that changing ANY single field of PlannerRuntimeMetadata produces
    a strictly different EvidenceId / SHA-256 hash when bound into REAL EvidenceRecord.create(...).
    """

    @pytest.fixture
    def mission_id(self) -> MissionId:
        from uuid import uuid4

        return MissionId(str(uuid4()))

    @pytest.fixture
    def action_id(self) -> ActionId:
        from uuid import uuid4

        return ActionId(str(uuid4()))

    @pytest.fixture
    def origin(self) -> EvidenceOrigin:
        return EvidenceOrigin.local_execution()

    @pytest.fixture
    def base_payload(self) -> dict[str, Any]:
        return {"mission_id": "12345678-1234-5678-1234-567812345678", "intent": "morning"}

    @pytest.fixture
    def base_meta(self) -> PlannerRuntimeMetadata:
        return create_planner_runtime_metadata()

    def test_baseline_evidence_record_deterministic(
        self,
        mission_id: MissionId,
        action_id: ActionId,
        origin: EvidenceOrigin,
        base_payload: dict[str, Any],
        base_meta: PlannerRuntimeMetadata,
    ) -> None:
        """Prove: same metadata + same origin + same payload + same mission/action relation
        => same EvidenceRecord.evidence_id.
        """
        bound1 = bind_planner_runtime_metadata(base_payload, base_meta)
        bound2 = bind_planner_runtime_metadata(base_payload, base_meta)

        rec1 = EvidenceRecord.create(
            action_id=action_id,
            mission_id=mission_id,
            origin=origin,
            payload=bound1,
        )
        rec2 = EvidenceRecord.create(
            action_id=action_id,
            mission_id=mission_id,
            origin=origin,
            payload=bound2,
        )

        assert isinstance(rec1.evidence_id, EvidenceId)
        assert rec1.evidence_id == rec2.evidence_id
        assert str(rec1.evidence_id) == str(rec2.evidence_id)
        assert rec1.origin == origin
        assert rec1.origin.provenance.value == "LOCAL_EXECUTION"

    @pytest.mark.parametrize(
        ("field", "modified_value"),
        [
            ("planner_runtime", "other_runtime"),
            ("planner_provider", "google_vertex"),
            ("model_id", "anthropic.claude-v2"),
            ("region_name", "eu-central-1"),
            ("schema_version", "v2"),
            ("strands_version", "99.99.99"),
            ("boto3_version", "99.99.99"),
            ("botocore_version", "99.99.99"),
            ("max_tokens", 4096),
            ("temperature", 0.7),
            ("connect_timeout_seconds", 10.0),
            ("read_timeout_seconds", 60.0),
            ("total_max_attempts", 3),
            ("retry_mode", "adaptive"),
            ("streaming", True),
            ("strands_sdk_retries", True),
            ("turns_limit", 2),
            ("tool_names", ("injected_tool",)),
        ],
    )
    def test_changing_any_of_18_metadata_fields_changes_real_evidence_record_id(
        self,
        mission_id: MissionId,
        action_id: ActionId,
        origin: EvidenceOrigin,
        base_payload: dict[str, Any],
        base_meta: PlannerRuntimeMetadata,
        field: str,
        modified_value: Any,
    ) -> None:
        """Prove that each of the 18 serialized metadata fields produces a distinct
        EvidenceRecord.evidence_id.

        Uses REAL EvidenceRecord.create(...) instances with identical caller mission/action/origin.
        Crucially, EXACTLY ONE field is varied; no companion or coupled fields are modified.
        """
        # 1. Base bound payload and record
        bound_base = bind_planner_runtime_metadata(base_payload, base_meta)
        base_record = EvidenceRecord.create(
            action_id=action_id,
            mission_id=mission_id,
            origin=origin,
            payload=bound_base,
        )

        # 2. Synthetic modified metadata - exactly ONE field modified
        kwargs = base_meta.to_dict()
        kwargs[field] = modified_value

        modified_meta = PlannerRuntimeMetadata(**kwargs)

        # 3. Modified bound payload and record
        bound_modified = bind_planner_runtime_metadata(base_payload, modified_meta)
        modified_record = EvidenceRecord.create(
            action_id=action_id,
            mission_id=mission_id,
            origin=origin,
            payload=bound_modified,
        )

        # 4. Assert EvidenceRecord.evidence_id strictly differs
        assert base_record.evidence_id != modified_record.evidence_id, (
            f"EvidenceRecord.evidence_id did NOT change when field {field!r} was changed "
            f"from {getattr(base_meta, field)!r} to {modified_value!r}"
        )
        assert base_record.origin == origin
        assert modified_record.origin == origin
        assert base_record.origin.provenance.value == "LOCAL_EXECUTION"
        assert modified_record.origin.provenance.value == "LOCAL_EXECUTION"


# ===========================================================================
# Zero Network Assertion
# ===========================================================================


class TestZeroNetworkInMetadata:
    """Verifies that no network calls are attempted during metadata operations."""

    def test_metadata_creation_and_binding_makes_zero_network_calls(self) -> None:
        import socket

        with patch.object(socket, "socket", side_effect=RuntimeError("Network attempted!")):
            meta = create_planner_runtime_metadata()
            payload = {"action": "calendar.read", "target": "calendar_event"}
            bound = bind_planner_runtime_metadata(payload, meta)
            eid = compute_evidence_id(bound)

            assert isinstance(eid, EvidenceId)
            assert len(str(eid)) == 64
