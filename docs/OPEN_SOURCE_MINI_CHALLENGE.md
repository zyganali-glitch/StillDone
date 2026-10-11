# Open Source Mini Challenge: `mcp-verify` (Phase P-17)

**Track**: Open Source Mini Challenge / Build, Ship, Shape: Amazon Developer Hackathon  
**Package**: `mcp-verify` (`packages/mcp_verify/`)  
**License**: Apache-2.0 (Apache License 2.0)  
**Repository Path**: `packages/mcp_verify/`  

---

## 1. Problem Statement & Motivation

The Model Context Protocol (MCP) has rapidly become the standard open protocol for connecting AI models to external tools, databases, and APIs. However, current MCP implementations suffer from a critical safety flaw:

> **A tool execution response (`200 OK`) does not prove that an outcome was actually achieved.**

When an LLM agent calls a mutation tool:
1. The remote service might return `200 OK` while the requested change was queued, dropped, or corrupted.
2. The agent has no standard way to verify that the real-world state matches the intended outcome.
3. If the resource state drifts later, the agent continues operating under false assumptions of success.

Rather than keeping StillDone's verification logic proprietary, we extracted the core verification engine into **`mcp-verify`**: a zero-dependency, lightweight, open-source middleware that brings deterministic read-back verification to **any** MCP tool server.

---

## 2. Architecture & Design

`mcp-verify` establishes the **Verifiable Tool Invariant**:

$$\text{INTENT} \to \text{MUTATION} \to \textbf{INDEPENDENT READ-BACK} \to \textbf{PREDICATE EVALUATION} \to \text{VERIFIED}$$

```
+---------------------------------------------------------------------------------+
| LLM Agent (Claude, Nova, Alexa+)                                                |
+---------------------------------------------------------------------------------+
                                      |
                         Calls MCP Tool ("calendar_update")
                                      v
+---------------------------------------------------------------------------------+
| mcp-verify Interception Middleware                                             |
|                                                                                 |
| 1. Execute Mutation Tool -----------------------------> Remote API (e.g. 200 OK) |
|                                                                                 |
| 2. Perform INDEPENDENT Read-Back ---------------------> Query API (GET state)   |
|                                                                                 |
| 3. Evaluate Verification Predicate:                                             |
|    - Expected: start_time == 07:30                                              |
|    - Observed: start_time == 07:30  --> Status: VERIFIED                        |
|    - Observed: start_time == 08:00  --> Status: CONTRADICTED                    |
|                                                                                 |
| 4. Return VerifiableOutcome to Agent:                                           |
|    - is_verified: True/False                                                    |
|    - status: VERIFIED | CONTRADICTED | READ_BACK_FAILED                         |
+---------------------------------------------------------------------------------+
```

### Core Components
1. **`VerificationPredicate`** (`contracts.py`):
   Defines expected post-mutation conditions using typed operators (`EQUALS`, `NOT_EQUALS`, `CONTAINS`, `EXISTS`, `GREATER_THAN`, `LESS_THAN`).
2. **`VerifiableToolMiddleware`** (`middleware.py`):
   Decorator-based middleware intercepting tool executions, triggering separate read-back handlers, and ensuring write success alone never confers verified status.
3. **`Verifier`** (`verifier.py`):
   Deterministic predicate evaluation engine calculating latency deltas, detecting contradictions, and sanitizing error details.

---

## 3. Provenance & Licensing (P-17.02)

- **License**: Apache License 2.0 (`packages/mcp_verify/LICENSE`).
- **Clean-Room Implementation**: 100% clean-room authored; zero lines copied from legacy or third-party proprietary donors.
- **Dependencies**: Zero external dependencies beyond standard library (`typing-extensions` optional).
- **Python Compatibility**: Python 3.11, 3.12, 3.13 tested.

---

## 4. Real Integration Example (P-17.04)

StillDone provides both a genuine MCP client/server protocol transport integration and an in-memory fixture demo:
1. **Real MCP Protocol Transport Integration (`packages/mcp_verify/examples/real_mcp_integration.py`)**:
   - Spawns an official `MCPServer` in a subprocess using stdio transport.
   - Connects using official `ClientSession` over real `stdio_client` transport.
   - Registers a genuine MCP mutation tool (`create_task_item`), a divergent mutation tool (`create_faulty_task_item`), and a separate MCP read-back tool (`get_task_item`).
   - Intercepts tool calls via `VerifiableToolMiddleware`, invokes mutation crossing the stdio transport, executes separate read-back tool crossing stdio transport, and evaluates the `VerificationPredicate`.
   - Proves both successful verification (`status=VERIFIED`) and detected discrepancies (`status=CONTRADICTED`) over real MCP client/server transport.
2. **In-Memory Fixture Example (`packages/mcp_verify/examples/verifiable_calendar_tool.py`)**:
   - Demonstrates verification mechanics against a local in-memory calendar mock without MCP SDK dependencies (`[FIXTURE EXAMPLE]`).

---

## 5. Standalone Packaging, Wheel Build & Publication Boundary (P-17.03, P-17.05)

- **Build Backend**: `hatchling` via standard PEP 621 `pyproject.toml`.
- **Reproducible Package Wheel Build & Isolated Venv Smoke Validation**:
  - `scripts/smoke_mcp_verify_wheel.py` deterministically builds standard `.whl` distribution artifacts via `uv build --wheel packages/mcp_verify`.
  - Creates an isolated temporary virtual environment outside the source tree.
  - Installs the built wheel via `pip`.
  - Ensures source checkout is strictly excluded from `sys.path`.
  - Imports `mcp_verify` directly from `site-packages` and executes a verification contract end-to-end.
  - Wired directly into `scripts/validate.py` (`validate_core_mcp`).
- **Standalone Package Tests**: `packages/mcp_verify/tests/test_mcp_verify.py` passing (6 focused tests).
- **Cross-Repository Tests**: `tests/test_phase_p17_open_source_mini_challenge.py` passing (7 focused tests).
- **Publication Status (P-17.05)**:
  - External publication (to public PyPI or public standalone GitHub repository) is classified as `BLOCKED_EXTERNAL / NOT_RUN`.
  - Publishing is an external irreversible action that requires explicit operator credentials and authorization. Local wheel build, clean venv installation, and metadata purity are 100% verified.
