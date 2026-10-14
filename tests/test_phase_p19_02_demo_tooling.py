"""Adversarial and functional test suite for Phase P-19.02 Demo-Resource Operator Tooling.

Validates:
1. Four distinct operational modes: INSPECT, SETUP, VERIFY, TEARDOWN.
2. Default is strictly DRY_RUN / NO_MUTATION (0 writes performed).
3. Idempotent setup: second setup run executes 0 writes and returns VERIFIED_EXISTING.
4. Idempotent teardown: second teardown run on clean state executes 0 writes and
   returns ALREADY_CLEAN.
5. Independent read-back requirement: provider mutation alone does not produce success;
   readback_verified must be confirmed through a distinct read.
6. Target isolation & out-of-scope rejection: primary/default calendars and task lists
   are strictly rejected fail-closed.
7. Container identity verification: calendar and task list titles must match "StillDone Demo".
8. Teardown confirmation law: mutations during teardown require exact target-bound
   confirmation token.
9. Sanitization: repr, str, and JSON outputs never expose raw calendar IDs, task list IDs,
   or credentials.
10. CLI interface: scripts/demo_resources.py correctly parses arguments, executes dry runs,
    and returns sanitized JSON.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from stilldone.adapters.calendar import CalendarTransportEvent
from stilldone.demo_isolation import (
    DemoResourceScope,
)
from stilldone.demo_seeding import (
    DEFAULT_DEMO_CALENDAR_TITLE,
    DEFAULT_DEMO_TASK_LIST_TITLE,
    DEFAULT_PREPARATION_TASK_TITLE,
    FakeCalendarSeedTransport,
    FakeTasksSeedTransport,
    create_canonical_event_spec,
)
from stilldone.demo_tooling import (
    CANONICAL_TEARDOWN_CONFIRMATION,
    DemoArtifactManifest,
    DemoOperationMode,
    DemoResourceOwnershipRecord,
    DemoToolingResult,
    DemoToolingStatus,
    execute_demo_resource_operation,
    make_scope_bound_teardown_confirmation,
)
from stilldone.domain.provenance import EvidenceProvenance

REPO_ROOT = Path(__file__).resolve().parent.parent

# Dynamically import scripts/demo_resources.py
_cli_path = REPO_ROOT / "scripts" / "demo_resources.py"
_cli_spec = importlib.util.spec_from_file_location("demo_resources_cli", _cli_path)
assert _cli_spec is not None and _cli_spec.loader is not None
demo_cli_mod: Any = importlib.util.module_from_spec(_cli_spec)
_cli_spec.loader.exec_module(demo_cli_mod)

VALID_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
VALID_TASK_LIST_ID = "MDk4NzY1NDMyMWRlbW8"


@pytest.fixture
def valid_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=VALID_CALENDAR_ID,
        task_list_id=VALID_TASK_LIST_ID,
    )


@pytest.fixture
def seeded_transports(
    valid_scope: DemoResourceScope,
) -> tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport]:
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)

    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)

    return cal_t, tasks_t


def add_canonical_event(
    cal_t: FakeCalendarSeedTransport, calendar_id: str, event_id: str = "ev_canon"
) -> Any:
    """Helper to add verified canonical demo event to calendar transport."""
    event_spec = create_canonical_event_spec()
    return cal_t.add_event(
        calendar_id,
        event_id=event_id,
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )


# ===========================================================================
# 1. Zero Mutation Dry-Run Defaults
# ===========================================================================


def test_inspect_mode_executes_zero_mutations(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.INSPECT,
        permit_mutation=False,
    )

    assert result.mode == DemoOperationMode.INSPECT
    assert result.status == DemoToolingStatus.INSPECTED
    assert result.writes_performed == 0
    assert result.is_success is True
    assert cal_t.writes_count == 0
    assert tasks_t.writes_count == 0


def test_setup_default_dry_run_executes_zero_mutations(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    # Event is absent, but permit_mutation=False (default)
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.SETUP,
        permit_mutation=False,
    )

    assert result.mode == DemoOperationMode.SETUP
    assert result.status == DemoToolingStatus.BLOCKED_DRY_RUN
    assert result.writes_performed == 0
    assert result.is_success is False
    assert "DRY RUN: Mutation required" in result.details
    assert cal_t.writes_count == 0
    assert tasks_t.writes_count == 0


def test_verify_mode_executes_zero_mutations(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.VERIFY,
        permit_mutation=False,
    )

    assert result.mode == DemoOperationMode.VERIFY
    assert result.writes_performed == 0
    assert cal_t.writes_count == 0
    assert tasks_t.writes_count == 0


def test_teardown_default_dry_run_executes_zero_mutations(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    # Add prep task to simulate post-mission state
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=False,
    )

    assert result.mode == DemoOperationMode.TEARDOWN
    assert result.status == DemoToolingStatus.BLOCKED_DRY_RUN
    assert result.writes_performed == 0
    assert result.is_success is False
    assert "DRY RUN: Found 1 demo task(s)" in result.details
    assert cal_t.writes_count == 0
    assert tasks_t.writes_count == 0


# ===========================================================================
# 2. Authorized Setup & Idempotency
# ===========================================================================


def test_authorized_setup_creates_event_and_verifies(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.SETUP,
        permit_mutation=True,
        event_spec=event_spec,
    )

    assert result.status == DemoToolingStatus.MUTATION_EXECUTED
    assert result.writes_performed == 1
    assert result.readback_verified is True
    assert result.is_success is True
    assert cal_t.writes_count == 1

    # Independent read-back confirmation
    events = cal_t.list_events_by_title(valid_scope.calendar_id, event_spec.title)
    assert len(events) == 1
    assert events[0].start_time == event_spec.start_time


def test_setup_idempotency_second_run_performs_zero_writes(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()

    # First run: mutates
    r1 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.SETUP,
        permit_mutation=True,
        event_spec=event_spec,
    )
    assert r1.status == DemoToolingStatus.MUTATION_EXECUTED
    assert r1.writes_performed == 1
    assert cal_t.writes_count == 1

    # Second run: already in canonical pre-state -> 0 writes!
    r2 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.SETUP,
        permit_mutation=True,
        event_spec=event_spec,
    )
    assert r2.status == DemoToolingStatus.VERIFIED_EXISTING
    assert r2.writes_performed == 0
    assert r2.readback_verified is True
    assert r2.is_success is True
    assert cal_t.writes_count == 1  # No additional writes!


# ===========================================================================
# 3. Pre-Mission Verification Mode
# ===========================================================================


def test_verify_succeeds_when_canonical_pre_state_satisfied(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()

    # Seed event
    cal_t.add_event(
        calendar_id=valid_scope.calendar_id,
        event_id="ev_canon",
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.VERIFY,
        event_spec=event_spec,
    )

    assert result.status == DemoToolingStatus.VERIFIED_READY
    assert result.writes_performed == 0
    assert result.readback_verified is True
    assert result.is_success is True


def test_verify_detects_contradictory_task(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()
    cal_t.add_event(
        calendar_id=valid_scope.calendar_id,
        event_id="ev_canon",
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )
    # Prep task present
    tasks_t.add_task(valid_scope.task_list_id, "t_99", DEFAULT_PREPARATION_TASK_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.VERIFY,
        event_spec=event_spec,
    )

    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.is_success is False
    assert result.error_message == "PREPARATION_TASK_PRESENT"
    assert result.writes_performed == 0


def test_verify_detects_drifted_event_time(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()
    # Event exists but shifted to 07:15
    cal_t.add_event(
        calendar_id=valid_scope.calendar_id,
        event_id="ev_canon",
        summary=event_spec.title,
        start_time="2026-10-15T07:15:00Z",
        end_time="2026-10-15T07:45:00Z",
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.VERIFY,
        event_spec=event_spec,
    )

    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    assert result.is_success is False
    assert result.error_message == "EVENT_READBACK_MISMATCH"
    assert result.writes_performed == 0


# ===========================================================================
# 4. Teardown, Confirmation, and Idempotency
# ===========================================================================


def test_teardown_already_clean_performs_zero_writes(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=CANONICAL_TEARDOWN_CONFIRMATION,
    )

    assert result.status == DemoToolingStatus.ALREADY_CLEAN
    assert result.writes_performed == 0
    assert result.readback_verified is True
    assert result.is_success is True


def test_teardown_missing_confirmation_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    # permit_mutation=True but NO teardown_confirmation (None)
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=None,
        manifest=DemoArtifactManifest(owned_task_ids={"t_101"}),
    )

    assert result.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert result.writes_performed == 0
    assert result.is_success is False
    assert tasks_t.writes_count == 0


def test_teardown_bare_confirmation_token_rejected_fail_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Bare CONFIRM_TEARDOWN without scope binding MUST be rejected fail-closed (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=CANONICAL_TEARDOWN_CONFIRMATION,  # Bare unbound token!
        manifest=DemoArtifactManifest(owned_task_ids={"t_101"}),
    )

    assert result.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert result.writes_performed == 0
    assert result.is_success is False
    assert tasks_t.writes_count == 0


def test_teardown_mismatched_scope_confirmation_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Mismatched calendar or task list ID in confirmation token must fail closed (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    # 1. Mismatched calendar
    r1 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=f"CONFIRM_TEARDOWN:wrong_cal:{valid_scope.task_list_id}",
        manifest=DemoArtifactManifest(owned_task_ids={"t_101"}),
    )
    assert r1.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert r1.writes_performed == 0

    # 2. Mismatched task list
    r2 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=f"CONFIRM_TEARDOWN:{valid_scope.calendar_id}:wrong_tl",
        manifest=DemoArtifactManifest(owned_task_ids={"t_101"}),
    )
    assert r2.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert r2.writes_performed == 0

    # 3. Empty string
    r3 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation="",
        manifest=DemoArtifactManifest(owned_task_ids={"t_101"}),
    )
    assert r3.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert r3.writes_performed == 0


def test_authorized_teardown_deletes_owned_prep_task_and_verifies(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Authorized teardown with exact scope token and owned manifest deletes task (B1, B2)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=DemoArtifactManifest(owned_task_ids={"t_101"}),
    )

    assert result.status == DemoToolingStatus.TEARDOWN_COMPLETED
    assert result.writes_performed == 1
    assert result.items_deleted == 1
    assert result.readback_verified is True
    assert result.is_success is True

    # Independent read-back confirmation: task is no longer present
    tasks = tasks_t.list_tasks(valid_scope.task_list_id)
    assert not any(t.get("title") == DEFAULT_PREPARATION_TASK_TITLE for t in tasks)


def test_teardown_preserves_unrelated_user_created_task(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """An unrelated user task titled 'Pack backpacks' must NOT be deleted without ownership (B2)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "user_task_999", DEFAULT_PREPARATION_TASK_TITLE)

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )

    # Manifest is empty / does not own user_task_999
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=DemoArtifactManifest(owned_task_ids=set()),
    )

    # Must fail closed with UNPROVEN_RESOURCE_OWNERSHIP and 0 writes
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "UNPROVEN_RESOURCE_OWNERSHIP"
    assert result.writes_performed == 0
    assert result.is_success is False
    assert tasks_t.writes_count == 0

    # User task MUST remain intact on the provider
    tasks = tasks_t.list_tasks(valid_scope.task_list_id)
    assert any(t.get("id") == "user_task_999" for t in tasks)


