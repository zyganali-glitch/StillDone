"""Deterministic runtime state-transition guards for StillDone.

Enforces lifecycle invariants based on the canonical MissionState vocabulary
and DECLARATIVE_MISSION_TRANSITIONS metadata frozen in Phase P-02.
Fails closed on any forbidden transition or illegal promotion attempt.
"""

from __future__ import annotations

from collections.abc import Iterable

from stilldone.domain.lifecycle import (
    DECLARATIVE_MISSION_TRANSITIONS,
    MissionState,
    StepEvidenceState,
)


class TransitionError(Exception):
    """Base exception for all mission state transition guard failures."""


class ForbiddenTransitionError(TransitionError):
    """Raised when a mission transition is not permitted by declarative lifecycle rules."""


class IllegalStatePromotionError(ForbiddenTransitionError):
    """Raised when an attempt is made to illegally promote a mission to READY.

    Enforces StillDone laws:
    - READY may only be entered from VERIFYING.
    - DRAFT, PLANNED, EXECUTING, NEEDS_APPROVAL, PARTIAL, and FAILED cannot transition to READY.
    - Executor/tool success alone (EXECUTED_UNVERIFIED) cannot promote to READY.
    - NOT_RUN cannot be interpreted as PASS/VERIFIED.
    """


def _normalize_mission_state(state: MissionState | str) -> MissionState:
    """Normalize input to a canonical MissionState enum instance, failing closed."""
    if isinstance(state, MissionState):
        return state
    if isinstance(state, str):
        try:
            return MissionState(state)
        except ValueError as exc:
            raise ForbiddenTransitionError(f"Invalid mission state: {state!r}") from exc
    raise TypeError(f"Expected MissionState or str, got {type(state).__name__}")


def _normalize_step_state(state: StepEvidenceState | str) -> StepEvidenceState:
    """Normalize input to a canonical StepEvidenceState enum instance, failing closed."""
    if isinstance(state, StepEvidenceState):
        return state
    if isinstance(state, str):
        try:
            return StepEvidenceState(state)
        except ValueError as exc:
            raise TransitionError(f"Invalid step evidence state: {state!r}") from exc
    raise TypeError(f"Expected StepEvidenceState or str, got {type(state).__name__}")


def is_transition_allowed(
    source: MissionState | str,
    destination: MissionState | str,
) -> bool:
    """Check whether a transition between two mission states is declared as permitted."""
    src = _normalize_mission_state(source)
    dst = _normalize_mission_state(destination)
    return (src, dst) in DECLARATIVE_MISSION_TRANSITIONS


def assert_valid_transition(
    source: MissionState | str,
    destination: MissionState | str,
) -> None:
    """Assert that a transition from source to destination is permitted.

    Fails closed with IllegalStatePromotionError or ForbiddenTransitionError.
    """
    src = _normalize_mission_state(source)
    dst = _normalize_mission_state(destination)

    # Special guard for READY promotion: must originate strictly from VERIFYING
    if dst == MissionState.READY and src != MissionState.VERIFYING:
        msg = (
            f"Illegal promotion to READY from {src}: "
            "READY may only be entered from VERIFYING. Direct promotion from "
            f"{src} is strictly forbidden."
        )
        raise IllegalStatePromotionError(msg)

    if (src, dst) not in DECLARATIVE_MISSION_TRANSITIONS:
        msg = f"Forbidden mission state transition: {src} -> {dst}"
        raise ForbiddenTransitionError(msg)


def assert_can_promote_to_ready(
    *,
    current_state: MissionState | str,
    step_evidence_states: Iterable[StepEvidenceState | str],
) -> None:
    """Assert that all deterministic requirements to enter READY are satisfied.

    Enforces StillDone core laws:
    1. current_state must be VERIFYING.
    2. step_evidence_states must be non-empty.
    3. NOT_RUN cannot be interpreted as PASS/VERIFIED.
    4. EXECUTED_UNVERIFIED (tool/executor success alone) cannot promote to READY.
    5. CONTRADICTED, BLOCKED, FAILED, and STALE prevent promotion to READY.
    6. All required steps must be independently observed as VERIFIED.
    """
    src = _normalize_mission_state(current_state)
    if src != MissionState.VERIFYING:
        msg = (
            f"Cannot promote to READY from {src}: "
            "mission must be in VERIFYING state with independent read-back evidence."
        )
        raise IllegalStatePromotionError(msg)

    steps = [_normalize_step_state(s) for s in step_evidence_states]
    if not steps:
        raise IllegalStatePromotionError(
            "Cannot promote to READY with zero step evidence states. "
            "Verification requires at least one independent observation."
        )

    for step in steps:
        if step == StepEvidenceState.NOT_RUN:
            raise IllegalStatePromotionError(
                "NOT_RUN cannot be interpreted as PASS/VERIFIED. "
                "Step was never executed; promotion to READY is forbidden."
            )
        if step == StepEvidenceState.EXECUTED_UNVERIFIED:
            raise IllegalStatePromotionError(
                "EXECUTED_UNVERIFIED (tool/executor success alone) cannot promote to READY. "
                "Mandatory independent read-back observation is required."
            )
        if step in {
            StepEvidenceState.CONTRADICTED,
            StepEvidenceState.BLOCKED,
            StepEvidenceState.FAILED,
            StepEvidenceState.STALE,
        }:
            raise IllegalStatePromotionError(
                f"Step in state {step} contradicts or invalidates verification. "
                "Promotion to READY is forbidden."
            )
        if step != StepEvidenceState.VERIFIED:
            raise IllegalStatePromotionError(
                f"Unhandled or non-VERIFIED step state: {step}. "
                "All steps must be VERIFIED for READY."
            )


class MissionTransitionGuard:
    """Deterministic runtime engine for validating and guarding mission state transitions."""

    @staticmethod
    def validate_transition(
        current_state: MissionState | str,
        target_state: MissionState | str,
    ) -> None:
        """Validate that transition from current_state to target_state is permitted."""
        assert_valid_transition(current_state, target_state)

    @staticmethod
    def validate_ready_promotion(
        current_state: MissionState | str,
        step_evidence_states: Iterable[StepEvidenceState | str],
    ) -> None:
        """Validate that all requirements to promote to READY are satisfied."""
        assert_can_promote_to_ready(
            current_state=current_state,
            step_evidence_states=step_evidence_states,
        )

    @classmethod
    def guard_transition(
        cls,
        current_state: MissionState | str,
        target_state: MissionState | str,
        *,
        step_evidence_states: Iterable[StepEvidenceState | str] | None = None,
    ) -> MissionState:
        """Guard and return the new validated target state, failing closed on any violation.

        If target_state is READY, step_evidence_states must be supplied and all
        steps must be VERIFIED.
        """
        src = _normalize_mission_state(current_state)
        dst = _normalize_mission_state(target_state)

        # First assert basic transition legality
        assert_valid_transition(src, dst)

        # If entering READY, strictly enforce evidence verification
        if dst == MissionState.READY:
            if step_evidence_states is None:
                raise IllegalStatePromotionError(
                    "Promotion to READY requires step_evidence_states; none was provided."
                )
            assert_can_promote_to_ready(
                current_state=src,
                step_evidence_states=step_evidence_states,
            )

        return dst
