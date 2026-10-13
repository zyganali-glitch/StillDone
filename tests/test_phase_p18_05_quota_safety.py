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
    actual_remaining_account_quota: str = "NOT_OBSERVED"
    authenticated_usage_observed: bool = False


# Documented published limits per official provider documentation as of 2026-10-13
PUBLISHED_QUOTA_SPECS: dict[str, ProviderQuotaSpec] = {
    "google_calendar": ProviderQuotaSpec(
        provider_name="Google Calendar API v3",
        official_documentation_url="https://developers.google.com/workspace/calendar/api/guides/quota",
        verification_date="2026-10-13",
        published_limit_description="1,000,000 queries per day default per project",
        published_limit_units_per_day=1_000_000,
        stilldone_mission_consumption_estimate=3,  # 1 read + 1 update + 1 read-back
        actual_remaining_account_quota="NOT_OBSERVED",
        authenticated_usage_observed=False,
    ),
    "google_tasks": ProviderQuotaSpec(
        provider_name="Google Tasks API v1",
        official_documentation_url="https://developers.google.com/workspace/tasks/limits",
        verification_date="2026-10-13",
        published_limit_description="50,000 queries per day courtesy limit",
        published_limit_units_per_day=50_000,
        stilldone_mission_consumption_estimate=2,  # 1 create + 1 read-back
        actual_remaining_account_quota="NOT_OBSERVED",
        authenticated_usage_observed=False,
    ),
    "open_meteo": ProviderQuotaSpec(
        provider_name="Open-Meteo Free Forecast API",
        official_documentation_url="https://open-meteo.com/en/pricing",
        verification_date="2026-10-13",
        published_limit_description="10,000 calls per day for non-commercial use (CC BY 4.0)",
        published_limit_units_per_day=10_000,
        stilldone_mission_consumption_estimate=1,  # 1 weather read
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
            # Offline execution invariant: actual quota MUST be NOT_OBSERVED
            assert spec.actual_remaining_account_quota == "NOT_OBSERVED"
            assert spec.authenticated_usage_observed is False

    def test_canonical_mission_consumption_is_negligible_fraction_of_limits(self) -> None:
        """StillDone canonical mission consumes <= 0.01% of any daily limit."""
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