def test_teardown_preserves_unrelated_user_created_event(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """An unrelated user event sharing demo title must NOT be deleted without ownership (B2)."""
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()
    # Add canonical event to calendar
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="ev_canon",
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )
    # Add an unowned extra user event
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="user_ev_999",
        summary=event_spec.title,
        start_time="2026-10-15T09:00:00Z",
        end_time="2026-10-15T09:30:00Z",
    )

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )

    # Manifest does not own user_ev_999
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=DemoArtifactManifest(owned_event_ids=set()),
    )

    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "UNPROVEN_RESOURCE_OWNERSHIP"
    assert result.writes_performed == 0
    assert result.is_success is False
    assert cal_t.writes_count == 0

    # User event MUST remain intact on provider
    events = cal_t.list_events_by_title(
        valid_scope.calendar_id, create_canonical_event_spec().title
    )
    assert any(e.id == "user_ev_999" for e in events)


def test_teardown_deterministic_event_selection_reversed_discovery_order(
    valid_scope: DemoResourceScope,
) -> None:
    """Teardown must NOT infer canonical identity from list index [0] (B3)."""
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)

    event_spec = create_canonical_event_spec()

    # Insert extra duplicate FIRST in transport (so it will be events[0] in discovery)
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="extra_ev_owned",
        summary=event_spec.title,
        start_time="2026-10-15T10:00:00Z",
        end_time="2026-10-15T10:30:00Z",
    )
    # Insert canonical event SECOND in transport (so it will be events[1] in discovery)
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="canonical_ev_keep",
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )

    # Manifest identifies extra_ev_owned for deletion and canonical_ev_keep as canonical
    manifest = DemoArtifactManifest(
        owned_event_ids={"extra_ev_owned"},
        canonical_event_id="canonical_ev_keep",
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        event_spec=event_spec,
        manifest=manifest,
    )

    assert result.status == DemoToolingStatus.TEARDOWN_COMPLETED
    assert result.writes_performed == 1
    assert result.items_deleted == 1
    assert result.readback_verified is True
    assert result.is_success is True

    # Crucial check: canonical event was PRESERVED, duplicate was DELETED
    remaining_events = cal_t.list_events_by_title(valid_scope.calendar_id, event_spec.title)
    assert len(remaining_events) == 1
    assert remaining_events[0].id == "canonical_ev_keep"


