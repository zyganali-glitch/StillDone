"""Tests for duplicate detection and duplicate evidence state (Phase P-10.04).

Enforces StillDone core architectural laws:
- Provider-neutral contract distinguishes:
  * EFFECT_ABSENT
  * INTENDED_EFFECT_EXISTS
  * DUPLICATE_DETECTED
  * DETERMINATION_INCONCLUSIVE
- Duplicate determination must be evidence-backed from independent external observation.
- Never infer duplicate truth from executor success prose or solely from an idempotency key.
- Binds duplicate evidence to canonical mission, action, target, and IntendedMutationIdentity.
- Bounded independent read-back for TASK_CREATE.
- Zero raw provider payload leakage; sanitized deterministic evidence only.
- Model / planner output has ZERO authority.
"""

from __future__ import annotations

import pytest

from stilldone.adapters.calendar import (
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksDuplicateDetector,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId
from stilldone.ledger import EvidenceRecord
from stilldone.planning.contracts import PlannerInput
from stilldone.recovery.duplicate import (
    DuplicateDeterminationStatus,
    DuplicateEvidenceRecord,
    GoogleCalendarEffectDetectorAdapter,
    GoogleTasksDuplicateDetectorAdapter,
    derive_intended_mutation_identity,
)
from stilldone.recovery.idempotency import PlannerRecoveryAuthorityError
from stilldone.recovery.orchestrator import (
    RecoveryActionType,
    RecoveryOrchestrator,
)

DEMO_SCOPE = DemoResourceScope(
    calendar_id="demo_cal@example.com",
    task_list_id="demo_tasks_123",
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK_LIST,
    resource_id="demo_tasks_123",
    parent_id=None,
)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_xyz",
    parent_id="demo_cal@example.com",
)


def _make_task_create_action(
    title: str = "Pack snacks", due: str | None = "2026-10-10"
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TASKS_TARGET,
        parameters={"title": title, "due": due},
    )


def _make_calendar_update_action(
    summary: str = "Family Briefing", start: str = "2026-10-08T07:00:00Z"
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_UPDATE,
        target=CAL_TARGET,
        parameters={"summary": summary, "start_time": start},
    )


class TestIntendedMutationIdentity:
    """Verifies deterministic IntendedMutationIdentity derivation and invariants."""

    def test_identical_action_produces_identical_mutation_identity(self) -> None:
        action1 = _make_task_create_action("Pack lunch")
        # Same action details
        ident1 = derive_intended_mutation_identity(action1)
        ident2 = derive_intended_mutation_identity(action1)

        assert ident1.mutation_id == ident2.mutation_id
        assert ident1.idempotency_key == ident2.idempotency_key
        assert ident1.parameters_digest == ident2.parameters_digest
        assert ident1.action_id == action1.action_id
        assert ident1.mission_id == action1.mission_id

    def test_different_parameters_produce_different_mutation_id(self) -> None:
        action1 = _make_task_create_action("Pack lunch")
        action2 = ActionContract.create(
            mission_id=action1.mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack breakfast"},
        )
        ident1 = derive_intended_mutation_identity(action1)
        ident2 = derive_intended_mutation_identity(action2)

        assert ident1.mutation_id != ident2.mutation_id
        assert ident1.parameters_digest != ident2.parameters_digest

    def test_reject_planner_proposal_in_mutation_identity_derivation(self) -> None:
        planner_input = PlannerInput(mission_id=MissionId.generate(), intent="inject")
        with pytest.raises(PlannerRecoveryAuthorityError):
            derive_intended_mutation_identity(planner_input)  # type: ignore[arg-type]


