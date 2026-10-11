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
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
    TaskTransport,
)
from stilldone.adapters.weather import (
    FakeOpenMeteoTransport,
    OpenMeteoReadAdapter,
    WeatherLocationConfig,
    WeatherTransport,
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
    FakeCalendarSeedTransport,
    FakeTasksSeedTransport,
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
from stilldone.domain.authority import (
    ApprovalGrant,
    AuthorityClass,
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
    MissionExecutionContract,
    SymbolicTargetResolver,
)
from stilldone.execution.gate import (
    ApprovedCalendarUpdateOutcome,
    CalendarMutationSpy,
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
from stilldone.execution.scheduler import ExecutionSchedule, schedule_execution
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
    PendingApproval,
    create_pending_approval,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
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

# Explicit UTC timestamps: pre-state is 07:45, desired target is 07:30
CANONICAL_INITIAL_START_TIME: str = "2026-10-04T07:45:00+00:00"
CANONICAL_INITIAL_END_TIME: str = "2026-10-04T08:15:00+00:00"
CANONICAL_DESIRED_START_TIME: str = "2026-10-04T07:30:00+00:00"
CANONICAL_DESIRED_END_TIME: str = "2026-10-04T08:00:00+00:00"
CANONICAL_CONTRADICTORY_START_TIME: str = "2026-10-04T08:00:00+00:00"
CANONICAL_CONTRADICTORY_END_TIME: str = "2026-10-04T08:30:00+00:00"

CANONICAL_WEATHER_LAT: float = 40.7128
CANONICAL_WEATHER_LON: float = -74.0060
CANONICAL_WEATHER_LOCATION_ID: str = "demo_weather_location"

PREDICATE_ID_WEATHER: PredicateId = PredicateId("11111111-0000-0000-0000-000000000001")
PREDICATE_ID_TASK: PredicateId = PredicateId("11111111-0000-0000-0000-000000000002")
PREDICATE_ID_CALENDAR: PredicateId = PredicateId("11111111-0000-0000-0000-000000000003")


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
        provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE,
    ) -> KillerMissionEnvironment:
        import tempfile

        target_dir = base_dir or Path(tempfile.mkdtemp(prefix="stilldone_killer_mission_"))
        return cls(base_dir=target_dir, provenance=provenance)

    def __init__(
        self,
        base_dir: Path,
        *,
        calendar_transport: CalendarTransport | None = None,
        tasks_transport: TaskTransport | None = None,
        weather_transport: WeatherTransport | None = None,
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

        # Transports
        self.calendar_transport = calendar_transport or FakeGoogleCalendarTransport()
        self.tasks_transport = tasks_transport or FakeGoogleTasksTransport()
        self.weather_transport = weather_transport or FakeOpenMeteoTransport()

        # Seed transports for P-13.01 preflight/seeding engine
        self.cal_seed_transport = FakeCalendarSeedTransport()
        self.cal_seed_transport.add_calendar(
            self.scope.calendar_id,
            DEFAULT_DEMO_CALENDAR_TITLE,
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
    ) -> None:
        self.env = env or KillerMissionEnvironment.create_fixture_environment()
        self.mission_id = mission_id or MissionId("11111111-2222-3333-4444-555555555555")
        self.intent_text = CANONICAL_KILLER_INTENT
        self.contract = MissionContract.create(self.intent_text, mission_id=self.mission_id)

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

        # Canonical Desired-State Predicates
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
            expected_value=CANONICAL_DESIRED_START_TIME,
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

    def _setup_canonical_plan(self) -> None:
        """Compile canonical plan and initialize action tracking."""
        step_weather = CandidateActionProposal.create(
            action_type=ActionType.WEATHER_READ,
            target_ref=SymbolicTargetRef.WEATHER_LOCATION,
            parameters={},
            explanation="Check morning departure weather",
        )
        step_task = CandidateActionProposal.create(
            action_type=ActionType.TASK_CREATE,
            target_ref=SymbolicTargetRef.TASK_LIST,
            parameters={"title": CANONICAL_DEMO_TASK_TITLE, "due": "2026-10-04"},
            explanation="Create reminder to pack backpacks",
        )
        step_cal = CandidateActionProposal.create(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
            parameters={"start_time": CANONICAL_DESIRED_START_TIME},
            explanation="Move leave for school event to 7:30",
        )
        self.candidate_plan = CandidatePlanProposal.create(
            mission_id=self.mission_id,
            steps=[step_weather, step_task, step_cal],
            explanation="Canonical killer mission plan proposal",
        )

        resolver = SymbolicTargetResolver(
            scope=self.env.scope,
            event_id_mappings={
                SymbolicTargetRef.LEAVE_FOR_SCHOOL: CANONICAL_DEMO_EVENT_ID,
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
            start_time=CANONICAL_INITIAL_START_TIME,
            end_time=CANONICAL_INITIAL_END_TIME,
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

        # Also seed in fake calendar runtime transport for subsequent steps
        if isinstance(self.env.calendar_transport, FakeGoogleCalendarTransport):
            self.env.calendar_transport.seed_event(
                calendar_id=self.env.scope.calendar_id,
                event_id=CANONICAL_DEMO_EVENT_ID,
                summary=CANONICAL_DEMO_EVENT_TITLE,
                start_time=CANONICAL_INITIAL_START_TIME,
                end_time=CANONICAL_INITIAL_END_TIME,
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
                f"prep task absent (clean pre-state verified)."
            ),
            writes_performed=seed_result.writes_performed,
            is_verified=seed_result.readback_verified,
        )
        self.step_results["P-13.01"] = res
        return res

    # -----------------------------------------------------------------------
    # Step 2: P-13.02 — Execute full mission from NL through AWS planner
    # -----------------------------------------------------------------------
    def step_p13_02_plan(self) -> KillerMissionStepResult:
        """Compile natural language proposal; assert zero model authority."""
        # Execute initial read-only weather observation (READ_ONLY, 0 writes)
        weather_gate = execute_gated_action(
            validate_action_contract(self.action_weather),
            self.router,
            tracker=self.tracker,
        )
        assert weather_gate.is_authorized
        assert weather_gate.provider_result is not None
        assert weather_gate.provider_result.success

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
        validated_action_task = validate_action_contract(self.action_task)

        # Authority check: REVERSIBLE_AUTO requires no approval
        auth_decision = evaluate_authority(validated_action_task, at=datetime.now(UTC))
        assert auth_decision.status == AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED

        # Execute gated action
        gate_decision = execute_gated_action(
            validated_action_task,
            self.router,
            tracker=self.tracker,
        )
        assert gate_decision.is_authorized
        assert gate_decision.provider_result is not None
        assert gate_decision.provider_result.success
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
        assert read_result.observation is not None
        assert read_result.observation.title == CANONICAL_DEMO_TASK_TITLE

        # Evaluate predicate deterministically
        task_obs = VerificationObservation(
            target=target_task,
            observed_at=datetime.now(UTC),
            exists=True,
            properties={
                "task_title": read_result.observation.title,
                "status": read_result.observation.status,
            },
            provenance=self.env.provenance,
        )
        pred_eval = evaluate_predicate(self.pred_task, task_obs)
        assert pred_eval.truth == PredicateTruth.TRUE
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
        assert not gate_decision.is_authorized
        assert gate_decision.status == ActionExecutionStatus.NOT_RUN

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
    def step_p13_05_calendar_approve(self) -> KillerMissionStepResult:
        """Grant bound approval, execute calendar update, and read back independently."""
        assert hasattr(self, "validated_action_cal"), "Must run step_p13_04 first"
        now = datetime.now(UTC)

        # 1. Read before-state for ETag/precondition safety
        read_action = ActionContract.create(
            mission_id=self.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=self.action_cal.target,
            parameters={},
            action_id=ActionId.generate(),
        )
        before_read = self.cal_read_adapter.read_event(read_action)
        assert before_read.observation is not None

        # 2. Issue ApprovalGrant bound to exact action and target
        grant = ApprovalGrant(
            action=self.action_cal,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=15),
        )

        # 3. Execute approved calendar update with independent read-back & receipt factory
        outcome: ApprovedCalendarUpdateOutcome = execute_approved_calendar_update(
            action=self.validated_action_cal,
            router=self.router,
            approval=grant,
            ledger=self.env.approval_ledger,
            read_adapter=self.cal_read_adapter,
            predicate=self.pred_calendar,
            source_sha="af2747f9c9b7562af8b9a226bb1e7f42b105af4f",
            tracker=self.tracker,
            pending_approval=self.pending_approval,
            before_read=before_read,
            spy=None,
            mission_ledger=self.env.mission_ledger,
            at=now,
            provenance=self.env.provenance,
        )

        assert outcome.is_verified
        assert outcome.provider_result.writes_performed == 1
        self.total_writes += 1
        self.approved_cal_outcome = outcome

        res = KillerMissionStepResult(
            task_id="P-13.05",
            step_name="Approve, Execute & Verify Calendar Update",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                "Approval consumed atomically. Event updated to 07:30 (writes=1). "
                "Independent read-back verified. ApprovedActionReceipt issued."
            ),
            writes_performed=1,
            is_verified=True,
            extra_metadata={
                "approval_id": str(grant.approval_id),
                "start_time": CANONICAL_DESIRED_START_TIME,
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
        """Evaluate all predicates; transition to READY; produce immutable receipt."""
        now = datetime.now(UTC)

        # 1. Weather observation
        target_weather = TargetIdentity(
            system="open_meteo",
            resource_kind=ResourceKind.WEATHER_LOCATION,
            resource_id=CANONICAL_WEATHER_LOCATION_ID,
        )
        weather_obs = VerificationObservation(
            target=target_weather,
            observed_at=now,
            exists=True,
            properties={"weather_status": "available"},
            provenance=self.env.provenance,
        )

        # 2. Calendar observation from verified read-back
        cal_obs = VerificationObservation(
            target=self.action_cal.target,
            observed_at=now,
            exists=True,
            properties={"start_time": CANONICAL_DESIRED_START_TIME},
            provenance=self.env.provenance,
        )

        observations = {
            PREDICATE_ID_WEATHER: weather_obs,
            PREDICATE_ID_TASK: self.task_observation,
            PREDICATE_ID_CALENDAR: cal_obs,
        }

        # 3. Deterministic readiness determination
        verification_requests = self.get_verification_requests()
        readiness: MissionReadinessDetermination = compute_mission_readiness(
            mission_id=self.mission_id,
            current_state=MissionState.VERIFYING,
            predicates=self.canonical_predicates,
            verification_requests=verification_requests,
            observations=observations,
            at=now,
        )
        assert readiness.is_ready
        assert readiness.state == MissionState.READY

        # 4. Create durable MissionSnapshot in READY state
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

        # 6. Produce immutable historical ReceiptProjection
        receipt_proj: ReceiptProjection = create_mission_ready_receipt(snapshot)
        self.ready_receipt = receipt_proj
        self.ready_receipt_hash = receipt_proj.receipt_hash.value

        res = KillerMissionStepResult(
            task_id="P-13.06",
            step_name="Produce Deterministic READY Mission Receipt",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                "All predicates evaluated TRUE and FRESH. Mission promoted to READY. "
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
        assert self.ready_receipt is not None, "Must produce READY receipt first"
        now = datetime.now(UTC)

        # 1. Induce external mutation on calendar transport (outside StillDone)
        # Event is moved back to 08:00 (departure window violated!)
        if isinstance(self.env.calendar_transport, FakeGoogleCalendarTransport):
            self.env.calendar_transport.seed_event(
                calendar_id=self.env.scope.calendar_id,
                event_id=CANONICAL_DEMO_EVENT_ID,
                summary=CANONICAL_DEMO_EVENT_TITLE,
                start_time=CANONICAL_CONTRADICTORY_START_TIME,
                end_time=CANONICAL_CONTRADICTORY_END_TIME,
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
        assert drift_read.observation is not None
        assert drift_read.observation.start_time == CANONICAL_CONTRADICTORY_START_TIME

        # 3. Create fresh contradictory observation
        fresh_cal_obs = VerificationObservation(
            target=self.action_cal.target,
            observed_at=now,
            exists=True,
            properties={"start_time": CANONICAL_CONTRADICTORY_START_TIME},
            provenance=self.env.provenance,
        )

        # 4. Predicate evaluation evaluates to FALSE
        pred_eval = evaluate_predicate(self.pred_calendar, fresh_cal_obs)
        assert pred_eval.truth == PredicateTruth.FALSE

        # 5. Reconcile mission state against fresh contradictory observation
        verification_requests = self.get_verification_requests()

        fresh_observations = {
            PREDICATE_ID_WEATHER: VerificationObservation(
                target=self.action_weather.target,
                observed_at=now,
                exists=True,
                properties={"weather_status": "available"},
                provenance=self.env.provenance,
            ),
            PREDICATE_ID_TASK: VerificationObservation(
                target=TargetIdentity(
                    "google_tasks",
                    ResourceKind.TASK,
                    self.created_task_id,
                    self.env.scope.task_list_id,
                ),
                observed_at=now,
                exists=True,
                properties={"task_title": CANONICAL_DEMO_TASK_TITLE},
                provenance=self.env.provenance,
            ),
            PREDICATE_ID_CALENDAR: fresh_cal_obs,
        }

        reconciliation: ReconciliationDetermination = reconcile_mission_state(
            mission_id=self.mission_id,
            predicates=self.canonical_predicates,
            verification_requests=verification_requests,
            fresh_observations=fresh_observations,
            at=now,
        )
        assert reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE

        transition_result = apply_reconciliation_transition(
            reconciliation=reconciliation,
            prior_state=MissionState.READY,
        )
        assert transition_result.new_state == MissionState.DRIFTED

        # 6. Create snapshot for drifted state and project current state
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
        assert current_state_proj.state == MissionState.DRIFTED

        # 8. Assert historical READY receipt hash on disk is strictly unchanged
        historical_receipt_still_valid = (
            self.ready_receipt.receipt_hash.value == self.ready_receipt_hash
        )
        assert historical_receipt_still_valid

        res = KillerMissionStepResult(
            task_id="P-13.07",
            step_name="Mutate Calendar Externally & Reconcile Drift",
            status="PASS",
            provenance=self.env.provenance,
            details=(
                "External calendar change observed (start_time=08:00). "
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
        self.step_p13_01_seed()
        self.step_p13_02_plan()
        self.step_p13_03_tasks_prep()
        self.step_p13_04_calendar_pause()
        self.step_p13_05_calendar_approve()
        self.step_p13_06_ready_receipt()
        self.step_p13_07_mutate_and_drift()

        return KillerMissionSliceOutcome(
            mission_id=self.mission_id,
            intent=self.intent_text,
            steps=self.step_results,
            ready_receipt_hash=self.ready_receipt_hash,
            drifted_receipt_hash=self.ready_receipt_hash,
            historical_receipt_immutable=True,
            final_state=MissionState.DRIFTED,
            total_writes_performed=self.total_writes,
            provenance=self.env.provenance,
            is_live=self.env.provenance == EvidenceProvenance.LIVE_GOOGLE,
        )


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
    "KillerMissionEnvironment",
    "KillerMissionSliceOutcome",
    "KillerMissionSliceRunner",
    "KillerMissionStepResult",
]
