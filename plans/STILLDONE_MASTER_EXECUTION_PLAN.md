# STILLDONE MASTER EXECUTION PLAN

Status vocabulary:
`PENDING`, `IN_PROGRESS`, `DONE`, `BLOCKED`.

Exact micro-task titles are immutable after canonical bootstrap.

## Global acceptance laws

1. Remote `main` is canonical after bootstrap.
2. No agent report can close its own task.
3. One exact micro-task at a time unless a bounded batch is explicit.
4. Edited ≠ validated.
5. Local commit ≠ remote closure.
6. `NOT_RUN` ≠ PASS.
7. Fixture/simulation ≠ live.
8. Recorded live ≠ current live.
9. Model prose cannot override deterministic facts.
10. Execute success cannot directly produce `VERIFIED`.
11. Required mutation verification needs independent read-back.
12. Mission `READY` is deterministic and revocable.
13. Current source-of-truth state outranks historical receipt.
14. Required mutations need idempotency/dedup semantics.
15. Blocked steps remain `NOT_RUN`.
16. Approval binds exact mission/action/params/target/expiry.
17. Live-required paths fail visibly; no silent fallback.
18. Competition-defining donor logic is concept-only/clean-room by default.
19. No secrets in prompts, repository, durable evidence, screenshots, or public logs.
20. Target personal spend is `$0.00`.
21. Public live endpoints must be budget bounded.
22. Current external platform facts come from official docs/live discovery.
23. Friction log records only observed facts.
24. User-facing demo simplicity outranks decorative architecture.
25. No future-phase implementation leakage.
26. Broad P-Ω audits occur at major proof/phase boundaries.

## Competition critical path

1. P-00 trusted repository/governance baseline.
2. P-01 live access/cost/technology feasibility.
3. P-02 provider-neutral mission/state contracts.
4. P-03 deterministic evidence/ledger primitives.
5. P-04 security/privacy/authority foundation.
6. P-05 real MCP Streamable HTTP spine.
7. P-06 real external service adapters and write/read-back proof.
8. P-07 real AWS planning/agent path.
9. P-08 deterministic mission execution engine.
10. P-09 independent verifier + reconciliation.
11. P-10 idempotency/retry/recovery.
12. P-11 approval compression.
13. P-12 durable cross-session state + drift.
14. P-13 complete killer mission vertical slice.
15. P-14 adversarial/failure campaign.
16. P-15 judge UX + simulated Alexa+ surface.
17. P-16 AWS Builder depth.
18. P-17 Open Source Mini Challenge.
19. P-18 latency/cost/reliability hardening.
20. P-19 judge reproduction/deployment.
21. P-20 competition evidence/feedback pack.
22. P-21 demo video.
23. P-22 submission freeze.

---

# P-00 — Repository, Competition Contract & Governance Bootstrap

Goal:
establish a trustworthy empty-product baseline before product code.

### P-00.01 — Bootstrap canonical StillDone repository from the frozen starter pack
Status: DONE

Acceptance:
- public `zyganali-glitch/StillDone` on `main`;
- Apache-2.0 visible;
- starter pack committed;
- no product/runtime code;
- no secrets/private local paths;
- remote SHA independently verifiable;
- HANDOFF points to P-00.02.

### P-00.02 — Re-verify competition rules, eligibility, submission contract, prizes, and judging criteria against current official sources
Status: DONE

Acceptance:
- current Devpost rules re-opened;
- deadline/judging dates recorded;
- Alexa+ qualifying routes confirmed;
- AWS Builder/Open Source requirements confirmed;
- repository/video/feedback/friction requirements confirmed;
- no stale competition claim.

### P-00.03 — Freeze donor pins, licenses, and concept-only provenance boundaries
Status: DONE

Acceptance:
- every donor immutable SHA or explicit source limitation;
- root license verified;
- reuse class frozen;
- zero implementation code imported.

### P-00.04 — Select minimal language/tooling baseline and deterministic validation commands
Status: DONE

