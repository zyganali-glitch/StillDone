# P-04 Security / Threat-Model Phase-Boundary Audit Report

## 1. Audit Metadata

| Field | Value |
|---|---|
| Audit date | 2026-10-01 |
| Starting verified SHA | `a44955595aabaf7f34daecc35100bb72b5120095` |
| Audit candidate SHA | _to be recorded after commit_ |
| Auditor | Antigravity executor (awaiting independent QA) |
| Phase | P-04 — Security, Privacy & Authority Foundation |
| Task | P-04.07 — Run focused security/threat-model P-Ω audit |

## 2. Scope

This audit covers the integrated security boundary produced by:
- P-04.01: Secret/config loading and fail-closed validation
- P-04.02: Log/evidence redaction
- P-04.03: Supported-action allowlist and parameter validation
- P-04.04: Authority classification and approval-binding verification
- P-04.05: Demo-resource isolation
- P-04.06: Public-endpoint rate/budget protection contract

And their interaction with preserved P-02/P-03 contracts.

## 3. Threat Model

### Attacker / Caller Assumptions

| Caller | Assumption |
|---|---|
| Public untrusted | Can send arbitrary requests to a future public endpoint |
| Operator (non-expert) | Trusted but may misconfigure |
| Model/planner | Cannot override deterministic facts; bounded action vocabulary |
| Python reflection | Defense against arbitrary hostile reflection is beyond P-04 contract scope |

### Trust Boundaries

```
[Public Untrusted] → Endpoint Rate/Budget → Action Allowlist → Authority/Approval → Demo Isolation → Provider Execution (future)
[Operator] → Config/Secret → Action Allowlist → Authority/Approval → Demo Isolation → Provider Execution (future)
[Model/Planner] → Action Allowlist → Authority/Approval → Demo Isolation → Provider Execution (future)
```

### Required Independent Gates (future execution path)

1. SUPPORTED / PARAMETER-VALID (P-04.03)
2. AUTHORITY-SATISFIED (P-04.04)
3. DEMO-RESOURCE-ISOLATED (P-04.05)
4. ENDPOINT/BUDGET-ADMITTED where applicable (P-04.06)

No gate substitutes for another. The orchestrator enforcing this chain belongs to later phases.

## 4. Audit Dimensions

### Dimension 1 — Canonical Remote / Ancestry

| Check | Result |
|---|---|
| Remote main SHA | `a44955595aabaf7f34daecc35100bb72b5120095` |
| Starting SHA matches | ✅ PASS |
| Linear ancestry across P-04 | ✅ PASS — 14 first-parent linear commits |
| No unreviewed commits | ✅ PASS |
| P-04.01–P-04.06 QA status | ✅ PASS (all 6 independently verified) |
| No local-only closure | ✅ PASS |

**P-04 Commit Lineage:**
```
a449555 fix(p04.06): add fail-closed self-validation to EndpointAdmissionDecision
f5b8cff feat(p04.06): implement public-endpoint rate and budget protection contract
95aa53a feat(p04.05): implement demo-resource isolation checks
2b24b48 fix(p04.04): repair target external identifier error secrecy
64af99c feat(p04.04): implement authority classification and approval-binding verification
63c5e27 docs(p04.03): repair canonical documentation parity
e1c0bbd feat(p04.03): implement supported-action allowlist and parameter validation
4125da1 fix(p04.02): repair URL decoded parameter-key redaction before re-encoding
b2d62c5 fix(p04.02): repair URL decoded-value redaction and metadata canonical category schema
dc2ba34 fix(p04.02): repair non-str log fallback, OAuth URL encoding, metadata immutability
2958e67 feat(p04.02): implement log and evidence redaction
933b536 fix(p04.01): enforce SecretString value type boundary
de258ff fix(p04.01): repair secret immutability, blank optional fail-closed
adfd0dc feat(p04.01): implement secret/config loading and fail-closed validation
```

### Dimension 2 — Secret / Config Boundary

