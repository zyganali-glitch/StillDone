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

Current rules snapshot: `2026-10-01` (re-verified against current official Devpost rules and resources).

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

**PHASE P-03 CLOSED — INDEPENDENT QA PASS (Verified SHA: `03245b3832ad9e9c82b9a30060e07fd87ca2e63b`); PHASE P-04 CLOSURE CANDIDATE — AWAITING INDEPENDENT QA (Last Verified Baseline SHA: `a44955595aabaf7f34daecc35100bb72b5120095`)**

Phase progression and verified milestones:
- **Phase P-00 (Bootstrap & Governance Baseline)**: Complete and closed with independent QA PASS (`P-00.01` through `P-00.05`).
- **Phase P-01 (Live Access, Zero-Cost & Platform Feasibility)**: Complete and closed with independent QA PASS (`P-01.01` through `P-01.08`, verified SHA `41e4ea717b43f558d9d07a7f1775c0780819910f`). Architecture v1 frozen; all live feasibility legs proven; zero-personal-spend path determined credible through judging (target personal spend strictly $0.00; actual billed cost and personal-spend delta preserved as `NOT_OBSERVED / UNKNOWN`).
- **Phase P-02 (Provider-Neutral Mission & Desired-State Contracts)**: Complete and closed with independent QA PASS (`P-02.01` through `P-02.08`, verified SHA `293ec637464294a6caaca8cffcd85dd666890f61`).
  - Provider-neutral domain contracts: `MissionContract`, `UserIntentSnapshot`, `DesiredStatePredicate`, `FreshnessContract`, `ActionContract`, `TargetIdentity`, `NormalizedParameters`, `ApprovalGrant`, `BindingHash`, `ExecutionAttempt`, `RetryPolicy`, `ResourceBinding`, `ReconciliationRequest`, and `EvidenceOrigin`.
  - Canonical vocabularies frozen: `MissionState` (10), `StepEvidenceState` (7), `PredicateOperator` (8), `FreshnessMode` (2), `ActionType` (5), `ResourceKind` (4), `AuthorityClass` (5), `RetryStrategy` (3), `ReconciliationReason` (3), `EvidenceProvenance` (6).
  - Hard boundary enforcement: Strictly zero external provider SDK imports (`boto3`, `google`, `mcp`, etc.), zero database/persistence implementations, zero generic evidence ledgers, zero generic content-addressed evidence ID implementations, zero runtime state-transition guard engines, zero model/LLM invocations, and zero silent live→fixture fallback.
  - Canonical recursive domain inspection: AST purity and anti-leakage checks recursively cover `src/stilldone/domain/**/*.py` (`rglob("*.py")`) with regression proof against nested module bypasses (`test_domain_source_enumeration_includes_nested_modules`, `test_nested_module_forbidden_import_detected`).
  - Donor truth: Zero donor source code imported (0 lines); all domain logic is clean-room reimplemented; donor concepts preserved as `CONCEPT_ONLY`.
- **Phase P-03 (Deterministic Evidence Ledger & Fact Authority)**: Complete and closed with independent QA PASS (`P-03.01` through `P-03.06`, verified baseline SHA `46e55b424eb999c666932871b5b5517397b85db6`, repair commit `03245b3832ad9e9c82b9a30060e07fd87ca2e63b`).
  - Canonical serialization & evidence identity: deterministic primitive projection (`to_canonical_primitive`, `canonical_json`, `canonical_serialize`), sorted keys, fail-closed post-NFC duplicate key collisions, and domain-separated SHA-256 `EvidenceId` (`stilldone:evidence:v1`).
  - Append-only ledger port: provider-neutral port (`MissionLedgerPort`) with immutable records (`MissionRecord`, `ActionRecord`, `EvidenceRecord`), duplicate/conflict fail-closed guards (`DuplicateRecordError`, `RecordConflictError`), defensive payload snapshot isolation (`freeze_canonical_payload`, `CanonicalPayload`, `CanonicalSequence`), and explicitly non-durable in-memory implementation (`InMemoryNonDurableLedger`).
  - Deterministic state-transition guards: runtime guard engine (`MissionTransitionGuard`) strictly enforcing lifecycle rules; promotion to `READY` permitted only from `VERIFYING` and requiring all-`VERIFIED` step evidence; executor success alone cannot promote; `NOT_RUN != PASS`.
  - Bounded sanitized provider-output capture: detached structural sanitization (`capture_provider_output`, `SanitizedProviderCapture`), explicit `CaptureBounds`, deterministic truncation metadata, fail-closed total size limits, and SHA-256 `CaptureDigest` (`stilldone:provider-capture:v1`).
  - Receipt projections: immutable `ReceiptProjection` binding exact mission snapshot, dedicated typed `MissionContentHash` (`stilldone:mission-content:v1`) bound to `MissionId` across all construction paths (`create`, `from_records`, `__post_init__`, and `compute_receipt_hash`), sorted deduplicated `EvidenceId` tuple, deep-frozen metadata snapshot, and domain-separated `ReceiptHash` (`stilldone:receipt-projection:v1`). Preserved source semantics without overclaiming raw 64-char hex digest alone.
  - Adversarial hardening: 27 negative tests covering tamper, mismatch, replay, stale, forbidden promotion, Unicode NFC collisions, and mutable alias isolation. Total suite passing: 218 tests.
  - Donor truth: strictly 0 donor lines imported; clean-room reimplemented.