Acceptance:
- language/runtime choice justified against MCP + AWS SDK support;
- lockfile strategy;
- formatter/linter/type/test commands;
- minimal package skeleton only;
- CI-compatible;
- no fake AWS/Google adapter.

### P-00.05 — Close bootstrap with documentation consolidation and focused P-Ω audit
Status: DONE

Acceptance:
- README/Plan/HANDOFF critical truth aligned;
- zero secrets;
- no future-phase code;
- clean-checkout bootstrap validation;
- independent QA required for phase closure.

Phase exit:
trusted empty-product repo exists.

---

# P-01 — Live Access, Zero-Cost & Platform Feasibility

Goal:
prove real required technologies before broad implementation.

### P-01.01 — Verify AWS account, hackathon credit, billing safety, region, and service-access reality
Status: PENDING

Acceptance:
- actual account/credit state observed;
- credit expiry/amount recorded;
- personal-spend risk documented;
- safe budget/kill strategy defined;
- no paid fallback enabled silently.

### P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt
Status: PENDING

Acceptance:
- current model ID discovered from live/official reality;
- real request/response;
- timing/cost metadata where available;
- provenance `LIVE_AWS`;
- no fixture fallback.

### P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model
Status: PENDING

Acceptance:
- real Strands runtime;
- bounded tool-free or harmless-tool run;
- exact versions recorded;
- deterministic event/result capture.

### P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence
Status: PENDING

Acceptance:
- if available/affordable: deploy harmless minimal runtime and invoke it;
- if unavailable: exact blocker documented;
- no architecture fiction;
- decision influences P-01.08.

### P-01.05 — Prove Google OAuth and live read-only access to dedicated demo Calendar and Tasks resources
Status: PENDING

Acceptance:
- dedicated demo resources created or identified;
- Calendar live read;
- Tasks live read;
- minimum feasible scopes documented;
- no unrelated personal data captured.

### P-01.06 — Execute first live Open-Meteo forecast call and record attribution/limit contract
Status: PENDING

Acceptance:
- live response;
- configured public city/location only;
- no API key;
- provenance `LIVE_EXTERNAL`;
- data attribution requirement recorded.

### P-01.07 — Validate MCP/Alexa+ current protocol requirements and build a minimal remote Streamable HTTP echo/health proof
Status: PENDING

Acceptance:
- current spec requirement re-verified;
- remote HTTPS endpoint;
- Streamable HTTP works;
- protocol/version recorded;
- latency measured;
- no product tools yet.

### P-01.08 — Freeze architecture v1 and issue live feasibility GO/BLOCKED decision
Status: PENDING

Acceptance:
- exact proven AWS stack selected;
- exact rejected/deferred AWS services named;
- external service set frozen;
- zero-cost path credible through judging;
- Alexa+ actual access remains optional unless proven;
- no mocked substitute can produce GO.

#### External-blocker parallelization law

If an AWS promotional-credit or access dependency blocks P-01 solely for external reasons, the independent QA may explicitly allow:
- P-02 provider-neutral contracts; then
- P-03 deterministic local evidence primitives.

Hard stop after P-03 without a new explicit amendment.
The P-01 phase remains open and cannot receive GO from local work.

Phase exit:
real model + real agent/runtime decision + real Google reads + real weather + real remote MCP spine proven.

---

# P-02 — Provider-Neutral Mission & Desired-State Contracts

Goal:
encode truth semantics before orchestration.

### P-02.01 — Define mission identity, immutable mission contract, and user-intent snapshot
Status: PENDING

### P-02.02 — Define desired-state predicate schema, required/optional semantics, and freshness contract
Status: PENDING

### P-02.03 — Define action contract, supported action vocabulary, target identity, and parameter normalization
Status: PENDING

### P-02.04 — Define mission lifecycle and step evidence states
Status: PENDING

### P-02.05 — Define authority classes, approval object, binding hash, and expiry semantics
Status: PENDING

