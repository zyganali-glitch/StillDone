"""Tests for Google Calendar Independent Read-Back Verifier (P-06.03).

Validates:
- Independence law:
  - Verifier performs a distinct, fresh provider read via GoogleCalendarReadAdapter.
  - An update response payload CANNOT substitute for read-back evidence.
  - Executor/provider-write success alone is NOT proof of verification.
- Deterministic match:
  - Freshly read provider state exactly matching ExpectedCalendarState produces MATCH.
- Deterministic mismatch:
  - Mismatched start_time produces MISMATCH with explicit mismatch reason.
  - Mismatched summary produces MISMATCH with explicit mismatch reason.
  - Mismatched all_day produces MISMATCH with explicit mismatch reason.
- Not found & Provider error:
  - Nonexistent event produces NOT_FOUND.
  - Provider failure during read-back produces PROVIDER_ERROR.
- Zero mutation:
  - Verifier performs zero provider writes and zero ledger/mission mutations.
- Drift / Non-substitutability:
  - Simulated post-mutation external drift (event changed externally after write)
    causes read-back verifier to detect MISMATCH, proving write success cannot certify reality.
- Truth boundaries:
  - CalendarReadbackResult has zero VERIFIED / READY attributes.
  - Verifier cannot promote mission state to READY.
  - Zero live Google calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from stilldone.adapters.calendar import (
    CalendarApiError,
    CalendarReadbackStatus,
    CalendarUpdateStatus,
    ExpectedCalendarState,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarReadbackVerifier,
    GoogleCalendarUpdateAdapter,
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

DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_TASKLIST_ID = "MDExMTI0ZGVtbw"
VALID_EVENT_ID = "evt_leave_for_school_001"
INITIAL_START = "2026-10-03T07:45:00+03:00"
UPDATED_START = "2026-10-03T07:30:00+03:00"


def _make_valid_approval(action: ActionContract) -> ApprovalGrant:
    now = datetime.now(tz=UTC)
    return ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id=DEMO_TASKLIST_ID,
    )


@pytest.fixture
def fake_transport() -> FakeGoogleCalendarTransport:
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=VALID_EVENT_ID,
        summary="Leave for school",
        start_time=INITIAL_START,
        all_day=False,
        etag='"etag_seed_1"',
    )
    return transport


@pytest.fixture
def read_adapter(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarReadAdapter:
    return GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)


@pytest.fixture
def update_adapter(
    demo_scope: DemoResourceScope, fake_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarUpdateAdapter:
    return GoogleCalendarUpdateAdapter(scope=demo_scope, transport=fake_transport)


@pytest.fixture
def verifier(read_adapter: GoogleCalendarReadAdapter) -> GoogleCalendarReadbackVerifier:
    return GoogleCalendarReadbackVerifier(read_adapter=read_adapter)


def _target_identity(event_id: str = VALID_EVENT_ID) -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id=event_id,
        parent_id=DEMO_CALENDAR_ID,
    )


# ===========================================================================
# 1. Distinct Provider Read & Independence Law
# ===========================================================================


class TestIndependenceLaw:
    def test_verifier_initiates_distinct_provider_read(
        self,
        verifier: GoogleCalendarReadbackVerifier,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(
            summary="Leave for school",
            start_time=INITIAL_START,
        )

        assert fake_transport.reads_count == 0
        result = verifier.verify(target, expected)

        assert fake_transport.reads_count == 1
        assert result.status == CalendarReadbackStatus.MATCH
        assert result.is_match is True

    def test_update_response_cannot_substitute_for_read_back(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        verifier: GoogleCalendarReadbackVerifier,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_UPDATE,
            target=_target_identity(),
            parameters={"start_time": UPDATED_START},
        )
        approval = _make_valid_approval(action)

        # 1. Perform update: writes_performed=1
        update_result = update_adapter.update_event(action, approval=approval)
        assert update_result.status == CalendarUpdateStatus.UPDATED
        initial_reads = fake_transport.reads_count
        initial_writes = fake_transport.writes_count

        # 2. Attempt to verify: verifier must NOT reuse update_result, it must issue a fresh read!
        expected = ExpectedCalendarState(start_time=UPDATED_START)
        readback_result = verifier.verify(action, expected)

        # Proves a separate read occurred after the update
        assert fake_transport.reads_count == initial_reads + 1
        # Proves verifier performed ZERO writes
        assert fake_transport.writes_count == initial_writes

        assert readback_result.status == CalendarReadbackStatus.MATCH
        assert readback_result.is_match is True


# ===========================================================================
# 2. Deterministic State Evaluation (Match & Mismatches)
# ===========================================================================


class TestDeterministicEvaluation:
    def test_exact_expected_state_produces_match(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(
            summary="Leave for school",
            start_time=INITIAL_START,
            all_day=False,
        )
        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MATCH
        assert result.is_match is True
        assert len(result.mismatches) == 0
        assert result.observation is not None
        assert result.observation.summary == "Leave for school"

    def test_mismatched_start_time_produces_mismatch(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(start_time="2026-10-03T09:00:00+03:00")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MISMATCH
        assert result.is_match is False
        assert result.mismatches == ("start_time mismatch",)

    def test_mismatched_summary_produces_mismatch(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(summary="Arrive at school")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MISMATCH
        assert result.is_match is False
        assert result.mismatches == ("summary mismatch",)

    def test_mismatched_all_day_produces_mismatch(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(all_day=True)

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MISMATCH
        assert result.is_match is False
        assert result.mismatches == ("all_day mismatch",)

    def test_expected_state_must_have_at_least_one_field(self) -> None:
        with pytest.raises(ValueError, match="requires at least one expected field"):
            ExpectedCalendarState()


# ===========================================================================
# 3. Not Found, Missing Event & Provider Failure
# ===========================================================================


class TestNotFoundAndProviderFailure:
    def test_nonexistent_event_produces_not_found(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity(event_id="missing_event_999")
        expected = ExpectedCalendarState(summary="Leave for school")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.NOT_FOUND
        assert result.is_match is False
        assert result.observation is None
        assert result.error_message is not None

    def test_provider_read_failure_produces_provider_error(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        broken_transport = MagicMock()
        broken_transport.get_event.side_effect = CalendarApiError("Google Calendar API down 503")
        broken_read_adapter = GoogleCalendarReadAdapter(
            scope=demo_scope, transport=broken_transport
        )
        verifier = GoogleCalendarReadbackVerifier(read_adapter=broken_read_adapter)

        target = _target_identity()
        expected = ExpectedCalendarState(summary="Leave for school")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.PROVIDER_ERROR
        assert result.is_match is False
        assert result.observation is None
        assert "503" in (result.error_message or "")


# ===========================================================================
# 4. Executor Success with Read-back Mismatch (Drift / Contradiction)
# ===========================================================================


class TestWriteSuccessWithReadbackMismatch:
    def test_external_drift_after_write_detected_as_mismatch(
        self,
        update_adapter: GoogleCalendarUpdateAdapter,
        verifier: GoogleCalendarReadbackVerifier,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Prove that external drift after write causes independent read-back to fail."""
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_UPDATE,
            target=_target_identity(),
            parameters={"start_time": UPDATED_START},
        )
        approval = _make_valid_approval(action)

        # 1. Update succeeds
        update_res = update_adapter.update_event(action, approval=approval)
        assert update_res.status == CalendarUpdateStatus.UPDATED
        assert update_res.writes_performed == 1

        # 2. External party drifts the event back to 08:30 directly in Google Calendar!
        drifted_raw = fake_transport._events[(DEMO_CALENDAR_ID, VALID_EVENT_ID)]
        drifted_raw["start"] = {"dateTime": "2026-10-03T08:30:00+03:00"}
        drifted_raw["etag"] = '"etag_drifted_by_operator"'

        # 3. Independent read-back is conducted with expected start_time = UPDATED_START (07:30)
        expected = ExpectedCalendarState(start_time=UPDATED_START)
        readback_res = verifier.verify(action, expected)

        # 4. Read-back MUST report MISMATCH, not match! Write success alone was not proof!
        assert readback_res.status == CalendarReadbackStatus.MISMATCH
        assert readback_res.is_match is False
        assert readback_res.mismatches == ("start_time mismatch",)


