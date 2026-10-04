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

import copy
import importlib.metadata
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stilldone.planning.bedrock import BedrockPlannerSettings

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
DEFAULT_RETRY_MODE: str = "standard"
DEFAULT_STREAMING: bool = False
DEFAULT_STRANDS_SDK_RETRIES: bool = False
DEFAULT_TURNS_LIMIT: int = 1
DEFAULT_TOOL_NAMES: tuple[str, ...] = ()
DEFAULT_TOOLS_COUNT: int = 0


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

    Required stored metadata fields (18 canonical fields):
    - planner_runtime: "strands"
    - planner_provider: "amazon_bedrock"
    - model_id: "amazon.nova-micro-v1:0"
    - region_name: "us-east-1"
    - schema_version: "v1"
    - strands_version: exact resolved version (e.g. 1.57.2)
    - boto3_version: exact resolved version
    - botocore_version: exact resolved version
    - max_tokens: 2048
    - temperature: 0.00001
    - connect_timeout_seconds: 5.0
    - read_timeout_seconds: 30.0
    - total_max_attempts: 1
    - retry_mode: "standard"
    - streaming: false
    - strands_sdk_retries: false
    - turns_limit: 1
    - tool_names: ()

    Derived read-only properties:
    - tools_count: len(tool_names) (single source of tool-count truth)
    """

    planner_runtime: str
    planner_provider: str
    model_id: str
    region_name: str
    schema_version: str
    strands_version: str
    boto3_version: str
    botocore_version: str
    max_tokens: int
    temperature: float
    connect_timeout_seconds: float
    read_timeout_seconds: float
    total_max_attempts: int
    retry_mode: str
    streaming: bool
    strands_sdk_retries: bool
    turns_limit: int
    tool_names: tuple[str, ...]

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
        if type(self.schema_version) is not str:
            raise TypeError(
                f"schema_version must be a str, got {type(self.schema_version).__name__}"
            )
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
        if type(self.max_tokens) is not int or type(self.max_tokens) is bool:
            raise TypeError(f"max_tokens must be an int, got {type(self.max_tokens).__name__}")
        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")

        if type(self.temperature) not in (float, int) or type(self.temperature) is bool:
            raise TypeError(
                f"temperature must be a float or int, got {type(self.temperature).__name__}"
            )
        if math.isnan(self.temperature) or math.isinf(self.temperature):
            raise ValueError("temperature cannot be NaN or infinity")
        if self.temperature < 0.0:
            raise ValueError(f"temperature cannot be negative, got {self.temperature}")
        if self.temperature > 1.0:
            raise ValueError(f"temperature cannot exceed 1.0, got {self.temperature}")

        if (
            type(self.connect_timeout_seconds) not in (float, int)
            or type(self.connect_timeout_seconds) is bool
        ):
            raise TypeError(
                f"connect_timeout_seconds must be a float or int, "
                f"got {type(self.connect_timeout_seconds).__name__}"
            )
        if math.isnan(self.connect_timeout_seconds) or math.isinf(self.connect_timeout_seconds):
            raise ValueError("connect_timeout_seconds cannot be NaN or infinity")
        if self.connect_timeout_seconds <= 0.0:
            raise ValueError(
                f"connect_timeout_seconds must be positive, got {self.connect_timeout_seconds}"
            )

        if (
            type(self.read_timeout_seconds) not in (float, int)
            or type(self.read_timeout_seconds) is bool
        ):
            raise TypeError(
                f"read_timeout_seconds must be a float or int, "
                f"got {type(self.read_timeout_seconds).__name__}"
            )
        if math.isnan(self.read_timeout_seconds) or math.isinf(self.read_timeout_seconds):
            raise ValueError("read_timeout_seconds cannot be NaN or infinity")
        if self.read_timeout_seconds <= 0.0:
            raise ValueError(
                f"read_timeout_seconds must be positive, got {self.read_timeout_seconds}"
            )

        if type(self.total_max_attempts) is not int or type(self.total_max_attempts) is bool:
            raise TypeError(
                f"total_max_attempts must be an int, got {type(self.total_max_attempts).__name__}"
            )
        if self.total_max_attempts <= 0:
            raise ValueError(f"total_max_attempts must be positive, got {self.total_max_attempts}")

        if type(self.retry_mode) is not str:
            raise TypeError(f"retry_mode must be a str, got {type(self.retry_mode).__name__}")
        if type(self.streaming) is not bool:
            raise TypeError(f"streaming must be a bool, got {type(self.streaming).__name__}")
        if type(self.strands_sdk_retries) is not bool:
            raise TypeError(
                f"strands_sdk_retries must be a bool, got {type(self.strands_sdk_retries).__name__}"
            )
        if type(self.turns_limit) is not int or type(self.turns_limit) is bool:
            raise TypeError(f"turns_limit must be an int, got {type(self.turns_limit).__name__}")
        if self.turns_limit <= 0:
            raise ValueError(f"turns_limit must be positive, got {self.turns_limit}")

        if not isinstance(self.tool_names, (list, tuple)):
            raise TypeError(
                f"tool_names must be a tuple of str, got {type(self.tool_names).__name__}"
            )
        for tn in self.tool_names:
            if not isinstance(tn, str):
                raise TypeError(f"tool_names items must be str, got {type(tn).__name__}")
        # Normalize tool_names to tuple
        if isinstance(self.tool_names, list):
            object.__setattr__(self, "tool_names", tuple(self.tool_names))

    @property
    def tools_count(self) -> int:
        """Derived tool count matching len(tool_names); single source of truth."""
        return len(self.tool_names)

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to a deterministic serializable dictionary."""
        return {
            "planner_runtime": self.planner_runtime,
            "planner_provider": self.planner_provider,
            "model_id": self.model_id,
            "region_name": self.region_name,
            "schema_version": self.schema_version,
            "strands_version": self.strands_version,
            "boto3_version": self.boto3_version,
            "botocore_version": self.botocore_version,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "read_timeout_seconds": self.read_timeout_seconds,
            "total_max_attempts": self.total_max_attempts,
            "retry_mode": self.retry_mode,
            "streaming": self.streaming,
            "strands_sdk_retries": self.strands_sdk_retries,
            "turns_limit": self.turns_limit,
            "tool_names": list(self.tool_names),
        }