| Check | Result |
|---|---|
| Explicit injection / call-time loading | ✅ PASS — `os.environ` inspected at call time only |
| Owned namespace (`STILLDONE_`) | ✅ PASS |
| Required-field fail-closed | ✅ PASS — `MissingConfigurationError` |
| Optional/default semantics | ✅ PASS |
| SecretString boundary | ✅ PASS — immutable, repr/str/format redacted |
| Exact-whitespace preservation | ✅ PASS — `parse_secret_string` preserves whitespace |
| No secret plaintext in public accessors | ✅ PASS — `to_dict(redact_secrets=True)`, `__repr__` masked |
| No static AWS credentials | ✅ PASS |
| No speculative Google OAuth secrets | ✅ PASS |
| No secret plaintext in exceptions | ✅ PASS — `is_secret` triggers redacted reason |
| Obvious bypass attempts | ✅ PASS — `__setattr__`, `__delattr__` blocked on SecretString |

**Verdict: PASS**

### Dimension 3 — Redaction / Evidence Safety

| Check | Result |
|---|---|
| Explicit sensitive-key policy | ✅ PASS — `SENSITIVE_SECRET_KEYS`, `SENSITIVE_IDENTIFIER_KEYS` |
| SecretString redacted without reveal() | ✅ PASS — line 562 |
| Email coverage | ✅ PASS — bounded regex |
| Bearer/Basic/JWT/Google/AWS patterns | ✅ PASS — all bounded |
| OAuth query + fragment handling | ✅ PASS — `_sanitize_oauth_url` |
| Decoded URL key AND value redaction | ✅ PASS — both keys and values processed |
| Sensitive external identifier policy | ✅ PASS — `SENSITIVE_IDENTIFIER_KEYS` |
| MissionId/ActionId/EvidenceId preserved | ✅ PASS — not blindly redacted |
| Unsupported objects fail closed | ✅ PASS — `UnsupportedRedactionTypeError` |
| No repr()/str() fallback | ✅ PASS |
| Deterministic/idempotent | ✅ PASS |
| Immutable metadata | ✅ PASS — `MappingProxyType` |
| Canonical metadata categories | ✅ PASS — `secret`, `email`, `identifier` |
| Capture ordering: redact → sanitize → digest | ✅ PASS — `capture.py:493` |
| No raw pre-redaction payload retained | ✅ PASS |

**Verdict: PASS**

### Dimension 4 — Action Allowlist / Parameter Policy

| Check | Result |
|---|---|
| Vocabulary exactly 5 actions | ✅ PASS — module-level assert |
| One policy entry per action | ✅ PASS |
| No generic shell/http/filesystem action | ✅ PASS |
| Action→system/resource matrix | ✅ PASS |
| Unknown parameter rejection | ✅ PASS — `UnknownParameterError` |
| Exact parameter-key spelling | ✅ PASS |
| Explicit internal string bounds | ✅ PASS — `MAX_PARAM_STRING_LENGTH = 1024` |
| No silent coercion | ✅ PASS — `type(val) is not str/bool` |
| Raw ActionContract cannot bypass | ✅ PASS — `__post_init__` re-validates |
| No provider/network imports | ✅ PASS — verified via AST |
| Validation ≠ authority | ✅ PASS |

**Verdict: PASS**

### Dimension 5 — Authority / Approval Binding

| Check | Result |
|---|---|
| Classification exact | ✅ PASS — frozen table verified |
| Only accepts ValidatedActionContract | ✅ PASS |
| Approval cannot lower authority class | ✅ PASS |
| Chat "yes" cannot authorize | ✅ PASS — requires ApprovalGrant |
| Exact binding (mission/action/type/params/target) | ✅ PASS — 9 verification rules |
| Authority-class binding | ✅ PASS |
| Validity window: issued_at ≤ at < expires_at | ✅ PASS |
| Timezone-aware `at` | ✅ PASS |
| Binding hash recomputation | ✅ PASS |
| Constant-time comparison (hmac.compare_digest) | ✅ PASS |
| Altered binding hash fails | ✅ PASS |
| Wrong mission/action/params/resource/parent fails | ✅ PASS |
| External target IDs not echoed in errors | ✅ PASS |
| READ_ONLY/REVERSIBLE_AUTO reject approval | ✅ PASS |
| IRREVERSIBLE cannot auto-authorize | ✅ PASS |
| No single-use durable consumption claim | ✅ PASS — documented |
| Authority success ≠ EXECUTED/VERIFIED/READY | ✅ PASS |

