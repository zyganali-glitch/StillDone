"""Planner runtime metadata contract for StillDone evidence binding.

Phase P-07.05:
Implements a strict immutable metadata contract that binds exact planner
model/runtime/version metadata to evidence payloads.

Architectural invariants:
- Metadata is runtime-owned deterministic truth.
- The model MUST NOT supply or override it.
- Uses importlib.metadata for deterministic installed-package version truth.
- Does NOT fabricate a planner pseudo ActionType or ActionId.
- Does NOT auto-append planner evidence to the ledger.
- The smallest deterministic evidence-binding surface:
  PlannerRuntimeMetadata + bind_planner_runtime_metadata().
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from typing import Any

# ===========================================================================
# Planner Runtime Kind & Provider Vocabulary
# ===========================================================================

PLANNER_RUNTIME_STRANDS: str = "strands"
PLANNER_PROVIDER_AMAZON_BEDROCK: str = "amazon_bedrock"

# Reserved nested payload key for planner runtime metadata
PLANNER_RUNTIME_PAYLOAD_KEY: str = "planner_runtime"

# Canonical defaults matching P-07.02/P-07.03 Bedrock configuration
DEFAULT_MODEL_ID: str = "amazon.nova-micro-v1:0"
DEFAULT_REGION_NAME: str = "us-east-1"
DEFAULT_SCHEMA_VERSION: str = "v1"
DEFAULT_MAX_TOKENS: int = 2048
DEFAULT_TEMPERATURE: float = 0.00001
DEFAULT_CONNECT_TIMEOUT_SECONDS: float = 5.0
DEFAULT_READ_TIMEOUT_SECONDS: float = 30.0
DEFAULT_TOTAL_MAX_ATTEMPTS: int = 1
DEFAULT_TOOLS_COUNT: int = 0
DEFAULT_TURNS_LIMIT: int = 1
DEFAULT_STREAMING: bool = False


# ===========================================================================
# Errors
# ===========================================================================


class PlannerMetadataError(Exception):
    """Base exception for all planner metadata errors."""


class ReservedKeyCollisionError(PlannerMetadataError, ValueError):
    """Raised when caller payload already contains the reserved planner_runtime key."""


class PackageVersionError(PlannerMetadataError, RuntimeError):
    """Raised when installed package version cannot be resolved."""


# ===========================================================================
# Package Version Resolution
# ===========================================================================


def _get_installed_version(package_name: str) -> str:
    """Get the installed version of a Python package using importlib.metadata.

    This is deterministic installed-package truth. The model MUST NOT
    supply or override package versions.

    Raises:
        PackageVersionError: If the package is not installed or version
            cannot be resolved.
    """
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        raise PackageVersionError(f"Required package '{package_name}' is not installed") from None


# ===========================================================================
# Planner Runtime Metadata
# ===========================================================================


@dataclass(frozen=True)
class PlannerRuntimeMetadata:
    """Immutable planner runtime metadata for evidence binding.

    All values are runtime-owned deterministic truth.
    The model MUST NOT supply or override any of these values.

    Required metadata fields (16 exact fields):
    - planner_runtime: "strands"
    - planner_provider: "amazon_bedrock"
    - model_id: "amazon.nova-micro-v1:0"
    - region_name: "us-east-1"
    - strands_version: exact resolved version (e.g. 1.57.2)
    - boto3_version: exact resolved version
    - botocore_version: exact resolved version
    - max_tokens: 2048
    - temperature: 0.00001
    - connect_timeout_seconds: 5.0
    - read_timeout_seconds: 30.0
    - total_max_attempts: 1
    - tools_count: 0
    - turns_limit: 1
    - streaming: false
    - schema_version: "v1"
    """

    planner_runtime: str
    planner_provider: str
    model_id: str
    region_name: str
    strands_version: str
    boto3_version: str
    botocore_version: str
    max_tokens: int
    temperature: float
    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_max_attempts: int
    tools_count: int
    turns_limit: int
    streaming: bool
    schema_version: str

    def __post_init__(self) -> None:
        """Validate metadata field types and invariants."""
        if type(self.planner_runtime) is not str:
            raise TypeError(
                f"planner_runtime must be a str, got {type(self.planner_runtime).__name__}"
            )
        if type(self.planner_provider) is not str:
            raise TypeError(
                f"planner_provider must be a str, got {type(self.planner_provider).__name__}"
            )
        if type(self.model_id) is not str:
            raise TypeError(f"model_id must be a str, got {type(self.model_id).__name__}")
        if type(self.region_name) is not str:
            raise TypeError(f"region_name must be a str, got {type(self.region_name).__name__}")
        if type(self.strands_version) is not str:
            raise TypeError(
                f"strands_version must be a str, got {type(self.strands_version).__name__}"
            )
        if type(self.boto3_version) is not str:
            raise TypeError(f"boto3_version must be a str, got {type(self.boto3_version).__name__}")
        if type(self.botocore_version) is not str:
            raise TypeError(
                f"botocore_version must be a str, got {type(self.botocore_version).__name__}"
            )
        if type(self.max_tokens) is not int:
            raise TypeError(f"max_tokens must be an int, got {type(self.max_tokens).__name__}")
        if not isinstance(self.temperature, (int, float)):
            raise TypeError(f"temperature must be a float, got {type(self.temperature).__name__}")
        if not isinstance(self.connect_timeout_seconds, (int, float)):
            msg = (
                f"connect_timeout_seconds must be a float, "
                f"got {type(self.connect_timeout_seconds).__name__}"
            )
            raise TypeError(msg)
        if not isinstance(self.read_timeout_seconds, (int, float)):
            msg = (
                f"read_timeout_seconds must be a float, "
                f"got {type(self.read_timeout_seconds).__name__}"
            )
            raise TypeError(msg)
        if type(self.total_max_attempts) is not int:
            raise TypeError(
                f"total_max_attempts must be an int, got {type(self.total_max_attempts).__name__}"
            )
        if type(self.tools_count) is not int:
            raise TypeError(f"tools_count must be an int, got {type(self.tools_count).__name__}")
        if type(self.turns_limit) is not int:
            raise TypeError(f"turns_limit must be an int, got {type(self.turns_limit).__name__}")
        if type(self.streaming) is not bool:
            raise TypeError(f"streaming must be a bool, got {type(self.streaming).__name__}")
        if type(self.schema_version) is not str:
            raise TypeError(
                f"schema_version must be a str, got {type(self.schema_version).__name__}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to a deterministic serializable dictionary."""
        return {
            "planner_runtime": self.planner_runtime,
            "planner_provider": self.planner_provider,
            "model_id": self.model_id,
            "region_name": self.region_name,
            "strands_version": self.strands_version,
            "boto3_version": self.boto3_version,
            "botocore_version": self.botocore_version,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "read_timeout_seconds": self.read_timeout_seconds,
            "total_max_attempts": self.total_max_attempts,
            "tools_count": self.tools_count,
            "turns_limit": self.turns_limit,
            "streaming": self.streaming,
            "schema_version": self.schema_version,
        }


