# P-20.04 — Judging-Criteria Alignment Map

**Document ID**: `docs/P20_04_JUDGING_CRITERIA_MAP.md`  
**Task**: `P-20.04 — Build judging-criteria map`  
**Competition**: *Build, Ship, Shape: Amazon Developer Hackathon* (Official Devpost Rules, Snapshot: 2026-10-01)  
**Track Alignment**: Primary: **Alexa+ Track**; Secondary: **AWS Builder Mini Challenge**, **Open Source Mini Challenge**  
**Evaluation Model**: 4 Equally Weighted Canonical Criteria (25% Each)  

---

## 1. Criterion 1: Technological Implementation (25%)

> **Judges look for**: Technical sophistication, code quality, effective use of Amazon Bedrock / AWS tools, architectural integrity, automated testing, and robust error handling.

### StillDone Evidence & Implementation:
1. **Real Streamable HTTP Model Context Protocol (MCP) Server Spine**:
   - Built with the official `mcp>=2.2.0` Python SDK over open-standard Streamable HTTP JSON-RPC 2.0 (`src/stilldone/mcp/server.py`, `src/stilldone/mcp/protocol.py`).
   - Implemented typed `mission_start` and `mission_status` tools, RFC 9728 Protected Resource Metadata (PRM), atomic rate limiting via SQLite WAL mode, and Alexa+ 401 header suppression middleware.
   - Proved live interoperability with `@modelcontextprotocol/inspector@2.9.0` and deployed Bedrock AgentCore Runtime microVM in `us-east-1` (`docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`).
2. **Real Amazon Bedrock Nova Micro & Strands Agents Integration**:
   - Orchestrated bounded natural language intent planning via Amazon Bedrock Converse API (`amazon.nova-micro-v1:0` in `us-east-1`) and Strands Agents SDK 1.57.2 (`src/stilldone/planning/`).
   - Proved real model inference in dated live session (`docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`) with deterministic envelope extraction and zero model authority.
3. **Dual-Runtime Architecture Without Resolver Overrides**:
   - Solved upstream `strands-agents 1.57.2` dependency conflict (`mcp<2.2` vs. `mcp>=2.2.0`) by architecting two completely isolated virtual environments (`pyproject.toml` for Core/MCP vs. `runtimes/strands_planner/pyproject.toml` for Strands Planner) without disabling or overriding package resolvers.
4. **Deterministic Verification & Reconciliation Engine**:
   - Decoupled verifiers (`GoogleCalendarReadbackVerifier`, `GoogleTasksReadbackVerifier`) evaluate exact mathematical predicates (`DesiredStatePredicate`) against fresh read-back observations, completely separate from tool execution status (`src/stilldone/verifier/`).
   - Monotonic state transition engine (`MissionTransitionGuard`) strictly prevents unauthorized state promotions.
5. **Idempotency, Deduplication & Crash Recovery**:
   - `DurableFileLedger` (JSONL + fsync) preserves in-flight mutation state across process restarts. Ambiguous timeouts trigger read-before-retry to eliminate duplicate calendar events or task creations (`src/stilldone/recovery/`).
6. **Exhaustive Automated Test Coverage**:
   - **3,800+ total automated tests** (2,667 Core/MCP tests, 1,155 Strands Planner tests across dual runtimes), 0 skipped, 0 failures, 100% passing in CI (`.github/workflows/ci.yml`).
   - Dedicated adversarial campaigns testing write timeouts, contradictory readbacks, tampering, replay attempts, and Unicode collisions.

---

## 2. Criterion 2: Design (25%)

> **Judges look for**: User experience, conversational voice design, accessibility, visual hierarchy, mobile responsiveness, and intuitive explanation of agent actions.

### StillDone Evidence & Implementation:
1. **One-Screen Multimodal Timeline & Departure Story**:
   - Designed a clean, scannable one-screen timeline for the canonical killer mission: *"Get my family ready for tomorrow morning. We need to leave by 7:30."*
   - Prominently showcases the departure lifecycle tracker: `07:45 AM (Initial Calendar) → 07:30 AM (Target Verified / READY) → 08:00 AM (External Drift / DRIFTED)`, allowing judges to instantly comprehend state evolution (`src/stilldone/judge_ux/html_renderer.py`).
2. **Truthful, Voice-Friendly Summaries for Alexa+**:
   - Synthesizes concise voice summaries (`VoiceSummary`) with duration bounds ($< 8$ seconds) designed specifically for voice devices (`Echo Show`, `Alexa+`).
   - Strictly truthful: distinguishes task additions to a list from physical preparation; never claims physical backpacks are packed.
3. **Accessible, WCAG AA Mathematical Contrast Compliance**:
   - 100% self-contained CSS with zero external web fonts or CDN scripts.
   - Mathematical verification across 18 rendered UI pairs confirms contrast ratios $\ge 4.5:1$ (all text) and $\ge 3.0:1$ (large/bold elements), eliminating low-contrast colors like `#64748b`.
   - Semantic HTML5 structure (`<main>`, `<header>`, `<article>`, `<section>`, `<footer>`, `<details>`, `<summary>`) with complete ARIA labels.