### P-02.06 — Define idempotency, retry, attempt, resource, and reconciliation contracts
Status: PENDING

### P-02.07 — Define evidence provenance and live/recorded/fixture separation
Status: PENDING

### P-02.08 — Add serialization, schema, forbidden-transition, and provider-purity tests
Status: PENDING

Phase exit:
core domain imports no AWS/Google/MCP UI SDK objects.

---

# P-03 — Deterministic Evidence Ledger & Fact Authority

Goal:
make evidence immutable enough to reason about honestly.

### P-03.01 — Implement canonical serialization and SHA-256 content-addressed evidence IDs
Status: PENDING

### P-03.02 — Implement append-only mission/action/evidence ledger interfaces
Status: PENDING

### P-03.03 — Implement deterministic state-transition guards
Status: PENDING

### P-03.04 — Implement bounded sanitized provider-output capture with digests
Status: PENDING

### P-03.05 — Bind receipt projections to exact mission/evidence hashes
Status: PENDING

### P-03.06 — Add tamper, mismatch, replay, stale, and forbidden-promotion tests
Status: PENDING

Phase exit:
local deterministic evidence primitives are green but do not claim live integration.

---

# P-04 — Security, Privacy & Authority Foundation

Goal:
make future live actions bounded by design.

### P-04.01 — Implement secret/config loading and fail-closed validation
Status: PENDING

### P-04.02 — Implement log/evidence redaction for tokens, OAuth material, emails, and sensitive identifiers
Status: PENDING

### P-04.03 — Implement supported-action allowlist and parameter validation
Status: PENDING

### P-04.04 — Implement authority classification and approval-binding verification
Status: PENDING

### P-04.05 — Implement demo-resource isolation checks
Status: PENDING

### P-04.06 — Implement public-endpoint rate/budget protection contract
Status: PENDING

### P-04.07 — Run focused security/threat-model P-Ω audit
Status: PENDING

Phase exit:
live writes may begin only after this phase.

---

# P-05 — Real MCP Server Spine

Goal:
build the Alexa+ track's real open-standard interface.

### P-05.01 — Implement MCP server with current required Streamable HTTP transport
Status: PENDING

### P-05.02 — Implement protocol initialization, capability declaration, and health/readiness
Status: PENDING

### P-05.03 — Expose read-only mission-status tool over typed contracts
Status: PENDING

### P-05.04 — Expose mission-start tool without live mutation yet
Status: PENDING

### P-05.05 — Add auth/rate-limit boundary appropriate to the proven judge path
Status: PENDING

### P-05.06 — Validate with current MCP inspector/client and remote deployment
Status: PENDING

### P-05.07 — Measure protocol latency and document Alexa+ direct-access compatibility gap
Status: PENDING

Phase exit:
real remote MCP server works; no fake Alexa+ integration claim.

---

# P-06 — Real External Service Adapters

Goal:
prove external state can be read, mutated safely, and read back.

### P-06.01 — Implement Google Calendar read adapter against dedicated demo calendar
Status: PENDING

### P-06.02 — Implement Google Calendar bounded update adapter with idempotency strategy
Status: PENDING

### P-06.03 — Implement Calendar independent read-back verifier
Status: PENDING

### P-06.04 — Implement Google Tasks read/create adapter against dedicated demo list
Status: PENDING

### P-06.05 — Implement Tasks independent read-back verifier and duplicate detection
Status: PENDING

### P-06.06 — Implement Open-Meteo live observation adapter with attribution
Status: PENDING

### P-06.07 — Prove first live write → read-back → VERIFIED slice on Tasks
Status: PENDING

### P-06.08 — Prove first live Calendar update → read-back → VERIFIED slice
Status: PENDING

Phase exit:
two real mutable systems independently verified.

---

# P-07 — Real AWS Planning & Agent Path

Goal:
make required AWS intelligence materially useful without giving it fact authority.

### P-07.01 — Define strict planner input/output schema and supported action vocabulary
Status: PENDING

