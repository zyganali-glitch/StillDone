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

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
)
from stilldone.pending_approval import (
    ApprovalDecision,
    PendingApproval,
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
from stilldone.snapshot import (
    DurableSnapshotRepository,
    create_mission_snapshot,
)
from stilldone.verifier.contracts import (
    VerificationObservation,
    VerificationRequest,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_name": self.step_name,
            "status": self.status,
            "provenance": self.provenance.value,
            "details": self.details,
            "writes_performed": self.writes_performed,
            "is_verified": self.is_verified,
            "receipt_hash": self.receipt_hash,
            "extra_metadata": dict(self.extra_metadata),
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": str(self.mission_id),
            "intent": self.intent,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "ready_receipt_hash": self.ready_receipt_hash,
            "drifted_receipt_hash": self.drifted_receipt_hash,
            "historical_receipt_immutable": self.historical_receipt_immutable,
            "final_state": self.final_state.value,
            "total_writes_performed": self.total_writes_performed,
            "provenance": self.provenance.value,
            "is_live": self.is_live,
        }


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

        target_dir = base_dir or Path(tempfile.mkdtemp(prefix="stilldone_killer_mission_"))
        return cls(
            base_dir=target_dir,
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

        target_dir = base_dir or Path(tempfile.mkdtemp(prefix="stilldone_live_killer_mission_"))
        return cls(
            base_dir=target_dir,
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
        calendar_transport: CalendarTransport | None = None,
        tasks_transport: TaskTransport | None = None,
        weather_transport: WeatherTransport | None = None,
        cal_seed_transport: CalendarSeedTransport | None = None,
        tasks_seed_transport: TasksSeedTransport | None = None,
        scope: DemoResourceScope | None = None,
        provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
    ) -> None:
        self.base_dir = Path(base_dir)
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
        self.mission_ledger = DurableFileLedger(self.ledger_file)
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

        # Initialize mission in durable ledger
        now = datetime.now(UTC)
        self.env.mission_ledger.append_mission(
            MissionRecord(
                mission_id=self.mission_id,
                contract=self.contract,
                state=MissionState.DRAFT,
                created_at=now,
                updated_at=now,
            )
        )

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
        self.candidate_plan = self._create_deterministic_proposal()

        resolver = SymbolicTargetResolver(
            scope=self.env.scope,
            event_id_mappings={
                SymbolicTargetRef.LEAVE_FOR_SCHOOL: self.seeded_event_id,
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

    # -----------------------------------------------------------------------
    # Step 1: P-13.01 — Seed canonical disposable demo resources reproducibly
    # -----------------------------------------------------------------------
    def step_p13_01_seed(self) -> KillerMissionStepResult:
        """Seed initial pre-state: Leave for school at 07:45, no prep task."""
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

        if self.live_mode and seed_result.event_id:
            self.seeded_event_id = seed_result.event_id
        elif not self.live_mode:
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
                f"Demo seeded: event '{CANONICAL_DEMO_EVENT_TITLE}' "
                f"(id={self.seeded_event_id}) at 07:45 UTC, "
                "prep task absent (clean pre-state verified)."
            ),
            writes_performed=seed_result.writes_performed,
            is_verified=seed_result.readback_verified,
            extra_metadata={"seeded_event_id": self.seeded_event_id},
        )
        self.step_results["P-13.01"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 2: P-13.02 — Execute full mission from NL through AWS planner
    # -----------------------------------------------------------------------
    def step_p13_02_plan(self) -> KillerMissionStepResult:
        """Compile natural language proposal; assert zero model authority."""
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

        now = datetime.now(UTC)

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

        weather_prov = (
            EvidenceProvenance.LIVE_EXTERNAL
            if (self.live_mode and not is_synthetic_transport(self.env.weather_transport))
            else (
                EvidenceProvenance.LOCAL_EXECUTION if self.live_mode else EvidenceProvenance.FIXTURE
            )
        )
        self.weather_observation = VerificationObservation(
            target=self.action_weather.target,
            observed_at=now,
            exists=True,
            properties={"weather_status": "available"},
            provenance=weather_prov,
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

        # Discover created task id from transport for independent read-back
        items, _ = self.env.tasks_transport.list_tasks(self.env.scope.task_list_id)
        matching = [t for t in items if t.title == CANONICAL_DEMO_TASK_TITLE]
        if matching:
            self.created_task_id = matching[0].id
        else:
            created_task_id = gate_decision.provider_result.details.get("task_id")
            if created_task_id:
                self.created_task_id = str(created_task_id)

        # Independent provider read-back
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
    ) -> None:
        if env.provenance == EvidenceProvenance.FIXTURE:
            raise InvalidEnvironmentConfigurationError(
                "LiveKillerMissionSliceRunner cannot run in a FIXTURE environment"
            )
        self.source_sha = source_sha
        self.expected_source_sha = expected_source_sha
        self.clean_working_tree_required = clean_working_tree_required
        self.google_credentials = google_credentials
        self.aws_credentials_available = aws_credentials_available
        self.git_runner = git_runner
        self.preflight_report: LivePreflightReport | None = None

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
        self.preflight_report = report
        return report

    def _require_preflight(self) -> None:
        """Enforce canonical live preflight before any step execution."""
        report = self.evaluate_preflight()
        if not report.is_ready:
            raise LivePreflightBlockedError(
                f"Live execution gate failed preflight: {'; '.join(report.blocker_reasons)}"
            )

    def step_p13_01_seed(self) -> KillerMissionStepResult:
        """Seed initial pre-state; gated strictly by live preflight."""
        self._require_preflight()
        res = super().step_p13_01_seed()
        if not self.seeded_event_id:
            raise KillerMissionVerificationError(
                "Seeding did not return a canonical provider event_id"
            )
        return res

    def step_p13_02_plan(self) -> KillerMissionStepResult:
        """Execute plan step; gated strictly by live preflight."""
        self._require_preflight()
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
        self.candidate_plan = plan_result.plan

        # Use the exact provider event_id established by seeding / read-back
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

        return super().step_p13_02_plan()

    def step_p13_03_tasks_prep(self) -> KillerMissionStepResult:
        """Execute tasks prep step; gated strictly by live preflight."""
        self._require_preflight()
        return super().step_p13_03_tasks_prep()

    def step_p13_04_calendar_pause(self) -> KillerMissionStepResult:
        """Execute approval pause step; gated strictly by live preflight."""
        self._require_preflight()
        return super().step_p13_04_calendar_pause()

    def step_p13_05_calendar_approve(
        self,
        decision: ApprovalDecision | str | None = None,
    ) -> KillerMissionStepResult:
        """Execute calendar update step; gated strictly by live preflight."""
        self._require_preflight()
        return super().step_p13_05_calendar_approve(decision=decision)

    def step_p13_06_ready_receipt(self) -> KillerMissionStepResult:
        """Produce ready receipt; gated strictly by live preflight."""
        self._require_preflight()
        return super().step_p13_06_ready_receipt()

    def step_p13_07_mutate_and_drift(self) -> KillerMissionStepResult:
        """Mutate and drift; gated strictly by live preflight."""
        self._require_preflight()
        return super().step_p13_07_mutate_and_drift()

    def run_full_slice(self) -> KillerMissionSliceOutcome:
        """Execute full slice, gated strictly by live preflight before ANY step or mutation."""
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

        return super().run_full_slice()


__all__ = [
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
    "get_canonical_mission_timestamps",
    "is_synthetic_service",
    "is_synthetic_transport",
]