class TestDuplicateEvidenceRecordInvariants:
    """Verifies evidence contract invariants and serialization."""

    def test_intended_effect_exists_requires_exactly_one_match(self) -> None:
        action = _make_task_create_action()
        ident = derive_intended_mutation_identity(action)

        # match_count=1 is valid
        rec = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
            intended_mutation=ident,
            match_count=1,
        )
        assert rec.match_count == 1

        # match_count != 1 fails closed
        with pytest.raises(ValueError, match="requires match_count == 1"):
            DuplicateEvidenceRecord(
                status=DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
                intended_mutation=ident,
                match_count=2,
            )

    def test_duplicate_detected_requires_at_least_two_matches(self) -> None:
        action = _make_task_create_action()
        ident = derive_intended_mutation_identity(action)

        rec = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.DUPLICATE_DETECTED,
            intended_mutation=ident,
            match_count=2,
        )
        assert rec.match_count == 2

        with pytest.raises(ValueError, match="requires match_count >= 2"):
            DuplicateEvidenceRecord(
                status=DuplicateDeterminationStatus.DUPLICATE_DETECTED,
                intended_mutation=ident,
                match_count=1,
            )

    def test_effect_absent_requires_zero_matches(self) -> None:
        action = _make_task_create_action()
        ident = derive_intended_mutation_identity(action)

        rec = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.EFFECT_ABSENT,
            intended_mutation=ident,
            match_count=0,
        )
        assert rec.match_count == 0

        with pytest.raises(ValueError, match="requires match_count == 0"):
            DuplicateEvidenceRecord(
                status=DuplicateDeterminationStatus.EFFECT_ABSENT,
                intended_mutation=ident,
                match_count=1,
            )

    def test_to_canonical_payload_and_evidence_record(self) -> None:
        action = _make_task_create_action()
        ident = derive_intended_mutation_identity(action)
        rec = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
            intended_mutation=ident,
            match_count=1,
            scanned_items=5,
            scanned_pages=1,
            matched_resource_id="task_abc",
        )

        payload = rec.to_canonical_payload()
        assert payload["status"] == "INTENDED_EFFECT_EXISTS"
        assert payload["mutation_id"] == ident.mutation_id
        assert payload["match_count"] == 1
        assert payload["scanned_items"] == 5
        assert payload["matched_resource_id"] == "task_abc"
        # Zero raw body leaks
        assert "Pack snacks" not in str(payload)

        # Canonical EvidenceRecord generation
        evidence = rec.to_evidence_record()
        assert isinstance(evidence, EvidenceRecord)
        assert evidence.action_id == action.action_id
        assert evidence.mission_id == action.mission_id
        assert evidence.payload["status"] == "INTENDED_EFFECT_EXISTS"


class TestGoogleTasksDuplicateDetectorAdapter:
    """Verifies integration with Tasks duplicate detector."""

    def test_tasks_adapter_detects_effect_absent(self) -> None:
        transport = FakeGoogleTasksTransport()
        detector = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        adapter = GoogleTasksDuplicateDetectorAdapter(detector=detector)

        action = _make_task_create_action("Pack medicine")
        rec = adapter.detect(action)

        assert rec.status == DuplicateDeterminationStatus.EFFECT_ABSENT
        assert rec.match_count == 0
        assert rec.scanned_items == 0

    def test_tasks_adapter_detects_intended_effect_exists(self) -> None:
        transport = FakeGoogleTasksTransport()
        # Seed 1 matching task
        transport.seed_task(
            task_list_id=DEMO_SCOPE.task_list_id,
            task_id="task_1",
            title="Pack medicine",
            due="2026-10-10",
        )
        detector = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        adapter = GoogleTasksDuplicateDetectorAdapter(detector=detector)

        action = _make_task_create_action("Pack medicine", due="2026-10-10")
        rec = adapter.detect(action)

        assert rec.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS
        assert rec.match_count == 1
        assert rec.scanned_items == 1

    def test_tasks_adapter_detects_duplicate(self) -> None:
        transport = FakeGoogleTasksTransport()
        # Seed 2 identical tasks
        transport.seed_task(
            task_list_id=DEMO_SCOPE.task_list_id,
            task_id="task_1",
            title="Pack medicine",
            due="2026-10-10",
        )
        transport.seed_task(
            task_list_id=DEMO_SCOPE.task_list_id,
            task_id="task_2",
            title="Pack medicine",
            due="2026-10-10",
        )
        detector = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        adapter = GoogleTasksDuplicateDetectorAdapter(detector=detector)

        action = _make_task_create_action("Pack medicine", due="2026-10-10")
        rec = adapter.detect(action)

        assert rec.status == DuplicateDeterminationStatus.DUPLICATE_DETECTED
        assert rec.match_count == 2
        assert rec.scanned_items == 2