def test_teardown_partial_failure_preserves_committed_writes_and_halts(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """A transport failure during destructive loop must halt safely and record writes (B4)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_1", DEFAULT_PREPARATION_TASK_TITLE)
    tasks_t.add_task(valid_scope.task_list_id, "t_2", DEFAULT_PREPARATION_TASK_TITLE)

    # Monkeypatch delete_task so that t_1 succeeds and t_2 raises an exception
    orig_delete = tasks_t.delete_task

    def delete_with_error(tl_id: str, task_id: str) -> None:
        if task_id == "t_2":
            raise RuntimeError("Provider connection reset during deletion of second task")
        orig_delete(tl_id, task_id)

    tasks_t.delete_task = delete_with_error  # type: ignore[method-assign, assignment]

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(owned_task_ids={"t_1", "t_2"})

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )

    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    assert result.error_message == "PARTIAL_MUTATION_FAILURE"
    # Crucial invariant: exactly 1 write committed; must NOT be reported as 0 writes
    assert result.writes_performed == 1
    assert result.items_deleted == 1
    assert result.readback_verified is False
    assert result.is_success is False
    assert "t_1" not in [t["id"] for t in tasks_t.list_tasks(valid_scope.task_list_id)]
    assert "t_2" in [t["id"] for t in tasks_t.list_tasks(valid_scope.task_list_id)]


def test_teardown_ambiguous_write_probe_detects_committed_deletion(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """When delete commits but transport drops acknowledgment, probe confirms write (B4)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_ambiguous", DEFAULT_PREPARATION_TASK_TITLE)

    orig_delete = tasks_t.delete_task

    def delete_then_raise(tl_id: str, task_id: str) -> None:
        orig_delete(tl_id, task_id)  # deletion committed on remote
        raise TimeoutError("Socket timeout waiting for HTTP 204 response")

    tasks_t.delete_task = delete_then_raise  # type: ignore[method-assign, assignment]

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(owned_task_ids={"t_ambiguous"})

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )

    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    # Even though TimeoutError was raised, probe saw write committed!
    assert result.writes_performed == 1
    assert result.items_deleted == 1


def test_teardown_idempotency_second_run_reports_already_clean(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(owned_task_ids={"t_101"})

    # First run: deletes task
    r1 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert r1.status == DemoToolingStatus.TEARDOWN_COMPLETED
    assert r1.writes_performed == 1

    # Second run: already clean -> 0 writes performed!
    r2 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert r2.status == DemoToolingStatus.ALREADY_CLEAN
    assert r2.writes_performed == 0
    assert r2.is_success is True
    assert r2.readback_verified is True


# ===========================================================================
# 5. Out-of-Scope and Boundary Protection Tests
# ===========================================================================


@pytest.mark.parametrize("forbidden_cal_id", ["primary", "default", "PRIMARY", " DEFAULT "])
def test_reject_forbidden_primary_calendar(
    forbidden_cal_id: str,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    scope = DemoResourceScope(
        calendar_id=forbidden_cal_id,
        task_list_id=VALID_TASK_LIST_ID,
    )

    result = execute_demo_resource_operation(
        scope=scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.INSPECT,
    )

    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.writes_performed == 0
    assert result.is_success is False


@pytest.mark.parametrize("forbidden_tl_id", ["default", "@default", "DEFAULT", " @default "])
def test_reject_forbidden_default_task_list(
    forbidden_tl_id: str,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    scope = DemoResourceScope(
        calendar_id=VALID_CALENDAR_ID,
        task_list_id=forbidden_tl_id,
    )

    result = execute_demo_resource_operation(
        scope=scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.INSPECT,
    )

    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.writes_performed == 0
    assert result.is_success is False


def test_reject_mismatched_calendar_title(
    valid_scope: DemoResourceScope,
) -> None:
    cal_t = FakeCalendarSeedTransport()
    # Calendar title does not match "StillDone Demo"
    cal_t.add_calendar(valid_scope.calendar_id, "Personal Work Calendar")
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.INSPECT,
    )

    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.is_success is False


def test_reject_mismatched_task_list_title(
    valid_scope: DemoResourceScope,
) -> None:
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = FakeTasksSeedTransport()
    # Task list title does not match "StillDone Demo"
    tasks_t.add_task_list(valid_scope.task_list_id, "Shopping List")

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.INSPECT,
    )

    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.is_success is False


def test_reject_missing_containers(
    valid_scope: DemoResourceScope,
) -> None:
    cal_t = FakeCalendarSeedTransport()  # calendar not added
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.INSPECT,
    )

    assert result.status == DemoToolingStatus.BLOCKED_PREFLIGHT
    assert result.error_message == "DEMO_CALENDAR_NOT_FOUND"