### P-07.02 — Implement real Bedrock planner adapter with exact timeout/token/retry settings
Status: PENDING

### P-07.03 — Implement real Strands planning agent using bounded tools/context
Status: PENDING

### P-07.04 — Reject malformed, unsupported, over-broad, or authority-violating model plans
Status: PENDING

### P-07.05 — Bind exact planner model/runtime/version metadata to evidence
Status: PENDING

### P-07.06 — Prove model is necessary for natural-language mission compilation in the live path
Status: PENDING

Phase exit:
AWS intelligence is genuine and bounded.

---

# P-08 — Deterministic Mission Execution Engine

Goal:
execute compiled plans without letting planner prose own truth.

### P-08.01 — Implement mission compiler from validated plan to immutable execution contract
Status: PENDING

### P-08.02 — Implement deterministic action scheduler and dependency ordering
Status: PENDING

### P-08.03 — Implement partial-failure preservation and per-step states
Status: PENDING

### P-08.04 — Implement execution attempts and provider-result recording
Status: PENDING

### P-08.05 — Implement no-silent-fallback adapter routing
Status: PENDING

### P-08.06 — Add mixed success/failure/not-run mission tests
Status: PENDING

Phase exit:
multi-step mission executes honestly.

---

# P-09 — Independent Verification & Reconciliation Engine

Goal:
make reality, not the executor, decide completion.

### P-09.01 — Implement verifier dispatch independent from execute result payload
Status: PENDING

### P-09.02 — Implement exact predicate evaluation for Calendar and Tasks
Status: PENDING

### P-09.03 — Implement freshness/stale evaluation
Status: PENDING

### P-09.04 — Implement deterministic mission readiness computation
Status: PENDING

### P-09.05 — Implement reconciliation of previously verified mission against fresh external state
Status: PENDING

### P-09.06 — Implement `READY → DRIFTED` downgrade with mismatch explanation
Status: PENDING

### P-09.07 — Add executor-success/readback-mismatch and stale-history tests
Status: PENDING

Phase exit:
renewable completion exists.

---

# P-10 — Idempotency, Retry & Recovery

Goal:
survive ambiguous network failures without duplicate real-world effects.

### P-10.01 — Freeze idempotency strategy per supported mutation
Status: PENDING

### P-10.02 — Implement bounded exponential retry and retry classification
Status: PENDING

### P-10.03 — Implement read-before-retry / verify-after-timeout behavior where appropriate
Status: PENDING

### P-10.04 — Implement duplicate detection and duplicate evidence state
Status: PENDING

### P-10.05 — Implement process restart/resume from durable mission ledger
Status: PENDING

### P-10.06 — Run injected timeout-after-write and crash/restart campaign
Status: PENDING

Phase exit:
at least one real failure can resume without duplicate effect.

---

# P-11 — Approval Compression

Goal:
reserve human attention for the meaningful boundary.

### P-11.01 — Freeze authority policy for canonical mission actions
Status: PENDING

### P-11.02 — Implement pending approval object and one-decision UX contract
Status: PENDING

### P-11.03 — Bind approval to exact mission/action/target/parameters/expiry
Status: PENDING

### P-11.04 — Reject stale, mismatched, replayed, or already-used approvals
Status: PENDING

### P-11.05 — Prove Calendar existing-event update remains NOT_RUN before approval
Status: PENDING

### P-11.06 — Prove approved Calendar update executes once and verifies
Status: PENDING

Phase exit:
one meaningful approval replaces repeated confirmations.

---

# P-12 — Durable Mission Continuity & Drift

Goal:
make missions survive sessions and reality changes.

### P-12.01 — Implement durable mission snapshot repository using the P-01-approved persistence path
Status: PENDING

### P-12.02 — Implement reload/resume across a fresh process/session
Status: PENDING

### P-12.03 — Implement bounded revalidation command/tool
Status: PENDING

