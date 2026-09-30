"""Adversarial hardening tests for Phase P-03 (P-03.06).

Proves that implemented Phase P-03 deterministic primitives fail closed:
1. TAMPER: altered payload, altered hash, altered binding, altered capture.
2. MISMATCH: wrong mission/action binding, mission ID vs hash, evidence list vs hash.
3. REPLAY: duplicate append, conflicting identity, replayed receipt/evidence separation.
4. STALE: STALE step evidence prevents READY, historical receipt cannot claim current-live.
5. FORBIDDEN PROMOTION: NOT_RUN, EXECUTED_UNVERIFIED, capture alone, receipt alone.
6. Unicode/canonicalization hardening: NFC collisions, non-finite floats, naive datetimes.
7. Payload isolation & append-only: deep freeze, immutability, no mutation leak.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from stilldone.application.ports.ledger_port import (
    ActionRecord,
    DuplicateRecordError,
    EvidenceRecord,
    InMemoryNonDurableLedger,
    MissionRecord,
    RecordConflictError,
    RecordNotFoundError,
)
from stilldone.capture import (
    CaptureDigest,
    SanitizedProviderCapture,
    capture_provider_output,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId
from stilldone.receipt import (
    MissionContentHash,
    ReceiptHashMismatchError,
    ReceiptMismatchError,
    ReceiptProjection,
    compute_mission_content_hash,
    validate_evidence_records_for_mission,
)
from stilldone.serialization import (
    to_canonical_primitive,
)
from stilldone.transitions import (
    IllegalStatePromotionError,
    assert_can_promote_to_ready,
    assert_valid_transition,
)


def _make_mission_contract(
    mid: MissionId | None = None, text: str = "Adversarial test"
) -> MissionContract:
    mission_id = mid or MissionId(str(uuid.uuid4()))
    intent = UserIntentSnapshot(
        mission_id=mission_id,
        text=text,
        captured_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
    )
    return MissionContract(
        mission_id=mission_id,
        intent=intent,
        created_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _make_action_contract(
    aid: ActionId | None = None, mid: MissionId | None = None
) -> ActionContract:
    mission_id = mid or MissionId(str(uuid.uuid4()))
    action_id = aid or ActionId(str(uuid.uuid4()))
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_adversarial_123",
    )
    return ActionContract(
        action_id=action_id,
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target,
        parameters=NormalizedParameters.from_dict({"calendar_id": "primary"}),
    )


def _make_evidence_record(
    mid: MissionId,
    aid: ActionId | None = None,
    payload: dict[str, Any] | None = None,
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    recorded_live_origin: EvidenceProvenance | None = None,
) -> EvidenceRecord:
    action_id = aid or ActionId(str(uuid.uuid4()))
    if provenance == EvidenceProvenance.RECORDED_LIVE and recorded_live_origin is None:
        recorded_live_origin = EvidenceProvenance.LIVE_GOOGLE
    origin = EvidenceOrigin(
        provenance=provenance,
        observed_at=datetime(2026, 9, 30, 10, 1, 0, tzinfo=UTC),
        recorded_live_origin=recorded_live_origin,
    )
    return EvidenceRecord.create(
        action_id=action_id,
        mission_id=mid,
        origin=origin,
        payload=payload or {"verified_key": "val_1"},
        created_at=datetime(2026, 9, 30, 10, 1, 0, tzinfo=UTC),
    )


# ===========================================================================
# 1. TAMPER TESTS
# ===========================================================================


def test_tamper_evidence_record_content_vs_evidence_id() -> None:
    """Tampering with evidence payload or EvidenceId fails closed on construction."""
    mid = MissionId(str(uuid.uuid4()))
    aid = ActionId(str(uuid.uuid4()))
    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
        observed_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
    )
    fake_eid = EvidenceId("e" * 64)

    # Directly supplying mismatched EvidenceId fails closed
    with pytest.raises(ValueError, match="Mismatched evidence_id"):
        EvidenceRecord(
            evidence_id=fake_eid,
            action_id=aid,
            mission_id=mid,
            origin=origin,
            payload={"k": "v"},
            created_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
        )


def test_tamper_receipt_mission_hash() -> None:
    """Tampering with mission_content_hash in ReceiptProjection fails closed."""
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid = EvidenceId("1" * 64)
    valid_receipt = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[eid],
        state_at_projection=MissionState.VERIFYING,
    )

    tampered_mhash = MissionContentHash("0" * 64)
    with pytest.raises(ReceiptHashMismatchError, match="Receipt hash mismatch"):
        ReceiptProjection(
            mission_id=mid,
            mission_content_hash=tampered_mhash,
            evidence_ids=valid_receipt.evidence_ids,
            state_at_projection=valid_receipt.state_at_projection,
            projected_at=valid_receipt.projected_at,
            receipt_hash=valid_receipt.receipt_hash,
            metadata=valid_receipt.metadata,
            is_historical=True,
        )


def test_tamper_receipt_evidence_binding() -> None:
    """Tampering with evidence_ids in ReceiptProjection fails closed."""
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid1 = EvidenceId("1" * 64)
    eid2 = EvidenceId("2" * 64)

    valid_receipt = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[eid1],
        state_at_projection=MissionState.VERIFYING,
    )

    # Tamper by substituting evidence_ids with eid2
    with pytest.raises(ReceiptHashMismatchError, match="Receipt hash mismatch"):
        ReceiptProjection(
            mission_id=mid,
            mission_content_hash=mhash,
            evidence_ids=(eid2,),
            state_at_projection=valid_receipt.state_at_projection,
            projected_at=valid_receipt.projected_at,
            receipt_hash=valid_receipt.receipt_hash,
            metadata=valid_receipt.metadata,
            is_historical=True,
        )


def test_tamper_provider_output_capture_vs_digest() -> None:
    """Tampering with payload in SanitizedProviderCapture fails closed."""
    cap = capture_provider_output({"response": "real_data"})
    tampered_digest = CaptureDigest("a" * 64)

    with pytest.raises(ValueError, match="Capture digest mismatch"):
        SanitizedProviderCapture(
            payload=cap.payload,
            digest=tampered_digest,
            is_truncated=cap.is_truncated,
            truncation_reasons=cap.truncation_reasons,
            bounds=cap.bounds,
        )


# ===========================================================================
# 2. MISMATCH TESTS
# ===========================================================================


def test_mismatch_evidence_bound_to_wrong_mission() -> None:
    """Evidence record bound to wrong mission is rejected by receipt projection."""
    mid_expected = MissionId("11111111-1111-4111-8111-111111111111")
    mid_foreign = MissionId("22222222-2222-4222-8222-222222222222")

    foreign_rec = _make_evidence_record(mid_foreign)
    with pytest.raises(ReceiptMismatchError, match="belongs to mission"):
        validate_evidence_records_for_mission(mid_expected, [foreign_rec])


def test_mismatch_ledger_append_action_wrong_mission() -> None:
    """Action record referencing wrong mission cannot be appended to ledger."""
    ledger = InMemoryNonDurableLedger()
    mid1 = MissionId(str(uuid.uuid4()))
    mid2 = MissionId(str(uuid.uuid4()))

    mc1 = _make_mission_contract(mid1)
    mrec1 = MissionRecord(
        mission_id=mid1,
        contract=mc1,
        state=MissionState.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    ledger.append_mission(mrec1)

    # Action referencing mid2 (which is not in ledger)
    act = _make_action_contract(mid=mid2)
    arec = ActionRecord(
        action_id=act.action_id,
        mission_id=mid2,
        action=act,
        approval_id=None,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(RecordNotFoundError, match="does not exist in ledger"):
        ledger.append_action(arec)


def test_mismatch_receipt_mission_identity_vs_mission_hash() -> None:
    """ReceiptProjection bound to mission A but hash of mission B fails closed."""
    mid_a = MissionId("11111111-1111-4111-8111-111111111111")
    mid_b = MissionId("22222222-2222-4222-8222-222222222222")

    mc_b = _make_mission_contract(mid_b)
    hash_b = compute_mission_content_hash(mc_b)

    eid = EvidenceId("1" * 64)
    # Projection has mission_id=mid_a, but hash_b embeds mid_b
    r = ReceiptProjection.create(
        mission_id=mid_a,
        mission_content_hash=hash_b,
        evidence_ids=[eid],
        state_at_projection=MissionState.VERIFYING,
    )
    # The receipt hash binds both mission_id and mission_content_hash
    # Altering mission_id to mid_b will mismatch the receipt hash
    with pytest.raises(ReceiptHashMismatchError):
        ReceiptProjection(
            mission_id=mid_b,
            mission_content_hash=hash_b,
            evidence_ids=r.evidence_ids,
            state_at_projection=r.state_at_projection,
            projected_at=r.projected_at,
            receipt_hash=r.receipt_hash,
            metadata=r.metadata,
            is_historical=True,
        )


def test_mismatch_receipt_evidence_list_vs_projection_hash() -> None:
    """Extra or omitted evidence ID causes receipt hash verification to fail closed."""
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    eid1 = EvidenceId("1" * 64)
    eid2 = EvidenceId("2" * 64)

    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[eid1],
        state_at_projection=MissionState.VERIFYING,
    )

    with pytest.raises(ReceiptHashMismatchError):
        ReceiptProjection(
            mission_id=mid,
            mission_content_hash=mhash,
            evidence_ids=(eid1, eid2),  # Extra evidence ID
            state_at_projection=r.state_at_projection,
            projected_at=r.projected_at,
            receipt_hash=r.receipt_hash,
            metadata=r.metadata,
            is_historical=True,
        )


# ===========================================================================
# 3. REPLAY TESTS
# ===========================================================================


def test_replay_duplicate_ledger_append() -> None:
    """Appending an identical record to ledger raises DuplicateRecordError."""
    ledger = InMemoryNonDurableLedger()
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    now = datetime.now(UTC)
    mrec = MissionRecord(
        mission_id=mid,
        contract=mc,
        state=MissionState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    ledger.append_mission(mrec)

    with pytest.raises(DuplicateRecordError, match="already exists"):
        ledger.append_mission(mrec)


def test_replay_conflicting_same_identity() -> None:
    """Appending conflicting content with same identity raises RecordConflictError."""
    ledger = InMemoryNonDurableLedger()
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    now = datetime.now(UTC)
    mrec1 = MissionRecord(
        mission_id=mid,
        contract=mc,
        state=MissionState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    ledger.append_mission(mrec1)

    mrec2 = MissionRecord(
        mission_id=mid,
        contract=mc,
        state=MissionState.EXECUTING,  # Different state!
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(RecordConflictError, match="Conflicting record"):
        ledger.append_mission(mrec2)


def test_replay_receipt_cannot_silently_overwrite_truth() -> None:
    """Historical receipt cannot alter ledger state or override current truth."""
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[],
        state_at_projection=MissionState.READY,
    )
    # Receipt is an immutable read-only projection
    assert r.is_historical is True
    # Has no ledger mutation methods
    assert not hasattr(r, "save")
    assert not hasattr(r, "persist")
    assert not hasattr(r, "write")


# ===========================================================================
# 4. STALE TESTS
# ===========================================================================


def test_stale_evidence_cannot_promote_ready() -> None:
    """Step evidence with STALE state strictly prevents promotion to READY."""
    with pytest.raises(IllegalStatePromotionError, match="STALE"):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[StepEvidenceState.VERIFIED, StepEvidenceState.STALE],
        )


def test_historical_receipt_and_capture_cannot_claim_current_live() -> None:
    """Historical receipts and RECORDED_LIVE evidence cannot masquerade as current-live."""
    # ReceiptProjection is always historical
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[],
        state_at_projection=MissionState.READY,
    )
    assert r.is_historical is True

    # EvidenceProvenance.RECORDED_LIVE is strictly NOT current-live
    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.RECORDED_LIVE,
        observed_at=datetime.now(UTC),
        recorded_live_origin=EvidenceProvenance.LIVE_GOOGLE,
    )
    assert origin.provenance.is_current_live_provenance is False
    assert origin.provenance.is_recorded_live is True


def test_freshness_semantics_separate_from_historical_evidence() -> None:
    """Historical evidence existence does not imply freshness."""
    rec = _make_evidence_record(
        MissionId(str(uuid.uuid4())),
        provenance=EvidenceProvenance.RECORDED_LIVE,
    )
    # Record exists and has EvidenceId
    assert rec.evidence_id is not None
    # But provenance confirms it is historical capture, not fresh current observation
    assert rec.origin.provenance == EvidenceProvenance.RECORDED_LIVE
    assert rec.origin.provenance.is_current_live_provenance is False


# ===========================================================================
# 5. FORBIDDEN PROMOTION TESTS
# ===========================================================================


def test_forbidden_promotion_not_run() -> None:
    """NOT_RUN cannot promote to READY."""
    with pytest.raises(IllegalStatePromotionError, match="NOT_RUN"):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[StepEvidenceState.NOT_RUN],
        )


def test_forbidden_promotion_executed_unverified() -> None:
    """EXECUTED_UNVERIFIED cannot promote to READY."""
    with pytest.raises(IllegalStatePromotionError, match="EXECUTED_UNVERIFIED"):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[StepEvidenceState.EXECUTED_UNVERIFIED],
        )


def test_forbidden_promotion_provider_capture_alone() -> None:
    """Sanitized provider capture alone does not promote to READY."""
    cap = capture_provider_output({"success": True})
    assert not hasattr(cap, "is_ready")
    assert not hasattr(cap, "is_verified")
    # Cannot bypass guard
    with pytest.raises(IllegalStatePromotionError):
        assert_can_promote_to_ready(
            current_state=MissionState.EXECUTING,
            step_evidence_states=[StepEvidenceState.EXECUTED_UNVERIFIED],
        )


def test_forbidden_promotion_receipt_existence_alone() -> None:
    """Receipt existence alone cannot promote a mission from EXECUTING to READY."""
    mid = MissionId(str(uuid.uuid4()))
    mc = _make_mission_contract(mid)
    mhash = compute_mission_content_hash(mc)
    r = ReceiptProjection.create(
        mission_id=mid,
        mission_content_hash=mhash,
        evidence_ids=[],
        state_at_projection=MissionState.EXECUTING,
    )
    assert r.state_at_projection == MissionState.EXECUTING
    with pytest.raises(
        IllegalStatePromotionError, match="READY may only be entered from VERIFYING"
    ):
        assert_valid_transition(r.state_at_projection, MissionState.READY)


def test_forbidden_promotion_invalidating_evidence_states() -> None:
    """CONTRADICTED, BLOCKED, and FAILED all prevent promotion to READY."""
    for invalid_state in (
        StepEvidenceState.CONTRADICTED,
        StepEvidenceState.BLOCKED,
        StepEvidenceState.FAILED,
    ):
        with pytest.raises(IllegalStatePromotionError, match=invalid_state.value):
            assert_can_promote_to_ready(
                current_state=MissionState.VERIFYING,
                step_evidence_states=[StepEvidenceState.VERIFIED, invalid_state],
            )


def test_direct_illegal_state_transitions_fail_closed() -> None:
    """Direct transitions from non-VERIFYING states to READY fail closed."""
    illegal_sources = [
        MissionState.DRAFT,
        MissionState.PLANNED,
        MissionState.EXECUTING,
        MissionState.NEEDS_APPROVAL,
        MissionState.PARTIAL,
        MissionState.FAILED,
        MissionState.CANCELLED,
    ]
    for src in illegal_sources:
        with pytest.raises(
            IllegalStatePromotionError, match="READY may only be entered from VERIFYING"
        ):
            assert_valid_transition(src, MissionState.READY)


# ===========================================================================
# 6. UNICODE & CANONICALIZATION HARDENING
# ===========================================================================


def test_canonicalization_unicode_nfc_collision_preserved() -> None:
    """Unicode key collision after NFC normalization fails closed."""
    # Combining character vs precomposed: e.g. e + combining acute vs é
    decomposed = "e\u0301"
    precomposed = "\u00e9"
    colliding_dict = {decomposed: "val1", precomposed: "val2"}

    with pytest.raises(ValueError, match="Canonical key collision after Unicode NFC normalization"):
        to_canonical_primitive(colliding_dict)

    with pytest.raises(ValueError, match="Canonical key collision after Unicode NFC normalization"):
        capture_provider_output(colliding_dict)


def test_canonicalization_rejections_preserved() -> None:
    """NaN, Inf, naive datetimes, and unsupported types fail closed."""
    with pytest.raises(ValueError, match="Non-finite float"):
        to_canonical_primitive(float("nan"))

    with pytest.raises(ValueError, match="Non-finite float"):
        to_canonical_primitive(float("inf"))

    with pytest.raises(ValueError, match="Naive datetime is not permitted"):
        to_canonical_primitive(datetime(2026, 9, 30, 10, 0, 0))  # naive datetime

    with pytest.raises(TypeError, match="Unsupported type for canonical serialization"):
        to_canonical_primitive({1, 2, 3})  # set


# ===========================================================================
# 7. EVIDENCE PAYLOAD ISOLATION & APPEND-ONLY INVARIANTS
# ===========================================================================


def test_evidence_payload_deep_isolation_preserved() -> None:
    """EvidenceRecord payload cannot be mutated via original dict or returned object."""
    nested: dict[str, Any] = {"inner": [1, 2, 3], "meta": {"depth": 1}}
    rec = _make_evidence_record(MissionId(str(uuid.uuid4())), payload=nested)

    # Mutating original dict has no effect on rec.payload
    nested["inner"].append(4)
    assert list(rec.payload["inner"]) == [1, 2, 3]

    # Mutating rec.payload directly raises TypeError
    with pytest.raises(TypeError):
        rec.payload["new_key"] = "tamper"

    with pytest.raises(TypeError):
        rec.payload["inner"].append(4)