4. **Mobile & Desktop Responsive Engine**:
   - Tested under real headless browser engines (Edge/Chromium) across mobile viewports (375px $\times$ 812px) and wide desktop viewports (1200px $\times$ 900px).
   - Guarantees zero horizontal overflow (`data-no-overflow="true"`) and responsive single-column reflow on narrow phones without squished tables or cramped sidebars (`tests/test_phase_p15_judge_ux.py`).
5. **Clear Visual State Hierarchy**:
   - Instant visual distinction between `READY` (emerald green), `PARTIAL` (sky blue), `DRIFTED` (amber gold), and `BLOCKED` (crimson red).
   - Human authorization boundary clearly isolated as an approval card with action parameters and cryptographic fingerprint.

---

## 3. Criterion 3: Potential Impact (25%)

> **Judges look for**: Real-world utility, scale of the problem addressed, safety and trust in AI assistants, and practical applicability across domains.

### StillDone Evidence & Implementation:
1. **Solving the Fundamental Flaw in AI Agent Delegation**:
   - Today's autonomous assistants report completion the moment an API call returns HTTP 200, but in the real world:
     - APIs succeed while actual state remains unverified;
     - Network drops cause ambiguous timeouts leading to accidental duplicate bookings;
     - External humans or systems later modify or cancel resources (reality drifts).
   - StillDone introduces the missing verification and drift-reconciliation layer for autonomous assistants, preventing missed flights, forgotten tasks, and hallucinated task completion.
2. **Reversible Approval Compression**:
   - Classifies actions into 5 authority classes (`READ_ONLY`, `REVERSIBLE_AUTO`, `REVERSIBLE_APPROVAL_REQUIRED`, `EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED`, `IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED`).
   - Non-destructive steps (weather check, prep task creation) execute autonomously; high-blast-radius calendar shifts pause for single-use human approval. Eliminates approval fatigue while preserving security boundaries.
3. **Cross-Domain Applicability**:
   - The provider-neutral architecture (`MissionContract`, `DesiredStatePredicate`, `VerificationObservation`) applies universally beyond calendar and tasks:
     - Home automation (verifying smart locks or thermostats actually changed state);
     - Travel & hospitality (monitoring flight delay drift against hotel reservation check-ins);
     - Enterprise operations (verifying cloud deployments, database migrations, and payroll batches).
4. **Consumer Trust & Auditability**:
   - Cryptographic receipt projections provide an immutable audit trail for families and enterprises, proving what was verified, at what time, and under what authority.

---

## 4. Criterion 4: Quality of Idea (25%)

> **Judges look for**: Originality, strength of the thesis, conceptual elegance, and adherence to foundational principles.

### StillDone Evidence & Implementation:
1. **The Core Thesis: "Done, and still true."**:
   - *"An outcome is not complete until the resulting state is independently observed, and completion can be revoked if reality later drifts."*
   - Flips AI assistant design from tool-execution-centric to desired-state-centric.
2. **The Drift Law & Dual-Truth Invariant**:
   - Reconciles historical auditability with current reality: an immutable historical receipt remains permanently unchanged as proof of what was true at issuance, while the live system-of-record state immediately downgrades to `DRIFTED` when reality changes.
   - Prevents AI assistants from rewriting historical audit logs while keeping current notifications accurate.
3. **Model Proves Nothing Law**:
   - LLMs are brilliant at interpreting unstructured user intent and proposing plans, but terrible at deterministic verification.
   - StillDone enforces an absolute boundary: models propose candidate plans, but **deterministic code** computes evidence state, evaluates predicates, checks freshness, and decides readiness. Model prose can never promote a mission to `READY`.
4. **Zero Personal Spend Discipline ($0.00)**:
   - Proves that production-grade autonomous agent systems with real Bedrock reasoning, real serverless microVMs, and dual-runtime test suites can be developed and judged with strictly zero personal spend, leveraging open-source tooling, free tiers, and bounded promotional credits.

---

## 5. Mini Challenge Alignments

### 5.1 AWS Builder Mini Challenge
- **Evidence**: Deployed and proved real Bedrock Nova Micro reasoning via Converse API (`P-01.02`, `P-07.06`), proved serverless Bedrock AgentCore Runtime microVM (`P-01.04`, `P-05.06`), and documented complete technical feedback and friction logs (`docs/P20_01_AWS_PRODUCT_FEEDBACK.md`, `docs/COMPETITION_FEEDBACK_LOG.md`).
- **Reference**: `docs/AWS_BUILDER_MAP.md`.

### 5.2 Open Source Mini Challenge
- **Evidence**: Released under an open-source license, implementing open standards (Model Context Protocol 2025-11-25 Streamable HTTP, RFC 9728 Protected Resource Metadata, RFC 6750 OAuth Resource Server), with 100% clean-room reimplementation (0 donor lines) and zero proprietary vendor lock-in.
- **Reference**: `docs/OPEN_SOURCE_MINI_CHALLENGE.md`.

---

*Verified judging-criteria alignment map committed under P-20.04.*
