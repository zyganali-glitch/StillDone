"""Tests for Phase P-08.04: Execution Attempts and Provider-Result Recording.

Validates that:
- Reuses canonical ExecutionAttempt, AttemptId, and IdempotencyKey.
- Exactly one runtime-owned ExecutionAttempt created per attempted action.
- attempt_number starts at 1 (no retry loops in P-08).
- Canonical ActionId and IdempotencyKey are strictly bound.
- Bounded provider-result facts are recorded separately from EvidenceRecord.
- HTTP / API success != VERIFIED / READY.
- Provider errors are sanitized according to security policy (secrets/emails redacted).
- Generic dispatcher routes all canonical adapter results and fails closed on unknown types.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stilldone.adapters.calendar import (
    CalendarEventObservation,
    CalendarReadResult,
    CalendarReadStatus,
    CalendarUpdateResult,
    CalendarUpdateStatus,
)
from stilldone.adapters.tasks import (
    TaskCreateResult,
    TaskCreateStatus,
    TaskObservation,
    TaskReadResult,
    TaskReadStatus,
)
from stilldone.adapters.weather import (
    ProviderAttribution,
    WeatherObservation,
    WeatherReadResult,
    WeatherReadStatus,
)
from stilldone.domain.action import ActionId, ActionType
from stilldone.domain.execution import AttemptId, ExecutionAttempt, IdempotencyKey
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.attempts import (
    create_execution_attempt,
    record_calendar_read_result,
    record_calendar_update_result,
    record_provider_exception,
    record_provider_result,
    record_task_create_result,
    record_task_read_result,
    record_weather_read_result,
)
from stilldone.execution.contracts import ExecutionContractTypeError
from stilldone.execution.state import ProviderExecutionResult


class TestCreateExecutionAttempt:
    """Canonical ExecutionAttempt construction."""

    def test_creates_runtime_owned_attempt(self) -> None:
        aid = ActionId.generate()
        attempt = create_execution_attempt(aid)

        assert isinstance(attempt, ExecutionAttempt)
        assert attempt.action_id == aid
        assert isinstance(attempt.idempotency_key, IdempotencyKey)
        assert isinstance(attempt.attempt_id, AttemptId)
        assert attempt.attempt_number == 1
        assert isinstance(attempt.started_at, datetime)
        assert attempt.started_at.tzinfo == UTC

    def test_explicit_idempotency_key_preserved(self) -> None:
        aid = ActionId.generate()
        ikey = IdempotencyKey.generate()
        attempt = create_execution_attempt(aid, idempotency_key=ikey)
        assert attempt.idempotency_key == ikey

    def test_invalid_action_id_fails_closed(self) -> None:
        with pytest.raises(ExecutionContractTypeError, match="ActionId"):
            create_execution_attempt("not-an-action-id")  # type: ignore[arg-type]


class TestRecordCalendarResults:
    """Provider result recording for Google Calendar."""

    def test_calendar_read_success(self) -> None:
        obs = CalendarEventObservation(
            event_id="evt-456",
            calendar_id="cal-123",
            summary="Leave for school",
            start_time="2026-10-06T07:30:00Z",
            end_time="2026-10-06T08:00:00Z",
            all_day=False,
            etag="etag-abc",
            status="confirmed",
            observed_at=datetime.now(UTC),
        )
        raw = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt-456",
            observation=obs,
            read_at=datetime.now(UTC),
        )
        res = record_calendar_read_result(raw)

        assert isinstance(res, ProviderExecutionResult)
        assert res.action_type == ActionType.CALENDAR_READ
        assert res.success is True
        assert res.status_name == "SUCCESS"
        assert res.writes_performed == 0
        assert res.details["etag_present"] is True
        assert res.error_message is None

    def test_calendar_read_error_sanitized(self) -> None:
        raw = CalendarReadResult(
            status=CalendarReadStatus.PROVIDER_ERROR,
            event_id="evt-456",
            error_message="Auth failed with token secret_bearer_token for user user@example.com",
            read_at=datetime.now(UTC),
        )
        res = record_calendar_read_result(raw)

        assert res.success is False
        assert res.status_name == "PROVIDER_ERROR"
        assert res.error_message is not None
        assert "user@example.com" not in res.error_message
        assert "[REDACTED_EMAIL]" in res.error_message

    def test_calendar_update_success(self) -> None:
        raw = CalendarUpdateResult(
            status=CalendarUpdateStatus.UPDATED,
            event_id="evt-456",
            writes_performed=1,
            updated_at=datetime.now(UTC),
        )
        res = record_calendar_update_result(raw)

        assert res.action_type == ActionType.CALENDAR_UPDATE
        assert res.success is True
        assert res.status_name == "UPDATED"
        assert res.writes_performed == 1


class TestRecordTasksResults:
    """Provider result recording for Google Tasks."""

    def test_task_create_success(self) -> None:
        raw = TaskCreateResult(
            status=TaskCreateStatus.CREATED,
            task_id="task-xyz-123",
            writes_performed=1,
            created_at=datetime.now(UTC),
        )
        res = record_task_create_result(raw)

        assert res.action_type == ActionType.TASK_CREATE
        assert res.success is True
        assert res.status_name == "CREATED"
        assert res.writes_performed == 1
        assert res.details["task_id_present"] is True

    def test_task_read_success(self) -> None:
        obs = TaskObservation(
            task_id="t-456",
            task_list_id="tl-123",
            title="Pack backpacks",
            due="2026-10-06",
            status="needsAction",
            deleted=False,
            hidden=False,
            etag="etag-task",
            observed_at=datetime.now(UTC),
        )
        raw = TaskReadResult(
            status=TaskReadStatus.MATCH,
            observation=obs,
            observed_at=datetime.now(UTC),
        )
        res = record_task_read_result(raw)

        assert res.action_type == ActionType.TASK_READ
        assert res.success is True
        assert res.status_name == "MATCH"
        assert res.writes_performed == 0


class TestRecordWeatherResults:
    """Provider result recording for Open-Meteo."""

    def test_weather_read_success(self) -> None:
        attr = ProviderAttribution(
            provider="Open-Meteo",
            license="CC BY 4.0",
            text="Weather data by Open-Meteo.com",
            url="https://open-meteo.com/",
        )
        obs = WeatherObservation(
            location_id="home",
            temperature_2m=15.0,
            precipitation=0.0,
            weather_code=1,
            wind_speed_10m=5.0,
            units={
                "temperature_2m": "°C",
                "precipitation": "mm",
                "weather_code": "wmo",
                "wind_speed_10m": "km/h",
            },
            observed_at=datetime.now(UTC),
            attribution=attr,
            provenance=EvidenceProvenance.FIXTURE,
            provider_valid_time="2026-10-06T07:00:00Z",
        )
        raw = WeatherReadResult(
            status=WeatherReadStatus.MATCH,
            observation=obs,
            observed_at=datetime.now(UTC),
        )
        res = record_weather_read_result(raw)

        assert res.action_type == ActionType.WEATHER_READ
        assert res.success is True
        assert res.status_name == "MATCH"
        assert res.writes_performed == 0
        assert res.details["provider"] == "Open-Meteo"


class TestRecordProviderException:
    """Provider exception handling and sanitization."""

    def test_record_exception_sanitization(self) -> None:
        exc = ConnectionError("Failed connecting to https://api.google.com?key=AIzaSySecret")
        res = record_provider_exception(ActionType.CALENDAR_READ, exc)

        assert res.success is False
        assert res.status_name == "ConnectionError"
        assert res.writes_performed == 0
        assert res.error_message is not None


class TestGenericRecordProviderResult:
    """Generic dispatcher fail-closed routing."""

    def test_dispatcher_with_calendar_update(self) -> None:
        raw = CalendarUpdateResult(
            status=CalendarUpdateStatus.UPDATED,
            event_id="evt-456",
            writes_performed=1,
            updated_at=datetime.now(UTC),
        )
        res = record_provider_result(ActionType.CALENDAR_UPDATE, raw)
        assert res.status_name == "UPDATED"
        assert res.success is True

    def test_dispatcher_rejects_unknown_result_type(self) -> None:
        with pytest.raises(ExecutionContractTypeError, match="Unsupported raw provider result"):
            record_provider_result(ActionType.CALENDAR_READ, "unknown string result")
