"""Tests for Planner Runtime Metadata and Evidence Binding (Phase P-07.05).

Verifies:
- PlannerRuntimeMetadata is an immutable frozen dataclass.
- All 16 required metadata fields are present and strictly typed.
- Package versions are resolved deterministically from installed environment.
- Missing package raises PackageVersionError.
- bind_planner_runtime_metadata creates a new dict under "planner_runtime".
- Original payload is never mutated.
- Key collision on "planner_runtime" raises ReservedKeyCollisionError.
- Changing ANY metadata field changes the computed EvidenceId.
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

from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.planning.metadata import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_ID,
    DEFAULT_READ_TIMEOUT_SECONDS,
    DEFAULT_REGION_NAME,
    DEFAULT_SCHEMA_VERSION,
    DEFAULT_STREAMING,
    DEFAULT_TEMPERATURE,
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

    def test_all_16_required_fields_present_and_correct(
        self, sample_metadata: PlannerRuntimeMetadata
    ) -> None:
        assert sample_metadata.planner_runtime == "strands"
        assert sample_metadata.planner_provider == "amazon_bedrock"
        assert sample_metadata.model_id == "amazon.nova-micro-v1:0"
        assert sample_metadata.region_name == "us-east-1"
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
        assert sample_metadata.tools_count == 0
        assert sample_metadata.turns_limit == 1
        assert sample_metadata.streaming is False
        assert sample_metadata.schema_version == "v1"

    def test_to_dict_contains_all_16_fields(self, sample_metadata: PlannerRuntimeMetadata) -> None:
        d = sample_metadata.to_dict()
        assert isinstance(d, dict)
        expected_keys = {
            "planner_runtime",
            "planner_provider",
            "model_id",
            "region_name",
            "strands_version",
            "boto3_version",
            "botocore_version",
            "max_tokens",
            "temperature",
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "total_max_attempts",
            "tools_count",
            "turns_limit",
            "streaming",
            "schema_version",
        }
        assert set(d.keys()) == expected_keys

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("planner_runtime", 123),
            ("planner_provider", 456),
            ("model_id", None),
            ("region_name", ["us-east-1"]),
            ("strands_version", 1.57),
            ("boto3_version", None),
            ("botocore_version", True),
            ("max_tokens", "2048"),
            ("temperature", "cold"),
            ("connect_timeout_seconds", "5s"),
            ("read_timeout_seconds", None),
            ("total_max_attempts", "1"),
            ("tools_count", "0"),
            ("turns_limit", "1"),
            ("streaming", "false"),
            ("schema_version", 1),
        ],
    )
    def test_field_type_validation_fails_closed(
        self, sample_metadata: PlannerRuntimeMetadata, field: str, bad_value: Any
    ) -> None:
        kwargs = sample_metadata.to_dict()
        kwargs[field] = bad_value
        with pytest.raises(TypeError):
            PlannerRuntimeMetadata(**kwargs)


# ===========================================================================
# Unit Tests: create_planner_runtime_metadata Factory
# ===========================================================================


class TestCreatePlannerRuntimeMetadata:
    """Verifies factory function behavior and defaults."""

    def test_defaults_match_p07_02_constants(self) -> None:
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
        assert meta.tools_count == DEFAULT_TOOLS_COUNT
        assert meta.turns_limit == DEFAULT_TURNS_LIMIT
        assert meta.streaming == DEFAULT_STREAMING

    def test_custom_overrides_respected(self) -> None:
        meta = create_planner_runtime_metadata(
            model_id="custom.model-v1",
            region_name="us-west-2",
            schema_version="v2",
            max_tokens=1024,
            temperature=0.5,
            connect_timeout_seconds=10.0,
            read_timeout_seconds=60.0,
            total_max_attempts=2,
            tools_count=3,
            turns_limit=5,
            streaming=True,
            strands_version="2.0.0",
            boto3_version="1.35.0",
            botocore_version="1.35.0",
        )
        assert meta.model_id == "custom.model-v1"
        assert meta.region_name == "us-west-2"
        assert meta.schema_version == "v2"
        assert meta.max_tokens == 1024
        assert meta.temperature == 0.5
        assert meta.connect_timeout_seconds == 10.0
        assert meta.read_timeout_seconds == 60.0
        assert meta.total_max_attempts == 2
        assert meta.tools_count == 3
        assert meta.turns_limit == 5
        assert meta.streaming is True
        assert meta.strands_version == "2.0.0"
        assert meta.boto3_version == "1.35.0"
        assert meta.botocore_version == "1.35.0"


# ===========================================================================
# Unit Tests: Evidence Binding Surface
# ===========================================================================


class TestBindPlannerRuntimeMetadata:
    """Verifies bind_planner_runtime_metadata immutability and collision rules."""

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
# Deterministic Evidence Hashing Sensitivity: Changing Any Field Changes Hash
# ===========================================================================


class TestEvidenceHashingSensitivity:
    """Proves that changing ANY single field of PlannerRuntimeMetadata produces
    a strictly different EvidenceId / SHA-256 hash.
    """

    @pytest.fixture
    def base_payload(self) -> dict[str, Any]:
        return {"mission_id": "12345678-1234-5678-1234-567812345678", "intent": "morning"}

    @pytest.fixture
    def base_meta(self) -> PlannerRuntimeMetadata:
        return create_planner_runtime_metadata()

    def test_baseline_evidence_id_deterministic(
        self, base_payload: dict[str, Any], base_meta: PlannerRuntimeMetadata
    ) -> None:
        bound1 = bind_planner_runtime_metadata(base_payload, base_meta)
        bound2 = bind_planner_runtime_metadata(base_payload, base_meta)

        eid1 = compute_evidence_id(bound1)
        eid2 = compute_evidence_id(bound2)

        assert isinstance(eid1, EvidenceId)
        assert eid1 == eid2
        assert str(eid1) == str(eid2)

    @pytest.mark.parametrize(
        ("field", "modified_value"),
        [
            ("planner_runtime", "other_runtime"),
            ("planner_provider", "google_vertex"),
            ("model_id", "anthropic.claude-v2"),
            ("region_name", "eu-central-1"),
            ("strands_version", "99.99.99"),
            ("boto3_version", "99.99.99"),
            ("botocore_version", "99.99.99"),
            ("max_tokens", 4096),
            ("temperature", 0.7),
            ("connect_timeout_seconds", 10.0),
            ("read_timeout_seconds", 60.0),
            ("total_max_attempts", 3),
            ("tools_count", 5),
            ("turns_limit", 2),
            ("streaming", True),
            ("schema_version", "v2"),
        ],
    )
    def test_changing_any_metadata_field_changes_evidence_hash(
        self,
        base_payload: dict[str, Any],
        base_meta: PlannerRuntimeMetadata,
        field: str,
        modified_value: Any,
    ) -> None:
        """Prove that each of the 16 metadata fields is bound into the evidence hash."""
        bound_base = bind_planner_runtime_metadata(base_payload, base_meta)
        base_eid = compute_evidence_id(bound_base)

        kwargs = base_meta.to_dict()
        kwargs[field] = modified_value
        modified_meta = PlannerRuntimeMetadata(**kwargs)

        bound_modified = bind_planner_runtime_metadata(base_payload, modified_meta)
        modified_eid = compute_evidence_id(bound_modified)

        assert modified_eid != base_eid, (
            f"EvidenceId did NOT change when field {field!r} was changed "
            f"from {getattr(base_meta, field)!r} to {modified_value!r}"
        )


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
