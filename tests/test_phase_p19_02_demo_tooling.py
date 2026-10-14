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
    DemoOperationMode,
    DemoToolingResult,
    DemoToolingStatus,
    execute_demo_resource_operation,
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
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    # permit_mutation=True but NO teardown_confirmation
    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=None,
    )

    assert result.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert result.writes_performed == 0
    assert result.is_success is False
    assert tasks_t.writes_count == 0


def test_teardown_wrong_confirmation_token_fails_closed(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation="WRONG_TOKEN",
    )

    assert result.status == DemoToolingStatus.CONFIRMATION_REQUIRED
    assert result.writes_performed == 0
    assert result.is_success is False
    assert tasks_t.writes_count == 0


def test_authorized_teardown_deletes_prep_task_and_verifies(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    result = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=CANONICAL_TEARDOWN_CONFIRMATION,
    )

    assert result.status == DemoToolingStatus.TEARDOWN_COMPLETED
    assert result.writes_performed == 1
    assert result.items_deleted == 1
    assert result.readback_verified is True
    assert result.is_success is True

    # Independent read-back confirmation: task is no longer present
    tasks = tasks_t.list_tasks(valid_scope.task_list_id)
    assert not any(t.get("title") == DEFAULT_PREPARATION_TASK_TITLE for t in tasks)


def test_teardown_idempotency_second_run_reports_already_clean(
    valid_scope: DemoResourceScope,
    seeded_transports: tuple[FakeCalendarSeedTransport, FakeTasksSeedTransport],
) -> None:
    cal_t, tasks_t = seeded_transports
    tasks_t.add_task(valid_scope.task_list_id, "t_101", DEFAULT_PREPARATION_TASK_TITLE)

    # First run: deletes task
    r1 = execute_demo_resource_operation(
        scope=valid_scope,
        calendar_transport=cal_t,
        tasks_transport=tasks_t,
        mode=DemoOperationMode.TEARDOWN,
        permit_mutation=True,
        teardown_confirmation=CANONICAL_TEARDOWN_CONFIRMATION,
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
        teardown_confirmation=CANONICAL_TEARDOWN_CONFIRMATION,
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