- **Phase P-04 (Security, Privacy & Authority Foundation)**: `CLOSURE CANDIDATE — awaiting independent QA`.
  - `P-04.01` (Secret/config fail-closed boundary): typed `ConfigSchema`, `ConfigField`, `SecretString` with masked representations, call-time/injected environment loading, owned `STILLDONE_` namespace validation, and fail-closed secret typing.
  - `P-04.02` (Log/evidence redaction & capture safety): deterministic pattern redaction for tokens, Bearer/Basic headers, JWTs, Google tokens, AWS access keys, emails, sensitive dictionary keys, and OAuth URLs (query/fragment decoded keys and values sanitized before re-encoding); immutable `RedactionMetadata`.
  - `P-04.03` (Supported-action allowlist & parameter policy): five-action closed allowlist (`calendar.read`, `calendar.update`, `task.read`, `task.create`, `weather.read`), strict parameter typing, non-coercing bounds (`MAX_PARAM_STRING_LENGTH = 1024`), and self-validating `ValidatedActionContract`. Zero provider or network imports.
  - `P-04.04` (Deterministic authority & bound approval verification): canonical authority classification (`READ_ONLY`, `REVERSIBLE_AUTO`, `REVERSIBLE_APPROVAL_REQUIRED`), timezone-aware half-open validity window, constant-time `hmac.compare_digest` verification, and strict target external identifier error secrecy.
  - `P-04.05` (Demo-resource isolation): strict runtime match against configured demo calendar ID and demo task-list ID; rejects aliases, wildcards, substrings, or unvalidated contracts; masks IDs in `DemoResourceScope` `__repr__`.
  - `P-04.06` (Public-endpoint rate/budget admission contract): deterministic provider-neutral rate/budget policy evaluator, exact `Decimal` arithmetic, operator live gate (`live_paid_path_enabled=False` default), deny on `PAID_CAPABLE_LIVE` + `PUBLIC_UNTRUSTED`, fresh credit coverage checks, internal gross ceiling enforcement, and self-validating `EndpointAdmissionDecision`. Evaluator is pure; does not claim atomic production rate limiting (deferred to P-05.05).
  - `P-04.07` (Phase-boundary security/threat-model audit): comprehensive 16-dimension audit documented in `docs/P04_SECURITY_THREAT_MODEL_AUDIT.md`; 40 cross-boundary integration security tests in `tests/test_phase_p04_security_audit.py` verifying vocabulary, authority, import purity, and cross-gate non-substitutability.
  - **Truth boundaries**: All P-04 evidence is strictly `LOCAL_EXECUTION` / CI. No Phase P-05 MCP server exists yet; no Phase P-06 live provider adapters exist yet; no live write/read-back implementation exists yet. Executor success does not create `VERIFIED` or `READY`.
  - **Suite truth**: 591 tests passing at independently verified P-04.06 baseline (`a44955595aabaf7f34daecc35100bb72b5120095`); 631 tests passing in P-04.07 audit candidate suite (candidate awaiting independent QA).
  - **Current micro-task status**:
    - P-04.01 — independent QA PASS
    - P-04.02 — independent QA PASS
    - P-04.03 — independent QA PASS
    - P-04.04 — independent QA PASS
    - P-04.05 — independent QA PASS
    - P-04.06 — independent QA PASS
    - P-04.07 — `REPAIRED — awaiting independent QA`
    - Phase P-04: `CLOSURE CANDIDATE — awaiting independent QA`
    - P-05.01: `PENDING / NOT AUTHORIZED`

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