# ===========================================================================
# 6. Sanitization and Privacy
# ===========================================================================


def test_result_sanitization_masks_sensitive_identifiers(
    valid_scope: DemoResourceScope,
) -> None:
    res = DemoToolingResult(
        mode=DemoOperationMode.INSPECT,
        status=DemoToolingStatus.INSPECTED,
        provenance=EvidenceProvenance.FIXTURE,
        calendar_id=valid_scope.calendar_id,
        task_list_id=valid_scope.task_list_id,
        writes_performed=0,
        readback_verified=False,
        is_success=True,
    )

    repr_str = repr(res)
    assert valid_scope.calendar_id not in repr_str
    assert valid_scope.task_list_id not in repr_str
    assert "***" in repr_str

    sanitized_dict = res.to_sanitized_dict()
    assert sanitized_dict["calendar_id"] == "[REDACTED]"
    assert sanitized_dict["task_list_id"] == "[REDACTED]"


# ===========================================================================
# 7. CLI Entry Point Tests
# ===========================================================================


def test_cli_inspect_dry_run_success() -> None:
    exit_code = demo_cli_mod.main(
        [
            "--mode",
            "inspect",
            "--calendar-id",
            VALID_CALENDAR_ID,
            "--task-list-id",
            VALID_TASK_LIST_ID,
            "--fixture",
        ]
    )
    assert exit_code == 0


def test_cli_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = demo_cli_mod.main(
        [
            "--mode",
            "inspect",
            "--calendar-id",
            VALID_CALENDAR_ID,
            "--task-list-id",
            VALID_TASK_LIST_ID,
            "--fixture",
            "--json",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["mode"] == "INSPECT"
    assert data["status"] == "INSPECTED"
    assert data["writes_performed"] == 0
    assert data["calendar_id"] == "[REDACTED]"


def test_cli_rejects_primary_calendar(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = demo_cli_mod.main(
        [
            "--mode",
            "inspect",
            "--calendar-id",
            "primary",
            "--task-list-id",
            VALID_TASK_LIST_ID,
            "--fixture",
            "--json",
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["status"] == "WRONG_TARGET_REJECTED"


# ===========================================================================
# 8. Targeted Regression: B3 Event Invariants & B5 Adversarial Sanitization
# ===========================================================================


def test_teardown_detects_missing_canonical_event_when_duplicates_exist(
    valid_scope: DemoResourceScope,
) -> None:
    """When duplicate events exist but none matches canonical pre-state spec, fail closed (B3)."""
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    event_spec = create_canonical_event_spec()

    # Seed 2 events with title but WRONG times (neither matches 07:30)
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="drifted_ev_1",
        summary=event_spec.title,
        start_time="2026-10-15T08:00:00Z",
        end_time="2026-10-15T08:30:00Z",
    )
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="drifted_ev_2",
        summary=event_spec.title,
        start_time="2026-10-15T09:00:00Z",
        end_time="2026-10-15T09:30:00Z",
    )

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        event_spec=event_spec,
    )

    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CANONICAL_EVENT_CORRUPTED_OR_MISSING"
    assert result.writes_performed == 0
    assert result.is_success is False
    assert cal_t.writes_count == 0


def test_teardown_detects_canonical_event_readback_drift(
    valid_scope: DemoResourceScope,
) -> None:
    """If canonical event is drifted/corrupted during read-back probe, fail verification (B3)."""
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    event_spec = create_canonical_event_spec()

    # Seed canonical event
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="canon_1",
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )
    # Seed duplicate owned event
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="extra_1",
        summary=event_spec.title,
        start_time="2026-10-15T11:00:00Z",
        end_time="2026-10-15T11:30:00Z",
    )

    # Monkeypatch delete_event so that when extra_1 is deleted, canon_1's start time drifts!
    orig_delete = cal_t.delete_event

    def delete_and_drift_canonical(calendar_id: str, event_id: str) -> None:
        orig_delete(calendar_id, event_id)
        # Drift canon_1
        c_dict = cal_t._events[(calendar_id, "canon_1")]
        c_dict["start"] = {"dateTime": "2026-10-15T06:30:00Z"}  # Genuinely drifted!

    cal_t.delete_event = delete_and_drift_canonical  # type: ignore[method-assign]

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(
        owned_event_ids={"extra_1"},
        canonical_event_id="canon_1",
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        event_spec=event_spec,
        manifest=manifest,
    )

    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    assert result.error_message == "TEARDOWN_READBACK_CANONICAL_EVENT_INVALID"
    assert result.readback_verified is False
    assert result.is_success is False
    assert result.writes_performed == 1


