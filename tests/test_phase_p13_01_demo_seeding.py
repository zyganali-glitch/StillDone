"""Unit and adversarial test suite for P-13.01 Demo Resource Seeding and Verification.

Validates:
- Enforces DemoResourceScope; strictly rejects primary/default aliases (WRONG_TARGET_REJECTED).
- Rejects non-DemoResourceScope instances with typed DemoScopeTypeError.
- Handles provider preflight failures (missing container -> BLOCKED_PREFLIGHT).
- Unauthorized mutation protection: permit_mutation=False stops fail-closed (0 writes).
- Idempotency: existing canonical event in pre-state returns VERIFIED_EXISTING with 0 writes;
  re-running seed maintains 0 writes and creates 0 duplicates.
- Duplicate contradiction: multiple events titled 'Leave for school' fail closed.
- Authorized creation: event missing with permit_mutation=True creates and reads back.
- Authorized reset: drifted event with permit_mutation=True updates and reads back.
- Missing read-back failure: post-write read-back returning None fails closed.
- Inconsistent read-back: read-back returning mismatched ID/start time fails closed.
- Privacy & Redaction: str/repr and sanitized dict never echo raw IDs.
- Read-only preflight entry point: check_demo_resources_preflight enforces permit_mutation=False.
"""

from __future__ import annotations

import pytest

from stilldone.demo_isolation import DemoResourceScope, DemoScopeTypeError
from stilldone.demo_seeding import (
    CanonicalEventSpec,
    DemoSeedResult,
    FakeCalendarSeedTransport,
    FakeTasksSeedTransport,
    SeedOperationStatus,
    check_demo_resources_preflight,
    create_canonical_event_spec,
    seed_canonical_demo_resources,
)
from stilldone.domain.provenance import EvidenceProvenance

VALID_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
VALID_TASK_LIST_ID = "MDk4NzY1NDMyMWRlbW8"
CANONICAL_START_TIME = "2026-10-12T07:45:00Z"
CANONICAL_END_TIME = "2026-10-12T08:15:00Z"


@pytest.fixture
def valid_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=VALID_CALENDAR_ID,
        task_list_id=VALID_TASK_LIST_ID,
    )


@pytest.fixture
def event_spec() -> CanonicalEventSpec:
    return CanonicalEventSpec(
        title="Leave for school",
        start_time=CANONICAL_START_TIME,
        end_time=CANONICAL_END_TIME,
        description="StillDone canonical demo event",
    )


@pytest.fixture
def seeded_transports(
    valid_scope: DemoResourceScope,
) -> tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport]:
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, "StillDone Demo")

    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, "StillDone Demo")

    return cal_t, tasks_t


# ===========================================================================
# 1. Scope & Wrong Target Tests
# ===========================================================================


def test_reject_non_demo_resource_scope(
    event_spec: CanonicalEventSpec,
) -> None:
    cal_t = FakeCalendarSeedTransport()
    tasks_t = FakeTasksSeedTransport()
    with pytest.raises(DemoScopeTypeError):
        seed_canonical_demo_resources(
            "not_a_scope",  # type: ignore[arg-type]
            cal_t,
            tasks_t,
            event_spec=event_spec,
        )


@pytest.mark.parametrize("forbidden_cal_id", ["primary", "default", "PRIMARY", " DEFAULT "])
def test_reject_forbidden_primary_or_default_calendar(
    forbidden_cal_id: str,
    event_spec: CanonicalEventSpec,
) -> None:
    scope = DemoResourceScope(
        calendar_id=forbidden_cal_id,
        task_list_id=VALID_TASK_LIST_ID,
    )
    cal_t = FakeCalendarSeedTransport()
    tasks_t = FakeTasksSeedTransport()

    res = seed_canonical_demo_resources(
        scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
    )
    assert res.status == SeedOperationStatus.WRONG_TARGET_REJECTED
    assert res.writes_performed == 0
    assert res.is_seed_complete is False
    assert res.error_message == "WRONG_TARGET_CALENDAR"


@pytest.mark.parametrize("forbidden_tl_id", ["default", "@default", "DEFAULT", " @default "])
def test_reject_forbidden_default_task_list(
    forbidden_tl_id: str,
    event_spec: CanonicalEventSpec,
) -> None:
    scope = DemoResourceScope(
        calendar_id=VALID_CALENDAR_ID,
        task_list_id=forbidden_tl_id,
    )
    cal_t = FakeCalendarSeedTransport()
    tasks_t = FakeTasksSeedTransport()

    res = seed_canonical_demo_resources(
        scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
    )
    assert res.status == SeedOperationStatus.WRONG_TARGET_REJECTED
    assert res.writes_performed == 0
    assert res.is_seed_complete is False
    assert res.error_message == "WRONG_TARGET_TASK_LIST"


