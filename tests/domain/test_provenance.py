"""Focused tests for P-02.07 evidence provenance and live/recorded/fixture separation."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.domain.lifecycle import StepEvidenceState
from stilldone.domain.provenance import (
    VALID_RECORDED_LIVE_ORIGINS,
    EvidenceOrigin,
    EvidenceProvenance,
    EvidenceProvenanceContract,
)


def test_exact_six_value_provenance_vocabulary() -> None:
    """A1. Exact six canonical provenance values frozen by AGENTS.md."""
    expected = {
        "FIXTURE": EvidenceProvenance.FIXTURE,
        "LOCAL_EXECUTION": EvidenceProvenance.LOCAL_EXECUTION,
        "LIVE_AWS": EvidenceProvenance.LIVE_AWS,
        "LIVE_GOOGLE": EvidenceProvenance.LIVE_GOOGLE,
        "LIVE_EXTERNAL": EvidenceProvenance.LIVE_EXTERNAL,
        "RECORDED_LIVE": EvidenceProvenance.RECORDED_LIVE,
    }

    assert len(EvidenceProvenance) == 6
    assert set(EvidenceProvenance) == set(expected.values())
    for name, member in expected.items():
        assert EvidenceProvenance(name) == member
        assert member.value == name

    # Narrower or arbitrary values rejected
    for bad in [
        "LIVE_GOOGLE_CALENDAR",
        "LIVE_GOOGLE_TASKS",
        "LIVE_REMOTE_MCP",
        "SIMULATED",
        "MOCK",
    ]:
        with pytest.raises(ValueError, match="is not a valid EvidenceProvenance"):
            EvidenceProvenance(bad)


def test_fixture_never_classifies_as_current_live() -> None:
    """B1. FIXTURE is synthetic/non-live and never current live."""
    prov = EvidenceProvenance.FIXTURE
    assert prov.is_fixture is True
    assert prov.is_current_live_provenance is False
    assert prov.is_external_live is False
    assert prov.is_recorded_live is False
    assert prov.is_local_execution is False

    origin = EvidenceOrigin.fixture()
    assert origin.is_fixture is True
    assert origin.is_current_live_provenance is False
    assert origin.is_external_live is False
    assert origin.is_recorded_live is False


def test_local_execution_never_classifies_as_external_live() -> None:
    """B2. LOCAL_EXECUTION is real local execution, but never external live."""
    prov = EvidenceProvenance.LOCAL_EXECUTION
    assert prov.is_local_execution is True
    assert prov.is_fixture is False
    assert prov.is_external_live is False
    assert prov.is_current_live_provenance is False
    assert prov.is_recorded_live is False

    origin = EvidenceOrigin.local_execution()
    assert origin.is_local_execution is True
    assert origin.is_external_live is False
    assert origin.is_current_live_provenance is False


def test_current_live_external_provenance_classification() -> None:
    """B3. LIVE_AWS, LIVE_GOOGLE, and LIVE_EXTERNAL classify as current external live."""
    live_set = [
        (EvidenceProvenance.LIVE_AWS, EvidenceOrigin.live_aws()),
        (EvidenceProvenance.LIVE_GOOGLE, EvidenceOrigin.live_google()),
        (EvidenceProvenance.LIVE_EXTERNAL, EvidenceOrigin.live_external()),
    ]
    for enum_val, contract_val in live_set:
        assert enum_val.is_current_live_provenance is True
        assert enum_val.is_external_live is True
        assert enum_val.is_fixture is False
        assert enum_val.is_local_execution is False
        assert enum_val.is_recorded_live is False

        assert contract_val.is_current_live_provenance is True
        assert contract_val.is_external_live is True
        assert contract_val.is_fixture is False
        assert contract_val.is_recorded_live is False


def test_recorded_live_never_classifies_as_current_live() -> None:
    """B4. RECORDED_LIVE is historical capture and never current live."""
    prov = EvidenceProvenance.RECORDED_LIVE
    assert prov.is_recorded_live is True
    assert prov.is_current_live_provenance is False
    assert prov.is_external_live is False
    assert prov.is_fixture is False
    assert prov.is_local_execution is False

    origin = EvidenceOrigin.recorded_live(original_provenance=EvidenceProvenance.LIVE_GOOGLE)
    assert origin.is_recorded_live is True
    assert origin.is_current_live_provenance is False
    assert origin.is_external_live is False


def test_recorded_live_valid_origin_families() -> None:
    """C1. RECORDED_LIVE accepts original source drawn only from live families."""
    assert VALID_RECORDED_LIVE_ORIGINS == {
        EvidenceProvenance.LIVE_AWS,
        EvidenceProvenance.LIVE_GOOGLE,
        EvidenceProvenance.LIVE_EXTERNAL,
    }

    for live_family in VALID_RECORDED_LIVE_ORIGINS:
        origin = EvidenceOrigin.recorded_live(original_provenance=live_family)
        assert origin.provenance == EvidenceProvenance.RECORDED_LIVE
        assert origin.recorded_live_origin == live_family

        # String construction also supported
        origin_str = EvidenceOrigin.create(
            provenance="RECORDED_LIVE",
            recorded_live_origin=live_family.value,
        )
        assert origin_str.recorded_live_origin == live_family


def test_fixture_and_local_execution_cannot_masquerade_as_recorded_live() -> None:
    """C2. FIXTURE, LOCAL_EXECUTION, and RECORDED_LIVE cannot be recorded-live original origin."""
    for forbidden_origin in [
        EvidenceProvenance.FIXTURE,
        EvidenceProvenance.LOCAL_EXECUTION,
        EvidenceProvenance.RECORDED_LIVE,
    ]:
        with pytest.raises(
            ValueError,
            match="RECORDED_LIVE origin must be drawn only from LIVE_AWS, LIVE_GOOGLE,",
        ):
            EvidenceOrigin.recorded_live(original_provenance=forbidden_origin)


def test_recorded_live_requires_origin() -> None:
    """C3. RECORDED_LIVE requires recorded_live_origin."""
    with pytest.raises(ValueError, match="RECORDED_LIVE provenance requires recorded_live_origin"):
        EvidenceOrigin(
            provenance=EvidenceProvenance.RECORDED_LIVE,
            observed_at=datetime.now(UTC),
            recorded_live_origin=None,
        )


def test_non_recorded_live_cannot_carry_recorded_live_origin() -> None:
    """C4. Non-RECORDED_LIVE provenance must not carry recorded-live origin metadata."""
    non_recorded = [
        EvidenceProvenance.FIXTURE,
        EvidenceProvenance.LOCAL_EXECUTION,
        EvidenceProvenance.LIVE_AWS,
        EvidenceProvenance.LIVE_GOOGLE,
        EvidenceProvenance.LIVE_EXTERNAL,
    ]
    for prov in non_recorded:
        with pytest.raises(
            ValueError, match="Non-RECORDED_LIVE provenance .* must not carry recorded_live_origin"
        ):
            EvidenceOrigin(
                provenance=prov,
                observed_at=datetime.now(UTC),
                recorded_live_origin=EvidenceProvenance.LIVE_AWS,
            )


def test_timestamp_awareness_and_utc_normalization() -> None:
    """C5. EvidenceOrigin enforces timezone-aware UTC timestamps."""
    # Naive timestamp rejected
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        EvidenceOrigin(
            provenance=EvidenceProvenance.LIVE_AWS,
            observed_at=datetime(2026, 9, 29, 12, 0, 0),
        )

    # Non-UTC timezone normalized to UTC
    tz_plus_5 = timezone(timedelta(hours=5))
    dt_local = datetime(2026, 9, 29, 17, 30, 0, tzinfo=tz_plus_5)
    origin = EvidenceOrigin.create(
        provenance=EvidenceProvenance.LIVE_GOOGLE,
        observed_at=dt_local,
    )
    assert origin.observed_at.tzinfo == UTC
    assert origin.observed_at == datetime(2026, 9, 29, 12, 30, 0, tzinfo=UTC)


def test_provenance_never_assigns_result_state() -> None:
    """D1. Provenance is separate from result state."""
    # Provenance answers WHERE/HOW, not whether predicate passed
    origin = EvidenceOrigin.live_google()
    assert origin.provenance == EvidenceProvenance.LIVE_GOOGLE

    # The origin object has no verification/pass/result fields
    fields = set(origin.__dataclass_fields__)
    assert fields == {"provenance", "observed_at", "recorded_live_origin"}
    assert not hasattr(origin, "state")
    assert not hasattr(origin, "status")
    assert not hasattr(origin, "verified")
    assert not hasattr(origin, "ready")
    assert not hasattr(origin, "result")

    # Domain demonstrates that provenance and step result can be paired orthogonally
    paired_examples = [
        (EvidenceOrigin.live_google(), StepEvidenceState.FAILED),
        (EvidenceOrigin.live_google(), StepEvidenceState.VERIFIED),
        (EvidenceOrigin.fixture(), StepEvidenceState.VERIFIED),
        (
            EvidenceOrigin.recorded_live(original_provenance=EvidenceProvenance.LIVE_AWS),
            StepEvidenceState.VERIFIED,
        ),
    ]
    for orig, step_state in paired_examples:
        # Both exist independently without contradiction
        assert isinstance(orig, EvidenceOrigin)
        assert isinstance(step_state, StepEvidenceState)


def test_provenance_alias_parity() -> None:
    """D2. EvidenceProvenanceContract is an alias for EvidenceOrigin."""
    assert EvidenceProvenanceContract is EvidenceOrigin


def test_provenance_immutability() -> None:
    """D3. EvidenceOrigin is frozen and immutable."""
    origin = EvidenceOrigin.live_external()
    with pytest.raises(FrozenInstanceError):
        origin.provenance = EvidenceProvenance.FIXTURE  # type: ignore[misc]


def test_provider_purity() -> None:
    """D4. Domain provenance module does not import external/provider SDKs."""
    forbidden = [
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "googleapiclient",
        "mcp",
        "requests",
        "httpx",
        "urllib3",
    ]
    for mod in forbidden:
        assert mod not in sys.modules, f"Forbidden provider module imported: {mod}"