### P-12.04 — Implement external-change drift detection on Calendar
Status: PENDING

### P-12.05 — Implement external-change drift detection on Tasks
Status: PENDING

### P-12.06 — Preserve historical receipt while publishing current truth
Status: PENDING

### P-12.07 — Run fresh-session `Are we still ready?` proof
Status: PENDING

Phase exit:
cross-session renewable completion proven.

---

# P-13 — Canonical Killer Mission Vertical Slice

Goal:
assemble the complete competition-defining experience.

### P-13.01 — Seed canonical disposable demo resources reproducibly
Status: PENDING

### P-13.02 — Execute full live mission from natural language through AWS planner
Status: PENDING

### P-13.03 — Create and independently verify real Tasks preparation action
Status: PENDING

### P-13.04 — Pause real Calendar change at approval boundary
Status: PENDING

### P-13.05 — Approve, execute, and independently verify real Calendar change
Status: PENDING

### P-13.06 — Produce `READY` mission receipt from deterministic facts
Status: PENDING

### P-13.07 — Mutate Calendar externally and prove `READY → DRIFTED`
Status: PENDING

### P-13.08 — Reproduce the entire live slice from a clean checkout
Status: PENDING

### P-13.09 — Run major P-Ω live-milestone audit
Status: PENDING

Phase exit:
competition thesis is real end-to-end.

---

# P-14 — Failure & Adversarial Campaign

Goal:
prove honesty under failure, not just success.

### P-14.01 — Provider 5xx/timeout before mutation
Status: PENDING

### P-14.02 — Timeout after mutation but before response
Status: PENDING

### P-14.03 — Read-back mismatch after execute success
Status: PENDING

### P-14.04 — OAuth permission revoked mid-mission
Status: PENDING

### P-14.05 — Model returns malformed/unsupported/over-authorized plan
Status: PENDING

### P-14.06 — Approval replay/mismatch/stale approval
Status: PENDING

### P-14.07 — Evidence tamper/replay/stale receipt
Status: PENDING

### P-14.08 — Duplicate retry stress
Status: PENDING

Phase exit:
failures remain truthful and bounded.

---

# P-15 — Judge UX & Simulated Alexa+ Experience

Goal:
make complex verification feel simple.

### P-15.01 — Design one-screen mission timeline and compact receipt
Status: PENDING

### P-15.02 — Implement simulated Alexa+ conversational surface with explicit label
Status: PENDING

### P-15.03 — Implement voice-friendly concise summaries
Status: PENDING

### P-15.04 — Implement approval card with exact bounded action
Status: PENDING

### P-15.05 — Implement READY/PARTIAL/DRIFTED visual hierarchy
Status: PENDING

### P-15.06 — Add expandable evidence detail without overwhelming primary UX
Status: PENDING

### P-15.07 — Run accessibility/responsive/browser checks
Status: PENDING

Phase exit:
judge understands product in under 20 seconds.

---

# P-16 — AWS Builder Depth

Goal:
maximize real AWS value without decorative service sprawl.

### P-16.01 — Audit actual AWS services used in the live critical path
Status: PENDING

### P-16.02 — Add exactly one additional AWS service only if it materially improves durable state, policy, identity, observability, or runtime
Status: PENDING

### P-16.03 — Prove the added AWS service live and document why it is not decorative
Status: PENDING

### P-16.04 — Produce AWS Builder architecture/evidence map
Status: PENDING

### P-16.05 — Validate cost impact against remaining promotional budget
Status: PENDING

Phase exit:
AWS Builder submission is creative and real.

---

# P-17 — Open Source Mini Challenge

Goal:
create a genuinely useful additional OSS contribution after the core is proven.

### P-17.01 — Select OSS route: new library or meaningful upstream contribution
Status: PENDING

Preferred concept:
generic MCP execute→read-back→verify integration pattern/middleware.

### P-17.02 — Freeze separate repo/contribution provenance and license
Status: PENDING

### P-17.03 — Implement reusable verification contract with tests
Status: PENDING