def test_teardown_mixed_owned_and_unowned_matching_title_events(
    valid_scope: DemoResourceScope,
) -> None:
    """When calendar has canonical, owned, and unowned user events, fail closed (B2, B3)."""
    cal_t = FakeCalendarSeedTransport()
    cal_t.add_calendar(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = FakeTasksSeedTransport()
    tasks_t.add_task_list(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    event_spec = create_canonical_event_spec()

    # 1. Canonical event
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="canon_keep",
        summary=event_spec.title,
        start_time=event_spec.start_time,
        end_time=event_spec.end_time,
    )
    # 2. Owned duplicate
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="owned_extra",
        summary=event_spec.title,
        start_time="2026-10-15T10:00:00Z",
        end_time="2026-10-15T10:30:00Z",
    )
    # 3. Unowned user event
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="unowned_user_ev",
        summary=event_spec.title,
        start_time="2026-10-15T12:00:00Z",
        end_time="2026-10-15T12:30:00Z",
    )

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    # Manifest only owns owned_extra, not unowned_user_ev
    manifest = DemoArtifactManifest(
        owned_event_ids={"owned_extra"},
        canonical_event_id="canon_keep",
    )

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        event_spec=event_spec,
        manifest=manifest,
    )

    # Must fail closed: UNPROVEN_RESOURCE_OWNERSHIP with 0 writes performed
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "UNPROVEN_RESOURCE_OWNERSHIP"
    assert result.writes_performed == 0
    assert result.is_success is False
    assert cal_t.writes_count == 0

    # All three events remain untouched on provider
    events = cal_t.list_events_by_title(valid_scope.calendar_id, event_spec.title)
    assert len(events) == 3
    event_ids = {e.id for e in events}
    assert event_ids == {"canon_keep", "owned_extra", "unowned_user_ev"}


def test_adversarial_sanitization_masks_all_credentials_paths_emails(
    valid_scope: DemoResourceScope,
) -> None:
    """Adversarial provider outputs with tokens, emails, paths, AWS keys must be redacted (B5)."""
    adversarial_text = (
        "Fatal error connecting to user judge.evaluator@enterprise.example.com using "
        "Bearer ya29.a0AfH6SMRandomBearerToken1234567890ExtraLongToken and "
        "AWS key AKIAIOSFODNN7EXAMPLE at path "
        "C:\\Users\\Administrator\\AppData\\Local\\StillDone\\creds.json "
        "or unix path /home/judge/production/google_secret.json for resource "
        f"{valid_scope.calendar_id} and task list {valid_scope.task_list_id}"
    )

    result = DemoToolingResult(
        mode=DemoOperationMode.TEARDOWN,
        status=DemoToolingStatus.VERIFICATION_FAILED,
        provenance=EvidenceProvenance.FIXTURE,
        calendar_id=valid_scope.calendar_id,
        task_list_id=valid_scope.task_list_id,
        writes_performed=0,
        readback_verified=False,
        is_success=False,
        details=adversarial_text,
        error_message=adversarial_text,
    )

    # Verify details sanitized
    assert "ya29." not in result.details
    assert "AKIA" not in result.details
    assert "judge.evaluator" not in result.details
    assert "Administrator" not in result.details
    assert "/home/judge" not in result.details
    assert valid_scope.calendar_id not in result.details
    assert valid_scope.task_list_id not in result.details

    # Verify error_message sanitized
    assert result.error_message is not None
    assert "ya29." not in result.error_message
    assert "AKIA" not in result.error_message
    assert "judge.evaluator" not in result.error_message
    assert "Administrator" not in result.error_message

    # Verify repr() sanitized
    repr_str = repr(result)
    assert "ya29." not in repr_str
    assert "AKIA" not in repr_str
    assert "judge.evaluator" not in repr_str
    assert "Administrator" not in repr_str
    assert valid_scope.calendar_id not in repr_str

    # Verify to_sanitized_dict() sanitized
    dict_repr = result.to_sanitized_dict()
    assert dict_repr["calendar_id"] == "[REDACTED]"
    assert dict_repr["task_list_id"] == "[REDACTED]"
    assert "ya29." not in dict_repr["details"]
    assert "judge.evaluator" not in dict_repr["details"]
    assert "AKIA" not in dict_repr["details"]


