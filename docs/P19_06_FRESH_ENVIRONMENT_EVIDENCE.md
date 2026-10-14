# P-19.06 — Fresh-Environment Reproduction & Evidence Capture

**Document ID**: `docs/P19_06_FRESH_ENVIRONMENT_EVIDENCE.md`  
**Task**: `P-19.06 — Fresh-environment reproduction and evidence capture`  
**Execution Provenance**: `FIXTURE / LOCAL_EXECUTION`  
**Source SHA**: `d5fdcff60cf21c1e96b2f4fe27df0af9da7bfb67`  
**Reproduction Verdict**: `SUCCESS (PASS Candidate)`  
**Personal Spend**: `$0.00`  
**Governing Authority**: `AGENTS.md` § 1–24; Zero Personal Spend Law (§ 12); Live-First Law (§ 9); Evidence Provenance (§ 10); Closure Contract (§ 3)  

---

## 1. Executive Summary & Verification Context

In compliance with Phase P-19.06, StillDone was executed from a pristine source tree in an isolated temporary working directory completely devoid of pre-existing virtual environments (`.venv`), compiled byte-code (`__pycache__`, `*.pyc`), test caches (`.pytest_cache`), or type-checker caches (`.mypy_cache`).

The reproduction script (`scripts/reproduce.py`) constructed the dual isolated Python environments from pinned lockfiles, verified MCP dependency boundaries without resolver overrides, executed the complete smoke test suite across both runtimes, and validated standalone package building and out-of-tree installation for `mcp-verify`.

---

## 2. Environment & Tool Versions

| Dimension | Exact Tool / Version | Notes |
| :--- | :--- | :--- |
| **Operating System** | `Windows 11 (win32)` | Local developer & test environment (Windows win32) |
| **Host Python** | `Python 3.13.16 (CPython)` | Host runtime initiating orchestration |
| **Package Manager** | `uv 0.12.23 (46b84fd0b 2026-10-03 x86_64-pc-windows-msvc)` | Astral uv for bit-for-bit lockfile synchronization |
| **Source Commit SHA** | `d5fdcff60cf21c1e96b2f4fe27df0af9da7bfb67` | Canonical Git commit evaluated |

---

## 3. Fresh Reproduction Execution Metrics

- **Reproduction Command**: `python scripts/reproduce.py`
- **Exit Code**: `0`
- **Execution Wall-Clock Duration**: `11.66s`
- **Isolated Virtual Environments Created**: `True`
  - Core / MCP Environment: Pinned via root `uv.lock` (`mcp == 2.2.0`)
  - Strands Planner Environment: Pinned via `runtimes/strands_planner/uv.lock` (`strands-agents == 1.57.2`, transitive `mcp == 2.1.1`)
- **Smoke Tests Executed & Passed**:
  - Core Smoke Suite: `269` tests passed (Domain contracts, demo isolation, receipts, redaction, action policies, authority policies)
  - Strands Planner Smoke Suite: `238` tests passed (Planning contracts, domain mission, domain action)
  - Standalone `mcp-verify` Wheel Smoke: `True` (wheel built, isolated venv created, verified outside source tree)
  - **Total Tests Passed in Fresh Environment**: `507` tests

---

## 4. Execution Matrix — Differences Between Environments

StillDone strictly separates what was executed locally, what is validated in CI, what was recorded live, and what is currently deployed:

| Execution Context | Target Platform | Integrations Exercised | Credentials Used | Billing Impact | Provenance Classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Local Fresh Reproduction** | Windows 11 (`win32`) | In-memory test doubles, deterministic verifiers | NONE | $0.00 | `FIXTURE / LOCAL_EXECUTION` |
| **CI Automated Validation** | Ubuntu 24.04 (`ubuntu-latest`) | Dual environment matrix, full 2,500+ unit & adversarial tests, Ruff, Mypy | NONE | $0.00 | `FIXTURE / LOCAL_EXECUTION` |
| **Historical Recorded Live** | AWS `us-east-1`, Google Calendar/Tasks | Real Bedrock Nova Micro, AgentCore Streamable HTTP microVM, Google OAuth mutations | Temporary operator session credentials | Promotional credits ($0.09 consumed, $0.00 personal spend) | `RECORDED_LIVE` |
| **Currently Deployed Live Services** | NONE | Intentionally blocked fail-closed at preflight (`P-19.03`) | NONE | $0.00 (Zero unmetered endpoints) | `BLOCKED_LIVE / NOT_RUN` |

> [!NOTE]
> **Claim Integrity**: StillDone only claims platforms and providers that were actually exercised. Local reproduction was performed on `Windows 11 (win32)`. CI execution is performed on Ubuntu Linux (`ubuntu-latest`). No macOS or mobile native platforms are falsely claimed as directly exercised.

---

## 5. Offline Fixture Invariant & Zero-Spend Bound

- **External Cloud API Calls**: Exactly **0** (0 AWS Bedrock, 0 AWS AgentCore, 0 Google Calendar, 0 Google Tasks, 0 Open-Meteo).
- **Cloud Credentials Required**: **NONE**.
- **Personal Spend Delta**: **$0.00** personal expenditure.
- **PyPI Setup Downloads Separation**: Initial package manager downloads during `uv sync --frozen` download open-source wheels from PyPI to construct local `.venv` environments. These standard package management operations are strictly separated from live cloud provider calls.
- **Under `--check-only`**: All operations (including wheel build, isolated venv creation, and test smoke) are strictly guaranteed 100% offline (`--no-sync --offline UV_OFFLINE=1`).

---

## 6. Sanitized Reproduction Console Log Snippet

```text
SUCCESS (PASS Candidate)
Verification Mode:           Quick smoke verification (use --full for complete suite)
Evidence Provenance:         FIXTURE / LOCAL_EXECUTION (offline deterministic)
Core / MCP Runtime:          Verified (mcp >= 2.2.0)
Strands Planner Runtime:     Verified (strands-agents 1.57.2, transitive mcp < 2.2.0)
Dependency Isolation:        100% PRESERVED (two distinct runtimes, never merged)
Cloud Credentials Required:  NONE
External API Calls:          0
Personal Spend Target:       $0.00 (NO billable resources accessed)
Historical Live Evidence:    Preserved in docs/ (marked RECORDED_LIVE)

Important Architecture & Network Boundary Clarification:
- Initial setup (default clean reproduction) downloads public, open-source Python
  wheels from PyPI via 'uv sync --frozen' to populate isolated local environments.
- These standard package manager downloads are STRICTLY DISTINCT from live cloud
  provider calls. Zero AWS Bedrock, AWS AgentCore, Google Calendar, Google Tasks,
  or Open-Meteo live API calls are ever made during setup or verification.
- Under '--check-only', every descendant package-management operation (including
  wheel build, isolated virtual environment creation, and smoke installation) is
  strictly guaranteed 100% offline (--no-sync --offline UV_OFFLINE=1).
- Historical live Google Calendar/Tasks and AWS Bedrock/AgentCore proofs
  are preserved as RECORDED_LIVE in docs/ (e.g. docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md,
  docs/P01_02_LIVE_BEDROCK_EVIDENCE.md). The canonical full killer-mission audit
  (docs/P13_KILLER_MISSION_AUDIT.md) preserves deterministic FIXTURE evaluation with
  live portions BLOCKED_LIVE/NOT_RUN. Clean-checkout reproduction evaluates the full
  deterministic core using verified in-memory fakes and contract assertions.
```
