"""Focused unit tests for StillDone append-only ledger contracts and in-memory port."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.ledger import (
    ActionRecord,
    DuplicateRecordError,
    EvidenceRecord,
    InMemoryNonDurableLedger,
    LedgerError,
    MissionRecord,
    RecordConflictError,
    RecordNotFoundError,
)


def _make_sample_mission(mid_str: str = "00000000-0000-0000-0000-000000000001") -> MissionRecord:
    mid = MissionId(mid_str)
    intent = UserIntentSnapshot(
        mission_id=mid,
        text="Sample test mission",
        captured_at=datetime(2026, 9, 30, 8, 0, 0, tzinfo=UTC),
    )
    contract = MissionContract(
        mission_id=mid,
        intent=intent,
        created_at=datetime(2026, 9, 30, 8, 0, 0, tzinfo=UTC),
    )
    return MissionRecord(
        mission_id=mid,
        contract=contract,
        state=MissionState.DRAFT,
        created_at=datetime(2026, 9, 30, 8, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 30, 8, 0, 0, tzinfo=UTC),
    )


def _make_sample_action(
    mid: MissionId,
    aid_str: str = "11111111-1111-1111-1111-111111111111",
) -> ActionRecord:
    aid = ActionId(aid_str)
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task-001",
        parent_id="list-001",
    )
    action_contract = ActionContract(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.TASK_READ,
        target=target,
        parameters=NormalizedParameters.from_dict({"task_list_id": "list-001"}),
    )
    return ActionRecord(
        action_id=aid,
        mission_id=mid,
        action=action_contract,
        approval_id=None,
        created_at=datetime(2026, 9, 30, 8, 1, 0, tzinfo=UTC),
    )


def _make_sample_evidence(
    mid: MissionId,
    aid: ActionId,
    payload: dict[str, str] | None = None,
) -> EvidenceRecord:
    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.LIVE_GOOGLE,
        observed_at=datetime(2026, 9, 30, 8, 2, 0, tzinfo=UTC),
    )
    p = payload or {"status": "needsAction", "title": "Buy milk"}
    return EvidenceRecord.create(
        action_id=aid,
        mission_id=mid,
        origin=origin,
        payload=p,
        created_at=datetime(2026, 9, 30, 8, 2, 0, tzinfo=UTC),
    )


def test_in_memory_ledger_durability_classification() -> None:
    """The in-memory ledger explicitly declares itself non-durable runtime-local state."""
    ledger = InMemoryNonDurableLedger()
    assert ledger.IS_DURABLE is False
    assert ledger.DURABILITY_CLASSIFICATION == "NON_DURABLE_TEST_OR_RUNTIME_LOCAL"


def test_append_and_retrieve_mission() -> None:
    """Missions can be appended and retrieved by ID."""
    ledger = InMemoryNonDurableLedger()
    m_record = _make_sample_mission()

    ledger.append_mission(m_record)
    retrieved = ledger.get_mission(m_record.mission_id)

    assert retrieved == m_record
    assert retrieved.mission_id == m_record.mission_id


def test_missing_records_raise_not_found() -> None:
    """Looking up non-existent records raises RecordNotFoundError."""
    ledger = InMemoryNonDurableLedger()
    with pytest.raises(RecordNotFoundError, match="Mission .* not found"):
        ledger.get_mission(MissionId("00000000-0000-0000-0000-999999999999"))

    with pytest.raises(RecordNotFoundError, match="Action .* not found"):
        ledger.get_action(ActionId("11111111-1111-1111-1111-999999999999"))

    with pytest.raises(RecordNotFoundError, match="Evidence .* not found"):
        ledger.get_evidence(EvidenceId("a" * 64))


def test_duplicate_mission_replay_fails_explicitly() -> None:
    """Re-appending an identical mission record raises DuplicateRecordError."""
    ledger = InMemoryNonDurableLedger()
    m_record = _make_sample_mission()

    ledger.append_mission(m_record)
    with pytest.raises(DuplicateRecordError, match="already exists with identical content"):
        ledger.append_mission(m_record)


def test_conflicting_mission_append_fails_closed() -> None:
    """Appending a mission with an existing ID but different content raises RecordConflictError."""
    ledger = InMemoryNonDurableLedger()
    m_record1 = _make_sample_mission()

    # Conflicting record with same ID but different state
    m_record2 = MissionRecord(
        mission_id=m_record1.mission_id,
        contract=m_record1.contract,
        state=MissionState.PLANNED,
        created_at=m_record1.created_at,
        updated_at=m_record1.updated_at,
    )

    ledger.append_mission(m_record1)
    with pytest.raises(RecordConflictError, match="Conflicting record for mission"):
        ledger.append_mission(m_record2)


def test_action_and_evidence_traceability() -> None:
    """Full traceability: mission -> action -> evidence and back."""
    ledger = InMemoryNonDurableLedger()
    m_record = _make_sample_mission()
    ledger.append_mission(m_record)

    a_record = _make_sample_action(m_record.mission_id)
    ledger.append_action(a_record)

    e_record1 = _make_sample_evidence(m_record.mission_id, a_record.action_id, {"step": "1"})
    e_record2 = _make_sample_evidence(m_record.mission_id, a_record.action_id, {"step": "2"})
    ledger.append_evidence(e_record1)
    ledger.append_evidence(e_record2)

    # Trace forward from mission
    actions = ledger.get_actions_for_mission(m_record.mission_id)
    assert len(actions) == 1
    assert actions[0].action_id == a_record.action_id

    evidence_for_mission = ledger.get_evidence_for_mission(m_record.mission_id)
    assert len(evidence_for_mission) == 2
    assert {e.evidence_id for e in evidence_for_mission} == {
        e_record1.evidence_id,
        e_record2.evidence_id,
    }

    # Trace forward from action
    evidence_for_action = ledger.get_evidence_for_action(a_record.action_id)
    assert len(evidence_for_action) == 2

    # Trace backward from evidence
    e_retrieved = ledger.get_evidence(e_record1.evidence_id)
    assert e_retrieved.action_id == a_record.action_id
    assert e_retrieved.mission_id == m_record.mission_id

    a_retrieved = ledger.get_action(e_retrieved.action_id)
    assert a_retrieved.mission_id == m_record.mission_id


def test_evidence_id_binding_validation() -> None:
    """EvidenceRecord strictly verifies that bound EvidenceId matches content-addressed SHA-256."""
    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.LIVE_GOOGLE,
        observed_at=datetime(2026, 9, 30, 8, 2, 0, tzinfo=UTC),
    )
    payload = {"status": "ok"}
    correct_id = compute_evidence_id({"origin": origin, "payload": payload})
    tampered_id = EvidenceId("f" * 64)

    # Valid creation
    record = EvidenceRecord(
        evidence_id=correct_id,
        action_id=ActionId("11111111-1111-1111-1111-111111111111"),
        mission_id=MissionId("00000000-0000-0000-0000-000000000001"),
        origin=origin,
        payload=payload,
        created_at=datetime(2026, 9, 30, 8, 2, 0, tzinfo=UTC),
    )
    assert record.evidence_id == correct_id

    # Tampered/mismatched EvidenceId fails closed
    with pytest.raises(ValueError, match="Mismatched evidence_id"):
        EvidenceRecord(
            evidence_id=tampered_id,
            action_id=ActionId("11111111-1111-1111-1111-111111111111"),
            mission_id=MissionId("00000000-0000-0000-0000-000000000001"),
            origin=origin,
            payload=payload,
            created_at=datetime(2026, 9, 30, 8, 2, 0, tzinfo=UTC),
        )


def test_relational_integrity_checks() -> None:
    """Appending actions or evidence without parent records or with mismatched parents fails."""
    ledger = InMemoryNonDurableLedger()
    m_record = _make_sample_mission("00000000-0000-0000-0000-000000000001")
    ledger.append_mission(m_record)

    # Appending action for non-existent mission
    orphan_action = _make_sample_action(MissionId("00000000-0000-0000-0000-999999999999"))
    with pytest.raises(RecordNotFoundError, match="mission .* does not exist"):
        ledger.append_action(orphan_action)

    valid_action = _make_sample_action(m_record.mission_id)
    ledger.append_action(valid_action)

    # Appending evidence with mismatched mission vs action's mission
    m_other = _make_sample_mission("00000000-0000-0000-0000-000000000002")
    ledger.append_mission(m_other)

    mismatched_evidence = _make_sample_evidence(
        mid=m_other.mission_id,  # claims m_other
        aid=valid_action.action_id,  # but action belongs to m_record
    )
    with pytest.raises(LedgerError, match="Relationship mismatch"):
        ledger.append_evidence(mismatched_evidence)
