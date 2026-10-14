# StillDone — Judge Reproduction & Inspection Guide

**Document ID**: `docs/REPRODUCTION.md`  
**Governing Authority**: `AGENTS.md` § 1–24; Zero Personal Spend Law (§ 12); Live-First Law (§ 9); Evidence Provenance (§ 10); Closure Contract (§ 3)  
**Target Personal Spend**: Strictly `$0.00`  
**Required Credentials**: **NONE**  

---

## 1. Quick Review Routes — Choose Your Evaluation Path

Judges and evaluators can inspect, verify, and reproduce StillDone through two distinct paths:

```
+-------------------------------------------------------------------------------------------------+
| PATH A: NO-INSTALL BROWSER REVIEW PATH (< 2 MINUTES)                                            |
| Zero dependencies, zero installation, works in any browser on any OS.                           |
| - Option 1: Open artifacts/judge_exhibit/index.html directly in Chrome, Edge, Safari, or Firefox.|
| - Option 2: Inspect Cloudflare Pages Free exhibit (*.pages.dev) when published by operator.     |
| - Option 3: Review authentic recorded live evidence logs in docs/ and the 3-minute demo video. |
+-------------------------------------------------------------------------------------------------+
                                                OR
+-------------------------------------------------------------------------------------------------+
| PATH B: SINGLE-COMMAND LOCAL REPRODUCTION (~10 SECONDS)                                         |
| Complete bit-for-bit test execution across dual isolated runtimes.                             |
| - Clone repo: git clone https://github.com/zyganali-glitch/StillDone.git                         |
| - Run: python scripts/reproduce.py                                                              |
| - 100% offline fixture verification, 0 cloud calls, 0 credentials needed, $0.00 personal spend.  |
+-------------------------------------------------------------------------------------------------+
```

---

## 2. Path A: No-Install Browser Review Path

If you do not wish to install Python or package managers, StillDone provides an immediate, rich browser review experience:

### 2.1 Local File Inspection
Open the self-contained static judge exhibit directly from your local repository clone:
- Primary bundle: [`artifacts/judge_exhibit/index.html`](../artifacts/judge_exhibit/index.html)
- Standalone single-file mirror: [`artifacts/stilldone_judge_exhibit.html`](../artifacts/stilldone_judge_exhibit.html)

**What you will see in the exhibit:**
1. **Simulated Alexa+ Surface**: Prominently labeled conversational banner disclosing the simulated front-end interface backed by the real StillDone deterministic engine.
2. **7-Step Desired-State Timeline**: From disposable seed pre-state verification through planning, task creation, human authorization pause, approved execution, receipt issuance, and external drift detection.
3. **Human Authorization Boundary**: Interactive inspection of the bounded single-use grant for `calendar.update` with cryptographic SHA-256 fingerprint.
4. **Expandable Evidence Drawers**: Clickable `<details>` disclosure elements displaying raw verified evidence properties, read-back target values, and observation timestamps.
5. **Drift Law Explanation**: Clear explanation of why the historical receipt remains `READY` while current system-of-record state is authoritative `DRIFTED`.

### 2.2 Hosted Cloudflare Pages Exhibit
- **Target URL**: `https://stilldone-judge-exhibit.pages.dev`
- **Current Status**: **`NOT_PUBLISHED / OPERATOR_ACTION_REQUIRED`**  
  *(In strict accordance with `AGENTS.md` § 12, automated CI does not hold personal operator Cloudflare credentials. The deployable static bundle is built and verified at `artifacts/judge_exhibit/index.html`; see [`docs/P19_04_PUBLIC_JUDGE_EXHIBIT.md`](P19_04_PUBLIC_JUDGE_EXHIBIT.md) for step-by-step Turkish operator guidance).*

### 2.3 Recorded Live Video & Evidence Ledger
You can review the authentic recorded live integration evidence without executing cloud calls:
- **AWS Bedrock Nova Micro Reasoning**: [`docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`](P01_02_LIVE_BEDROCK_EVIDENCE.md) and [`docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`](P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md).
- **AWS Bedrock AgentCore Streamable HTTP Server**: [`docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`](P05_06_LIVE_REMOTE_MCP_EVIDENCE.md).
- **Google Calendar & Tasks Read-Back Verifiers**: [`docs/P13_KILLER_MISSION_AUDIT.md`](P13_KILLER_MISSION_AUDIT.md).
- **October 14, 2026 Operator AWS Observations**: [`docs/P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md`](P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md).

---

## 3. Truth Matrix — Real Technology, Fixture Tests & Blocked Paths

StillDone strictly adheres to the **Evidence Law** (`AGENTS.md` § 10): Result state is fundamentally separate from evidence provenance.