def create_planner_runtime_metadata(
    settings: BedrockPlannerSettings | None = None,
) -> PlannerRuntimeMetadata:
    """Create PlannerRuntimeMetadata from runtime-owned settings and installed versions.

    Derives strictly from validated BedrockPlannerSettings and installed package versions.
    Production version truth comes ONLY from importlib.metadata.
    The model MUST NOT supply or override metadata.
    """
    from stilldone.planning.bedrock import BedrockPlannerSettings

    cfg = settings if settings is not None else BedrockPlannerSettings()
    if not isinstance(cfg, BedrockPlannerSettings):
        raise TypeError(f"settings must be BedrockPlannerSettings, got {type(cfg).__name__}")

    resolved_strands = _get_installed_version("strands-agents")
    resolved_boto3 = _get_installed_version("boto3")
    resolved_botocore = _get_installed_version("botocore")

    return PlannerRuntimeMetadata(
        planner_runtime=PLANNER_RUNTIME_STRANDS,
        planner_provider=PLANNER_PROVIDER_AMAZON_BEDROCK,
        model_id=cfg.model_id,
        region_name=cfg.region_name,
        schema_version=DEFAULT_SCHEMA_VERSION,
        strands_version=resolved_strands,
        boto3_version=resolved_boto3,
        botocore_version=resolved_botocore,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        connect_timeout_seconds=cfg.connect_timeout,
        read_timeout_seconds=cfg.read_timeout,
        total_max_attempts=cfg.total_max_attempts,
        retry_mode=cfg.retry_mode,
        streaming=False,
        strands_sdk_retries=False,
        turns_limit=1,
        tool_names=(),
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
    PLANNER_RUNTIME_PAYLOAD_KEY. The original payload is deeply isolated and NOT mutated.

    Fails closed if:
    - payload is not a dict
    - metadata is not a PlannerRuntimeMetadata instance
    - payload already contains the reserved key

    Returns:
        New deep-detached dict with planner_runtime metadata bound.
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

    # Deep-detach bound payload
    result = copy.deepcopy(payload)
    result[PLANNER_RUNTIME_PAYLOAD_KEY] = metadata.to_dict()
    return result


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL_ID",
    "DEFAULT_READ_TIMEOUT_SECONDS",
    "DEFAULT_REGION_NAME",
    "DEFAULT_RETRY_MODE",
    "DEFAULT_SCHEMA_VERSION",
    "DEFAULT_STRANDS_SDK_RETRIES",
    "DEFAULT_STREAMING",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOOLS_COUNT",
    "DEFAULT_TOOL_NAMES",
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