### P-17.04 — Add at least one real integration example
Status: PENDING

### P-17.05 — Publish contribution URL/repo/fork/PR during hackathon window
Status: PENDING

### P-17.06 — Produce Open Source mini-challenge evidence description
Status: PENDING

Phase exit:
meaningful tested OSS work exists beyond the main repo.

---

# P-18 — Performance, Cost & Reliability Hardening

Goal:
ensure the real build survives judging and stays within budget.

### P-18.01 — Measure end-to-end mission latency and per-component latency
Status: PENDING

### P-18.02 — Measure MCP transport latency against current Alexa+ requirements
Status: PENDING

### P-18.03 — Measure AWS usage/cost per canonical mission
Status: PENDING

### P-18.04 — Enforce runtime budget/rate limits
Status: PENDING

### P-18.05 — Verify Google/Open-Meteo quota safety
Status: PENDING

### P-18.06 — Run bounded repeated-mission reliability test
Status: PENDING

### P-18.07 — Verify judge-period availability plan and credit expiry
Status: PENDING

Phase exit:
demo and judge path are financially and operationally credible.

---

# P-19 — Judge Reproduction & Deployment

Goal:
make the project inspectable without hiding behind the developer machine.

### P-19.01 — Create clean-checkout setup path
Status: PENDING

### P-19.02 — Create sanitized demo-resource setup/teardown commands
Status: PENDING

### P-19.03 — Deploy final remote MCP/runtime path
Status: PENDING

### P-19.04 — Publish read-only public judge exhibit without unmetered paid execution
Status: PENDING

### P-19.05 — Write no-install judge path and full reproduction path
Status: PENDING

### P-19.06 — Fresh-environment reproduction and evidence capture
Status: PENDING

Phase exit:
judges can understand and reproduce the supported boundary.

---

# P-20 — Competition Evidence, Feedback & Claim Audit

Goal:
bind every submission claim to proof.

### P-20.01 — Consolidate factual product feedback for every Amazon/AWS tool used
Status: PENDING

### P-20.02 — Consolidate friction logs and actionable suggestions
Status: PENDING

### P-20.03 — Build claim-by-claim evidence manifest
Status: PENDING

### P-20.04 — Build judging-criteria map
Status: PENDING

### P-20.05 — Build live/recorded/fixture/simulated disclosure
Status: PENDING

### P-20.06 — Audit donor/license/build-period truth
Status: PENDING

Phase exit:
no unsupported competition claim remains.

---

# P-21 — Demo Video & Submission Media

Goal:
deliver a sub-3-minute proof-first story.

### P-21.01 — Freeze 2:30–2:50 demo script and shot list
Status: PENDING

### P-21.02 — Record fresh canonical live mission
Status: PENDING

### P-21.03 — Record external drift and fresh reconciliation
Status: PENDING

### P-21.04 — Produce English TTS/captions and remove secret/PII exposure
Status: PENDING

### P-21.05 — Verify video duration/public playback/copyright/trademark safety
Status: PENDING

### P-21.06 — Produce final screenshot gallery
Status: PENDING

Phase exit:
video leads with real product proof.

---

# P-22 — Submission Freeze

Goal:
freeze a truthful, reproducible, eligible competition candidate.

### P-22.01 — Re-verify current official rules and submission form fields
Status: PENDING

### P-22.02 — Final full test, clean-checkout, live-smoke, and P-Ω audit
Status: PENDING

### P-22.03 — Freeze final Devpost text, AWS Builder answer, Open Source answer, feedback, and friction logs
Status: PENDING

### P-22.04 — Verify public repo/license/About metadata and judge links
Status: PENDING

### P-22.05 — Verify judge-period service/budget availability
Status: PENDING

### P-22.06 — Tag immutable submission candidate and record final SHA
Status: PENDING

### P-22.07 — Operator submits Devpost and records submission evidence
Status: PENDING

Phase exit:
SUBMITTED.
