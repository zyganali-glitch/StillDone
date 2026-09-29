"""Canonical mission lifecycle and step evidence states.

Defines the exact provider-neutral vocabulary and semantic contracts for
mission states and step evidence states as specified in docs/PRODUCT_CONTRACT.md.
Does NOT implement state mutation, transition execution, or guard engines (deferred to P-03.03).
"""

from __future__ import annotations

from enum import StrEnum


class MissionState(StrEnum):
    """Canonical lifecycle states for a StillDone mission.

    Exactly 10 states as defined by the canonical product contract.
    Completion (READY) is an observable, renewable state—not permanent.
    """

    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    VERIFYING = "VERIFYING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    DRIFTED = "DRIFTED"
    CANCELLED = "CANCELLED"


class StepEvidenceState(StrEnum):
    """Canonical step evidence states for action and verification steps.

    Core StillDone invariants:
    - NOT_RUN is never PASS.
    - Execution success alone yields at most EXECUTED_UNVERIFIED.
    - VERIFIED requires independent read-back observation.
    - CONTRADICTED is distinct from FAILED.
    - BLOCKED is distinct from FAILED.
    - STALE means historical verification has expired freshness.
    """

    NOT_RUN = "NOT_RUN"
    EXECUTED_UNVERIFIED = "EXECUTED_UNVERIFIED"
    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    STALE = "STALE"


# Declarative contract metadata documenting allowable transitions.
# NOTE: Runtime enforcement and state guards are strictly deferred to P-03.03.
# No mutating methods or transition authorization engines are implemented here.
DECLARATIVE_MISSION_TRANSITIONS: frozenset[tuple[MissionState, MissionState]] = frozenset(
    {
        (MissionState.DRAFT, MissionState.PLANNED),
        (MissionState.DRAFT, MissionState.CANCELLED),
        (MissionState.PLANNED, MissionState.EXECUTING),
        (MissionState.PLANNED, MissionState.NEEDS_APPROVAL),
        (MissionState.PLANNED, MissionState.CANCELLED),
        (MissionState.NEEDS_APPROVAL, MissionState.EXECUTING),
        (MissionState.NEEDS_APPROVAL, MissionState.CANCELLED),
        (MissionState.EXECUTING, MissionState.VERIFYING),
        (MissionState.EXECUTING, MissionState.PARTIAL),
        (MissionState.EXECUTING, MissionState.FAILED),
        (MissionState.VERIFYING, MissionState.READY),
        (MissionState.VERIFYING, MissionState.PARTIAL),
        (MissionState.VERIFYING, MissionState.FAILED),
        (MissionState.READY, MissionState.DRIFTED),
        (MissionState.DRIFTED, MissionState.VERIFYING),
        (MissionState.DRIFTED, MissionState.EXECUTING),
        (MissionState.DRIFTED, MissionState.CANCELLED),
        (MissionState.PARTIAL, MissionState.EXECUTING),
        (MissionState.PARTIAL, MissionState.CANCELLED),
    }
)
