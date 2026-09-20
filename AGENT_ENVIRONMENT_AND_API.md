# Environment & API Memory — StillDone

## Current status

BOOTSTRAPPED TOOLING BASELINE (P-00.04).

Minimal reproducible Python engineering baseline frozen with deterministic locking and validation commands.

## Chosen language & tooling baseline

- **Selected StillDone Runtime Target**: CPython `3.13`. Python 3.13 (`PYTHON_3_13`) is the official, recommended direct-code runtime for Amazon Bedrock AgentCore on Amazon Linux 2023, supported through June 30, 2029 (runtime updates blocked August 31, 2029).
- **Package Ecosystem Compatibility Floor**: Python `>=3.11` in `pyproject.toml`. Retained strictly as a permissive lower bound for packaging and static tool resolution; Python 3.11 is **not** the deployment target (its AgentCore runtime updates were blocked on August 31, 2026).
- **Observed Validation Runtimes**:
  - Local Windows development: CPython `3.13.5` (Windows x86_64 host installation).
  - Linux CI: CPython `3.13.14` (installed via `uv python install 3.13` with pinned `uv 0.11.28` on Ubuntu runners).
  - `.python-version`: `3.13` (specifies the Python 3.13 series across environments).
- **Package & Dependency Manager**: `uv` pinned to exact version `0.11.28` (local host and CI), using standard PEP 621 `pyproject.toml` and deterministic cross-platform `uv.lock`.
- **Formatting & Linting**: `ruff` (`0.16.8`) (`ruff format --check .`, `ruff check .`).
- **Static Type Checking**: `mypy` (`2.3.1`) (`mypy src tests`, configured with `strict = true`).
- **Test Runner**: `pytest` (`9.1.1`) (`pytest`).
- **Cross-Platform Aggregate Validator**: `python scripts/validate.py`.
- **Continuous Integration**: `.github/workflows/ci.yml` using immutable action SHAs (`actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2`, `astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86 # v5.4.2` with `version: "0.11.28"`), running `uv python install 3.13` and `uv sync --frozen`.

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

1. **MCP Streamable HTTP**: Supported natively by the official `mcp` Python SDK (requires Python >= 3.10) with ASGI/Starlette/FastMCP integration for single-endpoint bidirectional communication.
2. **AWS Bedrock & AgentCore Runtime**: AWS first-party `boto3` SDK and Amazon Bedrock AgentCore Runtime natively support Python 3.13 (`PYTHON_3_13`, AL2023 base). Python 3.11 reached deprecation on June 30, 2026 and its runtime updates were blocked on August 31, 2026, making Python 3.13 the required modern target.
3. **Strands Agents SDK**: While AWS Strands Agents provides official SDKs for both Python (`strands-agents`) and TypeScript (`@strands-agents/sdk`), Python was selected for StillDone because of:
   - Direct compatibility with AgentCore direct-code Python 3.13 deployment;
   - Comprehensive first-party `boto3` Bedrock integration and agent tool patterns;
   - Official first-party Python SDKs for Google Calendar and Google Tasks (`google-api-python-client`, `google-auth`);
   - Single-language backend simplicity for the mission compiler, predicate engine, and MCP server without cross-process serialization boundaries.
4. **Google APIs**: `google-api-python-client` and `google-auth` provide mature, battle-tested Calendar and Tasks integration for headless/desktop OAuth and REST mutations.
5. **Open-Meteo**: Simple standard HTTP JSON retrieval via `httpx` or standard library.
6. **Structured Typing**: Pydantic v2 offers robust schema validation, JSON Schema emission for LLM tool use, and immutable contract models.
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
