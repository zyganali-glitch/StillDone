"""Focused tests for bounded sanitized provider-output capture and digests (P-03.04)."""

from __future__ import annotations

from typing import Any

import pytest

from stilldone.application.ports.ledger_port import CanonicalPayload, CanonicalSequence
from stilldone.capture import (
    CAPTURE_DIGEST_DOMAIN_SEPARATOR,
    CaptureBoundExceededError,
    CaptureBounds,
    CaptureDigest,
    SanitizedProviderCapture,
    UnsupportedProviderOutputError,
    capture_provider_output,
    compute_capture_digest,
)


def test_stable_identical_capture_and_digest() -> None:
    """Stable identical inputs produce identical sanitized capture and digest."""
    data = {
        "status": "confirmed",
        "items": [1, 2, 3],
        "meta": {"source": "test_provider", "count": 3},
    }
    cap1 = capture_provider_output(data)
    cap2 = capture_provider_output(data)

    assert cap1.digest == cap2.digest
    assert cap1.digest.value == cap2.digest.value
    assert len(cap1.digest.value) == 64
    assert cap1.is_truncated is False
    assert cap1.truncation_reasons == ()
    assert cap1.payload == cap2.payload


def test_material_change_changes_digest() -> None:
    """Any material change to payload or metadata alters the capture digest."""
    data1 = {"id": "res_123", "value": 42}
    data2 = {"id": "res_123", "value": 43}

    cap1 = capture_provider_output(data1)
    cap2 = capture_provider_output(data2)

    assert cap1.digest != cap2.digest


def test_unsupported_objects_fail_closed() -> None:
    """Arbitrary classes, exceptions, callables, iterators, and sets fail closed."""

    class ArbitrarySDKResponse:
        def __init__(self) -> None:
            self.secret = "xyz"

    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output(ArbitrarySDKResponse())

    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output(RuntimeError("SDK connection dropped"))

    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output(lambda x: x)

    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output(iter([1, 2, 3]))

    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output({1, 2, 3})

    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output(b"binary_payload")


def test_mapping_keys_must_be_strings() -> None:
    """Mappings with non-string keys fail closed."""
    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output({1: "integer_key"})


def test_deterministic_bounds_construction() -> None:
    """CaptureBounds validates positive integer bounds."""
    bounds = CaptureBounds(
        max_depth=5,
        max_mapping_entries=10,
        max_sequence_items=10,
        max_string_length=100,
        max_total_bytes=1024,
    )
    assert bounds.max_depth == 5
    assert bounds.max_string_length == 100

    with pytest.raises(ValueError, match="max_depth must be a positive integer"):
        CaptureBounds(max_depth=0)

    with pytest.raises(ValueError, match="max_string_length must be a positive integer"):
        CaptureBounds(max_string_length=-5)


def test_oversized_string_truncation_and_fail_closed() -> None:
    """Oversized strings truncate deterministically or fail closed based on policy."""
    long_str = "A" * 50
    bounds = CaptureBounds(max_string_length=20)

    # Truncation mode
    cap = capture_provider_output({"text": long_str}, bounds=bounds, fail_closed=False)
    assert cap.is_truncated is True
    assert "max_string_length_exceeded" in cap.truncation_reasons
    assert cap.payload["text"] == "A" * 20

    # Fail closed mode
    with pytest.raises(
        CaptureBoundExceededError, match="String length 50 exceeds max_string_length"
    ):
        capture_provider_output({"text": long_str}, bounds=bounds, fail_closed=True)


def test_oversized_sequence_truncation_and_fail_closed() -> None:
    """Oversized sequences truncate deterministically or fail closed."""
    seq = list(range(20))
    bounds = CaptureBounds(max_sequence_items=5)

    # Truncate mode
    cap = capture_provider_output(seq, bounds=bounds, fail_closed=False)
    assert cap.is_truncated is True
    assert "max_sequence_items_exceeded" in cap.truncation_reasons
    assert len(cap.payload) == 5
    assert list(cap.payload) == [0, 1, 2, 3, 4]

    # Fail closed mode
    with pytest.raises(CaptureBoundExceededError, match="Sequence items count 20 exceeds"):
        capture_provider_output(seq, bounds=bounds, fail_closed=True)


def test_oversized_mapping_truncation_and_fail_closed() -> None:
    """Oversized mappings truncate deterministically by lexicographical keys or fail closed."""
    mapping = {f"key_{i:02d}": i for i in range(10)}
    bounds = CaptureBounds(max_mapping_entries=3)

    # Truncate mode
    cap = capture_provider_output(mapping, bounds=bounds, fail_closed=False)
    assert cap.is_truncated is True
    assert "max_mapping_entries_exceeded" in cap.truncation_reasons
    assert len(cap.payload) == 3
    # Lexicographically sorted first 3 keys: key_00, key_01, key_02
    assert list(cap.payload.keys()) == ["key_00", "key_01", "key_02"]

    # Fail closed mode
    with pytest.raises(CaptureBoundExceededError, match="Mapping entries count 10 exceeds"):
        capture_provider_output(mapping, bounds=bounds, fail_closed=True)


