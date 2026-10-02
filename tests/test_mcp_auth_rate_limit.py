"""Tests for StillDone MCP Authentication and Rate-Limit Boundary (Phase P-05.05).

Covers all 30 required specifications and the real loopback cross-boundary proof:
- OAuth Resource Server boundary and configuration
- Alexa+ 401 compatibility (suppressing WWW-Authenticate on 401 only)
- RFC 9728 Protected Resource Metadata (PRM) endpoint verification
- Bearer token authentication enforcement (header-only, sentinel safety)
- Scope and RFC 8707 resource verification
- Atomic SQLite rate limit store and concurrency safety (BEGIN IMMEDIATE)
- Half-open window rollover semantics
- Quota isolation: /health, /ready, and PRM do not consume quota
- Fail-closed storage behavior
- Real loopback Streamable HTTP cross-boundary integration
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from stilldone.application.ports.ledger_port import InMemoryNonDurableLedger
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.endpoint_protection import (
    CallerClass,
    EndpointAdmissionDecision,
    EndpointProtectionPolicy,
    EndpointRequestAssessment,
    RequestExposureClass,
)

if TYPE_CHECKING:
    from stilldone.mcp.auth import MCPAuthConfig, SyntheticTokenVerifier


@pytest.fixture(autouse=True, scope="module")
def _cleanup_mcp_sys_modules() -> Generator[None, None, None]:
    """Module-level cleanup to keep sys.modules pure after MCP server tests finish."""
    yield
    mcp_keys = [
        k
        for k in list(sys.modules.keys())
        if k == "mcp"
        or k.startswith("mcp.")
        or k.startswith("mcp_")
        or k.startswith("stilldone.mcp")
        or k == "httpx"
        or k.startswith("httpx.")
        or k.startswith("httpx2")
    ]
    for k in mcp_keys:
        sys.modules.pop(k, None)


SAMPLE_ISSUER_URL = "https://auth.example.com"
SAMPLE_RESOURCE_URL = "http://127.0.0.1:8000/mcp"
SAMPLE_SCOPE = "stilldone:mcp"
SENTINEL_TOKEN = "sentinel-super-secret-token-xyz-987"


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def auth_config() -> MCPAuthConfig:
    from stilldone.mcp.auth import MCPAuthConfig

    return MCPAuthConfig(
        issuer_url=SAMPLE_ISSUER_URL,
        resource_server_url=SAMPLE_RESOURCE_URL,
        required_scopes=(SAMPLE_SCOPE,),
        validate_token_resource=True,
        alexa_profile=True,
    )


@pytest.fixture
def rate_policy() -> EndpointProtectionPolicy:
    return EndpointProtectionPolicy(
        max_requests_per_window=3,
        max_paid_live_requests_per_window=1,
        internal_gross_ceiling=Decimal("10.00"),
        live_paid_path_enabled=False,
    )


@pytest.fixture
def synthetic_verifier() -> SyntheticTokenVerifier:
    from mcp.server.auth.provider import AccessToken

    from stilldone.mcp.auth import SyntheticTokenVerifier

    verifier = SyntheticTokenVerifier()
    verifier.register_token(
        "valid_token",
        AccessToken(
            token="valid_token",
            client_id="alexa_client",
            scopes=[SAMPLE_SCOPE],
            resource=SAMPLE_RESOURCE_URL,
        ),
    )
    verifier.register_token(
        SENTINEL_TOKEN,
        AccessToken(
            token=SENTINEL_TOKEN,
            client_id="alexa_client",
            scopes=[SAMPLE_SCOPE],
            resource=SAMPLE_RESOURCE_URL,
        ),
    )
    verifier.register_token(
        "wrong_scope_token",
        AccessToken(
            token="wrong_scope_token",
            client_id="alexa_client",
            scopes=["other:unauthorized_scope"],
            resource=SAMPLE_RESOURCE_URL,
        ),
    )
    verifier.register_token(
        "wrong_resource_token",
        AccessToken(
            token="wrong_resource_token",
            client_id="alexa_client",
            scopes=[SAMPLE_SCOPE],
            resource="http://other-service.example.com/mcp",
        ),
    )
    verifier.register_token(
        "expired_token",
        AccessToken(
            token="expired_token",
            client_id="alexa_client",
            scopes=[SAMPLE_SCOPE],
            resource=SAMPLE_RESOURCE_URL,
            expires_at=int(datetime.now(UTC).timestamp()) - 3600,
        ),
    )
    return verifier


# ===========================================================================
# REQUIRED TESTS — AUTH (Tests 1 - 15)
# ===========================================================================


class TestMCPAuthentication:
    """Test OAuth 2.0 Resource Server authentication and PRM."""

    def test_01_protected_mcp_without_token_returns_401(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(CANONICAL_MCP_PATH)
            assert resp.status_code == 401

    def test_02_alexa_profile_401_contains_no_www_authenticate(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        assert auth_config.alexa_profile is True
        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(CANONICAL_MCP_PATH)
            assert resp.status_code == 401
            headers_lower = {k.lower(): v for k, v in resp.headers.items()}
            assert "www-authenticate" not in headers_lower

    def test_02b_generic_profile_401_retains_www_authenticate(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPAuthConfig,
            MCPServerConfig,
            create_mcp_app,
        )

        generic_auth = MCPAuthConfig(
            issuer_url=auth_config.issuer_url,
            resource_server_url=auth_config.resource_server_url,
            required_scopes=auth_config.required_scopes,
            validate_token_resource=True,
            alexa_profile=False,
        )
        cfg = MCPServerConfig(auth_config=generic_auth)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(CANONICAL_MCP_PATH)
            assert resp.status_code == 401
            headers_lower = {k.lower(): v for k, v in resp.headers.items()}
            assert "www-authenticate" in headers_lower

    def test_03_invalid_bearer_returns_401(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer invalid_nonexistent_token"},
            )
            assert resp.status_code == 401

    def test_03b_expired_bearer_returns_401(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer expired_token"},
            )
            assert resp.status_code == 401

    def test_04_raw_bearer_sentinel_absent_from_response_and_error_text(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": f"Bearer {SENTINEL_TOKEN}"},
            )
            # Response should not leak the secret sentinel token anywhere in body or headers
            assert SENTINEL_TOKEN not in resp.text
            for val in resp.headers.values():
                assert SENTINEL_TOKEN not in val

    def test_05_query_string_token_without_authorization_header_rejected(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp1 = client.post(f"{CANONICAL_MCP_PATH}?token=valid_token")
            assert resp1.status_code == 401

            resp2 = client.post(f"{CANONICAL_MCP_PATH}?access_token=valid_token")
            assert resp2.status_code == 401

    def test_06_wrong_resource_token_rejected(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer wrong_resource_token"},
            )
            assert resp.status_code == 401

    def test_07_insufficient_scope_token_rejected(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer wrong_scope_token"},
            )
            # Insufficient scope returns HTTP 403 Forbidden with www-authenticate
            assert resp.status_code == 403
            headers_lower = {k.lower(): v for k, v in resp.headers.items()}
            assert "www-authenticate" in headers_lower

    def test_08_valid_exact_resource_scoped_token_accepted(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer valid_token"},
            )
            # Not 401 or 403; passed auth gate
            assert resp.status_code not in (401, 403)

    @pytest.mark.anyio
    async def test_09_and_10_valid_authenticated_official_mcp_client_initialization_and_tools(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        import httpx2
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        cfg = MCPServerConfig(
            host=CANONICAL_MCP_HOST,
            port=port,
            path=CANONICAL_MCP_PATH,
            auth_config=auth_config,
        )
        ledger = InMemoryNonDurableLedger()

        async with run_loopback_mcp_server(
            config=cfg,
            ledger=ledger,
            token_verifier=synthetic_verifier,
        ) as (_, endpoint_url):
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer valid_token"},
                timeout=10.0,
            ) as http_client:
                async with streamable_http_client(endpoint_url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        init_result = await session.initialize()
                        assert init_result.protocol_version == "2025-11-25"
                        assert init_result.server_info.name == "StillDone"

                        tools_res = await session.list_tools()
                        tool_names = sorted(t.name for t in tools_res.tools)
                        assert tool_names == ["mission_start", "mission_status"]

    def test_11_to_14_prm_endpoint_and_metadata_truth(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            # 11. PRM endpoint is publicly readable without auth
            resp = client.get("/.well-known/oauth-protected-resource/mcp")
            assert resp.status_code == 200
            data = resp.json()

            # 12. PRM resource URI is exact
            assert data["resource"] == SAMPLE_RESOURCE_URL

            # 13. PRM authorization_servers is exact configured issuer
            assert data["authorization_servers"] == [f"{SAMPLE_ISSUER_URL}/"]

            # 14. PRM scopes are exact configured scopes
            assert data["scopes_supported"] == [SAMPLE_SCOPE]
            assert data["bearer_methods_supported"] == ["header"]

    def test_authorization_server_compatibility_truth_boundary(self) -> None:
        from stilldone.mcp import AUTHORIZATION_SERVER_LIVE_COMPATIBILITY

        assert AUTHORIZATION_SERVER_LIVE_COMPATIBILITY == "NOT_ESTABLISHED"

    def test_create_mcp_server_with_auth_config(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from stilldone.mcp import MCPServerConfig, create_mcp_server

        cfg = MCPServerConfig(auth_config=auth_config)
        server = create_mcp_server(cfg, token_verifier=synthetic_verifier)
        assert server.name == "StillDone"

    def test_15_health_and_readiness_remain_minimal_and_non_sensitive(
        self,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)
        with TestClient(app) as client:
            r_health = client.get("/health")
            assert r_health.status_code == 200
            assert r_health.json() == {"status": "alive", "scope": "process"}

            r_ready = client.get("/ready")
            assert r_ready.status_code == 200
            assert r_ready.json() == {"status": "ready", "scope": "mcp_transport"}

            # Ensure zero tokens, secrets, or internal paths disclosed
            for resp in (r_health, r_ready):
                assert "auth" not in resp.text
                assert "token" not in resp.text
                assert "db" not in resp.text

    def test_auth_config_with_missing_token_verifier_fails_construction(
        self,
        auth_config: MCPAuthConfig,
    ) -> None:
        """1. auth_config + missing token_verifier fails server and app construction."""
        from stilldone.mcp import MCPServerConfig, create_mcp_app, create_mcp_server

        cfg = MCPServerConfig(auth_config=auth_config)

        with pytest.raises(ValueError, match="token_verifier is None"):
            create_mcp_server(cfg, token_verifier=None)

        with pytest.raises(ValueError, match="token_verifier is None"):
            create_mcp_app(cfg, token_verifier=None)

    @pytest.mark.anyio
    async def test_auth_failure_occurs_before_mcp_can_be_served(
        self,
        auth_config: MCPAuthConfig,
    ) -> None:
        """2. Failure occurs before /mcp can be served or loopback port bound."""
        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        cfg = MCPServerConfig(
            host=CANONICAL_MCP_HOST,
            port=port,
            auth_config=auth_config,
        )

        with pytest.raises(ValueError, match="token_verifier is None"):
            async with run_loopback_mcp_server(cfg, token_verifier=None):
                pass  # pragma: no cover

    def test_no_automatic_synthetic_token_verifier_fallback(
        self,
        auth_config: MCPAuthConfig,
    ) -> None:
        """3. No automatic SyntheticTokenVerifier fallback occurs when verifier is omitted."""
        from stilldone.mcp import MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(auth_config=auth_config)
        with pytest.raises(ValueError, match="token_verifier is None"):
            create_mcp_app(cfg)

    def test_auth_config_none_permits_explicit_local_unprotected_construction(self) -> None:
        """4. auth_config=None still permits explicit local unprotected construction."""
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            MCPServerConfig,
            create_mcp_app,
            create_mcp_server,
        )

        cfg = MCPServerConfig(auth_config=None)
        server = create_mcp_server(cfg)
        assert server.name == "StillDone"

        app = create_mcp_app(cfg)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_empty_required_scopes_rejected(self) -> None:
        """9. Empty required_scopes collection is rejected."""
        from stilldone.mcp import MCPAuthConfig

        with pytest.raises(ValueError, match="non-empty collection"):
            MCPAuthConfig(
                issuer_url=SAMPLE_ISSUER_URL,
                resource_server_url=SAMPLE_RESOURCE_URL,
                required_scopes=(),
            )

        with pytest.raises(ValueError, match="non-empty collection"):
            MCPAuthConfig(
                issuer_url=SAMPLE_ISSUER_URL,
                resource_server_url=SAMPLE_RESOURCE_URL,
                required_scopes=[],  # type: ignore[arg-type]
            )

    def test_duplicate_and_blank_required_scopes_rejected(self) -> None:
        """10. Duplicate and blank required scopes are rejected."""
        from stilldone.mcp import MCPAuthConfig

        with pytest.raises(ValueError, match="Duplicate scope"):
            MCPAuthConfig(
                issuer_url=SAMPLE_ISSUER_URL,
                resource_server_url=SAMPLE_RESOURCE_URL,
                required_scopes=("stilldone:mcp", "stilldone:mcp"),
            )

        with pytest.raises(ValueError, match="non-empty strings"):
            MCPAuthConfig(
                issuer_url=SAMPLE_ISSUER_URL,
                resource_server_url=SAMPLE_RESOURCE_URL,
                required_scopes=("",),
            )

        with pytest.raises(ValueError, match="non-empty strings"):
            MCPAuthConfig(
                issuer_url=SAMPLE_ISSUER_URL,
                resource_server_url=SAMPLE_RESOURCE_URL,
                required_scopes=("   ",),
            )


# ===========================================================================
# REQUIRED TESTS — RATE (Tests 16 - 30)
# ===========================================================================


class TestMCPRateLimiting:
    """Test atomic SQLite rate limit store and runtime enforcement."""

    def test_16_to_19_atomic_consumption_and_exact_boundary(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        from stilldone.mcp import SqliteRateLimitStore

        db_path = temp_dir / "rate_test.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        at = datetime(2026, 10, 1, 12, 0, 15, tzinfo=UTC)

        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )

        # 16. First allowed request consumes one slot atomically
        d1 = store.check_and_consume(request, rate_policy, at)
        assert d1.is_allowed
        snap1 = store.get_snapshot(at)
        assert snap1.total_requests == 1
        assert snap1.paid_live_requests == 0

        # 17. Requests below limit succeed
        d2 = store.check_and_consume(request, rate_policy, at)
        assert d2.is_allowed
        assert store.get_snapshot(at).total_requests == 2

        # 18. Limit boundary is exact: limit is 3, 3rd succeeds
        d3 = store.check_and_consume(request, rate_policy, at)
        assert d3.is_allowed
        assert store.get_snapshot(at).total_requests == 3

        # 19. Request beyond limit returns DENY / RATE_LIMIT_EXCEEDED
        d4 = store.check_and_consume(request, rate_policy, at)
        assert d4.is_denied
        assert d4.reason.value == "RATE_LIMIT_EXCEEDED"
        # Total requests remains strictly 3; rejected attempt does not increment counter
        assert store.get_snapshot(at).total_requests == 3

    def test_20_and_21_denied_request_does_not_invoke_mcp_or_mutate_ledger(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        db_path = temp_dir / "rate_protect.db"
        policy = EndpointProtectionPolicy(
            max_requests_per_window=1,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        ledger = InMemoryNonDurableLedger()
        cfg = MCPServerConfig(
            auth_config=auth_config,
            rate_limit_policy=policy,
            rate_limit_db_path=db_path,
        )
        app = create_mcp_app(cfg, ledger=ledger, token_verifier=synthetic_verifier)

        with TestClient(app) as client:
            headers = {"Authorization": "Bearer valid_token"}
            # First request succeeds (passed auth + rate limit)
            r1 = client.post(CANONICAL_MCP_PATH, headers=headers)
            assert r1.status_code != 429

            # Second request exceeds window limit (1) -> HTTP 429
            r2 = client.post(CANONICAL_MCP_PATH, headers=headers)
            assert r2.status_code == 429
            data = r2.json()
            assert data["error"] == "rate_limit_exceeded"
            assert "retry_after_seconds" in data

            # Verify ledger was never mutated
            assert len(ledger._missions) == 0
            assert len(ledger._actions) == 0
            assert len(ledger._evidence) == 0

            # Verify persistent counter remains at 1
            store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            now = datetime.now(UTC)
            assert store.get_snapshot(now).total_requests == 1

    def test_22_concurrent_callers_cannot_exceed_configured_limit(
        self,
        temp_dir: Path,
    ) -> None:
        from stilldone.mcp import SqliteRateLimitStore

        db_path = temp_dir / "rate_concurrent.db"
        # Pre-initialize schema to avoid racing DDL during concurrent admission tests
        SqliteRateLimitStore(db_path, window_duration_seconds=60)
        limit = 5
        policy = EndpointProtectionPolicy(
            max_requests_per_window=limit,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        at = datetime(2026, 10, 1, 14, 0, 10, tzinfo=UTC)

        def attempt_admission(worker_id: int) -> tuple[int, bool]:
            # Each worker uses an independent store instance pointing to the same SQLite database
            store_worker = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            req = EndpointRequestAssessment(
                exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
                caller_class=CallerClass.PUBLIC_UNTRUSTED,
            )
            decision = store_worker.check_and_consume(req, policy, at)
            return worker_id, decision.is_allowed

        num_workers = 25
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_admission, i) for i in range(num_workers)]
            results = [f.result() for f in futures]

        allowed_count = sum(1 for _, allowed in results if allowed)
        denied_count = sum(1 for _, allowed in results if not allowed)

        # Exactly limit admissions allowed; all others fail closed
        assert allowed_count == limit
        assert denied_count == num_workers - limit

        # Re-check persistent store count
        final_store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        assert final_store.get_snapshot(at).total_requests == limit

    def test_23_rate_state_persists_across_store_reconstruction(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        from stilldone.mcp import SqliteRateLimitStore

        db_path = temp_dir / "rate_persist.db"
        at = datetime(2026, 10, 1, 15, 30, 0, tzinfo=UTC)
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )

        # Store instance 1 consumes 2 requests
        s1 = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        s1.check_and_consume(request, rate_policy, at)
        s1.check_and_consume(request, rate_policy, at)
        assert s1.get_snapshot(at).total_requests == 2

        # Reconstruct new store instance on same file path
        s2 = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        snap2 = s2.get_snapshot(at)
        assert snap2.total_requests == 2

        # 3rd request consumes final allowed slot
        d3 = s2.check_and_consume(request, rate_policy, at)
        assert d3.is_allowed

        # 4th request from instance 3 denied
        s3 = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        d4 = s3.check_and_consume(request, rate_policy, at)
        assert d4.is_denied

    def test_24_rate_store_error_fails_closed_500_without_leaking_path(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            RateLimitStoreError,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        class BrokenStore(SqliteRateLimitStore):
            def check_and_consume(
                self,
                request: EndpointRequestAssessment,
                policy: EndpointProtectionPolicy,
                at: datetime,
                budget_snapshot: Any | None = None,
            ) -> EndpointAdmissionDecision:
                raise RateLimitStoreError("Simulated disk I/O failure on /var/secret/rate.db")

        db_path = temp_dir / "rate_fail.db"
        store = BrokenStore(db_path)
        cfg = MCPServerConfig(
            auth_config=auth_config,
            rate_limit_policy=rate_policy,
        )
        app = create_mcp_app(
            cfg,
            token_verifier=synthetic_verifier,
            rate_limit_store=store,
        )

        with TestClient(app) as client:
            resp = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer valid_token"},
            )
            assert resp.status_code == 500
            data = resp.json()
            assert data["error"] == "rate_limit_unavailable"
            # Never leak database path or internals
            assert "/var/secret" not in resp.text
            assert "disk I/O" not in resp.text

    def test_25_health_endpoint_exempt_from_rate_limit(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        db_path = temp_dir / "rate_health.db"
        policy = EndpointProtectionPolicy(
            max_requests_per_window=1,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        cfg = MCPServerConfig(
            auth_config=auth_config,
            rate_limit_policy=policy,
            rate_limit_db_path=db_path,
        )
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)

        with TestClient(app) as client:
            # Consume the only quota slot via /mcp
            r_mcp1 = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer valid_token"},
            )
            assert r_mcp1.status_code != 429

            # /mcp is now rate limited
            r_mcp2 = client.post(
                CANONICAL_MCP_PATH,
                headers={"Authorization": "Bearer valid_token"},
            )
            assert r_mcp2.status_code == 429

            # /health remains fully accessible and returns 200
            r_health = client.get("/health")
            assert r_health.status_code == 200
            assert r_health.json()["status"] == "alive"

            # /health did not increment quota counter
            store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            now = datetime.now(UTC)
            assert store.get_snapshot(now).total_requests == 1

    def test_26_ready_endpoint_exempt_from_rate_limit(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        db_path = temp_dir / "rate_ready.db"
        policy = EndpointProtectionPolicy(
            max_requests_per_window=1,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        cfg = MCPServerConfig(
            auth_config=auth_config,
            rate_limit_policy=policy,
            rate_limit_db_path=db_path,
        )
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)

        with TestClient(app) as client:
            # Exhaust quota via /mcp
            client.post(CANONICAL_MCP_PATH, headers={"Authorization": "Bearer valid_token"})
            assert (
                client.post(
                    CANONICAL_MCP_PATH, headers={"Authorization": "Bearer valid_token"}
                ).status_code
                == 429
            )

            # /ready remains accessible
            r_ready = client.get("/ready")
            assert r_ready.status_code == 200
            assert r_ready.json()["status"] == "ready"

            # /ready did not increment quota
            store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            now = datetime.now(UTC)
            assert store.get_snapshot(now).total_requests == 1

    def test_27_prm_endpoint_exempt_from_rate_limit(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        db_path = temp_dir / "rate_prm.db"
        policy = EndpointProtectionPolicy(
            max_requests_per_window=1,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        cfg = MCPServerConfig(
            auth_config=auth_config,
            rate_limit_policy=policy,
            rate_limit_db_path=db_path,
        )
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)

        with TestClient(app) as client:
            # Exhaust quota on /mcp
            client.post(CANONICAL_MCP_PATH, headers={"Authorization": "Bearer valid_token"})
            assert (
                client.post(
                    CANONICAL_MCP_PATH, headers={"Authorization": "Bearer valid_token"}
                ).status_code
                == 429
            )

            # PRM endpoint remains accessible
            r_prm = client.get("/.well-known/oauth-protected-resource/mcp")
            assert r_prm.status_code == 200
            assert r_prm.json()["resource"] == SAMPLE_RESOURCE_URL

            # PRM did not increment quota
            store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            now = datetime.now(UTC)
            assert store.get_snapshot(now).total_requests == 1

    def test_28_half_open_window_boundary_rollover(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        from stilldone.mcp import SqliteRateLimitStore

        db_path = temp_dir / "rate_window.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        req = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )

        # Window 1: 12:00:00 - 12:01:00
        t_w1_start = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        t_w1_mid = datetime(2026, 10, 1, 12, 0, 30, tzinfo=UTC)
        t_w1_last_sec = datetime(2026, 10, 1, 12, 0, 59, tzinfo=UTC)

        # Exhaust window 1 (limit = 3)
        assert store.check_and_consume(req, rate_policy, t_w1_start).is_allowed
        assert store.check_and_consume(req, rate_policy, t_w1_mid).is_allowed
        assert store.check_and_consume(req, rate_policy, t_w1_last_sec).is_allowed
        # 4th in window 1 denied
        assert store.check_and_consume(req, rate_policy, t_w1_last_sec).is_denied

        # Window 2: exactly at boundary 12:01:00 (half-open: window_start <= at < window_end)
        t_w2_start = datetime(2026, 10, 1, 12, 1, 0, tzinfo=UTC)
        # In new window, quota is refreshed! First request must succeed
        d_w2_1 = store.check_and_consume(req, rate_policy, t_w2_start)
        assert d_w2_1.is_allowed
        assert store.get_snapshot(t_w2_start).total_requests == 1

        # Window 1 snapshot unchanged
        assert store.get_snapshot(t_w1_start).total_requests == 3

    def test_29_zero_sensitive_data_in_sqlite_store(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        import sqlite3

        from stilldone.mcp import SqliteRateLimitStore

        db_path = temp_dir / "rate_audit.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        at = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        req = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )
        store.check_and_consume(req, rate_policy, at)

        # Read SQLite schema and data directly
        conn = sqlite3.connect(str(db_path))
        try:
            # Check table schema: only window_start, window_end, total_requests, paid_live_requests
            cols = [col[1] for col in conn.execute("PRAGMA table_info(rate_limit_windows);")]
            assert cols == ["window_start", "window_end", "total_requests", "paid_live_requests"]

            # Read all rows
            rows = conn.execute("SELECT * FROM rate_limit_windows;").fetchall()
            assert len(rows) == 1
            row_text = str(rows[0])

            # Zero sensitive tokens, intents, contracts, IDs in SQLite store
            for forbidden_term in ("token", "secret", "intent", "mission", "auth", "sentinel"):
                assert forbidden_term not in row_text.lower()
        finally:
            conn.close()

    def test_30_unauthenticated_request_fails_at_auth_before_rate_limit(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        db_path = temp_dir / "rate_order.db"
        # Policy limit = 1
        policy = EndpointProtectionPolicy(
            max_requests_per_window=1,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        cfg = MCPServerConfig(
            auth_config=auth_config,
            rate_limit_policy=policy,
            rate_limit_db_path=db_path,
        )
        app = create_mcp_app(cfg, token_verifier=synthetic_verifier)

        with TestClient(app) as client:
            # Send 5 unauthenticated requests without Bearer token
            for _ in range(5):
                r = client.post(CANONICAL_MCP_PATH)
                # Auth fails immediately with 401, NOT 429
                assert r.status_code == 401

            # Verify rate store counter is STILL 0 (unauthenticated requests NEVER consume quota)
            store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            now = datetime.now(UTC)
            assert store.get_snapshot(now).total_requests == 0

    @pytest.mark.anyio
    async def test_alexa_401_compatibility_middleware_standalone(self) -> None:
        from starlette.types import Message, Receive, Scope, Send

        from stilldone.mcp import Alexa401CompatibilityMiddleware

        async def mock_app_401(scope: Scope, receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"www-authenticate", b"Bearer error=test"),
                        (b"content-type", b"application/json"),
                    ],
                }
            )

        sent_messages: list[Message] = []

        async def mock_send(msg: Message) -> None:
            sent_messages.append(msg)

        async def dummy_receive() -> Message:
            return {"type": "http.request"}

        middleware = Alexa401CompatibilityMiddleware(mock_app_401, enabled=True)
        await middleware({"type": "http"}, dummy_receive, mock_send)

        headers = dict(sent_messages[0]["headers"])
        assert b"www-authenticate" not in headers
        assert b"content-type" in headers

    @pytest.mark.anyio
    async def test_rate_limit_middleware_standalone(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        from starlette.types import Message, Receive, Scope, Send

        from stilldone.mcp import RateLimitMiddleware, SqliteRateLimitStore

        db_path = temp_dir / "standalone_rl.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)

        async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})

        sent: list[Message] = []

        async def capture_send(msg: Message) -> None:
            sent.append(msg)

        async def dummy_receive() -> Message:
            return {"type": "http.request"}

        rl = RateLimitMiddleware(inner_app, store=store, policy=rate_policy)
        await rl({"type": "http"}, dummy_receive, capture_send)
        assert sent[0]["status"] == 200

    def test_rate_policy_without_store_or_path_fails_construction(
        self,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        """11. Policy without store or db_path fails construction."""
        from stilldone.mcp import MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig(rate_limit_policy=rate_policy, rate_limit_db_path=None)
        with pytest.raises(ValueError, match="neither rate_limit_store nor rate_limit_db_path"):
            create_mcp_app(cfg, rate_limit_store=None)

    def test_rate_store_without_policy_fails_construction(
        self,
        temp_dir: Path,
    ) -> None:
        """12. Store without policy fails construction."""
        from stilldone.mcp import MCPServerConfig, SqliteRateLimitStore, create_mcp_app

        db_path = temp_dir / "store_no_policy.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        cfg = MCPServerConfig(rate_limit_policy=None, rate_limit_db_path=None)

        with pytest.raises(ValueError, match="without rate_limit_policy"):
            create_mcp_app(cfg, rate_limit_store=store)

    def test_db_path_without_policy_fails_construction(
        self,
        temp_dir: Path,
    ) -> None:
        """13. DB path without policy fails construction."""
        from stilldone.mcp import MCPServerConfig

        db_path = temp_dir / "path_no_policy.db"
        with pytest.raises(ValueError, match="rate_limit_db_path cannot be configured"):
            MCPServerConfig(rate_limit_policy=None, rate_limit_db_path=db_path)

    def test_both_store_and_db_path_fails_construction_ambiguity_guard(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        """Ambiguity guard: Both store and db_path supplied simultaneously fails closed."""
        from stilldone.mcp import MCPServerConfig, SqliteRateLimitStore, create_mcp_app

        db_path = temp_dir / "ambiguous.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        cfg = MCPServerConfig(rate_limit_policy=rate_policy, rate_limit_db_path=db_path)

        with pytest.raises(ValueError, match="simultaneously"):
            create_mcp_app(cfg, rate_limit_store=store)

    def test_valid_policy_with_injected_store_succeeds(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        """14. Valid policy + injected store succeeds in Mode B."""
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            MCPServerConfig,
            SqliteRateLimitStore,
            create_mcp_app,
        )

        db_path = temp_dir / "mode_b_store.db"
        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
        cfg = MCPServerConfig(rate_limit_policy=rate_policy, rate_limit_db_path=None)

        app = create_mcp_app(cfg, rate_limit_store=store)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_valid_policy_with_db_path_succeeds(
        self,
        temp_dir: Path,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        """15. Valid policy + db path succeeds in Mode B."""
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            MCPServerConfig,
            create_mcp_app,
        )

        db_path = temp_dir / "mode_b_path.db"
        cfg = MCPServerConfig(rate_limit_policy=rate_policy, rate_limit_db_path=db_path)

        app = create_mcp_app(cfg)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_partial_config_cannot_reach_mcp_tool_execution(
        self,
        auth_config: MCPAuthConfig,
        rate_policy: EndpointProtectionPolicy,
    ) -> None:
        """16. Partial configuration fails closed before any tool execution can be reached."""
        from stilldone.mcp import MCPServerConfig, create_mcp_app

        # Partial auth config: cannot create app to serve tools
        cfg_partial_auth = MCPServerConfig(auth_config=auth_config)
        with pytest.raises(ValueError, match="token_verifier is None"):
            create_mcp_app(cfg_partial_auth)

        # Partial rate config: cannot create app to serve tools
        cfg_partial_rate = MCPServerConfig(rate_limit_policy=rate_policy, rate_limit_db_path=None)
        with pytest.raises(ValueError, match="neither rate_limit_store nor rate_limit_db_path"):
            create_mcp_app(cfg_partial_rate)


# ===========================================================================
# REQUIRED CROSS-BOUNDARY TEST
# ===========================================================================


class TestCrossBoundaryRealLoopback:
    """Proves real loopback Streamable HTTP transport:

    valid Bearer + quota available + mission_start -> DRAFT mission
    -> valid Bearer + quota available + mission_status -> matches DRAFT
    -> exhaust quota -> subsequent request denied (429) without extra ledger mutation.
    """

    @pytest.mark.anyio
    async def test_cross_boundary_valid_bearer_quota_and_exhaustion(
        self,
        temp_dir: Path,
        auth_config: MCPAuthConfig,
        synthetic_verifier: SyntheticTokenVerifier,
    ) -> None:
        import anyio
        import httpx2
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            SqliteRateLimitStore,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        db_path = temp_dir / "cross_boundary.db"
        # Configure quota limit = 6 (initialize takes 4 requests, mission_start 1, mission_status 1)
        policy = EndpointProtectionPolicy(
            max_requests_per_window=6,
            max_paid_live_requests_per_window=6,
            internal_gross_ceiling=Decimal("10.00"),
            live_paid_path_enabled=False,
        )
        cfg = MCPServerConfig(
            host=CANONICAL_MCP_HOST,
            port=port,
            path=CANONICAL_MCP_PATH,
            auth_config=auth_config,
            rate_limit_policy=policy,
            rate_limit_db_path=db_path,
        )
        ledger = InMemoryNonDurableLedger()

        async with run_loopback_mcp_server(
            config=cfg,
            ledger=ledger,
            token_verifier=synthetic_verifier,
        ) as (_, endpoint_url):
            # Client with valid bearer token
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer valid_token"},
                timeout=10.0,
            ) as http_client:
                async with streamable_http_client(
                    endpoint_url, http_client=http_client, terminate_on_close=False
                ) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()

                        # Request: mission_start
                        start_result = await session.call_tool(
                            "mission_start",
                            {"intent": "Prepare morning routine for tomorrow"},
                        )
                        assert not start_result.is_error
                        assert start_result.content is not None
                        start_data = json.loads(start_result.content[0].text)  # type: ignore[union-attr]
                        mission_id = start_data["mission_id"]
                        assert start_data["state"] == MissionState.DRAFT.value

                        # Verify ledger has exactly 1 DRAFT mission
                        assert len(ledger._missions) == 1
                        mission_record = ledger.get_mission(MissionId(mission_id))
                        assert mission_record.state == MissionState.DRAFT

                        # Request: mission_status
                        status_result = await session.call_tool(
                            "mission_status",
                            {"mission_id": mission_id},
                        )
                        assert not status_result.is_error
                        assert status_result.content is not None
                        status_data = json.loads(status_result.content[0].text)  # type: ignore[union-attr]
                        assert status_data["mission_id"] == mission_id
                        assert status_data["state"] == MissionState.DRAFT.value

                        # Allow background SSE stream establishment to settle before session close
                        store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
                        for _ in range(50):
                            if store.get_snapshot(datetime.now(UTC)).total_requests >= 6:
                                break
                            await anyio.sleep(0.02)

            # Verify SQLite store recorded exactly 6 requests (quota now exhausted)
            store = SqliteRateLimitStore(db_path, window_duration_seconds=60)
            now = datetime.now(UTC)
            assert store.get_snapshot(now).total_requests == 6

            # Now quota is exhausted (limit = 6). A subsequent request must fail with HTTP 429
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer valid_token"},
                timeout=10.0,
            ) as http_client:
                # Raw HTTP POST to /mcp
                resp = await http_client.post(endpoint_url)
                assert resp.status_code == 429
                data = resp.json()
                assert data["error"] == "rate_limit_exceeded"

            # Final ledger check: STILL exactly 1 mission (zero additional mutation!)
            assert len(ledger._missions) == 1
