# Environment & API Memory — StillDone

## Current status

BOOTSTRAPPED TOOLING BASELINE (P-00.04).

Minimal reproducible Python engineering baseline frozen with deterministic locking and validation commands.

## Chosen language & tooling baseline

- **Primary Runtime**: Python `>=3.11` (actively validated on CPython `3.13.5` on Windows and Linux CI).
- **Package & Dependency Manager**: `uv` (v0.11.28+), using standard PEP 621 `pyproject.toml` and deterministic cross-platform `uv.lock`.
- **Formatting & Linting**: `ruff` (`ruff format --check .`, `ruff check .`).
- **Static Type Checking**: `mypy` (`mypy src tests`, configured with `strict = true`).
- **Test Runner**: `pytest` (`pytest`).
- **Cross-Platform Aggregate Validator**: `python scripts/validate.py`.
- **Continuous Integration**: `.github/workflows/ci.yml` (free Ubuntu runner with `astral-sh/setup-uv` and `uv sync --frozen`).

## Canonical validation commands

All commands return non-zero on failure, require zero network access after initial sync, and require zero cloud credentials:

| Purpose | Canonical Command |
|---|---|
| Dependency sync (clean / frozen) | `uv sync --frozen` |
| Formatting check | `uv run ruff format --check .` |
| Lint check | `uv run ruff check .` |
| Static type check | `uv run mypy src tests` |
| Test suite | `uv run pytest` |
| Aggregate validation | `uv run python scripts/validate.py` |

## Decisive toolchain selection rationale

1. **MCP Streamable HTTP**: Supported natively by official `mcp` Python SDK (requires Python >= 3.10) with ASGI/Starlette/FastMCP integration.
2. **AWS Bedrock & AgentCore**: AWS first-party `boto3` SDK and AgentCore serverless runtime have first-class Python support and reference implementations.
3. **Strands Agents SDK**: `strands-agents` was released by AWS primarily as a Python package (requires Python >= 3.10) with deep Bedrock and MCP integrations.
4. **Google APIs**: `google-api-python-client` and `google-auth` provide mature, battle-tested Calendar and Tasks integration.
5. **Open-Meteo**: Simple standard HTTP JSON retrieval via `httpx` or standard library.
6. **Structured Typing**: Pydantic v2 offers unmatched schema validation, JSON Schema emission for LLM tool use, and immutable contract support.
7. **Cross-Platform Reproducibility**: `uv` provides universal cross-platform lockfiles (`uv.lock`) without native build hurdles on Windows or Linux.

## Dependencies policy & status

- **Runtime dependencies**: `[]` (empty; no speculative SDKs added in P-00.04).
- **Development dependencies**: `ruff`, `mypy`, `pytest` pinned deterministically in `uv.lock`.
- Real provider SDKs (`mcp`, `boto3`, `strands-agents`, `google-api-python-client`, `httpx`) will be introduced in their exact Master Plan tasks.

## Intended external systems (Pending P-01)

Primary track/runtime:
- MCP Streamable HTTP

Preferred AWS path, pending P-01:
- Amazon Bedrock
- Strands SDK
- Amazon Bedrock AgentCore

Canonical external demo systems:
- Google Calendar API
- Google Tasks API
- Open-Meteo

Deferred:
- Gmail
- payments
- browser automation
- health APIs

## Secrets

Expected future secrets/config may include:
- AWS auth through approved local/account mechanism;
- Google OAuth client configuration;
- Google OAuth tokens.

Never commit them.

Use `.env.example` only after exact variables exist.