def test_cli_ephemeral_fixture_notice_displayed_in_text_and_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI must explicitly surface ephemeral fixture notice in text and JSON outputs (B5)."""
    # 1. Text mode
    exit_code_text = demo_cli_mod.main(
        [
            "--mode",
            "inspect",
            "--calendar-id",
            VALID_CALENDAR_ID,
            "--task-list-id",
            VALID_TASK_LIST_ID,
            "--fixture",
        ]
    )
    assert exit_code_text == 0
    text_out = capsys.readouterr().out
    assert "EPHEMERAL IN-MEMORY FIXTURE" in text_out
    assert "Independent CLI executions DO NOT share persisted state" in text_out
    assert "0 calls to real Google APIs" in text_out

    # 2. JSON mode
    exit_code_json = demo_cli_mod.main(
        [
            "--mode",
            "inspect",
            "--calendar-id",
            VALID_CALENDAR_ID,
            "--task-list-id",
            VALID_TASK_LIST_ID,
            "--fixture",
            "--json",
        ]
    )
    assert exit_code_json == 0
    json_out = capsys.readouterr().out
    data = json.loads(json_out)
    assert data["ephemeral_fixture_notice"] is True
    assert "ephemeral in-memory fixture" in data["fixture_warning"].lower()


# ===========================================================================
# 9. P-19.02 Safety-Closure Repaired Test Suite (B1, B2, B3, B4)
# ===========================================================================


class _DummyLiveCalendarTransport:
    def __init__(self, cal_id: str, title: str) -> None:
        self.cal_id = cal_id
        self.title = title

    def get_calendar(self, calendar_id: str) -> dict[str, Any] | None:
        if calendar_id == self.cal_id:
            return {"id": self.cal_id, "summary": self.title, "primary": False}
        return None

    def list_events_by_title(
        self, calendar_id: str, title: str, max_pages: int = 10
    ) -> list[CalendarTransportEvent]:
        return []

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        return None

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> CalendarTransportEvent:
        raise NotImplementedError

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        if_match: str | None = None,
    ) -> CalendarTransportEvent:
        raise NotImplementedError

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        raise NotImplementedError


class _DummyLiveTasksTransport:
    def __init__(self, tl_id: str, title: str) -> None:
        self.tl_id = tl_id
        self.title = title

    def get_task_list(self, task_list_id: str) -> dict[str, Any] | None:
        if task_list_id == self.tl_id:
            return {"id": self.tl_id, "title": self.title}
        return None

    def list_tasks(self, task_list_id: str, max_pages: int = 10) -> list[dict[str, Any]]:
        return []

    def delete_task(self, task_list_id: str, task_id: str) -> None:
        raise NotImplementedError


def test_b1_manifest_scope_mismatch_rejected(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Teardown fails closed if manifest scope mismatches target scope (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    # Manifest bound to a different calendar
    mismatched_manifest = DemoArtifactManifest(
        calendar_id="cal_different_id_999",
        task_list_id=valid_scope.task_list_id,
        owned_task_ids={"t_1"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=mismatched_manifest,
    )
    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.error_message == "MISMATCHED_MANIFEST_SCOPE"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b1_cli_ownership_unauthorized_on_live_transport(
    valid_scope: DemoResourceScope,
) -> None:
    """CLI-provided IDs alone must never confer deletion authority on a live transport (B1)."""
    cal_t = _DummyLiveCalendarTransport(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = _DummyLiveTasksTransport(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    cli_manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"live_task_claimed_by_cli"},
        is_cli_untrusted=True,
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=cli_manifest,
        provenance=EvidenceProvenance.LIVE_GOOGLE,
    )
    assert result.status == DemoToolingStatus.BLOCKED_UNAUTHORIZED
    assert result.error_message == "CLI_OWNERSHIP_UNAUTHORIZED_FOR_LIVE"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b1_rejects_falsely_claimed_unrelated_task_ownership(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Falsely claiming ownership of an unrelated task cannot authorize deletion (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "user_tax_return_task", "File 2025 Taxes")
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"user_tax_return_task"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CONTRADICTORY_OWNERSHIP_RECORD"
    assert result.writes_performed == 0
    assert result.is_success is False
    # Verify task was NOT deleted
    remaining = tasks_t.list_tasks(valid_scope.task_list_id)
    assert any(t.get("id") == "user_tax_return_task" for t in remaining)


def test_b1_rejects_stale_or_absent_claimed_ownership(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Claiming ownership of absent or stale resource fails closed before mutation (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_candidate_prep", DEFAULT_PREPARATION_TASK_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"nonexistent_task_ghost_id"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "STALE_OR_ABSENT_OWNERSHIP_RECORD"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b1_valid_proven_ownership_record_authorized_teardown(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Valid, proven operator-owned fixture cleanup succeeds (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_proven_1", DEFAULT_PREPARATION_TASK_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    record = DemoResourceOwnershipRecord(
        resource_id="t_proven_1",
        resource_kind="TASK",
        scope_id=valid_scope.task_list_id,
        provenance=EvidenceProvenance.FIXTURE,
        created_by="stilldone.demo_seeding",
        evidence_id="seed_run_12345",
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        records=(record,),
        owned_task_ids={"t_proven_1"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.TEARDOWN_COMPLETED
    assert result.writes_performed == 1
    assert result.items_deleted == 1
    assert result.is_success is True
    assert result.readback_verified is True


def test_b2_empty_calendar_fails_closed_never_already_clean(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Empty calendar fails closed; missing canonical event cannot report ALREADY_CLEAN (B2)."""
    cal_t, tasks_t = seeded_transports
    # Zero events, zero tasks on transports
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CANONICAL_EVENT_CORRUPTED_OR_MISSING"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b2_missing_canonical_event_with_owned_prep_task_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Missing canonical event with owned prep task present fails closed (B2)."""
    cal_t, tasks_t = seeded_transports
    # Zero calendar events
    tasks_t.add_task(valid_scope.task_list_id, "t_prep_owned", DEFAULT_PREPARATION_TASK_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"t_prep_owned"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CANONICAL_EVENT_CORRUPTED_OR_MISSING"
    assert result.writes_performed == 0
    assert result.is_success is False
    # Task must NOT have been deleted
    assert any(t.get("id") == "t_prep_owned" for t in tasks_t.list_tasks(valid_scope.task_list_id))


def test_b2_corrupted_canonical_event_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Corrupted canonical event (e.g. wrong start time) fails closed with 0 writes (B2)."""
    cal_t, tasks_t = seeded_transports
    event_spec = create_canonical_event_spec()
    # Add corrupted event (start time 09:00 instead of 07:30)
    cal_t.add_event(
        valid_scope.calendar_id,
        event_id="corrupt_ev",
        summary=event_spec.title,
        start_time="2026-10-15T09:00:00Z",
        end_time="2026-10-15T09:30:00Z",
    )
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        event_spec=event_spec,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CANONICAL_EVENT_CORRUPTED_OR_MISSING"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b2_clean_canonical_state_reports_already_clean(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """When canonical event verified and 0 demo items exist, report ALREADY_CLEAN (B2)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    # Zero tasks on task list
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
    )
    assert result.status == DemoToolingStatus.ALREADY_CLEAN
    assert result.writes_performed == 0
    assert result.is_success is True
    assert result.readback_verified is True