**Verdict: PASS**

### Dimension 6 — Demo-Resource Isolation

| Check | Result |
|---|---|
| calendar.read/update → parent_id == demo cal | ✅ PASS |
| task.read → parent_id == demo task-list | ✅ PASS |
| task.create → resource_id == demo task-list, parent_id None | ✅ PASS |
| weather.read → NOT_APPLICABLE | ✅ PASS |
| Explicit runtime scope only | ✅ PASS — no env/global |
| No "primary" alias | ✅ PASS |
| No wildcard | ✅ PASS |
| Exact case-sensitive matching | ✅ PASS — Python `!=` |
| No strip/prefix/suffix/substring | ✅ PASS |
| Raw IDs absent from repr/error | ✅ PASS — `***` masking |
| Raw ActionContract rejected | ✅ PASS |
| Isolation ≠ authority | ✅ PASS |
| Static match ≠ Google-confirmed | ✅ PASS |

**Verdict: PASS**

### Dimension 7 — Endpoint Rate / Budget Contract

| Check | Result |
|---|---|
| Finite general request limit | ✅ PASS |
| Finite paid-live limit | ✅ PASS |
| Bool rejected as integer | ✅ PASS |
| Half-open window: start ≤ at < end | ✅ PASS |
| Timezone-aware `at` | ✅ PASS |
| live_paid_path_enabled defaults False | ✅ PASS |
| PAID_CAPABLE_LIVE + PUBLIC_UNTRUSTED denied | ✅ PASS |
| Operator classification not from request payload | ✅ PASS |
| Exact Decimal arithmetic | ✅ PASS |
| No float/string money coercion | ✅ PASS |
| Conservative positive cost estimate required | ✅ PASS |
| Fresh budget truth required | ✅ PASS |
| Confirmed credit coverage required | ✅ PASS |
| Internal gross ceiling enforced | ✅ PASS |
| Remaining credit enforced | ✅ PASS |
| Promotional credit ≠ AWS hard cap | ✅ PASS |
| Self-validating decision construction | ✅ PASS |
| Contradictory ALLOW/DENY fails closed | ✅ PASS |
| No atomic quota consumption claim | ✅ PASS |
| Persistent counters deferred to P-05.05 | ✅ PASS |
| ALLOW ≠ billing proof | ✅ PASS |

**Verdict: PASS**

### Dimension 8 — Cross-Gate Composition

| Invariant | Result |
|---|---|
| ValidatedActionContract ≠ authority | ✅ PASS — tested |
| AuthorityDecision ALLOW ≠ demo isolation | ✅ PASS — tested |
| DemoIsolationResult ISOLATED ≠ authority | ✅ PASS — tested |
| EndpointAdmissionDecision ALLOW ≠ action/authority/isolation | ✅ PASS — tested |
| Redacted evidence ≠ execution/verification | ✅ PASS |
| ApprovalGrant ≠ supported action or isolation | ✅ PASS — tested |

**Verdict: PASS**

### Dimension 9 — Executor-Success / Fact-Authority Law

| Check | Result |
|---|---|
| EXECUTED_UNVERIFIED cannot → READY | ✅ PASS — `IllegalStatePromotionError` |
| NOT_RUN ≠ PASS | ✅ PASS — explicit check |
| Capture existence ≠ VERIFIED | ✅ PASS — `CaptureDigest` docstring |
| Approval ≠ VERIFIED | ✅ PASS |
| Isolation ≠ VERIFIED | ✅ PASS |
| Endpoint admission ≠ VERIFIED | ✅ PASS |
| READY requires all VERIFIED + VERIFYING state | ✅ PASS |
| READY → DRIFTED remains possible | ✅ PASS — transition table |
| No alternate promotion path introduced | ✅ PASS |

