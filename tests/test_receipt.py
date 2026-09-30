"""Focused tests for receipt projections bound to exact mission/evidence hashes (P-03.05)."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from stilldone.application.ports.ledger_port import CanonicalPayload, EvidenceRecord
from stilldone.domain.action import ActionId
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.receipt import (
    DuplicateEvidenceBindingError,
    EvidenceOrderError,
    MalformedHashError,
    MissionContentHash,
    ReceiptHash,
    ReceiptHashMismatchError,
    ReceiptMismatchError,
    ReceiptProjection,
    compute_mission_content_hash,
    compute_receipt_hash,
    validate_evidence_records_for_mission,
)


def _make_mission_contract(
    mission_id: MissionId | None = None, text: str = "Test task"
) -> MissionContract:
    mid = mission_id or MissionId(str(uuid.uuid4()))
    intent = UserIntentSnapshot(
        mission_id=mid,
        text=text,
        captured_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
    )
    return MissionContract(
        mission_id=mid,
        intent=intent,
        created_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _make_evidence_record(
    mission_id: MissionId,
    action_id: ActionId | None = None,
    payload: dict[str, Any] | None = None,
) -> EvidenceRecord:
    aid = action_id or ActionId(str(uuid.uuid4()))
    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
        observed_at=datetime(2026, 9, 30, 10, 1, 0, tzinfo=UTC),
    )
    return EvidenceRecord.create(
        action_id=aid,
        mission_id=mission_id,
        origin=origin,
        payload=payload or {"status": "ok"},
        created_at=datetime(2026, 9, 30, 10, 1, 0, tzinfo=UTC),
    )


def test_mission_content_hash_deterministic_and_domain_separated() -> None:
    """MissionContentHash produces deterministic 64-char lowercase hex hash bound to MissionId."""
    mid1 = MissionId("11111111-1111-4111-8111-111111111111")
    mid2 = MissionId("22222222-2222-4222-8222-222222222222")
    mc1 = _make_mission_contract(mid1)
    mc2 = _make_mission_contract(mid1)
    mc3 = _make_mission_contract(mid2)

    h1 = compute_mission_content_hash(mc1)
    h2 = compute_mission_content_hash(mc2)
    h3 = compute_mission_content_hash(mc3)

    assert h1 == h2
    assert h1.value == h2.value
    assert len(h1.value) == 64
    assert h1.mission_id == mid1
    assert h3.mission_id == mid2
    assert h1 != h3

    # Does not collide with EvidenceId semantics for the same dict
    eid = compute_evidence_id({"content": mc1})
    assert h1.value != eid.value


def test_malformed_hashes_fail_closed() -> None:
    """MissionContentHash and ReceiptHash fail closed on malformed values."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")

    with pytest.raises(MalformedHashError, match="must be exactly 64 characters"):
        MissionContentHash("short", mid)

    with pytest.raises(MalformedHashError, match="must be lowercase hexadecimal"):
        MissionContentHash("A" * 64, mid)

    with pytest.raises(TypeError, match="mission_id must be a MissionId instance"):
        MissionContentHash("a" * 64, "invalid_mid")  # type: ignore[arg-type]

    with pytest.raises(MalformedHashError, match="must be exactly 64 characters"):
        ReceiptHash("too_long" * 10)

    with pytest.raises(MalformedHashError, match="must be lowercase hexadecimal"):
        ReceiptHash("g" * 64)


def test_mission_content_hash_mission_mismatch_fails_closed() -> None:
    """MissionContentHash must match the ReceiptProjection mission_id on all construction paths."""
    mid_a = MissionId("11111111-1111-4111-8111-111111111111")
    mid_b = MissionId("22222222-2222-4222-8222-222222222222")

    mc_a = _make_mission_contract(mid_a, "Task A")
    mc_b = _make_mission_contract(mid_b, "Task B")
    hash_a = compute_mission_content_hash(mc_a)
    hash_b = compute_mission_content_hash(mc_b)

    eid = EvidenceId("1" * 64)

    # 1. ReceiptProjection.create() fails immediately with ReceiptMismatchError
    with pytest.raises(ReceiptMismatchError, match="does not match"):
        ReceiptProjection.create(
            mission_id=mid_a,
            mission_content_hash=hash_b,
            evidence_ids=[eid],
            state_at_projection=MissionState.VERIFYING,
        )

    # 2. Direct constructor fails immediately with ReceiptMismatchError
    dummy_rhash = ReceiptHash("0" * 64)
    with pytest.raises(ReceiptMismatchError, match="does not match"):
        ReceiptProjection(
            mission_id=mid_a,
            mission_content_hash=hash_b,
            evidence_ids=(eid,),
            state_at_projection=MissionState.VERIFYING,
            projected_at=datetime.now(UTC),
            receipt_hash=dummy_rhash,
            metadata=CanonicalPayload({}),
            is_historical=True,
        )

    # 3. from_records() fails immediately with ReceiptMismatchError
    rec_a = _make_evidence_record(mid_a)
    with pytest.raises(ReceiptMismatchError, match="does not match"):
        ReceiptProjection.from_records(
            mission_id=mid_a,
            mission_content_hash=hash_b,
            evidence_records=[rec_a],
            state_at_projection=MissionState.VERIFYING,
        )

    # 4. compute_receipt_hash() fails immediately with ReceiptMismatchError
    with pytest.raises(ReceiptMismatchError, match="does not match"):
        compute_receipt_hash(
            mission_id=mid_a,
            mission_content_hash=hash_b,
            evidence_ids=(eid,),
            state_at_projection=MissionState.VERIFYING,
            projected_at=datetime.now(UTC),
        )

    # 5. Matching mission_id + mission_content_hash succeeds
    valid_receipt = ReceiptProjection.create(
        mission_id=mid_a,
        mission_content_hash=hash_a,
        evidence_ids=[eid],
        state_at_projection=MissionState.VERIFYING,
    )
    assert valid_receipt.mission_id == mid_a
    assert valid_receipt.mission_content_hash == hash_a


