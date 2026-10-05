"""Execution attempts and provider-result recording.

Phase P-08.04:
Reuses canonical ExecutionAttempt, AttemptId, and IdempotencyKey.
Records bounded provider-result facts separately from EvidenceRecord.

Laws:
- Single attempt per action (attempt_number starts at 1; no retry loop in P-08).
- Canonical runtime-owned IdempotencyKey bound per mutation lineage.
- Provider results preserve response classification without allowing provider prose
  to create verification truth (HTTP success != VERIFIED / READY).
- Provider errors are sanitized with redact_text to prevent credential/PII leaks.
- Separated from EvidenceRecord and verification predicates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from stilldone.adapters.calendar import (
    CalendarReadResult,
    CalendarReadStatus,
    CalendarUpdateResult,
    CalendarUpdateStatus,
)
from stilldone.adapters.tasks import (
    TaskCreateResult,
    TaskCreateStatus,
    TaskReadResult,
    TaskReadStatus,
)
from stilldone.adapters.weather import (
    WeatherReadResult,
    WeatherReadStatus,
)
from stilldone.domain.action import ActionId, ActionType
from stilldone.domain.execution import AttemptId, ExecutionAttempt, IdempotencyKey
from stilldone.execution.contracts import (
    ExecutionContractTypeError,
    ExecutionContractValueError,
    ExecutionLineageError,
)
from stilldone.execution.state import ProviderExecutionResult
from stilldone.redaction import redact_text


def create_execution_attempt(
    action_id: ActionId,
    *,
    idempotency_key: IdempotencyKey | None = None,
    attempt_number: int = 1,
    started_at: datetime | None = None,
    attempt_id: AttemptId | None = None,
) -> ExecutionAttempt:
    """Create a runtime-owned ExecutionAttempt for an action.

    Args:
        action_id: Canonical ActionId.
        idempotency_key: Runtime-owned IdempotencyKey (generated if None).
        attempt_number: 1-based attempt number (strictly 1 in P-08; no retry loops).
        started_at: Timestamp when attempt started (defaults to now UTC).
        attempt_id: Canonical AttemptId (generated if None).

    Returns:
        Canonical ExecutionAttempt.

    Raises:
        ExecutionContractTypeError: If action_id is not an ActionId or attempt_number is not an int.
        ExecutionContractValueError: If attempt_number != 1.
    """
    if not isinstance(action_id, ActionId):
        raise ExecutionContractTypeError(
            f"action_id must be an ActionId, got {type(action_id).__name__}"
        )
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise ExecutionContractTypeError(
            f"attempt_number must be an int, got {type(attempt_number).__name__}"
        )
    if attempt_number != 1:
        raise ExecutionContractValueError(
            f"P-08 execution attempts only allow attempt_number=1, got {attempt_number}"
        )

    ikey = idempotency_key or IdempotencyKey.generate()
    now = started_at or datetime.now(UTC)

    return ExecutionAttempt.create(
        action_id=action_id,
        idempotency_key=ikey,
        attempt_number=attempt_number,
        started_at=now,
        attempt_id=attempt_id,
    )


def record_calendar_read_result(result: CalendarReadResult) -> ProviderExecutionResult:
    """Record bounded provider facts from CalendarReadResult."""
    if not isinstance(result, CalendarReadResult):
        raise ExecutionContractTypeError("result must be a CalendarReadResult")

    success = result.status == CalendarReadStatus.SUCCESS
    err = redact_text(result.error_message) if result.error_message else None
    details: dict[str, Any] = {}
    if result.observation is not None:
        details["etag_present"] = result.observation.etag is not None
        details["has_summary"] = bool(result.observation.summary)
        details["all_day"] = result.observation.all_day

    return ProviderExecutionResult(
        action_type=ActionType.CALENDAR_READ,
        success=success,
        status_name=result.status.value,
        writes_performed=0,
        captured_at=result.read_at,
        details=details,
        error_message=err,
    )


def record_calendar_update_result(result: CalendarUpdateResult) -> ProviderExecutionResult:
    """Record bounded provider facts from CalendarUpdateResult."""
    if not isinstance(result, CalendarUpdateResult):
        raise ExecutionContractTypeError("result must be a CalendarUpdateResult")

    success = result.status == CalendarUpdateStatus.UPDATED
    err = redact_text(result.error_message) if result.error_message else None
    details: dict[str, Any] = {
        "writes_performed": result.writes_performed,
    }

    return ProviderExecutionResult(
        action_type=ActionType.CALENDAR_UPDATE,
        success=success,
        status_name=result.status.value,
        writes_performed=result.writes_performed,
        captured_at=result.updated_at,
        details=details,
        error_message=err,
    )


def record_task_read_result(result: TaskReadResult) -> ProviderExecutionResult:
    """Record bounded provider facts from TaskReadResult."""
    if not isinstance(result, TaskReadResult):
        raise ExecutionContractTypeError("result must be a TaskReadResult")

    success = result.status == TaskReadStatus.MATCH
    err = redact_text(result.error_message) if result.error_message else None
    details: dict[str, Any] = {}
    if result.observation is not None:
        details["has_title"] = bool(result.observation.title)
        details["has_due"] = result.observation.due is not None

    return ProviderExecutionResult(
        action_type=ActionType.TASK_READ,
        success=success,
        status_name=result.status.value,
        writes_performed=0,
        captured_at=result.observed_at,
        details=details,
        error_message=err,
    )


def record_task_create_result(result: TaskCreateResult) -> ProviderExecutionResult:
    """Record bounded provider facts from TaskCreateResult."""
    if not isinstance(result, TaskCreateResult):
        raise ExecutionContractTypeError("result must be a TaskCreateResult")

    success = result.status == TaskCreateStatus.CREATED
    err = redact_text(result.error_message) if result.error_message else None
    details: dict[str, Any] = {
        "task_id_present": result.task_id is not None,
    }

    return ProviderExecutionResult(
        action_type=ActionType.TASK_CREATE,
        success=success,
        status_name=result.status.value,
        writes_performed=result.writes_performed,
        captured_at=result.created_at,
        details=details,
        error_message=err,
    )


def record_weather_read_result(result: WeatherReadResult) -> ProviderExecutionResult:
    """Record bounded provider facts from WeatherReadResult."""
    if not isinstance(result, WeatherReadResult):
        raise ExecutionContractTypeError("result must be a WeatherReadResult")

    success = result.status == WeatherReadStatus.MATCH
    err = redact_text(result.error_message) if result.error_message else None
    details: dict[str, Any] = {}
    if result.observation is not None:
        details["provider"] = result.observation.attribution.provider
        details["license"] = result.observation.attribution.license

    return ProviderExecutionResult(
        action_type=ActionType.WEATHER_READ,
        success=success,
        status_name=result.status.value,
        writes_performed=0,
        captured_at=result.observed_at,
        details=details,
        error_message=err,
    )


def record_provider_exception(
    action_type: ActionType,
    exc: Exception,
) -> ProviderExecutionResult:
    """Record a caught provider exception as a sanitized ProviderExecutionResult."""
    if not isinstance(action_type, ActionType):
        raise ExecutionContractTypeError("action_type must be an ActionType")
    if not isinstance(exc, Exception):
        raise ExecutionContractTypeError("exc must be an Exception instance")

    sanitized_err = redact_text(str(exc))
    return ProviderExecutionResult(
        action_type=action_type,
        success=False,
        status_name=type(exc).__name__,
        writes_performed=0,
        captured_at=datetime.now(UTC),
        details={"exception_type": type(exc).__name__},
        error_message=sanitized_err,
    )


def record_provider_result(
    action_type: ActionType,
    raw_result: Any,
) -> ProviderExecutionResult:
    """Generic dispatcher recording a provider result into a canonical ProviderExecutionResult.

    Fails closed on mismatched action types or unsupported result types.
    """
    if not isinstance(action_type, ActionType):
        raise ExecutionContractTypeError(
            f"action_type must be an ActionType, got {type(action_type).__name__}"
        )

    if isinstance(raw_result, Exception):
        return record_provider_exception(action_type, raw_result)

    if isinstance(raw_result, CalendarReadResult):
        if action_type != ActionType.CALENDAR_READ:
            raise ExecutionLineageError(
                f"CalendarReadResult does not match action_type {action_type.value}"
            )
        return record_calendar_read_result(raw_result)

    if isinstance(raw_result, CalendarUpdateResult):
        if action_type != ActionType.CALENDAR_UPDATE:
            raise ExecutionLineageError(
                f"CalendarUpdateResult does not match action_type {action_type.value}"
            )
        return record_calendar_update_result(raw_result)

    if isinstance(raw_result, TaskReadResult):
        if action_type != ActionType.TASK_READ:
            raise ExecutionLineageError(
                f"TaskReadResult does not match action_type {action_type.value}"
            )
        return record_task_read_result(raw_result)

    if isinstance(raw_result, TaskCreateResult):
        if action_type != ActionType.TASK_CREATE:
            raise ExecutionLineageError(
                f"TaskCreateResult does not match action_type {action_type.value}"
            )
        return record_task_create_result(raw_result)

    if isinstance(raw_result, WeatherReadResult):
        if action_type != ActionType.WEATHER_READ:
            raise ExecutionLineageError(
                f"WeatherReadResult does not match action_type {action_type.value}"
            )
        return record_weather_read_result(raw_result)

    raise ExecutionContractTypeError(
        f"Unsupported raw provider result type: {type(raw_result).__name__}"
    )
