"""Focused unit tests for StillDone EvidenceId and content-addressed hashing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId, compute_evidence_id


def test_evidence_id_validation() -> None:
    """EvidenceId validates 64 lowercase hexadecimal characters."""
    valid_hex = "a" * 64
    eid = EvidenceId(valid_hex)
    assert str(eid) == valid_hex
    assert eid.value == valid_hex
    assert eid.to_canonical() == valid_hex

    # Non-string
    with pytest.raises(TypeError, match="EvidenceId value must be a string"):
        EvidenceId(12345)  # type: ignore[arg-type]

    # Invalid length
    with pytest.raises(ValueError, match="EvidenceId must be exactly 64 hexadecimal characters"):
        EvidenceId("a" * 63)
    with pytest.raises(ValueError, match="EvidenceId must be exactly 64 hexadecimal characters"):
        EvidenceId("a" * 65)

    # Uppercase or non-hex characters
    with pytest.raises(ValueError, match="EvidenceId must be lowercase hexadecimal"):
        EvidenceId("A" * 64)
    with pytest.raises(ValueError, match="EvidenceId must be lowercase hexadecimal"):
        EvidenceId("g" * 64)


def test_identical_content_yields_identical_evidence_id() -> None:
    """Identical content, regardless of dictionary insertion order, yields identical EvidenceId."""
    content_a = {
        "status": "confirmed",
        "event_id": "evt-001",
        "summary": "Pack school lunch",
        "count": 1,
    }
    content_b = {
        "count": 1,
        "summary": "Pack school lunch",
        "event_id": "evt-001",
        "status": "confirmed",
    }

    id_a = compute_evidence_id(content_a)
    id_b = compute_evidence_id(content_b)
    id_c = EvidenceId.compute(content_a)

    assert id_a == id_b == id_c
    assert len(id_a.value) == 64
    assert id_a.value.islower()


def test_changed_content_yields_different_evidence_id() -> None:
    """Any material change to content yields a distinct EvidenceId."""
    base_content = {
        "event_id": "evt-001",
        "status": "confirmed",
    }
    modified_content = {
        "event_id": "evt-001",
        "status": "tentative",
    }
    added_content = {
        "event_id": "evt-001",
        "status": "confirmed",
        "extra": "value",
    }

    id_base = compute_evidence_id(base_content)
    id_mod = compute_evidence_id(modified_content)
    id_add = compute_evidence_id(added_content)

    assert id_base != id_mod
    assert id_base != id_add
    assert id_mod != id_add


def test_domain_separation_changes_evidence_id() -> None:
    """Different domain separators or versions produce distinct EvidenceIds for same content."""
    content = {"status": "ok"}
    id_v1 = compute_evidence_id(content, domain="stilldone:evidence:v1")
    id_v2 = compute_evidence_id(content, domain="stilldone:evidence:v2")
    id_other = compute_evidence_id(content, domain="stilldone:other:v1")

    assert id_v1 != id_v2
    assert id_v1 != id_other
    assert id_v1 == compute_evidence_id(content)  # default is v1

    # Empty domain fails closed
    with pytest.raises(ValueError, match="domain must be a non-empty string"):
        compute_evidence_id(content, domain="")
    with pytest.raises(ValueError, match="domain must be a non-empty string"):
        compute_evidence_id(content, domain="   ")


def test_timestamp_normalization_in_evidence_hashing() -> None:
    """Different timezone representations of the exact same instant produce identical EvidenceId."""
    t1 = datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 30, 13, 0, 0, tzinfo=timezone(timedelta(hours=3)))

    id1 = compute_evidence_id({"timestamp": t1})
    id2 = compute_evidence_id({"timestamp": t2})

    assert id1 == id2


def test_malformed_content_fails_closed() -> None:
    """Malformed or unsupported content passed to compute_evidence_id fails closed."""
    with pytest.raises(TypeError, match="Unsupported type"):
        compute_evidence_id(object())

    with pytest.raises(ValueError, match="Naive datetime is not permitted"):
        compute_evidence_id({"bad_dt": datetime(2026, 9, 30, 10, 0, 0)})

    with pytest.raises(ValueError, match="Non-finite float"):
        compute_evidence_id({"bad_float": float("nan")})


def test_provenance_does_not_promote_result_or_state() -> None:
    """Evidence provenance is strictly origin metadata.

    It does NOT imply result or verification state.
    """
    # Provenance tags describe WHERE evidence came from
    origin_fixture = EvidenceOrigin(
        provenance=EvidenceProvenance.FIXTURE,
        observed_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
    )
    origin_live = EvidenceOrigin(
        provenance=EvidenceProvenance.LIVE_GOOGLE,
        observed_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
    )

    ev_fixture = compute_evidence_id({"origin": origin_fixture, "payload": "sample"})
    ev_live = compute_evidence_id({"origin": origin_live, "payload": "sample"})

    # Content addressed IDs differ because provenance differs
    assert ev_fixture != ev_live

    # Critical invariant: Neither EvidenceId nor EvidenceOrigin has any attribute or method
    # that grants or computes VERIFIED, READY, or PASS.
    assert not hasattr(ev_fixture, "is_verified")
    assert not hasattr(ev_live, "is_ready")
    assert not hasattr(origin_live, "is_verified")
    assert not hasattr(origin_live, "is_ready")

    # In StillDone, step state remains separate:
    # A step with LIVE_GOOGLE evidence may still be EXECUTED_UNVERIFIED, CONTRADICTED, or FAILED.
    # The existence of evidence identity never overrides this separation.
