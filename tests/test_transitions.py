"""Focused unit tests for StillDone deterministic runtime state-transition guards."""

from __future__ import annotations

import pytest

from stilldone.domain.lifecycle import (
    DECLARATIVE_MISSION_TRANSITIONS,
    MissionState,
    StepEvidenceState,
)
from stilldone.transitions import (
    ForbiddenTransitionError,
    IllegalStatePromotionError,
    MissionTransitionGuard,
    assert_can_promote_to_ready,
    assert_valid_transition,
    is_transition_allowed,
)


def test_all_declarative_transitions_are_permitted() -> None:
    """Every pair in DECLARATIVE_MISSION_TRANSITIONS passes transition validation."""
    for src, dst in DECLARATIVE_MISSION_TRANSITIONS:
        assert is_transition_allowed(src, dst) is True
        assert_valid_transition(src, dst)


def test_forbidden_transitions_to_ready() -> None:
    """Direct transitions to READY from states other than VERIFYING are strictly forbidden."""
    forbidden_sources = [
        MissionState.DRAFT,
        MissionState.PLANNED,
        MissionState.EXECUTING,
        MissionState.NEEDS_APPROVAL,
        MissionState.PARTIAL,
        MissionState.FAILED,
        MissionState.CANCELLED,
    ]

    for src in forbidden_sources:
        assert is_transition_allowed(src, MissionState.READY) is False
        with pytest.raises(IllegalStatePromotionError, match="Illegal promotion to READY"):
            assert_valid_transition(src, MissionState.READY)
        with pytest.raises(IllegalStatePromotionError, match="Illegal promotion to READY"):
            MissionTransitionGuard.guard_transition(
                src,
                MissionState.READY,
                step_evidence_states=[StepEvidenceState.VERIFIED],
            )


def test_ready_only_entered_from_verifying() -> None:
    """READY can ONLY be entered from VERIFYING with valid evidence."""
    # When in VERIFYING with verified evidence, promotion succeeds
    new_state = MissionTransitionGuard.guard_transition(
        MissionState.VERIFYING,
        MissionState.READY,
        step_evidence_states=[StepEvidenceState.VERIFIED],
    )
    assert new_state == MissionState.READY

    # Without evidence states, promotion fails closed
    with pytest.raises(IllegalStatePromotionError, match="requires step_evidence_states"):
        MissionTransitionGuard.guard_transition(
            MissionState.VERIFYING,
            MissionState.READY,
        )


def test_executor_success_alone_cannot_promote_to_ready() -> None:
    """Tool/executor success alone (EXECUTED_UNVERIFIED) CANNOT promote a mission to READY.

    Mandatory independent read-back verification is required.
    """
    with pytest.raises(
        IllegalStatePromotionError, match="EXECUTED_UNVERIFIED .* cannot promote to READY"
    ):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[StepEvidenceState.EXECUTED_UNVERIFIED],
        )

    with pytest.raises(
        IllegalStatePromotionError, match="EXECUTED_UNVERIFIED .* cannot promote to READY"
    ):
        MissionTransitionGuard.guard_transition(
            MissionState.VERIFYING,
            MissionState.READY,
            step_evidence_states=[StepEvidenceState.EXECUTED_UNVERIFIED],
        )


def test_not_run_cannot_promote_to_ready() -> None:
    """NOT_RUN cannot be interpreted as PASS or VERIFIED and cannot promote to READY."""
    with pytest.raises(
        IllegalStatePromotionError, match="NOT_RUN cannot be interpreted as PASS/VERIFIED"
    ):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[StepEvidenceState.NOT_RUN],
        )

    # Mixed steps where one is VERIFIED but another is NOT_RUN must fail closed
    with pytest.raises(
        IllegalStatePromotionError, match="NOT_RUN cannot be interpreted as PASS/VERIFIED"
    ):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[StepEvidenceState.VERIFIED, StepEvidenceState.NOT_RUN],
        )


def test_invalidating_step_states_prevent_ready_promotion() -> None:
    """CONTRADICTED, BLOCKED, FAILED, and STALE step states prevent READY promotion."""
    invalidating_states = [
        StepEvidenceState.CONTRADICTED,
        StepEvidenceState.BLOCKED,
        StepEvidenceState.FAILED,
        StepEvidenceState.STALE,
    ]

    for bad_step in invalidating_states:
        with pytest.raises(
            IllegalStatePromotionError, match="contradicts or invalidates verification"
        ):
            assert_can_promote_to_ready(
                current_state=MissionState.VERIFYING,
                step_evidence_states=[bad_step],
            )
        # Even alongside a VERIFIED step, any bad step fails closed
        with pytest.raises(
            IllegalStatePromotionError, match="contradicts or invalidates verification"
        ):
            assert_can_promote_to_ready(
                current_state=MissionState.VERIFYING,
                step_evidence_states=[StepEvidenceState.VERIFIED, bad_step],
            )


def test_empty_step_evidence_cannot_promote_to_ready() -> None:
    """Zero step evidence states cannot promote to READY."""
    with pytest.raises(IllegalStatePromotionError, match="zero step evidence states"):
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[],
        )


def test_ready_can_transition_to_drifted() -> None:
    """READY is renewable and can transition to DRIFTED when reality diverges."""
    assert is_transition_allowed(MissionState.READY, MissionState.DRIFTED) is True
    assert_valid_transition(MissionState.READY, MissionState.DRIFTED)

    new_state = MissionTransitionGuard.guard_transition(
        MissionState.READY,
        MissionState.DRIFTED,
    )
    assert new_state == MissionState.DRIFTED

    # From DRIFTED, re-reconciliation or re-execution paths are valid
    assert is_transition_allowed(MissionState.DRIFTED, MissionState.VERIFYING) is True
    assert is_transition_allowed(MissionState.DRIFTED, MissionState.EXECUTING) is True
    assert is_transition_allowed(MissionState.DRIFTED, MissionState.CANCELLED) is True


def test_terminal_states_cannot_transition() -> None:
    """CANCELLED and FAILED are terminal states and cannot transition to any state."""
    for dst in MissionState:
        assert is_transition_allowed(MissionState.CANCELLED, dst) is False
        with pytest.raises(
            ForbiddenTransitionError,
            match=r"(Forbidden mission state transition|Illegal promotion to READY)",
        ):
            assert_valid_transition(MissionState.CANCELLED, dst)

        assert is_transition_allowed(MissionState.FAILED, dst) is False
        with pytest.raises(
            ForbiddenTransitionError,
            match=r"(Forbidden mission state transition|Illegal promotion to READY)",
        ):
            assert_valid_transition(MissionState.FAILED, dst)


def test_invalid_state_strings_fail_closed() -> None:
    """Malformed or unknown state strings fail closed."""
    with pytest.raises(ForbiddenTransitionError, match="Invalid mission state"):
        is_transition_allowed("NON_EXISTENT_STATE", MissionState.PLANNED)

    with pytest.raises(ForbiddenTransitionError, match="Invalid mission state"):
        assert_valid_transition(MissionState.DRAFT, "INVALID_TARGET")
