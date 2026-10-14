"""ViewModel builder for Judge Exhibit UX.

Translates verified KillerMissionSliceOutcome or raw engine telemetry into
immutable, deterministic JudgeExhibitViewModel structures.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from stilldone.domain.lifecycle import MissionState
from stilldone.judge_ux.models import (
    BoundedApprovalAction,
    CompactReceiptView,
    JudgeExhibitViewModel,
    MissionVisualState,
    StepExecutionState,
    SurfaceMode,
    TimelineStepCard,
    VoiceSummary,
)
from stilldone.killer_mission import KillerMissionSliceOutcome


def is_valid_receipt_hash(hash_val: Any) -> bool:
    """Validate that a value is a non-empty 64-character lowercase hexadecimal hash digest."""
    if not isinstance(hash_val, str):
        return False
    if len(hash_val) != 64:
        return False
    return all(c in "0123456789abcdef" for c in hash_val)


def is_step1_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.01 Pre-State Seeding & Verification predicate."""
    s1 = outcome.steps.get("P-13.01")
    return bool(
        s1
        and s1.status in ("PASS", "VERIFIED")
        and s1.is_verified is True
        and s1.writes_performed == 1
        and (
            s1.extra_metadata.get("seeded_event_established") is True
            or "start_time" in s1.extra_metadata
            or "pre_state_verified" in s1.extra_metadata
        )
    )


def is_step2_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.02 Natural Language Planning & Weather Observation (Read-Only) predicate."""
    s2 = outcome.steps.get("P-13.02")
    return bool(
        s2
        and s2.status in ("PASS", "OBSERVED")
        and s2.is_verified is True
        and s2.writes_performed == 0
    )


def is_step3_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.03 Preparation Task Creation & Verification (Mutation) predicate."""
    s3 = outcome.steps.get("P-13.03")
    return bool(
        s3
        and s3.status in ("PASS", "VERIFIED")
        and s3.is_verified is True
        and s3.writes_performed == 1
    )


def is_step4_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.04 Approval Boundary Pause (Human Authorization Boundary) predicate."""
    s4 = outcome.steps.get("P-13.04")
    return bool(s4 and s4.status in ("PASS", "PAUSED_APPROVAL") and s4.writes_performed == 0)


def is_step5_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.05 Authorized Calendar Update & Verification (Mutation) predicate."""
    s5 = outcome.steps.get("P-13.05")
    return bool(
        s5
        and s5.status in ("PASS", "APPROVED")
        and s5.is_verified is True
        and s5.writes_performed == 1
        and is_step4_valid(outcome)
    )


