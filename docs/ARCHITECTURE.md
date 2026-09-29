# StillDone Architecture

## Status

`ARCHITECTURE v1 — FROZEN AT P-01 LIVE FEASIBILITY GATE`  
**Freeze Date**: `2026-09-29`  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md) § P-01.08  

---

## 1. Core Architectural Principle

The LLM sits beside deterministic execution truth, not above it:

> **An outcome is not complete until the resulting state is independently observed, and completion can be revoked if reality later drifts.**

A successful tool/adapter response **MUST NOT** directly produce `VERIFIED`.

Required success chain for a mutable real-world step:

$$\text{INTENT} \longrightarrow \text{CONTRACT} \longrightarrow \text{AUTHORITY} \longrightarrow \text{EXECUTE} \longrightarrow \text{INDEPENDENT READBACK} \longrightarrow \text{PREDICATE EVALUATION} \longrightarrow \text{VERIFIED}$$

If the independent read-back cannot prove the expected state:
- keep the step unverified or contradicted;
- do not let model prose promote it;
- mission status `READY` is computed strictly by deterministic code from verified predicates and freshness contracts.

---

## 2. Target Component Model

```text
Simulated Alexa+ Client Surface (visibly labeled; partner access NOT_ESTABLISHED)
                         |
                         v
Remote MCP Server — Streamable HTTP (MCP spec >= 2025-11-25)
                         |
                         v
                Mission Intake & Intent Capture
                         |
             +-----------+-----------+
             |                       |
             v                       v
      Model/Strands Planner    Deterministic Contract Compiler
             |                       |
             +-----------+-----------+
                         |
                         v
                  Authority Engine (5 Action Classes)
                         |
                         v
                  Mission Executor (AWS AgentCore Runtime)
               /         |          \
              /          |           \
     Google Calendar  Google Tasks  Open-Meteo
              \          |           /
               \         |          /
                         v
               Independent Readback Engine
                         |
                         v
              Predicate & Drift Evaluation Engine
                         |
                         v
          Mission Ledger + Evidence Store (Provider-Neutral Port)
                         |
                         v
         Voice Summary + Visual Receipt Surface
```

### Component Responsibilities

1. **Remote MCP Server (`Streamable HTTP`)**:
   - Implements Model Context Protocol specification version `2025-11-25` (or later) over Streamable HTTP transport.
   - Operates in stateless direct-JSON mode (`enableJsonResponse: true`) or streaming mode on a unified `/mcp` endpoint over public HTTPS.
   - Enforces the `< 500ms` round-trip query response latency threshold for tool acknowledgments and status queries.
   - Primary technical qualification path for the Alexa+ Track.
   - Downstream mandatory requirement: The final canonical product repository must contain and actually execute this real self-hosted MCP server at runtime before submission freeze.

2. **Simulated Alexa+ Experience Client Surface**:
   - Visibly labeled web/desktop interface providing conversational voice/text interaction and visual cards.
   - Officially recognized qualifying alternative surface under hackathon rules, explicitly exempt from the runtime-technology-hook requirement.
   - Connects to the real StillDone backend and remote MCP server; backend actions remain 100% real.
   - Never presents itself as Alexa+ itself; clearly designated as `SIMULATED ALEXA+ EXPERIENCE`.

3. **Mission Intake & Intent Capture**:
   - Ingests natural-language delegation from the user.
   - Captures an immutable snapshot of user intent, timestamp, and target scope.

4. **Model/Strands Planner**:
   - Powered by Amazon Bedrock foundation models (`amazon.nova-micro-v1:0` in `us-east-1`) via the Strands Agents SDK (`strands-agents`).
   - Decomposes natural-language intent into candidate action sequences and proposed outcomes.
   - Role strictly bounded to proposal and explanation; **cannot** mark actions verified, fabricate external IDs, or override deterministic facts.

