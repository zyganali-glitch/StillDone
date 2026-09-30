"""Bounded sanitized provider-output capture primitive for StillDone.

Provides deterministic, provider-neutral structural sanitization and content digests
for tool and provider outputs before evidence handling.
Strictly enforces structural bounds, isolates output from runtime memory addresses/reprs,
and binds the stored capture to a domain-separated SHA-256 CaptureDigest.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from stilldone.application.ports.ledger_port import (
    CanonicalPayload,
    CanonicalSequence,
)
from stilldone.redaction import (
    UnsupportedRedactionTypeError,
    redact,
)
from stilldone.serialization import (
    canonical_serialize,
    normalize_datetime,
    to_canonical_primitive,
)

CAPTURE_DIGEST_DOMAIN_SEPARATOR: str = "stilldone:provider-capture:v1"

DEFAULT_MAX_DEPTH: int = 16
DEFAULT_MAX_MAPPING_ENTRIES: int = 256
DEFAULT_MAX_SEQUENCE_ITEMS: int = 256
DEFAULT_MAX_STRING_LENGTH: int = 4096
DEFAULT_MAX_TOTAL_BYTES: int = 65536


class CaptureError(Exception):
    """Base exception for provider output capture errors."""


class UnsupportedProviderOutputError(CaptureError, UnsupportedRedactionTypeError):
    """Raised when an unsupported provider output object is encountered."""


class CaptureBoundExceededError(CaptureError):
    """Raised when a capture bound is exceeded in fail-closed mode or total bytes limit."""


@dataclass(frozen=True)
class CaptureBounds:
    """Explicit deterministic structural limits for provider output capture."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_mapping_entries: int = DEFAULT_MAX_MAPPING_ENTRIES
    max_sequence_items: int = DEFAULT_MAX_SEQUENCE_ITEMS
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES

    def __post_init__(self) -> None:
        for field_name in (
            "max_depth",
            "max_mapping_entries",
            "max_sequence_items",
            "max_string_length",
            "max_total_bytes",
        ):
            val = getattr(self, field_name)
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise ValueError(f"{field_name} must be a positive integer, got {val!r}")


DEFAULT_CAPTURE_BOUNDS = CaptureBounds()