**Verdict: PASS**

### Dimension 10 — External-ID / Secret Error Surfaces

| Surface | Result |
|---|---|
| Config errors | ✅ PASS — `is_secret` redacts plaintext |
| Redaction errors | ✅ PASS — type names only |
| Action validation errors | ✅ PASS — no parameter values echoed |
| Authority errors | ✅ PASS — no target IDs echoed |
| Demo isolation errors | ✅ PASS — `***` masking, generic messages |
| Endpoint protection errors | ✅ PASS — no sensitive data |

**Note (non-blocking):** `ValidatedActionContract` and `ActionContract` use default dataclass `__repr__` which would include `resource_id`/`parent_id`. This is a P-02 domain-model concern rather than a P-04 error surface defect, as all P-04 exception paths explicitly avoid echoing these values. Observation recorded; not classified as P-04 blocker.

**Verdict: PASS**

### Dimension 11 — Future-Phase Leakage

| Check | Result |
|---|---|
| No MCP server | ✅ PASS |
| No Streamable HTTP transport | ✅ PASS |
| No MCP tool routes | ✅ PASS |
| No auth middleware | ✅ PASS |
| No persistent/atomic counter store | ✅ PASS |
| No Google Calendar adapter | ✅ PASS |
| No Google Tasks adapter | ✅ PASS |
| No Open-Meteo adapter | ✅ PASS |
| No read-back verifier | ✅ PASS |
| No planner/model integration | ✅ PASS |

**Verdict: PASS**

### Dimension 12 — Live / Evidence Mode Truth

| Check | Result |
|---|---|
| No AWS live calls in P-04 | ✅ PASS |
| No Google live calls in P-04 | ✅ PASS |
| No Open-Meteo live calls in P-04 | ✅ PASS |
| No MCP live calls in P-04 | ✅ PASS |
| No model live calls in P-04 | ✅ PASS |

Evidence provenance: `LOCAL_EXECUTION` only.

**Verdict: PASS**

### Dimension 13 — Cost / Zero-Spend

| Check | Result |
|---|---|
| Personal-spend target | $0.00 |
| P-04 provider/cloud calls | Zero |
| No automatic paid fallback | ✅ PASS |
| No public unmetered paid endpoint | ✅ PASS (P-04.06 is contract only) |
| Promotional credit ≠ hard AWS spend cap | ✅ PASS (documented) |

**Verdict: PASS**

### Dimension 14 — Donor / License / Dependencies

| Check | Result |
|---|---|
| Apache-2.0 present | ✅ PASS |
| No P-04 donor source copied | ✅ PASS |
| P-04 code is CLEAN_ROOM_REIMPLEMENTED | ✅ PASS |
| `dependencies = []` in pyproject.toml | ✅ PASS |
| No unnecessary provider SDKs | ✅ PASS |

**Verdict: PASS**

### Dimension 15 — Secret Scan

| Check | Result |
|---|---|
| AWS access key patterns | ✅ PASS — only test sentinels (`AKIAIOSFODNN7EXAMPLE`) |
| OAuth tokens | ✅ PASS — none committed |
| client_secret assignments | ✅ PASS — only in redaction regex |
| Authorization/Bearer material | ✅ PASS — only in redaction patterns |
| Private keys | ✅ PASS — none found |
| .env files | ✅ PASS — none committed |
| Real email addresses | ✅ PASS — only test sentinels |

**Verdict: PASS**

### Dimension 16 — Test Integrity

