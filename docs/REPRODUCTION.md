# StillDone — Clean-Checkout Reproduction & Judge Guide

This guide provides the official instructions to reproduce and verify StillDone from a pristine clone of the public repository.

---

## 1. Zero Spend & Zero Credentials Guarantee

- **Target Personal Spend:** `$0.00`.
- **Cloud Credentials Required:** **NONE**.
- **External API Calls:** **0**.
- **Account Requirements:** No AWS account, no Google Cloud project, and no paid subscriptions are required to reproduce and verify the StillDone codebase.

All reproducible test suites execute deterministically under `FIXTURE` and `LOCAL_EXECUTION` provenance using isolated in-memory fakes and strict contract assertions.

> [!IMPORTANT]
> **Initial Setup vs. Cloud Provider Network Separation:**
> Initial repository setup (`python scripts/reproduce.py`) downloads public, open-source Python wheels from PyPI via `uv sync --frozen` to construct the two local isolated virtual environments. These package-manager downloads are **strictly distinct** from live cloud provider calls. StillDone requires **zero** cloud credentials and executes **zero** live AWS Bedrock, AWS AgentCore, Google Calendar, Google Tasks, or Open-Meteo calls during setup, testing, or judge reproduction.
> When `--check-only` is passed, **every descendant package-management operation** (including wheel build, isolated venv creation, and test smoke installation) is strictly guaranteed 100% offline.

> [!NOTE]
> Historical live AWS Bedrock/AgentCore and Google Calendar/Tasks execution evidence is recorded and preserved in `docs/` (e.g. [`P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`](P05_06_LIVE_REMOTE_MCP_EVIDENCE.md) and [`P01_02_LIVE_BEDROCK_EVIDENCE.md`](P01_02_LIVE_BEDROCK_EVIDENCE.md)) under `RECORDED_LIVE` provenance.
> The canonical killer-mission milestone audit ([`P13_KILLER_MISSION_AUDIT.md`](P13_KILLER_MISSION_AUDIT.md)) is evaluated in deterministic `FIXTURE` regression mode with live cloud portions preserved as `BLOCKED_LIVE / NOT_RUN`.

---

## 2. System Requirements & Supported Versions

| Component | Supported Version Range | CI Tested Version |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11, Ubuntu 22.04/24.04, macOS 13+ | Ubuntu Linux (`ubuntu-latest`) |
| **Package Manager** | `uv >= 0.11.28` | `0.11.28` / `0.12.23` |
| **Core / MCP Python** | Python `3.11`, `3.12`, `3.13` | `3.13` (`.python-version: 3.13`) |
| **Strands Planner Python** | Python `3.11`, `3.12` | `3.12` |

### Installing `uv` (if not already installed)

StillDone uses Astral's `uv` for reproducible, high-speed multi-environment synchronization.

- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

---

## 3. Two-Runtime Isolated Dependency Architecture

StillDone strictly isolates two distinct runtime environments:

1. **StillDone Core / MCP Runtime** (`pyproject.toml` at repo root):
   - Requires `mcp >= 2.2.0` for the modern Streamable HTTP MCP server spine.
   - Pinned by root [`uv.lock`](../uv.lock).
2. **Strands Planner Runtime** (`runtimes/strands_planner/pyproject.toml`):
   - Requires `strands-agents == 1.57.2`, which upstream pins `mcp >= 1.23.0, < 2.2.0`.
   - Pinned by [`runtimes/strands_planner/uv.lock`](../runtimes/strands_planner/uv.lock).

**Architectural Law:** The two environments have non-intersecting MCP SDK dependency requirements. They must **never** be merged or forced into a single global environment.

---

## 4. Quick-Start Reproduction (One Command)

From a fresh clone of the repository:

```bash
git clone https://github.com/zyganali-glitch/StillDone.git
cd StillDone

# Run automated clean-checkout reproduction (~10 seconds)
python scripts/reproduce.py
```

### What this script does automatically:
1. Verifies that `uv` and supported Python versions are present.
2. Synchronizes both isolated environments strictly from their pinned lockfiles:
   - `uv sync --frozen` (Core environment)
   - `uv sync --frozen --project runtimes/strands_planner` (Strands environment)
3. Asserts the MCP dependency bounds on both environments:
   - Core: `mcp >= 2.2.0`
   - Strands Planner: `strands-agents == 1.57.2`, transitive `mcp < 2.2.0`
4. Validates production imports across the isolated runtime boundary via `PYTHONPATH=src`.
5. Executes the quick smoke verification suite covering domain models, demo isolation, approval binding, redaction, receipts, planning contracts, and standalone wheel smoke.
6. Emits a sanitized summary confirming 0 external calls, 0 credentials needed, and $0.00 personal spend.

---

## 5. Advanced Reproduction Options

### Full Test Suite Execution (~2 minutes)

To run the complete test suite across both runtimes (all 2,500+ unit and adversarial tests):

```bash
python scripts/reproduce.py --full
```

### Check Only (Without Network Sync)

If the virtual environments are already installed:

```bash
python scripts/reproduce.py --check-only
```

### Sync Dependencies Only

To prepare environments without running tests:

```bash
python scripts/reproduce.py --sync-only
```

### Direct Manual Step Reproduction

If you prefer to run steps individually:

```bash
# 1. Sync Core environment
uv sync --frozen

# 2. Sync Strands Planner environment
uv sync --frozen --project runtimes/strands_planner

# 3. Run Core formatting and linting
uv run ruff format --check .
uv run ruff check .

# 4. Run Core type checking
uv run mypy src tests --exclude "tests[\\/]planning[\\/]test_(strands_agent|rejection_hardening|planner_metadata)\.py"

# 5. Run Core tests
uv run pytest --ignore=tests/planning/test_strands_agent.py --ignore=tests/planning/test_rejection_hardening.py --ignore=tests/planning/test_planner_metadata.py

# 6. Run Strands Planner tests
uv run --project runtimes/strands_planner pytest tests/planning tests/domain

# 7. Run standalone mcp-verify wheel smoke
uv run python scripts/smoke_mcp_verify_wheel.py
```

---

## 6. Troubleshooting & Helpful Error Handling

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| `PREREQUISITE MISSING: Astral 'uv'` | `uv` is not installed or not in system `PATH`. | Run the one-line install command above or `pip install uv`. |
| `Python >= 3.11 required` | The host Python is 3.10 or older. | Install Python 3.12 or 3.13, or let `uv` download it automatically via `uv python install 3.13`. |
| `Lockfile mismatch` | Modified dependencies without updating lockfile. | StillDone reproduction mandates `--frozen` to guarantee exact bit-for-bit judge reproduction. Re-run `git status` to ensure working tree is clean. |
| Incompatible MCP conflict | Merged the two environments. | Do not install dependencies from root into `runtimes/strands_planner` or vice-versa. Always use `--project runtimes/strands_planner`. |