| Component / Capability | Provenance / State | Exact Milestone | Evidence Documentation | Truth Boundary & Details |
| :--- | :--- | :--- | :--- | :--- |
| **AWS Bedrock Nova Micro Reasoning** | `RECORDED_LIVE` | P-01.02 & P-07.06 | [`docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`](P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md) | Real model invocation (`amazon.nova-micro-v1:0` in `us-east-1`, 3.463s latency, zero tool execution authority). |
| **AWS Bedrock AgentCore Runtime** | `RECORDED_LIVE` | P-05.06 | [`docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`](P05_06_LIVE_REMOTE_MCP_EVIDENCE.md) | Real serverless CodeZip microVM deployed in `us-east-1` on port 8000; Streamable HTTP MCP tools tested via SigV4 signing bridge. |
| **Google Calendar API Integration** | `RECORDED_LIVE` | P-01.03 & P-11.06 | [`docs/P01_LIVE_FEASIBILITY.md`](P01_LIVE_FEASIBILITY.md) | Real Google Calendar v3 events created, updated, and read back in dedicated disposable demo calendar. |
| **Google Tasks API Integration** | `RECORDED_LIVE` | P-01.04 | [`docs/P01_LIVE_FEASIBILITY.md`](P01_LIVE_FEASIBILITY.md) | Real Google Tasks v1 task creation and independent read-back in demo task list. |
| **Open-Meteo Weather API Integration** | `RECORDED_LIVE` | P-01.05 | [`docs/P01_LIVE_FEASIBILITY.md`](P01_LIVE_FEASIBILITY.md) | Real weather forecast read from Open-Meteo under CC BY 4.0 data attribution. |
| **Full Killer Mission End-to-End Slice** | `FIXTURE / LOCAL_EXECUTION` | P-13.01–P-13.07 | [`docs/P13_KILLER_MISSION_AUDIT.md`](P13_KILLER_MISSION_AUDIT.md) | Complete multi-step state machine, approval gating, and drift reconciliation evaluated in deterministic regression mode. |
| **Current 24/7 Remote MCP Endpoint** | `BLOCKED / NOT_RUN` | P-19.03 | [`docs/P19_03_REMOTE_MCP_DEPLOYMENT_PREFLIGHT.md`](P19_03_REMOTE_MCP_DEPLOYMENT_PREFLIGHT.md) | Continuous 24/7 cloud microVM hosting is intentionally stopped to guarantee $0.00 personal spend. |
| **Current Live Cloud Mutations** | `BLOCKED_LIVE / NOT_RUN` | P-13.02 / P-16.03 | [`docs/P13_KILLER_MISSION_AUDIT.md`](P13_KILLER_MISSION_AUDIT.md) | Live cloud write paths require authenticated operator credentials and are safely gated fail-closed during judge evaluation. |

---

## 4. How Historical Receipts and Current State Differ

A central innovation of StillDone is the strict separation between:
1. **`ReceiptProjection` (`is_historical=True`)**:
   - An immutable cryptographic snapshot of the mission state at the exact moment it achieved `READY`.
   - Content-addressed via domain-separated SHA-256 (`stilldone:receipt-projection:v1`).
   - Binds the exact mission snapshot, verified evidence IDs, predicate satisfactions, and issuance timestamp.
   - **Permanence Law**: Once issued, a historical receipt is permanent audit evidence. It is never overwritten, modified, or deleted.
2. **`CurrentStateProjection` (`is_historical=False`)**:
   - The authoritative current system-of-record state evaluated dynamically from fresh read-back observations.
   - If external reality changes (e.g. an event is moved, a task is deleted, or weather shifts), the mission state is downgraded to `DRIFTED`.
   - **Current Truth Law**: Historical receipts never override current reality. The user is truthfully informed: *"You were ready at 07:30, but your calendar has moved to 08:00 externally."*

---

## 5. Dual Python Environment Architecture & Isolation Truth

### 5.1 Why Two Runtimes Are Required
StillDone strictly enforces two isolated dependency environments with zero resolver overrides:
- **Upstream Dependency Incompatibility**: StillDone Core requires `mcp >= 2.2.0` for modern Streamable HTTP server features. However, AWS's `strands-agents == 1.57.2` upstream officially requires `mcp >= 1.23.0, < 2.2.0`. These version requirements do not intersect.
- **Architectural Solution**: Rather than forcing fragile resolver hacks or overriding dependencies, StillDone separates:
  1. **StillDone Core / MCP Runtime** (`pyproject.toml` at repo root): Owns the MCP server, deterministic state machine, evidence ledger, and adapters. Resolved to `mcp == 2.2.0`.
  2. **Strands Planner Runtime** (`runtimes/strands_planner/pyproject.toml`): Owns non-authoritative plan proposal generation only. Resolved to `strands-agents == 1.57.2` and transitive `mcp == 2.1.1`.
- **Packaging Purity**: ONE repository, ONE canonical codebase (`src/stilldone`). No duplicated business logic.

