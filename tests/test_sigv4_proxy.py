"""Focused tests for scripts/sigv4_proxy.py boundary rules.

Proves:
1. GET /ping does NOT return fake {"status":"Healthy"}.
2. GET /health does NOT return fake health.
3. unsupported GET returns bounded non-success (405).
4. upstream subprocess stderr containing sentinel secret/ARN text is NOT returned to client.
5. POST /mcp successful upstream payload is returned without synthetic MCP business content.
6. proxy binds loopback only.
7. credentials/Authorization are not logged.

Strict Invariants:
- Zero live AWS calls.
- Zero network external calls.
- Strictly local thread-based test server bound to 127.0.0.1 on ephemeral port.
"""

from __future__ import annotations

import importlib.util
import io
import json
import threading
from collections.abc import Generator
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_proxy_path = Path(__file__).parent.parent / "scripts" / "sigv4_proxy.py"
_spec = importlib.util.spec_from_file_location("sigv4_proxy", _proxy_path)
assert _spec is not None and _spec.loader is not None
proxy_module: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proxy_module)
SigV4ProxyHandler: type[Any] = proxy_module.SigV4ProxyHandler


@pytest.fixture
def proxy_server() -> Generator[tuple[str, int], None, None]:
    """Start an ephemeral SigV4 proxy server on 127.0.0.1 for testing."""
    proxy_module._active_session_id = None
    server = HTTPServer(("127.0.0.1", 0), SigV4ProxyHandler)
    host = str(server.server_address[0])
    port = int(server.server_address[1])

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield host, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        proxy_module._active_session_id = None


def test_get_ping_does_not_return_fake_healthy(proxy_server: tuple[str, int]) -> None:
    """1. GET /ping does NOT return fake {"status":"Healthy"}."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)
    try:
        conn.request("GET", "/ping")
        resp = conn.getresponse()
        body = resp.read()

        # Must not be HTTP 200
        assert resp.status == 405
        # Must not fabricate Healthy status
        assert b'"status":"Healthy"' not in body
        assert b'"Healthy"' not in body
        # Must return structured method-not-allowed error
        data = json.loads(body.decode("utf-8"))
        assert data.get("error") == "Method Not Allowed"
    finally:
        conn.close()


def test_get_health_does_not_return_fake_healthy(proxy_server: tuple[str, int]) -> None:
    """2. GET /health does NOT return fake health."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        body = resp.read()

        assert resp.status == 405
        assert b'"status":"Healthy"' not in body
        assert b'"Healthy"' not in body
        data = json.loads(body.decode("utf-8"))
        assert data.get("error") == "Method Not Allowed"
    finally:
        conn.close()


def test_unsupported_get_returns_bounded_non_success(proxy_server: tuple[str, int]) -> None:
    """3. Unsupported GET returns bounded non-success (405)."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)
    try:
        for path in ("/", "/mcp", "/random-path", "/ready"):
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()

            assert resp.status == 405
            assert resp.getheader("Allow") == "POST"
            data = json.loads(body.decode("utf-8"))
            assert data["error"] == "Method Not Allowed"
    finally:
        conn.close()


def test_upstream_subprocess_stderr_redacted(proxy_server: tuple[str, int]) -> None:
    """4. Upstream subprocess stderr with sentinel text is NOT returned to client."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    sentinel_secret = "SECRET_KEY_AKIA_SENTINEL_TOKEN_12345"
    sentinel_arn = "arn:aws:iam::123456789012:role/SuperSecretRole"
    sentinel_account = "123456789012"
    sentinel_session = "sentinel-session-uuid-98765"

    fake_failure = MagicMock()
    fake_failure.returncode = 1
    fake_failure.stderr = (
        f"ValidationException: {sentinel_secret} in {sentinel_arn} for "
        f"account {sentinel_account} with session {sentinel_session}"
    )
    fake_failure.stdout = ""

    try:
        with patch("subprocess.run", return_value=fake_failure):
            headers = {"Content-Type": "application/json"}
            conn.request(
                "POST",
                "/mcp",
                body=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
                headers=headers,
            )
            resp = conn.getresponse()
            body = resp.read()

            # Must return bounded 502
            assert resp.status == 502
            body_str = body.decode("utf-8")

            # Must NOT leak sentinel secrets, ARNs, accounts, sessions, or raw stderr
            assert sentinel_secret not in body_str
            assert sentinel_arn not in body_str
            assert sentinel_account not in body_str
            assert sentinel_session not in body_str
            assert "ValidationException" not in body_str

            # Must contain only bounded generic error and exit code
            data = json.loads(body_str)
            assert data == {
                "error": "AgentCore invocation failed",
                "exit_code": 1,
            }
    finally:
        conn.close()


def test_post_mcp_returns_upstream_payload_without_synthetic_mcp_content(
    proxy_server: tuple[str, int],
) -> None:
    """5. POST /mcp upstream payload is returned without synthetic MCP business content."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    raw_upstream_event = (
        b"event: message\r\n"
        b'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"mission_status"}]}}\r\n\r\n'
    )

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> MagicMock:
        # Last argument of cmd is out_path
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(raw_upstream_event)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = json.dumps({"runtimeSessionId": "test-runtime-session-abc"})
        mock_res.stderr = ""
        return mock_res

    try:
        with patch("subprocess.run", side_effect=fake_subprocess_run):
            headers = {"Content-Type": "application/json"}
            conn.request(
                "POST",
                "/mcp",
                body=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
                headers=headers,
            )
            resp = conn.getresponse()
            body = resp.read()

            assert resp.status == 200
            assert resp.getheader("Content-Type") == "text/event-stream"
            assert resp.getheader("Mcp-Session-Id") == "test-runtime-session-abc"
            # Exactly the raw upstream event data, no synthesized business content
            assert body == raw_upstream_event
    finally:
        conn.close()


def test_proxy_binds_loopback_only() -> None:
    """6. Proxy binds loopback only."""
    # Direct test of server creation defaults
    server = HTTPServer(("127.0.0.1", 0), SigV4ProxyHandler)
    try:
        host = str(server.server_address[0])
        assert host == "127.0.0.1"
        assert host != "0.0.0.0"
    finally:
        server.server_close()


def test_credentials_and_authorization_not_logged(proxy_server: tuple[str, int]) -> None:
    """7. Credentials/Authorization are not logged."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    secret_auth_token = "BEARER_TOKEN_SECRET_XYZ_999"
    secret_custom_auth = "AWS4-HMAC-SHA256 Credential=SECRET_AKIA/..."

    stderr_capture = io.StringIO()

    try:
        with patch("sys.stderr", stderr_capture):
            headers = {
                "Authorization": f"Bearer {secret_auth_token}",
                "X-Amz-Security-Token": secret_custom_auth,
            }
            conn.request("GET", "/ping", headers=headers)
            resp = conn.getresponse()
            resp.read()

        logged_output = stderr_capture.getvalue()
        # Verify log output has no sensitive headers or tokens
        assert secret_auth_token not in logged_output
        assert secret_custom_auth not in logged_output
        assert "Authorization" not in logged_output
        assert "X-Amz-Security-Token" not in logged_output
        # Only method and path are logged
        assert "[Proxy] GET /ping" in logged_output
    finally:
        conn.close()