@dataclass(frozen=True)
class CaptureDigest:
    """Immutable content-addressed digest for bounded sanitized provider capture.

    Backed by a 64-character lowercase hexadecimal SHA-256 digest with domain separation.
    NOTE: CaptureDigest is strictly a content hash of the sanitized stored capture.
    It does NOT assert that the provider execution succeeded, that evidence is verified,
    or that a mission is ready/passing.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError(f"CaptureDigest value must be a str, got {type(self.value).__name__}")
        if len(self.value) != 64:
            raise ValueError(f"CaptureDigest must be exactly 64 characters, got {len(self.value)}")
        for char in self.value:
            if char not in "0123456789abcdef":
                raise ValueError(f"CaptureDigest must be lowercase hexadecimal: {self.value!r}")

    def to_canonical(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


def compute_capture_digest(
    *,
    payload: Any,
    is_truncated: bool,
    truncation_reasons: tuple[str, ...],
    bounds: CaptureBounds,
    domain: str = CAPTURE_DIGEST_DOMAIN_SEPARATOR,
) -> CaptureDigest:
    """Compute a deterministic SHA-256 digest binding the stored sanitized capture.

    Binds:
    - Domain separator / version string (default: 'stilldone:provider-capture:v1')
    - Canonical serialized payload
    - Truncation flag (is_truncated)
    - Sorted truncation reasons
    - Applied bounds

    If capture is truncated, this digest binds the exact stored truncated representation
    and explicitly does NOT represent the original untruncated provider response.
    """
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain must be a non-empty string")
    if not isinstance(bounds, CaptureBounds):
        raise TypeError(f"bounds must be CaptureBounds, got {type(bounds).__name__}")

    envelope: dict[str, Any] = {
        "_domain": domain,
        "bounds": {
            "max_depth": bounds.max_depth,
            "max_mapping_entries": bounds.max_mapping_entries,
            "max_sequence_items": bounds.max_sequence_items,
            "max_string_length": bounds.max_string_length,
            "max_total_bytes": bounds.max_total_bytes,
        },
        "is_truncated": is_truncated,
        "payload": to_canonical_primitive(payload),
        "truncation_reasons": sorted(truncation_reasons),
    }
    serialized_bytes = canonical_serialize(envelope)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
    return CaptureDigest(digest)


@dataclass(frozen=True)
class SanitizedProviderCapture:
    """Immutable, detached, bounded sanitized representation of provider output.

    Guarantees:
    - Payload is strictly JSON-compatible canonical primitive structure.
    - Deeply isolated: no raw provider objects, memory addresses, or reprs retained.
    - Mappings and sequences in payload are defensively frozen.
    - Contains explicit truncation metadata if any bound was exceeded.
    - Strongly typed CaptureDigest binds exact stored payload, truncation, and bounds.
    - Does NOT contain or imply VERIFIED, READY, or PASS semantics.
    """

    payload: Any
    digest: CaptureDigest
    is_truncated: bool
    truncation_reasons: tuple[str, ...]
    bounds: CaptureBounds

    def __post_init__(self) -> None:
        if not isinstance(self.digest, CaptureDigest):
            raise TypeError(f"digest must be CaptureDigest, got {type(self.digest).__name__}")
        if not isinstance(self.is_truncated, bool):
            raise TypeError(f"is_truncated must be a bool, got {type(self.is_truncated).__name__}")
        if not isinstance(self.truncation_reasons, tuple):
            raise TypeError(
                f"truncation_reasons must be a tuple, got {type(self.truncation_reasons).__name__}"
            )
        for r in self.truncation_reasons:
            if not isinstance(r, str):
                raise TypeError(f"truncation reasons must be strings, got {type(r).__name__}")
        if not isinstance(self.bounds, CaptureBounds):
            raise TypeError(f"bounds must be CaptureBounds, got {type(self.bounds).__name__}")

        if self.is_truncated != (len(self.truncation_reasons) > 0):
            raise ValueError(
                f"is_truncated={self.is_truncated} inconsistent with "
                f"truncation_reasons={self.truncation_reasons}"
            )

        if self.truncation_reasons != tuple(sorted(set(self.truncation_reasons))):
            raise ValueError(
                f"truncation_reasons must be deduplicated and sorted: {self.truncation_reasons}"
            )

        # Ensure payload is deep-frozen and detached
        frozen_payload = _freeze_value_recursive(self.payload)
        object.__setattr__(self, "payload", frozen_payload)

        # Check total serialized payload bytes
        serialized = canonical_serialize(self.payload)
        if len(serialized) > self.bounds.max_total_bytes:
            raise CaptureBoundExceededError(
                f"Total serialized payload size {len(serialized)} bytes exceeds "
                f"max_total_bytes {self.bounds.max_total_bytes}"
            )

        # Invariant: bound digest must match computed digest
        expected_digest = compute_capture_digest(
            payload=self.payload,
            is_truncated=self.is_truncated,
            truncation_reasons=self.truncation_reasons,
            bounds=self.bounds,
        )
        if self.digest != expected_digest:
            raise ValueError(
                f"Capture digest mismatch: bound {self.digest} != computed {expected_digest}"
            )

    def to_canonical(self) -> dict[str, Any]:
        """Return canonical JSON-compatible projection of the capture."""
        return {
            "bounds": {
                "max_depth": self.bounds.max_depth,
                "max_mapping_entries": self.bounds.max_mapping_entries,
                "max_sequence_items": self.bounds.max_sequence_items,
                "max_string_length": self.bounds.max_string_length,
                "max_total_bytes": self.bounds.max_total_bytes,
            },
            "digest": self.digest.to_canonical(),
            "is_truncated": self.is_truncated,
            "payload": to_canonical_primitive(self.payload),
            "truncation_reasons": list(self.truncation_reasons),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_canonical()


def _freeze_value_recursive(obj: Any) -> Any:
    """Recursively freeze dictionaries to CanonicalPayload and sequences to CanonicalSequence."""
    if isinstance(obj, dict):
        return CanonicalPayload({k: _freeze_value_recursive(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return CanonicalSequence([_freeze_value_recursive(v) for v in obj])
    return obj


def _sanitize_node(
    val: Any,
    *,
    depth: int,
    bounds: CaptureBounds,
    fail_closed: bool,
    reasons: set[str],
) -> Any:
    """Recursively sanitize a single node while enforcing structural bounds."""
    # 1. Depth boundary check
    if depth > bounds.max_depth:
        if fail_closed:
            raise CaptureBoundExceededError(
                f"Nesting depth {depth} exceeds max_depth {bounds.max_depth}"
            )
        reasons.add("max_depth_exceeded")
        return "[TRUNCATED:MAX_DEPTH]"

    # 2. Explicitly forbidden/unsupported types fail closed
    if isinstance(val, type):
        raise UnsupportedProviderOutputError("Type objects cannot be captured as provider output")
    if isinstance(val, BaseException):
        raise UnsupportedProviderOutputError(
            f"Exception objects ({type(val).__name__}) cannot be captured as provider output"
        )
    if callable(val):
        raise UnsupportedProviderOutputError(
            f"Callables ({type(val).__name__}) cannot be captured as provider output"
        )
    if isinstance(val, (bytes, bytearray, memoryview)):
        raise UnsupportedProviderOutputError(
            f"Binary data ({type(val).__name__}) is not supported in canonical provider capture"
        )
    if isinstance(val, (set, frozenset)):
        raise UnsupportedProviderOutputError(
            f"Unordered sets ({type(val).__name__}) are not supported in canonical provider capture"
        )
    if hasattr(val, "__next__") and not isinstance(val, (str, list, tuple, dict)):
        raise UnsupportedProviderOutputError(
            f"Iterators and generators ({type(val).__name__}) cannot be captured as provider output"
        )

    # 3. Scalar primitives
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if not math.isfinite(val):
            raise UnsupportedProviderOutputError(f"Non-finite float is not permitted: {val!r}")
        return 0.0 if val == 0.0 else val

    # 4. Strings
    if isinstance(val, str):
        norm_s = unicodedata.normalize("NFC", val)
        if len(norm_s) > bounds.max_string_length:
            if fail_closed:
                raise CaptureBoundExceededError(
                    f"String length {len(norm_s)} exceeds max_string_length "
                    f"{bounds.max_string_length}"
                )
            reasons.add("max_string_length_exceeded")
            return norm_s[: bounds.max_string_length]
        return norm_s

    # 5. Temporal and domain primitives
    if isinstance(val, datetime):
        iso_str = normalize_datetime(val)
        if len(iso_str) > bounds.max_string_length:
            if fail_closed:
                raise CaptureBoundExceededError(
                    "Normalized datetime string exceeds max_string_length"
                )
            reasons.add("max_string_length_exceeded")
            return iso_str[: bounds.max_string_length]
        return iso_str
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, Enum):
        return _sanitize_node(
            val.value, depth=depth, bounds=bounds, fail_closed=fail_closed, reasons=reasons
        )

    # 6. Dataclasses
    if dataclasses.is_dataclass(val) and not isinstance(val, type):
        fields = dataclasses.fields(val)
        # Check if it is a single-value wrapper dataclass
        if len(fields) == 1 and fields[0].name == "value":
            inner_val = getattr(val, "value", None)
            if isinstance(inner_val, str):
                return _sanitize_node(
                    inner_val, depth=depth, bounds=bounds, fail_closed=fail_closed, reasons=reasons
                )
        dict_rep = {f.name: getattr(val, f.name) for f in sorted(fields, key=lambda f: f.name)}
        return _sanitize_mapping(
            dict_rep, depth=depth, bounds=bounds, fail_closed=fail_closed, reasons=reasons
        )

    # 7. Objects with explicit canonical or dict projection hooks
    if hasattr(val, "to_canonical") and callable(val.to_canonical):
        return _sanitize_node(
            val.to_canonical(),
            depth=depth,
            bounds=bounds,
            fail_closed=fail_closed,
            reasons=reasons,
        )
    if hasattr(val, "to_dict") and callable(val.to_dict):
        return _sanitize_node(
            val.to_dict(), depth=depth, bounds=bounds, fail_closed=fail_closed, reasons=reasons
        )

    # 8. Mappings
    if isinstance(val, Mapping):
        return _sanitize_mapping(
            val, depth=depth, bounds=bounds, fail_closed=fail_closed, reasons=reasons
        )

    # 9. Sequences
    if isinstance(val, Sequence):
        return _sanitize_sequence(
            val, depth=depth, bounds=bounds, fail_closed=fail_closed, reasons=reasons
        )

    # 10. Any other arbitrary object fails closed
    raise UnsupportedProviderOutputError(
        f"Unsupported provider output type: {type(val).__name__} ({type(val).__module__})"
    )


def _sanitize_mapping(
    mapping: Mapping[Any, Any],
    *,
    depth: int,
    bounds: CaptureBounds,
    fail_closed: bool,
    reasons: set[str],
) -> CanonicalPayload:
    """Sanitize and bound mapping entries, sorting keys lexicographically."""
    # Ensure all keys are strings and check for post-NFC duplicate collisions
    normalized_items: list[tuple[str, Any]] = []
    seen_keys: dict[str, str] = {}

    for k, v in mapping.items():
        if not isinstance(k, str):
            raise UnsupportedProviderOutputError(
                f"Mapping keys must be strings for provider output capture, got {type(k).__name__}"
            )
        norm_k = unicodedata.normalize("NFC", k)
        if norm_k in seen_keys:
            orig_k = seen_keys[norm_k]
            raise ValueError(
                f"Canonical key collision after Unicode NFC normalization: {k!r} "
                f"collides with {orig_k!r}"
            )
        seen_keys[norm_k] = k
        normalized_items.append((norm_k, v))

    # Sort keys lexicographically for deterministic ordering
    sorted_items = sorted(normalized_items, key=lambda item: item[0])

    # Check mapping entries bound
    if len(sorted_items) > bounds.max_mapping_entries:
        if fail_closed:
            raise CaptureBoundExceededError(
                f"Mapping entries count {len(sorted_items)} exceeds "
                f"max_mapping_entries {bounds.max_mapping_entries}"
            )
        reasons.add("max_mapping_entries_exceeded")
        selected_items = sorted_items[: bounds.max_mapping_entries]
    else:
        selected_items = sorted_items

    sanitized_dict: dict[str, Any] = {}
    for k, v in selected_items:
        sanitized_dict[k] = _sanitize_node(
            v, depth=depth + 1, bounds=bounds, fail_closed=fail_closed, reasons=reasons
        )

    return CanonicalPayload(sanitized_dict)


def _sanitize_sequence(
    seq: Sequence[Any],
    *,
    depth: int,
    bounds: CaptureBounds,
    fail_closed: bool,
    reasons: set[str],
) -> CanonicalSequence:
    """Sanitize and bound sequence items."""
    if len(seq) > bounds.max_sequence_items:
        if fail_closed:
            raise CaptureBoundExceededError(
                f"Sequence items count {len(seq)} exceeds "
                f"max_sequence_items {bounds.max_sequence_items}"
            )
        reasons.add("max_sequence_items_exceeded")
        selected_items = seq[: bounds.max_sequence_items]
    else:
        selected_items = seq

    sanitized_list: list[Any] = []
    for item in selected_items:
        sanitized_list.append(
            _sanitize_node(
                item, depth=depth + 1, bounds=bounds, fail_closed=fail_closed, reasons=reasons
            )
        )

    return CanonicalSequence(sanitized_list)


def capture_provider_output(
    raw_output: Any,
    bounds: CaptureBounds | None = None,
    *,
    fail_closed: bool = False,
) -> SanitizedProviderCapture:
    """Capture and sanitize raw provider output into a bounded, detached canonical representation.

    Enforces:
    - Detachment: No raw provider objects, memory addresses, or reprs retained.
    - Explicit bounds: max_depth, max_mapping_entries, max_sequence_items,
      max_string_length, max_total_bytes.
    - Bound violation handling: fails closed if fail_closed=True; otherwise truncates
      and records deterministic truncation reasons.
    - Total size limit: always fails closed if serialized payload exceeds max_total_bytes.
    - Cryptographic digest: domain-separated SHA-256 CaptureDigest binding the exact stored payload,
      truncation state, truncation reasons, and bounds.
    """
    effective_bounds = bounds if bounds is not None else DEFAULT_CAPTURE_BOUNDS
    if not isinstance(effective_bounds, CaptureBounds):
        raise TypeError(f"bounds must be CaptureBounds, got {type(effective_bounds).__name__}")

    # P-04.02 Redaction boundary: sensitive material removed before structural capture
    try:
        redacted_raw = redact(raw_output)
    except UnsupportedRedactionTypeError as err:
        raise UnsupportedProviderOutputError(str(err)) from err

    reasons: set[str] = set()

    sanitized_payload = _sanitize_node(
        redacted_raw,
        depth=1,
        bounds=effective_bounds,
        fail_closed=fail_closed,
        reasons=reasons,
    )

    # Freeze payload into immutable canonical structure
    frozen_payload = _freeze_value_recursive(sanitized_payload)

    # Check total serialized payload bytes
    serialized_bytes = canonical_serialize(frozen_payload)
    if len(serialized_bytes) > effective_bounds.max_total_bytes:
        raise CaptureBoundExceededError(
            f"Total serialized capture size {len(serialized_bytes)} bytes exceeds "
            f"max_total_bytes {effective_bounds.max_total_bytes}"
        )

    is_truncated = len(reasons) > 0
    truncation_reasons = tuple(sorted(reasons))

    digest = compute_capture_digest(
        payload=frozen_payload,
        is_truncated=is_truncated,
        truncation_reasons=truncation_reasons,
        bounds=effective_bounds,
    )

    return SanitizedProviderCapture(
        payload=frozen_payload,
        digest=digest,
        is_truncated=is_truncated,
        truncation_reasons=truncation_reasons,
        bounds=effective_bounds,
    )