# ===========================================================================
# 2. Container Preflight Failure Tests
# ===========================================================================


def test_blocked_preflight_when_calendar_not_found(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
) -> None:
    cal_t = FakeCalendarSeedTransport()  # empty: calendar not added
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id)

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
    )
    assert res.status == SeedOperationStatus.BLOCKED_PREFLIGHT
    assert res.error_message == "DEMO_CALENDAR_NOT_FOUND"
    assert res.writes_performed == 0
    assert res.is_seed_complete is False


def test_blocked_preflight_when_task_list_not_found(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
) -> None:
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id)
    tasks_t = FakeTasksSeedTransport()  # empty: task list not added

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
    )
    assert res.status == SeedOperationStatus.BLOCKED_PREFLIGHT
    assert res.error_message == "DEMO_TASK_LIST_NOT_FOUND"
    assert res.writes_performed == 0
    assert res.is_seed_complete is False


# ===========================================================================
# 3. Unauthorized Mutation Boundary Tests
# ===========================================================================


def test_blocked_unauthorized_when_event_missing_and_permit_mutation_false(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    # calendar has 0 events

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=False,
    )
    assert res.status == SeedOperationStatus.BLOCKED_UNAUTHORIZED
    assert res.error_message == "MUTATION_UNAUTHORIZED"
    assert res.writes_performed == 0
    assert res.is_seed_complete is False
    assert cal_t.writes_count == 0


def test_blocked_unauthorized_when_event_drifted_and_permit_mutation_false(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    # event exists but at 07:30 instead of canonical 07:45
    cal_t.add_event(
        valid_scope.calendar_id,
        "ev_existing",
        event_spec.title,
        "2026-10-12T07:30:00Z",
        "2026-10-12T08:00:00Z",
    )

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=False,
    )
    assert res.status == SeedOperationStatus.BLOCKED_UNAUTHORIZED
    assert res.error_message == "MUTATION_UNAUTHORIZED"
    assert res.writes_performed == 0
    assert res.is_seed_complete is False
    assert cal_t.writes_count == 0


# ===========================================================================
# 4. Idempotency & Verified Existing Tests
# ===========================================================================


def test_verified_existing_when_canonical_event_matches_pre_state(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    cal_t.add_event(
        valid_scope.calendar_id,
        "ev_canonical",
        event_spec.title,
        CANONICAL_START_TIME,
        CANONICAL_END_TIME,
    )

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=False,
        provenance=EvidenceProvenance.FIXTURE,
    )
    assert res.status == SeedOperationStatus.VERIFIED_EXISTING
    assert res.writes_performed == 0
    assert res.readback_verified is True
    assert res.is_seed_complete is True
    assert res.event_id == "ev_canonical"
    assert res.event_start_time == CANONICAL_START_TIME
    assert cal_t.writes_count == 0


def test_idempotent_rerun_creates_zero_duplicates_and_zero_writes(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    # First run: authorized creation
    res1 = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
    )
    assert res1.status == SeedOperationStatus.MUTATION_EXECUTED
    assert res1.writes_performed == 1
    assert res1.is_seed_complete is True
    assert cal_t.writes_count == 1

    # Second run: must detect existing event without creating duplicate
    res2 = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
    )
    assert res2.status == SeedOperationStatus.VERIFIED_EXISTING
    assert res2.writes_performed == 0
    assert res2.readback_verified is True
    assert res2.is_seed_complete is True
    assert res2.event_id == res1.event_id
    assert cal_t.writes_count == 1  # zero additional writes
    assert len(cal_t.list_events_by_title(valid_scope.calendar_id, event_spec.title)) == 1


# ===========================================================================
# 5. Duplicate Contradiction Fail-Closed Tests
# ===========================================================================


def test_duplicate_contradiction_fails_closed(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    # Add TWO events with identical title
    cal_t.add_event(
        valid_scope.calendar_id,
        "ev_1",
        event_spec.title,
        CANONICAL_START_TIME,
        CANONICAL_END_TIME,
    )
    cal_t.add_event(
        valid_scope.calendar_id,
        "ev_2",
        event_spec.title,
        "2026-10-12T07:30:00Z",
        "2026-10-12T08:00:00Z",
    )

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
    )
    assert res.status == SeedOperationStatus.DUPLICATE_CONTRADICTION
    assert res.error_message == "DUPLICATE_EVENTS_CONTRADICTION"
    assert res.writes_performed == 0
    assert res.is_seed_complete is False
    assert cal_t.writes_count == 0


# ===========================================================================
# 6. Authorized Mutation & Independent Read-Back Tests
# ===========================================================================