def create_planner_runtime_metadata(
    *,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = DEFAULT_REGION_NAME,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
    total_max_attempts: int = DEFAULT_TOTAL_MAX_ATTEMPTS,
    tools_count: int = DEFAULT_TOOLS_COUNT,
    turns_limit: int = DEFAULT_TURNS_LIMIT,
    streaming: bool = DEFAULT_STREAMING,
    strands_version: str | None = None,
    boto3_version: str | None = None,
    botocore_version: str | None = None,
) -> PlannerRuntimeMetadata:
    """Create PlannerRuntimeMetadata with runtime-resolved package versions.

    Package versions are resolved deterministically via importlib.metadata
    unless explicitly supplied (e.g. for testing version variations).
    The model MUST NOT supply or override package versions.
    """
    resolved_strands = (
        strands_version if strands_version is not None else _get_installed_version("strands-agents")
    )
    resolved_boto3 = boto3_version if boto3_version is not None else _get_installed_version("boto3")
    resolved_botocore = (
        botocore_version if botocore_version is not None else _get_installed_version("botocore")
    )

    return PlannerRuntimeMetadata(
        planner_runtime=PLANNER_RUNTIME_STRANDS,
        planner_provider=PLANNER_PROVIDER_AMAZON_BEDROCK,
        model_id=model_id,
        region_name=region_name,
        strands_version=resolved_strands,
        boto3_version=resolved_boto3,
        botocore_version=resolved_botocore,
        max_tokens=max_tokens,
        temperature=temperature,
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
        total_max_attempts=total_max_attempts,
        tools_count=tools_count,
        turns_limit=turns_limit,
        streaming=streaming,
        schema_version=schema_version,
    )


# ===========================================================================
# Evidence Binding Surface
# ===========================================================================


def bind_planner_runtime_metadata(
    payload: dict[str, Any],
    metadata: PlannerRuntimeMetadata,
) -> dict[str, Any]:
    """Bind planner runtime metadata into an evidence payload.

    Creates a new dict with the metadata injected under the reserved
    PLANNER_RUNTIME_PAYLOAD_KEY. The original payload is NOT mutated.

    Fails closed if:
    - payload is not a dict
    - metadata is not a PlannerRuntimeMetadata instance
    - payload already contains the reserved key

    Returns:
        New dict with planner_runtime metadata bound.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload must be a dict, got {type(payload).__name__}")
    if not isinstance(metadata, PlannerRuntimeMetadata):
        raise TypeError(
            f"metadata must be a PlannerRuntimeMetadata instance, got {type(metadata).__name__}"
        )

    if PLANNER_RUNTIME_PAYLOAD_KEY in payload:
        raise ReservedKeyCollisionError(
            f"Payload already contains reserved key {PLANNER_RUNTIME_PAYLOAD_KEY!r}; "
            f"cannot overwrite existing planner runtime metadata"
        )

    # Create a new dict — never mutate the input
    result = dict(payload)
    result[PLANNER_RUNTIME_PAYLOAD_KEY] = metadata.to_dict()
    return result


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL_ID",
    "DEFAULT_READ_TIMEOUT_SECONDS",
    "DEFAULT_REGION_NAME",
    "DEFAULT_SCHEMA_VERSION",
    "DEFAULT_STREAMING",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOOLS_COUNT",
    "DEFAULT_TOTAL_MAX_ATTEMPTS",
    "DEFAULT_TURNS_LIMIT",
    "PLANNER_PROVIDER_AMAZON_BEDROCK",
    "PLANNER_RUNTIME_PAYLOAD_KEY",
    "PLANNER_RUNTIME_STRANDS",
    "PackageVersionError",
    "PlannerMetadataError",
    "PlannerRuntimeMetadata",
    "ReservedKeyCollisionError",
    "bind_planner_runtime_metadata",
    "create_planner_runtime_metadata",
]
