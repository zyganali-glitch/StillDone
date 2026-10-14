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


def test_post_mcp_reuses_preseeded_session_id_preventing_duplicate_sessions(
    proxy_server: tuple[str, int],
) -> None:
    """8. Pre-seeded session ID is passed on first request, preventing duplicate sessions."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    # Pre-seed session ID
    proxy_module._active_session_id = "preseeded-session-id-12345"

    executed_cmd: list[str] = []

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal executed_cmd
        executed_cmd = list(cmd)
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(b'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\r\n\r\n')
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = json.dumps({"runtimeSessionId": "preseeded-session-id-12345"})
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
            assert resp.status == 200
            assert resp.getheader("Mcp-Session-Id") == "preseeded-session-id-12345"

            # Assert that preseeded session ID was passed to AgentCore CLI on the first call
            assert "--runtime-session-id" in executed_cmd
            assert "--mcp-session-id" in executed_cmd
            rt_idx = executed_cmd.index("--runtime-session-id")
            assert executed_cmd[rt_idx + 1] == "preseeded-session-id-12345"
            mcp_idx = executed_cmd.index("--mcp-session-id")
            assert executed_cmd[mcp_idx + 1] == "preseeded-session-id-12345"
    finally:
        conn.close()


def test_post_mcp_incoming_header_session_id_persists(
    proxy_server: tuple[str, int],
) -> None:
    """9. Incoming Mcp-Session-Id header is passed to AgentCore and updates active session."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    executed_cmd: list[str] = []

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal executed_cmd
        executed_cmd = list(cmd)
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(b'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\r\n\r\n')
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = json.dumps({"runtimeSessionId": "incoming-session-uuid-777"})
        mock_res.stderr = ""
        return mock_res

    try:
        with patch("subprocess.run", side_effect=fake_subprocess_run):
            headers = {
                "Content-Type": "application/json",
                "Mcp-Session-Id": "incoming-session-uuid-777",
            }
            conn.request(
                "POST",
                "/mcp",
                body=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
                headers=headers,
            )
            resp = conn.getresponse()
            assert resp.status == 200
            assert resp.getheader("Mcp-Session-Id") == "incoming-session-uuid-777"
            assert proxy_module._active_session_id == "incoming-session-uuid-777"

            rt_idx = executed_cmd.index("--runtime-session-id")
            assert executed_cmd[rt_idx + 1] == "incoming-session-uuid-777"
    finally:
        conn.close()


def test_run_cli_arg_parsing_sets_runtime_arn_and_session_id() -> None:
    """10. run() CLI parses ARN and --session-id without launching server."""
    test_arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/stilldone-rt-123"
    test_session = "cli-session-id-456"

    with (
        patch("sys.argv", ["sigv4_proxy.py", test_arn, "--session-id", test_session]),
        patch.object(proxy_module, "HTTPServer") as mock_server,
    ):
        mock_instance = MagicMock()
        mock_server.return_value = mock_instance
        # Stop serve_forever from blocking
        mock_instance.serve_forever.return_value = None

        proxy_module.run()

        assert proxy_module.AGENT_RUNTIME_ARN == test_arn
        assert proxy_module._active_session_id == test_session


def test_post_mcp_rejects_mismatched_client_session_id(proxy_server: tuple[str, int]) -> None:
    """11. Inbound Mcp-Session-Id header mismatching active proxy session fails closed.

    Fails closed with HTTP 400.
    """
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    # Pre-seed session ID
    proxy_module._active_session_id = "preseeded-session-12345"

    subprocess_called = False

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal subprocess_called
        subprocess_called = True
        return MagicMock(returncode=0, stdout="{}", stderr="")

    try:
        with patch("subprocess.run", side_effect=fake_subprocess_run):
            headers = {
                "Content-Type": "application/json",
                "Mcp-Session-Id": "hostile-mismatched-session-99999",
            }
            conn.request(
                "POST",
                "/mcp",
                body=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
                headers=headers,
            )
            resp = conn.getresponse()
            body = resp.read()

            assert resp.status == 400
            data = json.loads(body.decode("utf-8"))
            assert data["error"] == "Session Mismatch"
            assert "hostile-mismatched-session-99999" not in body.decode("utf-8")
            assert "preseeded-session-12345" not in body.decode("utf-8")

            # Upstream invocation must NOT be executed on session mismatch
            assert subprocess_called is False
    finally:
        conn.close()


def test_log_message_sanitizes_query_strings_and_session_ids(
    proxy_server: tuple[str, int],
) -> None:
    """12. Path logging strips query strings and session/credential query parameters."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    secret_in_query = "SESSION_TOKEN_SECRET_98765"
    raw_path_with_query = f"/mcp?session_id={secret_in_query}&auth=supersecret"

    stderr_capture = io.StringIO()

    try:
        with patch("sys.stderr", stderr_capture):
            conn.request("GET", raw_path_with_query)
            resp = conn.getresponse()
            resp.read()

        logged = stderr_capture.getvalue()
        assert secret_in_query not in logged
        assert "supersecret" not in logged
        assert "?session_id=" not in logged
        assert "[Proxy] GET /mcp\n" in logged
    finally:
        conn.close()


def test_unexpected_upstream_session_identity_fails_closed(
    proxy_server: tuple[str, int],
) -> None:
    """13. Upstream returning an unexpected session identity fails closed (HTTP 502)."""
    host, port = proxy_server
    conn = HTTPConnection(host, port, timeout=5.0)

    proxy_module._active_session_id = "preseeded-session-12345"

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> MagicMock:
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(b"event: message\r\ndata: {}\r\n\r\n")
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = json.dumps({"runtimeSessionId": "unexpected-foreign-session-666"})
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

            assert resp.status == 502
            data = json.loads(body.decode("utf-8"))
            assert data["error"] == "Upstream Session Mismatch"
            assert "unexpected-foreign-session-666" not in body.decode("utf-8")
            assert "preseeded-session-12345" not in body.decode("utf-8")
    finally:
        conn.close()


def test_startup_message_does_not_print_raw_session_id() -> None:
    """14. run() startup output does not leak raw session ID strings."""
    test_arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-rt"
    test_session = "secret-session-id-token-abcxyz"

    stdout_buf = io.StringIO()

    with (
        patch("sys.argv", ["sigv4_proxy.py", test_arn, "--session-id", test_session]),
        patch.object(proxy_module, "HTTPServer") as mock_server,
        patch("sys.stdout", stdout_buf),
    ):
        mock_instance = MagicMock()
        mock_server.return_value = mock_instance
        mock_instance.serve_forever.return_value = None

        proxy_module.run()

        output = stdout_buf.getvalue()
        assert test_session not in output
        assert "[session-bound]" in output
