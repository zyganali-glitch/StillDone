# StillDone — Strands Planner Runtime

Isolated runtime environment for the StillDone non-authoritative Strands planning agent (Phase P-07).

## Architecture & Dependency Isolation

- **StillDone Core / MCP Runtime** (`pyproject.toml` at repo root) requires `mcp>=2.2.0` for open-standard Streamable HTTP MCP server spine.
- **Strands Agents 1.57.2** upstream package pins `mcp>=1.23.0,<2.2`.
- Because these version sets do not intersect, the two runtimes are strictly dependency-isolated.
- This runtime owns ONLY:
  - P-07 planner model execution (`strands.Agent`, `BedrockModel`);
  - Candidate plan proposal production (`CandidatePlanProposal`);
  - Deterministic planner runtime metadata (`PlannerRuntimeMetadata`).
- This runtime owns ZERO:
  - Execution or mutations;
  - Fact authority or independent read-back;
  - `VERIFIED` or `READY` promotion;
  - Direct evidence ledger appends.
- Canonical StillDone contracts and domain logic in `../../src/stilldone` are reused directly without duplication.

## Production Invocation Contract (P-07.06+)

To execute or import StillDone planning capabilities from the isolated planner environment without installing root dependencies (which would pull conflicting `mcp>=2.2.0`), supply the canonical repo `src` via `PYTHONPATH`:

**POSIX (Linux / macOS / CI):**
```bash
PYTHONPATH=src uv run --project runtimes/strands_planner python -c "import stilldone; from stilldone.planning.strands_agent import plan_with_strands; from stilldone.planning.metadata import create_planner_runtime_metadata"
```

**Windows PowerShell:**
```powershell
$env:PYTHONPATH = "src"; uv run --project runtimes/strands_planner python -c "import stilldone; from stilldone.planning.strands_agent import plan_with_strands; from stilldone.planning.metadata import create_planner_runtime_metadata"
```