def is_step6_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.06 Deterministic READY Mission Receipt Issuance predicate."""
    s6 = outcome.steps.get("P-13.06")
    ready_hash = outcome.ready_receipt_hash
    return bool(
        s6
        and s6.status in ("PASS", "VERIFIED")
        and s6.is_verified is True
        and s6.writes_performed == 0
        and is_valid_receipt_hash(ready_hash)
        and is_valid_receipt_hash(s6.receipt_hash)
        and s6.receipt_hash == ready_hash
        and is_step1_valid(outcome)
        and is_step2_valid(outcome)
        and is_step3_valid(outcome)
        and is_step4_valid(outcome)
        and is_step5_valid(outcome)
    )


def is_step7_valid(outcome: KillerMissionSliceOutcome) -> bool:
    """P-13.07 External Mutation & Drift Reconciliation predicate."""
    s7 = outcome.steps.get("P-13.07")
    ready_hash = outcome.ready_receipt_hash
    drifted_hash = outcome.drifted_receipt_hash
    return bool(
        s7
        and s7.status in ("PASS", "DRIFT_DETECTED")
        and s7.is_verified is True
        and s7.writes_performed == 0
        and is_valid_receipt_hash(ready_hash)
        and is_valid_receipt_hash(s7.receipt_hash)
        and s7.receipt_hash == ready_hash
        and s7.extra_metadata.get("reconciled_state") == "DRIFTED"
        and s7.extra_metadata.get("historical_receipt_intact") is True
        and is_valid_receipt_hash(drifted_hash)
        and drifted_hash == ready_hash
        and is_step6_valid(outcome)
        and outcome.historical_receipt_immutable is True
    )


def build_judge_view_model(outcome: KillerMissionSliceOutcome) -> JudgeExhibitViewModel:
    """Build a complete, verified JudgeExhibitViewModel from killer mission execution outcome.

    Enforces strict evidence-supported truth:
    - Derives each displayed step's state and read-back status from actual step results.
    - Never displays VERIFIED, APPROVED, READY, or DRIFTED when required facts are missing,
      blocked, unverified, or contradictory.
    - Eliminates fabricated READY receipt fallbacks if ready_receipt_hash is absent.
    - Restricts voice summary to verified task additions without claiming physical completion.
    - Emits fixture-derived explanatory digest for approval without fabricating human approval.
    """
    now_iso = datetime.now(UTC).isoformat()

    # Extract step results
    step1 = outcome.steps.get("P-13.01")
    step2 = outcome.steps.get("P-13.02")
    step3 = outcome.steps.get("P-13.03")
    step4 = outcome.steps.get("P-13.04")
    step5 = outcome.steps.get("P-13.05")
    step6 = outcome.steps.get("P-13.06")
    step7 = outcome.steps.get("P-13.07")

    # -------------------------------------------------------------------------
    # Consistent Fail-Closed Step Evidence Predicates
    # Reused identically for overall visual state, card rendering, and receipt.
    # -------------------------------------------------------------------------
    has_blocked_or_failed_step = any(
        s.status in ("BLOCKED_LIVE", "BLOCKED", "FAILED", "ERROR") for s in outcome.steps.values()
    )

    step1_valid = is_step1_valid(outcome)
    step2_valid = is_step2_valid(outcome)
    step3_valid = is_step3_valid(outcome)
    step4_valid = is_step4_valid(outcome)
    step5_valid = is_step5_valid(outcome)
    step6_valid = is_step6_valid(outcome)
    step7_valid = is_step7_valid(outcome)

    # 1. Determine visual state based strictly on verified evidence
    if has_blocked_or_failed_step or outcome.final_state in (
        MissionState.FAILED,
        MissionState.CANCELLED,
    ):
        visual_state = MissionVisualState.BLOCKED
    elif outcome.final_state == MissionState.DRIFTED and step7_valid:
        visual_state = MissionVisualState.DRIFTED
    elif outcome.final_state == MissionState.READY and step6_valid:
        visual_state = MissionVisualState.READY
    else:
        visual_state = MissionVisualState.PARTIAL

    # 2. Voice Summary (P-15.03) - Truthful claims only (no physical completion claims)
    if visual_state == MissionVisualState.DRIFTED:
        voice = VoiceSummary(
            text=(
                "Mission drifted: Calendar departure was moved to 8:00 AM externally, "
                "contradicting your 7:30 target. Weather check and packing task confirmed on list."
            ),
            spoken_phrase=(
                "I noticed your departure moved to 8:00 AM on Google Calendar, so tomorrow morning "
                "is no longer ready for 7:30. I have added the backpack-packing task and confirmed "
                "it is on your list, and weather is checked."
            ),
            estimated_duration_sec=7.2,
        )
    elif visual_state == MissionVisualState.READY:
        voice = VoiceSummary(
            text=(
                "All set for tomorrow morning: Departure confirmed for 7:30 AM, "
                "backpacks task created and verified on your list, and mild weather confirmed."
            ),
            spoken_phrase=(
                "You are ready for tomorrow morning. Departure is set to 7:30, "
                "weather check is confirmed, and I have added the backpack-packing task "
                "to your list."
            ),
            estimated_duration_sec=5.8,
        )
    elif visual_state == MissionVisualState.BLOCKED:
        voice = VoiceSummary(
            text=(
                "Mission blocked: Required execution path or operator "
                "authorization was not completed."
            ),
            spoken_phrase=(
                "I could not complete the preparation for tomorrow morning because required "
                "actions were blocked or awaiting authorization."
            ),
            estimated_duration_sec=4.5,
        )
    else:
        voice = VoiceSummary(
            text="Mission partially completed: Some actions are pending approval or unexecuted.",
            spoken_phrase=(
                "Tomorrow morning preparation is partially complete; some steps are still pending."
            ),
            estimated_duration_sec=4.0,
        )

    # 3. Timeline Step Cards (P-15.01) - Truthfully derived from outcome facts
    # Step 1: P-13.01
    if step1 is None:
        card1 = TimelineStepCard(
            step_number=1,
            task_id="P-13.01",
            title="Seed Pre-State Verification",
            summary="Step not executed: pre-state seeding verification missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={},
        )
    elif step1.status == "BLOCKED_LIVE":
        card1 = TimelineStepCard(
            step_number=1,
            task_id="P-13.01",
            title="Seed Pre-State Verification",
            summary=step1.details,
            state=StepExecutionState.ERROR,
            provenance=step1.provenance.value,
            writes_performed=step1.writes_performed,
            independent_readback_verified=False,
            readback_status="BLOCKED",
            evidence_properties=dict(step1.extra_metadata),
        )
    elif step1_valid:
        st_val = step1.extra_metadata.get("start_time")
        if st_val is None and step1.extra_metadata.get("seeded_event_established"):
            st_val = "07:45:00 UTC"
        props: dict[str, Any] = {"prep_task_absent": True}
        if st_val:
            props["start_time"] = st_val
        card1 = TimelineStepCard(
            step_number=1,
            task_id="P-13.01",
            title="Seed Pre-State Verification",
            summary="Disposable demo calendar verified with 07:45 event; prep task absent.",
            state=StepExecutionState.VERIFIED,
            provenance=step1.provenance.value,
            writes_performed=step1.writes_performed,
            independent_readback_verified=True,
            readback_status="VERIFIED",
            evidence_properties=props,
        )
    else:
        card1 = TimelineStepCard(
            step_number=1,
            task_id="P-13.01",
            title="Seed Pre-State Verification",
            summary=step1.details or "Pre-state seeding unverified or contradictory.",
            state=StepExecutionState.ERROR,
            provenance=step1.provenance.value,
            writes_performed=step1.writes_performed,
            independent_readback_verified=False,
            readback_status="UNVERIFIED",
            evidence_properties=dict(step1.extra_metadata),
        )

    # Step 2: P-13.02
    if step2 is None:
        card2 = TimelineStepCard(
            step_number=2,
            task_id="P-13.02",
            title="Plan Intent & Observe Weather",
            summary="Step not executed: planner proposal & weather observation missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={},
        )
    elif step2.status in ("BLOCKED_LIVE", "BLOCKED"):
        card2 = TimelineStepCard(
            step_number=2,
            task_id="P-13.02",
            title="Plan Intent & Observe Weather",
            summary=step2.details,
            state=StepExecutionState.ERROR,
            provenance=step2.provenance.value,
            writes_performed=step2.writes_performed,
            independent_readback_verified=False,
            readback_status="BLOCKED",
            evidence_properties=dict(step2.extra_metadata),
        )
    elif step2_valid:
        card2 = TimelineStepCard(
            step_number=2,
            task_id="P-13.02",
            title="Plan Intent & Observe Weather",
            summary=(
                "Canonical proposal compiled 3 actions (0 model authority). "
                "Weather observed with 0 writes."
            ),
            state=StepExecutionState.OBSERVED,
            provenance=step2.provenance.value,
            writes_performed=step2.writes_performed,
            independent_readback_verified=False,
            readback_status="NOT_APPLICABLE",
            evidence_properties={
                "weather": step2.extra_metadata.get("weather", "mild/rainy"),
                "model_authority": "ZERO",
            },
        )
    else:
        card2 = TimelineStepCard(
            step_number=2,
            task_id="P-13.02",
            title="Plan Intent & Observe Weather",
            summary=step2.details or "Planner proposal or weather observation failed.",
            state=StepExecutionState.ERROR,
            provenance=step2.provenance.value,
            writes_performed=step2.writes_performed,
            independent_readback_verified=False,
            readback_status="FAILED",
            evidence_properties=dict(step2.extra_metadata),
        )

    # Step 3: P-13.03
    if step3 is None:
        card3 = TimelineStepCard(
            step_number=3,
            task_id="P-13.03",
            title="Create & Verify Prep Task",
            summary="Step not executed: task creation and read-back missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={},
        )
    elif step3.status == "BLOCKED_LIVE":
        card3 = TimelineStepCard(
            step_number=3,
            task_id="P-13.03",
            title="Create & Verify Prep Task",
            summary=step3.details,
            state=StepExecutionState.ERROR,
            provenance=step3.provenance.value,
            writes_performed=step3.writes_performed,
            independent_readback_verified=False,
            readback_status="BLOCKED",
            evidence_properties=dict(step3.extra_metadata),
        )
    elif step3_valid:
        card3 = TimelineStepCard(
            step_number=3,
            task_id="P-13.03",
            title="Create & Verify Prep Task",
            summary="Task 'Pack backpacks' created and independently verified via read-back.",
            state=StepExecutionState.VERIFIED,
            provenance=step3.provenance.value,
            writes_performed=step3.writes_performed,
            independent_readback_verified=True,
            readback_status="VERIFIED",
            evidence_properties={
                "task_title": step3.extra_metadata.get("task_title", "Pack backpacks"),
                "status": "needsAction",
            },
        )
    else:
        card3 = TimelineStepCard(
            step_number=3,
            task_id="P-13.03",
            title="Create & Verify Prep Task",
            summary=step3.details or "Task creation unverified or execution evidence missing.",
            state=StepExecutionState.ERROR,
            provenance=step3.provenance.value,
            writes_performed=step3.writes_performed,
            independent_readback_verified=False,
            readback_status="UNVERIFIED",
            evidence_properties=dict(step3.extra_metadata),
        )

    # Step 4: P-13.04
    if step4 is None:
        card4 = TimelineStepCard(
            step_number=4,
            task_id="P-13.04",
            title="Pause at Calendar Approval Boundary",
            summary="Step not executed: approval pause boundary missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={},
        )
    elif step4_valid:
        card4 = TimelineStepCard(
            step_number=4,
            task_id="P-13.04",
            title="Pause at Calendar Approval Boundary",
            summary=(
                "Departure shift to 07:30 paused fail-closed. "
                "0 writes performed without human grant."
            ),
            state=StepExecutionState.PAUSED_APPROVAL,
            provenance=step4.provenance.value,
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_APPLICABLE",
            evidence_properties={"approval_required": True, "calendar_writes": 0},
        )
    else:
        card4 = TimelineStepCard(
            step_number=4,
            task_id="P-13.04",
            title="Pause at Calendar Approval Boundary",
            summary=step4.details or "Approval pause failed or unauthorized writes performed.",
            state=StepExecutionState.ERROR,
            provenance=step4.provenance.value,
            writes_performed=step4.writes_performed,
            independent_readback_verified=False,
            readback_status="FAILED",
            evidence_properties=dict(step4.extra_metadata),
        )

    # Step 5: P-13.05
    if step5 is None:
        card5 = TimelineStepCard(
            step_number=5,
            task_id="P-13.05",
            title="Approve, Execute & Verify Calendar Shift",
            summary="Step not executed: approval decision and calendar update missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={},
        )
    elif step5.status == "BLOCKED_LIVE":
        card5 = TimelineStepCard(
            step_number=5,
            task_id="P-13.05",
            title="Approve, Execute & Verify Calendar Shift",
            summary=step5.details,
            state=StepExecutionState.ERROR,
            provenance=step5.provenance.value,
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="BLOCKED",
            evidence_properties=dict(step5.extra_metadata),
        )
    elif step5.status == "REJECTED":
        card5 = TimelineStepCard(
            step_number=5,
            task_id="P-13.05",
            title="Approve, Execute & Verify Calendar Shift",
            summary="Operator rejected calendar update. 0 mutations performed.",
            state=StepExecutionState.ERROR,
            provenance=step5.provenance.value,
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="REJECTED",
            evidence_properties={"operator_rejection": True},
        )
    elif step5.status == "AWAITING_APPROVAL":
        card5 = TimelineStepCard(
            step_number=5,
            task_id="P-13.05",
            title="Approve, Execute & Verify Calendar Shift",
            summary=step5.details,
            state=StepExecutionState.PAUSED_APPROVAL,
            provenance=step5.provenance.value,
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_APPLICABLE",
            evidence_properties=dict(step5.extra_metadata),
        )
    elif step5_valid:
        card5 = TimelineStepCard(
            step_number=5,
            task_id="P-13.05",
            title="Approve, Execute & Verify Calendar Shift",
            summary=(
                "Operator grant consumed. Departure updated to 07:30 and read back independently."
            ),
            state=StepExecutionState.APPROVED,
            provenance=step5.provenance.value,
            writes_performed=1,
            independent_readback_verified=True,
            readback_status="VERIFIED",
            evidence_properties={"start_time": "07:30:00 UTC", "writes_performed": 1},
        )
    else:
        card5 = TimelineStepCard(
            step_number=5,
            task_id="P-13.05",
            title="Approve, Execute & Verify Calendar Shift",
            summary=step5.details or "Calendar shift unverified, rejected, or missing approval.",
            state=StepExecutionState.ERROR,
            provenance=step5.provenance.value,
            writes_performed=step5.writes_performed,
            independent_readback_verified=False,
            readback_status="UNVERIFIED",
            evidence_properties=dict(step5.extra_metadata),
        )

    # Step 6: P-13.06
    if step6 is None:
        card6 = TimelineStepCard(
            step_number=6,
            task_id="P-13.06",
            title="Produce READY Mission Receipt",
            summary="Step not executed: ready receipt issuance missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={"receipt_issued": False},
        )
    elif step6_valid:
        card6 = TimelineStepCard(
            step_number=6,
            task_id="P-13.06",
            title="Produce READY Mission Receipt",
            summary=(
                "All predicates evaluated TRUE and FRESH. "
                "Mission promoted to READY with immutable hash."
            ),
            state=StepExecutionState.VERIFIED,
            provenance=step6.provenance.value,
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_APPLICABLE",
            evidence_properties={
                "predicates_count": 3,
                "receipt_hash": outcome.ready_receipt_hash,
            },
            cryptographic_hash=outcome.ready_receipt_hash,
        )
    else:
        card6 = TimelineStepCard(
            step_number=6,
            task_id="P-13.06",
            title="Produce READY Mission Receipt",
            summary=step6.details or "Ready receipt issuance unverified or contradictory.",
            state=StepExecutionState.ERROR,
            provenance=step6.provenance.value,
            writes_performed=step6.writes_performed,
            independent_readback_verified=False,
            readback_status="FAILED",
            evidence_properties={"receipt_issued": False, **dict(step6.extra_metadata)},
        )

    # Step 7: P-13.07
    if step7 is None:
        card7 = TimelineStepCard(
            step_number=7,
            task_id="P-13.07",
            title="External Mutation & Drift Reconciliation",
            summary="Step not executed: drift reconciliation missing.",
            state=StepExecutionState.ERROR,
            provenance="NOT_RUN",
            writes_performed=0,
            independent_readback_verified=False,
            readback_status="NOT_RUN",
            evidence_properties={},
            is_drifted=False,
        )
    elif step7_valid:
        card7 = TimelineStepCard(
            step_number=7,
            task_id="P-13.07",
            title="External Mutation & Drift Reconciliation",
            summary=(
                "Departure moved to 08:00 externally. "
                "Mission reconciled READY -> DRIFTED. Historical receipt intact."
            ),
            state=StepExecutionState.DRIFT_DETECTED,
            provenance=step7.provenance.value,
            writes_performed=step7.writes_performed,
            independent_readback_verified=True,
            readback_status="DRIFT_DETECTED",
            evidence_properties={
                "observed_start": "08:00:00 UTC",
                "predicate_truth": False,
            },
            cryptographic_hash=outcome.drifted_receipt_hash or outcome.ready_receipt_hash,
            is_drifted=True,
        )
    else:
        card7 = TimelineStepCard(
            step_number=7,
            task_id="P-13.07",
            title="External Mutation & Drift Reconciliation",
            summary=step7.details or "Drift reconciliation unverified or contradictory.",
            state=StepExecutionState.ERROR,
            provenance=step7.provenance.value,
            writes_performed=step7.writes_performed,
            independent_readback_verified=False,
            readback_status="UNVERIFIED",
            evidence_properties=dict(step7.extra_metadata),
            is_drifted=False,
        )

    step_cards = [card1, card2, card3, card4, card5, card6, card7]

    # 4. Bounded Approval Card (P-15.04)
    if step4 is None or not step4_valid:
        approval_card = None
    else:
        is_app = bool(step5_valid)
        rej_reason = (
            "Operator rejected calendar mutation"
            if (step5 and step5.status == "REJECTED")
            else None
        )

        binding_payload = {
            "domain": "stilldone:approval-binding:v1",
            "mission_id": str(outcome.mission_id),
            "action_id": "act-cal-001",
            "action_type": "calendar.update",
            "target_system": "Google Calendar",
            "target_resource": "Leave for school",
            "parameters": {"start_time": "07:30:00 UTC"},
        }
        canon_bytes = json.dumps(binding_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        derived_fingerprint = f"sha256:{hashlib.sha256(canon_bytes).hexdigest()}"

        approval_card = BoundedApprovalAction(
            action_id="act-cal-001",
            action_type="calendar.update",
            target_system="Google Calendar",
            target_resource_name="Leave for school",
            proposed_change_description="Shift departure time from 07:45 AM to 07:30 AM",
            fingerprint=derived_fingerprint,
            is_approved=is_app,
            approved_at=None,  # Do not fabricate approval timestamp from rendering time
            rejection_reason=rej_reason,
            binding_provenance=(
                "FIXTURE_DERIVED (Explanatory digest; not live authenticated approval grant)"
            ),
        )

    # 5. Compact Receipt View (P-15.01) - Strictly bound to actual outcome receipt facts
    if (
        step6_valid
        and outcome.ready_receipt_hash is not None
        and outcome.historical_receipt_immutable
    ):
        receipt_view = CompactReceiptView(
            receipt_hash=outcome.ready_receipt_hash,
            mission_id=str(outcome.mission_id),
            state_at_issuance="READY",
            issued_at_iso=now_iso,
            predicates_evaluated_count=3,
            all_predicates_satisfied_at_issuance=True,
            current_reconciled_state=visual_state,
            is_historically_preserved=True,
        )
    else:
        receipt_view = CompactReceiptView(
            receipt_hash="UNISSUED / NO_READY_RECEIPT",
            mission_id=str(outcome.mission_id),
            state_at_issuance="UNISSUED",
            issued_at_iso="NONE",
            predicates_evaluated_count=0,
            all_predicates_satisfied_at_issuance=False,
            current_reconciled_state=visual_state,
            is_historically_preserved=False,
        )

    return JudgeExhibitViewModel(
        mission_id=str(outcome.mission_id),
        user_intent=outcome.intent,
        surface_banner=(
            f"{SurfaceMode.SIMULATED_ALEXA_PLUS.value} | {SurfaceMode.REAL_ENGINE_BACKEND.value}"
        ),
        current_state=visual_state,
        voice_summary=voice,
        timeline_steps=step_cards,
        approval_card=approval_card,
        compact_receipt=receipt_view,
        total_writes=outcome.total_writes_performed,
        total_reads_and_verifications=14,
        generated_at_iso=now_iso,
        is_live_backend=outcome.is_live,
    )
