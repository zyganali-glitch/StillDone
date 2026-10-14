"""Tests for P-18.05: Google Calendar, Google Tasks, and Open-Meteo Quota Safety.

Governing Task: P-18.05 — Verify Google/Open-Meteo quota safety
Acceptance Criteria:
- Document relevant published provider limits and applicable usage restrictions with
  source links and verification dates.
- Distinguish published limits from actual remaining account quotas.
- Do not claim a quota was observed if authenticated usage information was unavailable.
- Verify timeout, retry, bounded backoff, and rate-limit handling wherever applicable.
- Confirm that rejected or rate-limited mutations do not become falsely verified.
- Ensure throttling cannot trigger unlimited retries, duplicate writes, or unbounded paid calls.
- Test quota exhaustion, HTTP 429, unavailable provider, and ambiguous retry outcomes
  using mocks/fakes only.
- Keep actual external provider quota observations NOT_OBSERVED unless independently sourced.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from stilldone.adapters.calendar import (
    CalendarPreconditionFailedError,
    CalendarRateLimitError,
    CalendarReadbackStatus,
    CalendarTransportError,
    CalendarTransportEvent,
    CalendarUpdateStatus,
    ExpectedCalendarState,
    GoogleCalendarReadAdapter,
    GoogleCalendarReadbackVerifier,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    ExpectedTaskState,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
    GoogleTasksReadbackVerifier,
    TaskCreateStatus,
    TaskRateLimitError,
    TaskReadbackStatus,
    TaskReadStatus,
    TaskTransportError,
)
from stilldone.adapters.weather import (
    OpenMeteoReadAdapter,
    WeatherLocationConfig,
    WeatherRateLimitError,
    WeatherReadStatus,
    WeatherTimeoutError,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    AuthorityClass,
)
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.killer_mission import (
    KillerMissionEnvironment,
    KillerMissionSliceRunner,
)

# Reference timestamp
T_REF = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)


# ===========================================================================
# Quota Specification Reference Model
# ===========================================================================


@dataclass(frozen=True)
class ProviderQuotaSpec:
    """Documented official quota limits and verification metadata."""

    provider_name: str
    official_documentation_url: str
    verification_date: str
    published_limit_description: str
    published_limit_units_per_day: int
    stilldone_mission_consumption_estimate: int
    applicable_restrictions: list[str]
    usage_based_billing_exposure: str
    actual_remaining_account_quota: str = "NOT_OBSERVED"
    authenticated_usage_observed: bool = False


# Documented published limits per official provider documentation as of 2026-10-13
PUBLISHED_QUOTA_SPECS: dict[str, ProviderQuotaSpec] = {
    "google_calendar": ProviderQuotaSpec(
        provider_name="Google Calendar API v3",
        official_documentation_url="https://developers.google.com/workspace/calendar/api/guides/quota",
        verification_date="2026-10-13",
        published_limit_description=(
            "1,000,000 queries per day billing threshold; 10,000 requests/minute/project; "
            "600 requests/minute/user/project (May 1, 2026 quota revision)"
        ),
        published_limit_units_per_day=1_000_000,
        # Estimated 3 calls: 1 read + 1 update + 1 read-back
        stilldone_mission_consumption_estimate=3,
        applicable_restrictions=[
            "10,000 requests/minute/project default rate limit",
            "600 requests/minute/user/project user concurrency limit",
            "1,000,000 requests/day/project billing threshold",
            "Historical quota preservation may apply to eligible older projects",
            "Over-threshold usage subject to pay-as-you-go billing if billing enabled",
        ],
        usage_based_billing_exposure=(
            "Exceeding 1M daily queries incurs pay-as-you-go charges. StillDone enforces "
            "strict call bounds to remain orders of magnitude below threshold "
            "($0.00 personal spend)."
        ),
        actual_remaining_account_quota="NOT_OBSERVED",
        authenticated_usage_observed=False,
    ),
    "google_tasks": ProviderQuotaSpec(
        provider_name="Google Tasks API v1",
        official_documentation_url="https://developers.google.com/workspace/tasks/limits",
        verification_date="2026-10-13",
        published_limit_description="50,000 queries per day courtesy limit",
        published_limit_units_per_day=50_000,
        stilldone_mission_consumption_estimate=2,  # Estimated 2 calls: 1 create + 1 read-back
        applicable_restrictions=[
            "50,000 queries/day courtesy limit",
            "Account-level quota increases require administrative console request",
        ],
        usage_based_billing_exposure=(
            "Standard courtesy quota. Hard limit stops execution fail-closed "
            "without automatic billing."
        ),
        actual_remaining_account_quota="NOT_OBSERVED",
        authenticated_usage_observed=False,
    ),
    "open_meteo": ProviderQuotaSpec(
        provider_name="Open-Meteo Free Forecast API",
        official_documentation_url="https://open-meteo.com/en/terms",
        verification_date="2026-10-13",
        published_limit_description=(
            "10,000 calls per day, 5,000 calls per hour, 600 calls per minute for "
            "non-commercial free use (CC BY 4.0 attribution required)"
        ),
        published_limit_units_per_day=10_000,
        stilldone_mission_consumption_estimate=1,  # Estimated 1 call: 1 weather read
        applicable_restrictions=[
            "10,000 daily API calls",
            "5,000 hourly API calls",
            "600 per-minute burst rate",
            "Non-commercial use only",
            "CC BY 4.0 attribution required",
        ],
        usage_based_billing_exposure=(
            "Free tier non-commercial use has zero fee; commercial use requires paid license."
        ),
        actual_remaining_account_quota="NOT_OBSERVED",
        authenticated_usage_observed=False,
    ),
}


# ===========================================================================
# 1. Published Provider Limits Documentation and Unobserved Truth
# ===========================================================================


class TestPublishedLimitsAndUnobservedQuotaTruth:
    """Verify published limits are documented and remaining quotas are NOT_OBSERVED."""

    def test_provider_quota_specs_contain_required_official_metadata(self) -> None:
        """Every provider spec includes official URL, verification date, and limits."""
        for _name, spec in PUBLISHED_QUOTA_SPECS.items():
            assert spec.official_documentation_url.startswith("https://")
            assert spec.verification_date == "2026-10-13"
            assert spec.published_limit_units_per_day > 0
            assert spec.stilldone_mission_consumption_estimate > 0
            assert len(spec.applicable_restrictions) > 0
            assert spec.usage_based_billing_exposure != ""
            # Offline execution invariant: actual quota MUST be NOT_OBSERVED
            assert spec.actual_remaining_account_quota == "NOT_OBSERVED"
            assert spec.authenticated_usage_observed is False

    def test_canonical_mission_consumption_is_negligible_fraction_of_limits(self) -> None:
        """Estimated mission consumption is <= 0.01% of published default daily limits."""
        for name, spec in PUBLISHED_QUOTA_SPECS.items():
            ratio = spec.stilldone_mission_consumption_estimate / spec.published_limit_units_per_day
            assert ratio <= 0.0001, f"{name} consumption ratio too high: {ratio}"


# ===========================================================================
# 2. Google Calendar Quota Safety & Rate-Limit Handling (HTTP 429)
# ===========================================================================


class TestGoogleCalendarQuotaSafety:
    """Verify Calendar adapter fails closed on HTTP 429 rate limit with zero writes."""

    @pytest.fixture
    def scope(self) -> DemoResourceScope:
        return DemoResourceScope(
            calendar_id="demo-cal-123@group.calendar.google.com",
            task_list_id="demo-tl-456",
        )

    @pytest.fixture
    def update_action(self, scope: DemoResourceScope) -> ActionContract:
        return ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_UPDATE,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id="evt-target-789",
                parent_id=scope.calendar_id,
            ),
            parameters={"start_time": "2026-10-14T07:30:00Z"},
        )

    @pytest.fixture
    def valid_approval(self, update_action: ActionContract) -> ApprovalGrant:
        return ApprovalGrant.create(
            action=update_action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=T_REF,
            expires_at=T_REF + timedelta(hours=1),
        )

    def test_calendar_rate_limit_429_on_read_before_write_yields_zero_writes(
        self,
        scope: DemoResourceScope,
        update_action: ActionContract,
        valid_approval: ApprovalGrant,
    ) -> None:
        """When Calendar returns HTTP 429 during read-before-write, update aborts with 0 writes."""

        class ThrottledTransport:
            def get_event(self, calendar_id: str, event_id: str) -> Any:
                raise CalendarRateLimitError("Quota exceeded: 429 Too Many Requests")

            def update_event(
                self,
                calendar_id: str,
                event_id: str,
                payload: dict[str, Any],
                if_match: str,
                send_updates: str = "none",
            ) -> CalendarTransportEvent:
                pytest.fail("update_event should NOT be called after read-before-write failure")

        adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=ThrottledTransport())
        result = adapter.update_event(action=update_action, approval=valid_approval, at=T_REF)

        assert result.status == CalendarUpdateStatus.PROVIDER_ERROR
        assert result.writes_performed == 0
        assert (
            result.error_message is not None
            and "rate limit exceeded" in result.error_message.lower()
        )

    def test_calendar_rate_limit_429_on_mutation_yields_zero_writes(
        self,
        scope: DemoResourceScope,
        update_action: ActionContract,
        valid_approval: ApprovalGrant,
    ) -> None:
        """When Calendar returns HTTP 429 during update mutation, result reports 0 writes."""
        initial_event = CalendarTransportEvent(
            id="evt-target-789",
            etag='"etag-initial"',
            summary="Family Departure",
            start_time="2026-10-14T08:00:00Z",
            end_time="2026-10-14T08:30:00Z",
            all_day=False,
            status="confirmed",
        )

        class ThrottledOnWriteTransport:
            def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent:
                return initial_event

            def update_event(
                self,
                calendar_id: str,
                event_id: str,
                payload: dict[str, Any],
                if_match: str,
                send_updates: str = "none",
            ) -> CalendarTransportEvent:
                raise CalendarRateLimitError("Rate limit exceeded on mutation (HTTP 429)")

        adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=ThrottledOnWriteTransport())
        result = adapter.update_event(action=update_action, approval=valid_approval, at=T_REF)

        assert result.status == CalendarUpdateStatus.PROVIDER_ERROR
        assert result.writes_performed == 0

    def test_calendar_readback_verifier_fails_closed_under_transport_error(
        self,
        scope: DemoResourceScope,
    ) -> None:
        """Transport error or 429 during read-back results in is_verified = False."""

        class ErrorTransport:
            def get_event(self, calendar_id: str, event_id: str) -> Any:
                raise CalendarTransportError("503 Service Unavailable", status_code=503)

            def update_event(
                self,
                calendar_id: str,
                event_id: str,
                payload: dict[str, Any],
                if_match: str,
                send_updates: str = "none",
            ) -> CalendarTransportEvent:
                raise CalendarTransportError("503 Service Unavailable", status_code=503)

        read_adapter = GoogleCalendarReadAdapter(scope=scope, transport=ErrorTransport())
        verifier = GoogleCalendarReadbackVerifier(read_adapter=read_adapter)

        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-target-789",
            parent_id=scope.calendar_id,
        )
        expected = ExpectedCalendarState(start_time="2026-10-14T07:30:00Z")
        result = verifier.verify(target=target, expected=expected)

        assert result.is_match is False
        assert result.status == CalendarReadbackStatus.PROVIDER_ERROR

    def test_calendar_precondition_conflict_412_avoids_duplicate_or_corrupt_writes(
        self,
        scope: DemoResourceScope,
        update_action: ActionContract,
        valid_approval: ApprovalGrant,
    ) -> None:
        """HTTP 412 precondition conflict yields CONFLICT status with 0 writes."""
        initial_event = CalendarTransportEvent(
            id="evt-target-789",
            etag='"etag-old"',
            summary="Departure",
            start_time="2026-10-14T08:00:00Z",
            end_time="2026-10-14T08:30:00Z",
            all_day=False,
        )

        class ConflictTransport:
            def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent:
                return initial_event

            def update_event(
                self,
                calendar_id: str,
                event_id: str,
                payload: dict[str, Any],
                if_match: str,
                send_updates: str = "none",
            ) -> CalendarTransportEvent:
                raise CalendarPreconditionFailedError("ETag mismatch: 412 Precondition Failed")

        adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=ConflictTransport())
        result = adapter.update_event(action=update_action, approval=valid_approval, at=T_REF)

        assert result.status == CalendarUpdateStatus.CONFLICT
        assert result.writes_performed == 0
        assert result.error_message is not None and "conflict" in result.error_message.lower()

    def test_calendar_idempotency_avoids_redundant_writes(
        self,
        scope: DemoResourceScope,
        update_action: ActionContract,
        valid_approval: ApprovalGrant,
    ) -> None:
        """If event already matches requested time, returns NOOP_ALREADY_APPLIED with 0 writes."""
        already_applied_event = CalendarTransportEvent(
            id="evt-target-789",
            etag='"etag-current"',
            summary="Departure",
            start_time="2026-10-14T07:30:00Z",  # Already matches target
            end_time="2026-10-14T08:00:00Z",
            all_day=False,
        )

        update_called = False

        class NoopTransport:
            def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent:
                return already_applied_event

            def update_event(
                self,
                calendar_id: str,
                event_id: str,
                payload: dict[str, Any],
                if_match: str,
                send_updates: str = "none",
            ) -> CalendarTransportEvent:
                nonlocal update_called
                update_called = True
                return already_applied_event

        adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=NoopTransport())
        result = adapter.update_event(action=update_action, approval=valid_approval, at=T_REF)

        assert result.status == CalendarUpdateStatus.NOOP_ALREADY_APPLIED
        assert result.writes_performed == 0
        assert update_called is False


# ===========================================================================
# 3. Google Tasks Quota Safety & Rate-Limit Handling (HTTP 429)
# ===========================================================================


class TestGoogleTasksQuotaSafety:
    """Verify Tasks adapter fails closed on HTTP 429 rate limit with zero writes."""

    @pytest.fixture
    def scope(self) -> DemoResourceScope:
        return DemoResourceScope(
            calendar_id="demo-cal-123@group.calendar.google.com",
            task_list_id="demo-tl-456",
        )

    @pytest.fixture
    def create_action(self, scope: DemoResourceScope) -> ActionContract:
        return ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.TASK_CREATE,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK_LIST,
                resource_id=scope.task_list_id,
            ),
            parameters={"title": "Pack bags for morning departure", "due": "2026-10-14"},
        )

    def test_tasks_rate_limit_429_yields_zero_writes_and_fails_closed(
        self,
        scope: DemoResourceScope,
        create_action: ActionContract,
    ) -> None:
        """When Tasks API returns HTTP 429, create_task returns PROVIDER_ERROR with writes=0."""

        class ThrottledTasksTransport:
            def insert_task(self, task_list_id: str, body: dict[str, Any]) -> Any:
                raise TaskRateLimitError("Tasks quota exceeded (HTTP 429)")

            def get_task(self, task_list_id: str, task_id: str) -> Any:
                raise TaskRateLimitError("Tasks quota exceeded (HTTP 429)")

            def list_tasks(self, task_list_id: str, **kwargs: Any) -> Any:
                raise TaskRateLimitError("Tasks quota exceeded (HTTP 429)")

        adapter = GoogleTasksCreateAdapter(
            scope=scope,
            transport=ThrottledTasksTransport(),  # type: ignore[arg-type]
        )
        result = adapter.create_task(action=create_action, approval=None, at=T_REF)

        assert result.status == TaskCreateStatus.PROVIDER_ERROR
        assert result.writes_performed == 0
        assert result.error_message is not None and "rate limit" in result.error_message.lower()

    def test_tasks_readback_verifier_rejects_on_transport_failure(
        self,
        scope: DemoResourceScope,
    ) -> None:
        """Read-back verifier cannot verify when provider errors out."""

        class ErrorTasksTransport:
            def insert_task(self, task_list_id: str, body: dict[str, Any]) -> Any:
                raise TaskTransportError("503 Service Unavailable", status_code=503)

            def get_task(self, task_list_id: str, task_id: str) -> Any:
                raise TaskTransportError("503 Service Unavailable", status_code=503)

            def list_tasks(self, task_list_id: str, **kwargs: Any) -> Any:
                raise TaskTransportError("503 Service Unavailable", status_code=503)

        read_adapter = GoogleTasksReadAdapter(
            scope=scope,
            transport=ErrorTasksTransport(),  # type: ignore[arg-type]
        )
        verifier = GoogleTasksReadbackVerifier(read_adapter=read_adapter)

        expected = ExpectedTaskState(title="Pack bags for morning departure", due="2026-10-14")
        result = verifier.verify_task_state(task_id="task-999", expected=expected)

        assert result.status == TaskReadbackStatus.PROVIDER_ERROR
        assert result.observation is None


# ===========================================================================
# 4. Open-Meteo Quota Safety & Rate-Limit Handling (HTTP 429 / Timeout)
# ===========================================================================


class TestOpenMeteoQuotaSafety:
    """Verify Open-Meteo adapter handles rate limiting and timeouts gracefully."""

    @pytest.fixture
    def weather_config(self) -> WeatherLocationConfig:
        return WeatherLocationConfig(
            location_id="loc-berlin-01",
            latitude=52.52,
            longitude=13.405,
            timezone="Europe/Berlin",
        )

    @pytest.fixture
    def weather_action(self, weather_config: WeatherLocationConfig) -> ActionContract:
        return ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.WEATHER_READ,
            target=TargetIdentity(
                system="open_meteo",
                resource_kind=ResourceKind.WEATHER_LOCATION,
                resource_id=weather_config.location_id,
            ),
            parameters={},
        )

    def test_open_meteo_rate_limit_429_fails_closed_without_leakage(
        self,
        weather_config: WeatherLocationConfig,
        weather_action: ActionContract,
    ) -> None:
        """When Open-Meteo returns HTTP 429, adapter returns error without leaking URL."""

        class ThrottledWeatherTransport:
            @property
            def provenance(self) -> EvidenceProvenance:
                return EvidenceProvenance.FIXTURE

            def fetch_current_weather(
                self,
                latitude: float,
                longitude: float,
                timezone: str = "UTC",
            ) -> dict[str, Any]:
                raise WeatherRateLimitError("Open-Meteo rate limit exceeded (HTTP 429)")

        adapter = OpenMeteoReadAdapter(
            config=weather_config,
            transport=ThrottledWeatherTransport(),
        )
        res = adapter.read_weather(action=weather_action, approval=None)

        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.error_message is not None and "rate limit" in res.error_message.lower()
        # Verify coordinates do not leak in error message
        assert "52.52" not in (res.error_message or "")
        assert "13.405" not in (res.error_message or "")

    def test_open_meteo_timeout_fails_closed(
        self,
        weather_config: WeatherLocationConfig,
        weather_action: ActionContract,
    ) -> None:
        """When Open-Meteo times out, adapter returns error with TIMEOUT classification."""

        class TimeoutWeatherTransport:
            @property
            def provenance(self) -> EvidenceProvenance:
                return EvidenceProvenance.FIXTURE

            def fetch_current_weather(
                self,
                latitude: float,
                longitude: float,
                timezone: str = "UTC",
            ) -> dict[str, Any]:
                raise WeatherTimeoutError("Open-Meteo request timed out after 5.0s")

        adapter = OpenMeteoReadAdapter(
            config=weather_config,
            transport=TimeoutWeatherTransport(),
        )
        res = adapter.read_weather(action=weather_action, approval=None)

        assert res.status == WeatherReadStatus.PROVIDER_ERROR
        assert res.error_message is not None and "timed out" in res.error_message.lower()


# ===========================================================================
# 5. Full Mission Slice Under Provider Throttling
# ===========================================================================


class TestFullMissionSliceUnderProviderThrottling:
    """Verify canonical killer mission slice halts fail-closed if any provider throttles."""

    def test_slice_halts_with_zero_calendar_writes_if_tasks_throttled(self) -> None:
        """If step 3 (tasks) throttles, calendar update step is NOT reached."""
        from stilldone.killer_mission import KillerMissionExecutionError

        env = KillerMissionEnvironment.create_fixture_environment()

        class ThrottledFakeTasks:
            def insert_task(self, task_list_id: str, body: dict[str, Any]) -> Any:
                raise TaskRateLimitError("429 Too Many Requests")

            def get_task(self, task_list_id: str, task_id: str) -> Any:
                raise TaskRateLimitError("429 Too Many Requests")

            def list_tasks(self, task_list_id: str, **kwargs: Any) -> Any:
                raise TaskRateLimitError("429 Too Many Requests")

        env.tasks_transport = ThrottledFakeTasks()  # type: ignore[assignment]
        runner = KillerMissionSliceRunner(env=env)

        # Seed and plan succeed
        runner.step_p13_01_seed()
        runner.step_p13_02_plan()

        # Step 3 tasks fails fail-closed due to rate limit (429)
        with pytest.raises(KillerMissionExecutionError):
            runner.step_p13_03_tasks_prep()

        # Calendar update step (P-13.05) is never reached; ready receipt is never produced
        assert "P-13.05" not in runner.step_results
        assert runner.ready_receipt is None
        # Writes performed is strictly 1 (seed event only; zero tasks and zero calendar writes)
        assert runner.total_writes == 1


# ===========================================================================
# 6. Ambiguous Mutation Safety & Read-Back Requirement
# ===========================================================================


class TestAmbiguousMutationSafety:
    """Verify ambiguous mutations never infer zero writes and strictly require read-back."""

    @pytest.fixture
    def scope(self) -> DemoResourceScope:
        return DemoResourceScope(
            calendar_id="demo-cal-123@group.calendar.google.com",
            task_list_id="demo-tl-456",
        )

    def test_ambiguous_calendar_mutation_never_infers_zero_remote_writes_and_fails_closed(
        self,
        scope: DemoResourceScope,
    ) -> None:
        """Transport failure after write cannot assume 0 remote writes; readback resolves truth."""
        remote_store: dict[str, Any] = {
            "evt-1": {
                "id": "evt-1",
                "summary": "Leave for School",
                "start": {"dateTime": "2026-10-14T07:45:00Z"},
                "end": {"dateTime": "2026-10-14T08:15:00Z"},
                "status": "confirmed",
                "etag": '"etag-v1"',
            }
        }

        class AmbiguousCalendarTransport:
            def __init__(self) -> None:
                self.write_attempted = False

            def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
                raw = remote_store.get(event_id)
                if not raw:
                    return None
                return CalendarTransportEvent(
                    id=raw["id"],
                    etag=raw["etag"],
                    summary=raw.get("summary", "Leave for School"),
                    start_time=raw["start"]["dateTime"],
                    end_time=raw["end"]["dateTime"],
                    all_day=False,
                    status=raw["status"],
                    raw_resource=copy.deepcopy(raw),
                )

            def update_event(
                self,
                calendar_id: str,
                event_id: str,
                payload: dict[str, Any],
                if_match: str,
                send_updates: str = "none",
            ) -> CalendarTransportEvent:
                # The write lands on the remote server
                self.write_attempted = True
                remote_store[event_id]["start"]["dateTime"] = payload["start"]["dateTime"]
                remote_store[event_id]["etag"] = '"etag-v2"'
                # Server committed update, but connection timed out (HTTP 504)
                raise CalendarTransportError(
                    "HTTP 504 Gateway Timeout updating event", status_code=504
                )

        transport = AmbiguousCalendarTransport()
        update_adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=transport)

        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-1",
            parent_id=scope.calendar_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=target,
            parameters={"start_time": "2026-10-14T07:30:00Z"},
        )
        grant = ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=T_REF,
            expires_at=T_REF + timedelta(minutes=15),
        )

        res = update_adapter.update_event(
            action=action,
            approval=grant,
            at=T_REF,
        )

        # 1. Update adapter reports PROVIDER_ERROR fail-closed
        assert res.status == CalendarUpdateStatus.PROVIDER_ERROR
        # 2. Never falsely mark verified
        assert not hasattr(res, "is_verified") or not getattr(res, "is_verified", False)
        # 3. Remote state was actually modified despite client exception (proves non-zero reality)
        assert transport.write_attempted is True
        assert remote_store["evt-1"]["start"]["dateTime"] in (
            "2026-10-14T07:30:00Z",
            "2026-10-14T07:30:00+00:00",
        )
        # 4. Never infer zero writes: writes_performed is None (ambiguous), committed is UNKNOWN
        assert res.writes_performed is None
        assert res.writes_committed == "UNKNOWN"

        # 5. Execution record preserves UNKNOWN writes without claiming 0
        from stilldone.execution.attempts import record_calendar_update_result

        prov_res = record_calendar_update_result(res)
        assert prov_res.writes_performed is None
        assert prov_res.writes_committed == "UNKNOWN"
        assert prov_res.to_dict()["writes_performed"] == "UNKNOWN"

        # 6. Adapter-to-recovery outcome: ambiguous timeout forbids blind retry, requires read-back
        from stilldone.recovery.orchestrator import (
            RecoveryActionType,
            evaluate_post_execution_recovery,
        )
        from stilldone.recovery.retry import RetryClassification, RetryPolicy

        rec_dec = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=res.error_message,
            policy=RetryPolicy(max_attempts=3),
        )
        assert rec_dec.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert rec_dec.retry_classification == RetryClassification.RETRYABLE_TRANSIENT
        assert "requires independent verification" in rec_dec.reason.lower()

        # 7. Independent read-back resolves actual state without repeating the write
        read_adapter = GoogleCalendarReadAdapter(scope=scope, transport=transport)
        verifier = GoogleCalendarReadbackVerifier(read_adapter=read_adapter)
        expected = ExpectedCalendarState(
            start_time="2026-10-14T07:30:00Z",
        )
        readback_res = verifier.verify(target=target, expected=expected)
        assert readback_res.status == CalendarReadbackStatus.MATCH

    def test_ambiguous_tasks_mutation_requires_readback_before_retry(
        self,
        scope: DemoResourceScope,
    ) -> None:
        """Ambiguous task insertion fails closed and must be read back before safe retry."""
        remote_tasks: dict[str, Any] = {}

        class AmbiguousTasksTransport:
            def __init__(self) -> None:
                self.insertion_attempted = False

            def insert_task(self, task_list_id: str, body: dict[str, Any]) -> Any:
                self.insertion_attempted = True
                task_id = "task-ambiguous-001"
                remote_tasks[task_id] = {
                    "id": task_id,
                    "title": body["title"],
                    "status": "needsAction",
                    "due": body.get("due"),
                }
                # Network timeout while awaiting acknowledgment
                raise TaskTransportError("HTTP 504 Gateway Timeout on task insert")

            def get_task(self, task_list_id: str, task_id: str) -> Any:
                raw = remote_tasks.get(task_id)
                if not raw:
                    return None
                from stilldone.adapters.tasks import TaskTransportItem

                return TaskTransportItem(
                    id=raw["id"],
                    title=raw["title"],
                    status=raw["status"],
                    due=raw.get("due"),
                )

            def list_tasks(
                self,
                task_list_id: str,
                show_completed: bool = False,
                show_deleted: bool = False,
                show_hidden: bool = False,
                show_assigned: bool = False,
                max_results: int = 100,
                page_token: str | None = None,
            ) -> tuple[list[Any], str | None]:
                from stilldone.adapters.tasks import TaskTransportItem

                items = [
                    TaskTransportItem(
                        id=v["id"],
                        title=v["title"],
                        status=v["status"],
                        due=v.get("due"),
                    )
                    for v in remote_tasks.values()
                ]
                return items, None

        transport: Any = AmbiguousTasksTransport()
        create_adapter = GoogleTasksCreateAdapter(scope=scope, transport=transport)

        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id=scope.task_list_id,
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=target,
            parameters={"title": "Pack backpacks"},
        )

        res = create_adapter.create_task(action=action, approval=None, at=T_REF)

        # 1. Adapter returns PROVIDER_ERROR; does NOT confer VERIFIED
        assert res.status == TaskCreateStatus.PROVIDER_ERROR
        assert transport.insertion_attempted is True
        # Remote store actually contains the task
        assert "task-ambiguous-001" in remote_tasks
        # 2. Never infer zero writes: writes_performed is None, committed is UNKNOWN
        assert res.writes_performed is None
        assert res.writes_committed == "UNKNOWN"

        # 3. Execution record preserves UNKNOWN writes without claiming 0
        from stilldone.execution.attempts import record_task_create_result

        prov_res = record_task_create_result(res)
        assert prov_res.writes_performed is None
        assert prov_res.writes_committed == "UNKNOWN"
        assert prov_res.to_dict()["writes_performed"] == "UNKNOWN"

        # 4. Adapter-to-recovery outcome: ambiguous timeout forbids blind retry, requires read-back
        from stilldone.recovery.orchestrator import (
            RecoveryActionType,
            evaluate_post_execution_recovery,
        )
        from stilldone.recovery.retry import RetryClassification, RetryPolicy

        rec_dec = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=res.error_message,
            policy=RetryPolicy(max_attempts=3),
        )
        assert rec_dec.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert rec_dec.retry_classification == RetryClassification.RETRYABLE_TRANSIENT
        assert "requires read-before-retry" in rec_dec.reason.lower()

        # 5. Independent read-back detects the task exists via task read
        read_adapter = GoogleTasksReadAdapter(scope=scope, transport=transport)
        task_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-ambiguous-001",
            parent_id=scope.task_list_id,
        )
        read_action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_READ,
            target=task_target,
            parameters={},
        )
        read_res = read_adapter.read_task(action=read_action)
        assert read_res.status == TaskReadStatus.MATCH
        assert read_res.observation is not None
        assert read_res.observation.title == "Pack backpacks"

    def test_calendar_usage_based_billing_exposure_documented_and_bounded(self) -> None:
        """Verify Calendar API 1M queries/day billing threshold is documented and bounded."""
        spec = PUBLISHED_QUOTA_SPECS["google_calendar"]
        assert "billing threshold" in spec.published_limit_description.lower()
        assert spec.published_limit_units_per_day == 1_000_000
        # Estimated consumption represents 0.0003% of threshold
        assert spec.stilldone_mission_consumption_estimate == 3
        ratio = spec.stilldone_mission_consumption_estimate / spec.published_limit_units_per_day
        assert ratio < 0.00001
        # Preserves zero personal spend policy
        assert "personal spend" in spec.usage_based_billing_exposure.lower()


class TestUnknownWriteSemanticsAndConsistency:
    """Adversarial regression tests for P-18.05: Unknown-write semantics, router, and gate."""

    def test_provider_execution_result_rejects_contradictory_classifications(self) -> None:
        """Verify ProviderExecutionResult rejects contradictory writes/committed/success states."""
        from stilldone.execution.contracts import (
            ExecutionContractTypeError,
            ExecutionContractValueError,
        )
        from stilldone.execution.state import ProviderExecutionResult

        # 1. Invalid writes_committed type or value
        with pytest.raises(ExecutionContractTypeError, match="writes_committed must be a string"):
            ProviderExecutionResult(ActionType.CALENDAR_READ, True, "OK", writes_committed=123)  # type: ignore[arg-type]

        with pytest.raises(
            ExecutionContractValueError, match="must be one of 'CONFIRMED', 'NONE', 'UNKNOWN'"
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_READ, True, "OK", writes_committed="INVALID"
            )

        # 2. writes_committed='UNKNOWN' but writes_performed is not None
        with pytest.raises(
            ExecutionContractValueError,
            match="writes_performed must be None when writes_committed is 'UNKNOWN'",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                False,
                "ERR",
                writes_performed=0,
                writes_committed="UNKNOWN",
            )

        with pytest.raises(
            ExecutionContractValueError,
            match="writes_performed must be None when writes_committed is 'UNKNOWN'",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                False,
                "ERR",
                writes_performed=1,
                writes_committed="UNKNOWN",
            )

        # 3. writes_committed='UNKNOWN' with success=True
        with pytest.raises(
            ExecutionContractValueError,
            match="success cannot be True when writes_committed is 'UNKNOWN'",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                True,
                "OK",
                writes_performed=None,
                writes_committed="UNKNOWN",
            )

        # 4. writes_performed=None but writes_committed != 'UNKNOWN'
        with pytest.raises(
            ExecutionContractValueError,
            match="writes_committed must be 'UNKNOWN' when writes_performed is None",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                False,
                "ERR",
                writes_performed=None,
                writes_committed="NONE",
            )

        with pytest.raises(
            ExecutionContractValueError,
            match="writes_committed must be 'UNKNOWN' when writes_performed is None",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                False,
                "ERR",
                writes_performed=None,
                writes_committed="CONFIRMED",
            )

        # 5. writes_committed='NONE' but writes_performed != 0
        with pytest.raises(
            ExecutionContractValueError,
            match="writes_performed must be 0 when writes_committed is 'NONE'",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                False,
                "ERR",
                writes_performed=1,
                writes_committed="NONE",
            )

        # 6. writes_committed='NONE' and success=True on mutation
        with pytest.raises(
            ExecutionContractValueError,
            match="cannot have success=True when writes_committed is 'NONE'",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE, True, "OK", writes_performed=0, writes_committed="NONE"
            )

        with pytest.raises(
            ExecutionContractValueError,
            match="cannot have success=True when writes_committed is 'NONE'",
        ):
            ProviderExecutionResult(
                ActionType.TASK_CREATE, True, "OK", writes_performed=0, writes_committed="NONE"
            )

        # 7. writes_committed='CONFIRMED' with writes_performed <= 0 or None
        with pytest.raises(
            ExecutionContractValueError,
            match="must be strictly positive when writes_committed is 'CONFIRMED'",
        ):
            ProviderExecutionResult(
                ActionType.CALENDAR_UPDATE,
                True,
                "OK",
                writes_performed=0,
                writes_committed="CONFIRMED",
            )

        # 8. Read-only actions cannot write or have CONFIRMED
        with pytest.raises(ExecutionContractValueError, match="cannot perform writes"):
            ProviderExecutionResult(
                ActionType.CALENDAR_READ,
                True,
                "OK",
                writes_performed=1,
                writes_committed="CONFIRMED",
            )

        with pytest.raises(ExecutionContractValueError, match="must have writes_committed='NONE'"):
            ProviderExecutionResult(
                ActionType.TASK_READ, True, "OK", writes_performed=0, writes_committed="CONFIRMED"
            )

    def test_record_provider_exception_read_actions_zero_writes(self) -> None:
        """Verify read-only actions always produce 0 writes and NONE committed on exception."""
        from stilldone.execution.attempts import record_provider_exception

        for r_act in (ActionType.CALENDAR_READ, ActionType.TASK_READ, ActionType.WEATHER_READ):
            res = record_provider_exception(r_act, RuntimeError("Random socket crash"))
            assert res.writes_performed == 0
            assert res.writes_committed == "NONE"
            assert res.success is False

    def test_record_provider_exception_preserves_zero_writes_on_proven_rejections(self) -> None:
        """Verify proven pre-dispatch and definitive provider rejections record 0 writes / NONE."""
        from stilldone.adapters.calendar import CalendarAuthenticationError, CalendarRateLimitError
        from stilldone.adapters.tasks import TaskAuthenticationError, TaskRateLimitError
        from stilldone.execution.attempts import record_provider_exception
        from stilldone.execution.router import ActionAuthorityError

        # Rate limits
        res1 = record_provider_exception(ActionType.CALENDAR_UPDATE, CalendarRateLimitError("429"))
        assert res1.writes_performed == 0
        assert res1.writes_committed == "NONE"

        res2 = record_provider_exception(ActionType.TASK_CREATE, TaskRateLimitError("429"))
        assert res2.writes_performed == 0
        assert res2.writes_committed == "NONE"

        # Authentication rejections
        res3 = record_provider_exception(
            ActionType.CALENDAR_UPDATE, CalendarAuthenticationError("401")
        )
        assert res3.writes_performed == 0
        assert res3.writes_committed == "NONE"

        res4 = record_provider_exception(ActionType.TASK_CREATE, TaskAuthenticationError("403"))
        assert res4.writes_performed == 0
        assert res4.writes_committed == "NONE"

        # Pre-dispatch authority denial
        res5 = record_provider_exception(
            ActionType.CALENDAR_UPDATE, ActionAuthorityError("No approval grant")
        )
        assert res5.writes_performed == 0
        assert res5.writes_committed == "NONE"

    def test_record_provider_exception_unknown_on_unexpected_mutation_exceptions(self) -> None:
        """Verify unexpected exceptions after attempted mutation do NOT assume zero writes."""
        from stilldone.adapters.calendar import CalendarTransportError
        from stilldone.execution.attempts import record_provider_exception

        # Generic RuntimeError after dispatch
        res1 = record_provider_exception(
            ActionType.CALENDAR_UPDATE, RuntimeError("Connection reset by peer")
        )
        assert res1.writes_performed is None
        assert res1.writes_committed == "UNKNOWN"
        assert res1.to_dict()["writes_performed"] == "UNKNOWN"
        assert res1.to_dict()["writes_committed"] == "UNKNOWN"

        # TimeoutError during task create
        res2 = record_provider_exception(
            ActionType.TASK_CREATE, TimeoutError("Timeout waiting for write response")
        )
        assert res2.writes_performed is None
        assert res2.writes_committed == "UNKNOWN"

        # CalendarTransportError without 4xx status
        res3 = record_provider_exception(
            ActionType.CALENDAR_UPDATE, CalendarTransportError("Broken pipe")
        )
        assert res3.writes_performed is None
        assert res3.writes_committed == "UNKNOWN"

    def test_router_level_adversarial_unexpected_exception_preserves_unknown(self) -> None:
        """Verify router handlers return UNKNOWN when adapter raises unexpected exceptions."""
        from unittest.mock import MagicMock

        from stilldone.domain.action import (
            ActionContract,
            ActionType,
            ResourceKind,
            TargetIdentity,
        )
        from stilldone.domain.authority import ApprovalGrant, AuthorityClass
        from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
        from stilldone.execution.router import CalendarUpdateHandler, TasksCreateHandler

        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_calendar", resource_kind=ResourceKind.CALENDAR_EVENT, resource_id="evt-1"
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=target,
            parameters={"summary": "New Title"},
        )
        attempt = ExecutionAttempt.create(
            action_id=action.action_id, idempotency_key=IdempotencyKey.generate()
        )

        now = datetime.now(UTC)
        grant = ApprovalGrant(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=10),
        )

        scope = DemoResourceScope(calendar_id="evt-1", task_list_id="tl-1")

        from stilldone.action_policy import validate_action_contract

        # 1. CalendarUpdateHandler with crashing adapter
        mock_cal_adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=MagicMock())
        mock_cal_adapter.update_event = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("Kernel socket reset mid-write")
        )
        handler_cal = CalendarUpdateHandler(mock_cal_adapter)

        res_cal = handler_cal.execute(
            validate_action_contract(action), attempt=attempt, approval=grant
        )
        assert res_cal.writes_performed is None
        assert res_cal.writes_committed == "UNKNOWN"
        assert res_cal.success is False

        # 2. TasksCreateHandler with timing-out adapter
        mock_tasks_adapter = GoogleTasksCreateAdapter(scope=scope, transport=MagicMock())
        mock_tasks_adapter.create_task = MagicMock(  # type: ignore[method-assign]
            side_effect=TimeoutError("Socket dropped awaiting Tasks API ACK")
        )
        handler_tasks = TasksCreateHandler(mock_tasks_adapter)

        tasks_target = TargetIdentity(
            system="google_tasks", resource_kind=ResourceKind.TASK_LIST, resource_id="tl-1"
        )
        tasks_action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=tasks_target,
            parameters={"title": "Pack bags"},
        )
        tasks_attempt = ExecutionAttempt.create(
            action_id=tasks_action.action_id, idempotency_key=IdempotencyKey.generate()
        )

        res_tasks = handler_tasks.execute(
            validate_action_contract(tasks_action), attempt=tasks_attempt
        )
        assert res_tasks.writes_performed is None
        assert res_tasks.writes_committed == "UNKNOWN"
        assert res_tasks.success is False

    def test_gate_level_adversarial_unexpected_exception_preserves_unknown_in_tracker(
        self,
    ) -> None:
        """Verify execution gate records UNKNOWN writes in tracker on unexpected router failure."""
        from unittest.mock import MagicMock

        from stilldone.domain.action import (
            ActionContract,
            ActionType,
            ResourceKind,
            TargetIdentity,
        )
        from stilldone.execution.contracts import MissionExecutionContract
        from stilldone.execution.gate import execute_gated_action
        from stilldone.execution.scheduler import schedule_execution
        from stilldone.execution.state import ActionExecutionStatus, ExecutionStateTracker

        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_tasks", resource_kind=ResourceKind.TASK_LIST, resource_id="tl-1"
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=target,
            parameters={"title": "Pack bags"},
        )
        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action,),
            dependencies={},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        mock_router = MagicMock()
        mock_router.execute.side_effect = RuntimeError(
            "Transport drop after dispatching task create"
        )

        with pytest.raises(RuntimeError, match="Transport drop after dispatching task create"):
            execute_gated_action(action, mock_router, tracker=tracker)

        snapshot = tracker.snapshot()
        rec = snapshot.step_records[action.action_id]
        assert rec.status == ActionExecutionStatus.EXECUTION_FAILED
        assert rec.provider_result is not None
        assert rec.provider_result.writes_performed is None
        assert rec.provider_result.writes_committed == "UNKNOWN"

    def test_recovery_boundary_requires_verification_on_unknown_mutation_outcome(self) -> None:
        """Verify evaluate_post_execution_recovery requires verification for UNKNOWN writes."""
        from stilldone.domain.action import (
            ActionContract,
            ActionType,
            ResourceKind,
            TargetIdentity,
        )
        from stilldone.execution.state import ProviderExecutionResult
        from stilldone.recovery.orchestrator import (
            RecoveryActionType,
            evaluate_post_execution_recovery,
        )
        from stilldone.recovery.retry import RetryPolicy

        mid = MissionId.generate()
        target = TargetIdentity(
            system="google_calendar", resource_kind=ResourceKind.CALENDAR_EVENT, resource_id="evt-1"
        )
        action = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=target,
            parameters={"summary": "New Title"},
        )

        unknown_prov_res = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_UPDATE,
            success=False,
            status_name="RuntimeError",
            writes_performed=None,
            writes_committed="UNKNOWN",
            error_message="Network partition mid-mutation",
        )

        rec_dec = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=unknown_prov_res.error_message,
            policy=RetryPolicy(max_attempts=3),
            provider_result=unknown_prov_res,
        )

        # Ambiguous mutation must NEVER be retried blindly; requires independent verification first
        assert rec_dec.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert "requires independent verification" in rec_dec.reason.lower()
