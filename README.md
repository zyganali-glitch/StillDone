# StillDone

> **Done, and still true.**

StillDone is a desired-state mission runtime for Alexa+ style assistants.

A normal agent can say an action succeeded because a tool returned success. StillDone uses a stricter rule:

> **An outcome is not complete until the resulting state is independently observed, and completion can be revoked if reality later drifts.**

## Canonical product thesis

StillDone turns a natural-language mission into a bounded desired-state contract, executes permitted actions across real services, independently reads back the resulting state, preserves partial failures and `NOT_RUN` honestly, and re-checks the mission later when the user asks whether it is **still done**.

### Canonical killer mission

> **“Get my family ready for tomorrow morning. We need to leave by 7:30.”**

The competition demo targets a dedicated disposable demo calendar and task list:

1. Read tomorrow’s real Google Calendar state.
2. Read real weather from Open-Meteo.
3. Read the real Google Tasks state.
4. Use a real AWS model/agent path to propose a typed mission plan.
5. Compile that plan into deterministic desired-state predicates.
6. Auto-execute safe reversible actions.
7. Ask for one bounded approval for the meaningful existing-calendar change.
8. Execute the approved action.
9. Perform independent read-back calls from the systems of record.
10. Report `READY` only when required predicates are verified.
11. Mutate the calendar externally.
12. Ask: **“Are we still ready?”**
13. Reconcile again and downgrade the mission to `DRIFTED` when reality no longer satisfies the contract.

The demo's wow moment is not that AI performs actions. It is that **the system withdraws its earlier claim when the real world changes.**

## Competition target

**Build, Ship, Shape: Amazon Developer Hackathon**

Primary:
- Alexa+ Track

Secondary:
- AWS Builder Mini Challenge
- Open Source Mini Challenge

Current rules snapshot: `2026-09-29` (re-verified against current official Devpost rules and resources).

Canonical official rules:
- https://amazonappdev2026.devpost.com/rules
- https://amazonappdev2026.devpost.com/
- https://amazonappdev2026.devpost.com/resources

Alexa+ official developer docs:
- https://developer.amazon.com/docs/alexaplus/add-ons/home.html
- https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html
- https://developer.amazon.com/docs/alexaplus/add-ons/choose-the-proper-alexaplus-integration-approach.html

## Evidence law

StillDone separates **result state** from **evidence provenance**.

Result examples:
- `NOT_RUN`
- `EXECUTED_UNVERIFIED`
- `VERIFIED`
- `CONTRADICTED`
- `BLOCKED`
- `FAILED`
- `STALE`
- `DRIFTED`

Provenance examples:
- `FIXTURE`
- `LOCAL_EXECUTION`
- `LIVE_AWS`
- `LIVE_GOOGLE`
- `LIVE_EXTERNAL`
- `RECORDED_LIVE`

A model may interpret or propose. It may not rewrite deterministic facts.

## Zero-personal-spend policy

Target personal spend: **$0.00**.

Allowed:
- hackathon promotional credits;
- verified free tiers;
- free/open-source local tools;
- free APIs within documented limits.

Forbidden without explicit operator approval:
- paid subscriptions;
- pay-as-you-go continuation beyond promotional/free budget;
- automatic paid fallback;
- unmetered public endpoints that can drain credits.

See:
- `docs/COST_AND_ACCESS_POLICY.md`
- `docs/OPERATOR_REQUIREMENTS.md`

## Current status

**PHASE P-02 CLOSED — INDEPENDENT QA PASS (Verified SHA: `293ec637464294a6caaca8cffcd85dd666890f61`); PHASE P-03 PENDING / NOT_STARTED**

Phase progression and verified milestones:
- **Phase P-00 (Bootstrap & Governance Baseline)**: Complete and closed with independent QA PASS (`P-00.01` through `P-00.05`).
- **Phase P-01 (Live Access, Zero-Cost & Platform Feasibility)**: Complete and closed with independent QA PASS (`P-01.01` through `P-01.08`, verified SHA `41e4ea717b43f558d9d07a7f1775c0780819910f`). Architecture v1 frozen; all live feasibility legs proven; zero personal spend verified ($0.00).
- **Phase P-02 (Provider-Neutral Mission & Desired-State Contracts)**: Complete and closed with independent QA PASS (`P-02.01` through `P-02.08`, verified SHA `293ec637464294a6caaca8cffcd85dd666890f61`).
  - Provider-neutral domain contracts: `MissionContract`, `UserIntentSnapshot`, `DesiredStatePredicate`, `FreshnessContract`, `ActionContract`, `TargetIdentity`, `NormalizedParameters`, `ApprovalGrant`, `BindingHash`, `ExecutionAttempt`, `RetryPolicy`, `ResourceBinding`, `ReconciliationRequest`, and `EvidenceOrigin`.
  - Canonical vocabularies frozen: `MissionState` (10), `StepEvidenceState` (7), `PredicateOperator` (8), `FreshnessMode` (2), `ActionType` (5), `ResourceKind` (4), `AuthorityClass` (5), `RetryStrategy` (3), `ReconciliationReason` (3), `EvidenceProvenance` (6).
  - Hard boundary enforcement: Strictly zero external provider SDK imports (`boto3`, `google`, `mcp`, etc.), zero database/persistence implementations, zero generic evidence ledgers, zero generic content-addressed evidence ID implementations, zero runtime state-transition guard engines, zero model/LLM invocations, and zero silent live→fixture fallback.
  - Canonical recursive domain inspection: AST purity and anti-leakage checks recursively cover `src/stilldone/domain/**/*.py` (`rglob("*.py")`) with regression proof against nested module bypasses (`test_domain_source_enumeration_includes_nested_modules`, `test_nested_module_forbidden_import_detected`).
  - Donor truth: Zero donor source code imported (0 lines); all domain logic is clean-room reimplemented; donor concepts preserved as `CONCEPT_ONLY`.
- **Phase P-03 (Deterministic Evidence Ledger & Fact Authority)**: `PENDING / NOT_STARTED`.
  - Next exact task: `P-03.01 — Implement canonical serialization and SHA-256 content-addressed evidence IDs`.
  - **Discipline constraints**: `P-03.01` is **NOT AUTHORIZED** until this Phase P-02 boundary reconciliation / P-Ω audit receives independent QA review. Phase P-03 MUST NOT START.

See:
- `plans/STILLDONE_MASTER_EXECUTION_PLAN.md`
- `docs/HANDOFF.md`
- `docs/ARCHITECTURE.md`
- `docs/P01_LIVE_FEASIBILITY.md`
- `docs/P_OMEGA_AUDIT_REPORT.md`
- `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`
- `docs/P01_03_LIVE_STRANDS_EVIDENCE.md`
- `docs/P01_04_LIVE_AGENTCORE_EVIDENCE.md`
- `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`
- `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`
- `docs/P01_07_LIVE_REMOTE_MCP_EVIDENCE.md`
- `docs/COMPETITION_FEEDBACK_LOG.md`
- `AGENTS.md`