class TestGoogleCalendarEffectDetectorAdapter:
    """Verifies integration with Google Calendar effect detection."""

    def test_calendar_adapter_detects_intended_effect_exists(self) -> None:
        transport = FakeGoogleCalendarTransport()
        # Seed calendar event with updated properties
        transport.seed_event(
            calendar_id=DEMO_SCOPE.calendar_id,
            event_id="event_xyz",
            summary="Family Briefing",
            start_time="2026-10-08T07:00:00Z",
            end_time="2026-10-08T07:30:00Z",
            all_day=False,
        )
        read_adapter = GoogleCalendarReadAdapter(scope=DEMO_SCOPE, transport=transport)
        adapter = GoogleCalendarEffectDetectorAdapter(read_adapter=read_adapter)

        action = _make_calendar_update_action(
            summary="Family Briefing", start="2026-10-08T07:00:00Z"
        )
        rec = adapter.detect(action)

        assert rec.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS
        assert rec.match_count == 1

    def test_calendar_adapter_detects_effect_absent_when_properties_differ(self) -> None:
        transport = FakeGoogleCalendarTransport()
        # Seed calendar event with OLD properties
        transport.seed_event(
            calendar_id=DEMO_SCOPE.calendar_id,
            event_id="event_xyz",
            summary="Old Morning Meeting",
            start_time="2026-10-08T06:00:00Z",
            end_time="2026-10-08T06:30:00Z",
            all_day=False,
        )
        read_adapter = GoogleCalendarReadAdapter(scope=DEMO_SCOPE, transport=transport)
        adapter = GoogleCalendarEffectDetectorAdapter(read_adapter=read_adapter)

        action = _make_calendar_update_action(
            summary="Family Briefing", start="2026-10-08T07:00:00Z"
        )
        rec = adapter.detect(action)

        assert rec.status == DuplicateDeterminationStatus.EFFECT_ABSENT
        assert rec.match_count == 0

    def test_calendar_adapter_inconclusive_when_event_not_found(self) -> None:
        transport = FakeGoogleCalendarTransport()
        read_adapter = GoogleCalendarReadAdapter(scope=DEMO_SCOPE, transport=transport)
        adapter = GoogleCalendarEffectDetectorAdapter(read_adapter=read_adapter)

        action = _make_calendar_update_action()
        rec = adapter.detect(action)

        assert rec.status == DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE
        assert rec.match_count == 0


class TestOrchestratorDuplicateIntegration:
    """Verifies that DuplicateEvidenceRecord bridges into RecoveryOrchestrator seamlessly."""

    def test_duplicate_evidence_bridges_to_orchestrator(self) -> None:
        orchestrator = RecoveryOrchestrator()
        action = _make_task_create_action("Pack shoes")
        ident = derive_intended_mutation_identity(action)

        # 1. INTENDED_EFFECT_EXISTS -> EFFECT_ALREADY_EXISTS
        rec_exists = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
            intended_mutation=ident,
            match_count=1,
        )
        d1 = orchestrator.evaluate_readback_outcome(
            action=action,
            attempt_number=1,
            readback_result=rec_exists.to_readback_result(),
        )
        assert d1.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS

        # 2. DUPLICATE_DETECTED -> DUPLICATE_PREVENTED
        rec_dup = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.DUPLICATE_DETECTED,
            intended_mutation=ident,
            match_count=2,
        )
        d2 = orchestrator.evaluate_readback_outcome(
            action=action,
            attempt_number=1,
            readback_result=rec_dup.to_readback_result(),
        )
        assert d2.action_type == RecoveryActionType.DUPLICATE_PREVENTED

        # 3. EFFECT_ABSENT -> RETRY
        rec_absent = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.EFFECT_ABSENT,
            intended_mutation=ident,
            match_count=0,
        )
        d3 = orchestrator.evaluate_readback_outcome(
            action=action,
            attempt_number=1,
            readback_result=rec_absent.to_readback_result(),
        )
        assert d3.action_type == RecoveryActionType.RETRY

        # 4. DETERMINATION_INCONCLUSIVE -> DO_NOT_RETRY (fail closed)
        rec_inconcl = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE,
            intended_mutation=ident,
            match_count=0,
            error_message="quota exceeded",
        )
        d4 = orchestrator.evaluate_readback_outcome(
            action=action,
            attempt_number=1,
            readback_result=rec_inconcl.to_readback_result(),
        )
        assert d4.action_type == RecoveryActionType.DO_NOT_RETRY
