"""Focused tests for P-02.01 mission identity, intent snapshot, and mission contract."""

from __future__ import annotations

import sys
import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot


def test_mission_id_generation_and_validation() -> None:
    """Verify runtime-generated mission IDs are valid opaque UUIDs."""
    mid = MissionId.generate()
    assert isinstance(mid.value, str)
    # Must parse successfully as UUID
    parsed = uuid.UUID(mid.value)
    assert parsed.version == 4
    assert str(mid) == mid.value


def test_mission_id_construction_from_string_and_uuid() -> None:
    """Verify valid string and UUID inputs are accepted and canonicalized."""
    raw_uuid = uuid.uuid4()
    mid_from_uuid = MissionId(raw_uuid)  # type: ignore[arg-type]
    mid_from_str = MissionId(str(raw_uuid).upper())

    assert mid_from_uuid.value == str(raw_uuid)
    assert mid_from_str.value == str(raw_uuid)  # canonicalized to lowercase
    assert mid_from_uuid == mid_from_str


def test_mission_id_rejects_invalid_values() -> None:
    """Verify invalid formats, empty strings, and non-UUID values are rejected."""
    with pytest.raises(ValueError, match="Invalid MissionId format"):
        MissionId("not-a-valid-uuid")

    with pytest.raises(ValueError, match="Invalid MissionId format"):
        MissionId("")

    with pytest.raises(ValueError, match="Invalid MissionId format"):
        MissionId("Get my family ready for tomorrow morning")

    with pytest.raises(TypeError, match="MissionId value must be a string or UUID instance"):
        MissionId(12345)  # type: ignore[arg-type]


def test_user_intent_snapshot_preserves_text_verbatim() -> None:
    """Verify user text is preserved verbatim with zero rewriting or trimming."""
    mid = MissionId.generate()
    now = datetime.now(UTC)
    raw_text = "  Get my family ready for tomorrow morning. We need to leave by 7:30.  \n"

    snapshot = UserIntentSnapshot(text=raw_text, captured_at=now, mission_id=mid)
    assert snapshot.text == raw_text
    assert snapshot.captured_at == now
    assert snapshot.mission_id == mid


def test_user_intent_snapshot_rejects_blank_text() -> None:
    """Verify whitespace-only or empty user text is rejected."""
    mid = MissionId.generate()
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="text cannot be blank or whitespace-only"):
        UserIntentSnapshot(text="", captured_at=now, mission_id=mid)

    with pytest.raises(ValueError, match="text cannot be blank or whitespace-only"):
        UserIntentSnapshot(text="   \n\t  ", captured_at=now, mission_id=mid)

    with pytest.raises(TypeError, match="text must be a string"):
        UserIntentSnapshot(text=None, captured_at=now, mission_id=mid)  # type: ignore[arg-type]


def test_user_intent_snapshot_rejects_naive_timestamp() -> None:
    """Verify naive datetimes without timezone information are rejected."""
    mid = MissionId.generate()
    naive_dt = datetime.now()  # no tzinfo

    with pytest.raises(ValueError, match="timezone-aware"):
        UserIntentSnapshot(
            text="Get my family ready",
            captured_at=naive_dt,
            mission_id=mid,
        )


def test_user_intent_snapshot_normalizes_aware_timestamp_to_utc() -> None:
    """Verify non-UTC timezone-aware timestamps are normalized to UTC."""
    mid = MissionId.generate()
    tz_plus_3 = timezone(timedelta(hours=3))
    aware_dt = datetime(2026, 9, 29, 14, 30, tzinfo=tz_plus_3)

    snapshot = UserIntentSnapshot(
        text="Get my family ready",
        captured_at=aware_dt,
        mission_id=mid,
    )
    assert snapshot.captured_at.tzinfo == UTC
    assert snapshot.captured_at.hour == 11
    assert snapshot.captured_at.minute == 30


def test_mission_contract_creation_and_fields() -> None:
    """Verify root mission contract binds identity, intent snapshot, and timestamp."""
    contract = MissionContract.create("Get my family ready for tomorrow morning.")
    assert isinstance(contract.mission_id, MissionId)
    assert isinstance(contract.intent, UserIntentSnapshot)
    assert contract.intent.mission_id == contract.mission_id
    assert contract.intent.text == "Get my family ready for tomorrow morning."
    assert contract.schema_version == "v1"
    assert contract.created_at.tzinfo == UTC


def test_mission_contract_rejects_mismatched_intent_linkage() -> None:
    """Verify contract creation rejects intent snapshots bound to different mission IDs."""
    mid1 = MissionId.generate()
    mid2 = MissionId.generate()
    now = datetime.now(UTC)
    intent = UserIntentSnapshot(text="Wake up early", captured_at=now, mission_id=mid1)

    with pytest.raises(ValueError, match="Intent snapshot mission_id must match"):
        MissionContract(mission_id=mid2, intent=intent, created_at=now)


def test_mission_contract_rejects_naive_timestamp() -> None:
    """Verify contract rejects naive creation timestamps."""
    mid = MissionId.generate()
    now_utc = datetime.now(UTC)
    intent = UserIntentSnapshot(text="Test", captured_at=now_utc, mission_id=mid)
    naive_dt = datetime.now()

    with pytest.raises(ValueError, match="timezone-aware"):
        MissionContract(mission_id=mid, intent=intent, created_at=naive_dt)


def test_immutability_enforced() -> None:
    """Verify frozen dataclasses reject mutation."""
    contract = MissionContract.create("Get my family ready.")

    with pytest.raises(FrozenInstanceError):
        contract.schema_version = "v2"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        contract.mission_id = MissionId.generate()  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        contract.intent.text = "New text"  # type: ignore[misc]


def test_no_provider_dependencies_imported() -> None:
    """Verify domain package does not import cloud or provider SDKs."""
    forbidden_modules = [
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "mcp",
        "requests",
        "httpx",
        "urllib3",
    ]
    for mod in forbidden_modules:
        assert mod not in sys.modules, f"Forbidden module {mod} was imported!"