def test_b3_delete_acknowledgment_lost_and_readback_unavailable_reports_ambiguous(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Delete acknowledgment lost AND readback probe unavailable reports AMBIGUOUS (B3)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_lost_ack", DEFAULT_PREPARATION_TASK_TITLE)

    # delete raises exception
    def failing_delete(tl_id: str, task_id: str) -> None:
        raise ConnectionResetError("TCP reset by peer during DELETE")

    tasks_t.delete_task = failing_delete  # type: ignore[assignment]

    # We want list_tasks to succeed during preflight scan, but fail during post-delete probe!
    call_count = 0
    orig_list_tasks = tasks_t.list_tasks

    def list_tasks_mock(tl_id: str, max_pages: int = 10) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise ConnectionResetError("TCP reset by peer during readback probe")
        return orig_list_tasks(tl_id, max_pages=max_pages)

    tasks_t.list_tasks = list_tasks_mock  # type: ignore[assignment]

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"t_lost_ack"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    assert result.is_ambiguous_outcome is True
    assert result.unresolved_attempts == 1
    assert result.writes_performed == 0
    assert result.error_message == "AMBIGUOUS_DELETION_OUTCOME"
    assert result.is_success is False


def test_b3_first_write_success_second_write_ambiguous_preserves_confirmed_count(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """First write succeeds, second delete ambiguous; confirmed writes preserved at 1 (B3)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_1_ok", DEFAULT_PREPARATION_TASK_TITLE)
    tasks_t.add_task(valid_scope.task_list_id, "t_2_ambig", DEFAULT_PREPARATION_TASK_TITLE)

    orig_delete = tasks_t.delete_task
    orig_list_tasks = tasks_t.list_tasks

    probe_should_fail = False

    def list_tasks_hook(tl_id: str, max_pages: int = 10) -> list[dict[str, Any]]:
        if probe_should_fail:
            raise ConnectionResetError("Probe network down")
        return orig_list_tasks(tl_id, max_pages=max_pages)

    def delete_with_hook(tl_id: str, task_id: str) -> None:
        nonlocal probe_should_fail
        if task_id == "t_1_ok":
            orig_delete(tl_id, task_id)
        else:
            probe_should_fail = True
            raise ConnectionResetError("Socket broken during DELETE t_2_ambig")

    tasks_t.delete_task = delete_with_hook  # type: ignore[assignment]
    tasks_t.list_tasks = list_tasks_hook  # type: ignore[assignment]

    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"t_1_ok", "t_2_ambig"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    assert result.is_ambiguous_outcome is True
    assert result.unresolved_attempts == 1
    # Crucial invariant: exactly 1 confirmed write committed
    assert result.writes_performed == 1
    assert result.items_deleted == 1
    assert result.error_message == "AMBIGUOUS_DELETION_OUTCOME"
    assert result.is_success is False


def test_b4_adversarial_private_resource_ids_not_leaked_in_results_repr_or_json() -> None:
    """Private IDs not matched by generic token regexes must never leak (B4)."""
    private_cal = "family_court_custody_case_2026"
    private_tl = "confidential_medical_oncology_referral_list"
    private_ev = "divorce_hearing_judge_chambers_room_402"
    private_task = "pickup_prescription_chemotherapy_meds"

    raw_details = (
        f"Operation error on calendar {private_cal} for event {private_ev} "
        f"and task {private_task} inside list {private_tl}."
    )
    raw_error = f"Failed to delete event {private_ev}."

    result = DemoToolingResult(
        mode=DemoOperationMode.TEARDOWN,
        status=DemoToolingStatus.VERIFICATION_FAILED,
        provenance=EvidenceProvenance.FIXTURE,
        calendar_id=private_cal,
        task_list_id=private_tl,
        writes_performed=0,
        readback_verified=False,
        is_success=False,
        details=raw_details,
        error_message=raw_error,
        known_resource_ids=(private_cal, private_tl, private_ev, private_task),
    )

    all_privates = [private_cal, private_tl, private_ev, private_task]

    # Check details
    for s in all_privates:
        assert s not in result.details, f"Private ID {s} leaked in details!"

    # Check error_message
    assert result.error_message is not None
    for s in all_privates:
        assert s not in result.error_message, f"Private ID {s} leaked in error_message!"

    # Check repr()
    repr_str = repr(result)
    for s in all_privates:
        assert s not in repr_str, f"Private ID {s} leaked in repr()!"

    # Check str()
    str_str = str(result)
    for s in all_privates:
        assert s not in str_str, f"Private ID {s} leaked in str()!"

    # Check to_sanitized_dict()
    sanitized_dict = result.to_sanitized_dict()
    assert sanitized_dict["calendar_id"] == "[REDACTED]"
    assert sanitized_dict["task_list_id"] == "[REDACTED]"
    json_str = json.dumps(sanitized_dict)
    for s in all_privates:
        assert s not in json_str, f"Private ID {s} leaked in JSON serialization!"


# ===========================================================================
# Item B: Destructive-Ownership Authority (P-19.02 Repair)
# ===========================================================================


def test_b1_forged_manifest_with_untrusted_false_blocked_on_live_transport(
    valid_scope: DemoResourceScope,
) -> None:
    """Caller-controlled is_cli_untrusted=False must never authorize live teardown (B1)."""
    cal_t = _DummyLiveCalendarTransport(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = _DummyLiveTasksTransport(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    forged_manifest = DemoArtifactManifest(
        scope=valid_scope,
        owned_task_ids={"unrelated_live_task_123"},
        is_cli_untrusted=False,  # Attempting to forge trusted evidence via flag
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=forged_manifest,
        provenance=EvidenceProvenance.LIVE_GOOGLE,
    )
    assert result.status == DemoToolingStatus.BLOCKED_UNAUTHORIZED
    assert result.error_message == "CLI_OWNERSHIP_UNAUTHORIZED_FOR_LIVE"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b1_forged_ownership_records_blocked_on_live_transport(
    valid_scope: DemoResourceScope,
) -> None:
    """Caller-supplied ownership records with forged evidence fields cannot authorize
    live teardown (B1).
    """
    cal_t = _DummyLiveCalendarTransport(valid_scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)
    tasks_t = _DummyLiveTasksTransport(valid_scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    forged_record = DemoResourceOwnershipRecord(
        resource_id="unrelated_live_task_456",
        resource_kind="TASK",
        scope_id=valid_scope.task_list_id,
        provenance=EvidenceProvenance.LIVE_GOOGLE,
        created_by="StillDone:DemoTooling",  # Self-declared creator string
        evidence_id="fake_evidence_id_789",  # Self-declared evidence ID
    )
    forged_manifest = DemoArtifactManifest(
        scope=valid_scope,
        records=(forged_record,),
        owned_task_ids={"unrelated_live_task_456"},
        is_cli_untrusted=False,
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=forged_manifest,
        provenance=EvidenceProvenance.LIVE_GOOGLE,
    )
    assert result.status == DemoToolingStatus.BLOCKED_UNAUTHORIZED
    assert result.error_message == "CLI_OWNERSHIP_UNAUTHORIZED_FOR_LIVE"
    assert result.writes_performed == 0
    assert result.is_success is False


def test_b1_record_with_absent_scope_binding_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Record with absent scope binding fails closed before mutation (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(
        valid_scope.task_list_id, "t_prep_absent_scope", DEFAULT_PREPARATION_TASK_TITLE
    )
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    record = DemoResourceOwnershipRecord(
        resource_id="t_prep_absent_scope",
        resource_kind="TASK",
        scope_id="",  # Absent scope binding
        provenance=EvidenceProvenance.FIXTURE,
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        records=(record,),
        owned_task_ids={"t_prep_absent_scope"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.error_message == "ABSENT_RECORD_SCOPE_BINDING"
    assert result.writes_performed == 0


def test_b1_record_with_mismatched_scope_id_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Record with mismatched scope ID fails closed before mutation (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(
        valid_scope.task_list_id, "t_prep_mismatched_scope", DEFAULT_PREPARATION_TASK_TITLE
    )
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    record = DemoResourceOwnershipRecord(
        resource_id="t_prep_mismatched_scope",
        resource_kind="TASK",
        scope_id="completely_wrong_task_list_id",
        provenance=EvidenceProvenance.FIXTURE,
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        records=(record,),
        owned_task_ids={"t_prep_mismatched_scope"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
    )
    assert result.status == DemoToolingStatus.WRONG_TARGET_REJECTED
    assert result.error_message == "MISMATCHED_RECORD_SCOPE"
    assert result.writes_performed == 0


def test_b1_record_with_mismatched_provenance_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Record claiming contradictory provenance fails closed before mutation (B1)."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    tasks_t.add_task(valid_scope.task_list_id, "t_prep_wrong_prov", DEFAULT_PREPARATION_TASK_TITLE)
    confirmation = make_scope_bound_teardown_confirmation(
        valid_scope.calendar_id, valid_scope.task_list_id
    )
    record = DemoResourceOwnershipRecord(
        resource_id="t_prep_wrong_prov",
        resource_kind="TASK",
        scope_id=valid_scope.task_list_id,
        provenance=EvidenceProvenance.LIVE_GOOGLE,  # Contradicts FIXTURE
    )
    manifest = DemoArtifactManifest(
        scope=valid_scope,
        records=(record,),
        owned_task_ids={"t_prep_wrong_prov"},
    )
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=confirmation,
        manifest=manifest,
        provenance=EvidenceProvenance.FIXTURE,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CONTRADICTORY_PROVENANCE_RECORD"
    assert result.writes_performed == 0


# ===========================================================================
# Item C: Canonical Pre-State get_event Read-Back (P-19.02 Repair)
# ===========================================================================


def test_c_stale_listing_followed_by_missing_get_event_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Listing returns canonical event, but get_event reports None (disappeared/deleted event).

    Must fail closed (CONTRADICTORY_STATE / CANONICAL_EVENT_READBACK_MISMATCH) with zero writes,
    and must NEVER declare ALREADY_CLEAN.
    """
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    # Simulate race condition: event was in listing, but get_event reports disappeared
    cal_t.fail_readback = True

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=False,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CANONICAL_EVENT_READBACK_MISMATCH"
    assert result.writes_performed == 0
    assert result.readback_verified is False
    assert result.is_success is False


def test_c_stale_listing_followed_by_contradictory_get_event_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Listing returns canonical event, but get_event reports contradictory/drifted state.

    Must fail closed (CONTRADICTORY_STATE / CANONICAL_EVENT_READBACK_MISMATCH) with zero writes,
    and must NEVER declare ALREADY_CLEAN.
    """
    cal_t, tasks_t = seeded_transports
    event = add_canonical_event(cal_t, valid_scope.calendar_id)
    # Simulate drift: get_event returns modified start time
    spec = create_canonical_event_spec()
    drifted_event = CalendarTransportEvent(
        id=event.id,
        etag=event.etag,
        summary=spec.title,
        start_time="2026-10-15T09:00:00Z",  # Drifted start time
        end_time=spec.end_time,
        all_day=False,
        status="confirmed",
    )
    cal_t.inconsistent_readback_event = drifted_event

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=False,
    )
    assert result.status == DemoToolingStatus.CONTRADICTORY_STATE
    assert result.error_message == "CANONICAL_EVENT_READBACK_MISMATCH"
    assert result.writes_performed == 0
    assert result.readback_verified is False
    assert result.is_success is False


def test_c_stale_listing_followed_by_unreadable_get_event_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listing returns canonical event, but get_event raises transport error.

    Must fail closed (VERIFICATION_FAILED / CANONICAL_EVENT_READBACK_FAILED) with zero writes.
    """
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)

    def _broken_get_event(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Transient network outage during get_event probe")

    monkeypatch.setattr(cal_t, "get_event", _broken_get_event)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=False,
    )
    assert result.status == DemoToolingStatus.VERIFICATION_FAILED
    assert result.error_message == "CANONICAL_EVENT_READBACK_FAILED"
    assert result.writes_performed == 0
    assert result.readback_verified is False
    assert result.is_success is False


def test_c_matching_get_event_readback_verifies_already_clean(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    """Independent get_event read-back succeeds and matches spec, verifying ALREADY_CLEAN."""
    cal_t, tasks_t = seeded_transports
    add_canonical_event(cal_t, valid_scope.calendar_id)
    # 0 candidate tasks, 0 candidate extra events

    reads_before = cal_t.reads_count
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=False,
    )
    assert result.status == DemoToolingStatus.ALREADY_CLEAN
    assert result.readback_verified is True
    assert result.is_success is True
    assert result.writes_performed == 0
    # Must prove get_event was called in addition to list_events
    assert cal_t.reads_count > reads_before