def test_nested_depth_boundary_and_fail_closed() -> None:
    """Nesting depth boundary halts recursion or fails closed."""
    # Depth: dict(1) -> dict(2) -> dict(3) -> dict(4)
    deep_data: dict[str, Any] = {"lvl1": {"lvl2": {"lvl3": {"lvl4": "val"}}}}
    bounds = CaptureBounds(max_depth=3)

    # Truncate mode
    cap = capture_provider_output(deep_data, bounds=bounds, fail_closed=False)
    assert cap.is_truncated is True
    assert "max_depth_exceeded" in cap.truncation_reasons
    assert cap.payload["lvl1"]["lvl2"]["lvl3"] == "[TRUNCATED:MAX_DEPTH]"

    # Fail closed mode
    with pytest.raises(CaptureBoundExceededError, match="Nesting depth 4 exceeds max_depth 3"):
        capture_provider_output(deep_data, bounds=bounds, fail_closed=True)


def test_max_total_bytes_always_fails_closed() -> None:
    """Total serialized capture size limit fails closed even in truncation mode."""
    data = {"k": "1234567890"}
    bounds = CaptureBounds(max_total_bytes=10)

    with pytest.raises(CaptureBoundExceededError, match="Total serialized capture size"):
        capture_provider_output(data, bounds=bounds, fail_closed=False)


def test_no_repr_or_memory_address_leakage() -> None:
    """Sanitized capture never leaks memory addresses or class reprs."""

    class DummyProviderObject:
        def __repr__(self) -> str:
            return "<DummyProviderObject at 0x7fffbeef1234>"

    obj = DummyProviderObject()
    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output(obj)

    # When wrapping in a dict
    with pytest.raises(UnsupportedProviderOutputError):
        capture_provider_output({"response": obj})


def test_digest_does_not_imply_verified_ready_pass() -> None:
    """Digest and capture objects do not carry or imply VERIFIED, READY, or PASS states."""
    cap = capture_provider_output({"result": "mutation_success", "records": 5})

    assert isinstance(cap.digest, CaptureDigest)
    assert not hasattr(cap, "is_verified")
    assert not hasattr(cap, "is_ready")
    assert not hasattr(cap, "state")
    assert not hasattr(cap.digest, "is_verified")
    assert not hasattr(cap.digest, "is_ready")
    assert not hasattr(cap.digest, "state")

    # Projection dict does not have status/readiness flags
    proj = cap.to_dict()
    assert "is_verified" not in proj
    assert "is_ready" not in proj
    assert "status" not in proj


def test_payload_immutability_and_caller_isolation() -> None:
    """Captured payload is defensively isolated and immutable against caller mutation."""
    original_dict = {"status": "ok", "items": [10, 20]}
    cap = capture_provider_output(original_dict)

    # Mutating original dict must not affect capture
    original_dict["status"] = "mutated"
    assert cap.payload["status"] == "ok"

    # Attempting to mutate capture payload fails closed
    assert isinstance(cap.payload, CanonicalPayload)
    with pytest.raises(TypeError, match="Evidence payload is immutable"):
        cap.payload["status"] = "tampered"

    assert isinstance(cap.payload["items"], CanonicalSequence)
    with pytest.raises(TypeError, match="Evidence payload sequence is immutable"):
        cap.payload["items"].append(30)


def test_digest_tamper_detection() -> None:
    """Tampering with bound CaptureDigest raises ValueError in post_init."""
    valid_cap = capture_provider_output({"a": 1})
    tampered_digest = CaptureDigest("0" * 64)

    with pytest.raises(ValueError, match="Capture digest mismatch"):
        SanitizedProviderCapture(
            payload=valid_cap.payload,
            digest=tampered_digest,
            is_truncated=valid_cap.is_truncated,
            truncation_reasons=valid_cap.truncation_reasons,
            bounds=valid_cap.bounds,
        )


def test_digest_binds_truncation_state() -> None:
    """Same payload under different truncation states or bounds has distinct digests."""
    bounds = CaptureBounds(max_sequence_items=2)
    cap = capture_provider_output([1, 2, 3], bounds=bounds, fail_closed=False)
    assert cap.is_truncated is True

    # Untruncated capture with identical payload
    bounds2 = CaptureBounds(max_sequence_items=5)
    cap2 = capture_provider_output([1, 2], bounds=bounds2, fail_closed=False)
    assert cap2.is_truncated is False

    # Payloads are identical ([1, 2]) but truncation state and bounds differ
    assert cap.payload == cap2.payload
    assert cap.digest != cap2.digest


def test_domain_separation_in_digest() -> None:
    """Alternative domain separators alter digest."""
    bounds = CaptureBounds()
    d1 = compute_capture_digest(
        payload={"a": 1},
        is_truncated=False,
        truncation_reasons=(),
        bounds=bounds,
        domain=CAPTURE_DIGEST_DOMAIN_SEPARATOR,
    )
    d2 = compute_capture_digest(
        payload={"a": 1},
        is_truncated=False,
        truncation_reasons=(),
        bounds=bounds,
        domain="stilldone:alternate-domain:v1",
    )
    assert d1 != d2