def test_authorized_creation_with_independent_readback(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
        provenance=EvidenceProvenance.FIXTURE,
    )
    assert res.status == SeedOperationStatus.MUTATION_EXECUTED
    assert res.writes_performed == 1
    assert res.readback_verified is True
    assert res.is_seed_complete is True
    assert res.event_id is not None
    assert res.event_start_time == CANONICAL_START_TIME
    assert cal_t.writes_count == 1
    assert cal_t.reads_count >= 1  # separate read-back executed


def test_authorized_update_of_drifted_event_with_independent_readback(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    cal_t.add_event(
        valid_scope.calendar_id,
        "ev_drifted",
        event_spec.title,
        "2026-10-12T07:30:00Z",
        "2026-10-12T08:00:00Z",
    )

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
    )
    assert res.status == SeedOperationStatus.MUTATION_EXECUTED
    assert res.writes_performed == 1
    assert res.readback_verified is True
    assert res.is_seed_complete is True
    assert res.event_id == "ev_drifted"
    assert res.event_start_time == CANONICAL_START_TIME
    assert cal_t.writes_count == 1


# ===========================================================================
# 7. Post-Write Read-Back Failure & Inconsistency Tests
# ===========================================================================


def test_readback_failure_after_insert_fails_closed(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    cal_t.fail_readback = True  # get_event returns None

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
    )
    assert res.status == SeedOperationStatus.VERIFICATION_FAILED
    assert res.error_message == "READBACK_MISMATCH_AFTER_INSERT"
    assert res.writes_performed == 1
    assert res.readback_verified is False
    assert res.is_seed_complete is False


def test_readback_inconsistent_start_time_after_update_fails_closed(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    cal_t.add_event(
        valid_scope.calendar_id,
        "ev_test",
        event_spec.title,
        "2026-10-12T07:30:00Z",
        "2026-10-12T08:00:00Z",
    )
    # Simulate read-back returning wrong/drifted start time despite update
    inconsistent = cal_t._to_transport_event(
        {
            "id": "ev_test",
            "etag": '"2000"',
            "summary": event_spec.title,
            "status": "confirmed",
            "start": {"dateTime": "2026-10-12T09:00:00Z"},
            "end": {"dateTime": "2026-10-12T09:30:00Z"},
        }
    )
    cal_t.inconsistent_readback_event = inconsistent

    res = seed_canonical_demo_resources(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
        permit_mutation=True,
    )
    assert res.status == SeedOperationStatus.VERIFICATION_FAILED
    assert res.error_message == "READBACK_MISMATCH_AFTER_UPDATE"
    assert res.writes_performed == 1
    assert res.readback_verified is False
    assert res.is_seed_complete is False


# ===========================================================================
# 8. Privacy, Redaction & Helpers Tests
# ===========================================================================


def test_privacy_and_redaction_in_str_and_repr(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
) -> None:
    result = DemoSeedResult(
        status=SeedOperationStatus.VERIFIED_EXISTING,
        provenance=EvidenceProvenance.FIXTURE,
        calendar_id=VALID_CALENDAR_ID,
        task_list_id=VALID_TASK_LIST_ID,
        event_id="ev_sensitive_id_9999",
        event_start_time=CANONICAL_START_TIME,
        writes_performed=0,
        readback_verified=True,
        is_seed_complete=True,
    )
    r_str = str(result)
    r_repr = repr(result)

    assert VALID_CALENDAR_ID not in r_str
    assert VALID_TASK_LIST_ID not in r_str
    assert "ev_sensitive_id_9999" not in r_str
    assert VALID_CALENDAR_ID not in r_repr
    assert VALID_TASK_LIST_ID not in r_repr
    assert "ev_sensitive_id_9999" not in r_repr

    d = result.to_sanitized_dict()
    assert d["calendar_id"] == "[REDACTED]"
    assert d["task_list_id"] == "[REDACTED]"
    assert d["event_id"] == "[REDACTED]"


def test_check_demo_resources_preflight_always_forces_zero_writes(
    valid_scope: DemoResourceScope,
    event_spec: CanonicalEventSpec,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    # Event is absent, so mutation would normally be needed
    res = check_demo_resources_preflight(
        valid_scope,
        cal_t,
        tasks_t,
        event_spec=event_spec,
    )
    assert res.status == SeedOperationStatus.BLOCKED_UNAUTHORIZED
    assert res.writes_performed == 0
    assert res.is_seed_complete is False
    assert cal_t.writes_count == 0


def test_create_canonical_event_spec_defaults() -> None:
    spec = create_canonical_event_spec()
    assert spec.title == "Leave for school"
    assert "T07:45:00Z" in spec.start_time
    assert "T08:15:00Z" in spec.end_time
    assert spec.description == "StillDone canonical demo event"
