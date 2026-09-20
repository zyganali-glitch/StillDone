# StillDone Architecture

## Status

`ARCHITECTURE TARGET v0 — AWS final service selection UNFROZEN until P-01 live feasibility closure`

## Design rule

The LLM sits beside deterministic execution truth, not above it.

## Target component model

```text
Simulated Alexa+ Client Surface (if partner access unavailable)
                         |
                         v
Remote MCP Server — Streamable HTTP
                         |
                         v
                Mission Intake
                         |
             +-----------+-----------+
             |                       |
             v                       v
      Model/Strands Planner    Deterministic Contract Compiler
             |                       |
             +-----------+-----------+
                         |
                         v
                  Authority Engine
                         |
                         v
                  Mission Executor
               /         |          \
              /          |           \
     Google Calendar  Google Tasks  Open-Meteo
              \          |           /
               \         |          /
                         v
               Independent Readback
                         |
                         v
              Predicate / Drift Engine
                         |
                         v
          Mission Ledger + Evidence Store
                         |
                         v
         Voice Summary + Visual Receipt
```

## Preferred AWS direction

Competition preference, subject to P-01 proof:
- Amazon Bedrock for real model inference;
- Strands SDK for the real agent/planning path;
- Amazon Bedrock AgentCore Runtime for deployment/runtime if account/region/cost feasibility is proven;
- one AWS persistence/state service if it materially improves the architecture and remains inside zero-cost/promotional limits.

Do not freeze DynamoDB, Step Functions, AgentCore Memory, Gateway, Identity, Lambda, or EventBridge merely because they are available. Each must earn its place.

## Provider-neutral boundaries

Core domain must not import provider SDKs.

Suggested package boundaries after tooling is chosen:

```text
domain/
  mission
  desired_state
  action
  authority
  evidence
  verification
  reconciliation

application/
  mission_service
  planner_port
  executor_port
  verifier_port
  ledger_port

adapters/
  aws/
  google_calendar/
  google_tasks/
  open_meteo/
  mcp/

web/
  simulated_alexa_client
  receipt_view
```

Exact language/package structure is frozen later.

## Why a dedicated demo calendar/task list

The canonical demo should use:
- a dedicated StillDone demo calendar;
- a dedicated StillDone demo task list.

Benefits:
- real Google APIs;
- bounded real mutations;
- no private unrelated events;
- easy cleanup;
- reproducibility;
- safer screenshot/video capture.

## Alexa+ integration strategy

Guaranteed qualifying target:
- self-hosted MCP server;
- MCP spec `2025-11-25` or later as allowed by current competition rules;
- Streamable HTTP.

Actual Alexa+ connection:
- optional;
- only when partner/runtime access is independently proven.

If direct Alexa+ connection is unavailable:
- use an explicit `SIMULATED ALEXA+ EXPERIENCE` client;
- keep backend calls real;
- never imply the client itself is connected to Alexa+.

## MCP performance constraint

Current Alexa+ MCP docs state a round-trip target below 500 ms.

The project must distinguish:
- MCP transport latency;
- long-running mission execution latency.

If needed, expose fast tool acknowledgment/status plus mission polling/progress rather than pretending a multi-service mission completes inside one sub-500 ms provider round trip.

Exact compatible pattern must be proven against current MCP/Alexa+ docs in the active phase.

## Data minimization

The mission ledger should not become a full copy of Calendar/Tasks.

Store only what is required for:
- contract evaluation;
- replay safety;
- verification;
- audit;
- drift explanation.

## No hidden simulation

Adapters must expose explicit mode/provenance.

A live adapter failing must fail visibly. It cannot silently switch to fixture mode.
