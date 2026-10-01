"""Tests for StillDone MCP Server Deployment Profile & AgentCore Configuration (Phase P-05.06).

Validates:
1. Default local profile still binds loopback only (127.0.0.1) and rejects non-loopback.
2. Explicit AgentCore profile allows 0.0.0.0:8000 binding.
3. create_agentcore_config sets expected values (0.0.0.0, 8000, /mcp, stateless_http=False).
4. GET /ping returns exactly {"status": "Healthy"} (HTTP 200, no-cache headers).
5. /ping is exempt from rate limiting and auth requirements.
6. /health and /ready endpoints remain intact and correct.
7. Path collision checks prevent /ping from clashing with /mcp, /health, or /ready.
8. Rate limiting is active on /mcp under AgentCore profile.
9. CLI argument parsing in __main__.py correctly configures profiles.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

import pytest

from stilldone.__main__ import parse_args


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
        or k == "starlette"
        or k.startswith("starlette.")
    ]
    for k in mcp_keys:
        sys.modules.pop(k, None)


class TestMCPServerDeploymentProfile:
    """Test deployment profile semantics and binding rules."""

    def test_default_profile_is_none_and_loopback_only(self) -> None:
        """Default MCPServerConfig enforces loopback-only binding."""
        from stilldone.mcp import CANONICAL_MCP_HOST, MCPServerConfig

        cfg = MCPServerConfig()
        assert cfg.deployment_profile is None
        assert cfg.host == CANONICAL_MCP_HOST

        # Loopback hosts succeed
        MCPServerConfig(host="127.0.0.1")
        MCPServerConfig(host="localhost")

        # Non-loopback hosts fail closed when deployment_profile is None
        with pytest.raises(ValueError, match="host must be a loopback address"):
            MCPServerConfig(host="0.0.0.0")

        with pytest.raises(ValueError, match="host must be a loopback address"):
            MCPServerConfig(host="192.168.1.50")

    def test_unknown_deployment_profile_rejected(self) -> None:
        """Unrecognized deployment_profile strings fail closed."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(ValueError, match="Unknown deployment_profile"):
            MCPServerConfig(deployment_profile="production")

        with pytest.raises(ValueError, match="Unknown deployment_profile"):
            MCPServerConfig(deployment_profile="cloud")

        with pytest.raises(TypeError, match="deployment_profile must be a string or None"):
            MCPServerConfig(deployment_profile=123)  # type: ignore[arg-type]

    def test_agentcore_profile_permits_non_loopback_bind(self) -> None:
        """deployment_profile='agentcore' explicitly permits 0.0.0.0 binding."""
        from stilldone.mcp import DEPLOYMENT_PROFILE_AGENTCORE, MCPServerConfig

        cfg = MCPServerConfig(
            host="0.0.0.0",
            port=8000,
            deployment_profile=DEPLOYMENT_PROFILE_AGENTCORE,
        )
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8000
        assert cfg.deployment_profile == "agentcore"

    def test_create_agentcore_config_factory(self) -> None:
        """create_agentcore_config creates canonical AgentCore deployment configuration."""
        from stilldone.mcp import DEPLOYMENT_PROFILE_AGENTCORE, create_agentcore_config

        cfg = create_agentcore_config(port=8000)
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8000
        assert cfg.path == "/mcp"
        assert cfg.stateless_http is False
        assert cfg.deployment_profile == DEPLOYMENT_PROFILE_AGENTCORE
        assert cfg.ping_path == "/ping"
        assert cfg.health_path == "/health"
        assert cfg.ready_path == "/ready"
        assert cfg.auth_config is None
        assert cfg.rate_limit_policy is not None
        assert cfg.rate_limit_db_path is not None
        assert cfg.rate_limit_policy.max_requests_per_window == 10
        assert cfg.rate_limit_policy.internal_gross_ceiling == Decimal("0.05")

    def test_create_agentcore_config_custom_rate_limit(self) -> None:
        """create_agentcore_config accepts custom rate limit max requests and db path."""
        from stilldone.mcp import create_agentcore_config

        with tempfile.TemporaryDirectory() as tmpdir:
            custom_db = Path(tmpdir) / "test_rate.db"
            cfg = create_agentcore_config(
                port=8080,
                max_requests_per_window=5,
                rate_limit_db_path=custom_db,
                rate_limit_window_seconds=30,
            )
            assert cfg.port == 8080
            assert cfg.rate_limit_policy is not None
            assert cfg.rate_limit_policy.max_requests_per_window == 5
            assert cfg.rate_limit_db_path == custom_db
            assert cfg.rate_limit_window_seconds == 30