def test_same_projection_same_receipt_hash() -> None:
    """Exact same mission and evidence projection yields identical receipt hash."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)

    eid1 = EvidenceId("1" * 64)
    eid2 = EvidenceId("2" * 64)

    proj_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)

    r1 = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[eid2, eid1],  # Unsorted input is canonically sorted
        state_at_projection=MissionState.VERIFYING,
        projected_at=proj_time,
        metadata={"version": "1.0"},
    )
    r2 = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[eid1, eid2],
        state_at_projection=MissionState.VERIFYING,
        projected_at=proj_time,
        metadata={"version": "1.0"},
    )

    assert r1.receipt_hash == r2.receipt_hash
    assert r1.evidence_ids == (eid1, eid2)


def test_material_changes_alter_receipt_hash() -> None:
    """Altering mission hash, evidence IDs, state, or metadata alters receipt hash."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc1 = _make_mission_contract(mid, "Task A")
    mc2 = _make_mission_contract(mid, "Task B")
    mhash1 = compute_mission_content_hash(mc1)
    mhash2 = compute_mission_content_hash(mc2)

    eid1 = EvidenceId("1" * 64)
    eid2 = EvidenceId("2" * 64)
    proj_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)

    base = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash1,
        evidence_ids=[eid1],
        state_at_projection=MissionState.VERIFYING,
        projected_at=proj_time,
    )

    # Different mission content hash (different text on same mission_id)
    diff_mission = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash2,
        evidence_ids=[eid1],
        state_at_projection=MissionState.VERIFYING,
        projected_at=proj_time,
    )
    assert base.receipt_hash != diff_mission.receipt_hash

    # Different evidence IDs
    diff_evidence = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash1,
        evidence_ids=[eid1, eid2],
        state_at_projection=MissionState.VERIFYING,
        projected_at=proj_time,
    )
    assert base.receipt_hash != diff_evidence.receipt_hash

    # Different state at projection
    diff_state = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash1,
        evidence_ids=[eid1],
        state_at_projection=MissionState.PARTIAL,
        projected_at=proj_time,
    )
    assert base.receipt_hash != diff_state.receipt_hash


def test_duplicate_evidence_binding_fails_closed() -> None:
    """Duplicate evidence IDs raise DuplicateEvidenceBindingError."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid = EvidenceId("a" * 64)

    with pytest.raises(DuplicateEvidenceBindingError, match="Duplicate evidence ID"):
        ReceiptProjection.create(
            mission_id=mid,
            mission_content_hash=mhash,
            evidence_ids=[eid, eid],
            state_at_projection=MissionState.VERIFYING,
        )


def test_evidence_order_error_on_direct_construction() -> None:
    """Unsorted evidence IDs on direct constructor fail closed with EvidenceOrderError."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid1 = EvidenceId("1" * 64)
    eid2 = EvidenceId("2" * 64)
    rhash = compute_receipt_hash(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=(eid2, eid1),
        state_at_projection=MissionState.VERIFYING,
        projected_at=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
    )

    with pytest.raises(EvidenceOrderError, match="Evidence IDs are not canonically ordered"):
        ReceiptProjection(
            mission_id=mid,
            mission_content_hash=mhash,
            evidence_ids=(eid2, eid1),  # Unsorted tuple
            state_at_projection=MissionState.VERIFYING,
            projected_at=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
            receipt_hash=rhash,
            metadata=CanonicalPayload({}),
            is_historical=True,
        )