5. **Deterministic Contract Compiler**:
   - Compiles proposed plans into typed, deterministic desired-state predicates.
   - Classifies predicates as `required` or `optional` and attaches explicit freshness contracts (maximum age before re-verification).
   - Validates that proposed actions conform strictly to the allowlisted supported action vocabulary.

6. **Authority Engine**:
   - Enforces approval compression and bounded human delegation across 5 discrete action classes:
     1. `READ_ONLY`: Autonomous execution permitted without approval.
     2. `REVERSIBLE_AUTO`: Safe, reversible new resource creation (e.g. creating a dedicated demo preparation task) executed autonomously.
     3. `REVERSIBLE_APPROVAL_REQUIRED`: Modification or rescheduling of an existing resource (e.g. moving `Leave for school` event from 07:45 to 07:30); requires single bounded human approval.
     4. `EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED`: Sending emails or external notifications; always requires human approval (deferred from core v1).
     5. `IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED`: Deletion or permanent destructive mutation; strictly blocked or requires explicit human confirmation.
   - Cryptographically binds approval objects to `(mission_id, action_id, parameter_hash, target_resource_id, validity_window)`. Chat confirmations like "yes" are rejected unless cryptographically bound to the pending approval object.

7. **Mission Executor (AWS AgentCore Runtime)**:
   - Serverless microVM execution environment (`AWS::BedrockAgentCore::Runtime`, direct CodeZip build, Python 3.13/3.14 in `us-east-1`).
   - Executes authorized actions against real service adapters using idempotency keys and bounded retry policies.

8. **Service Adapters**:
   - **Google Calendar Adapter**: Interacts with Google Calendar API using least-privilege scopes (`calendar.calendarlist.readonly`, `calendar.events.readonly` during read phase; scoped write during mutation). Bound strictly to the dedicated disposable `StillDone Demo` calendar.
   - **Google Tasks Adapter**: Interacts with Google Tasks API using least-privilege scopes (`tasks.readonly` during read phase; scoped write during mutation). Bound strictly to the dedicated disposable `StillDone Demo` task list.
   - **Open-Meteo Adapter**: Queries public Open-Meteo Forecast API (`https://api.open-meteo.com/v1/forecast`) for public demo coordinates (Seattle, WA). Strictly zero authentication, keys, or personal geolocation sent.

9. **Independent Readback Engine**:
   - Initiates fresh, independent read queries directly against the external systems of record (Google Calendar, Google Tasks) following mutation.
   - Decoupled from the execution pipeline to ensure write success responses cannot masquerade as verification.

10. **Predicate & Drift Evaluation Engine**:
    - Evaluates independently observed external state against desired-state predicates.
    - Computes mission status `READY` deterministically when all required predicates pass within freshness bounds.
    - Re-evaluates predicates upon subsequent reconciliation queries ("Are we still ready?").
    - Automatically revokes `READY` and downgrades mission to `DRIFTED` if external reality deviates from the desired-state contract.

11. **Mission Ledger & Evidence Store (Provider-Neutral Port)**:
    - Immutable, append-only ledger tracking missions, actions, approvals, and evidence items.
    - Each evidence record is content-addressed via SHA-256 and records explicit provenance (`FIXTURE`, `LOCAL_EXECUTION`, `LIVE_AWS`, `LIVE_GOOGLE`, `LIVE_EXTERNAL`, `RECORDED_LIVE`).
    - Core domain interacts via a provider-neutral repository port (`ledger_port.py`), which is frozen in Architecture v1. Concrete persistence is deferred to Phase P-03 (`DEFERRED / NOT_YET_IMPLEMENTED`). A local append-only file/SQLite ledger is a candidate direction only; it is not yet implemented, validated, or accepted. P-03 exact tasks will determine and prove the concrete implementation.

12. **Voice Summary & Visual Receipt Surface**:
    - Synthesizes concise voice status for Alexa+ conversational flow.
    - Renders structured visual cards displaying live mission state, verified predicates, freshness timestamps, evidence provenance, and drift explanations.

---

## 3. Frozen Proven AWS Stack

Only AWS components with verified, repeatable live evidence are selected for Architecture v1:

