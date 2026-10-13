"""Adversarial validation tests for P-18.04: Runtime Budget & Rate Limits.

Governing Task: P-18.04 — Enforce runtime budget/rate limits
Acceptance Criteria:
- Public or unauthenticated requests cannot enable paid AWS execution.
- Explicit operator-controlled authorization remains mandatory for paid-capable paths.
- Missing, stale, inconsistent, or unverifiable budget/credit observations fail closed.
- Rate-limit exhaustion denies execution before paid operations or provider mutations.
- Existing persistent rate-limit handling remains atomic and correct under concurrency.
- Request retries, replay, process restarts, and concurrent callers cannot trivially bypass
  the effective budget/rate admission controls.
- An estimated internal cost ceiling must never be represented as a guaranteed AWS billing hard cap.
- No silent fallback from blocked LIVE execution to fixture execution.
- No bypass of mission authority, approvals, evidence, or verified-state boundaries.
- Zero paid execution activated by this test suite ($0.00 spend).
"""

from __future__ import annotations

import ast
import concurrent.futures
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from stilldone.endpoint_protection import (
    AdmissionReason,
    AdmissionStatus,
    BudgetSnapshot,
    CallerClass,
    EndpointAdmissionDecision,
    EndpointProtectionPolicy,
    EndpointProtectionTypeError,
    EndpointProtectionValueError,
    EndpointRequestAssessment,
    RateSnapshot,
    RequestExposureClass,
    evaluate_endpoint_admission,
)

