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

`packages/mcp_verify/examples/verifiable_calendar_tool.py` proves `mcp-verify` against two scenarios:
1. **Normal Verified Write**: Tool updates departure time to 07:30; independent read-back verifies start_time matches 07:30 (`VERIFIED`).
2. **Corrupted Write**: Tool returns `200 OK`, but backend stores corrupted 08:00 departure; `mcp-verify` intercepts the discrepancy and flags `CONTRADICTED`, preventing false agent confidence.

---

## 5. Standalone Packaging & Test Proofs (P-17.03, P-17.05)

- **Build Backend**: `hatchling` via standard PEP 621 `pyproject.toml`.
- **Standalone Package Tests**: `packages/mcp_verify/tests/test_mcp_verify.py` passing (5 focused tests).
- **Cross-Repository Tests**: `tests/test_phase_p17_open_source_mini_challenge.py` passing (6 focused tests).