| AWS Component | Proven Runtime Version / ID | Proven Region | Live Feasibility Evidence | Role in Architecture v1 |
|---|---|---|---|---|
| **Amazon Bedrock (Inference)** | `amazon.nova-micro-v1:0` | `us-east-1` | P-01.02 (Cycle 3: `pong`, stopReason=`end_turn`, tokens: 11, latency: 7259ms) | Primary reasoning & planning engine for intent decomposition and candidate plan proposal. |
| **Strands Agents SDK** | `strands-agents 1.57.1` (with `botocore[crt]` / `awscrt 0.36.0`) | `us-east-1` | P-01.03 (`STRANDS_OK`, native `BedrockModel`, elapsed: 1179ms) | Agentic framework orchestrating planning loops and structured contract synthesis. |
| **Amazon Bedrock AgentCore Runtime** | `@aws/agentcore 0.30.0` / CodeZip / AL2023 MicroVM | `us-east-1` | P-01.04 (Repair Cycle: `AGENTCORE_OK`, HTTP 200, status `READY`) | Bounded serverless container runtime hosting mission orchestration and executor entrypoints. |

> [!IMPORTANT]
> **Integration Boundary Truth**: P-01 proved the independent live feasibility of each required AWS leg. Production cross-service integration across all three components is scheduled in subsequent implementation phases (P-04, P-05, P-07).

---

## 4. AWS Service Set Classification (Selected, Deferred, Rejected)

Every candidate AWS service is explicitly classified to prevent architectural creep and enforce zero-personal-spend safety:

| AWS Service | Classification | Deterministic Rationale |
|---|---|---|
| **Amazon Bedrock (Nova Micro)** | **`SELECTED`** | Earned by live proof in P-01.02. Proven low latency, minimal cost, and active promotional-credit coverage. |
| **Strands Agents SDK** | **`SELECTED`** | Earned by live proof in P-01.03. Proven native Bedrock provider integration and tool-free bounded execution. |
| **AgentCore Runtime** | **`SELECTED`** | Earned by live proof in P-01.04. Proven serverless CodeZip deployment, data-plane invocation, and clean teardown in `us-east-1`. |
| **AgentCore Gateway** | **`REJECTED_FOR_V1`** | Unnecessary architectural complexity; direct data-plane invocation via AWS SDK/CLI is fully sufficient and eliminates routing overhead and potential unmetered endpoint costs. |
| **AgentCore Memory** | **`REJECTED_FOR_V1`** | Architecturally conflicts with StillDone's core thesis. Mission state, evidence, and verification must be owned by an immutable, deterministic ledger, not opaque probabilistic model memory. |
| **AgentCore Identity** | **`DEFERRED`** | External API authorization (Google OAuth) is handled via direct least-privilege token management. AgentCore Identity is not required for the single-operator v1 killer demo. |
| **Amazon DynamoDB** | **`DEFERRED`** | The mission ledger boundary is frozen as a provider-neutral port (`ledger_port.py`). Concrete persistence is deferred to Phase P-03 (`DEFERRED / NOT_YET_IMPLEMENTED`). A local append-only file/SQLite ledger is a candidate direction only; it is NOT yet implemented, validated, or accepted. DynamoDB adapter deferred to an explicit later task if cloud persistence is needed. |
| **AWS Lambda (Standard)** | **`REJECTED_FOR_V1`** | Redundant. AgentCore Runtime provides the serverless container execution environment for StillDone. |
| **AWS Step Functions** | **`REJECTED_FOR_V1`** | State transitions and verification logic must be executed and audited deterministically by StillDone's Python domain engine, not outsourced to an external cloud workflow service. |
| **Amazon EventBridge** | **`REJECTED_FOR_V1`** | Synchronous/reconciliation micro-task execution in v1 does not require an asynchronous pub/sub event bus; adds operational moving parts without verification benefit. |
| **Amazon SageMaker** | **`REJECTED_FOR_V1`** | Out of scope. Foundation model inference is fully served by Amazon Bedrock. |
| **Amazon Cognito** | **`REJECTED_FOR_V1`** | No complex multi-tenant user pool is needed for dedicated disposable demo resources and local/simulated client surfaces. |
| **Amazon S3 (Application State)** | **`REJECTED_FOR_V1`** | S3 is used ephemerally only by the CDK/AgentCore deployment pipeline for CodeZip staging; it is rejected as a store for dynamic application state. |
| **Bedrock Provisioned Throughput** | **`REJECTED_FOR_V1`** | Prohibitively expensive minimum commitments. Strictly pay-per-token on-demand invocation is enforced to maintain zero personal spend. |
| **AWS Marketplace 3P Models** | **`REJECTED_FOR_V1`** | Third-party foundation models carry EULA, FTU use-case questionnaires, and subscription billing risks. Amazon-native models are fully covered by promotional credits. |

