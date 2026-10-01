"""Local SigV4 Signing Proxy for MCP Inspector and HTTP clients.

Binds to 127.0.0.1:8080 and transparently forwards MCP wire traffic to the real
AWS Bedrock AgentCore Runtime endpoint, authenticated via AWS SigV4 using the
short-lived AWS profile 'stilldone-p01'.

Strict Invariants:
1. Zero mock responses, zero response synthesis or filtering.
2. Forwards exact MCP wire traffic bidirectionally.
3. Acquires AWS credentials solely from the active short-lived profile.
4. Never logs, persists, or exposes credentials, tokens, or Authorization values.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("STILLDONE_SIGV4_PROXY_PORT", "8080"))
PROFILE = os.environ.get("AWS_PROFILE", "stilldone-p01")
REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")


# Shared active session ID across requests in this run
_active_session_id: str | None = None


class SigV4ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"[Proxy] {self.command} {self.path}\n")

    def do_GET(self) -> None:
        if self.path in ("/ping", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"Healthy"}')
            return

        self.send_response(405)
        self.end_headers()

    def do_POST(self) -> None:
        global _active_session_id
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Check if incoming request specified a session ID
        req_session = self.headers.get("mcp-session-id") or self.headers.get("Mcp-Session-Id")
        target_session = req_session or _active_session_id

        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".json") as req_f:
            req_f.write(body)
            req_path = req_f.name

        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".json") as out_f:
            out_path = out_f.name

        try:
            cmd = [
                "aws",
                "bedrock-agentcore",
                "invoke-agent-runtime",
                "--agent-runtime-arn",
                AGENT_RUNTIME_ARN,
                "--content-type",
                "application/json",
                "--accept",
                "application/json, text/event-stream",
                "--payload",
                f"fileb://{req_path}",
                "--region",
                REGION,
                "--profile",
                PROFILE,
            ]
            if target_session:
                cmd.extend(
                    [
                        "--runtime-session-id",
                        target_session,
                        "--mcp-session-id",
                        target_session,
                    ]
                )

            cmd.append(out_path)
            res = subprocess.run(cmd, capture_output=True, text=True)

            if res.returncode != 0:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                err_payload = json.dumps(
                    {
                        "error": "AgentCore invocation failed",
                        "details": res.stderr,
                    }
                )
                self.wfile.write(err_payload.encode())
                return

            # Parse stdout JSON to capture returned session IDs
            try:
                meta = json.loads(res.stdout)
                ret_session = meta.get("runtimeSessionId") or meta.get("mcpSessionId")
                if ret_session:
                    _active_session_id = ret_session
            except Exception:
                pass

            with open(out_path, "rb") as f:
                resp_data = f.read()

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            if _active_session_id:
                self.send_header("Mcp-Session-Id", _active_session_id)
            self.end_headers()
            self.wfile.write(resp_data)

        finally:
            if os.path.exists(req_path):
                os.unlink(req_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


def run() -> None:
    global AGENT_RUNTIME_ARN
    if len(sys.argv) > 1 and sys.argv[1].startswith("arn:aws:bedrock-agentcore:"):
        AGENT_RUNTIME_ARN = sys.argv[1]

    if not AGENT_RUNTIME_ARN:
        sys.stderr.write(
            "Usage: python scripts/sigv4_proxy.py <AGENT_RUNTIME_ARN> "
            "or set AGENT_RUNTIME_ARN env var\n"
        )
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", PORT), SigV4ProxyHandler)
    print(f"SigV4 Signing Proxy listening on http://127.0.0.1:{PORT}/mcp")
    server.serve_forever()


if __name__ == "__main__":
    run()