class TestPingEndpoint:
    """Test GET /ping endpoint behavior."""

    def test_ping_endpoint_returns_healthy(self) -> None:
        """GET /ping returns HTTP 200 with bounded {"status": "Healthy"}."""
        from starlette.testclient import TestClient

        from stilldone.mcp import PING_STATUS_HEALTHY, MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig()
        app = create_mcp_app(cfg)
        client = TestClient(app)

        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"status": PING_STATUS_HEALTHY}
        assert response.json() == {"status": "Healthy"}
        assert response.headers.get("cache-control") == "no-cache, no-store, must-revalidate"

    def test_ping_endpoint_contains_no_secrets_or_metadata(self) -> None:
        """GET /ping response contains strictly {"status": "Healthy"} and nothing else."""
        from starlette.testclient import TestClient

        from stilldone.mcp import MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig()
        app = create_mcp_app(cfg)
        client = TestClient(app)

        response = client.get("/ping")
        data = response.json()
        assert set(data.keys()) == {"status"}
        assert data["status"] == "Healthy"

    def test_health_and_ready_endpoints_remain_correct(self) -> None:
        """Existing /health and /ready endpoints are unchanged."""
        from starlette.testclient import TestClient

        from stilldone.mcp import MCPServerConfig, create_mcp_app

        cfg = MCPServerConfig()
        app = create_mcp_app(cfg)
        client = TestClient(app)

        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "alive", "scope": "process"}

        ready_resp = client.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json() == {"status": "ready", "scope": "mcp_transport"}

    def test_ping_path_validation_and_collisions(self) -> None:
        """ping_path must be valid non-root path and cannot collide with other paths."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(ValueError, match="ping_path must be a string starting with '/'"):
            MCPServerConfig(ping_path="ping")

        with pytest.raises(ValueError, match="ping_path must be a non-root path"):
            MCPServerConfig(ping_path="/")

        # Clash with /mcp
        with pytest.raises(ValueError, match="ping_path cannot clash with mcp path"):
            MCPServerConfig(ping_path="/mcp")

        # Clash with /ready
        with pytest.raises(ValueError, match="ping_path and ready_path cannot be identical"):
            MCPServerConfig(ping_path="/ready")


class TestAgentCoreAppIntegration:
    """Test full app behavior under the AgentCore deployment profile."""

    def test_agentcore_app_serves_ping_health_ready_and_mcp(self) -> None:
        """AgentCore app mounts /ping, /health, /ready, and /mcp."""
        from starlette.testclient import TestClient

        from stilldone.mcp import create_agentcore_config, create_mcp_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rate_limit.db"
            cfg = create_agentcore_config(
                port=8000,
                rate_limit_db_path=db_path,
                max_requests_per_window=10,
            )
            app = create_mcp_app(cfg)
            client = TestClient(app)

            # /ping is alive
            r_ping = client.get("/ping")
            assert r_ping.status_code == 200
            assert r_ping.json() == {"status": "Healthy"}

            # /health is alive
            r_health = client.get("/health")
            assert r_health.status_code == 200
            assert r_health.json()["status"] == "alive"

            # /ready is ready
            r_ready = client.get("/ready")
            assert r_ready.status_code == 200
            assert r_ready.json()["status"] == "ready"

    def test_agentcore_rate_limiting_enforcement_on_mcp(self) -> None:
        """Under AgentCore profile, rate limiter protects /mcp and returns 429 when exhausted."""
        from starlette.testclient import TestClient

        from stilldone.mcp import create_agentcore_config, create_mcp_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rate_limit.db"
            # Limit to 2 requests
            cfg = create_agentcore_config(
                port=8000,
                rate_limit_db_path=db_path,
                max_requests_per_window=2,
            )
            app = create_mcp_app(cfg)
            with TestClient(app) as client:
                # Request 1 to /mcp (POST with empty body or invalid json still hits rate limiter)
                r1 = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
                assert r1.status_code != 429

                # Request 2 to /mcp
                r2 = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping"})
                assert r2.status_code != 429

                # Request 3 to /mcp should be RATE LIMITED (HTTP 429)
                r3 = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "ping"})
                assert r3.status_code == 429
                data = r3.json()
                assert data["error"] == "rate_limit_exceeded"
                assert "retry_after_seconds" in data

                # BUT /ping and /health remain exempt and succeed!
                assert client.get("/ping").status_code == 200
                assert client.get("/health").status_code == 200
                assert client.get("/ready").status_code == 200


class TestCliArgs:
    """Test CLI argument parsing."""

    def test_default_args(self) -> None:
        args = parse_args([])
        assert args.profile == "local"
        assert args.port == 8000
        assert args.host is None
        assert args.rate_limit_max == 10

    def test_agentcore_profile_args(self) -> None:
        args = parse_args(["--profile", "agentcore", "--port", "8000", "--rate-limit-max", "5"])
        assert args.profile == "agentcore"
        assert args.port == 8000
        assert args.rate_limit_max == 5