| Check | Result |
|---|---|
| Negative tests exercise production paths | ✅ PASS |
| No implementation-bypassing monkeypatches | ✅ PASS |
| Expected failure assertions specific | ✅ PASS |
| No removed/weakened security tests | ✅ PASS |
| Direct-construction/bypass tests present | ✅ PASS |
| External-ID secrecy tests present | ✅ PASS |
| URL encoded key/value regressions present | ✅ PASS |
| Endpoint decision direct-construction regressions | ✅ PASS |

**Verdict: PASS**

## 5. Added Audit Tests

File: `tests/test_phase_p04_security_audit.py` — 40 tests

Cross-boundary invariants frozen:
- Canonical action vocabulary = exactly 5
- Exact authority classification table
- No P-04 security result exposes VERIFIED/READY
- No forbidden provider/network imports in 7 P-04 modules (AST verification)
- No provider execution capabilities
- No future-phase modules/packages
- Cross-gate non-substitutability (5 independence proofs)
- Fact-authority law preservation (4 P-03 contract tests)

## 6. Test Results

| Suite | Result |
|---|---|
| test_config.py | ✅ PASS |
| test_redaction.py | ✅ PASS |
| test_capture.py | ✅ PASS |
| test_action_policy.py | ✅ PASS |
| test_authority_policy.py | ✅ PASS |
| test_demo_isolation.py | ✅ PASS |
| test_endpoint_protection.py | ✅ PASS |
| test_phase_p04_security_audit.py | ✅ 40/40 PASS |
| **Full suite** | **631 passed in 2.83s** |

## 7. Validation Pipeline

| Check | Result |
|---|---|
| `uv sync --frozen` | ✅ PASS |
| `ruff format --check .` | ✅ PASS |
| `ruff check .` | ✅ PASS |
| `mypy src tests` | ✅ PASS |
| `pytest` | ✅ 631 passed |
| `python scripts/validate.py` | ✅ ALL VALIDATION CHECKS PASSED |

## 8. Known Limitations / Deferred Controls

These are **ACCEPTABLE DEFERRED CONTROLS** — not P-04 defects:

| Control | Status | Target Phase |
|---|---|---|
| Durable approval consumption/revocation | Deferred | P-11 |
| Atomic persistent public endpoint counters | Deferred | P-05.05 |
| Transport authentication | Deferred | P-05.05 |
| Real MCP server | Deferred | P-05.01 |
| Google/AWS provider adapters | Deferred | P-06 |
| Live resource-membership verification | Deferred | P-06 |
| Live write/read-back | Deferred | P-06+ |
| Durable production ledger | Deferred | P-12 |
| Execution orchestrator | Deferred | P-08 |
| Real current billing hard-stop | Deferred | P-05.05 |
| ValidatedActionContract/ActionContract custom repr | Observation | Future hardening |

P-04 code/docs do not falsely claim any of these exist.

## 9. Evidence Provenance

- All P-04 evidence: `LOCAL_EXECUTION`
- Historical P-01 live evidence: `RECORDED_LIVE` (not relabeled)
- CI evidence: GitHub Actions (not labeled as `LIVE_EXTERNAL` provider evidence)

## 10. Cost Truth

- Personal-spend target: $0.00
- P-04: zero provider/cloud calls
- Historical P-01: actual billed cost as documented in existing records
- Promotional credit is not treated as hard AWS spend cap

## 11. Donor / Provenance Truth

- Reuse class: `CLEAN_ROOM_REIMPLEMENTED`
- Zero donor lines imported in P-04
- No provenance blocker

## 12. Phase-Gate Recommendation

**P-04.07 audit candidate found no blockers.**

All 16 audit dimensions passed. No production source changes were required.

The executor does NOT self-award independent QA PASS.

### Recommended Status

```
P-04.01 — PASS
P-04.02 — PASS
P-04.03 — PASS
P-04.04 — PASS
P-04.05 — PASS
P-04.06 — PASS
P-04.07 — DONE — awaiting independent QA
Phase P-04 — CLOSURE CANDIDATE / awaiting independent QA
P-05.01 — PENDING / NOT AUTHORIZED
```
