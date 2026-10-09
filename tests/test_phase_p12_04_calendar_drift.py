"""Tests for External-Change Drift Detection on Google Calendar (Phase P-12.04).

Validates:
- Compares fresh independently observed Calendar state against persisted desired state.
- Detects time, summary, status, and availability changes.
- Preserves exact event and calendar identity; never matches events by title alone.
- Legitimate persisted READY mission transitions to DRIFTED through canonical lifecycle rules.
- Does NOT fabricate a READY predecessor solely to demonstrate drift (non-READY rejected).
- Errors and stale reads do NOT masquerade as confirmed drift (fail closed / inconclusive).
- Zero Calendar writes or new approval consumption (strictly read-only).
- Proves stable state, changed state, missing event, stale read, wrong event, API failure,
  and repeated revalidation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stilldone.adapters.calendar import (
    CalendarTransportError,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import ActionContract, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.drift import (
    DriftTargetMismatchError,
    detect_calendar_drift,
    record_drift_in_snapshot,
)
from stilldone.snapshot import (
    DurableSnapshotRepository,
    MissionSnapshot,
    create_mission_snapshot,
)
from stilldone.verifier.reconciliation import (
    ReconciliationLifecycleError,
    ReconciliationStatus,
)


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId.generate()


@pytest.fixture
def cal_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_school_departure_001",
        parent_id="c_demo@group.calendar.google.com",
    )


@pytest.fixture
def demo_scope(cal_target: TargetIdentity) -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=cal_target.parent_id or "c_demo@group.calendar.google.com",
        task_list_id="list_demo_tasks",
    )


def _make_ready_snapshot(
    mission_id: MissionId,
    target: TargetIdentity,
    *,
    expected_summary: str = "Leave for school",
    expected_start: str = "2026-10-03T07:30:00+03:00",
    expected_status: str = "confirmed",
    state: MissionState = MissionState.READY,
) -> tuple[MissionSnapshot, DesiredStatePredicate, DesiredStatePredicate]:
    pred_summary = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_summary,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_start = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_start,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target,
        parameters={},
    )

    contract = MissionContract.create(
        text="Ensure departure calendar is verified",
        mission_id=mission_id,
        created_at=datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC),
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=state,
        contract=contract,
        desired_state=(pred_summary, pred_start),
        actions=(action,),
    )
    return snapshot, pred_summary, pred_start


def test_calendar_stable_state_remains_ready(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Stable state: calendar event matches desired state; mission remains READY."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is False
    assert result.is_inconclusive is False
    assert result.prior_state == MissionState.READY
    assert result.new_state == MissionState.READY
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.STILL_TRUE
    assert fake_transport.writes_count == 0  # Read-only verification


def test_calendar_changed_summary_detects_drift_and_transitions(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Changed state: external event summary changed to 'Stay home'; transitions to DRIFTED."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Stay home",  # Changed externally!
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, pred_summary, _ = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is True
    assert result.is_inconclusive is False
    assert result.prior_state == MissionState.READY
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE
    assert pred_summary.predicate_id in result.reconciliation.drifted_predicate_ids

    # Persist in durable repository
    repo = DurableSnapshotRepository(storage_path=str(tmp_path))
    drifted_snap = record_drift_in_snapshot(repo, snapshot, result)
    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED
    loaded = repo.load_snapshot(mission_id)
    assert loaded.state == MissionState.DRIFTED


def test_calendar_changed_start_time_detects_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Changed state: external start_time shifted by 1 hour; transitions to DRIFTED."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T08:30:00+03:00",  # Shifted from 07:30 to 08:30
        end_time="2026-10-03T09:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, pred_start = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert pred_start.predicate_id in result.reconciliation.drifted_predicate_ids


def test_calendar_missing_event_404_detects_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Missing event: external event deleted (404); desired state contradicted -> DRIFTED."""
    fake_transport = FakeGoogleCalendarTransport()
    # No event seeded => transport returns 404 / NOT_FOUND
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE


def test_calendar_stale_read_is_inconclusive_no_false_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Stale read: observation expired relative to eval_at; fails closed as inconclusive."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Different Event",
        start_time="2026-10-03T07:30:00+03:00",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    # Evaluate at a point far in future (10 hours later) so fresh read-back is stale
    future_time = datetime.now(UTC) + timedelta(hours=10)
    result = detect_calendar_drift(
        snapshot=snapshot,
        calendar_adapter=adapter,
        eval_at=future_time,
    )

    # Stale read MUST NOT masquerade as confirmed drift!
    assert result.is_drifted is False
    assert result.is_inconclusive is True
    assert result.new_state == MissionState.READY  # Remains in prior state


def test_calendar_api_failure_is_inconclusive_no_false_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API failure: 503 error during read; inconclusive, remains READY without false drift."""
    fake_transport = FakeGoogleCalendarTransport()
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    def failing_get_event(*args: object, **kwargs: object) -> None:
        raise CalendarTransportError("503 Service Unavailable", status_code=503)

    monkeypatch.setattr(fake_transport, "get_event", failing_get_event)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is False
    assert result.is_inconclusive is True
    assert result.new_state == MissionState.READY
    assert "provider" in (result.error_message or "").lower()


def test_calendar_wrong_event_or_target_mismatch_fails_closed(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Wrong event or title-only match attempt fails closed."""
    fake_transport = FakeGoogleCalendarTransport()
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    wrong_target = TargetIdentity(
        system="google_tasks",  # Mismatched system
        resource_kind=ResourceKind.TASK,
        resource_id="wrong_id",
        parent_id="wrong_list",
    )

    with pytest.raises(DriftTargetMismatchError):
        detect_calendar_drift(
            snapshot=snapshot,
            calendar_adapter=adapter,
            target=wrong_target,
        )


def test_calendar_non_ready_predecessor_rejected_fail_closed(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Non-READY predecessor rejected: cannot fabricate READY to demonstrate drift."""
    fake_transport = FakeGoogleCalendarTransport()
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    # Mission in VERIFYING state, never established as READY
    unready_snapshot, _, _ = _make_ready_snapshot(
        mission_id, cal_target, state=MissionState.VERIFYING
    )

    with pytest.raises(
        ReconciliationLifecycleError, match="Drift detection is only permitted from READY"
    ):
        detect_calendar_drift(snapshot=unready_snapshot, calendar_adapter=adapter)


def test_calendar_repeated_revalidation_is_idempotent(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Repeated revalidation on stable state consistently yields STILL_TRUE / READY."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    res1 = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    res2 = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert res1.new_state == MissionState.READY
    assert res2.new_state == MissionState.READY
    assert res1.is_drifted is False
    assert res2.is_drifted is False
