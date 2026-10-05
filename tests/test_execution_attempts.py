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
from stilldone.execution.contracts import (
    ExecutionContractTypeError,
    ExecutionContractValueError,
    ExecutionLineageError,
)
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

    def test_attempt_number_one_accepted(self) -> None:
        aid = ActionId.generate()
        attempt = create_execution_attempt(aid, attempt_number=1)
        assert attempt.attempt_number == 1

    def test_attempt_number_zero_rejected(self) -> None:
        aid = ActionId.generate()
        with pytest.raises(ExecutionContractValueError, match="only allow attempt_number=1"):
            create_execution_attempt(aid, attempt_number=0)

    def test_attempt_number_two_rejected(self) -> None:
        aid = ActionId.generate()
        with pytest.raises(ExecutionContractValueError, match="only allow attempt_number=1"):
            create_execution_attempt(aid, attempt_number=2)

    def test_attempt_number_three_rejected(self) -> None:
        aid = ActionId.generate()
        with pytest.raises(ExecutionContractValueError, match="only allow attempt_number=1"):
            create_execution_attempt(aid, attempt_number=3)

    def test_attempt_number_negative_rejected(self) -> None:
        aid = ActionId.generate()
        with pytest.raises(ExecutionContractValueError, match="only allow attempt_number=1"):
            create_execution_attempt(aid, attempt_number=-1)

    def test_attempt_number_bool_rejected(self) -> None:
        aid = ActionId.generate()
        with pytest.raises(ExecutionContractTypeError, match="attempt_number must be an int"):
            create_execution_attempt(aid, attempt_number=True)


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
    """Generic dispatcher fail-closed routing and lineage enforcement."""

    def test_all_five_valid_result_family_mappings_pass(self) -> None:
        now = datetime.now(UTC)

        # 1. CALENDAR_READ + CalendarReadResult
        cal_read_raw = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt-1",
            read_at=now,
        )
        res1 = record_provider_result(ActionType.CALENDAR_READ, cal_read_raw)
        assert res1.action_type == ActionType.CALENDAR_READ
        assert res1.success is True

        # 2. CALENDAR_UPDATE + CalendarUpdateResult
        cal_up_raw = CalendarUpdateResult(
            status=CalendarUpdateStatus.UPDATED,
            event_id="evt-1",
            writes_performed=1,
            updated_at=now,
        )
        res2 = record_provider_result(ActionType.CALENDAR_UPDATE, cal_up_raw)
        assert res2.action_type == ActionType.CALENDAR_UPDATE
        assert res2.success is True

        # 3. TASK_READ + TaskReadResult
        task_read_raw = TaskReadResult(
            status=TaskReadStatus.MATCH,
            observed_at=now,
        )
        res3 = record_provider_result(ActionType.TASK_READ, task_read_raw)
        assert res3.action_type == ActionType.TASK_READ
        assert res3.success is True

        # 4. TASK_CREATE + TaskCreateResult
        task_create_raw = TaskCreateResult(
            status=TaskCreateStatus.CREATED,
            task_id="t-1",
            writes_performed=1,
            created_at=now,
        )
        res4 = record_provider_result(ActionType.TASK_CREATE, task_create_raw)
        assert res4.action_type == ActionType.TASK_CREATE
        assert res4.success is True

        # 5. WEATHER_READ + WeatherReadResult
        weather_raw = WeatherReadResult(
            status=WeatherReadStatus.MATCH,
            observed_at=now,
        )
        res5 = record_provider_result(ActionType.WEATHER_READ, weather_raw)
        assert res5.action_type == ActionType.WEATHER_READ
        assert res5.success is True

    def test_mismatched_result_family_rejected(self) -> None:
        now = datetime.now(UTC)
        cal_read_raw = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt-1",
            read_at=now,
        )
        weather_raw = WeatherReadResult(
            status=WeatherReadStatus.MATCH,
            observed_at=now,
        )
        task_create_raw = TaskCreateResult(
            status=TaskCreateStatus.CREATED,
            task_id="t-1",
            writes_performed=1,
            created_at=now,
        )

        # TASK_CREATE + CalendarReadResult -> rejected
        with pytest.raises(ExecutionLineageError, match="does not match action_type"):
            record_provider_result(ActionType.TASK_CREATE, cal_read_raw)

        # CALENDAR_READ + WeatherReadResult -> rejected
        with pytest.raises(ExecutionLineageError, match="does not match action_type"):
            record_provider_result(ActionType.CALENDAR_READ, weather_raw)

        # WEATHER_READ + TaskCreateResult -> rejected
        with pytest.raises(ExecutionLineageError, match="does not match action_type"):
            record_provider_result(ActionType.WEATHER_READ, task_create_raw)

    def test_invalid_action_type_rejected(self) -> None:
        now = datetime.now(UTC)
        cal_read_raw = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt-1",
            read_at=now,
        )
        with pytest.raises(ExecutionContractTypeError, match="action_type must be an ActionType"):
            record_provider_result("not-an-action-type", cal_read_raw)  # type: ignore[arg-type]

    def test_exception_input_preserves_caller_action_type(self) -> None:
        exc = RuntimeError("Service unavailable")
        res = record_provider_result(ActionType.WEATHER_READ, exc)
        assert res.action_type == ActionType.WEATHER_READ
        assert res.success is False
        assert res.status_name == "RuntimeError"
        assert res.error_message == "Service unavailable"

    def test_dispatcher_rejects_unknown_result_type(self) -> None:
        with pytest.raises(ExecutionContractTypeError, match="Unsupported raw provider result"):
            record_provider_result(ActionType.CALENDAR_READ, "unknown string result")

    def test_no_evidence_or_verification_ownership(self) -> None:
        now = datetime.now(UTC)
        raw = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt-1",
            read_at=now,
        )
        res = record_provider_result(ActionType.CALENDAR_READ, raw)
        assert not hasattr(res, "evidence_id")
        assert not hasattr(res, "evidence_records")
        assert not hasattr(res, "is_verified")
        assert not hasattr(res, "is_ready")