---

## 5. Frozen External Service Set

Architecture v1 interfaces with exactly four external service boundaries:

```text
External Boundaries:
1. Google Calendar API (v3)
2. Google Tasks API (v1)
3. Open-Meteo Forecast API
4. MCP Streamable HTTP Protocol Boundary
```

### 5.1 Google Calendar & Google Tasks Boundary
- **Dedicated Disposable Resources**:
  - Secondary Calendar: `StillDone Demo` (redacted in documentation as `[REDACTED_CALENDAR_ID]`).
  - Dedicated Task List: `StillDone Demo` (redacted in documentation as `[REDACTED_TASKLIST_ID]`).
  - Zero access or fallback to primary personal calendars or default task lists.
- **Least-Privilege Scopes**:
  - Read Phase (proven in P-01.05): `calendar.calendarlist.readonly`, `calendar.events.readonly`, `tasks.readonly`.
  - Mutation Phase (scheduled in P-06): narrowest event-update and task-insert scopes; zero Gmail, Drive, or contact scopes.
- **Operational Readiness Risk**:
  - Google Cloud OAuth application operates in **Testing** status (restricted to configured test users, 100-user cap).
  - Refresh tokens in Testing mode may expire after 7 days, requiring interactive operator re-authorization before final demo recording and judging.
  - This is an operational readiness item, not proof that current live access remains fresh.