### 5.2 Package Setup Downloads vs. Cloud API Calls
> [!IMPORTANT]
> **Setup Downloads Are Not Cloud API Calls**:
> When running `python scripts/reproduce.py`, the `uv` package manager downloads standard open-source Python packages (wheels) from PyPI to build local virtual environments (`.venv`). These downloads are purely package installation operations. StillDone makes **ZERO** cloud provider API calls (0 AWS Bedrock, 0 AWS AgentCore, 0 Google Cloud, 0 Open-Meteo) during setup, testing, or judge reproduction.

---

## 6. Path B: Single-Command Local Reproduction

### 6.1 System Requirements

| Prerequisite | Minimum Version | Tested in CI |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11, Ubuntu 22.04/24.04, macOS 13+ | Ubuntu Linux (`ubuntu-latest`) |
| **Package Manager** | Astral `uv >= 0.11.28` | `0.11.28` / `0.12.23` |
| **Python** | Python `3.11`, `3.12`, or `3.13` | Python `3.13` (Core), `3.12` (Planner) |

Installing `uv` (if not installed):
- **Windows (PowerShell)**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **macOS / Linux**: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 6.2 Quick Reproduction (~10 Seconds)
```bash
git clone https://github.com/zyganali-glitch/StillDone.git
cd StillDone

# Run automated reproduction
python scripts/reproduce.py
```

### 6.3 What the Reproduction Script Verifies
1. Validates that `uv` and supported Python versions are present.
2. Synchronizes both isolated environments strictly from their pinned lockfiles:
   - `uv sync --frozen` (Core environment)
   - `uv sync --frozen --project runtimes/strands_planner` (Strands Planner environment)
3. Enforces dependency bounds on both environments:
   - Core: `mcp >= 2.2.0`
   - Strands Planner: `strands-agents == 1.57.2`, transitive `mcp < 2.2.0`
4. Validates production imports across the isolated runtime boundary via `PYTHONPATH=src`.
5. Executes the quick smoke verification suite covering domain models, demo isolation, approval binding, redaction, receipts, planning contracts, and standalone wheel smoke.
6. Emits a sanitized summary confirming 0 external calls, 0 credentials needed, and $0.00 personal spend.

---

## 7. Advanced Reproduction Options

### 7.1 Full Test Suite Execution (~2 Minutes)
To run the complete test suite across both runtimes (all 2,500+ unit and adversarial tests):
```bash
python scripts/reproduce.py --full
```

### 7.2 Check Only (Without Network Synchronization)
If virtual environments already exist, execute 100% offline without modifying environments:
```bash
python scripts/reproduce.py --check-only
```

### 7.3 Sync Dependencies Only
To synchronize dependencies without running tests:
```bash
python scripts/reproduce.py --sync-only
```

### 7.4 Manual Step-by-Step Reproduction
If you prefer running commands individually:

```bash
# 1. Sync Core environment
uv sync --frozen

# 2. Sync Strands Planner environment
uv sync --frozen --project runtimes/strands_planner

# 3. Format and lint checks
uv run ruff format --check .
uv run ruff check .

# 4. Type checking Core
uv run mypy src tests --exclude "tests[\\/]planning[\\/]test_(strands_agent|rejection_hardening|planner_metadata)\.py"

# 5. Type checking Strands Planner
uv run --project runtimes/strands_planner mypy src/stilldone/planning tests/planning

# 6. Core tests (MCP server, state machine, evidence ledger, adapters)
uv run pytest --ignore=tests/planning/test_strands_agent.py --ignore=tests/planning/test_rejection_hardening.py --ignore=tests/planning/test_planner_metadata.py

# 7. Strands Planner tests
uv run --project runtimes/strands_planner pytest tests/planning tests/domain

# 8. Standalone open-source mcp-verify wheel smoke
uv run python scripts/smoke_mcp_verify_wheel.py

# 9. Public Judge Exhibit generation & verification
uv run python scripts/p19_04_build_judge_exhibit.py
```

---

## 8. Troubleshooting & Common Questions

| Question / Issue | Cause | Explanation / Solution |
| :--- | :--- | :--- |
| **Do I need an AWS account or API keys?** | None required | All reproduction tests execute under deterministic `FIXTURE` and `LOCAL_EXECUTION` provenance. StillDone requires zero AWS credentials to verify. |
| **Do I need Google OAuth credentials?** | None required | Demo calendar and tasks tests use verified in-memory test doubles with identical HTTP/API contract semantics. |
| **Why are there two `uv.lock` files?** | Dependency isolation | The Core MCP server requires `mcp >= 2.2.0`, while Strands requires `mcp < 2.2.0`. They are intentionally isolated to avoid resolver conflicts. |
| **`PREREQUISITE MISSING: Astral 'uv'`** | `uv` not in `PATH` | Run the one-line install command above or install via `pip install uv`. |
| **Can I run under Python 3.11 or 3.12?** | Supported | StillDone supports Python 3.11, 3.12, and 3.13. |