def test_receipt_hash_mismatch_fails_closed() -> None:
    """Tampered or mismatched receipt hash fails closed with ReceiptHashMismatchError."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid = EvidenceId("1" * 64)
    fake_hash = ReceiptHash("f" * 64)

    with pytest.raises(ReceiptHashMismatchError, match="Receipt hash mismatch"):
        ReceiptProjection(
            mission_id=mid,
            mission_content_hash=mhash,
            evidence_ids=(eid,),
            state_at_projection=MissionState.VERIFYING,
            projected_at=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
            receipt_hash=fake_hash,
            metadata=CanonicalPayload({}),
            is_historical=True,
        )


def test_evidence_records_mission_mismatch_fails_closed() -> None:
    """Evidence records belonging to a different mission fail closed with ReceiptMismatchError."""
    mid1 = MissionId("11111111-1111-4111-8111-111111111111")
    mid2 = MissionId("22222222-2222-4222-8222-222222222222")

    rec1 = _make_evidence_record(mid1)
    rec2 = _make_evidence_record(mid2)  # Mismatched mission

    with pytest.raises(ReceiptMismatchError, match="belongs to mission"):
        validate_evidence_records_for_mission(mid1, [rec1, rec2])

    mc1 = _make_mission_contract(mid1)
    mhash1 = compute_mission_content_hash(mc1)
    with pytest.raises(ReceiptMismatchError, match="belongs to mission"):
        ReceiptProjection.from_records(
            mission_id=mid1,
            mission_content_hash=mhash1,
            evidence_records=[rec1, rec2],
            state_at_projection=MissionState.VERIFYING,
        )


def test_receipt_cannot_claim_current_live_truth_or_ready() -> None:
    """Receipt is explicitly historical and cannot claim current-live truth or promote to READY."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)

    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[],
        state_at_projection=MissionState.VERIFYING,
    )

    assert r.is_historical is True
    # Attempting to set is_historical=False fails closed
    with pytest.raises(ValueError, match="is_historical=True"):
        ReceiptProjection(
            mission_id=r.mission_id,
            mission_content_hash=r.mission_content_hash,
            evidence_ids=r.evidence_ids,
            state_at_projection=r.state_at_projection,
            projected_at=r.projected_at,
            receipt_hash=r.receipt_hash,
            metadata=r.metadata,
            is_historical=False,
        )

    # Receipt object does NOT have promotion or ready methods
    assert not hasattr(r, "promote_to_ready")
    assert not hasattr(r, "assert_ready")
    assert not hasattr(r, "is_ready")


def test_receipt_immutability() -> None:
    """ReceiptProjection fields cannot be mutated."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[],
        state_at_projection=MissionState.VERIFYING,
    )

    with pytest.raises(FrozenInstanceError):
        r.state_at_projection = MissionState.READY  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        r.is_historical = False  # type: ignore[misc]


def test_receipt_canonical_projection() -> None:
    """ReceiptProjection projects to a clean canonical JSON-compatible dictionary."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid = EvidenceId("a" * 64)

    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[eid],
        state_at_projection=MissionState.VERIFYING,
        projected_at=datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC),
        metadata={"note": "audit_receipt"},
    )
    proj = r.to_canonical()

    assert proj["mission_id"] == str(mid)
    assert proj["mission_content_hash"] == mhash.value
    assert proj["evidence_ids"] == [eid.value]
    assert proj["state_at_projection"] == "VERIFYING"
    assert proj["projected_at"] == "2026-09-30T12:00:00+00:00"
    assert proj["is_historical"] is True
    assert proj["metadata"] == {"note": "audit_receipt"}
    assert proj["receipt_hash"] == r.receipt_hash.value


def test_receipt_metadata_immutability_and_isolation() -> None:
    """Receipt metadata is deeply isolated and immutable against caller and receiver mutations."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)

    tags_list = ["audit", "verified"]
    nested_dict = {"tags": tags_list, "counter": 42}
    original_meta = {
        "env": "prod",
        "nested": nested_dict,
    }

    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[],
        state_at_projection=MissionState.VERIFYING,
        metadata=original_meta,
    )

    # 1. Top-level caller mutation does not affect receipt
    original_meta["env"] = "tampered"
    assert r.metadata["env"] == "prod"

    # 2. Nested caller dict mutation does not affect receipt
    nested_dict["counter"] = 999
    assert r.metadata["nested"]["counter"] == 42

    # 3. Nested caller list mutation does not affect receipt
    tags_list.append("malicious")
    assert list(r.metadata["nested"]["tags"]) == ["audit", "verified"]

    # 4. Direct mutation on receipt metadata fails closed
    with pytest.raises(TypeError, match="Evidence payload is immutable"):
        r.metadata["new_key"] = "illegal"

    with pytest.raises(TypeError, match="Evidence payload is immutable"):
        r.metadata["nested"]["counter"] = 100

    with pytest.raises(TypeError, match="Evidence payload sequence is immutable"):
        r.metadata["nested"]["tags"].append("illegal")

    with pytest.raises(TypeError, match="Evidence payload is immutable"):
        r.metadata.pop("env")

    # 5. to_canonical() and to_dict() return detached mutable copy
    proj = r.to_dict()
    proj["metadata"]["env"] = "modified_in_projection"
    assert r.metadata["env"] == "prod"


def test_receipt_metadata_post_nfc_collision_fails_closed() -> None:
    """Metadata with post-NFC duplicate key collisions fails closed."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)

    colliding = {"e\u0301": "val1", "\u00e9": "val2"}
    with pytest.raises(ValueError, match="Canonical key collision after Unicode NFC normalization"):
        ReceiptProjection.create(
            mission_id=mid,
            mission_content_hash=mhash,
            evidence_ids=[],
            state_at_projection=MissionState.VERIFYING,
            metadata=colliding,
        )