# Reference timestamp in UTC
T_REF = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
T_START = T_REF
T_END = T_REF + timedelta(minutes=1)
T_MID = T_REF + timedelta(seconds=30)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a unique temporary SQLite database path."""
    return tmp_path / "rate_limits_test.sqlite"


@pytest.fixture
def base_policy() -> EndpointProtectionPolicy:
    """Standard baseline policy: live paid path disabled by default."""
    return EndpointProtectionPolicy(
        max_requests_per_window=5,
        max_paid_live_requests_per_window=2,
        internal_gross_ceiling=Decimal("10.00"),
        live_paid_path_enabled=False,
    )


@pytest.fixture
def paid_enabled_policy() -> EndpointProtectionPolicy:
    """Policy with live paid path explicitly enabled by operator."""
    return EndpointProtectionPolicy(
        max_requests_per_window=10,
        max_paid_live_requests_per_window=3,
        internal_gross_ceiling=Decimal("5.00"),
        live_paid_path_enabled=True,
    )


@pytest.fixture
def valid_budget_snapshot() -> BudgetSnapshot:
    """Valid, fresh budget snapshot with confirmed promotional credit."""
    return BudgetSnapshot(
        already_accounted_gross_cost=Decimal("0.50"),
        remaining_promotional_credit=Decimal("149.50"),
        credit_coverage_confirmed=True,
        observed_at=T_START,
        valid_until=T_END,
    )


# ===========================================================================
# 1. Public / Unauthenticated Callers Cannot Enable Paid AWS Execution
# ===========================================================================


class TestPublicUnauthenticatedPaidAccessBlock:
    """Verify that public or unauthenticated requests can never reach paid execution."""

    def test_public_untrusted_caller_with_paid_live_request_strictly_forbidden(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
        valid_budget_snapshot: BudgetSnapshot,
    ) -> None:
        """Even if operator enabled live paid path, PUBLIC_UNTRUSTED callers are denied."""
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
            cost_estimate=Decimal("0.000021"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=valid_budget_snapshot,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.PUBLIC_PAID_PATH_FORBIDDEN
        assert not decision.is_allowed
        assert decision.is_denied

    def test_spoofed_operator_class_in_headers_does_not_bypass_middleware(
        self,
        tmp_db: Path,
        base_policy: EndpointProtectionPolicy,
    ) -> None:
        """RateLimitMiddleware classifies all incoming untrusted requests as PUBLIC_UNTRUSTED."""
        from stilldone.mcp.rate_limit import RateLimitMiddleware, SqliteRateLimitStore

        store = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)
        downstream_called = False

        async def downstream_app(scope: Any, receive: Any, send: Any) -> None:
            nonlocal downstream_called
            downstream_called = True

        middleware = RateLimitMiddleware(
            app=downstream_app,
            store=store,
            policy=base_policy,
            clock=lambda: T_MID,
        )

        sent_messages: list[dict[str, Any]] = []

        async def mock_receive() -> Any:
            return {"type": "http.request"}

        async def mock_send(msg: Any) -> None:
            sent_messages.append(msg)

        # Craft request with adversarial headers attempting to claim operator status
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"x-caller-class", b"OPERATOR_CONTROLLED"),
                (b"x-exposure-class", b"PAID_CAPABLE_LIVE"),
            ],
        }

        import asyncio

        asyncio.run(middleware(scope, mock_receive, mock_send))

        # Request succeeds as NO_PAID_CAPABILITY general request, not paid capable
        assert downstream_called is True
        # Verify the consumption in store was strictly NO_PAID_CAPABILITY
        snap = store.get_snapshot(T_MID)
        assert snap.total_requests == 1
        assert snap.paid_live_requests == 0  # Zero paid capability consumed


# ===========================================================================
# 2. Operator Authorization Mandatory for Paid Paths
# ===========================================================================


class TestOperatorAuthorizationMandatory:
    """Verify that operator gate live_paid_path_enabled=False fails closed."""

    def test_live_paid_path_disabled_denies_even_operator_controlled_requests(
        self,
        base_policy: EndpointProtectionPolicy,
        valid_budget_snapshot: BudgetSnapshot,
    ) -> None:
        """When live_paid_path_enabled is False, even OPERATOR_CONTROLLED requests are denied."""
        assert base_policy.live_paid_path_enabled is False

        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.000021"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=base_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=valid_budget_snapshot,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.LIVE_PATH_DISABLED

    def test_no_paid_capability_unaffected_by_live_gate(
        self,
        base_policy: EndpointProtectionPolicy,
    ) -> None:
        """NO_PAID_CAPABILITY requests are permitted regardless of live_paid_path_enabled."""
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=base_policy,
            rate_snapshot=rate_snapshot,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.ALLOW
        assert decision.reason == AdmissionReason.ALLOWED


# ===========================================================================
# 3. Missing, Stale, Inconsistent Budget Truth Fails Closed
# ===========================================================================


class TestBudgetTruthFreshnessAndConsistency:
    """Verify all forms of invalid, stale, or unconfirmed budget truth fail closed."""

    def test_missing_budget_snapshot_fails_closed(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
    ) -> None:
        """None budget snapshot for PAID_CAPABLE_LIVE yields BUDGET_TRUTH_STALE."""
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.01"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=None,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.BUDGET_TRUTH_STALE

    def test_stale_budget_snapshot_past_valid_until_fails_closed(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
    ) -> None:
        """Budget snapshot expired (at >= valid_until) yields BUDGET_TRUTH_STALE."""
        stale_budget = BudgetSnapshot(
            already_accounted_gross_cost=Decimal("0.50"),
            remaining_promotional_credit=Decimal("149.50"),
            credit_coverage_confirmed=True,
            observed_at=T_START - timedelta(hours=2),
            valid_until=T_START - timedelta(hours=1),
        )
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.01"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=stale_budget,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.BUDGET_TRUTH_STALE

    def test_unconfirmed_credit_coverage_fails_closed(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
    ) -> None:
        """Credit coverage unconfirmed yields CREDIT_COVERAGE_UNCONFIRMED."""
        unconfirmed_budget = BudgetSnapshot(
            already_accounted_gross_cost=Decimal("0.50"),
            remaining_promotional_credit=Decimal("149.50"),
            credit_coverage_confirmed=False,
            observed_at=T_START,
            valid_until=T_END,
        )
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.01"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=unconfirmed_budget,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.CREDIT_COVERAGE_UNCONFIRMED

    def test_cost_estimate_exceeding_internal_ceiling_fails_closed(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
    ) -> None:
        """Incremental cost exceeding internal ceiling yields INTERNAL_BUDGET_EXCEEDED."""
        budget = BudgetSnapshot(
            already_accounted_gross_cost=Decimal("4.99"),
            remaining_promotional_credit=Decimal("100.00"),
            credit_coverage_confirmed=True,
            observed_at=T_START,
            valid_until=T_END,
        )
        # Ceiling is 5.00; 4.99 + 0.02 = 5.01 > 5.00
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.02"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=budget,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.INTERNAL_BUDGET_EXCEEDED

    def test_cost_estimate_exceeding_remaining_credit_fails_closed(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
    ) -> None:
        """Cost estimate exceeding credit yields INSUFFICIENT_OBSERVED_CREDIT."""
        budget = BudgetSnapshot(
            already_accounted_gross_cost=Decimal("0.10"),
            remaining_promotional_credit=Decimal("0.05"),  # only $0.05 left
            credit_coverage_confirmed=True,
            observed_at=T_START,
            valid_until=T_END,
        )
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.10"),  # $0.10 > $0.05
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=budget,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.DENY
        assert decision.reason == AdmissionReason.INSUFFICIENT_OBSERVED_CREDIT

    def test_float_or_negative_money_values_strictly_rejected(self) -> None:
        """Floating point and negative money types fail construction immediately."""
        with pytest.raises(EndpointProtectionTypeError):
            EndpointProtectionPolicy(
                max_requests_per_window=10,
                max_paid_live_requests_per_window=5,
                internal_gross_ceiling=10.0,  # type: ignore[arg-type]
            )

        with pytest.raises(EndpointProtectionValueError):
            EndpointProtectionPolicy(
                max_requests_per_window=10,
                max_paid_live_requests_per_window=5,
                internal_gross_ceiling=Decimal("-1.00"),
            )


# ===========================================================================
# 4. Rate-Limit Exhaustion Denies Execution Before Mutations
# ===========================================================================


class TestRateLimitExhaustionDeniesBeforeMutation:
    """Verify that rate exhaustion blocks requests before any downstream call or write."""

    def test_exhaustion_returns_429_without_invoking_downstream_handler(
        self,
        tmp_db: Path,
    ) -> None:
        """Once limit is reached, middleware sends 429 and never calls app."""
        from stilldone.mcp.rate_limit import RateLimitMiddleware, SqliteRateLimitStore

        policy = EndpointProtectionPolicy(
            max_requests_per_window=2,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        store = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)
        app_calls = 0

        async def downstream_app(scope: Any, receive: Any, send: Any) -> None:
            nonlocal app_calls
            app_calls += 1

        middleware = RateLimitMiddleware(
            app=downstream_app,
            store=store,
            policy=policy,
            clock=lambda: T_MID,
        )

        async def send_request() -> int:
            sent: list[dict[str, Any]] = []

            async def mock_receive() -> Any:
                return {"type": "http.request"}

            async def mock_send(msg: Any) -> None:
                sent.append(msg)

            scope = {"type": "http", "method": "GET", "path": "/mcp"}
            await middleware(scope, mock_receive, mock_send)
            status_msg = [m for m in sent if m.get("type") == "http.response.start"]
            return status_msg[0]["status"] if status_msg else 200

        import asyncio

        # Request 1: Allowed -> downstream app invoked
        s1 = asyncio.run(send_request())
        assert s1 == 200 or app_calls == 1

        # Request 2: Allowed -> downstream app invoked
        s2 = asyncio.run(send_request())
        assert s2 == 200 or app_calls == 2

        # Request 3: Denied -> 429 returned, downstream app NOT called
        s3 = asyncio.run(send_request())
        assert s3 == 429
        assert app_calls == 2  # Crucial: app was NOT called a 3rd time


# ===========================================================================
# 5. Atomic Concurrency Safety Under Multithreaded Contention
# ===========================================================================


class TestAtomicConcurrencySafety:
    """Verify that SQLite BEGIN IMMEDIATE prevents over-allocation under race conditions."""

    def test_multithreaded_race_cannot_exceed_limit(
        self,
        tmp_db: Path,
    ) -> None:
        """20 concurrent threads attempting to claim 5 slots: exactly 5 succeed, 15 fail."""
        from stilldone.mcp.rate_limit import SqliteRateLimitStore

        max_allowed = 5
        policy = EndpointProtectionPolicy(
            max_requests_per_window=max_allowed,
            max_paid_live_requests_per_window=2,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        store = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)

        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )

        def worker() -> AdmissionStatus:
            decision = store.check_and_consume(
                request=request,
                policy=policy,
                at=T_MID,
            )
            return decision.status

        # Execute 20 concurrent threads simultaneously
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(20)]
            results = [f.result() for f in futures]

        allowed_count = sum(1 for s in results if s == AdmissionStatus.ALLOW)
        denied_count = sum(1 for s in results if s == AdmissionStatus.DENY)

        assert allowed_count == max_allowed
        assert denied_count == 15

        # Check stored total requests in DB is exactly max_allowed
        snapshot = store.get_snapshot(T_MID)
        assert snapshot.total_requests == max_allowed


# ===========================================================================
# 6. Replay, Retry, and Process Restart Resilience
# ===========================================================================


class TestReplayAndRestartResilience:
    """Verify that store reconstruction and rapid replay cannot bypass limits."""

    def test_state_persists_across_process_restart_simulation(
        self,
        tmp_db: Path,
    ) -> None:
        """A new SqliteRateLimitStore pointing to the same file sees previous counts."""
        from stilldone.mcp.rate_limit import SqliteRateLimitStore

        policy = EndpointProtectionPolicy(
            max_requests_per_window=3,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )

        # Process 1 consumes 2 of 3 slots
        store_proc1 = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)
        d1 = store_proc1.check_and_consume(request, policy, T_MID)
        d2 = store_proc1.check_and_consume(request, policy, T_MID)
        assert d1.status == AdmissionStatus.ALLOW
        assert d2.status == AdmissionStatus.ALLOW

        # Process 1 terminates. Process 2 starts up with fresh instance on same DB
        store_proc2 = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)
        snap = store_proc2.get_snapshot(T_MID)
        assert snap.total_requests == 2

        # Process 2 consumes the 3rd slot
        d3 = store_proc2.check_and_consume(request, policy, T_MID)
        assert d3.status == AdmissionStatus.ALLOW

        # 4th request must be DENIED by Process 2
        d4 = store_proc2.check_and_consume(request, policy, T_MID)
        assert d4.status == AdmissionStatus.DENY
        assert d4.reason == AdmissionReason.RATE_LIMIT_EXCEEDED

    def test_rapid_replayed_requests_fail_closed_with_retry_after(
        self,
        tmp_db: Path,
    ) -> None:
        """Rapid retries beyond limit produce 429 with retry-after header."""
        from stilldone.mcp.rate_limit import RateLimitMiddleware, SqliteRateLimitStore

        policy = EndpointProtectionPolicy(
            max_requests_per_window=1,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        store = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)

        async def dummy_app(scope: Any, receive: Any, send: Any) -> None:
            pass

        middleware = RateLimitMiddleware(
            app=dummy_app,
            store=store,
            policy=policy,
            clock=lambda: T_MID,
        )

        import asyncio

        async def call() -> dict[str, Any]:
            sent: list[dict[str, Any]] = []

            async def mock_receive() -> Any:
                return {"type": "http.request"}

            async def send(msg: Any) -> None:
                sent.append(msg)

            await middleware({"type": "http", "method": "GET", "path": "/mcp"}, mock_receive, send)
            start_msg = [m for m in sent if m.get("type") == "http.response.start"]
            return start_msg[0] if start_msg else {}

        # 1st call admitted
        asyncio.run(call())

        # 2nd replayed call denied with 429 and retry-after header
        res2 = asyncio.run(call())
        assert res2["status"] == 429
        headers = dict(res2["headers"])
        assert b"retry-after" in headers
        retry_seconds = int(headers[b"retry-after"])
        assert retry_seconds > 0


# ===========================================================================
# 7. Internal Cost Ceiling Is Not an AWS Billing Hard Cap
# ===========================================================================


class TestCeilingTruthBoundary:
    """Verify that internal gross ceiling is software policy, never mislabeled as AWS hard cap."""

    def test_admission_decision_cannot_serve_as_billing_guarantee(self) -> None:
        """Contract invariant: EndpointAdmissionDecision confers zero spend or billing proof."""
        decision = EndpointAdmissionDecision(
            status=AdmissionStatus.ALLOW,
            reason=AdmissionReason.ALLOWED,
            evaluated_at=T_MID,
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
            cost_estimate=None,
        )
        assert decision.is_allowed is True
        # Decision has no attribute or method representing provider hard caps or actual billing
        assert not hasattr(decision, "aws_hard_cap_guaranteed")
        assert not hasattr(decision, "actual_spend_delta")
        assert not hasattr(decision, "promotional_credit_deducted")


# ===========================================================================
# 8. Zero Bypass of Mission Authority, Approvals, or Verified State
# ===========================================================================


class TestZeroAuthorityOrVerificationBypass:
    """Verify admission decision confers zero execution authority or verified state."""

    def test_admission_decision_contains_no_approval_grant_or_readiness(
        self,
        paid_enabled_policy: EndpointProtectionPolicy,
        valid_budget_snapshot: BudgetSnapshot,
    ) -> None:
        """An ALLOW admission decision confers zero authority and zero verified/ready state."""
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.000021"),
        )
        rate_snapshot = RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )

        decision = evaluate_endpoint_admission(
            request=request,
            policy=paid_enabled_policy,
            rate_snapshot=rate_snapshot,
            budget_snapshot=valid_budget_snapshot,
            at=T_MID,
        )

        assert decision.status == AdmissionStatus.ALLOW
        # Authority boundary check: Decision is NOT an ApprovalGrant
        assert not hasattr(decision, "approval_id")
        assert not hasattr(decision, "grant_token")
        assert not hasattr(decision, "state")
        assert not hasattr(decision, "is_verified")
        assert not hasattr(decision, "is_ready")


# ===========================================================================
# 9. Python -O Assertions-Disabled Boundary Verification
# ===========================================================================


class TestAssertionsDisabledBoundary:
    """Verify contracts and evaluators do not rely on Python assert statements."""

    def test_endpoint_protection_contracts_do_not_rely_on_assert(self) -> None:
        """Inspect endpoint_protection module to ensure validation uses explicit raise."""
        import stilldone.endpoint_protection as mod

        file_path = Path(mod.__file__)
        tree = ast.parse(file_path.read_text(encoding="utf-8"))

        # Find any Assert nodes in classes/functions
        assert_nodes: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                assert_nodes.append(node.lineno)

        # No assert statements in production module logic
        assert len(assert_nodes) == 0, f"Found assert statements at lines: {assert_nodes}"

    def test_mcp_rate_limit_module_does_not_rely_on_assert(self) -> None:
        """Inspect mcp.rate_limit module to ensure validation uses explicit raise."""
        import stilldone.mcp.rate_limit as mod

        file_path = Path(mod.__file__)
        tree = ast.parse(file_path.read_text(encoding="utf-8"))

        assert_nodes: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                assert_nodes.append(node.lineno)

        assert len(assert_nodes) == 0, f"Found assert statements at lines: {assert_nodes}"


# ===========================================================================
# 10. Runtime Admission Protection Truth & Capability Boundary
# ===========================================================================


class TestRuntimeAdmissionProtectionTruth:
    """Verify actual middleware boundary, safe exception handling, and non-paid MCP tool surface."""

    def test_unexpected_store_exception_fails_closed_without_unbound_body(
        self,
        tmp_db: Path,
        base_policy: EndpointProtectionPolicy,
    ) -> None:
        """Arbitrary non-RateLimitStoreError exceptions produce privacy-safe
        500 response without crashing.
        """
        import asyncio
        import json
        from unittest.mock import MagicMock

        from stilldone.mcp.rate_limit import RateLimitMiddleware, SqliteRateLimitStore

        store = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)
        # Force an unexpected exception (e.g. unexpected RuntimeError, sqlite3 error)
        store.check_and_consume = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("Internal SQLite disk crash /secret/path")
        )

        middleware = RateLimitMiddleware(
            app=MagicMock(),
            store=store,
            policy=base_policy,
            clock=lambda: T_MID,
        )

        sent_messages: list[dict[str, Any]] = []

        async def mock_receive() -> Any:
            return {"type": "http.request"}

        async def mock_send(message: Any) -> None:
            sent_messages.append(message)

        scope = {"type": "http", "method": "GET", "path": "/mcp"}
        # Must execute cleanly without UnboundLocalError
        asyncio.run(middleware(scope, mock_receive, mock_send))

        # Check HTTP 500 status
        start_msgs = [m for m in sent_messages if m.get("type") == "http.response.start"]
        assert len(start_msgs) == 1
        assert start_msgs[0]["status"] == 500

        # Check privacy-safe payload
        body_msgs = [m for m in sent_messages if m.get("type") == "http.response.body"]
        assert len(body_msgs) == 1
        body_data = json.loads(body_msgs[0]["body"].decode("utf-8"))
        assert body_data["error"] == "rate_limit_unavailable"
        assert body_data["description"] == "Rate limiting storage unavailable"
        # Crucial: no leaking of internal exception text or paths
        assert "Internal SQLite" not in body_msgs[0]["body"].decode("utf-8")
        assert "secret" not in body_msgs[0]["body"].decode("utf-8")

    def test_real_middleware_assessment_is_strictly_no_paid_capability(
        self,
        tmp_db: Path,
        base_policy: EndpointProtectionPolicy,
    ) -> None:
        """Confirm that public RateLimitMiddleware evaluates requests as NO_PAID_CAPABILITY."""
        import asyncio

        from stilldone.mcp.rate_limit import RateLimitMiddleware, SqliteRateLimitStore

        store = SqliteRateLimitStore(tmp_db, window_duration_seconds=60)
        captured_assessments: list[EndpointRequestAssessment] = []
        original_consume = store.check_and_consume

        def spy_consume(
            req: EndpointRequestAssessment,
            pol: EndpointProtectionPolicy,
            at: datetime,
        ) -> EndpointAdmissionDecision:
            captured_assessments.append(req)
            return original_consume(req, pol, at)

        store.check_and_consume = spy_consume  # type: ignore[assignment]

        async def dummy_app(scope: Any, receive: Any, send: Any) -> None:
            pass

        middleware = RateLimitMiddleware(
            app=dummy_app,
            store=store,
            policy=base_policy,
            clock=lambda: T_MID,
        )

        async def mock_receive() -> Any:
            return {"type": "http.request"}

        async def mock_send(message: Any) -> None:
            pass

        scope = {"type": "http", "method": "POST", "path": "/mcp"}
        asyncio.run(middleware(scope, mock_receive, mock_send))

        assert len(captured_assessments) == 1
        req = captured_assessments[0]
        # Verified capability boundary
        assert req.exposure_class == RequestExposureClass.NO_PAID_CAPABILITY
        assert req.caller_class == CallerClass.PUBLIC_UNTRUSTED
        assert req.cost_estimate is None

    def test_current_mcp_tools_do_not_invoke_paid_execution(self) -> None:
        """Confirm current MCP business tools (mission_start, mission_status)
        do not trigger paid calls.
        """
        from stilldone.application.ports.ledger_port import InMemoryNonDurableLedger
        from stilldone.domain.lifecycle import MissionState
        from stilldone.mcp.mission_start import (
            MISSION_START_TOOL_DESCRIPTION,
            create_mission_start_handler,
        )
        from stilldone.mcp.mission_status import (
            MISSION_STATUS_TOOL_DESCRIPTION,
            create_mission_status_handler,
        )

        # 1. Inspect tool contracts
        assert (
            "without executing, planning, or mutating external systems"
            in MISSION_START_TOOL_DESCRIPTION
        )
        assert (
            "without executing, mutating, approving, reconciling, verifying, or refreshing"
            in MISSION_STATUS_TOOL_DESCRIPTION
        )

        # 2. Execute mission_start: creates local DRAFT mission only (0 network/paid calls)
        from stilldone.domain.mission import MissionId

        ledger = InMemoryNonDurableLedger()
        start_handler = create_mission_start_handler(ledger)
        start_result = start_handler("Pack backpacks for school tomorrow morning")
        assert start_result.mission_id is not None
        assert start_result.state == MissionState.DRAFT.value
        created_record = ledger.get_mission(MissionId(start_result.mission_id))
        assert created_record.state == MissionState.DRAFT

        # 3. Execute mission_status: reads local ledger only (0 network/paid calls)
        status_handler = create_mission_status_handler(ledger)
        status_result = status_handler(created_record.mission_id.value)
        assert status_result.mission_id == created_record.mission_id.value
        assert status_result.state == MissionState.DRAFT.value
