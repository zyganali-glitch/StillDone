"""Data models for StillDone Judge UX & Simulated Alexa+ conversational surface.

Phase P-15:
- P-15.01: One-screen mission timeline and compact receipt
- P-15.02: Simulated Alexa+ conversational surface with explicit label
- P-15.03: Voice-friendly concise summaries
- P-15.04: Approval card with exact bounded action
- P-15.05: READY/PARTIAL/DRIFTED visual hierarchy
- P-15.06: Expandable evidence detail without overwhelming primary UX
- P-15.07: Accessible, responsive semantic design

Zero LLM authority: All UI data structures are deterministically computed from
verified engine facts, never from model hallucinations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SurfaceMode(StrEnum):
    """Execution surface mode for explicit label disclosure."""

    SIMULATED_ALEXA_PLUS = "SIMULATED ALEXA+ EXPERIENCE"
    REAL_ENGINE_BACKEND = "REAL STILLDONE ENGINE (STREAMABLE HTTP MCP)"


class MissionVisualState(StrEnum):
    """Visual state hierarchy for mission progress display."""

    READY = "READY"
    DRIFTED = "DRIFTED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"


class StepExecutionState(StrEnum):
    """Execution state for individual timeline steps."""

    VERIFIED = "VERIFIED"
    PAUSED_APPROVAL = "PAUSED_APPROVAL"
    APPROVED = "APPROVED"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    OBSERVED = "OBSERVED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VoiceSummary:
    """Concise, natural voice-friendly summary representation for Alexa+ speech."""

    text: str
    spoken_phrase: str
    estimated_duration_sec: float
    tone: str = "concise"


@dataclass(frozen=True)
class BoundedApprovalAction:
    """Exact bounded action requiring human authorization."""

    action_id: str
    action_type: str
    target_system: str
    target_resource_name: str
    proposed_change_description: str
    fingerprint: str
    is_approved: bool = False
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    binding_provenance: str = "FIXTURE_DERIVED"


@dataclass(frozen=True)
class TimelineStepCard:
    """A discrete timeline event on the one-screen mission timeline."""

    step_number: int
    task_id: str
    title: str
    summary: str
    state: StepExecutionState
    provenance: str  # FIXTURE / LOCAL_EXECUTION / LIVE_GOOGLE
    writes_performed: int
    independent_readback_verified: bool
    # "VERIFIED", "NOT_APPLICABLE", "DRIFT_DETECTED", "NOT_RUN"
    readback_status: str = "NOT_APPLICABLE"
    evidence_properties: dict[str, Any] = field(default_factory=dict)
    cryptographic_hash: str | None = None
    is_drifted: bool = False


@dataclass(frozen=True)
class CompactReceiptView:
    """Immutable compact receipt view clearly separated from current reality."""

    receipt_hash: str
    mission_id: str
    state_at_issuance: str
    issued_at_iso: str
    predicates_evaluated_count: int
    all_predicates_satisfied_at_issuance: bool
    current_reconciled_state: MissionVisualState
    is_historically_preserved: bool = True


@dataclass(frozen=True)
class JudgeExhibitViewModel:
    """Complete, self-contained view model for the Judge exhibit UX."""

    mission_id: str
    user_intent: str
    surface_banner: str
    current_state: MissionVisualState
    voice_summary: VoiceSummary
    timeline_steps: list[TimelineStepCard]
    approval_card: BoundedApprovalAction | None
    compact_receipt: CompactReceiptView
    total_writes: int
    total_reads_and_verifications: int
    generated_at_iso: str
    is_live_backend: bool = False
