"""Focused tests for P-02.04 mission lifecycle and step evidence states."""

from __future__ import annotations

import sys

from stilldone.domain import lifecycle
from stilldone.domain.lifecycle import (
    DECLARATIVE_MISSION_TRANSITIONS,
    MissionState,
    StepEvidenceState,
)


def test_exact_mission_state_vocabulary() -> None:
    """Verify exact 10 canonical mission states as defined by docs/PRODUCT_CONTRACT.md."""
    expected = {
        "DRAFT": MissionState.DRAFT,
        "PLANNED": MissionState.PLANNED,
        "EXECUTING": MissionState.EXECUTING,
        "NEEDS_APPROVAL": MissionState.NEEDS_APPROVAL,
        "VERIFYING": MissionState.VERIFYING,
        "READY": MissionState.READY,
        "PARTIAL": MissionState.PARTIAL,
        "FAILED": MissionState.FAILED,
        "DRIFTED": MissionState.DRIFTED,
        "CANCELLED": MissionState.CANCELLED,
    }
    assert len(MissionState) == 10
    for name, member in expected.items():
        assert MissionState(name) == member
        assert member.value == name


def test_exact_step_evidence_state_vocabulary() -> None:
    """Verify exact 7 canonical step evidence states."""
    expected = {
        "NOT_RUN": StepEvidenceState.NOT_RUN,
        "EXECUTED_UNVERIFIED": StepEvidenceState.EXECUTED_UNVERIFIED,
        "VERIFIED": StepEvidenceState.VERIFIED,
        "CONTRADICTED": StepEvidenceState.CONTRADICTED,
        "BLOCKED": StepEvidenceState.BLOCKED,
        "FAILED": StepEvidenceState.FAILED,
        "STALE": StepEvidenceState.STALE,
    }
    assert len(StepEvidenceState) == 7
    for name, member in expected.items():
        assert StepEvidenceState(name) == member
        assert member.value == name


def test_state_distinctions() -> None:
    """Verify critical semantic distinctions enforced by StillDone laws."""
    # NOT_RUN is never VERIFIED
    assert len({StepEvidenceState.NOT_RUN, StepEvidenceState.VERIFIED}) == 2

    # EXECUTED_UNVERIFIED is never VERIFIED (execution != verification)
    assert len({StepEvidenceState.EXECUTED_UNVERIFIED, StepEvidenceState.VERIFIED}) == 2

    # CONTRADICTED is distinct from FAILED
    assert len({StepEvidenceState.CONTRADICTED, StepEvidenceState.FAILED}) == 2

    # BLOCKED is distinct from FAILED
    assert len({StepEvidenceState.BLOCKED, StepEvidenceState.FAILED}) == 2

    # STALE is distinct from NOT_RUN and VERIFIED
    assert (
        len({StepEvidenceState.STALE, StepEvidenceState.NOT_RUN, StepEvidenceState.VERIFIED}) == 3
    )

    # READY and DRIFTED are distinct (drift revokes completion)
    assert len({MissionState.READY, MissionState.DRIFTED}) == 2


def test_declarative_transitions_are_metadata_only() -> None:
    """Verify transitions are exposed as immutable contract metadata only."""
    assert isinstance(DECLARATIVE_MISSION_TRANSITIONS, frozenset)
    assert (MissionState.DRAFT, MissionState.PLANNED) in DECLARATIVE_MISSION_TRANSITIONS
    assert (MissionState.READY, MissionState.DRIFTED) in DECLARATIVE_MISSION_TRANSITIONS
    assert (MissionState.DRIFTED, MissionState.VERIFYING) in DECLARATIVE_MISSION_TRANSITIONS

    # Direct jump from DRAFT to READY is not in declared valid transitions
    assert (MissionState.DRAFT, MissionState.READY) not in DECLARATIVE_MISSION_TRANSITIONS


def test_no_transition_guard_engine_implemented() -> None:
    """Verify P-02.04 does not implement transition engine methods (deferred to P-03.03)."""
    prohibited_functions = [
        "transition",
        "advance",
        "mutate_state",
        "execute_transition",
        "validate_transition",
        "apply_transition",
        "StateEngine",
        "TransitionGuard",
    ]
    for name in prohibited_functions:
        assert not hasattr(lifecycle, name), (
            f"Prohibited transition engine element {name!r} found in lifecycle module!"
        )


def test_no_provider_dependencies_imported() -> None:
    """Verify lifecycle module does not import cloud or provider SDKs."""
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
