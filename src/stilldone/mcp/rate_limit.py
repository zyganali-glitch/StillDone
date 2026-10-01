"""Persistent atomic rate-limit store and ASGI enforcement middleware for StillDone MCP.

Enforces provider-neutral admission semantics using the canonical P-04.06 contracts:
- EndpointProtectionPolicy
- RateSnapshot
- EndpointRequestAssessment
- EndpointAdmissionDecision
- evaluate_endpoint_admission

Runtime enforcement:
- ATOMIC READ -> EVALUATE -> CONDITIONAL CONSUME -> COMMIT inside SQLite BEGIN IMMEDIATE.
- Half-open window law: window_start <= at < window_end.
- Persistent counts preserved across store reconstruction.
- Zero sensitive data stored: stores strictly integer request counters per window.
- Fail closed: storage failure returns bounded HTTP 500 without leaking database internals.
- Exceeded limit: returns bounded HTTP 429 without invoking MCP tools or mutating ledger.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from starlette.types import ASGIApp, Receive, Scope, Send

from stilldone.endpoint_protection import (
    AdmissionReason,
    AdmissionStatus,
    CallerClass,
    EndpointAdmissionDecision,
    EndpointProtectionError,
    EndpointProtectionPolicy,
    EndpointRequestAssessment,
    RateSnapshot,
    RequestExposureClass,
    evaluate_endpoint_admission,
)

if TYPE_CHECKING:
    pass

DEFAULT_WINDOW_SECONDS: Final[int] = 60
DEFAULT_SQLITE_TIMEOUT: Final[float] = 30.0


class RateLimitStoreError(EndpointProtectionError):
    """Raised when the persistent rate store cannot initialize, read, or write safely."""


class SqliteRateLimitStore:
    """Small bounded persistent rate-limit store backed by stdlib SQLite.

    Guarantees:
    - Atomicity: Uses SQLite BEGIN IMMEDIATE to ensure atomic read-evaluate-increment
      with zero race window under concurrent requests.
    - Persistence: Fixed-window counts persist across server/store reconstruction.
    - Zero data leakage: Stores strictly (window_start, window_end, total_requests,
      paid_live_requests). Never stores tokens, intents, mission contracts, or external IDs.
    - Bounded scope: Single-instance judge-path control, not distributed DDoS infrastructure.
    - Half-open window: Preserves window_start <= at < window_end.
    - Fail-closed: Errors during database operations raise RateLimitStoreError and fail closed.
    """

    def __init__(
        self,
        db_path: str | Path,
        window_duration_seconds: int = DEFAULT_WINDOW_SECONDS,
        timeout: float = DEFAULT_SQLITE_TIMEOUT,
    ) -> None:
        if isinstance(window_duration_seconds, bool) or not isinstance(
            window_duration_seconds, int
        ):
            raise TypeError("window_duration_seconds must be an integer, not bool")
        if window_duration_seconds <= 0:
            raise ValueError("window_duration_seconds must be strictly positive")

        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
            raise TypeError("timeout must be a float or integer")
        if timeout <= 0:
            raise ValueError("timeout must be strictly positive")

        self._db_path = Path(db_path).resolve()
        self._window_duration_seconds = window_duration_seconds
        self._timeout = float(timeout)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def window_duration_seconds(self) -> int:
        return self._window_duration_seconds

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=self._timeout,
                isolation_level=None,
            )
            try:
                conn.execute(f"PRAGMA busy_timeout={int(self._timeout * 1000)};")
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.OperationalError:
                    pass
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rate_limit_windows (
                        window_start TEXT PRIMARY KEY,
                        window_end TEXT NOT NULL,
                        total_requests INTEGER NOT NULL,
                        paid_live_requests INTEGER NOT NULL
                    )
                    """
                )
            finally:
                conn.close()
        except Exception as e:
            raise RateLimitStoreError(f"Failed to initialize rate store: {type(e).__name__}") from e

    def compute_window(self, at: datetime) -> tuple[datetime, datetime]:
        """Compute half-open window [window_start, window_end) for timestamp `at`."""
        if not isinstance(at, datetime):
            raise TypeError("at must be a datetime instance")
        if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
            raise ValueError("at must be timezone-aware")

        at_utc = at.astimezone(UTC)
        epoch = math.floor(at_utc.timestamp())
        start_sec = (epoch // self._window_duration_seconds) * self._window_duration_seconds
        end_sec = start_sec + self._window_duration_seconds

        window_start = datetime.fromtimestamp(start_sec, tz=UTC)
        window_end = datetime.fromtimestamp(end_sec, tz=UTC)
        return window_start, window_end

    def check_and_consume(
        self,
        request: EndpointRequestAssessment,
        policy: EndpointProtectionPolicy,
        at: datetime,
        budget_snapshot: Any | None = None,
    ) -> EndpointAdmissionDecision:
        """Atomic read -> evaluate -> conditional consume -> commit."""
        window_start, window_end = self.compute_window(at)
        start_str = window_start.isoformat()
        end_str = window_end.isoformat()

        try:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=self._timeout,
                isolation_level=None,
            )
            conn.execute(f"PRAGMA busy_timeout={int(self._timeout * 1000)};")
        except Exception as e:
            raise RateLimitStoreError("Cannot connect to rate store") from e

        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "SELECT total_requests, paid_live_requests "
                "FROM rate_limit_windows WHERE window_start = ?",
                (start_str,),
            )
            row = cur.fetchone()
            if row is not None:
                total_requests = int(row[0])
                paid_live_requests = int(row[1])
            else:
                total_requests = 0
                paid_live_requests = 0

            rate_snapshot = RateSnapshot(
                window_start=window_start,
                window_end=window_end,
                total_requests=total_requests,
                paid_live_requests=paid_live_requests,
            )

            decision = evaluate_endpoint_admission(
                request=request,
                policy=policy,
                rate_snapshot=rate_snapshot,
                budget_snapshot=budget_snapshot,
                at=at,
            )

            if decision.status == AdmissionStatus.ALLOW:
                increment_paid = (
                    1 if request.exposure_class == RequestExposureClass.PAID_CAPABLE_LIVE else 0
                )
                if row is not None:
                    conn.execute(
                        """
                        UPDATE rate_limit_windows
                        SET total_requests = total_requests + 1,
                            paid_live_requests = paid_live_requests + ?
                        WHERE window_start = ?
                        """,
                        (increment_paid, start_str),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO rate_limit_windows
                        (window_start, window_end, total_requests, paid_live_requests)
                        VALUES (?, ?, 1, ?)
                        """,
                        (start_str, end_str, increment_paid),
                    )
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")

            return decision
        except EndpointProtectionError:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise RateLimitStoreError("Rate limit transaction failed") from e
        finally:
            conn.close()

    def get_snapshot(self, at: datetime) -> RateSnapshot:
        """Read snapshot for window containing `at` without mutating."""
        window_start, window_end = self.compute_window(at)
        start_str = window_start.isoformat()
        try:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=self._timeout,
                isolation_level=None,
            )
            try:
                conn.execute(f"PRAGMA busy_timeout={int(self._timeout * 1000)};")
                cur = conn.execute(
                    "SELECT total_requests, paid_live_requests "
                    "FROM rate_limit_windows WHERE window_start = ?",
                    (start_str,),
                )
                row = cur.fetchone()
                if row is not None:
                    return RateSnapshot(
                        window_start=window_start,
                        window_end=window_end,
                        total_requests=int(row[0]),
                        paid_live_requests=int(row[1]),
                    )
                return RateSnapshot(
                    window_start=window_start,
                    window_end=window_end,
                    total_requests=0,
                    paid_live_requests=0,
                )
            finally:
                conn.close()
        except Exception as e:
            raise RateLimitStoreError("Failed to read rate snapshot") from e

    def __repr__(self) -> str:
        return f"SqliteRateLimitStore(window_duration_seconds={self._window_duration_seconds})"


class RateLimitMiddleware:
    """ASGI middleware enforcing atomic rate limits before requests reach the MCP server.

    Security & Ordering Law:
    - Protects the MCP endpoint from exceeding policy limits.
    - Evaluates admission using pure P-04.06 evaluate_endpoint_admission.
    - If denied -> returns bounded HTTP 429 response immediately.
      The MCP tool handler is NOT invoked; ledger is NOT mutated.
    - If rate store fails -> returns bounded HTTP 500 response immediately.
      Fails closed without leaking SQLite path or database internals.
    - Current classification: RequestExposureClass.NO_PAID_CAPABILITY,
      CallerClass.PUBLIC_UNTRUSTED.
    """

    def __init__(
        self,
        app: ASGIApp,
        store: SqliteRateLimitStore,
        policy: EndpointProtectionPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.app = app
        self.store = store
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(UTC))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        at = self.clock()
        request_assessment = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )

        try:
            decision = await asyncio.to_thread(
                self.store.check_and_consume,
                request_assessment,
                self.policy,
                at,
            )
        except Exception as exc:
            if isinstance(exc, RateLimitStoreError) or type(exc).__name__ == "RateLimitStoreError":
                # Fail closed on storage error without leaking internals
                body = json.dumps(
                    {
                        "error": "rate_limit_unavailable",
                        "description": "Rate limiting storage unavailable",
                    }
                ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        if decision.status == AdmissionStatus.DENY:
            reason_code = (
                "rate_limit_exceeded"
                if decision.reason == AdmissionReason.RATE_LIMIT_EXCEEDED
                else decision.reason.value.lower()
            )
            _, window_end = self.store.compute_window(at)
            retry_after_seconds = max(1, int((window_end - at).total_seconds()))
            body = json.dumps(
                {
                    "error": reason_code,
                    "description": "Rate limit exceeded",
                    "retry_after_seconds": retry_after_seconds,
                }
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"retry-after", str(retry_after_seconds).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Admitted: proceed to underlying MCP application
        await self.app(scope, receive, send)
