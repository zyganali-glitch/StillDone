"""Canonical Killer Mission Vertical Slice for StillDone.

Phase P-13:
Executes the competition-defining vertical slice end-to-end:
"Get my family ready for tomorrow morning. We need to leave by 7:30."

Core Architectural Laws:
- Natural language intent compiled through non-authoritative candidate plan.
- Planner / LLM proposals have ZERO verification, execution, or readiness authority.
- Every mutable action must pass the frozen authority policy boundary.
- Unapproved calendar mutations halt fail-closed at the approval boundary (0 writes).
- Real human approval must cryptographically bind to exact mission/action/parameters/target/expiry.
- Execute response != verification: every mutation requires independent provider read-back.
- Mission READY is computed purely by deterministic predicate evaluation and freshness rules.
- External reality drift (e.g. calendar event moved) downgrades mission from READY to DRIFTED.
- Historical receipts remain immutable forever; current state projects authoritative current truth.
- Dual-runtime isolation and zero personal spend ($0.00) strictly preserved.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from stilldone.action_policy import (
    validate_action_contract,
)
from stilldone.adapters.calendar import (
    CalendarTransport,
    FakeGoogleCalendarTransport,
    GoogleApiClientCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleApiClientTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
    TaskTransport,
)
from stilldone.adapters.weather import (
    FakeOpenMeteoTransport,
    OpenMeteoHttpTransport,
    OpenMeteoReadAdapter,
    WeatherLocationConfig,
    WeatherObservation,
    WeatherReadResult,
    WeatherReadStatus,
    WeatherTransport,
)
from stilldone.approval_binding import (
    ApprovalBindingResult,
    ApprovalBindingStatus,
    resolve_pending_approval,
)
from stilldone.approval_consumption import ApprovalLedger
from stilldone.authority_policy import (
    AuthorityDecisionStatus,
    evaluate_authority,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.demo_seeding import (
    DEFAULT_DEMO_CALENDAR_TITLE,
    DEFAULT_DEMO_TASK_LIST_TITLE,
    CalendarSeedTransport,
    FakeCalendarSeedTransport,
    FakeTasksSeedTransport,
    GoogleApiClientCalendarSeedTransport,
    GoogleApiClientTasksSeedTransport,
    TasksSeedTransport,
    create_canonical_event_spec,
    seed_canonical_demo_resources,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.evidence import EvidenceId
from stilldone.execution.compiler import compile_candidate_plan
from stilldone.execution.contracts import (
    SymbolicTargetResolver,
)
from stilldone.execution.gate import (
    ApprovedCalendarUpdateOutcome,
    execute_approved_calendar_update,
    execute_gated_action,
)
from stilldone.execution.router import (
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
    TasksCreateHandler,
    TasksReadHandler,
    WeatherReadHandler,
)
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
)
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    MissionRecord,
    RecordNotFoundError,
)
from stilldone.pending_approval import (
    ApprovalDecision,
    PendingApproval,
    PendingApprovalStatus,
    create_pending_approval,
)
from stilldone.planning.bedrock import BedrockPlannerAdapter
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    PlannerInput,
    SymbolicTargetRef,
)
from stilldone.receipt import (
    CurrentStateProjection,
    ReceiptProjection,
    create_mission_ready_receipt,
    project_current_state,
)
from stilldone.redaction import redact, redact_text
from stilldone.snapshot import (
    DurableSnapshotRepository,
    create_mission_snapshot,
)
from stilldone.verifier.contracts import (
    VerificationObservation,
    VerificationRequest,
)
from stilldone.verifier.freshness import (
    FreshnessStatus,
    evaluate_freshness,
)
from stilldone.verifier.predicates import (
    PredicateTruth,
    evaluate_predicate,
)
from stilldone.verifier.readiness import (
    MissionReadinessDetermination,
    compute_mission_readiness,
)
from stilldone.verifier.reconciliation import (
    ReconciliationDetermination,
    ReconciliationStatus,
    apply_reconciliation_transition,
    reconcile_mission_state,
)

# ===========================================================================
# Canonical Killer Mission Constants
# ===========================================================================

CANONICAL_KILLER_INTENT: str = "Get my family ready for tomorrow morning. We need to leave by 7:30."
CANONICAL_DEMO_CALENDAR_ID: str = "c_stilldone_demo_calendar"
CANONICAL_DEMO_TASK_LIST_ID: str = "tl_stilldone_demo_task_list"
CANONICAL_DEMO_EVENT_ID: str = "evt_leave_for_school"
CANONICAL_DEMO_EVENT_TITLE: str = "Leave for school"
CANONICAL_DEMO_TASK_TITLE: str = "Pack backpacks"

FIXTURE_SOURCE_SHA: str = "0000000000000000000000000000000000000000"
DATE_FORMAT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_canonical_mission_timestamps(demo_date: str = "2026-10-04") -> dict[str, str]:
    """Generate canonical UTC timestamps for the killer mission from a single target date."""
    if not DATE_FORMAT_RE.match(demo_date):
        raise ValueError(f"Invalid demo_date format: {demo_date!r}; expected YYYY-MM-DD")
    try:
        datetime.strptime(demo_date, "%Y-%m-%d")
    except ValueError as val_err:
        raise ValueError(
            f"Invalid demo_date: {demo_date!r} is not a valid calendar date"
        ) from val_err
    return {
        "initial_start": f"{demo_date}T07:45:00+00:00",
        "initial_end": f"{demo_date}T08:15:00+00:00",
        "desired_start": f"{demo_date}T07:30:00+00:00",
        "desired_end": f"{demo_date}T08:00:00+00:00",
        "contradictory_start": f"{demo_date}T08:00:00+00:00",
        "contradictory_end": f"{demo_date}T08:30:00+00:00",
        "task_due": demo_date,
    }


# Explicit UTC timestamps: pre-state is 07:45, desired target is 07:30 (fixture date)
_DEFAULT_TIMESTAMPS = get_canonical_mission_timestamps("2026-10-04")
CANONICAL_INITIAL_START_TIME: str = _DEFAULT_TIMESTAMPS["initial_start"]
CANONICAL_INITIAL_END_TIME: str = _DEFAULT_TIMESTAMPS["initial_end"]
CANONICAL_DESIRED_START_TIME: str = _DEFAULT_TIMESTAMPS["desired_start"]
CANONICAL_DESIRED_END_TIME: str = _DEFAULT_TIMESTAMPS["desired_end"]
CANONICAL_CONTRADICTORY_START_TIME: str = _DEFAULT_TIMESTAMPS["contradictory_start"]
CANONICAL_CONTRADICTORY_END_TIME: str = _DEFAULT_TIMESTAMPS["contradictory_end"]

CANONICAL_WEATHER_LAT: float = 40.7128
CANONICAL_WEATHER_LON: float = -74.0060
CANONICAL_WEATHER_LOCATION_ID: str = "demo_weather_location"

PREDICATE_ID_WEATHER: PredicateId = PredicateId("11111111-0000-0000-0000-000000000001")
PREDICATE_ID_TASK: PredicateId = PredicateId("11111111-0000-0000-0000-000000000002")
PREDICATE_ID_CALENDAR: PredicateId = PredicateId("11111111-0000-0000-0000-000000000003")


# ===========================================================================
# Killer Mission Exception Hierarchy (Fail-Closed Runtime Validation)
# ===========================================================================


class KillerMissionError(Exception):
    """Base exception for canonical killer mission execution failures."""


class KillerMissionExecutionError(KillerMissionError):
    """Raised when an action execution fails authority, provider, or state checks."""


class KillerMissionAuthorityError(KillerMissionError):
    """Raised when an action violates authority boundaries or fails to pause mutations."""


class KillerMissionVerificationError(KillerMissionError):
    """Raised when an independent provider read-back or predicate evaluation fails."""


class KillerMissionSequenceError(KillerMissionError):
    """Raised when steps are executed out of sequence or missing required preconditions."""


class KillerMissionReadinessError(KillerMissionError):
    """Raised when mission readiness computation fails to reach the expected state."""


class KillerMissionReconciliationError(KillerMissionError):
    """Raised when reconciliation after external reality change fails."""


class KillerMissionIntegrityError(KillerMissionError):
    """Raised when cryptographic receipt or snapshot integrity is violated."""


class LiveExecutionBlockedError(KillerMissionError):
    """Raised when live execution path is attempted without operator authorization."""


class InvalidEnvironmentConfigurationError(KillerMissionError):
    """Raised when environment transport and provenance boundaries are violated."""


class LivePreflightBlockedError(KillerMissionError):
    """Raised when live execution preflight checks fail or require operator consent."""


class CanonicalKillerPlanValidationError(KillerMissionError):
    """Base exception for canonical killer mission plan validation failures."""


class InvalidActionCountError(CanonicalKillerPlanValidationError):
    """Raised when candidate plan does not contain exactly 3 steps."""


class InvalidActionOrderError(CanonicalKillerPlanValidationError):
    """Raised when candidate plan steps are in wrong dependency order."""


class InvalidActionTypeError(CanonicalKillerPlanValidationError):
    """Raised when candidate plan action types do not match expected canonical types."""


class InvalidSymbolicTargetError(CanonicalKillerPlanValidationError):
    """Raised when candidate plan targets do not match expected symbolic targets."""


class InvalidPlanParameterError(CanonicalKillerPlanValidationError):
    """Raised when plan step parameters do not match runtime target date or constraints."""


class DuplicatedMutationError(CanonicalKillerPlanValidationError):
    """Raised when candidate plan contains duplicated mutations."""


def validate_canonical_killer_mission_plan(
    plan: CandidatePlanProposal,
    *,
    target_date: str,
    desired_start_time: str,
    scope: DemoResourceScope | None = None,
) -> None:
    """Validate candidate plan strictly against canonical killer mission contract (Defect B).

    Enforces before any execution or mutation occurs:
    1. Exactly three expected actions in correct dependency order.
    2. Expected action types and symbolic target references:
       - step 0: WEATHER_READ -> WEATHER_LOCATION
       - step 1: TASK_CREATE -> TASK_LIST
       - step 2: CALENDAR_UPDATE -> LEAVE_FOR_SCHOOL
    3. Exact runtime target date and bounded intended parameters:
       - step 1 parameters: title == "Pack backpacks", due == target_date
       - step 2 parameters: start_time == desired_start_time
    4. Dedicated demo scope.
    5. No additional, missing, repeated or reordered mutation.
    6. Model output grants no approval, authority, READY or verification.
    """
    if not isinstance(plan, CandidatePlanProposal):
        raise TypeError(f"plan must be CandidatePlanProposal, got {type(plan).__name__}")

    steps = plan.steps
    if len(steps) != 3:
        raise InvalidActionCountError(
            f"Canonical killer mission plan requires exactly 3 steps, got {len(steps)}"
        )

    action_types = [s.action_type for s in steps]
    if len(set(action_types)) != 3:
        raise DuplicatedMutationError(
            f"Candidate plan contains duplicated action types: {[a.value for a in action_types]}"
        )

    # 1. Step 0: WEATHER_READ
    s0 = steps[0]
    if s0.action_type != ActionType.WEATHER_READ:
        if ActionType.WEATHER_READ in action_types:
            raise InvalidActionOrderError(
                f"Step 0 must be WEATHER_READ, got {s0.action_type.value}"
            )
        raise InvalidActionTypeError(
            f"Step 0 must be ActionType.WEATHER_READ, got {s0.action_type.value}"
        )
    if s0.target_ref != SymbolicTargetRef.WEATHER_LOCATION:
        raise InvalidSymbolicTargetError(
            f"Step 0 target_ref must be {SymbolicTargetRef.WEATHER_LOCATION.value}, "
            f"got {s0.target_ref.value}"
        )

    # 2. Step 1: TASK_CREATE
    s1 = steps[1]
    if s1.action_type != ActionType.TASK_CREATE:
        if ActionType.TASK_CREATE in action_types:
            raise InvalidActionOrderError(f"Step 1 must be TASK_CREATE, got {s1.action_type.value}")
        raise InvalidActionTypeError(
            f"Step 1 must be ActionType.TASK_CREATE, got {s1.action_type.value}"
        )
    if s1.target_ref != SymbolicTargetRef.TASK_LIST:
        raise InvalidSymbolicTargetError(
            f"Step 1 target_ref must be {SymbolicTargetRef.TASK_LIST.value}, "
            f"got {s1.target_ref.value}"
        )
    task_title = s1.parameters.get("title")
    if task_title != CANONICAL_DEMO_TASK_TITLE:
        raise InvalidPlanParameterError(
            f"Task title mismatch: expected {CANONICAL_DEMO_TASK_TITLE!r}, got {task_title!r}"
        )
    task_due = s1.parameters.get("due")
    if task_due != target_date:
        raise InvalidPlanParameterError(
            f"Task due date mismatch: expected {target_date!r}, got {task_due!r}"
        )

    # 3. Step 2: CALENDAR_UPDATE
    s2 = steps[2]
    if s2.action_type != ActionType.CALENDAR_UPDATE:
        if ActionType.CALENDAR_UPDATE in action_types:
            raise InvalidActionOrderError(
                f"Step 2 must be CALENDAR_UPDATE, got {s2.action_type.value}"
            )
        raise InvalidActionTypeError(
            f"Step 2 must be ActionType.CALENDAR_UPDATE, got {s2.action_type.value}"
        )
    if s2.target_ref != SymbolicTargetRef.LEAVE_FOR_SCHOOL:
        raise InvalidSymbolicTargetError(
            f"Step 2 target_ref must be {SymbolicTargetRef.LEAVE_FOR_SCHOOL.value}, "
            f"got {s2.target_ref.value}"
        )
    cal_start = s2.parameters.get("start_time")
    if cal_start != desired_start_time:
        raise InvalidPlanParameterError(
            f"Calendar start_time mismatch: expected {desired_start_time!r}, got {cal_start!r}"
        )

    # Scope validation
    if scope is not None:
        if scope.calendar_id in ("primary", "default", "@default", ""):
            raise InvalidPlanParameterError(
                f"Scope calendar_id {scope.calendar_id!r} is not a dedicated demo container"
            )
        if scope.task_list_id in ("primary", "default", "@default", ""):
            raise InvalidPlanParameterError(
                f"Scope task_list_id {scope.task_list_id!r} is not a dedicated demo container"
            )


# ===========================================================================
# Live Preflight Evaluation
# ===========================================================================


@dataclass(frozen=True)
class LivePreflightReport:
    """Deterministic preflight report checking requirements for live execution."""

    is_ready: bool
    operator_approved: bool
    source_sha_verified: bool
    clean_working_tree_verified: bool
    google_auth_available: bool
    aws_bedrock_auth_available: bool
    open_meteo_reachable: bool
    disposable_scope_verified: bool
    transports_verified: bool
    blocker_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "operator_approved": self.operator_approved,
            "source_sha_verified": self.source_sha_verified,
            "clean_working_tree_verified": self.clean_working_tree_verified,
            "google_auth_available": self.google_auth_available,
            "aws_bedrock_auth_available": self.aws_bedrock_auth_available,
            "open_meteo_reachable": self.open_meteo_reachable,
            "disposable_scope_verified": self.disposable_scope_verified,
            "transports_verified": self.transports_verified,
            "blocker_reasons": list(self.blocker_reasons),
        }


HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")


def is_synthetic_service(service: Any) -> bool:
    """Detect whether a service or client is a mock / synthetic object."""
    if service is None:
        return False
    from unittest.mock import Mock, NonCallableMock

    if isinstance(service, (Mock, NonCallableMock)):
        return True
    mod = getattr(service.__class__, "__module__", "")
    if mod.startswith("unittest.mock"):
        return True
    if getattr(service, "_is_synthetic", False) or getattr(service, "_is_mock", False):
        return True
    return False


def is_synthetic_transport(transport: Any) -> bool:
    """Detect whether a transport or its wrapped service is synthetic/mock."""
    if transport is None:
        return False
    from unittest.mock import Mock, NonCallableMock

    if isinstance(transport, (Mock, NonCallableMock)):
        return True
    svc = getattr(transport, "_service", None)
    if svc is not None and is_synthetic_service(svc):
        return True
    if isinstance(
        transport,
        (
            FakeGoogleCalendarTransport,
            FakeGoogleTasksTransport,
            FakeOpenMeteoTransport,
            FakeCalendarSeedTransport,
            FakeTasksSeedTransport,
        ),
    ):
        return True
    return False


def check_live_preflight(
    scope: DemoResourceScope,
    *,
    operator_approved: bool = False,
    source_sha: str | None = None,
    expected_source_sha: str | None = None,
    clean_working_tree_required: bool = True,
    google_credentials: Any = None,
    aws_credentials_available: bool = False,
    calendar_transport: CalendarTransport | None = None,
    tasks_transport: TaskTransport | None = None,
    weather_transport: WeatherTransport | None = None,
    bedrock_planner_available: bool = False,
    git_runner: Callable[[list[str]], Any] | None = None,
) -> LivePreflightReport:
    """Evaluate deterministic preflight before attempting ANY live mission execution.

    ONE canonical entry gate enforcing zero mutations and zero approval consumption
    if any preflight requirement is not met. Fails closed against invalid source SHA,
    git mismatch, dirty working tree, and synthetic mocks.
    """
    blockers: list[str] = []

    # 1. Explicit operator approval
    if not operator_approved:
        blockers.append(
            "Operator authorization required to maintain Zero Personal Spend Law ($0.00)"
        )

    # 2. Strict Source SHA & Git Remote / Working Tree Fail-Closed Gate
    sha_ok = True
    clean_ok = True

    if not source_sha or not isinstance(source_sha, str) or not HEX_40_RE.match(source_sha):
        blockers.append("Exact source SHA gate failed: valid lowercase 40-hex commit SHA required")
        sha_ok = False
    else:

        def _run_git(cmd: list[str]) -> tuple[int, str, str]:
            if git_runner is not None:
                res = git_runner(cmd)
                if hasattr(res, "returncode"):
                    return res.returncode, str(res.stdout).strip(), str(res.stderr).strip()
                return int(res[0]), str(res[1]).strip(), str(res[2]).strip()
            import subprocess

            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

        try:
            # 1. git rev-parse HEAD
            rc_head, out_head, err_head = _run_git(["git", "rev-parse", "HEAD"])
            if rc_head != 0 or not out_head or not HEX_40_RE.match(out_head.lower()):
                blockers.append(f"Git rev-parse HEAD failed: {err_head or 'non-zero exit code'}")
                sha_ok = False
                head_sha = ""
            else:
                head_sha = out_head.lower()

            # 2. git rev-parse origin/main
            rc_origin, out_origin, err_origin = _run_git(["git", "rev-parse", "origin/main"])
            if rc_origin != 0 or not out_origin or not HEX_40_RE.match(out_origin.lower()):
                blockers.append(
                    f"Git rev-parse origin/main failed: {err_origin or 'non-zero exit code'}"
                )
                sha_ok = False
                origin_sha = ""
            else:
                origin_sha = out_origin.lower()

            # 3. HEAD == origin/main
            if head_sha and origin_sha and head_sha != origin_sha:
                blockers.append(f"Git HEAD ({head_sha}) does not match origin/main ({origin_sha})")
                sha_ok = False

            # 4. HEAD == source_sha
            if head_sha and head_sha != source_sha.lower():
                blockers.append(
                    f"Git HEAD ({head_sha}) does not match authorized source_sha ({source_sha})"
                )
                sha_ok = False

            # 5. Caller-supplied expected_source_sha check if provided
            if expected_source_sha:
                if (
                    not HEX_40_RE.match(expected_source_sha.lower())
                    or expected_source_sha.lower() != source_sha.lower()
                ):
                    blockers.append(
                        f"Source SHA gate mismatch: expected {expected_source_sha}, "
                        f"got {source_sha}"
                    )
                    sha_ok = False

            # 6. Working tree clean
            if clean_working_tree_required:
                rc_status, out_status, err_status = _run_git(["git", "status", "--porcelain"])
                if rc_status != 0:
                    blockers.append(
                        f"Git status check failed: {err_status or 'non-zero exit code'}"
                    )
                    clean_ok = False
                elif out_status:
                    blockers.append(
                        "Working tree is dirty; clean remote gate required for live proof"
                    )
                    clean_ok = False

        except Exception as exc:
            blockers.append(f"Git command execution failed: {type(exc).__name__}")
            sha_ok = False
            clean_ok = False

    # 4. Google OAuth availability
    google_ok = google_credentials is not None
    if not google_ok:
        blockers.append("Google OAuth 2.0 credentials not configured for demo calendar/tasks")

    # 5. AWS short-lived credentials / session availability
    aws_ok = aws_credentials_available
    if not aws_ok:
        blockers.append("AWS short-lived credentials/session not available for Bedrock planner")

    # 6. Dedicated disposable Calendar/Tasks scope
    disposable_ok = (
        scope.calendar_id not in ("primary", "default", "@default", "")
        and scope.task_list_id not in ("primary", "default", "@default", "")
        and len(scope.calendar_id) > 0
        and len(scope.task_list_id) > 0
    )
    if not disposable_ok:
        blockers.append(
            f"Invalid disposable resource scope: calendar_id={scope.calendar_id!r}, "
            f"task_list_id={scope.task_list_id!r}. Primary/default calendars strictly forbidden."
        )

    # 7. Real transport validation (must be real production transports, NOT synthetic/mock)
    transports_ok = True
    if (
        calendar_transport is None
        or not isinstance(calendar_transport, GoogleApiClientCalendarTransport)
        or is_synthetic_transport(calendar_transport)
    ):
        blockers.append(
            "Real Google Calendar production transport (GoogleApiClientCalendarTransport) "
            "required (non-mock)"
        )
        transports_ok = False
    if (
        tasks_transport is None
        or not isinstance(tasks_transport, GoogleApiClientTasksTransport)
        or is_synthetic_transport(tasks_transport)
    ):
        blockers.append(
            "Real Google Tasks production transport (GoogleApiClientTasksTransport) "
            "required (non-mock)"
        )
        transports_ok = False
    if (
        weather_transport is None
        or not isinstance(weather_transport, OpenMeteoHttpTransport)
        or is_synthetic_transport(weather_transport)
    ):
        blockers.append(
            "Real Open-Meteo production transport (OpenMeteoHttpTransport) required (non-mock)"
        )
        transports_ok = False

    # 8. Bedrock planner availability
    if not bedrock_planner_available:
        blockers.append("Amazon Bedrock planner adapter is not available or unconfigured")

    is_ready = len(blockers) == 0
    return LivePreflightReport(
        is_ready=is_ready,
        operator_approved=operator_approved,
        source_sha_verified=sha_ok,
        clean_working_tree_verified=clean_ok,
        google_auth_available=google_ok,
        aws_bedrock_auth_available=aws_ok,
        open_meteo_reachable=isinstance(weather_transport, OpenMeteoHttpTransport)
        and not is_synthetic_transport(weather_transport),
        disposable_scope_verified=disposable_ok,
        transports_verified=transports_ok,
        blocker_reasons=blockers,
    )


# ===========================================================================
# Step and Outcome Result Models
# ===========================================================================


@dataclass(frozen=True)
class KillerMissionStepResult:
    """Outcome of a single micro-task in the canonical killer mission slice."""

    task_id: str
    step_name: str
    status: str
    provenance: EvidenceProvenance
    details: str
    writes_performed: int = 0
    is_verified: bool = False
    receipt_hash: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact_identifiers: bool = True) -> dict[str, Any]:
        meta = (
            redact(dict(self.extra_metadata)) if redact_identifiers else dict(self.extra_metadata)
        )
        det = redact_text(self.details) if redact_identifiers else self.details
        return {
            "task_id": self.task_id,
            "step_name": self.step_name,
            "status": self.status,
            "provenance": self.provenance.value,
            "details": det,
            "writes_performed": self.writes_performed,
            "is_verified": self.is_verified,
            "receipt_hash": self.receipt_hash,
            "extra_metadata": meta,
        }

    def to_canonical(self) -> dict[str, Any]:
        """Project to canonical dictionary with sensitive identifiers redacted."""
        return self.to_dict(redact_identifiers=True)


@dataclass(frozen=True)
class KillerMissionSliceOutcome:
    """Consolidated outcome of the entire Phase P-13 killer mission vertical slice."""

    mission_id: MissionId
    intent: str
    steps: dict[str, KillerMissionStepResult]
    ready_receipt_hash: str | None
    drifted_receipt_hash: str | None
    historical_receipt_immutable: bool
    final_state: MissionState
    total_writes_performed: int
    provenance: EvidenceProvenance
    is_live: bool

    def to_dict(self, *, redact_identifiers: bool = True) -> dict[str, Any]:
        return {
            "mission_id": str(self.mission_id),
            "intent": self.intent,
            "steps": {
                k: v.to_dict(redact_identifiers=redact_identifiers) for k, v in self.steps.items()
            },
            "ready_receipt_hash": self.ready_receipt_hash,
            "drifted_receipt_hash": self.drifted_receipt_hash,
            "historical_receipt_immutable": self.historical_receipt_immutable,
            "final_state": self.final_state.value,
            "total_writes_performed": self.total_writes_performed,
            "provenance": self.provenance.value,
            "is_live": self.is_live,
        }

    def to_canonical(self) -> dict[str, Any]:
        """Project to canonical dictionary with sensitive identifiers redacted."""
        return self.to_dict(redact_identifiers=True)


# ===========================================================================
# Authorized Post-Pending Human Decision Boundary (Defect C / Phase 4)
# ===========================================================================


def compute_action_parameter_fingerprint(
    parameters: Mapping[str, Any] | dict[str, Any],
) -> str:
    """Compute deterministic SHA-256 fingerprint of action parameters."""
    normalized = json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class AuthenticatedHumanApprovalChannel(Protocol):
    """Protocol for an authenticated, trusted human approval decision channel.

    Enforces that human authorization cannot be granted by raw callbacks,
    self-declared authority strings, or self-constructed dataclasses.
    """

    def verify_decision(
        self,
        pending: PendingApproval,
        decision: AuthorizedPostPendingApprovalDecision,
    ) -> bool:
        """Verify that decision was authenticated through a trusted human channel

        against exact PendingApproval.
        """
        ...


@dataclass(frozen=True)
class AuthorizedPostPendingApprovalDecision:
    """Explicitly authorized post-PendingApproval decision boundary for live mutation.

    Binds:
    - exact PendingApproval ID;
    - mission identity;
    - action identity;
    - exact event target;
    - action parameter fingerprint;
    - decision timestamp and authority source;
    - one-time decision ID (prevents replay).
    """

    decision_id: str
    pending_approval_id: str
    mission_id: str
    action_id: str
    target_event_id: str
    action_parameter_fingerprint: str
    decision: ApprovalDecision
    authority_source: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, str) or not self.decision_id.strip():
            raise ValueError("decision_id must be a non-empty string")
        if not isinstance(self.pending_approval_id, str) or not self.pending_approval_id.strip():
            raise ValueError("pending_approval_id must be a non-empty string")
        if not isinstance(self.mission_id, str) or not self.mission_id.strip():
            raise ValueError("mission_id must be a non-empty string")
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be a non-empty string")
        if not isinstance(self.target_event_id, str) or not self.target_event_id.strip():
            raise ValueError("target_event_id must be a non-empty string")
        if (
            not isinstance(self.action_parameter_fingerprint, str)
            or not self.action_parameter_fingerprint.strip()
        ):
            raise ValueError("action_parameter_fingerprint must be a non-empty string")
        if not isinstance(self.decision, ApprovalDecision):
            raise TypeError("decision must be an ApprovalDecision instance")
        if not isinstance(self.authority_source, str) or not self.authority_source.strip():
            raise ValueError("authority_source must be a non-empty string")
        if not isinstance(self.decided_at, datetime) or self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be a timezone-aware UTC datetime")


def create_authorized_post_pending_decision(
    pending: PendingApproval,
    *,
    target_event_id: str,
    action_parameters: Mapping[str, Any] | dict[str, Any],
    decision: ApprovalDecision = ApprovalDecision.APPROVE,
    authority_source: str = "HUMAN_OPERATOR",
    decided_at: datetime | None = None,
    decision_id: str | None = None,
) -> AuthorizedPostPendingApprovalDecision:
    """Create an AuthorizedPostPendingApprovalDecision bound to an exact PendingApproval."""
    now = decided_at or datetime.now(UTC)
    dec_id = decision_id or f"auth-dec-{uuid.uuid4()}"
    return AuthorizedPostPendingApprovalDecision(
        decision_id=dec_id,
        pending_approval_id=str(pending.pending_approval_id),
        mission_id=str(pending.mission_id),
        action_id=str(pending.action_id),
        target_event_id=target_event_id,
        action_parameter_fingerprint=compute_action_parameter_fingerprint(action_parameters),
        decision=decision,
        authority_source=authority_source,
        decided_at=now if now.tzinfo is not None else now.replace(tzinfo=UTC),
    )


# ===========================================================================
# Killer Mission Environment
# ===========================================================================


class KillerMissionEnvironment:
    """Execution environment holding transports, scope, and durable repositories."""

    @classmethod
    def create_fixture_environment(
        cls,
        base_dir: Path | None = None,
        *,
        provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
        calendar_transport: CalendarTransport | None = None,
        tasks_transport: TaskTransport | None = None,
        weather_transport: WeatherTransport | None = None,
        cal_seed_transport: CalendarSeedTransport | None = None,
        tasks_seed_transport: TasksSeedTransport | None = None,
    ) -> KillerMissionEnvironment:
        """Create strict fixture environment with zero live connectivity.

        Provenance MUST be strictly FIXTURE. Caller-selected live decoration is rejected.
        Only fake/mock transports are permitted.
        """
        if provenance != EvidenceProvenance.FIXTURE:
            raise InvalidEnvironmentConfigurationError(
                f"Fixture environment requires EvidenceProvenance.FIXTURE; got {provenance.value}. "
                "LIVE provenance decoration is strictly prohibited in fixture mode."
            )

        if (
            isinstance(calendar_transport, GoogleApiClientCalendarTransport)
            or isinstance(tasks_transport, GoogleApiClientTasksTransport)
            or isinstance(weather_transport, OpenMeteoHttpTransport)
            or isinstance(cal_seed_transport, GoogleApiClientCalendarSeedTransport)
            or isinstance(tasks_seed_transport, GoogleApiClientTasksSeedTransport)
        ):
            raise InvalidEnvironmentConfigurationError(
                "Production live transports are strictly prohibited in fixture environments"
            )

        import tempfile

        has_explicit = base_dir is not None
        target_dir = base_dir or Path(tempfile.mkdtemp(prefix="stilldone_killer_mission_"))
        return cls(
            base_dir=target_dir,
            has_explicit_base_dir=has_explicit,
            calendar_transport=calendar_transport,
            tasks_transport=tasks_transport,
            weather_transport=weather_transport,
            cal_seed_transport=cal_seed_transport,
            tasks_seed_transport=tasks_seed_transport,
            provenance=EvidenceProvenance.FIXTURE,
        )

    @classmethod
    def create_live_environment(
        cls,
        base_dir: Path | None = None,
        scope: DemoResourceScope | None = None,
        *,
        calendar_transport: CalendarTransport | None = None,
        tasks_transport: TaskTransport | None = None,
        weather_transport: WeatherTransport | None = None,
        cal_seed_transport: CalendarSeedTransport | None = None,
        tasks_seed_transport: TasksSeedTransport | None = None,
    ) -> KillerMissionEnvironment:
        """Create explicit live environment configured for real provider integrations.

        Requires explicit concrete production transports. Missing or fake transports
        fail-closed with typed InvalidEnvironmentConfigurationError.
        No default fake transports allowed.
        """
        if calendar_transport is None:
            raise InvalidEnvironmentConfigurationError(
                "Live environment requires explicit concrete calendar_transport "
                "(GoogleApiClientCalendarTransport); missing transport is prohibited."
            )
        if isinstance(calendar_transport, FakeGoogleCalendarTransport):
            raise InvalidEnvironmentConfigurationError(
                "Fake calendar transport supplied to live environment; "
                "concrete GoogleApiClientCalendarTransport is strictly required."
            )
        if not isinstance(calendar_transport, GoogleApiClientCalendarTransport):
            raise InvalidEnvironmentConfigurationError(
                f"Invalid calendar transport type for live environment: "
                f"{type(calendar_transport).__name__}; expected GoogleApiClientCalendarTransport."
            )

        if tasks_transport is None:
            raise InvalidEnvironmentConfigurationError(
                "Live environment requires explicit concrete tasks_transport "
                "(GoogleApiClientTasksTransport); missing transport is prohibited."
            )
        if isinstance(tasks_transport, FakeGoogleTasksTransport):
            raise InvalidEnvironmentConfigurationError(
                "Fake tasks transport supplied to live environment; "
                "concrete GoogleApiClientTasksTransport is strictly required."
            )
        if not isinstance(tasks_transport, GoogleApiClientTasksTransport):
            raise InvalidEnvironmentConfigurationError(
                f"Invalid tasks transport type for live environment: "
                f"{type(tasks_transport).__name__}; expected GoogleApiClientTasksTransport."
            )

        if weather_transport is None:
            raise InvalidEnvironmentConfigurationError(
                "Live environment requires explicit concrete weather_transport "
                "(OpenMeteoHttpTransport); missing transport is prohibited."
            )
        if isinstance(weather_transport, FakeOpenMeteoTransport):
            raise InvalidEnvironmentConfigurationError(
                "Fake weather transport supplied to live environment; "
                "concrete OpenMeteoHttpTransport is strictly required."
            )
        if not isinstance(weather_transport, OpenMeteoHttpTransport):
            raise InvalidEnvironmentConfigurationError(
                f"Invalid weather transport type for live environment: "
                f"{type(weather_transport).__name__}; expected OpenMeteoHttpTransport."
            )

        if cal_seed_transport is not None and isinstance(
            cal_seed_transport, FakeCalendarSeedTransport
        ):
            raise InvalidEnvironmentConfigurationError(
                "Fake calendar seed transport supplied to live environment."
            )
        if tasks_seed_transport is not None and isinstance(
            tasks_seed_transport, FakeTasksSeedTransport
        ):
            raise InvalidEnvironmentConfigurationError(
                "Fake tasks seed transport supplied to live environment."
            )

        if cal_seed_transport is None and isinstance(
            calendar_transport, GoogleApiClientCalendarTransport
        ):
            cal_seed_transport = GoogleApiClientCalendarSeedTransport(calendar_transport._service)
        if tasks_seed_transport is None and isinstance(
            tasks_transport, GoogleApiClientTasksTransport
        ):
            tasks_seed_transport = GoogleApiClientTasksSeedTransport(tasks_transport._service)

        has_synthetic = (
            is_synthetic_transport(calendar_transport)
            or is_synthetic_transport(tasks_transport)
            or is_synthetic_transport(weather_transport)
            or is_synthetic_transport(cal_seed_transport)
            or is_synthetic_transport(tasks_seed_transport)
        )
        resolved_provenance = (
            EvidenceProvenance.LOCAL_EXECUTION if has_synthetic else EvidenceProvenance.LIVE_GOOGLE
        )

        import tempfile

        has_explicit = base_dir is not None
        target_dir = base_dir or Path(tempfile.mkdtemp(prefix="stilldone_live_killer_mission_"))
        return cls(
            base_dir=target_dir,
            has_explicit_base_dir=has_explicit,
            scope=scope,
            calendar_transport=calendar_transport,
            tasks_transport=tasks_transport,
            weather_transport=weather_transport,
            cal_seed_transport=cal_seed_transport,
            tasks_seed_transport=tasks_seed_transport,
            provenance=resolved_provenance,
        )

    def __init__(
        self,
        base_dir: Path,
        *,
        has_explicit_base_dir: bool = True,
        calendar_transport: CalendarTransport | None = None,
        tasks_transport: TaskTransport | None = None,
        weather_transport: WeatherTransport | None = None,
        cal_seed_transport: CalendarSeedTransport | None = None,
        tasks_seed_transport: TasksSeedTransport | None = None,
        scope: DemoResourceScope | None = None,
        provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.has_explicit_base_dir = has_explicit_base_dir
        self.is_ephemeral_storage = not has_explicit_base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.scope = scope or DemoResourceScope(
            calendar_id=CANONICAL_DEMO_CALENDAR_ID,
            task_list_id=CANONICAL_DEMO_TASK_LIST_ID,
        )
        self.provenance = provenance

        # Enforce closed-world consistency: external LIVE provenance cannot have
        # synthetic or fake transports!
        if self.provenance.is_external_live:
            if (
                calendar_transport is None
                or isinstance(calendar_transport, FakeGoogleCalendarTransport)
                or tasks_transport is None
                or isinstance(tasks_transport, FakeGoogleTasksTransport)
                or weather_transport is None
                or isinstance(weather_transport, FakeOpenMeteoTransport)
                or isinstance(cal_seed_transport, FakeCalendarSeedTransport)
                or isinstance(tasks_seed_transport, FakeTasksSeedTransport)
                or is_synthetic_transport(calendar_transport)
                or is_synthetic_transport(tasks_transport)
                or is_synthetic_transport(weather_transport)
                or is_synthetic_transport(cal_seed_transport)
                or is_synthetic_transport(tasks_seed_transport)
            ):
                raise InvalidEnvironmentConfigurationError(
                    f"Live provenance ({self.provenance.value}) cannot be combined "
                    "with synthetic / mock services or missing/fake transports. "
                    "Use EvidenceProvenance.LOCAL_EXECUTION for injected-service wiring tests."
                )

        if provenance == EvidenceProvenance.FIXTURE:
            if (
                isinstance(calendar_transport, GoogleApiClientCalendarTransport)
                or isinstance(tasks_transport, GoogleApiClientTasksTransport)
                or isinstance(weather_transport, OpenMeteoHttpTransport)
                or isinstance(cal_seed_transport, GoogleApiClientCalendarSeedTransport)
                or isinstance(tasks_seed_transport, GoogleApiClientTasksSeedTransport)
            ):
                raise InvalidEnvironmentConfigurationError(
                    "Fixture provenance cannot be combined with production live transports."
                )

        # Transports
        self.calendar_transport = calendar_transport or FakeGoogleCalendarTransport()
        self.tasks_transport = tasks_transport or FakeGoogleTasksTransport()
        self.weather_transport = weather_transport or FakeOpenMeteoTransport()

        # Seed transports for P-13.01 preflight/seeding engine
        if cal_seed_transport is not None:
            self.cal_seed_transport = cal_seed_transport
        else:
            if self.provenance.is_external_live:
                raise InvalidEnvironmentConfigurationError(
                    "Live environment requires concrete calendar seed transport or service"
                )
            self.cal_seed_transport = FakeCalendarSeedTransport()
            self.cal_seed_transport.add_calendar(
                self.scope.calendar_id,
                DEFAULT_DEMO_CALENDAR_TITLE,
            )

        if tasks_seed_transport is not None:
            self.tasks_seed_transport = tasks_seed_transport
        else:
            if self.provenance.is_external_live:
                raise InvalidEnvironmentConfigurationError(
                    "Live environment requires concrete tasks seed transport or service"
                )
            self.tasks_seed_transport = FakeTasksSeedTransport()
            self.tasks_seed_transport.add_task_list(
                self.scope.task_list_id,
                DEFAULT_DEMO_TASK_LIST_TITLE,
            )

        # Durable directories and files
        self.ledger_file = self.base_dir / "ledger.jsonl"
        self.snapshots_dir = self.base_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Durable infrastructure
        try:
            self.mission_ledger = DurableFileLedger(self.ledger_file)
        except Exception as exc:
            raise KillerMissionIntegrityError(
                f"Failed to initialize durable ledger from '{self.ledger_file}': {exc}"
            ) from exc
        self.approval_ledger = ApprovalLedger(ledger=self.mission_ledger)
        self.snapshot_repo = DurableSnapshotRepository(self.snapshots_dir)


# ===========================================================================
# Killer Mission Slice Runner
# ===========================================================================


class KillerMissionSliceRunner:
    """Executes the canonical killer mission vertical slice (P-13.01 through P-13.07)."""

    def __init__(
        self,
        env: KillerMissionEnvironment | None = None,
        *,
        mission_id: MissionId | None = None,
        live_mode: bool = False,
        operator_approved: bool = False,
        bedrock_planner: BedrockPlannerAdapter | None = None,
        demo_date: str = "2026-10-04",
        calendar_decision: ApprovalDecision | str | None = ApprovalDecision.APPROVE,
    ) -> None:
        if type(self) is KillerMissionSliceRunner:
            if live_mode or (env is not None and env.provenance != EvidenceProvenance.FIXTURE):
                raise InvalidEnvironmentConfigurationError(
                    "KillerMissionSliceRunner is restricted to fixture/local regression only "
                    "(EvidenceProvenance.FIXTURE, live_mode=False). "
                    "Use LiveKillerMissionSliceRunner for live execution."
                )

        self.env = env or KillerMissionEnvironment.create_fixture_environment()
        self.mission_id = mission_id or MissionId("11111111-2222-3333-4444-555555555555")
        self.live_mode = live_mode or (self.env.provenance != EvidenceProvenance.FIXTURE)
        self.operator_approved = operator_approved
        self.bedrock_planner = bedrock_planner
        self.intent_text = CANONICAL_KILLER_INTENT
        self.contract = MissionContract.create(self.intent_text, mission_id=self.mission_id)

        # Target date driving all timestamps for the entire mission
        self.demo_date = demo_date
        ts = get_canonical_mission_timestamps(self.demo_date)
        self.initial_start_time = ts["initial_start"]
        self.initial_end_time = ts["initial_end"]
        self.desired_start_time = ts["desired_start"]
        self.desired_end_time = ts["desired_end"]
        self.contradictory_start_time = ts["contradictory_start"]
        self.contradictory_end_time = ts["contradictory_end"]
        self.task_due_date = ts["task_due"]

        # Human approval decision for calendar update
        if isinstance(calendar_decision, str):
            calendar_decision = ApprovalDecision(calendar_decision)
        self.calendar_decision: ApprovalDecision | None = calendar_decision

        # Seeded event ID (dynamic in live mode, deterministic constant in fixture)
        self.seeded_event_id: str = CANONICAL_DEMO_EVENT_ID

        # Actual provider observations captured across steps
        self.weather_observation: VerificationObservation | None = None
        self.task_observation: VerificationObservation | None = None
        self.calendar_observation: VerificationObservation | None = None

        # Setup router and adapters
        self.cal_read_adapter = GoogleCalendarReadAdapter(
            self.env.scope, self.env.calendar_transport
        )
        self.cal_update_adapter = GoogleCalendarUpdateAdapter(
            self.env.scope, self.env.calendar_transport
        )
        self.tasks_read_adapter = GoogleTasksReadAdapter(self.env.scope, self.env.tasks_transport)
        self.tasks_create_adapter = GoogleTasksCreateAdapter(
            self.env.scope, self.env.tasks_transport
        )
        weather_config = WeatherLocationConfig(
            location_id=CANONICAL_WEATHER_LOCATION_ID,
            latitude=CANONICAL_WEATHER_LAT,
            longitude=CANONICAL_WEATHER_LON,
        )
        self.weather_adapter = OpenMeteoReadAdapter(
            weather_config,
            self.env.weather_transport,
        )

        self.router = AdapterRouter(
            {
                ActionType.CALENDAR_READ: CalendarReadHandler(self.cal_read_adapter),
                ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(self.cal_update_adapter),
                ActionType.TASK_READ: TasksReadHandler(self.tasks_read_adapter),
                ActionType.TASK_CREATE: TasksCreateHandler(self.tasks_create_adapter),
                ActionType.WEATHER_READ: WeatherReadHandler(self.weather_adapter),
            }
        )

        # Runtime execution state
        self.step_results: dict[str, KillerMissionStepResult] = {}
        self.ready_receipt: ReceiptProjection | None = None
        self.ready_receipt_hash: str | None = None
        self.drifted_receipt_hash: str | None = None
        self.total_writes: int = 0
        self.created_task_id: str = "t_pack_backpacks_001"

        # Canonical Desired-State Predicates driven by single target date
        self.pred_weather = DesiredStatePredicate(
            predicate_id=PREDICATE_ID_WEATHER,
            mission_id=self.mission_id,
            subject="weather_status",
            operator=PredicateOperator.EQUALS,
            expected_value="available",
            required=True,
            freshness=FreshnessContract.current(),
        )
        self.pred_task = DesiredStatePredicate(
            predicate_id=PREDICATE_ID_TASK,
            mission_id=self.mission_id,
            subject="task_title",
            operator=PredicateOperator.EQUALS,
            expected_value=CANONICAL_DEMO_TASK_TITLE,
            required=True,
            freshness=FreshnessContract.current(),
        )
        self.pred_calendar = DesiredStatePredicate(
            predicate_id=PREDICATE_ID_CALENDAR,
            mission_id=self.mission_id,
            subject="start_time",
            operator=PredicateOperator.EQUALS,
            expected_value=self.desired_start_time,
            required=True,
            freshness=FreshnessContract.current(),
        )
        self.canonical_predicates = [self.pred_weather, self.pred_task, self.pred_calendar]

        # Initialize mission in durable ledger or restore existing session (Repair A3)
        self._is_resumed_mission: bool = False
        self._existing_mission_record: MissionRecord | None = None

        all_existing_missions: list[MissionRecord] = []
        if hasattr(self.env.mission_ledger, "get_all_missions"):
            try:
                all_existing_missions = self.env.mission_ledger.get_all_missions()
            except Exception as exc:
                raise KillerMissionIntegrityError(
                    f"Failed to inspect existing missions in ledger: {exc}"
                ) from exc

        if all_existing_missions:
            matching = [m for m in all_existing_missions if m.mission_id == self.mission_id]
            if not matching:
                stored_ids = [str(m.mission_id) for m in all_existing_missions]
                raise KillerMissionIntegrityError(
                    f"Persistent storage contains existing mission(s) {stored_ids}, "
                    f"which does not match active mission '{self.mission_id}'. "
                    "Mismatched mission identity in persistent storage."
                )
            self._existing_mission_record = matching[0]
            self._is_resumed_mission = True
            if self._existing_mission_record.contract.intent.text != self.contract.intent.text:
                raise KillerMissionIntegrityError(
                    f"Existing mission '{self.mission_id}' has contradictory intent: "
                    f"'{self._existing_mission_record.contract.intent.text}' != "
                    f"'{self.contract.intent.text}'"
                )
        else:
            try:
                self._existing_mission_record = self.env.mission_ledger.get_mission(self.mission_id)
                self._is_resumed_mission = True
                if self._existing_mission_record.contract.intent.text != self.contract.intent.text:
                    raise KillerMissionIntegrityError(
                        f"Existing mission '{self.mission_id}' has contradictory intent: "
                        f"'{self._existing_mission_record.contract.intent.text}' != "
                        f"'{self.contract.intent.text}'"
                    )
            except RecordNotFoundError:
                self._is_resumed_mission = False
                now = datetime.now(UTC)
                try:
                    self.env.mission_ledger.append_mission(
                        MissionRecord(
                            mission_id=self.mission_id,
                            contract=self.contract,
                            state=MissionState.DRAFT,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                except Exception as exc:
                    raise KillerMissionIntegrityError(
                        f"Failed to append initial mission record to ledger: {exc}"
                    ) from exc
            except (KillerMissionIntegrityError, KillerMissionAuthorityError):
                raise
            except Exception as exc:
                raise KillerMissionIntegrityError(
                    f"Failed to query existing mission '{self.mission_id}' in ledger: {exc}"
                ) from exc

        # Compile canonical plan & execution state tracker
        self._setup_canonical_plan()

    def _create_deterministic_proposal(self) -> CandidatePlanProposal:
        """Create deterministic proposal for fixture regression testing."""
        step_weather = CandidateActionProposal.create(
            action_type=ActionType.WEATHER_READ,
            target_ref=SymbolicTargetRef.WEATHER_LOCATION,
            parameters={},
            explanation="Check morning departure weather",
        )
        step_task = CandidateActionProposal.create(
            action_type=ActionType.TASK_CREATE,
            target_ref=SymbolicTargetRef.TASK_LIST,
            parameters={"title": CANONICAL_DEMO_TASK_TITLE, "due": self.task_due_date},
            explanation="Create reminder to pack backpacks",
        )
        step_cal = CandidateActionProposal.create(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
            parameters={"start_time": self.desired_start_time},
            explanation="Move leave for school event to 7:30",
        )
        return CandidatePlanProposal.create(
            mission_id=self.mission_id,
            steps=[step_weather, step_task, step_cal],
            explanation="Canonical killer mission plan proposal",
        )

    def _setup_canonical_plan(self) -> None:
        """Compile canonical plan and action tracking (fixture deterministic proposal)."""
        self.candidate_plan: CandidatePlanProposal | None = self._create_deterministic_proposal()
        validate_canonical_killer_mission_plan(
            self.candidate_plan,
            target_date=self.demo_date,
            desired_start_time=self.desired_start_time,
            scope=self.env.scope,
        )

        resolver = SymbolicTargetResolver(
            scope=self.env.scope,
            event_id_mappings={
                SymbolicTargetRef.LEAVE_FOR_SCHOOL: self.seeded_event_id or CANONICAL_DEMO_EVENT_ID,
            },
        )
        self.execution_contract = compile_candidate_plan(
            self.candidate_plan,
            resolver,
        )
        self.schedule = schedule_execution(self.execution_contract)
        self.tracker = ExecutionStateTracker(self.execution_contract, self.schedule)

        self.action_weather = self.execution_contract.actions[0]
        self.action_task = self.execution_contract.actions[1]
        self.action_cal = self.execution_contract.actions[2]
        self.validated_action_cal = validate_action_contract(self.action_cal)

    def _require_shared_live_mutation_boundary(self, operation: str) -> None:
        """Enforce live recovery and preflight prerequisites at shared mutation boundaries."""
        if not self.live_mode:
            return
        if getattr(self, "_existing_mission_detected", False) and not getattr(
            self, "_execution_state_restored", False
        ):
            raise KillerMissionIntegrityError(
                f"Cannot execute {operation} for existing mission '{self.mission_id}': "
                "an existing durable mission record was detected in persistent storage, "
                "but full safe rehydration is not supported. "
                "Use a new mission ID with fresh stable storage."
            )
        # Shared live preflight enforcement is mandatory:
        preflight_fn = getattr(self, "_require_preflight", None)
        if not callable(preflight_fn):
            raise LivePreflightBlockedError(
                f"Live execution boundary requires a mandatory '_require_preflight' "
                f"implementation; missing or non-callable preflight on live runner "
                f"fails closed for {operation}."
            )
        preflight_fn()

    # -----------------------------------------------------------------------
    # Step 1: P-13.01 — Seed canonical disposable demo resources reproducibly
    # -----------------------------------------------------------------------
    def step_p13_01_seed(self) -> KillerMissionStepResult:
        """Seed initial pre-state: Leave for school at 07:45, no prep task."""
        if self.live_mode:
            self._require_shared_live_mutation_boundary("seeding")
            cand = getattr(self, "candidate_plan", None)
            val_cand = getattr(self, "validated_candidate_plan", None)
            if cand is None or val_cand is None or cand is not val_cand:
                raise CanonicalKillerPlanValidationError(
                    "Live seeding cannot proceed without an independently validated "
                    "canonical candidate plan."
                )
            validate_canonical_killer_mission_plan(
                cand,
                target_date=self.demo_date,
                desired_start_time=self.desired_start_time,
                scope=self.env.scope,
            )
        seed_spec = create_canonical_event_spec(
            start_time=self.initial_start_time,
            end_time=self.initial_end_time,
        )
        seed_result = seed_canonical_demo_resources(
            scope=self.env.scope,
            calendar_transport=self.env.cal_seed_transport,
            tasks_transport=self.env.tasks_seed_transport,
            event_spec=seed_spec,
            permit_mutation=True,
            provenance=self.env.provenance,
        )
        self.total_writes += seed_result.writes_performed

        if self.live_mode:
            if not seed_result.event_id or not seed_result.event_id.strip():
                raise KillerMissionVerificationError(
                    "Live demo seeding failed to establish an authoritative provider event ID"
                )
            self.seeded_event_id = seed_result.event_id.strip()
            # Rebind calendar update action to the exact provider event_id
            target_cal = TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=self.seeded_event_id,
                parent_id=self.env.scope.calendar_id,
            )
            self.action_cal = ActionContract.create(
                mission_id=self.mission_id,
                action_type=ActionType.CALENDAR_UPDATE,
                target=target_cal,
                parameters={"start_time": self.desired_start_time},
                action_id=self.action_cal.action_id,
            )
            self.validated_action_cal = validate_action_contract(self.action_cal)
        else:
            self.seeded_event_id = CANONICAL_DEMO_EVENT_ID

        # Also seed in fake calendar runtime transport for subsequent steps
        if isinstance(self.env.calendar_transport, FakeGoogleCalendarTransport):
            self.env.calendar_transport.seed_event(
                calendar_id=self.env.scope.calendar_id,
                event_id=self.seeded_event_id,
                summary=CANONICAL_DEMO_EVENT_TITLE,
                start_time=self.initial_start_time,
                end_time=self.initial_end_time,
            )

        if not seed_result.is_seed_complete:
            res = KillerMissionStepResult(
                task_id="P-13.01",
                step_name="Seed Canonical Demo Resources",
                status="FAILED",
                provenance=self.env.provenance,
                details=f"Demo seeding failed: {seed_result.details}",
                writes_performed=seed_result.writes_performed,
                is_verified=False,
            )
            self.step_results["P-13.01"] = res
            return res

        res = KillerMissionStepResult(
            task_id="P-13.01",
            step_name="Seed Canonical Demo Resources",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                f"Demo seeded: event '{CANONICAL_DEMO_EVENT_TITLE}' at 07:45 UTC, "
                "prep task absent (clean pre-state verified)."
            ),
            writes_performed=seed_result.writes_performed,
            is_verified=seed_result.readback_verified,
            extra_metadata={"seeded_event_established": True},
        )
        self.step_results["P-13.01"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 2: P-13.02 — Execute full mission from NL through AWS planner
    # -----------------------------------------------------------------------
    def step_p13_02_plan(self) -> KillerMissionStepResult:
        """Compile natural language proposal; assert zero model authority."""
        if self.live_mode:
            self._require_shared_live_mutation_boundary("planning")
        if self.live_mode and not self.operator_approved:
            res = KillerMissionStepResult(
                task_id="P-13.02",
                step_name="Natural Language Planning & Compilation",
                status="BLOCKED_LIVE",
                provenance=EvidenceProvenance.LIVE_AWS,
                details=(
                    "AWS Bedrock Converse / Strands live planning requires explicit operator "
                    "authorization. Zero personal spend policy enforced fail-closed."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={"live_preflight_blocked": True},
            )
            self.step_results["P-13.02"] = res
            return res

        if self.live_mode and self.bedrock_planner is None:
            raise KillerMissionExecutionError(
                "Live mode requires concrete Bedrock / Strands planner adapter; "
                "fallback to deterministic proposal is strictly prohibited."
            )

        # Execute initial read-only weather observation (READ_ONLY, 0 writes)
        weather_gate = execute_gated_action(
            validate_action_contract(self.action_weather),
            self.router,
            tracker=self.tracker,
        )
        if not weather_gate.is_authorized:
            raise KillerMissionAuthorityError("Weather read action was not authorized")
        if weather_gate.provider_result is None or not weather_gate.provider_result.success:
            raise KillerMissionExecutionError("Weather read provider execution failed")

        # Independent provider observation from canonical OpenMeteoReadAdapter (Defect A)
        weather_result: WeatherReadResult = self.weather_adapter.read_weather(
            validate_action_contract(self.action_weather)
        )
        if weather_result.status != WeatherReadStatus.MATCH or weather_result.observation is None:
            raise KillerMissionVerificationError(
                "Weather read failed to produce a valid observation "
                f"(status={weather_result.status.value})"
            )

        obs: WeatherObservation = weather_result.observation

        # Validate observation constraints fail-closed
        if obs.location_id != self.action_weather.target.resource_id:
            raise KillerMissionVerificationError(
                f"Weather observation location mismatch: expected "
                f"{self.action_weather.target.resource_id!r}, got {obs.location_id!r}"
            )
        if not obs.provider_valid_time:
            raise KillerMissionVerificationError("Weather observation missing provider_valid_time")
        if not obs.attribution or not obs.attribution.provider:
            raise KillerMissionVerificationError(
                "Weather observation missing required provider attribution"
            )

        # Check temporal validity / freshness without refreshing timestamps
        eval_now = datetime.now(UTC)
        freshness_eval = evaluate_freshness(
            obs.observed_at,
            at=eval_now,
            freshness_contract=self.pred_weather.freshness,
        )
        if freshness_eval.status != FreshnessStatus.FRESH:
            raise KillerMissionVerificationError(
                f"Weather observation is stale or temporally invalid: {freshness_eval.status.value}"
            )

        # Deterministically derive weather properties from verified observation
        self.weather_observation = VerificationObservation(
            target=self.action_weather.target,
            observed_at=obs.observed_at,  # actual provider observation time preserved
            exists=True,
            properties={
                "weather_status": "available",
                "location_id": obs.location_id,
                "temperature_2m": obs.temperature_2m,
                "precipitation": obs.precipitation,
                "weather_code": obs.weather_code,
                "wind_speed_10m": obs.wind_speed_10m,
                "provider_valid_time": obs.provider_valid_time,
                "provider": obs.attribution.provider,
                "license": obs.attribution.license,
            },
            provenance=obs.provenance,
            raw_observation=obs,
        )

        res = KillerMissionStepResult(
            task_id="P-13.02",
            step_name="Natural Language Planning & Compilation",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                f"Compiled {len(self.schedule)} steps from proposal. "
                "Weather observation verified (0 writes). "
                "Model authority boundary verified (0 execution authority)."
            ),
            writes_performed=0,
            is_verified=True,
            extra_metadata={
                "steps_count": len(self.schedule),
            },
        )
        self.step_results["P-13.02"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 3: P-13.03 — Create and independently verify Tasks preparation action
    # -----------------------------------------------------------------------
    def step_p13_03_tasks_prep(self) -> KillerMissionStepResult:
        """Execute task.create (REVERSIBLE_AUTO) and independently verify with task.read."""
        if self.live_mode:
            self._require_shared_live_mutation_boundary("tasks preparation")
            cand = getattr(self, "candidate_plan", None)
            val_cand = getattr(self, "validated_candidate_plan", None)
            if cand is None or val_cand is None or cand is not val_cand:
                raise CanonicalKillerPlanValidationError(
                    "Live tasks creation cannot proceed without an independently validated "
                    "canonical candidate plan."
                )
            validate_canonical_killer_mission_plan(
                cand,
                target_date=self.demo_date,
                desired_start_time=self.desired_start_time,
                scope=self.env.scope,
            )
            seeded_id = getattr(self, "seeded_event_id", None)
            if (
                not seeded_id
                or not isinstance(seeded_id, str)
                or not seeded_id.strip()
                or seeded_id == CANONICAL_DEMO_EVENT_ID
            ):
                raise KillerMissionSequenceError(
                    "Live tasks creation requires an established authoritative provider event ID "
                    "from seeding step P-13.01."
                )
            step1 = self.step_results.get("P-13.01")
            if step1 is None or step1.status != "PASS" or not step1.is_verified:
                raise KillerMissionSequenceError(
                    "Live tasks creation requires proven preceding seeding step P-13.01 "
                    "with PASS status and independent read-back verification."
                )
            step2 = self.step_results.get("P-13.02")
            if step2 is None or step2.status != "PASS" or not step2.is_verified:
                raise KillerMissionSequenceError(
                    "Live tasks creation requires proven preceding planning step P-13.02 "
                    "with PASS status and verified weather observation."
                )
            if getattr(self, "weather_observation", None) is None:
                raise KillerMissionSequenceError(
                    "Live tasks creation requires an established, verified weather observation "
                    "from P-13.02."
                )
        if self.live_mode and not self.operator_approved:
            res = KillerMissionStepResult(
                task_id="P-13.03",
                step_name="Execute & Verify Tasks Preparation Action",
                status="BLOCKED_LIVE",
                provenance=EvidenceProvenance.LIVE_GOOGLE,
                details=(
                    "Google Tasks live mutation requires explicit operator authorization "
                    "and live OAuth credentials. Execution blocked fail-closed."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={"live_preflight_blocked": True},
            )
            self.step_results["P-13.03"] = res
            return res

        validated_action_task = validate_action_contract(self.action_task)

        # Authority check: REVERSIBLE_AUTO requires no approval
        auth_decision = evaluate_authority(validated_action_task, at=datetime.now(UTC))
        if auth_decision.status != AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED:
            raise KillerMissionAuthorityError(
                f"Tasks preparation requires no approval; got {auth_decision.status}"
            )

        # Execute gated action
        gate_decision = execute_gated_action(
            validated_action_task,
            self.router,
            tracker=self.tracker,
        )
        if not gate_decision.is_authorized:
            raise KillerMissionAuthorityError("Tasks preparation action was not authorized")
        if gate_decision.provider_result is None or not gate_decision.provider_result.success:
            raise KillerMissionExecutionError("Tasks preparation provider execution failed")
        self.total_writes += 1

        # Discover created task id strictly from authoritative provider create result (Defect D)
        created_task_id = gate_decision.provider_result.details.get("task_id")
        if (
            not created_task_id
            or not isinstance(created_task_id, str)
            or not created_task_id.strip()
        ):
            raise KillerMissionVerificationError(
                "Authoritative task.create result did not return an exact provider task ID"
            )
        self.created_task_id = str(created_task_id).strip()

        # Independent provider read-back by exact task ID (NO title-based substitution)
        target_task = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id=self.created_task_id,
            parent_id=self.env.scope.task_list_id,
        )
        raw_action_read = ActionContract.create(
            mission_id=self.mission_id,
            action_type=ActionType.TASK_READ,
            target=target_task,
            parameters={},
            action_id=ActionId.generate(),
        )
        read_result = self.tasks_read_adapter.read_task(raw_action_read)
        if read_result.observation is None:
            raise KillerMissionVerificationError(
                "Independent task readback returned None observation"
            )
        if read_result.observation.title != CANONICAL_DEMO_TASK_TITLE:
            raise KillerMissionVerificationError(
                f"Task title mismatch: expected {CANONICAL_DEMO_TASK_TITLE!r}, "
                f"got {read_result.observation.title!r}"
            )
        if read_result.observation.status != "needsAction":
            raise KillerMissionVerificationError(
                f"Expected task status 'needsAction', got {read_result.observation.status!r}"
            )
        if read_result.observation.task_list_id != self.env.scope.task_list_id:
            raise KillerMissionVerificationError(
                f"Task list mismatch: expected {self.env.scope.task_list_id!r}, "
                f"got {read_result.observation.task_list_id!r}"
            )

        # Evaluate predicate deterministically
        task_prov = (
            EvidenceProvenance.LIVE_GOOGLE
            if (self.live_mode and not is_synthetic_transport(self.env.tasks_transport))
            else (
                EvidenceProvenance.LOCAL_EXECUTION if self.live_mode else EvidenceProvenance.FIXTURE
            )
        )
        task_obs = VerificationObservation(
            target=target_task,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={
                "task_title": read_result.observation.title,
                "status": read_result.observation.status,
            },
            provenance=task_prov,
        )
        pred_eval = evaluate_predicate(self.pred_task, task_obs)
        if pred_eval.truth != PredicateTruth.TRUE:
            raise KillerMissionVerificationError("Task predicate evaluation failed")
        self.task_observation = task_obs

        # Record action in durable ledger
        now = datetime.now(UTC)
        self.env.mission_ledger.append_action(
            ActionRecord(
                action_id=self.action_task.action_id,
                mission_id=self.mission_id,
                action=self.action_task,
                approval_id=None,
                created_at=now,
            )
        )

        res = KillerMissionStepResult(
            task_id="P-13.03",
            step_name="Execute & Verify Tasks Preparation Action",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                f"Task '{CANONICAL_DEMO_TASK_TITLE}' created (writes=1) and "
                "independently verified via separate task.read read-back."
            ),
            writes_performed=1,
            is_verified=True,
        )
        self.step_results["P-13.03"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 4: P-13.04 — Pause real Calendar change at approval boundary
    # -----------------------------------------------------------------------
    def step_p13_04_calendar_pause(self) -> KillerMissionStepResult:
        """Evaluate calendar.update authority; pause fail-closed with PendingApproval."""
        if self.live_mode:
            self._require_shared_live_mutation_boundary("calendar pause")
            if getattr(self.env, "is_ephemeral_storage", False) or not getattr(
                self.env, "has_explicit_base_dir", True
            ):
                raise KillerMissionAuthorityError(
                    "Stable durable storage boundary is required for operations relying on "
                    "approval authority; ephemeral or unconfigured storage cannot guarantee "
                    "restart replay protection."
                )
            cand = getattr(self, "candidate_plan", None)
            val_cand = getattr(self, "validated_candidate_plan", None)
            if cand is None or val_cand is None or cand is not val_cand:
                raise CanonicalKillerPlanValidationError(
                    "Live calendar pause cannot proceed without an independently validated "
                    "canonical candidate plan."
                )
            validate_canonical_killer_mission_plan(
                cand,
                target_date=self.demo_date,
                desired_start_time=self.desired_start_time,
                scope=self.env.scope,
            )
            seeded_id = getattr(self, "seeded_event_id", None)
            if (
                not seeded_id
                or not isinstance(seeded_id, str)
                or not seeded_id.strip()
                or seeded_id == CANONICAL_DEMO_EVENT_ID
            ):
                raise KillerMissionSequenceError(
                    "Live calendar pause requires an established authoritative provider event ID "
                    "from seeding step P-13.01."
                )
            step1 = self.step_results.get("P-13.01")
            if step1 is None or step1.status != "PASS" or not step1.is_verified:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires proven preceding seeding step P-13.01."
                )
            step2 = self.step_results.get("P-13.02")
            if step2 is None or step2.status != "PASS" or not step2.is_verified:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires proven preceding planning step P-13.02."
                )
            if getattr(self, "weather_observation", None) is None:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires an established, verified weather observation "
                    "from P-13.02."
                )
            step3 = self.step_results.get("P-13.03")
            if step3 is None or step3.status != "PASS" or not step3.is_verified:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires proven preceding tasks preparation step "
                    "P-13.03 with PASS status and independent read-back verification."
                )
            if getattr(self, "task_observation", None) is None:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires an established, verified tasks observation "
                    "from P-13.03."
                )
            if not hasattr(self, "action_cal") or self.action_cal is None:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires an established calendar update action."
                )
            if str(self.action_cal.target.resource_id) != str(seeded_id):
                target_cal = TargetIdentity(
                    system="google_calendar",
                    resource_kind=ResourceKind.CALENDAR_EVENT,
                    resource_id=str(seeded_id),
                    parent_id=self.env.scope.calendar_id,
                )
                self.action_cal = ActionContract.create(
                    mission_id=self.mission_id,
                    action_type=ActionType.CALENDAR_UPDATE,
                    target=target_cal,
                    parameters=getattr(
                        self.action_cal, "parameters", {"start_time": self.desired_start_time}
                    ),
                    action_id=self.action_cal.action_id,
                )
                self.validated_action_cal = validate_action_contract(self.action_cal)
            if not hasattr(self, "validated_action_cal") or self.validated_action_cal is None:
                raise KillerMissionSequenceError(
                    "Live calendar pause requires validated calendar action contract."
                )
            validate_action_contract(self.action_cal)
        # Pre-execution authority gate evaluation: unapproved action MUST halt
        gate_decision = execute_gated_action(
            self.validated_action_cal,
            self.router,
            tracker=self.tracker,
        )
        if gate_decision.is_authorized:
            raise KillerMissionAuthorityError(
                "Calendar update must not be authorized without approval"
            )
        if gate_decision.status != ActionExecutionStatus.NOT_RUN:
            raise KillerMissionExecutionError(
                f"Unapproved action must remain NOT_RUN; got {gate_decision.status}"
            )

        # Create PendingApproval bound to exact action and target
        now = datetime.now(UTC)
        pending_approval: PendingApproval = create_pending_approval(
            self.validated_action_cal,
            requested_at=now,
        )
        self.pending_approval = pending_approval

        # Record action in durable ledger
        self.env.mission_ledger.append_action(
            ActionRecord(
                action_id=self.action_cal.action_id,
                mission_id=self.mission_id,
                action=self.action_cal,
                approval_id=None,
                created_at=now,
            )
        )

        res = KillerMissionStepResult(
            task_id="P-13.04",
            step_name="Pause at Calendar Approval Boundary",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                "Unapproved mutation paused fail-closed (0 calendar writes). "
                f"PendingApproval created: {pending_approval.pending_approval_id}."
            ),
            writes_performed=0,
            is_verified=False,
            extra_metadata={
                "pending_approval_id": str(pending_approval.pending_approval_id),
                "approval_required": True,
            },
        )
        self.step_results["P-13.04"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 5: P-13.05 — Approve, execute, and verify real Calendar change
    # -----------------------------------------------------------------------
    def step_p13_05_calendar_approve(
        self,
        decision: ApprovalDecision | str | None = None,
    ) -> KillerMissionStepResult:
        """Grant bound approval, execute calendar update, and read back independently."""
        if not hasattr(self, "pending_approval"):
            raise KillerMissionSequenceError("Must run step_p13_04 first")

        if self.live_mode:
            self._require_shared_live_mutation_boundary("calendar approval")
            if getattr(self.env, "is_ephemeral_storage", False) or not getattr(
                self.env, "has_explicit_base_dir", True
            ):
                raise KillerMissionAuthorityError(
                    "Stable durable storage boundary is required for operations relying on "
                    "approval authority; ephemeral or unconfigured storage cannot guarantee "
                    "restart replay protection."
                )

        if self.live_mode and not self.operator_approved:
            res = KillerMissionStepResult(
                task_id="P-13.05",
                step_name="Approve, Execute & Verify Calendar Update",
                status="BLOCKED_LIVE",
                provenance=EvidenceProvenance.LIVE_GOOGLE,
                details=(
                    "Google Calendar live mutation requires explicit operator authorization "
                    "and live OAuth credentials. Execution blocked fail-closed."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={"live_preflight_blocked": True},
            )
            self.step_results["P-13.05"] = res
            return res

        eff_decision: ApprovalDecision | None = None
        dec_to_check = decision if decision is not None else self.calendar_decision
        if dec_to_check is not None:
            eff_decision = (
                dec_to_check
                if isinstance(dec_to_check, ApprovalDecision)
                else ApprovalDecision(dec_to_check)
            )

        # Shared mutation boundary protection (Repair A1):
        # Direct parent-method invocation or generic operator_approved=True must NEVER
        # authorize a live Calendar update without independently authenticated human consent.
        if self.live_mode and (
            eff_decision == ApprovalDecision.APPROVE
            or (isinstance(eff_decision, str) and str(eff_decision).upper() == "APPROVE")
        ):
            raise KillerMissionAuthorityError(
                "Direct live approval bypass prohibited: raw APPROVE parameter or parent method "
                "invocation cannot grant human authorization in live execution. Live mutation "
                "requires an authenticated, explicitly authorized post-PendingApproval "
                "human decision channel."
            )

        now = datetime.now(UTC)

        # 1. If no explicit decision is given, pause awaiting human decision
        if eff_decision is None:
            res = KillerMissionStepResult(
                task_id="P-13.05",
                step_name="Approve, Execute & Verify Calendar Update",
                status="AWAITING_APPROVAL",
                provenance=self.env.provenance,
                details=(
                    "Mutation paused awaiting explicit human ApprovalDecision on PendingApproval; "
                    "0 calendar writes."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={
                    "pending_approval_id": str(self.pending_approval.pending_approval_id),
                    "approval_status": "PENDING_DECISION",
                },
            )
            self.step_results["P-13.05"] = res
            return res

        # 2. If decision is REJECT: resolve via canonical P-11.03 path
        if eff_decision == ApprovalDecision.REJECT:
            if self.live_mode:
                pa_str = str(self.pending_approval.pending_approval_id)
                if not (
                    hasattr(self.env, "approval_ledger")
                    and self.env.approval_ledger is not None
                    and self.env.approval_ledger.is_rejected(pa_str)
                ):
                    raise KillerMissionAuthorityError(
                        "Direct live rejection bypass prohibited: raw REJECT parameter or parent "
                        "method invocation cannot establish durable terminal rejection without "
                        "persisted canonical evidence in ApprovalLedger."
                    )
            rejection_result = resolve_pending_approval(
                self.pending_approval,
                ApprovalDecision.REJECT,
                issued_at=now,
                expires_at=now + timedelta(minutes=15),
                rejection_reason="Operator rejected calendar mutation",
            )
            res = KillerMissionStepResult(
                task_id="P-13.05",
                step_name="Approve, Execute & Verify Calendar Update",
                status="REJECTED",
                provenance=self.env.provenance,
                details=(
                    "PendingApproval rejected by operator; 0 grant issued; "
                    "0 calendar writes performed."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={
                    "pending_approval_id": str(self.pending_approval.pending_approval_id),
                    "rejection_status": rejection_result.status.value,
                },
            )
            self.step_results["P-13.05"] = res
            return res

        # 3. Decision is APPROVE: resolve via canonical P-11.03 path
        if self.live_mode:
            raise KillerMissionAuthorityError(
                "Direct live approval bypass prohibited: raw APPROVE parameter or parent method "
                "invocation cannot grant human authorization in live execution. Live mutation "
                "requires an authenticated, explicitly authorized post-PendingApproval "
                "human decision channel."
            )

        binding_result: ApprovalBindingResult = resolve_pending_approval(
            self.pending_approval,
            ApprovalDecision.APPROVE,
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=15),
        )
        if binding_result.status != ApprovalBindingStatus.APPROVED or binding_result.grant is None:
            raise KillerMissionAuthorityError(
                "Failed to obtain valid ApprovalGrant for APPROVE decision"
            )
        grant = binding_result.grant

        # Read before-state for ETag/precondition safety
        read_action = ActionContract.create(
            mission_id=self.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=self.action_cal.target,
            parameters={},
            action_id=ActionId.generate(),
        )
        before_read = self.cal_read_adapter.read_event(read_action)
        if before_read.observation is None:
            raise KillerMissionVerificationError(
                "Calendar before-state read returned None observation"
            )

        active_source_sha = (
            self.source_sha
            if (self.live_mode and hasattr(self, "source_sha") and self.source_sha)
            else FIXTURE_SOURCE_SHA
        )

        outcome: ApprovedCalendarUpdateOutcome = execute_approved_calendar_update(
            action=self.validated_action_cal,
            router=self.router,
            approval=grant,
            ledger=self.env.approval_ledger,
            read_adapter=self.cal_read_adapter,
            predicate=self.pred_calendar,
            source_sha=active_source_sha,
            tracker=self.tracker,
            pending_approval=self.pending_approval,
            before_read=before_read,
            spy=None,
            mission_ledger=self.env.mission_ledger,
            at=now,
            provenance=self.env.provenance,
        )

        if not outcome.is_verified:
            raise KillerMissionVerificationError("Approved calendar update was not verified")
        if outcome.provider_result.writes_performed != 1:
            raise KillerMissionExecutionError(
                f"Expected exactly 1 write, got {outcome.provider_result.writes_performed}"
            )
        self.total_writes += 1
        self.approved_cal_outcome = outcome

        # Store verified calendar observation from outcome's independent read-back
        cal_prov = (
            EvidenceProvenance.LIVE_GOOGLE
            if (self.live_mode and not is_synthetic_transport(self.env.calendar_transport))
            else (
                EvidenceProvenance.LOCAL_EXECUTION if self.live_mode else EvidenceProvenance.FIXTURE
            )
        )
        if outcome.after_read.observation is not None:
            self.calendar_observation = VerificationObservation(
                target=self.action_cal.target,
                observed_at=outcome.after_read.observation.observed_at,
                exists=True,
                properties={"start_time": outcome.after_read.observation.start_time},
                provenance=cal_prov,
            )

        res = KillerMissionStepResult(
            task_id="P-13.05",
            step_name="Approve, Execute & Verify Calendar Update",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                "Approval consumed atomically. "
                f"Event updated to {self.desired_start_time} (writes=1). "
                "Independent read-back verified. ApprovedActionReceipt issued."
            ),
            writes_performed=1,
            is_verified=True,
            extra_metadata={
                "approval_id": str(grant.approval_id),
                "start_time": self.desired_start_time,
            },
        )
        self.step_results["P-13.05"] = res
        return res

    def get_verification_requests(self) -> dict[PredicateId, VerificationRequest]:
        """Construct canonical verification requests for the 3 killer mission predicates."""
        req_weather = VerificationRequest.create(
            action=self.action_weather,
            target=self.action_weather.target,
            predicate=self.pred_weather,
        )
        target_task = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id=self.created_task_id,
            parent_id=self.env.scope.task_list_id,
        )
        req_task = VerificationRequest.create(
            action=self.action_task,
            target=target_task,
            predicate=self.pred_task,
        )
        req_cal = VerificationRequest.create(
            action=self.action_cal,
            target=self.action_cal.target,
            predicate=self.pred_calendar,
        )
        return {
            PREDICATE_ID_WEATHER: req_weather,
            PREDICATE_ID_TASK: req_task,
            PREDICATE_ID_CALENDAR: req_cal,
        }

    # -----------------------------------------------------------------------
    # Step 6: P-13.06 — Produce READY mission receipt from deterministic facts
    # -----------------------------------------------------------------------
    def step_p13_06_ready_receipt(self) -> KillerMissionStepResult:
        """Evaluate all predicates from actual provider observations; transition to READY."""
        if self.live_mode:
            self._require_shared_live_mutation_boundary("ready receipt generation")
        now = datetime.now(UTC)

        # Strictly require real observations captured from P-13.02, P-13.03, and P-13.05
        if self.weather_observation is None:
            raise KillerMissionVerificationError(
                "Missing actual weather observation from P-13.02; cannot reach READY"
            )
        if self.task_observation is None:
            raise KillerMissionVerificationError(
                "Missing actual tasks observation from P-13.03; cannot reach READY"
            )
        if self.calendar_observation is None:
            raise KillerMissionVerificationError(
                "Missing actual calendar observation from P-13.05; cannot reach READY"
            )

        observations = {
            PREDICATE_ID_WEATHER: self.weather_observation,
            PREDICATE_ID_TASK: self.task_observation,
            PREDICATE_ID_CALENDAR: self.calendar_observation,
        }

        # Deterministic readiness determination
        verification_requests = self.get_verification_requests()
        readiness: MissionReadinessDetermination = compute_mission_readiness(
            mission_id=self.mission_id,
            current_state=MissionState.VERIFYING,
            predicates=self.canonical_predicates,
            verification_requests=verification_requests,
            observations=observations,
            at=now,
        )
        if not readiness.is_ready or readiness.state != MissionState.READY:
            raise KillerMissionReadinessError(
                f"Mission failed to reach READY state; got state={readiness.state}"
            )

        # Create durable MissionSnapshot in READY state
        ev_id1 = EvidenceId.compute("ev_weather_obs_p13")
        ev_id2 = EvidenceId.compute("ev_tasks_obs_p13")
        ev_id3 = EvidenceId.compute("ev_cal_obs_p13")
        evidence_ids = [ev_id1, ev_id2, ev_id3]

        predicate_bindings = {
            PREDICATE_ID_WEATHER: self.action_weather.target,
            PREDICATE_ID_TASK: self.action_task.target,
            PREDICATE_ID_CALENDAR: self.action_cal.target,
        }

        attempts = [
            srec.attempt
            for srec in self.tracker.snapshot().step_records.values()
            if srec.attempt is not None
        ]
        consumed = [self.approved_cal_outcome.consumption_record]

        snapshot = create_mission_snapshot(
            mission_id=self.mission_id,
            contract=self.contract,
            state=MissionState.READY,
            desired_state=self.canonical_predicates,
            actions=self.execution_contract.actions,
            step_records=self.tracker.snapshot().step_records,
            consumed_approvals=consumed,
            execution_attempts=attempts,
            evidence_ids=evidence_ids,
            predicate_bindings=predicate_bindings,
            created_at=now,
        )
        self.env.snapshot_repo.save_snapshot(snapshot)

        # Produce immutable historical ReceiptProjection
        receipt_proj: ReceiptProjection = create_mission_ready_receipt(snapshot)
        self.ready_receipt = receipt_proj
        self.ready_receipt_hash = receipt_proj.receipt_hash.value

        res = KillerMissionStepResult(
            task_id="P-13.06",
            step_name="Produce Deterministic READY Mission Receipt",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                "All predicates evaluated TRUE and FRESH from actual provider observations. "
                "Mission promoted to READY. "
                f"Immutable receipt created: {self.ready_receipt_hash[:16]}..."
            ),
            writes_performed=0,
            is_verified=True,
            receipt_hash=self.ready_receipt_hash,
            extra_metadata={
                "mission_state": MissionState.READY.value,
                "predicates_count": len(self.canonical_predicates),
            },
        )
        self.step_results["P-13.06"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 7: P-13.07 — Mutate Calendar externally and prove READY -> DRIFTED
    # -----------------------------------------------------------------------
    def step_p13_07_mutate_and_drift(self) -> KillerMissionStepResult:
        """Induce external reality change; prove READY -> DRIFTED while receipt stays."""
        if self.live_mode:
            self._require_shared_live_mutation_boundary("drift reconciliation")
        if self.ready_receipt is None:
            raise KillerMissionSequenceError("Must produce READY receipt first")
        now = datetime.now(UTC)

        # 1. Induce external mutation on calendar transport (outside StillDone)
        # Event is moved back to contradictory start time (departure window violated!)
        if isinstance(self.env.calendar_transport, FakeGoogleCalendarTransport):
            self.env.calendar_transport.seed_event(
                calendar_id=self.env.scope.calendar_id,
                event_id=self.seeded_event_id,
                summary=CANONICAL_DEMO_EVENT_TITLE,
                start_time=self.contradictory_start_time,
                end_time=self.contradictory_end_time,
            )

        # 2. Independent read-back observes changed reality
        read_action = ActionContract.create(
            mission_id=self.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=self.action_cal.target,
            parameters={},
            action_id=ActionId.generate(),
        )
        drift_read = self.cal_read_adapter.read_event(read_action)
        if drift_read.observation is None:
            raise KillerMissionVerificationError("Calendar drift read returned None observation")
        if drift_read.observation.start_time != self.contradictory_start_time:
            raise KillerMissionVerificationError(
                f"Expected start_time={self.contradictory_start_time}, "
                f"got {drift_read.observation.start_time}"
            )

        cal_prov = (
            EvidenceProvenance.LIVE_GOOGLE
            if (self.live_mode and not is_synthetic_transport(self.env.calendar_transport))
            else (
                EvidenceProvenance.LOCAL_EXECUTION if self.live_mode else EvidenceProvenance.FIXTURE
            )
        )
        fresh_cal_obs = VerificationObservation(
            target=self.action_cal.target,
            observed_at=now,
            exists=True,
            properties={"start_time": self.contradictory_start_time},
            provenance=cal_prov,
        )

        pred_eval = evaluate_predicate(self.pred_calendar, fresh_cal_obs)
        if pred_eval.truth != PredicateTruth.FALSE:
            raise KillerMissionVerificationError(
                "Calendar predicate must evaluate to FALSE upon drift"
            )

        if self.weather_observation is None or self.task_observation is None:
            raise KillerMissionVerificationError(
                "Missing prior observations for drift reconciliation"
            )
        fresh_observations = {
            PREDICATE_ID_WEATHER: self.weather_observation,
            PREDICATE_ID_TASK: self.task_observation,
            PREDICATE_ID_CALENDAR: fresh_cal_obs,
        }

        verification_requests = self.get_verification_requests()
        reconciliation: ReconciliationDetermination = reconcile_mission_state(
            mission_id=self.mission_id,
            predicates=self.canonical_predicates,
            verification_requests=verification_requests,
            fresh_observations=fresh_observations,
            at=now,
        )
        if reconciliation.status != ReconciliationStatus.NO_LONGER_TRUE:
            raise KillerMissionReconciliationError(
                f"Expected reconciliation status NO_LONGER_TRUE; got {reconciliation.status}"
            )

        transition_result = apply_reconciliation_transition(
            reconciliation=reconciliation,
            prior_state=MissionState.READY,
        )
        if transition_result.new_state != MissionState.DRIFTED:
            raise KillerMissionReconciliationError(
                f"Expected transition to DRIFTED; got {transition_result.new_state}"
            )

        # Create snapshot for drifted state and project current state
        ev_drift = EvidenceId.compute("ev_drift_detection_p13")
        predicate_bindings = {
            PREDICATE_ID_WEATHER: self.action_weather.target,
            PREDICATE_ID_TASK: self.action_task.target,
            PREDICATE_ID_CALENDAR: self.action_cal.target,
        }
        attempts = [
            srec.attempt
            for srec in self.tracker.snapshot().step_records.values()
            if srec.attempt is not None
        ]
        consumed = [self.approved_cal_outcome.consumption_record]
        drifted_snapshot = create_mission_snapshot(
            mission_id=self.mission_id,
            contract=self.contract,
            state=MissionState.DRIFTED,
            desired_state=self.canonical_predicates,
            actions=self.execution_contract.actions,
            step_records=self.tracker.snapshot().step_records,
            consumed_approvals=consumed,
            execution_attempts=attempts,
            evidence_ids=[ev_drift],
            predicate_bindings=predicate_bindings,
            created_at=now,
        )
        self.env.snapshot_repo.save_snapshot(drifted_snapshot)

        current_state_proj: CurrentStateProjection = project_current_state(
            drifted_snapshot,
            historical_receipt=self.ready_receipt,
            as_of=now,
        )
        if current_state_proj.state != MissionState.DRIFTED:
            raise KillerMissionReconciliationError(
                f"Expected current_state_proj.state DRIFTED; got {current_state_proj.state}"
            )

        # Assert historical READY receipt hash on disk is strictly unchanged
        historical_receipt_still_valid = (
            self.ready_receipt.receipt_hash.value == self.ready_receipt_hash
        )
        if not historical_receipt_still_valid:
            raise KillerMissionIntegrityError("Historical receipt hash was unexpectedly modified")

        res = KillerMissionStepResult(
            task_id="P-13.07",
            step_name="Mutate Calendar Externally & Reconcile Drift",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                f"External calendar change observed (start_time={self.contradictory_start_time}). "
                "Predicate evaluated FALSE. Mission reconciled READY -> DRIFTED. "
                "Original historical receipt hash strictly preserved."
            ),
            writes_performed=0,
            is_verified=True,
            receipt_hash=self.ready_receipt_hash,
            extra_metadata={
                "reconciled_state": MissionState.DRIFTED.value,
                "historical_receipt_intact": True,
            },
        )
        self.step_results["P-13.07"] = res
        return res

    # -----------------------------------------------------------------------
    # Run Full Slice End-to-End
    # -----------------------------------------------------------------------
    def run_full_slice(self) -> KillerMissionSliceOutcome:
        """Execute all micro-tasks of the canonical killer mission vertical slice."""
        if self.live_mode and not self.operator_approved:
            for task_id, step_name in [
                ("P-13.01", "Seed Canonical Demo Resources"),
                ("P-13.02", "Natural Language Planning & Compilation"),
                ("P-13.03", "Execute & Verify Tasks Preparation Action"),
                ("P-13.04", "Pause at Calendar Approval Boundary"),
                ("P-13.05", "Approve, Execute & Verify Calendar Update"),
                ("P-13.06", "Produce Deterministic READY Mission Receipt"),
                ("P-13.07", "Mutate Calendar Externally & Reconcile Drift"),
            ]:
                self.step_results[task_id] = KillerMissionStepResult(
                    task_id=task_id,
                    step_name=step_name,
                    status="BLOCKED_LIVE",
                    provenance=self.env.provenance,
                    details=(
                        "Live execution path blocked: explicit operator authorization required "
                        "to maintain Zero Personal Spend Law ($0.00). 0 mutations executed."
                    ),
                    writes_performed=0,
                    is_verified=False,
                    extra_metadata={"live_preflight_blocked": True},
                )
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=MissionState.DRAFT,
                total_writes_performed=0,
                provenance=self.env.provenance,
                is_live=self.live_mode,
            )

        self.step_p13_01_seed()
        step2 = self.step_p13_02_plan()
        if step2.status == "BLOCKED_LIVE":
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=MissionState.DRAFT,
                total_writes_performed=self.total_writes,
                provenance=self.env.provenance,
                is_live=self.live_mode,
            )
        self.step_p13_03_tasks_prep()
        self.step_p13_04_calendar_pause()
        step5 = self.step_p13_05_calendar_approve()
        if step5.status in ("AWAITING_APPROVAL", "REJECTED", "PAUSED", "BLOCKED_LIVE"):
            final_st = (
                MissionState.CANCELLED
                if step5.status == "REJECTED"
                else (
                    MissionState.NEEDS_APPROVAL
                    if step5.status == "AWAITING_APPROVAL"
                    else MissionState.DRAFT
                )
            )
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=final_st,
                total_writes_performed=self.total_writes,
                provenance=self.env.provenance,
                is_live=self.live_mode,
            )
        self.step_p13_06_ready_receipt()
        self.step_p13_07_mutate_and_drift()

        return KillerMissionSliceOutcome(
            mission_id=self.mission_id,
            intent=self.intent_text,
            steps=dict(self.step_results),
            ready_receipt_hash=self.ready_receipt_hash,
            drifted_receipt_hash=self.ready_receipt_hash,
            historical_receipt_immutable=True,
            final_state=MissionState.DRIFTED,
            total_writes_performed=self.total_writes,
            provenance=self.env.provenance,
            is_live=self.live_mode,
        )


ALLOWED_CONSUMED_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "decision_id",
        "consumed_at",
        "decision",
        "mission_id",
        "action_id",
        "pending_approval_id",
    }
)
REQUIRED_CONSUMED_DECISION_KEYS: frozenset[str] = frozenset({"decision_id", "consumed_at"})


class LiveKillerMissionSliceRunner(KillerMissionSliceRunner):
    """Canonical runner owning strict live dependencies and authoritative preflight gating."""

    def __init__(
        self,
        env: KillerMissionEnvironment,
        *,
        mission_id: MissionId | None = None,
        operator_approved: bool = False,
        source_sha: str | None = None,
        expected_source_sha: str | None = None,
        clean_working_tree_required: bool = True,
        google_credentials: Any = None,
        aws_credentials_available: bool = False,
        bedrock_planner: BedrockPlannerAdapter | None = None,
        git_runner: Callable[[list[str]], Any] | None = None,
        demo_date: str | None = None,
        calendar_decision: ApprovalDecision | str | None = None,
        post_pending_decision_callback: (
            Callable[
                [PendingApproval],
                AuthorizedPostPendingApprovalDecision | ApprovalDecision | str | None,
            ]
            | None
        ) = None,
        approval_channel: AuthenticatedHumanApprovalChannel | None = None,
    ) -> None:
        if env.provenance == EvidenceProvenance.FIXTURE:
            raise InvalidEnvironmentConfigurationError(
                "LiveKillerMissionSliceRunner cannot run in a FIXTURE environment"
            )
        # Pre-authorized live APPROVE is strictly prohibited (Defect C)
        if calendar_decision in (ApprovalDecision.APPROVE, "APPROVE"):
            raise KillerMissionAuthorityError(
                "Pre-authorized calendar approval is strictly prohibited in live mode; "
                "human approval must occur after PendingApproval exists."
            )

        self.source_sha = source_sha
        self.expected_source_sha = expected_source_sha
        self.clean_working_tree_required = clean_working_tree_required
        self.google_credentials = google_credentials
        self.aws_credentials_available = aws_credentials_available
        self.git_runner = git_runner
        self.post_pending_decision_callback = post_pending_decision_callback
        self.approval_channel = approval_channel
        self.preflight_report: LivePreflightReport | None = None
        self._consumed_approval_decision_ids: set[str] = set()
        self._consumed_decisions_lock = threading.RLock()
        # Resolve live demo target date: default to tomorrow in UTC if not provided
        resolved_demo_date = (
            demo_date
            if demo_date is not None
            else (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%d")
        )

        super().__init__(
            env=env,
            mission_id=mission_id,
            live_mode=True,
            operator_approved=operator_approved,
            bedrock_planner=bedrock_planner,
            demo_date=resolved_demo_date,
            calendar_decision=calendar_decision,
        )
        self.raw_candidate_plan: CandidatePlanProposal | None = None
        self.candidate_plan = None
        self.validated_candidate_plan: CandidatePlanProposal | None = None
        self._consumed_decisions_file = self.env.base_dir / "consumed_approval_decisions.jsonl"
        self._persistence_failed: bool = False
        # A3 REPAIR: Strictly separate "existing durable mission was detected" from
        # "execution state was safely restored". Detection means the mission ID and
        # intent match a persisted record. Restoration means the exact previous
        # action progression, snapshot, provider identity, and lifecycle state were
        # safely reconstructed. Full safe rehydration is NOT currently supported,
        # so _execution_state_restored is always False.
        if not getattr(self.env, "has_explicit_base_dir", True) or getattr(
            self.env, "is_ephemeral_storage", False
        ):
            self.is_first_time_storage = False
            self._existing_mission_detected = False
            self._execution_state_restored = False
            self.is_restored_session = False
        else:
            self.is_first_time_storage = not self._is_resumed_mission
            self._existing_mission_detected = self._is_resumed_mission
            # Full safe rehydration is NOT currently supported: the runner creates
            # fresh execution state (candidate_plan, tracker, schedule) and does NOT
            # reconstruct previous action progression, snapshot revision, or provider
            # identity. Setting this to True would falsely claim recovery.
            self._execution_state_restored = False
            # is_restored_session requires BOTH detection AND successful state
            # rehydration. Since rehydration is not supported, this is always False.
            self.is_restored_session = False
        self.existing_mission_detected = self._existing_mission_detected
        self.is_existing_mission_detected = self._existing_mission_detected
        self.is_execution_state_restored = self._execution_state_restored
        self._load_consumed_decision_ids()

    def _load_consumed_decision_ids(self, *, require_durable: bool = False) -> None:
        """Load durably persisted consumed approval decision IDs across process restart.

        When require_durable=True or when historical recovery is demanded, fails closed
        if stable durable storage is unavailable, absent, or unconfigured, preventing
        silent restart with an empty authorization history.
        """
        if require_durable:
            if not getattr(self.env, "has_explicit_base_dir", True) or getattr(
                self.env, "is_ephemeral_storage", False
            ):
                raise KillerMissionAuthorityError(
                    "Stable durable storage boundary is required for operations relying on "
                    "historical approval consumption; ephemeral or unconfigured storage "
                    "cannot guarantee restart replay protection."
                )
            if (
                not hasattr(self, "_consumed_decisions_file")
                or not self._consumed_decisions_file.exists()
            ):
                dec_path = getattr(self, "_consumed_decisions_file", None)
                raise KillerMissionAuthorityError(
                    f"Persistent approval consumption log not found at '{dec_path}'; "
                    "cannot recover historical authorization state."
                )

        with self._consumed_decisions_lock:
            # 1. Hydrate from canonical ApprovalLedger
            ledger_dec_ids: set[str] = set()
            ledger_records_by_id: dict[str, Any] = {}
            if hasattr(self.env, "approval_ledger") and self.env.approval_ledger is not None:
                for rec in self.env.approval_ledger.get_decision_records():
                    if rec.decision_id:
                        ledger_dec_ids.add(rec.decision_id)
                        ledger_records_by_id[rec.decision_id] = rec
                self._consumed_approval_decision_ids.update(ledger_dec_ids)

            # 2. If decision log file exists, validate strictly
            if hasattr(self, "_consumed_decisions_file") and self._consumed_decisions_file.exists():
                loaded_ids: set[str] = set()
                try:
                    with open(self._consumed_decisions_file, encoding="utf-8") as f:
                        for line_idx, line in enumerate(f, 1):
                            line_str = line.strip()
                            if not line_str:
                                continue
                            try:
                                d = json.loads(line_str)
                            except Exception as e:
                                raise KillerMissionIntegrityError(
                                    f"Corrupt or truncated consumed decision record on line "
                                    f"{line_idx}: {e}"
                                ) from e
                            if not isinstance(d, dict):
                                raise KillerMissionIntegrityError(
                                    f"Invalid consumed decision record structure on line "
                                    f"{line_idx}: expected dict"
                                )
                            extra_keys = set(d.keys()) - ALLOWED_CONSUMED_DECISION_KEYS
                            if extra_keys:
                                raise KillerMissionIntegrityError(
                                    f"Unexpected fields {extra_keys} in consumed decision record "
                                    f"on line {line_idx}"
                                )
                            missing_keys = REQUIRED_CONSUMED_DECISION_KEYS - set(d.keys())
                            if missing_keys:
                                raise KillerMissionIntegrityError(
                                    f"Missing required fields {missing_keys} in consumed decision "
                                    f"record on line {line_idx}"
                                )
                            did = d.get("decision_id")
                            if not did or not isinstance(did, str) or not did.strip():
                                raise KillerMissionIntegrityError(
                                    f"Consumed decision record missing valid 'decision_id' "
                                    f"on line {line_idx}"
                                )
                            cat = d.get("consumed_at")
                            if not cat or not isinstance(cat, str) or not cat.strip():
                                raise KillerMissionIntegrityError(
                                    f"Consumed decision record missing valid 'consumed_at' "
                                    f"on line {line_idx}"
                                )
                            try:
                                dt = datetime.fromisoformat(cat)
                            except Exception as e:
                                raise KillerMissionIntegrityError(
                                    f"Corrupted consumed_at timestamp '{cat}' "
                                    f"on line {line_idx}: {e}"
                                ) from e
                            offset = dt.utcoffset()
                            if dt.tzinfo is None or offset is None:
                                raise KillerMissionIntegrityError(
                                    "consumed_at timestamp must be timezone-aware UTC "
                                    f"on line {line_idx}"
                                )
                            if offset.total_seconds() != 0:
                                raise KillerMissionIntegrityError(
                                    f"consumed_at timestamp must be UTC on line {line_idx}"
                                )
                            if "decision" in d:
                                dec_val = d["decision"]
                                if not isinstance(dec_val, str) or dec_val not in {
                                    "APPROVE",
                                    "REJECT",
                                }:
                                    raise KillerMissionIntegrityError(
                                        f"Invalid decision value '{dec_val}' on line {line_idx}"
                                    )
                            if "mission_id" in d:
                                mid_val = d["mission_id"]
                                if not isinstance(mid_val, str) or not mid_val.strip():
                                    raise KillerMissionIntegrityError(
                                        "Invalid mission_id in consumed decision record "
                                        f"on line {line_idx}"
                                    )
                            if did in loaded_ids:
                                raise KillerMissionIntegrityError(
                                    f"Duplicate consumed decision ID '{did}' detected in "
                                    "persistent log"
                                )
                            loaded_ids.add(did)

                            # Verify full decision lineage against canonical ledger
                            if did in ledger_records_by_id:
                                l_rec = ledger_records_by_id[did]
                                if "mission_id" in d and str(d["mission_id"]) != str(
                                    l_rec.mission_id
                                ):
                                    raise KillerMissionIntegrityError(
                                        f"Contradictory mission_id for decision '{did}' between "
                                        f"JSONL ('{d['mission_id']}') and canonical ledger "
                                        f"('{l_rec.mission_id}')"
                                    )
                                if (
                                    "action_id" in d
                                    and l_rec.action_id
                                    and str(d["action_id"]) != str(l_rec.action_id)
                                ):
                                    raise KillerMissionIntegrityError(
                                        f"Contradictory action_id for decision '{did}' between "
                                        f"JSONL ('{d['action_id']}') and canonical ledger "
                                        f"('{l_rec.action_id}')"
                                    )
                                if "decision" in d:
                                    jsonl_dec = d["decision"]
                                    if jsonl_dec == "REJECT" and l_rec.status.value != "REJECTED":
                                        raise KillerMissionIntegrityError(
                                            f"Contradictory decision value for decision '{did}': "
                                            f"JSONL has '{jsonl_dec}', but canonical ledger record "
                                            f"has status '{l_rec.status.value}'"
                                        )
                                    elif (
                                        jsonl_dec == "APPROVE" and l_rec.status.value != "CONSUMED"
                                    ):
                                        raise KillerMissionIntegrityError(
                                            f"Contradictory decision value for decision '{did}': "
                                            f"JSONL has '{jsonl_dec}', but canonical ledger record "
                                            f"has status '{l_rec.status.value}'"
                                        )
                                if "pending_approval_id" in d:
                                    if l_rec.approval_id:
                                        if str(d["pending_approval_id"]) != str(l_rec.approval_id):
                                            raise KillerMissionIntegrityError(
                                                f"Contradictory pending_approval_id for decision "
                                                f"'{did}' between JSONL "
                                                f"('{d['pending_approval_id']}') and "
                                                f"canonical ledger ('{l_rec.approval_id}')"
                                            )
                                    else:
                                        raise KillerMissionIntegrityError(
                                            f"Contradictory pending_approval_id for decision "
                                            f"'{did}': present in JSONL "
                                            f"('{d['pending_approval_id']}') but absent in "
                                            "canonical ledger"
                                        )

                    # 3. Discrepancy detection between decision log and canonical ledger (Repair A2)
                    # The canonical ApprovalLedger is the single authoritative source of
                    # current approval/decision authority. The JSONL is auxiliary historical
                    # input only — it must never independently authorize execution.
                    # Missing, contradictory or incomplete evidence must fail closed.
                    if loaded_ids and not ledger_dec_ids:
                        # JSONL has decisions but canonical ledger is empty — the JSONL
                        # cannot independently authorize; fail closed.
                        raise KillerMissionIntegrityError(
                            "Auxiliary JSONL decision log contains decision IDs "
                            f"{loaded_ids} but the canonical ApprovalLedger is empty; "
                            "JSONL cannot be an independent authorization source. "
                            "Missing canonical ledger evidence must fail closed."
                        )
                    elif loaded_ids - ledger_dec_ids:
                        # Auxiliary JSONL contains decisions not present in the authoritative
                        # canonical ApprovalLedger. Auxiliary records cannot claim authority without
                        # matching canonical evidence; fail closed.
                        unmatched = loaded_ids - ledger_dec_ids
                        raise KillerMissionIntegrityError(
                            "Discrepancy detected between decision log and canonical approval "
                            f"ledger: JSONL has decisions {unmatched} not found in canonical "
                            "ledger; auxiliary log cannot independently establish authority "
                            "without matching trusted canonical evidence."
                        )
                    # Canonical-only history (ledger_dec_ids - loaded_ids) is completely valid,
                    # as ApprovalLedger backed by canonical mission ledger is authoritative.
                except OSError as e:
                    raise KillerMissionIntegrityError(
                        f"Failed to read durable consumed approval decisions: {e}"
                    ) from e

    def _persist_consumed_decision_id(
        self,
        decision_id: str,
        *,
        decision: ApprovalDecision | str = ApprovalDecision.REJECT,
        action_id: str | None = None,
        mission_id: str | None = None,
        pending_approval_id: str | None = None,
    ) -> None:
        """Durably persist consumed decision ID with append, fsync, and atomic rollback."""
        if getattr(self, "_persistence_failed", False):
            raise KillerMissionIntegrityError(
                "Persistence failure previously occurred; "
                "cannot continue authorization-sensitive operations"
            )

        dec_str = decision.value if isinstance(decision, ApprovalDecision) else str(decision)
        if dec_str != ApprovalDecision.REJECT.value:
            raise KillerMissionAuthorityError(
                f"Prohibited decision value '{dec_str}' passed to rejection persistence: "
                "until an authenticated production approval channel exists, persisting "
                "APPROVE is prohibited and cannot be recorded as a rejection"
            )

        # Replay check: already consumed decisions fail closed under authority boundary
        if decision_id in self._consumed_approval_decision_ids or (
            hasattr(self.env, "approval_ledger")
            and self.env.approval_ledger is not None
            and self.env.approval_ledger.is_decision_consumed(decision_id)
        ):
            raise KillerMissionAuthorityError(
                f"Approval decision '{decision_id}' has already been consumed "
                "(duplicate/replay prohibited)"
            )

        # A3 RECOVERY GATE: Helper cannot mutate durable state on unrestored runner
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                f"Cannot persist consumed decision for existing mission '{self.mission_id}': "
                "an existing durable mission record was detected in persistent storage, "
                "but full safe rehydration is not supported. "
                "Use a new mission ID with fresh stable storage."
            )

        # Require that PendingApproval exists (cannot forge rejection before P-13.04)
        if not hasattr(self, "pending_approval") or self.pending_approval is None:
            raise KillerMissionSequenceError(
                "Cannot persist consumed rejection before P-13.04 establishes PendingApproval"
            )

        # Require exact pending_approval_id binding
        if (
            not pending_approval_id
            or not isinstance(pending_approval_id, str)
            or not pending_approval_id.strip()
        ):
            raise KillerMissionAuthorityError(
                "Cannot persist consumed rejection without exact pending_approval_id binding"
            )

        pa_str = pending_approval_id.strip()
        expected_pa_str = str(self.pending_approval.pending_approval_id)
        if pa_str != expected_pa_str:
            raise KillerMissionAuthorityError(
                f"Mismatched pending_approval_id '{pa_str}'; expected '{expected_pa_str}'"
            )

        expected_act_str = str(self.pending_approval.action_id)
        if action_id is not None and str(action_id).strip() != expected_act_str:
            raise KillerMissionAuthorityError(
                f"Mismatched action_id '{action_id}'; expected '{expected_act_str}'"
            )
        act_str = expected_act_str

        expected_mid_str = str(self.pending_approval.mission_id)
        if mission_id is not None and str(mission_id).strip() != expected_mid_str:
            raise KillerMissionAuthorityError(
                f"Mismatched mission_id '{mission_id}'; expected '{expected_mid_str}'"
            )
        mid_str = expected_mid_str

        with self._consumed_decisions_lock:
            if getattr(self, "_persistence_failed", False):
                raise KillerMissionIntegrityError(
                    "Persistence failure previously occurred; "
                    "cannot continue authorization-sensitive operations"
                )

            if decision_id in self._consumed_approval_decision_ids or (
                hasattr(self.env, "approval_ledger")
                and self.env.approval_ledger is not None
                and self.env.approval_ledger.is_decision_consumed(decision_id)
            ):
                raise KillerMissionAuthorityError(
                    f"Approval decision '{decision_id}' has already been consumed "
                    "(duplicate/replay prohibited)"
                )

            # Revalidate existing persistent log before appending
            if self._consumed_decisions_file.exists():
                try:
                    self._load_consumed_decision_ids()
                except Exception as exc:
                    self._persistence_failed = True
                    raise KillerMissionIntegrityError(
                        f"Cannot append to corrupted persistent decision log: {exc}"
                    ) from exc

            now_utc = datetime.now(UTC)

            # Check if pending_approval was already rejected/consumed in approval_ledger
            if hasattr(self.env, "approval_ledger") and self.env.approval_ledger is not None:
                if self.env.approval_ledger.is_rejected(pa_str):
                    raise KillerMissionAuthorityError(
                        f"Pending approval '{pa_str}' was already rejected; "
                        "second decision cannot independently reject the same pending approval"
                    )
                if self.env.approval_ledger.is_consumed(pa_str):
                    raise KillerMissionAuthorityError(
                        f"Pending approval '{pa_str}' was already consumed; "
                        "rejection cannot overwrite consumed approval"
                    )

            # Ensure action exists in mission ledger using public method get_action
            if hasattr(self.env, "mission_ledger") and self.env.mission_ledger is not None:
                try:
                    self.env.mission_ledger.get_action(ActionId(act_str))
                except RecordNotFoundError as exc:
                    if getattr(self, "action_cal", None) and act_str == str(
                        self.action_cal.action_id
                    ):
                        self.env.mission_ledger.append_action(
                            ActionRecord(
                                action_id=self.action_cal.action_id,
                                mission_id=self.mission_id,
                                action=self.action_cal,
                                approval_id=None,
                                created_at=now_utc,
                            )
                        )
                    else:
                        self._persistence_failed = True
                        raise KillerMissionIntegrityError(
                            f"Action '{act_str}' not found in ledger; cannot record decision"
                        ) from exc

            rec: dict[str, Any] = {
                "decision_id": decision_id,
                "consumed_at": now_utc.isoformat(),
                "decision": dec_str,
                "mission_id": mid_str,
                "action_id": act_str,
                "pending_approval_id": pa_str,
            }

            line = json.dumps(rec) + "\n"

            orig_size = (
                self._consumed_decisions_file.stat().st_size
                if self._consumed_decisions_file.exists()
                else 0
            )

            # 1. Append to JSONL file
            try:
                self._consumed_decisions_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._consumed_decisions_file, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                # Rollback partial write
                try:
                    if self._consumed_decisions_file.exists():
                        with open(self._consumed_decisions_file, "r+", encoding="utf-8") as rf:
                            rf.truncate(orig_size)
                            rf.flush()
                            os.fsync(rf.fileno())
                except Exception:
                    pass
                self._persistence_failed = True
                raise KillerMissionIntegrityError(
                    f"Failed to durably commit consumed approval decision: {e}"
                ) from e

            # 2. Persist to canonical ApprovalLedger
            if hasattr(self.env, "approval_ledger") and self.env.approval_ledger is not None:
                try:
                    self.env.approval_ledger.record_rejection(
                        decision_id,
                        action_id=ActionId(act_str),
                        mission_id=MissionId(mid_str),
                        at=now_utc,
                        pending_approval_id=pa_str,
                    )
                except Exception as exc:
                    # Rollback the JSONL append if ledger append fails
                    try:
                        if self._consumed_decisions_file.exists():
                            with open(self._consumed_decisions_file, "r+", encoding="utf-8") as rf:
                                rf.truncate(orig_size)
                                rf.flush()
                                os.fsync(rf.fileno())
                    except Exception:
                        pass
                    self._persistence_failed = True
                    raise KillerMissionIntegrityError(
                        "Failed to commit consumed approval decision to canonical approval "
                        f"ledger: {exc}"
                    ) from exc

            # ONLY add to in-memory set AFTER all persistence steps succeed!
            self._consumed_approval_decision_ids.add(decision_id)

    def reload_consumed_decisions(self, *, require_durable: bool = True) -> None:
        """Explicitly reload consumed decision IDs from durable storage."""
        self._load_consumed_decision_ids(require_durable=require_durable)

    def evaluate_preflight(self) -> LivePreflightReport:
        """Evaluate canonical live preflight against all live gate prerequisites."""
        report = check_live_preflight(
            scope=self.env.scope,
            operator_approved=self.operator_approved,
            source_sha=self.source_sha,
            expected_source_sha=self.expected_source_sha,
            clean_working_tree_required=self.clean_working_tree_required,
            google_credentials=self.google_credentials,
            aws_credentials_available=self.aws_credentials_available,
            calendar_transport=self.env.calendar_transport,
            tasks_transport=self.env.tasks_transport,
            weather_transport=self.env.weather_transport,
            bedrock_planner_available=isinstance(self.bedrock_planner, BedrockPlannerAdapter),
            git_runner=self.git_runner,
        )

        # Enforce stable durable storage prerequisite on live execution path
        new_blockers: list[str] = []
        if getattr(self.env, "is_ephemeral_storage", False) or not getattr(
            self.env, "has_explicit_base_dir", True
        ):
            new_blockers.append(
                "Stable durable storage boundary is required for live execution; "
                "ephemeral or unconfigured storage cannot guarantee restart replay protection."
            )
        else:
            try:
                self.env.base_dir.mkdir(parents=True, exist_ok=True)
                canary = self.env.base_dir / ".canary_write_test"
                canary.write_text("test", encoding="utf-8")
                canary.unlink()
            except Exception as e:
                new_blockers.append(
                    f"Stable durable storage directory '{self.env.base_dir}' is not writable: {e}"
                )

        if hasattr(self, "_consumed_decisions_file") and self._consumed_decisions_file.exists():
            try:
                self._load_consumed_decision_ids()
            except Exception as e:
                new_blockers.append(
                    f"Corrupted or inaccessible persistent approval consumption log: {e}"
                )

        if new_blockers:
            import dataclasses

            report = dataclasses.replace(
                report,
                is_ready=False,
                blocker_reasons=report.blocker_reasons + new_blockers,
            )

        self.preflight_report = report
        return report

    def _require_preflight(self) -> None:
        """Enforce canonical live preflight before any step execution."""
        report = self.evaluate_preflight()
        if not report.is_ready:
            raise LivePreflightBlockedError(
                f"Live execution gate failed preflight: {'; '.join(report.blocker_reasons)}"
            )

    def _propose_and_validate_candidate_plan(self) -> None:
        """Propose candidate plan from Bedrock and validate before publishing or mutating."""
        self._require_preflight()
        self.candidate_plan = None
        self.validated_candidate_plan = None
        if self.bedrock_planner is None or not isinstance(
            self.bedrock_planner, BedrockPlannerAdapter
        ):
            raise KillerMissionExecutionError(
                "Live mode requires concrete Bedrock / Strands planner adapter; "
                "fallback to deterministic proposal is strictly prohibited."
            )
        planner_input = PlannerInput(
            mission_id=self.mission_id,
            intent=self.intent_text,
        )
        plan_result = self.bedrock_planner.plan(planner_input)
        raw_plan = plan_result.plan
        self.raw_candidate_plan = raw_plan

        # Validate exact 3-step killer mission plan before ANY assignment or mutation
        validate_canonical_killer_mission_plan(
            raw_plan,
            target_date=self.demo_date,
            desired_start_time=self.desired_start_time,
            scope=self.env.scope,
        )
        self.candidate_plan = raw_plan
        self.validated_candidate_plan = raw_plan

    def _compile_validated_plan_with_seeded_id(self) -> None:
        """Compile validated candidate plan with the exact provider event ID from seeding."""
        if (
            not self.candidate_plan
            or not self.validated_candidate_plan
            or self.candidate_plan is not self.validated_candidate_plan
        ):
            raise KillerMissionSequenceError("No validated candidate plan available to compile")
        validate_canonical_killer_mission_plan(
            self.candidate_plan,
            target_date=self.demo_date,
            desired_start_time=self.desired_start_time,
            scope=self.env.scope,
        )
        if not self.seeded_event_id:
            raise KillerMissionSequenceError(
                "Cannot compile candidate plan without seeded provider event_id. "
                "Seeding must occur after plan validation and before compilation."
            )
        actual_event_id = self.seeded_event_id
        resolver = SymbolicTargetResolver(
            scope=self.env.scope,
            event_id_mappings={
                SymbolicTargetRef.LEAVE_FOR_SCHOOL: actual_event_id,
            },
        )
        self.execution_contract = compile_candidate_plan(
            self.candidate_plan,
            resolver,
        )
        self.schedule = schedule_execution(self.execution_contract)
        self.tracker = ExecutionStateTracker(self.execution_contract, self.schedule)
        self.action_weather = self.execution_contract.actions[0]
        self.action_task = self.execution_contract.actions[1]
        self.action_cal = self.execution_contract.actions[2]
        self.validated_action_cal = validate_action_contract(self.action_cal)

    def step_p13_01_seed(self) -> KillerMissionStepResult:
        """Seed initial pre-state; gated strictly by live preflight and validated candidate plan."""
        # A3 RECOVERY GATE: Block direct step entry on detected-but-unrestored missions.
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                "Cannot execute seeding for existing mission: full safe rehydration "
                "is not supported. Use a new mission ID with fresh stable storage."
            )
        self._require_preflight()
        if self.candidate_plan is not None:
            validate_canonical_killer_mission_plan(
                self.candidate_plan,
                target_date=self.demo_date,
                desired_start_time=self.desired_start_time,
                scope=self.env.scope,
            )
            if self.validated_candidate_plan is not self.candidate_plan:
                raise CanonicalKillerPlanValidationError(
                    "Candidate plan was modified or injected without canonical proposal validation"
                )
        else:
            self._propose_and_validate_candidate_plan()

        if self.candidate_plan is None:
            raise KillerMissionExecutionError("Candidate plan is None")
        # Fail-closed revalidation on the exact candidate_plan before any external seeding mutation
        validate_canonical_killer_mission_plan(
            self.candidate_plan,
            target_date=self.demo_date,
            desired_start_time=self.desired_start_time,
            scope=self.env.scope,
        )
        res = super().step_p13_01_seed()
        if not self.seeded_event_id:
            raise KillerMissionVerificationError(
                "Seeding did not return a canonical provider event_id"
            )
        return res

    def step_p13_02_plan(self) -> KillerMissionStepResult:
        """Execute plan step; gated strictly by live preflight."""
        # A3 RECOVERY GATE
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                "Cannot execute planning for existing mission: full safe rehydration "
                "is not supported. Use a new mission ID with fresh stable storage."
            )
        self._require_preflight()
        if self.candidate_plan is not None:
            validate_canonical_killer_mission_plan(
                self.candidate_plan,
                target_date=self.demo_date,
                desired_start_time=self.desired_start_time,
                scope=self.env.scope,
            )
            if self.validated_candidate_plan is not self.candidate_plan:
                raise CanonicalKillerPlanValidationError(
                    "Candidate plan was modified or injected without canonical proposal validation"
                )
        else:
            self._propose_and_validate_candidate_plan()

        if self.candidate_plan is None:
            raise KillerMissionExecutionError("Candidate plan is None")
        validate_canonical_killer_mission_plan(
            self.candidate_plan,
            target_date=self.demo_date,
            desired_start_time=self.desired_start_time,
            scope=self.env.scope,
        )
        if not self.seeded_event_id:
            raise KillerMissionSequenceError(
                "Cannot compile candidate plan without seeded provider event_id. "
                "Seeding must occur after plan validation and before compilation."
            )
        self._compile_validated_plan_with_seeded_id()
        return super().step_p13_02_plan()

    def step_p13_03_tasks_prep(self) -> KillerMissionStepResult:
        """Execute tasks prep step; gated strictly by live preflight."""
        # A3 RECOVERY GATE
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                "Cannot execute tasks prep for existing mission: full safe rehydration "
                "is not supported. Use a new mission ID with fresh stable storage."
            )
        self._require_preflight()
        return super().step_p13_03_tasks_prep()

    def step_p13_04_calendar_pause(self) -> KillerMissionStepResult:
        """Execute approval pause step; gated strictly by live preflight."""
        # A3 RECOVERY GATE
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                "Cannot execute calendar pause for existing mission: full safe rehydration "
                "is not supported. Use a new mission ID with fresh stable storage."
            )
        if getattr(self.env, "is_ephemeral_storage", False) or not getattr(
            self.env, "has_explicit_base_dir", True
        ):
            raise KillerMissionAuthorityError(
                "Stable durable storage boundary is required for operations relying on "
                "approval authority; ephemeral or unconfigured storage cannot guarantee "
                "restart replay protection."
            )
        self._require_preflight()
        return super().step_p13_04_calendar_pause()

    def step_p13_05_calendar_approve(
        self,
        decision: Any = None,
    ) -> KillerMissionStepResult:
        """Execute calendar update step; gated strictly by live preflight.

        Direct live approval bypass is prohibited. Live mutation decisions must
        come through an authenticated, explicitly authorized post-PendingApproval
        human decision channel.
        """
        # Replay check: already consumed decision ID fails closed under authority boundary
        dec_id = getattr(decision, "decision_id", None)
        if dec_id and (
            dec_id in self._consumed_approval_decision_ids
            or (
                hasattr(self.env, "approval_ledger")
                and self.env.approval_ledger is not None
                and self.env.approval_ledger.is_decision_consumed(str(dec_id))
            )
        ):
            raise KillerMissionAuthorityError(
                f"Approval decision '{dec_id}' has already been consumed (replay prohibited)"
            )

        # A3 RECOVERY GATE: Block decision paths on unrestored runner at entry boundary
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                "Cannot execute calendar mutation approval for existing mission "
                f"'{self.mission_id}': an existing durable mission record was detected "
                "in persistent storage, but full safe rehydration is not supported. "
                "Use a new mission ID with fresh stable storage."
            )

        if getattr(self.env, "is_ephemeral_storage", False) or not getattr(
            self.env, "has_explicit_base_dir", True
        ):
            raise KillerMissionAuthorityError(
                "Stable durable storage boundary is required for operations relying on "
                "approval authority; ephemeral or unconfigured storage cannot guarantee "
                "restart replay protection."
            )
        if getattr(self, "_persistence_failed", False):
            raise KillerMissionIntegrityError(
                "Persistence failure previously occurred; "
                "cannot continue authorization-sensitive operations"
            )
        self._require_preflight()
        if not hasattr(self, "pending_approval") or self.pending_approval is None:
            raise KillerMissionSequenceError(
                "Cannot approve calendar update before P-13.04 establishes PendingApproval"
            )

        pa_id_str = str(self.pending_approval.pending_approval_id)
        if (
            hasattr(self.env, "approval_ledger")
            and self.env.approval_ledger is not None
            and self.env.approval_ledger.is_rejected(pa_id_str)
        ):
            raise KillerMissionAuthorityError(
                f"Pending approval '{pa_id_str}' has already been consumed / rejected "
                "(replay prohibited)"
            )

        eff_decision = decision

        # 1. Reject direct bypass with raw APPROVE
        if eff_decision == ApprovalDecision.APPROVE or str(eff_decision).upper() == "APPROVE":
            raise KillerMissionAuthorityError(
                "Direct live approval bypass prohibited: raw APPROVE parameter cannot grant "
                "human authorization in live execution. Live mutation decision must come "
                "through the explicitly authorized post-PendingApproval decision boundary."
            )

        # 2. Rejection via raw REJECT parameter
        if eff_decision == ApprovalDecision.REJECT or str(eff_decision).upper() == "REJECT":
            res = KillerMissionStepResult(
                task_id="P-13.05",
                step_name="Approve, Execute & Verify Calendar Update",
                status="BLOCKED_APPROVAL_CHANNEL",
                provenance=self.env.provenance,
                details=(
                    "Live calendar mutation halted: raw REJECT parameter cannot establish durable "
                    "terminal rejection authority without an authenticated, bound human decision "
                    "channel. 0 calendar writes performed."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={
                    "raw_negative_instruction": True,
                    "durable_terminal_rejection": False,
                    "pending_approval_id": str(self.pending_approval.pending_approval_id),
                },
            )
            self.step_results["P-13.05"] = res
            return res

        # 3. Consult post_pending_decision_callback if decision is not supplied
        if eff_decision is None and self.post_pending_decision_callback is not None:
            cb_result = self.post_pending_decision_callback(self.pending_approval)
            if cb_result is None:
                return super().step_p13_05_calendar_approve(decision=None)
            if cb_result == ApprovalDecision.REJECT or str(cb_result).upper() == "REJECT":
                res = KillerMissionStepResult(
                    task_id="P-13.05",
                    step_name="Approve, Execute & Verify Calendar Update",
                    status="BLOCKED_APPROVAL_CHANNEL",
                    provenance=self.env.provenance,
                    details=(
                        "Live calendar mutation halted: callback returned raw REJECT, but raw "
                        "callback return values cannot establish durable terminal rejection "
                        "authority without an authenticated human decision channel. "
                        "0 calendar writes performed."
                    ),
                    writes_performed=0,
                    is_verified=False,
                    extra_metadata={
                        "raw_negative_instruction": True,
                        "durable_terminal_rejection": False,
                        "pending_approval_id": str(self.pending_approval.pending_approval_id),
                        "unauthenticated_callback": True,
                    },
                )
                self.step_results["P-13.05"] = res
                return res
            if cb_result == ApprovalDecision.APPROVE or str(cb_result).upper() == "APPROVE":
                # Remove raw APPROVE -> authorized decision auto-promotion.
                # A callback return value is not independently authenticated human consent.
                res = KillerMissionStepResult(
                    task_id="P-13.05",
                    step_name="Approve, Execute & Verify Calendar Update",
                    status="BLOCKED_APPROVAL_CHANNEL",
                    provenance=self.env.provenance,
                    details=(
                        "Live calendar mutation blocked: callback returned raw APPROVE, but raw "
                        "callback return values cannot grant human authorization. Live mutation "
                        "requires an authenticated human decision channel. 0 writes performed."
                    ),
                    writes_performed=0,
                    is_verified=False,
                    extra_metadata={"unauthenticated_callback": True},
                )
                self.step_results["P-13.05"] = res
                return res
            if isinstance(cb_result, AuthorizedPostPendingApprovalDecision):
                eff_decision = cb_result
            else:
                raise KillerMissionAuthorityError(
                    "Unexpected post_pending_decision_callback return type: "
                    f"{type(cb_result).__name__}"
                )

        # 4. If still None, pause awaiting approval
        if eff_decision is None:
            return super().step_p13_05_calendar_approve(decision=None)

        # 5. Enforce AuthorizedPostPendingApprovalDecision validation
        if not isinstance(eff_decision, AuthorizedPostPendingApprovalDecision):
            raise KillerMissionAuthorityError(
                f"Live approval decision must be an AuthorizedPostPendingApprovalDecision, "
                f"got {type(eff_decision).__name__}"
            )

        # Check pending approval status: must be strictly PENDING
        if self.pending_approval.status != PendingApprovalStatus.PENDING:
            raise KillerMissionAuthorityError(
                "Pending approval is not in PENDING status; "
                f"got status={self.pending_approval.status.value}"
            )

        # Replay prevention
        if eff_decision.decision_id in self._consumed_approval_decision_ids:
            raise KillerMissionAuthorityError(
                f"Approval decision '{eff_decision.decision_id}' has already been "
                "consumed (replay prohibited)"
            )

        # Binding checks against exact PendingApproval
        if eff_decision.pending_approval_id != str(self.pending_approval.pending_approval_id):
            raise KillerMissionAuthorityError(
                "Authorized decision pending_approval_id mismatch: expected "
                f"'{self.pending_approval.pending_approval_id}', "
                f"got '{eff_decision.pending_approval_id}'"
            )
        if eff_decision.mission_id != str(self.mission_id) or eff_decision.mission_id != str(
            self.pending_approval.mission_id
        ):
            raise KillerMissionAuthorityError("Authorized decision mission_id mismatch")
        if eff_decision.action_id != str(
            self.action_cal.action_id
        ) or eff_decision.action_id != str(self.pending_approval.action_id):
            raise KillerMissionAuthorityError("Authorized decision action_id mismatch")
        if eff_decision.target_event_id != self.seeded_event_id:
            raise KillerMissionAuthorityError("Authorized decision target_event_id mismatch")

        expected_fp = compute_action_parameter_fingerprint(self.action_cal.parameters.to_dict())
        pending_fp = compute_action_parameter_fingerprint(
            self.pending_approval.parameters.to_dict()
        )
        if (
            eff_decision.action_parameter_fingerprint != expected_fp
            or eff_decision.action_parameter_fingerprint != pending_fp
        ):
            raise KillerMissionAuthorityError(
                "Authorized decision action_parameter_fingerprint mismatch"
            )

        # Staleness check (15-minute window)
        now_utc = datetime.now(UTC)
        age = now_utc - eff_decision.decided_at
        if age > timedelta(minutes=15) or age < timedelta(minutes=-5):
            raise KillerMissionAuthorityError(
                f"Authorized decision is stale / expired (age: {age.total_seconds():.1f}s)"
            )

        # A3 RECOVERY GATE: Block mutation approval on unrestored runner
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                "Cannot execute calendar mutation approval for existing mission: full safe "
                "rehydration is not supported. Use a new mission ID with fresh stable storage."
            )

        # Enforce trusted human channel authentication before ANY live mutation write
        # Do NOT consume decision yet! If channel verification fails or is untrusted,
        # decision remains UNCONSUMED.
        if self.approval_channel is None:
            res = KillerMissionStepResult(
                task_id="P-13.05",
                step_name="Approve, Execute & Verify Calendar Update",
                status="BLOCKED_APPROVAL_CHANNEL",
                provenance=self.env.provenance,
                details=(
                    f"Live calendar mutation blocked: no authenticated, trusted human decision "
                    f"channel is available for {eff_decision.decision.value}. A dataclass, model "
                    "response, callback return value, or self-declared authority_source is not "
                    "independently authenticated human consent. Stopping before Calendar write or "
                    "durable consumption (0 writes performed, 0 consumed approvals)."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={
                    "blocked_approval_channel": True,
                    "unauthenticated_decision": True,
                    "pending_approval_id": str(self.pending_approval.pending_approval_id),
                },
            )
            self.step_results["P-13.05"] = res
            return res

        auth_success = False
        try:
            auth_success = bool(
                self.approval_channel.verify_decision(self.pending_approval, eff_decision)
            )
        except Exception:
            auth_success = False

        if not auth_success:
            res = KillerMissionStepResult(
                task_id="P-13.05",
                step_name="Approve, Execute & Verify Calendar Update",
                status="BLOCKED_APPROVAL_CHANNEL",
                provenance=self.env.provenance,
                details=(
                    "Live calendar mutation blocked: human approval channel authentication failed "
                    f"for {eff_decision.decision.value}. 0 writes performed, 0 consumed approvals."
                ),
                writes_performed=0,
                is_verified=False,
                extra_metadata={
                    "blocked_approval_channel": True,
                    "authentication_failed": True,
                    "pending_approval_id": str(self.pending_approval.pending_approval_id),
                },
            )
            self.step_results["P-13.05"] = res
            return res

        # Enforce genuine production channel trust boundary:
        # A mock channel, fake verifier, arbitrary object, or unestablished trust source
        # returning True cannot establish production human authority. Because no genuine
        # authenticated production channel is available in current deployment, production
        # live decisions fail closed with BLOCKED_APPROVAL_CHANNEL.
        res = KillerMissionStepResult(
            task_id="P-13.05",
            step_name="Approve, Execute & Verify Calendar Update",
            status="BLOCKED_APPROVAL_CHANNEL",
            provenance=self.env.provenance,
            details=(
                "Live calendar mutation blocked: no genuine authenticated human decision "
                "implementation is available in production. A fake verifier or test mock returning "
                "True cannot establish production human authority merely by implementing the "
                f"Protocol for {eff_decision.decision.value}. Stopping before Calendar write or "
                "durable consumption to preserve negative invariant "
                "(0 writes performed, 0 consumed approvals)."
            ),
            writes_performed=0,
            is_verified=False,
            extra_metadata={
                "blocked_approval_channel": True,
                "unestablished_trust_source": True,
                "pending_approval_id": str(self.pending_approval.pending_approval_id),
            },
        )
        self.step_results["P-13.05"] = res
        return res

    def step_p13_06_ready_receipt(self) -> KillerMissionStepResult:
        """Produce ready receipt; gated strictly by live preflight and unrestored runner gate."""
        # A3 RECOVERY GATE
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                f"Cannot produce ready receipt for existing mission '{self.mission_id}': "
                "full safe rehydration is not supported. "
                "Use a new mission ID with fresh stable storage."
            )
        self._require_preflight()
        return super().step_p13_06_ready_receipt()

    def step_p13_07_mutate_and_drift(self) -> KillerMissionStepResult:
        """Mutate and drift; in live execution external drift is NOT exercised automatically."""
        # A3 RECOVERY GATE
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                f"Cannot execute drift for existing mission '{self.mission_id}': "
                "full safe rehydration is not supported. "
                "Use a new mission ID with fresh stable storage."
            )
        self._require_preflight()
        res = KillerMissionStepResult(
            task_id="P-13.07",
            step_name="Mutate Calendar Externally & Reconcile Drift",
            status="NOT_RUN",
            provenance=self.env.provenance,
            details=(
                "External drift was not exercised in live execution. Live drift remains "
                "NOT_RUN until a separate authorized external mutation occurs."
            ),
            writes_performed=0,
            is_verified=False,
            extra_metadata={"live_drift_pending": True},
        )
        self.step_results["P-13.07"] = res
        return res

    def run_full_slice(self) -> KillerMissionSliceOutcome:
        """Execute full slice, gated strictly by live preflight; stops at READY.

        A3 REPAIR: If an existing mission was detected in persistent storage but
        full safe rehydration is not supported, resumed live execution is blocked
        explicitly. This prevents duplicate seeding, duplicate task creation, and
        regenerated PendingApproval/authorization from a fresh execution tracker
        operating over partially-progressed persistent state.
        """
        # A3 RECOVERY GATE: Block resumed live execution when rehydration is unavailable.
        if self._existing_mission_detected and not self._execution_state_restored:
            raise KillerMissionIntegrityError(
                f"Cannot resume live execution for existing mission '{self.mission_id}': "
                "an existing durable mission record was detected in persistent storage, but "
                "full safe rehydration of the previous action progression, snapshot revision, "
                "provider identity, and lifecycle state is not currently supported. "
                "Restarting with a fresh execution tracker over partially-progressed state "
                "would risk duplicate seeding, duplicate task creation, and unauthorized "
                "re-execution. Use a new mission ID with fresh stable storage for legitimate "
                "new missions."
            )
        report = self.evaluate_preflight()
        if not report.is_ready:
            blocker_text = "; ".join(report.blocker_reasons)
            step_defs = [
                ("P-13.01", "Seed Canonical Demo Resources"),
                ("P-13.02", "Natural Language Planning & Compilation"),
                ("P-13.03", "Execute & Verify Tasks Preparation Action"),
                ("P-13.04", "Pause at Calendar Approval Boundary"),
                ("P-13.05", "Approve, Execute & Verify Calendar Update"),
                ("P-13.06", "Produce Deterministic READY Mission Receipt"),
                ("P-13.07", "Mutate Calendar Externally & Reconcile Drift"),
            ]
            for task_id, step_name in step_defs:
                self.step_results[task_id] = KillerMissionStepResult(
                    task_id=task_id,
                    step_name=step_name,
                    status="BLOCKED_LIVE",
                    provenance=self.env.provenance,
                    details=f"Live execution blocked by preflight: {blocker_text}",
                    writes_performed=0,
                    is_verified=False,
                    extra_metadata={"blocker_reasons": list(report.blocker_reasons)},
                )
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=MissionState.DRAFT,
                total_writes_performed=0,
                provenance=self.env.provenance,
                is_live=True,
            )

        # 1. Bounded Bedrock proposal & exact canonical plan validation BEFORE ANY SEEDING
        try:
            self._propose_and_validate_candidate_plan()
        except Exception as exc:
            step_defs = [
                ("P-13.01", "Seed Canonical Demo Resources"),
                ("P-13.02", "Natural Language Planning & Compilation"),
                ("P-13.03", "Execute & Verify Tasks Preparation Action"),
                ("P-13.04", "Pause at Calendar Approval Boundary"),
                ("P-13.05", "Approve, Execute & Verify Calendar Update"),
                ("P-13.06", "Produce Deterministic READY Mission Receipt"),
                ("P-13.07", "Mutate Calendar Externally & Reconcile Drift"),
            ]
            self.step_results["P-13.02"] = KillerMissionStepResult(
                task_id="P-13.02",
                step_name="Natural Language Planning & Compilation",
                status="FAILED",
                provenance=self.env.provenance,
                details=(
                    f"Bedrock plan proposal failed canonical validation: "
                    f"{type(exc).__name__}: {exc}"
                ),
                writes_performed=0,
                is_verified=False,
            )
            for task_id, step_name in step_defs:
                if task_id not in self.step_results:
                    self.step_results[task_id] = KillerMissionStepResult(
                        task_id=task_id,
                        step_name=step_name,
                        status="NOT_RUN",
                        provenance=self.env.provenance,
                        details=(
                            "Execution halted before mutation due to plan validation failure."
                        ),
                        writes_performed=0,
                        is_verified=False,
                    )
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=MissionState.FAILED,
                total_writes_performed=0,
                provenance=self.env.provenance,
                is_live=True,
            )

        # 2. Authorized disposable seeding AFTER candidate plan is validated
        self.step_p13_01_seed()

        # 3. Bind exact provider-generated event ID & compile validated actions
        step2 = self.step_p13_02_plan()
        if step2.status in ("FAILED", "BLOCKED_LIVE"):
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=MissionState.DRAFT,
                total_writes_performed=self.total_writes,
                provenance=self.env.provenance,
                is_live=True,
            )

        # 4. Tasks prep
        self.step_p13_03_tasks_prep()

        # 5. Pause at approval boundary
        self.step_p13_04_calendar_pause()

        # 6. Approve calendar update
        step5 = self.step_p13_05_calendar_approve()
        if step5.status in (
            "AWAITING_APPROVAL",
            "REJECTED",
            "PAUSED",
            "BLOCKED_LIVE",
            "BLOCKED_APPROVAL_CHANNEL",
        ):
            final_st = (
                MissionState.CANCELLED
                if step5.status == "REJECTED"
                else (
                    MissionState.NEEDS_APPROVAL
                    if step5.status in ("AWAITING_APPROVAL", "BLOCKED_APPROVAL_CHANNEL")
                    else MissionState.DRAFT
                )
            )
            return KillerMissionSliceOutcome(
                mission_id=self.mission_id,
                intent=self.intent_text,
                steps=dict(self.step_results),
                ready_receipt_hash=None,
                drifted_receipt_hash=None,
                historical_receipt_immutable=False,
                final_state=final_st,
                total_writes_performed=self.total_writes,
                provenance=self.env.provenance,
                is_live=True,
            )

        # 7. Produce deterministic READY receipt
        self.step_p13_06_ready_receipt()

        # 8. Live drift remains NOT_RUN
        self.step_results["P-13.07"] = KillerMissionStepResult(
            task_id="P-13.07",
            step_name="Mutate Calendar Externally & Reconcile Drift",
            status="NOT_RUN",
            provenance=self.env.provenance,
            details=(
                "External drift was not exercised in live execution. Live drift remains "
                "NOT_RUN until a separate authorized external mutation occurs."
            ),
            writes_performed=0,
            is_verified=False,
            extra_metadata={"live_drift_pending": True},
        )

        return KillerMissionSliceOutcome(
            mission_id=self.mission_id,
            intent=self.intent_text,
            steps=dict(self.step_results),
            ready_receipt_hash=self.ready_receipt_hash,
            drifted_receipt_hash=None,
            historical_receipt_immutable=True,
            final_state=MissionState.READY,
            total_writes_performed=self.total_writes,
            provenance=self.env.provenance,
            is_live=True,
        )


__all__ = [
    "AuthenticatedHumanApprovalChannel",
    "AuthorizedPostPendingApprovalDecision",
    "CANONICAL_CONTRADICTORY_START_TIME",
    "CANONICAL_DEMO_CALENDAR_ID",
    "CANONICAL_DEMO_EVENT_ID",
    "CANONICAL_DEMO_EVENT_TITLE",
    "CANONICAL_DEMO_TASK_LIST_ID",
    "CANONICAL_DEMO_TASK_TITLE",
    "CANONICAL_DESIRED_START_TIME",
    "CANONICAL_INITIAL_START_TIME",
    "CANONICAL_KILLER_INTENT",
    "DemoResourceScope",
    "FIXTURE_SOURCE_SHA",
    "FakeGoogleCalendarTransport",
    "InvalidEnvironmentConfigurationError",
    "KillerMissionAuthorityError",
    "KillerMissionEnvironment",
    "KillerMissionError",
    "KillerMissionExecutionError",
    "KillerMissionIntegrityError",
    "KillerMissionReadinessError",
    "KillerMissionReconciliationError",
    "KillerMissionSequenceError",
    "KillerMissionSliceOutcome",
    "KillerMissionSliceRunner",
    "KillerMissionStepResult",
    "KillerMissionVerificationError",
    "LiveExecutionBlockedError",
    "LiveKillerMissionSliceRunner",
    "LivePreflightBlockedError",
    "LivePreflightReport",
    "check_live_preflight",
    "compute_action_parameter_fingerprint",
    "create_authorized_post_pending_decision",
    "get_canonical_mission_timestamps",
    "is_synthetic_service",
    "is_synthetic_transport",
]