# ===========================================================================
# 5. Zero Mutation & Truth Boundaries
# ===========================================================================


class TestVerifierTruthBoundaries:
    def test_verifier_performs_zero_writes(
        self,
        verifier: GoogleCalendarReadbackVerifier,
        fake_transport: FakeGoogleCalendarTransport,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(summary="Leave for school")

        assert fake_transport.writes_count == 0
        verifier.verify(target, expected)
        assert fake_transport.writes_count == 0

    def test_no_verified_or_ready_attributes_on_readback_result(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(summary="Leave for school")
        result = verifier.verify(target, expected)

        attrs = dir(result)
        for forbidden in ("verified", "ready", "is_verified", "is_ready"):
            assert forbidden not in attrs, (
                f"Forbidden attribute {forbidden} found on CalendarReadbackResult"
            )

    def test_readback_result_repr_masks_event_id(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        target = _target_identity()
        expected = ExpectedCalendarState(summary="Leave for school")
        result = verifier.verify(target, expected)

        res_repr = repr(result)
        res_str = str(result)

        assert VALID_EVENT_ID not in res_repr
        assert VALID_EVENT_ID not in res_str


# ===========================================================================
# 6. ExpectedCalendarState Masking (Defect 2)
# ===========================================================================


class TestExpectedCalendarStateMasking:
    def test_expected_calendar_state_repr_and_str_mask_private_values(self) -> None:
        state = ExpectedCalendarState(
            summary="CONFIDENTIAL_LEAVE_FOR_SCHOOL",
            start_time="2026-10-03T07:45:00+03:00",
            all_day=False,
        )
        rep = repr(state)
        s = str(state)

        # Private values must NEVER appear
        assert "CONFIDENTIAL_LEAVE_FOR_SCHOOL" not in rep
        assert "CONFIDENTIAL_LEAVE_FOR_SCHOOL" not in s
        assert "2026-10-03T07:45:00+03:00" not in rep
        assert "2026-10-03T07:45:00+03:00" not in s

        # Boolean presence flags are present
        assert "has_summary=True" in rep
        assert "has_start_time=True" in rep
        assert "has_all_day=True" in rep
        assert rep == s

    def test_expected_calendar_state_repr_partial_fields(self) -> None:
        state = ExpectedCalendarState(summary="SECRET")
        assert (
            repr(state)
            == "ExpectedCalendarState(has_summary=True, has_start_time=False, has_all_day=False)"
        )

        state2 = ExpectedCalendarState(start_time="2026-10-03T07:45:00+03:00")
        assert (
            repr(state2)
            == "ExpectedCalendarState(has_summary=False, has_start_time=True, has_all_day=False)"
        )

        state3 = ExpectedCalendarState(all_day=True)
        assert (
            repr(state3)
            == "ExpectedCalendarState(has_summary=False, has_start_time=False, has_all_day=True)"
        )


# ===========================================================================
# 7. Verification Timestamp Semantics (Defect 3)
# ===========================================================================


class TestVerificationTimestampSemantics:
    def test_verified_at_occurs_after_provider_read_on_match(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        t_before = datetime.now(tz=UTC)
        target = _target_identity()
        expected = ExpectedCalendarState(summary="Leave for school")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MATCH
        assert result.observation is not None
        assert result.verified_at >= t_before
        assert result.verified_at >= result.observation.observed_at
        assert result.verified_at <= datetime.now(tz=UTC)

    def test_verified_at_occurs_after_provider_read_on_mismatch(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        t_before = datetime.now(tz=UTC)
        target = _target_identity()
        expected = ExpectedCalendarState(summary="Different summary")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MISMATCH
        assert result.observation is not None
        assert result.verified_at >= t_before
        assert result.verified_at >= result.observation.observed_at
        assert result.verified_at <= datetime.now(tz=UTC)

    def test_verified_at_occurs_after_provider_read_on_not_found(
        self,
        verifier: GoogleCalendarReadbackVerifier,
    ) -> None:
        t_before = datetime.now(tz=UTC)
        target = _target_identity(event_id="nonexistent_evt")
        expected = ExpectedCalendarState(summary="Leave for school")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.NOT_FOUND
        assert result.verified_at >= t_before
        assert result.verified_at <= datetime.now(tz=UTC)

    def test_verified_at_occurs_after_provider_read_on_provider_error(
        self,
        demo_scope: DemoResourceScope,
    ) -> None:
        t_before = datetime.now(tz=UTC)
        broken_transport = MagicMock()
        broken_transport.get_event.side_effect = CalendarApiError("Google Calendar API down 503")
        broken_read_adapter = GoogleCalendarReadAdapter(
            scope=demo_scope, transport=broken_transport
        )
        verifier = GoogleCalendarReadbackVerifier(read_adapter=broken_read_adapter)

        target = _target_identity()
        expected = ExpectedCalendarState(summary="Leave for school")

        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.PROVIDER_ERROR
        assert result.verified_at >= t_before
        assert result.verified_at <= datetime.now(tz=UTC)


# ===========================================================================
# 8. Adversarial Privacy & Hostile Sentinel Coverage
# ===========================================================================


SENTINEL_CALENDAR_ID = "c_secret_demo_cal_xyz_777@group.calendar.google.com"
SENTINEL_EVENT_ID = "evt_confidential_999"
SENTINEL_EXPECTED_SUMMARY = "TOP_SECRET_BOARD_MEETING_EXPECTED"
SENTINEL_OBSERVED_SUMMARY = "HIGHLY_CONFIDENTIAL_DOCTOR_APPOINTMENT_OBSERVED"
SENTINEL_EXPECTED_START = "2026-10-03T11:22:33+03:00"
SENTINEL_OBSERVED_START = "2026-10-03T14:55:00+03:00"
SENTINEL_ACCESS_TOKEN = "ya29.a0AfH6SMD_HOSTILE_BEARER_TOKEN_SENTINEL_SECRET"
SENTINEL_PROVIDER_URL = (
    "https://www.googleapis.com/calendar/v3/calendars/secret/events/confidential"
)

HOSTILE_SENTINELS = (
    SENTINEL_CALENDAR_ID,
    SENTINEL_EVENT_ID,
    SENTINEL_EXPECTED_SUMMARY,
    SENTINEL_OBSERVED_SUMMARY,
    SENTINEL_EXPECTED_START,
    SENTINEL_OBSERVED_START,
    SENTINEL_ACCESS_TOKEN,
    SENTINEL_PROVIDER_URL,
)


class TestAdversarialPrivacySentinels:
    def test_mismatch_zero_sentinel_leakage(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Prove zero sentinel leakage through mismatches, repr, str, and logs in mismatch."""
        scope = DemoResourceScope(
            calendar_id=SENTINEL_CALENDAR_ID,
            task_list_id=DEMO_TASKLIST_ID,
        )
        transport = FakeGoogleCalendarTransport()
        transport.seed_event(
            calendar_id=SENTINEL_CALENDAR_ID,
            event_id=SENTINEL_EVENT_ID,
            summary=SENTINEL_OBSERVED_SUMMARY,
            start_time=SENTINEL_OBSERVED_START,
            all_day=False,
            etag='"etag_sentinel_1"',
        )
        read_adapter = GoogleCalendarReadAdapter(scope=scope, transport=transport)
        verifier = GoogleCalendarReadbackVerifier(read_adapter=read_adapter)

        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=SENTINEL_EVENT_ID,
            parent_id=SENTINEL_CALENDAR_ID,
        )
        expected = ExpectedCalendarState(
            summary=SENTINEL_EXPECTED_SUMMARY,
            start_time=SENTINEL_EXPECTED_START,
        )

        caplog.clear()
        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.MISMATCH
        assert result.is_match is False
        assert result.mismatches == ("summary mismatch", "start_time mismatch")

        # 1. Surface: mismatches tuple/list
        for m in result.mismatches:
            for sentinel in HOSTILE_SENTINELS:
                assert sentinel not in m, f"Sentinel {sentinel} leaked in mismatch: {m}"

        # 2. Surface: repr(result) and str(result)
        res_repr = repr(result)
        res_str = str(result)
        for sentinel in HOSTILE_SENTINELS:
            assert sentinel not in res_repr, f"Sentinel {sentinel} leaked in result repr"
            assert sentinel not in res_str, f"Sentinel {sentinel} leaked in result str"

        # 3. Surface: repr(result.expected) and str(result.expected)
        exp_repr = repr(result.expected)
        exp_str = str(result.expected)
        for sentinel in HOSTILE_SENTINELS:
            assert sentinel not in exp_repr, f"Sentinel {sentinel} leaked in expected repr"
            assert sentinel not in exp_str, f"Sentinel {sentinel} leaked in expected str"

        # 4. Surface: captured logs
        for sentinel in HOSTILE_SENTINELS:
            assert sentinel not in caplog.text, f"Sentinel {sentinel} leaked in logs"

    def test_not_found_zero_sentinel_leakage(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Prove zero sentinel leakage through NOT_FOUND error message and repr/str."""
        scope = DemoResourceScope(
            calendar_id=SENTINEL_CALENDAR_ID,
            task_list_id=DEMO_TASKLIST_ID,
        )
        transport = FakeGoogleCalendarTransport()
        read_adapter = GoogleCalendarReadAdapter(scope=scope, transport=transport)
        verifier = GoogleCalendarReadbackVerifier(read_adapter=read_adapter)

        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=SENTINEL_EVENT_ID,
            parent_id=SENTINEL_CALENDAR_ID,
        )
        expected = ExpectedCalendarState(
            summary=SENTINEL_EXPECTED_SUMMARY,
            start_time=SENTINEL_EXPECTED_START,
        )

        caplog.clear()
        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.NOT_FOUND
        for sentinel in HOSTILE_SENTINELS:
            assert sentinel not in (result.error_message or "")
            assert sentinel not in repr(result)
            assert sentinel not in str(result)
            assert sentinel not in repr(result.expected)
            assert sentinel not in str(result.expected)
            assert sentinel not in caplog.text

    def test_hostile_provider_error_zero_sentinel_leakage(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Prove raw hostile provider exception containing tokens/URLs/IDs is sanitized."""
        scope = DemoResourceScope(
            calendar_id=SENTINEL_CALENDAR_ID,
            task_list_id=DEMO_TASKLIST_ID,
        )
        raw_hostile_exception = CalendarApiError(
            f"CRITICAL: Failed at {SENTINEL_PROVIDER_URL} with auth {SENTINEL_ACCESS_TOKEN} "
            f"for {SENTINEL_CALENDAR_ID}/{SENTINEL_EVENT_ID} - private summary: "
            f"{SENTINEL_OBSERVED_SUMMARY} at {SENTINEL_OBSERVED_START} (status 500)",
            status_code=500,
        )
        hostile_transport = MagicMock()
        hostile_transport.get_event.side_effect = raw_hostile_exception
        read_adapter = GoogleCalendarReadAdapter(scope=scope, transport=hostile_transport)
        verifier = GoogleCalendarReadbackVerifier(read_adapter=read_adapter)

        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=SENTINEL_EVENT_ID,
            parent_id=SENTINEL_CALENDAR_ID,
        )
        expected = ExpectedCalendarState(
            summary=SENTINEL_EXPECTED_SUMMARY,
            start_time=SENTINEL_EXPECTED_START,
        )

        caplog.clear()
        result = verifier.verify(target, expected)

        assert result.status == CalendarReadbackStatus.PROVIDER_ERROR
        assert result.error_message is not None
        assert "status 500" in result.error_message

        # Assert zero sentinel leakage across all public surfaces
        for sentinel in HOSTILE_SENTINELS:
            assert sentinel not in result.error_message, (
                f"Sentinel {sentinel} leaked in error_message: {result.error_message}"
            )
            assert sentinel not in repr(result), f"Sentinel {sentinel} leaked in repr(result)"
            assert sentinel not in str(result), f"Sentinel {sentinel} leaked in str(result)"
            assert sentinel not in repr(result.expected), (
                f"Sentinel {sentinel} leaked in repr(expected)"
            )
            assert sentinel not in str(result.expected), (
                f"Sentinel {sentinel} leaked in str(expected)"
            )
            assert sentinel not in caplog.text, f"Sentinel {sentinel} leaked in log output"