### 5.2 Open-Meteo Forecast API Boundary
- **Endpoint**: Public forecast endpoint `https://api.open-meteo.com/v1/forecast`.
- **Query Privacy**: Fixed public coordinates for Seattle, WA (`47.6062`, `-122.3321`). Zero user/device geolocation transmitted.
- **Licence & Attribution Contract**:
  - Weather data provided under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.
  - Mandatory user-facing attribution contract:  
    > **Weather data by [Open-Meteo.com](https://open-meteo.com/) — CC BY 4.0**
- **Evaluation & Usage Boundary**:
  - Free API tier permits non-commercial evaluation, prototyping, and educational use under documented fair-use limits (< 10,000 calls/day, 5,000 calls/hr, 600 calls/min).
  - StillDone's hackathon build and demo evaluation operate strictly within this non-commercial evaluation boundary. Public commercial production use is not overclaimed.
  - No paid Open-Meteo subscription is required or authorized.

### 5.3 MCP Streamable HTTP Protocol Boundary
- **Specification Compliance**: Model Context Protocol version `2025-11-25` (or later) over Streamable HTTP transport.
- **Transport Mode**: Stateless direct-JSON mode (`enableJsonResponse: true`) supported on `/mcp` over public HTTPS.
- **Latency Budget**: Server round-trip query response latency target `< 500ms` (proven probe latency: 61.26ms).
- **Authentication Requirements Recorded**:
  - Two-tier model cataloged from official Amazon docs: Tier 1 (`client_credentials` for service-level discovery) and Tier 2 (`authorization_code` + PKCE S256 for user account linking).
  - Actual Alexa+ partner client registration: `NOT_ESTABLISHED`.

---

## 6. Provider-Neutral Boundaries & Hexagonal Ports

To enforce the law that core domain logic remains independent of cloud SDKs and external APIs, Architecture v1 defines clean hexagonal ports:

```text
src/stilldone/
├── domain/                    <-- Zero external provider SDK dependencies
│   ├── mission.py             <-- Mission identity, lifecycle, state machine
│   ├── desired_state.py       <-- Predicate schemas, required/optional, freshness
│   ├── action.py              <-- Supported action vocabulary, parameter normalization
│   ├── authority.py           <-- 5 action classes, approval objects, cryptographic hashes
│   ├── evidence.py            <-- Content-addressed evidence IDs, provenance tags
│   └── reconciliation.py      <-- Drift detection rules, revocation logic
│
├── application/               <-- Orchestration ports & use cases
│   ├── ports/
│   │   ├── planner_port.py    <-- Propose candidate mission plans
│   │   ├── executor_port.py   <-- Execute authorized actions
│   │   ├── verifier_port.py   <-- Independent readback from system of record
│   │   └── ledger_port.py     <-- Append-only evidence & mission ledger interface
│   └── mission_service.py     <-- Coordinates intake -> plan -> compile -> exec -> verify -> reconcile
│
├── adapters/                  <-- Infrastructure implementations (contain SDKs)
│   ├── aws/
│   │   ├── bedrock_planner.py <-- Amazon Bedrock + Strands SDK adapter
│   │   └── agentcore_exec.py  <-- AgentCore Runtime executor adapter
│   ├── google/
│   │   ├── calendar.py        <-- Google Calendar API v3 adapter
│   │   └── tasks.py           <-- Google Tasks API v1 adapter
│   ├── weather/
│   │   └── open_meteo.py      <-- Open-Meteo REST API adapter
│   ├── mcp/
│   │   └── server.py          <-- Real Streamable HTTP MCP server
│   └── persistence/
│       └── (deferred to P-03) <-- Candidate direction: local append-only ledger (NOT yet implemented)
│
└── web/                       <-- User interfaces
    └── simulated_alexa/       <-- Visibly labeled simulated Alexa+ client & receipt UI
```

---

## 7. Hard Architectural Invariants

Architecture v1 strictly enforces the following system invariants:

1. **Execute ≠ Verified**: A mutation response (HTTP 200, tool success) **NEVER** creates `VERIFIED` state or promotes a mission to `READY`.
2. **Mandatory Independent Readback**: Verification requires an independent, separately executed read query against the system of record.
3. **Deterministic Authority**: The Python runtime owns mission state, predicate evaluation, and verification. The model may plan, interpret, and explain, but **cannot** certify, approve, or modify evidence facts.
4. **Bounded Action Vocabulary**: Actions proposed by the model are strictly validated against an immutable allowlist of supported schemas before compilation.
5. **Cryptographic Approval Binding**: Approval objects are bound to `(mission_id, action_id, params_hash, target_id, expiry_window)`. Unbound affirmations are rejected.
6. **Freshness & Drift Law**: `READY` is a temporary, observable state. If an external fact fails its predicate or freshness window upon subsequent reconciliation, the mission is downgraded to `DRIFTED`.
7. **Explicit Evidence Provenance**: Every piece of evidence carries an immutable provenance tag (`FIXTURE`, `LOCAL_EXECUTION`, `LIVE_AWS`, `LIVE_GOOGLE`, `LIVE_EXTERNAL`, `RECORDED_LIVE`). Recorded-live evidence is historical and never claimed as current live.
8. **No Silent Live $\to$ Fixture Fallback**: If a required live service call fails, it must fail visibly and produce an honest `FAILED`, `BLOCKED`, or `CONTRADICTED` state.
9. **Zero Personal Spend Discipline**: Development, testing, and evaluation strictly respect the `$0.00` personal spend target.
10. **Runtime MCP Requirement**: The final canonical repository must contain and execute the real self-hosted MCP Streamable HTTP server path at runtime before submission freeze.

