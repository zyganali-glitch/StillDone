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
Status: DONE — independent QA PASS (Verified SHA: `e3d5aa79d8569ebe7e20e48300060b15ba30c187`)

Acceptance:
- actual account/credit state observed: YES (Paid account plan; Basic support plan; credit usage at checkpoint: $0.00 observed; current account charges: NOT_OBSERVED / UNKNOWN in P-01.01 evidence);
- credit expiry/amount recorded: $150.00 granted / $150.00 remaining / $0.00 used; Billing detail expiration: 2028-09-01; hackathon email wording: 2028-08-31; discrepancy: OBSERVED; cause: UNKNOWN / NOT_ESTABLISHED (conservative boundary applies); separate $100 AWS Free Tier signup credit noted ($250 total remaining);
- credit coverage observed: live Billing "Applicable products" list explicitly includes Amazon Bedrock and AgentCore services;
- personal-spend risk documented: Zero Personal Spend Law ($0.00) enforced; credits offset bills but do not hard-cap spend; AWS Budgets confirmed asynchronous alerting (8–12 hr delay);
- safe budget/kill strategy defined: decision SAFE_TO_ATTEMPT_NEXT_LIVE_TASK strictly bounds next live work to one single P-01.02 test inference; documented in `docs/P01_LIVE_FEASIBILITY.md`;
- mutations recorded: reconciliation executor AWS mutations: NONE; cloud resource mutations: NONE; Bedrock inference: NONE; prior operator account/billing actions (creation, Paid plan, credit redemption) recorded only as current state;
- no paid fallback enabled silently: guaranteed by policy;
- note: P-01.01 independent QA PASS was awarded (Verified SHA: `e3d5aa79d8569ebe7e20e48300060b15ba30c187`). Task P-01.02 subsequently executed under bounded QA authorization; P-01.02 is now BLOCKED / NOT ACCEPTED (current blocker is authorizationStatus = NOT_AUTHORIZED; external state = AWS_SUPPORT_PENDING; third inference is NOT AUTHORIZED).


### P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt
Status: DONE — independent QA PASS (Verified SHA: `67bf97a26e3c5a1cea9cb90929cfa390c43b9995`)

Acceptance:
- current model ID discovered from live/official reality: YES (`amazon.nova-micro-v1:0` selected via live Bedrock `list-foundation-models` in `us-east-1` across cycles);
- pre-call pricing and cost bounded: YES (official Bedrock pricing verified; gross request upper bound <= $0.000006, well below $0.01 limit);
- real request attempts executed: Cycle 1 = 1 attempt; Cycle 2 = 1 attempt; Diagnostic Cycle = 0 attempts; Cycle 3 = 1 attempt (Cumulative inference attempts = 3);
- read-only diagnostic executed: Cycle 3 preflight `get-foundation-model-availability` returned `authorizationStatus = AUTHORIZED` (agreement: AVAILABLE, entitlement: AVAILABLE, region: AVAILABLE, agreementError: null);
- AWS Support remediation: authenticated AWS Support case opened on 2026-09-27, operator provided project use case on 2026-09-28, AWS Support confirmed account adjustments completed by authorized service team (blocker functionally remediated; administrative case state: NOT_OBSERVED / NOT_ESTABLISHED);
- live results observed:
  - Cycle 1: `AccessDeniedException` (`Your account is currently being verified. Verification normally takes less than 2 hours.`);
  - Cycle 2: `ValidationException` (`Operation not allowed`);
  - Diagnostic Cycle: `get-foundation-model-availability` -> `authorizationStatus = NOT_AUTHORIZED`;
  - AWS Support Remediation: AWS Support confirmed account adjustments completed for base models; blocker functionally remediated;
  - Cycle 3 Preflight: `get-foundation-model-availability` -> `authorizationStatus = AUTHORIZED`;
  - Cycle 3 Inference: **SUCCESS** — `aws bedrock-runtime converse` returned genuine model response (`pong`, stopReason=`end_turn`, inputTokens=8, outputTokens=3, totalTokens=11, latency=7259ms);
- zero-retry law enforced: exactly 1 attempt consumed in Cycle 3; zero retries; fourth attempt is strictly NOT_RUN / NOT_AUTHORIZED; no second model, no second region, no fallback provider, no fixture fallback;
- timing/cost metadata: valid usage metadata returned (inputTokens=8, outputTokens=3, totalTokens=11, stopReason=end_turn, latencyMs=7259); usage-derived estimated gross request cost $\approx \$0.00000070$ (well below $\$0.01$ limit; target personal spend remains strictly $\$0.00$); actual billed request cost and post-call billing delta: NOT_OBSERVED / UNKNOWN; personal-spend delta: NOT_OBSERVED / UNKNOWN;
- provenance: `LIVE_AWS`;
- documented evidence: `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`;
- note: Task closed with independent QA PASS (Verified SHA: `67bf97a26e3c5a1cea9cb90929cfa390c43b9995`).


### P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model
Status: DONE — independent QA PASS (Verified SHA: `bfa46d24f20c69557f1e747500e874082f1406ed`)

Acceptance:
- real Strands runtime: YES (`strands-agents 1.57.1`, `boto3 1.43.103`, `botocore 1.43.103`, `awscrt 0.36.0` on Python 3.13.5);
- Bedrock provider integration: native `from strands.models.bedrock import BedrockModel` configured with `amazon.nova-micro-v1:0` in `us-east-1` via short-lived profile session;
- bounded tool-free run: strictly tool-free (`tools=[]`, zero injected tools, zero MCP/shell/network tools, `streaming=False`, `max_tokens=32`, `temperature=0.0`);
- exact prompt & result: prompt `"Reply only with: STRANDS_OK"` executed; model returned `"STRANDS_OK"` (`stop_reason="end_turn"`, tokens: in=8, out=5, total=13, elapsed=1179ms, model latency=264ms, TTFB=1174ms);
- deterministic event/result capture: structured `AgentResult.to_dict()` captured with tracking ID `c8b738aa-5acf-4422-84b5-c8d0d85edda9`;
- zero-retry law enforced: exactly 1 invocation attempt; zero retries; no second model;
- billing truth: usage-derived estimated gross request cost $\approx \$0.00000098$ ($\ll \$0.01$); actual billed request cost / personal-spend delta: NOT_OBSERVED / UNKNOWN; target personal spend remains strictly `$0.00`;
- cleanup & provenance: `aws logout` executed immediately; provenance: `LIVE_AWS + REAL_STRANDS_RUNTIME`;
- documented evidence: `docs/P01_03_LIVE_STRANDS_EVIDENCE.md`;
- note: Task closed with independent QA PASS (Verified SHA: `bfa46d24f20c69557f1e747500e874082f1406ed`).


### P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence
Status: DONE — independent QA PASS (Verified SHA: `274187c19538e9e9f5f18fe3e2f372a8465cbc91`)

Acceptance:
- cycle 1 historical proof preserved: deployed serverless microVM AgentCore runtime to `us-east-1` (CodeZip, Python 3.13, platformVersion `V1`, status `READY`); executed 1 remote invocation; observed Windows PowerShell inline JSON quoting defect yielding deterministic validation string `UNKNOWN_PROMPT`; full teardown executed;
- CDK bootstrap reconciliation & cost remediation: read-only audit confirmed `CDKToolkit` originally created during P-01.04 as retained shared infrastructure; independent QA identified active customer-managed KMS key (`AWS::KMS::Key`, `KeyManager: CUSTOMER`); surgical cost-closure remediation executed via official `cdk bootstrap --no-bootstrap-customer-key` in exactly 1 operation; stack reached `UPDATE_COMPLETE` with `FileAssetsBucketKmsKeyId=AWS_MANAGED_KEY`; `AWS::KMS::Key` transitioned to `DELETE_COMPLETE` in CloudFormation and `PendingDeletion` in KMS ($0 ongoing storage fee); remaining shared resource classes audited: `AWS::ECR::Repository`, `AWS::IAM::Policy`, `AWS::IAM::Role`, `AWS::S3::Bucket`, `AWS::S3::BucketPolicy`, `AWS::SSM::Parameter`; no active customer-managed bootstrap key remains attributable to P-01.04;
- repair cycle deployment: exactly 1 deployment executed in isolated scratch directory outside canonical repo; reached `READY` in `us-east-1` (Python 3.14, platformVersion `V1`);
- repair cycle remote invocation: exactly 1 data-plane invocation executed via `aws bedrock-agentcore invoke-agent-runtime` using binary payload file `fileb://payload.json` (`{"prompt":"PING"}`) and fresh session ID;
- deterministic acceptance: remote runtime executed custom Python entrypoint and returned HTTP 200 with exact deterministic response `{"result": "AGENTCORE_OK"}`;
- zero model invocations: strictly 0 models or LLMs invoked inside runtime across cycles;
- zero retries: exactly 1 invocation attempt in Cycle 1, exactly 1 invocation attempt in Repair Cycle; strictly zero retries;
- financial safety: cumulative usage-derived gross cost $\approx \$0.00521\text{ USD}$ (including 1.143 hours active customer KMS lifetime @ $1/mo prorated; well below authorized $\$0.10$ limit); actual billed cost / personal-spend delta: `NOT_OBSERVED / UNKNOWN`; the `$0.00` personal-spend target remains in force; actual personal-spend delta was not observed; the retained bootstrap has only a negligible known S3 storage component ($\approx \$0.0000007/\text{month}$); specific promotional-credit offset for that component was not established in this task;
- mandatory teardown: full teardown executed immediately (`agentcore remove all -y` + `agentcore deploy -y -v`); runtime deleted, stack deleted, S3 zip deleted, scratch directory deleted, AWS logout verified;
- sanitization: all raw account IDs, runtime IDs, session IDs, bucket names, and local paths sanitized in public evidence;
- evidence doc: `docs/P01_04_LIVE_AGENTCORE_EVIDENCE.md`;
- friction logged: `F-20260928-02`;
- note: Task closed with independent QA PASS (Verified SHA: `274187c19538e9e9f5f18fe3e2f372a8465cbc91`).

### P-01.05 — Prove Google OAuth and live read-only access to dedicated demo Calendar and Tasks resources
Status: DONE — independent QA PASS (Verified SHA: `191eb2b4451be22bbe2360742a7a4c01a942ecb5`)

Acceptance:
- dedicated demo resources created or identified: YES (disposable secondary Google Calendar `StillDone Demo` and dedicated task list `StillDone Demo` created manually by operator);
- Calendar live read: YES (1 CalendarList discovery call matched target exactly once; 1 events.list read against target calendar executed successfully returning 0 events; zero fallback to primary calendar);
- Tasks live read: YES (1 tasklists.list discovery call matched target exactly once; 1 tasks.list read against target task list executed successfully returning 0 tasks; zero fallback to default task list);
- minimum feasible scopes documented: YES (`calendar.calendarlist.readonly`, `calendar.events.readonly`, `tasks.readonly`; zero write scopes, zero Gmail/Drive/profile scopes);
- no unrelated personal data captured: YES (in-memory filtering only; zero unrelated calendar/task names stored; zero personal emails or tokens committed; resource IDs sanitized as `[REDACTED_CALENDAR_ID]` and `[REDACTED_TASKLIST_ID]`);
- zero mutation & zero retry: 0 writes, 0 retries, 0 billing/paid quota changes, $0.00 personal spend;
- ephemeral credentials cleanup: local `ephemeral_token.json` deleted; remote OAuth grant `NOT_REVOKED`;
- non-blocking operational note: test-user OAuth authorizations can expire after 7 days while the Google Cloud OAuth app remains in Testing mode; final live-demo readiness must account for this;
- provenance: `LIVE_GOOGLE_CALENDAR` and `LIVE_GOOGLE_TASKS`;
- evidence doc: `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`;
- note: Task closed with independent QA PASS (Verified SHA: `191eb2b4451be22bbe2360742a7a4c01a942ecb5`).

### P-01.06 — Execute first live Open-Meteo forecast call and record attribution/limit contract
Status: DONE — independent QA PASS (Verified SHA: `0cfac5a398af574bbb375a5ecf275c8a33fe7861`)

Acceptance:
- live response: YES (HTTP 200 OK from public endpoint `https://api.open-meteo.com/v1/forecast`, latency 429.34ms, generation time 0.294ms, returned timezone `America/Los_Angeles` with valid daily units and 3 forecast dates `2026-09-28` to `2026-09-30`);
- configured public city/location only: YES (fixed public demo coordinates for Seattle, WA `47.6062`, `-122.3321`; zero operator/device geolocation sent; zero personal identifiers or credentials; network-layer metadata like source IP processed according to provider terms);
- no API key: YES (strictly zero authentication, zero API keys, zero accounts or paid subscriptions; $0.00 personal spend);
- provenance: `LIVE_EXTERNAL`;
- data attribution requirement recorded: YES (CC BY 4.0 licence observed; display attribution contract recorded as "Weather data by Open-Meteo.com — CC BY 4.0"; prototype/evaluation feasibility distinguished from future commercial/judging deployment eligibility to be frozen at P-01.08);
- zero mutation & zero retry: exactly 1 forecast query attempt, 0 retries, 0 fallback providers;
- evidence doc: `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`;
- note: Task closed with independent QA PASS (Verified SHA: `0cfac5a398af574bbb375a5ecf275c8a33fe7861`).

### P-01.07 — Validate MCP/Alexa+ current protocol requirements and build a minimal remote Streamable HTTP echo/health proof
Status: DONE — independent QA PASS (Verified SHA: `87232f7f3e8bbff7882bb52691665f100e5ee16a`)

Acceptance:
- current spec requirement re-verified: YES (inspected official Amazon Alexa+ docs, MCP spec, and official TypeScript SDK on 2026-09-29; recorded Streamable HTTP mandatory, legacy SSE deprecated, remote HTTPS mandatory, <500ms MCP server round-trip query response latency threshold, two-tier auth model: Tier 1 service-level client_credentials and Tier 2 user-level authorization_code + PKCE S256 with optional account linking, RFC 9728 Protected Resource Metadata, Amazon explicit unsupported auth mechanisms, select-partner platform availability with operator partner access NOT_ESTABLISHED, and protocol version discrepancies across Amazon documentation);
- remote HTTPS endpoint: YES (ephemeral Cloudflare Quick Tunnel provisioned via official `cloudflared` v2026.9.3 without account, domain purchase, paid plan, or persistent resource; temporary hostname `https://omissions-lessons-nutritional-warren.trycloudflare.com`);
- Streamable HTTP works: YES (ephemeral server implemented strictly outside StillDone repo in isolated scratch dir using official `@modelcontextprotocol/sdk` v1.31.0 in stateless direct-JSON mode `enableJsonResponse: true` over `/mcp`; tested via real official MCP client SDK over public HTTPS);
- protocol/version recorded: YES (negotiated protocol version `2025-11-25`; documented discrepancies with Amazon sample docs citing `2024-11-05`, `2025-03-26`, and `2025-11-25`);
- latency measured: YES (connection/negotiation 339.91ms, tools/list 106.77ms, echo tool call round-trip 61.26ms; satisfies `< 500ms` MCP server round-trip query response latency requirement -> `ALEXA_PLUS_LATENCY_REQUIREMENT = OBSERVED_PASS_FOR_THIS_PROBE`);
- zero product tools: YES (strictly 0 product tools; exactly 1 diagnostic transport-only `echo` tool returning `MCP_OK`);
- zero retries: YES (exactly 1 connection, 1 tools/list, 1 tools/call; 0 retries; 0 fallback transports);
- zero external writes: YES (0 filesystem, 0 shell, 0 AWS, 0 Google, 0 weather, 0 mission runtime calls);
- clean teardown: YES (MCP client closed, Cloudflare tunnel killed, server killed, port 3456 released, scratch dir purged, 0 persistent Cloudflare resources created);
- provenance: `LIVE_REMOTE_MCP` (client provenance: `REAL_MCP_SDK_CLIENT`; Alexa+ actual client integration: `NOT_RUN / NOT_ESTABLISHED`);
- evidence doc: `docs/P01_07_LIVE_REMOTE_MCP_EVIDENCE.md`;
- friction logged: `F-20260929-01`;
- note: Task closed with independent QA PASS (Verified SHA: `87232f7f3e8bbff7882bb52691665f100e5ee16a`).

### P-01.08 — Freeze architecture v1 and issue live feasibility GO/BLOCKED decision
Status: DONE — independent QA PASS (Verified SHA: `41e4ea717b43f558d9d07a7f1775c0780819910f`)

Acceptance:
- exact proven AWS stack selected: YES (Amazon Bedrock foundation model `amazon.nova-micro-v1:0` in `us-east-1` for inference, Strands Agents SDK `1.57.1` with native `BedrockModel` for agent orchestration, Amazon Bedrock AgentCore Runtime serverless CodeZip path for microVM container execution);
- exact rejected/deferred AWS services named: YES (AgentCore Gateway, AgentCore Memory, AWS Lambda, AWS Step Functions, Amazon EventBridge, Amazon SageMaker, Amazon Cognito, Amazon S3 for application state, Bedrock Provisioned Throughput, and AWS Marketplace 3P models all REJECTED_FOR_V1; Amazon DynamoDB and AgentCore Identity DEFERRED; provider-neutral ledger port frozen, with concrete persistence deferred to P-03 as candidate direction only);
- external service set frozen: YES (Google Calendar API v3 and Google Tasks API v1 bound to dedicated disposable `StillDone Demo` resources; Open-Meteo Forecast API under CC BY 4.0 data licence with mandatory display attribution and non-commercial evaluation tier; MCP Streamable HTTP boundary);
- zero-cost path credible through judging: YES (target personal spend strictly $0.00; $150 hackathon promotional credit active; cumulative P-01 usage-derived gross cost estimated at ~$0.00521 USD, well below $0.10 ceiling; actual billed cost and personal-spend delta preserved as `NOT_OBSERVED / UNKNOWN`; retained CDK bootstrap customer KMS key remediated to `PendingDeletion` with $0 ongoing storage fee; Google, Open-Meteo, and Cloudflare courtesy/free paths used; verdict: `ZERO_PERSONAL_SPEND_PATH = CREDIBLE_THROUGH_JUDGING` as an architectural feasibility determination, not proof of $0.00 actual delta);
- Alexa+ actual access remains optional unless proven: YES (Alexa+ partner client access honestly classified as `NOT_ESTABLISHED`; simulated Alexa+ client surface visibly labeled as alternate qualifying surface exempt from runtime hook; downstream mandatory requirement for canonical repo runtime MCP execution recorded);
- no mocked substitute can produce GO: YES (all required legs proven live on real systems; zero mock substitutes used to award GO);
- broad P-Ω audit completed: YES (comprehensive Phase P-01 closure audit completed, including surgical repair of 3 documentation-parity findings; zero phase-blocking defects remain; `docs/P_OMEGA_AUDIT_REPORT.md` updated);
- phase gate decision: **`DONE — LIVE FEASIBILITY GO — independent QA PASS`**;
- phase exit: Phase P-01 is complete and closed with independent QA PASS (Verified SHA: `41e4ea717b43f558d9d07a7f1775c0780819910f`). Phase P-02 is authorized to start.
- next exact task: `P-02.01 — Define mission identity, immutable mission contract, and user-intent snapshot`.

---

# P-02 — Provider-Neutral Mission & Desired-State Contracts

Goal:
encode truth semantics before orchestration.

### P-02.01 — Define mission identity, immutable mission contract, and user-intent snapshot
Status: DONE — independent QA PASS (Verified commit: `23ac89cb9abac7eec75bdcfcaa159335784e3c28`)

Acceptance:
- mission identity: opaque UUID-backed `MissionId` generated by deterministic runtime code; invalid formats and non-UUIDs rejected;
- user intent snapshot: immutable `UserIntentSnapshot` retaining exact user text verbatim; blank/whitespace rejected; timezone-aware UTC normalized;
- mission contract: immutable `MissionContract` binding mission identity, intent snapshot, creation timestamp, and schema version;
- immutability: all objects frozen;
- provider purity: zero AWS/Google/MCP/UI/network dependencies imported;
- focused unit tests: `tests/domain/test_mission.py` passing.

### P-02.02 — Define desired-state predicate schema, required/optional semantics, and freshness contract
Status: DONE — independent QA PASS (Verified commit: `ae88027e8c225c00ed692daf4afda7daaa7a17fe`)

Acceptance:
- desired-state predicate: typed immutable `DesiredStatePredicate` with `PredicateId`, `MissionId`, subject, operator, scalar JSON-like expected value, required flag, and freshness contract;
- bounded operator vocabulary: `PredicateOperator` (`==`, `!=`, `exists`, `does_not_exist`, `<`, `<=`, `>`, `>=`); arbitrary code/expressions/eval rejected;
- freshness contract: `FreshnessContract` supporting `CURRENT` and bounded positive `MAX_AGE` (seconds); contradictory, zero, and negative values rejected;
- required/optional semantics: explicit boolean contract defined without calculating READY;
- immutability: all objects frozen;
- provider purity: zero external SDK or provider imports;
- focused unit tests: `tests/domain/test_desired_state.py` passing.

### P-02.03 — Define action contract, supported action vocabulary, target identity, and parameter normalization
Status: DONE — independent QA PASS (Verified commit: `268c991c2e2a0b2d8e3937ee575ad24330bbd241`)

Acceptance:
- supported action vocabulary: finite `ActionType` covering exactly 5 required capabilities (`calendar.read`, `calendar.update`, `task.read`, `task.create`, `weather.read`); arbitrary shell, HTTP, filesystem, delete, and model actions forbidden;
- target identity: immutable `TargetIdentity` distinguishing system namespace, `ResourceKind` (`calendar_event`, `task_list`, `task`, `weather_location`), resource ID, and optional parent ID;
- creation targeting: creation binds to parent container target without fabricating child ID;
- parameter normalization: self-validating immutable `NormalizedParameters` enforcing post-init invariants on all construction paths (direct constructor and `from_dict`); validates string keys before sorting; duplicate, blank, non-string keys rejected; non-scalar, nested, and non-finite numeric values (NaN/Inf) fail closed; unsorted direct construction canonicalized to deterministic lexicographical order matching `from_dict`;
- action contract: immutable `ActionContract` binding runtime `ActionId`, `MissionId`, `ActionType`, `TargetIdentity`, and `NormalizedParameters`; malformed parameters cannot be smuggled via any path;
- execution/authority boundary: zero execution, zero authority classification, zero approval object creation;
- immutability: all objects frozen;
- provider purity: zero external SDK or provider imports;
- focused unit tests: `tests/domain/test_action.py` passing.

### P-02.04 — Define mission lifecycle and step evidence states
Status: DONE — independent QA PASS (Verified commit: `268c991c2e2a0b2d8e3937ee575ad24330bbd241`)

Acceptance:
- mission lifecycle vocabulary: exact 10 states (`DRAFT`, `PLANNED`, `EXECUTING`, `NEEDS_APPROVAL`, `VERIFYING`, `READY`, `PARTIAL`, `FAILED`, `DRIFTED`, `CANCELLED`);
- step evidence vocabulary: exact 7 states (`NOT_RUN`, `EXECUTED_UNVERIFIED`, `VERIFIED`, `CONTRADICTED`, `BLOCKED`, `FAILED`, `STALE`);
- StillDone invariants enforced: `NOT_RUN` is not `PASS`; execute success alone yields at most `EXECUTED_UNVERIFIED`; `VERIFIED` requires independent read-back; `CONTRADICTED` and `BLOCKED` are distinct from `FAILED`; `STALE` captures expired freshness; `READY` is renewable; `DRIFTED` captures reality divergence;
- boundary protection: declarative transition metadata only (`DECLARATIVE_MISSION_TRANSITIONS`); runtime transition guard engine strictly deferred to P-03.03; zero mutating/transition methods implemented;
- provider purity: zero external SDK or provider imports;
- focused unit tests: `tests/domain/test_lifecycle.py` passing.

### P-02.05 — Define authority classes, approval object, binding hash, and expiry semantics
Status: DONE — independent QA PASS (Verified SHA: `e2dd124fda1af627949835c0d438861c43cf5226`)

Acceptance:
- exact authority classes: exactly five canonical classes (`READ_ONLY`, `REVERSIBLE_AUTO`, `REVERSIBLE_APPROVAL_REQUIRED`, `EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED`, `IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED`); pure contract metadata `requires_human_approval` defined; dynamic classification deferred;
- approval identity: opaque UUID-backed `ApprovalId` generated deterministically by runtime code;
- approval contract: immutable `ApprovalGrant` binding `approval_id`, `mission_id`, `action_id`, `authority_class`, `issued_at`, `expires_at`, and `binding_hash`; free-form chat strings rejected;
- binding hash: domain-separated SHA-256 digest (`stilldone:approval-binding:v1`) binding mission ID, action ID, action type, normalized parameters, complete target identity, authority class, issued_at, and expires_at; canonical 64 lowercase hex `BindingHash` value type;
- expiry semantics: pure deterministic `is_expired(at)` check; timezone-aware UTC normalized; boundary equality counts as expired;
- execution/authority boundary: zero execution, zero authority classification, zero approval verification engine;
- immutability: all objects frozen;
- provider purity: zero external SDK or provider imports;
- focused unit tests: `tests/domain/test_authority.py` passing.

### P-02.06 — Define idempotency, retry, attempt, resource, and reconciliation contracts
Status: DONE — independent QA PASS (Verified commit: `bc8e7c6e66667803fc6d10fef6e6460b803c3777`)

Acceptance:
- idempotency contract: runtime-owned opaque UUID-backed `IdempotencyKey`; valid UUIDs accepted, malformed strings and non-UUID types rejected; generated once per mutation lineage; retries reuse the same key;
- retry safety contract: bounded `RetryPolicy` distinguishing `NO_RETRY`, `IDEMPOTENT_RETRY`, and `READ_BEFORE_RETRY`; lost/unknown provider response cannot justify blind retry; `max_attempts` strictly bounded by `MAX_RETRY_ATTEMPTS_CEILING` (5); `NO_RETRY` strictly requires `max_attempts == 1`;
- attempt contract: immutable 1-based `ExecutionAttempt` binding `ActionId`, `IdempotencyKey`, `AttemptId`, `attempt_number` >= 1, and UTC-normalized `started_at`; 0 and negative attempt numbers rejected; execution result and evidence remain separate;
- resource binding contract: immutable `ResourceBinding` preserving `TargetIdentity` vocabulary; distinguishes requested/parent target from concrete resolved resource identity; creation actions can exist with `resolved_target=None` without fabricating IDs; parent container cannot masquerade as resolved child resource;
- reconciliation request contract: immutable `ReconciliationRequest` binding `MissionId`, `ReconciliationReason` (`POST_EXECUTION_VERIFY`, `EXPLICIT_USER_CHECK`, `FRESHNESS_REFRESH`), UTC-normalized `requested_at`, and `PredicateScope` (all-required or non-empty unique selective); request contract only (zero provider reads, predicate evaluation, or mission state mutations);
- immutability: all dataclasses frozen;
- provider purity: zero external SDK or provider imports;
- focused unit tests: `tests/domain/test_execution.py` passing.


### P-02.07 — Define evidence provenance and live/recorded/fixture separation
Status: DONE — independent QA PASS (Verified commit: `380c63f1a46979ecef54187117ac0b843cbd5c24`)

Acceptance:
- exact six-value provenance vocabulary: `FIXTURE`, `LOCAL_EXECUTION`, `LIVE_AWS`, `LIVE_GOOGLE`, `LIVE_EXTERNAL`, `RECORDED_LIVE` frozen strictly as defined by `AGENTS.md` and `docs/EVIDENCE_AND_STATE_CONTRACT.md`;
- live/recorded/fixture separation: `FIXTURE` is non-live; `LOCAL_EXECUTION` is local-only; `LIVE_AWS`, `LIVE_GOOGLE`, and `LIVE_EXTERNAL` represent fresh current-live external provenance; `RECORDED_LIVE` represents historical capture and never classifies as current-live;
- recorded-live lineage contract: immutable `EvidenceOrigin` (`EvidenceProvenanceContract`) requiring `recorded_live_origin` drawn strictly from `{LIVE_AWS, LIVE_GOOGLE, LIVE_EXTERNAL}`; `FIXTURE`, `LOCAL_EXECUTION`, and `RECORDED_LIVE` cannot masquerade as recorded-live origin; non-`RECORDED_LIVE` provenance forbidden from carrying recorded-live origin metadata;
- provenance is not result: zero automatic promotion to `VERIFIED`, `READY`, or `PASS`; provenance answers WHERE/HOW evidence originated;
- timestamp contract: timezone-aware UTC normalized; naive timestamps rejected;
- immutability: dataclasses frozen;
- provider purity: zero external SDK or provider imports;
- focused unit tests: `tests/domain/test_provenance.py` passing.

### P-02.08 — Add serialization, schema, forbidden-transition, and provider-purity tests
Status: DONE — independent QA PASS (Verified commit: `293ec637464294a6caaca8cffcd85dd666890f61`)

Acceptance:
- serialization and lossless schema projection: test-local projection helpers prove stable lossless JSON projection across `MissionContract`, `DesiredStatePredicate`, `ActionContract`, `ApprovalGrant`, `ExecutionAttempt`, `RetryPolicy`, `ResourceBinding`, `ReconciliationRequest`, and `EvidenceOrigin`; canonical strings for IDs, exact canonical enum strings, UTC ISO timestamps, and normalized parameter sorting verified; zero generic evidence hashing or ledger serialization introduced;
- schema stability tests: exact vocabularies and cardinalities frozen across all 10 domain enums (`MissionState` [10], `StepEvidenceState` [7], `PredicateOperator` [8], `FreshnessMode` [2], `ActionType` [5], `ResourceKind` [4], `AuthorityClass` [5], `RetryStrategy` [3], `ReconciliationReason` [3], `EvidenceProvenance` [6]); public exports in `stilldone.domain` verified;
- forbidden-transition tests: verified declarative lifecycle metadata (`DRAFT`/`PLANNED`/`EXECUTING`/`NEEDS_APPROVAL`/`PARTIAL`/`FAILED` -> `READY` all forbidden; `READY` entered strictly from `VERIFYING`; `READY` -> `DRIFTED` permitted; `EXECUTING` cannot bypass `VERIFYING`); zero runtime transition guards implemented;
- static provider-purity AST inspection: AST walk across all domain Python source files proves strictly zero imports of provider SDKs (`boto3`, `botocore`, `strands`, `agentcore`, `google`, `googleapiclient`, `mcp`, `requests`, `httpx`, `urllib3`, `aiohttp`, `flask`, `fastapi`, `sqlite3`, `sqlalchemy`, `tkinter`);
- future-leakage assertions: verified zero persistence, zero SQLite, zero `open()` file calls, zero generic evidence ledger/hashing, zero runtime transition engine, zero model/LLM invocation, and zero live/fixture fallback;
- recursive domain inspection: repair commit `293ec637464294a6caaca8cffcd85dd666890f61` canonicalized recursive `rglob("*.py")` inspection across `src/stilldone/domain/**/*.py` with regression protection against nested module bypasses (`test_domain_source_enumeration_includes_nested_modules`, `test_nested_module_forbidden_import_detected`);
- focused unit tests: `tests/domain/test_phase_p02_contracts.py` passing (120 total tests in suite passing);
- phase exit: Phase P-02 is complete and closed with independent QA PASS (Verified SHA: `293ec637464294a6caaca8cffcd85dd666890f61`). (Historically, at Phase P-02 closure exit, Phase P-03 was `PENDING / NOT_STARTED / NOT AUTHORIZED`; Phase P-03 is now closed).

Phase exit:
core domain imports no AWS/Google/MCP UI SDK objects; Phase P-02 closed with independent QA PASS.


---

# P-03 — Deterministic Evidence Ledger & Fact Authority

Goal:
make evidence immutable enough to reason about honestly.

### P-03.01 — Implement canonical serialization and SHA-256 content-addressed evidence IDs
Status: DONE — independent QA PASS (Verified SHA: `766a42cfe5f9bd93386198c8b21878296da5402a`)

Acceptance:
- canonical serialization: deterministic JSON primitive projection (`to_canonical_primitive`, `canonical_json`, `canonical_serialize`), sorted dictionary keys, NFC-normalized unicode with fail-closed collision detection for post-NFC duplicate canonical keys, UTC-normalized timestamps, canonical enum values and ID wrapper projection; non-finite floats, naive datetimes, and unsupported types fail closed;
- evidence identity: strongly typed immutable `EvidenceId` backed by 64 lowercase hexadecimal SHA-256 digest;
- content-addressed hashing: `compute_evidence_id` with explicit domain separation/versioning (`stilldone:evidence:v1`); identical content yields identical EvidenceId; changed content yields distinct EvidenceId;
- provenance/result separation: provenance records origin only, zero implicit promotion to `VERIFIED`, `READY`, or `PASS`;
- focused tests: `tests/test_serialization.py` and `tests/test_evidence.py` passing (155 total tests passing in suite).

### P-03.02 — Implement append-only mission/action/evidence ledger interfaces
Status: DONE — independent QA PASS (Verified SHA: `8cf48527eacc69d45a378e85ce5bcf1bff0bcfa0`)

Acceptance:
- typed ledger records: immutable `MissionRecord`, `ActionRecord`, and `EvidenceRecord` with strict relationship integrity (`mission -> action -> evidence`);
- payload immutability & defensive isolation: `EvidenceRecord` owns an immutable canonical snapshot of its payload (`CanonicalPayload`, `CanonicalSequence`) preventing mutation via caller input dicts, nested dicts/lists, or retrieved ledger objects;
- content-addressed EvidenceId binding: `EvidenceRecord` strictly binds and validates exact `EvidenceId` matching canonical content-addressed hash across freezing and retrieval;
- append-only semantics: silent overwriting prohibited; identical replay raises explicit `DuplicateRecordError`; conflicting same-identity/different-content attempts fail closed with `RecordConflictError`;
- provider-neutral interface: `MissionLedgerPort` abstract port defined; zero SQLite, zero filesystem persistence, zero DynamoDB, zero AWS/Google/MCP imports;
- non-durable classification: `InMemoryNonDurableLedger` explicitly classified as `IS_DURABLE = False`, `DURABILITY_CLASSIFICATION = "NON_DURABLE_TEST_OR_RUNTIME_LOCAL"`;
- focused tests: `tests/test_ledger.py` passing (161 total tests passing in suite).

### P-03.03 — Implement deterministic state-transition guards
Status: DONE — independent QA PASS (Verified SHA: `2079f28d291922f0d4aa6525aa2989f42b3da610`)

Acceptance:
- runtime transition guard engine: `MissionTransitionGuard`, `assert_valid_transition`, `assert_can_promote_to_ready`, and `is_transition_allowed` using canonical `MissionState` and `DECLARATIVE_MISSION_TRANSITIONS`;
- critical transition laws enforced: direct transitions from `DRAFT`, `PLANNED`, `EXECUTING`, `NEEDS_APPROVAL`, `PARTIAL`, `FAILED`, and `CANCELLED` to `READY` strictly fail closed with `IllegalStatePromotionError`; `READY` may strictly be entered only from `VERIFYING`; `READY -> DRIFTED` permitted;
- evidence-based READY promotion: executor/tool success alone (`EXECUTED_UNVERIFIED`) cannot promote to `READY`; `NOT_RUN` cannot be interpreted as `PASS`/`VERIFIED`; `CONTRADICTED`, `BLOCKED`, `FAILED`, and `STALE` prevent promotion to `READY`; all steps must be `VERIFIED`;
- fail-closed validation: malformed or unsupported state values fail closed;
- focused tests: `tests/test_transitions.py` passing (152 total tests passing in suite).

### P-03.04 — Implement bounded sanitized provider-output capture with digests
Status: DONE — independent QA PASS (Verified SHA: `69715d57cc6f2289540974bc1b3ac91d013348b6`)

Acceptance:
- bounded structural sanitization: detached canonical JSON-compatible primitives (`CanonicalPayload`, `CanonicalSequence`), no arbitrary provider objects, no object reprs, no memory addresses;
- explicit deterministic bounds: `CaptureBounds` enforcing `max_depth` (16), `max_mapping_entries` (256), `max_sequence_items` (256), `max_string_length` (4096), `max_total_bytes` (65536);
- truncation and fail-closed policies: violations fail closed under `fail_closed=True` or `max_total_bytes`; otherwise produce explicit, deterministic truncation metadata (`is_truncated=True`, sorted `truncation_reasons`);
- content digest: strongly typed `CaptureDigest` backed by SHA-256 with domain separation `stilldone:provider-capture:v1` binding payload, truncation status, truncation reasons, and bounds;
- evidence separation: digest does not assert or imply `VERIFIED`, `READY`, or `PASS`;
- focused tests: `tests/test_capture.py` passing (177 total tests passing in suite).

### P-03.05 — Bind receipt projections to exact mission/evidence hashes
Status: DONE — independent QA PASS (Verified Baseline SHA: `46e55b424eb999c666932871b5b5517397b85db6`)

Acceptance:
- typed immutable receipt projection: `ReceiptProjection` binding exact mission snapshot, canonically ordered evidence IDs, projection state, UTC timestamp, and deterministic receipt hash;
- dedicated mission content hash: `MissionContentHash` backed by SHA-256 with domain separation `stilldone:mission-content:v1`, strictly bound to `mission_id` to prove identity attribution across all construction paths (`create`, direct `__post_init__`, `from_records`, `compute_receipt_hash`); mismatched identity fails closed immediately with `ReceiptMismatchError`;
- detached immutable receipt metadata: receipt metadata frozen as `CanonicalPayload` via `freeze_canonical_payload`, preventing post-construction mutation and caller alias leakage; `to_canonical()` and `to_dict()` return detached mutable copies; post-NFC duplicate collisions fail closed;
- exact ordered evidence binding: immutable tuple of unique `EvidenceId` instances sorted lexicographically; duplicate or unsorted bindings fail closed (`DuplicateEvidenceBindingError`, `EvidenceOrderError`);
- deterministic receipt hash: `ReceiptHash` backed by SHA-256 with domain separation `stilldone:receipt-projection:v1`; same projection yields identical hash; material changes yield distinct hashes;
- integrity and mismatch guards: fail closed on malformed hashes, evidence belonging to mismatched missions (`ReceiptMismatchError`), or altered hashes (`ReceiptHashMismatchError`);
- truth boundaries respected: receipt is explicitly historical (`is_historical=True`), does not claim current-live truth or independent read-back, and cannot promote to READY;
- focused tests: `tests/test_receipt.py` passing (190 total tests passing in suite).

### P-03.06 — Add tamper, mismatch, replay, stale, and forbidden-promotion tests
Status: DONE — independent QA PASS (Verified Baseline SHA: `46e55b424eb999c666932871b5b5517397b85db6`)

Acceptance:
- TAMPER tests: verified fail-closed detection of altered evidence content vs EvidenceId, mutated receipt mission hash, altered evidence binding, altered provider-output capture vs digest, caller alias mutation isolation, nested caller mutation isolation, and direct metadata mutation prevention (`TypeError`);
- MISMATCH tests: verified fail-closed rejection of evidence bound to mismatched missions (`ReceiptMismatchError`), actions bound to missing missions in ledger (`RecordNotFoundError`), mission identity vs content hash mismatch across all construction paths, and evidence list vs projection hash mismatch;
- REPLAY tests: verified append-only ledger rejection of duplicate appends (`DuplicateRecordError`) and conflicting same-identity records (`RecordConflictError`), and proved historical receipts cannot silently overwrite current state;
- STALE tests: proved STALE step evidence strictly prevents promotion to READY (`IllegalStatePromotionError`), historical receipts and RECORDED_LIVE evidence cannot masquerade as current-live truth, and freshness semantics remain separate from evidence existence;
- FORBIDDEN PROMOTION tests: proved NOT_RUN, EXECUTED_UNVERIFIED, provider capture alone, receipt existence alone, and invalidating evidence states (CONTRADICTED, BLOCKED, FAILED) cannot promote to READY, and verified direct illegal transitions from non-VERIFYING states fail closed;
- Unicode & canonicalization hardening: preserved fail-closed behavior for Unicode NFC collisions, non-finite floats, naive datetimes, and unsupported types;
- Evidence payload isolation & append-only: preserved deep payload freezing and caller isolation across evidence records and receipt projections;
- focused tests: `tests/test_phase_p03_adversarial.py` passing (218 total tests passing in suite).

Phase exit:
local deterministic evidence primitives are green but do not claim live integration. Phase P-03 is CLOSED with independent QA PASS (Verified Baseline SHA: `46e55b424eb999c666932871b5b5517397b85db6`). (Historically, at the P-03 implementation exit before the P-03 phase-boundary P-Ω closure, Phase P-04 was `PENDING / NOT_STARTED / NOT AUTHORIZED`; Phase P-04 is currently `CLOSURE CANDIDATE — awaiting independent QA review`).

---

# P-04 — Security, Privacy & Authority Foundation

Goal:
make future live actions bounded by design.

### P-04.01 — Implement secret/config loading and fail-closed validation
Status: DONE — independent QA PASS (Verified SHA: `933b5364e69c8804dc448c9b0c84e02877d8446d`)

Acceptance:
- explicit injection & call-time process environment: config loader accepts explicit mapping or process environment at call time; strictly zero environment reads at module import time; no implicit .env loading; no python-dotenv dependency;
- owned namespace protection: declared fields checked; unrecognized keys in owned namespace (`STILLDONE_`) fail closed with `UnknownConfigurationKeyError` (typo prevention); unrelated system environment variables ignored;
- fail-closed validation: required fields fail closed when absent (`MissingConfigurationError`), empty string, whitespace-only, or malformed for declared type/validator (`InvalidConfigurationValueError`);
- optional values & defaults: defaults are explicit in code, non-secret, and deterministic; optional values with malformed/empty input fail closed;
- secret value handling: `SecretString` protects sensitive values; plaintext shielded from `repr()`, `str()`, format strings, dataclass reprs, and validation error messages; narrow explicit access via `get_secret_value()` / `reveal()`; direct string equality comparison forbidden (`TypeError`); constant-time equality with `SecretString`;
- snapshot & alias safety: `LoadedConfig` represents an immutable snapshot completely isolated from caller environment mutations; dataclass instantiation supported via `load_dataclass`;
- zero provider credentials required: static AWS IAM keys and Google OAuth secrets strictly excluded from schema;
- focused unit tests: `tests/test_config.py` passing (272 total tests passing in suite).

### P-04.02 — Implement log/evidence redaction for tokens, OAuth material, emails, and sensitive identifiers
Status: DONE — independent QA PASS (Verified SHA: `4125da1357ed38483941216aae1a3182afadf404`)

Acceptance:
- deterministic provider-neutral redaction boundary: `src/stilldone/redaction.py` implementing `redact`, `redact_with_metadata`, `redact_text`, and `redact_log_message`;
- semantic redaction markers: `[REDACTED_SECRET]`, `[REDACTED_EMAIL]`, `[REDACTED_IDENTIFIER]`;
- normalized sensitive mapping keys: robust matching for snake_case, kebab-case, camelCase, PascalCase, and UPPERCASE across tokens, client secrets, passwords, credentials, API keys, and AWS credential material;
- SecretString safety: values directly replaced with `[REDACTED_SECRET]` without ever calling `get_secret_value()` or `reveal()`;
- email address redaction: bounded regex pattern detecting standalone or embedded emails;
- OAuth material sanitization: callback URLs with query or fragment `code`, `state`, `token` sanitized while preserving scheme, host, path, and non-sensitive parameters;
- sensitive external identifiers: explicit key policy (`account_id`, `calendar_id`, `task_list_id`, `session_id`, `external_resource_id`) and AWS access key IDs (`AKIA...`, `ASIA...`) redacted while preserving StillDone domain identifiers (`MissionId`, `ActionId`, `EvidenceId`);
- detached/idempotent transformation: caller input is never mutated; result is deeply isolated; `redact(redact(x)) == redact(x)`;
- P-03.04 capture boundary integration: raw provider output is redacted before structural sanitization, bounds checking, and digest computation in `capture_provider_output`; stored payload contains only redacted representation; digest describes stored redacted payload;
- fail-closed & error safety: unsupported objects fail closed with `UnsupportedRedactionTypeError` without leaking repr() or memory addresses; zero secret plaintext echoed in error messages;
- focused tests: `tests/test_redaction.py` passing (77 redaction tests, 16 capture tests, 54 config tests; 349 total tests passing in suite at final verified closure SHA `4125da1357ed38483941216aae1a3182afadf404`).

### P-04.03 — Implement supported-action allowlist and parameter validation
Status: DONE — independent QA PASS (Verified SHA: `63c5e2792967edd37e93b6583663395824b7e688`)

Acceptance:
- closed-world action policy: `src/stilldone/action_policy.py` implementing immutable `ACTION_POLICIES` mapping exactly 5 canonical `ActionType` members to `ActionPolicy`; zero dynamic/plugin/model-defined actions; missing/extra entries fail closed;
- target system & ResourceKind compatibility: calendar.read -> google_calendar / CALENDAR_EVENT; calendar.update -> google_calendar / CALENDAR_EVENT; task.read -> google_tasks / TASK; task.create -> google_tasks / TASK_LIST; weather.read -> open_meteo / WEATHER_LOCATION; mismatched system or ResourceKind fails closed with `ActionTargetCompatibilityError`;
- closed-world parameter schemas: calendar.read, task.read, weather.read reject all parameters; calendar.update requires at least 1 supported parameter from {summary, start_time, all_day}; task.create requires title: str and accepts optional due: str; unknown/misspelled/alias parameters fail closed with `UnknownParameterError`;
- strict type safety & deterministic bounds: all_day accepts bool only (no int/str coercions); strings non-empty and non-whitespace; internal security bound `MAX_PARAM_STRING_LENGTH = 1024`; oversized values fail closed with `OversizedParameterError`;
- secret/error safety: validation errors identify key, rule, type, and target, never echoing sensitive parameter plaintext values;
- bypass resistance: `ValidatedActionContract` is self-validating on construction; direct `ActionContract` construction undergoes identical validation;
- purity & authority boundary: pure validation only; zero provider/network imports; zero authority classification (`AuthorityClass`), approval grants (`ApprovalGrant`), or execution side effects;
- focused unit tests: `tests/test_action_policy.py` passing (98 focused action-policy tests, 447 total tests in suite passing).

### P-04.04 — Implement authority classification and approval-binding verification
Status: independent QA PASS (Verified SHA: `2b24b4826009a8d9155616c90355185c3f19062e`)

Acceptance:
- precondition & bypass resistance: authority classification accepts only P-04.03 `ValidatedActionContract`; raw `ActionContract` or unvalidated objects fail closed (`AuthorityPolicyTypeError`);
- closed-world classification: `src/stilldone/authority_policy.py` implementing immutable `ACTION_AUTHORITY_TABLE` mapping all 5 canonical `ActionType` members: calendar.read -> READ_ONLY, task.read -> READ_ONLY, weather.read -> READ_ONLY, task.create -> REVERSIBLE_AUTO, calendar.update -> REVERSIBLE_APPROVAL_REQUIRED; missing/extra entries fail closed;
- deterministic authority decision semantics: immutable `AuthorityDecision` model with 4 canonical statuses: `AUTHORIZED_NO_APPROVAL_REQUIRED`, `AUTHORIZED_BY_BOUND_APPROVAL`, `APPROVAL_REQUIRED`, `BLOCKED`; preserves action ID, mission ID, action type, evaluation timestamp, approval ID, and structured `RejectionReason`;
- no-approval actions: `READ_ONLY` and `REVERSIBLE_AUTO` succeed with `approval=None`; unexpected approval grants fail closed (`UnexpectedApprovalGrantError` / `UNEXPECTED_APPROVAL_GRANT`);
- approval-required actions: `calendar.update` requires exact cryptographically bound `ApprovalGrant`; missing approval yields `APPROVAL_REQUIRED`;
- exact cryptographic binding verification: `verify_approval_grant` strictly verifies candidate action against grant action, mission ID, action ID, action type, parameters, and complete `TargetIdentity`; recomputes `compute_approval_binding_hash` and verifies with constant-time equality (`hmac.compare_digest`);
- validity window enforcement: strict evaluation against explicit timezone-aware observation timestamp `at` (`issued_at <= at < expires_at`); naive datetimes fail closed (`AuthorityPolicyValueError`); boundary `at == expires_at` is expired; boundary `at == issued_at` is valid;
- wrong/stale/tampered approval law: wrong mission, wrong action ID, changed parameters, changed target resource/parent, wrong action type, wrong authority class, altered binding hash, expired, or future grants fail closed; string "yes" and arbitrary model prose rejected with `InvalidApprovalTypeError`;
- policy law: `IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED` is never auto-authorized even with an ApprovalGrant; `EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED` requires exact bound approval;
- replay & purity boundaries: static binding/validity verification only; does not claim single-use durable consumption; pure verification creating zero execution attempts, zero ledger mutations, and zero state promotions;
- error secrecy: sensitive action parameter plaintext and external target identifiers (resource_id, parent_id) are never echoed in error messages or decision reasons; safe structural facts only are reported; `repr(ApprovalGrant)` is not dumped;
- focused unit tests: `tests/test_authority_policy.py` passing (44 focused authority-policy tests, 491 total tests in suite passing).

### P-04.05 — Implement demo-resource isolation checks
Status: DONE — independent QA PASS (Verified SHA: `95aa53aece4c16792e6fc33f916133bab02bd78d`)

Acceptance:
- precondition & bypass resistance: isolation checks accept only P-04.03 `ValidatedActionContract`; raw `ActionContract` or unvalidated objects fail closed (`DemoIsolationTypeError`);
- closed-world explicit scope: `src/stilldone/demo_isolation.py` implementing immutable `DemoResourceScope` with required non-empty `calendar_id` and `task_list_id`; whitespace-only or non-string IDs fail closed (`DemoScopeValueError`, `DemoScopeTypeError`); no implicit environment reads or global mutable state;
- sensitive identifier safety: `DemoResourceScope` masks IDs in `str()` and `repr()` (`***`); exception messages and result representations never echo configured or candidate external IDs;
- exact match law: case-sensitive exact string comparison for external IDs; prefixes, suffixes, substrings, and whitespace trimming fail closed;
- calendar actions isolation: `calendar.read` and `calendar.update` require non-null `target.parent_id` matching `scope.calendar_id`; missing `parent_id` fails (`MissingParentContainerError`); mismatch fails (`CalendarOutOfScopeError`); varying `resource_id` allowed within demo calendar;
- task actions isolation: `task.read` requires non-null `target.parent_id` matching `scope.task_list_id` (`TaskOutOfScopeError`); `task.create` targets container directly with `target.resource_id` matching `scope.task_list_id` and requires `target.parent_id` to be None (`UnexpectedParentContainerError`);
- weather non-Google action: `weather.read` returns explicit `NOT_APPLICABLE` status (`DemoIsolationStatus.NOT_APPLICABLE`);
- static-vs-live truth & authority boundary: pure static target-scope validation; zero Google API calls; zero provider/network imports; confers zero authority, creates zero approvals, and cannot produce `VERIFIED` or `READY` state;
- focused unit tests: `tests/test_demo_isolation.py` passing (35 focused isolation tests, 526 total tests in suite passing).

### P-04.06 — Implement public-endpoint rate/budget protection contract
Status: DONE — independent QA PASS (Verified SHA: `a44955595aabaf7f34daecc35100bb72b5120095`)

Acceptance:
- deterministic provider-neutral rate and budget protection: `src/stilldone/endpoint_protection.py` implementing immutable `EndpointProtectionPolicy`, `RateSnapshot`, `BudgetSnapshot`, `EndpointRequestAssessment`, `EndpointAdmissionDecision`, and pure `evaluate_endpoint_admission`;
- request exposure classes: minimal closed enum `RequestExposureClass` (`NO_PAID_CAPABILITY`, `PAID_CAPABLE_LIVE`); `NO_PAID_CAPABILITY` passes general rate limit without requiring budget snapshot and does not consume paid-live allowance;
- explicit operator live gate: `policy.live_paid_path_enabled: bool` defaults to `False` (no implicit True); disabled gate fails closed (`LIVE_PATH_DISABLED`);
- caller exposure classes: closed enum `CallerClass` (`PUBLIC_UNTRUSTED`, `OPERATOR_CONTROLLED`); `PAID_CAPABLE_LIVE` + `PUBLIC_UNTRUSTED` fails closed (`PUBLIC_PAID_PATH_FORBIDDEN`);
- finite rate limits & fail-closed window: exact positive integer limits; bool rejected; snapshot window `window_start <= at < window_end` enforced; boundary `at == window_start` valid, `at == window_end` fails closed (`RATE_SNAPSHOT_INVALID_OR_STALE`); general rate ceiling (`RATE_LIMIT_EXCEEDED`) and paid-live rate ceiling (`PAID_LIVE_RATE_LIMIT_EXCEEDED`) enforced with zero off-by-one errors;
- exact budget policy & credit freshness: exact `Decimal` arithmetic; floats, NaNs, infinities, and string coercions rejected; required conservative gross estimate for `PAID_CAPABLE_LIVE` (> 0, finite); snapshot freshness `observed_at <= at < valid_until` (`BUDGET_TRUTH_STALE`); unconfirmed credit coverage denied (`CREDIT_COVERAGE_UNCONFIRMED`); usage + estimate > ceiling denied (`INTERNAL_BUDGET_EXCEEDED`); estimate > remaining credit denied (`INSUFFICIENT_OBSERVED_CREDIT`); exact internal budget boundary admitted;
- zero-personal-spend truth boundary: `ALLOW` decision certifies deterministic contract compliance with fresh supplied facts; does not claim billing proof, personal spend proof, or AWS hard cap;
- rate-limit persistence boundary: pure evaluator evaluates snapshot; does not claim atomic quota consumption or concurrency safety (deferred to P-05.05 / deployment layer);
- separation of concerns: admission decision contains zero authority classes (`AuthorityClass`), approval grants (`ApprovalGrant`), execution attempts (`ExecutionAttempt`), ledger mutations, or mission state promotions (`VERIFIED`, `READY`);
- fail-closed decision model: `EndpointAdmissionDecision` enforces post-init self-validation for canonical enum types, timezone-aware datetime, positive finite Decimal cost estimates, `NO_PAID_CAPABILITY` estimate absence, `ALLOW`/`ALLOWED` consistency, and `OPERATOR_CONTROLLED`/non-None estimate for `PAID_CAPABLE_LIVE` `ALLOW` decisions;
- purity: zero network, zero provider SDK imports, zero environment reads, zero wall-clock reads (`datetime.now`);
- focused unit tests: `tests/test_endpoint_protection.py` passing (65 focused tests, 591 total tests in suite passing).

### P-04.07 — Run focused security/threat-model P-Ω audit
Status: DONE — independent QA PASS (Verified closure SHA: `3dbde03de5993a163f019a7867401d9f88310fdc`)

Acceptance:
- 16-dimension security/threat-model audit executed and documented in `docs/P04_SECURITY_THREAT_MODEL_AUDIT.md`;
- historical Phase P-03 audit preserved (`docs/P_OMEGA_AUDIT_REPORT.md` untouched);
- cross-boundary integration security test suite created: `tests/test_phase_p04_security_audit.py` (40 focused tests, 631 total tests in suite passing);
- verified exact canonical action vocabulary (5 actions: `calendar.read`, `calendar.update`, `task.read`, `task.create`, `weather.read`);
- verified exact authority classifications (`READ_ONLY`, `REVERSIBLE_AUTO`, `REVERSIBLE_APPROVAL_REQUIRED`);
- verified zero individual P-04 gate results produce or expose `VERIFIED` or `READY` states;
- verified AST inspection confirms zero forbidden provider SDK imports (`boto3`, `google`, `mcp`, etc.) across all 7 P-04 modules;
- verified zero provider execution capabilities across all 7 P-04 modules;
- verified complete absence of future-phase modules (MCP server, provider adapters, planners);
- verified cross-gate non-substitutability across all security boundaries;
- verified fact-authority law preservation (NOT_RUN ≠ PASS, tool success cannot promote to READY);
- zero personal spend maintained ($0.00); clean-room reimplemented (0 donor lines imported);
- zero blockers, zero FAIL findings, zero production code changes.

Phase exit:
Phase P-04 is CLOSED — independent QA PASS (Verified closure SHA: `3dbde03de5993a163f019a7867401d9f88310fdc`).

---

# P-05 — Real MCP Server Spine

Goal:
build the Alexa+ track's real open-standard interface.

### P-05.01 — Implement MCP server with current required Streamable HTTP transport
Status: DONE — independent QA PASS (Verified SHA: `c87c2046f8175f17db575b2a27c538bfaa95e150`)

Acceptance:
- official MCP Python SDK (`mcp>=2.2.0`, `mcp-types==2.2.0`) installed as minimum required direct dependency;
- server spine implemented in bounded package `src/stilldone/mcp/` (`server.py`, `__init__.py`) using official `mcp.server.mcpserver.MCPServer`;
- canonical Streamable HTTP endpoint `/mcp` configured with default loopback binding (`127.0.0.1`);
- deterministic server configuration `MCPServerConfig` (frozen, validating host, port, path, name, version);
- real loopback transport lifecycle `run_loopback_mcp_server` and `create_mcp_app` returning `starlette.applications.Starlette`;
- verified real loopback transport proof with official client `streamable_http_client` and `ClientSession`: protocol negotiation succeeds, negotiated protocol version observed as `2025-11-25` matching Alexa+ specification;
- clean shutdown: client and server terminate cleanly and loopback port is verified released;
- zero business tools, zero prompts, zero resources exposed; no mission-status tool (P-05.03), no mission-start tool (P-05.04);
- zero auth middleware, PRM, or OAuth (P-05.05);
- zero Google/AWS/Open-Meteo provider calls, zero model calls, zero ledger/evidence mutations;
- all 631 existing tests remain green (total passing: 652 tests).

### P-05.02 — Implement protocol initialization, capability declaration, and health/readiness
Status: DONE — independent QA PASS (Verified SHA: `a5812224ef2430699d40d37a75ef9937c1be482d`)

Acceptance:
- immutable protocol snapshots `MCPCapabilitySnapshot` and `MCPInitializationSnapshot` implemented in `src/stilldone/mcp/protocol.py`;
- truthful protocol negotiation snapshot extracting real negotiated protocol version (`2025-11-25` matching Alexa+ spec), canonical server identity (`StillDone` / `0.1.0`), and declared capability flags;
- official MCP runtime advertises tools capability (`has_tools=True`, `tools.listChanged` observed `False`);
- official MCP runtime advertises prompts capability (`has_prompts=True`);
- official MCP runtime advertises resources capability (`has_resources=True`);
- current StillDone business surface remains empty: 0 tools (`list_tools() == []`), 0 prompts (`list_prompts() == []`), 0 resources (`list_resources() == []`);
- protocol capability advertised != business items exposed; advertising protocol capabilities does not mean a StillDone business feature exists;
- no mission-status/start business tool exists yet (`mission_status`, `mission_start`, etc.), zero provider capabilities (`google`, `aws`, `bedrock`, `weather`), and zero auth mechanisms declared;
- protocol snapshots confer zero authority, create zero approval grants or execution attempts, and cannot produce `VERIFIED` or `READY` mission state;
- deterministic plain HTTP `/health` endpoint implemented in `src/stilldone/mcp/health.py` returning `{"status": "alive", "scope": "process"}` (HTTP 200, no-cache headers);
- deterministic plain HTTP `/ready` endpoint implemented in `src/stilldone/mcp/health.py` returning `{"status": "ready", "scope": "mcp_transport"}` (HTTP 200) when transport is ready, or `{"status": "not_ready", "scope": "mcp_transport"}` (HTTP 503) when unready;
- readiness scope strictly declared as `mcp_transport`; does not claim ledger readiness, provider readiness, auth readiness, or mission readiness;
- endpoints mounted on existing Starlette app via `MCPServerConfig` (`health_path="/health"`, `ready_path="/ready"`) with path collision validation against `/mcp`;
- zero secrets, tokens, or environment dumps in health/ready responses;
- full test coverage added in `tests/test_mcp_server.py` (33 focused MCP tests); 664 total tests passing in suite.

### P-05.03 — Expose read-only mission-status tool over typed contracts
Status: DONE — independent QA PASS (Verified SHA: `01effe9cdd210afa71a68812d1b51908a547f4fe`)

Acceptance:
- StillDone's first business MCP tool registered: `mission_status` using official MCPServer tool API;
- input schema derived from type hints requires `mission_id: str`;
- published MCP input schema explicitly declares `additionalProperties: false`; unexpected extra arguments fail closed at runtime with redacted values (`[REDACTED]`), zero ledger mutation, and full transport-level verification over Streamable HTTP;
- tool input parses strictly via canonical `MissionId` and queries `MissionLedgerPort.get_mission(MissionId)`;
- malformed UUID fails closed with bounded safe tool error without echoing malformed input;
- missing mission maps `RecordNotFoundError` to visible bounded safe tool error without manufacturing records or storage;
- typed immutable projection `MissionStatusView` implemented in `src/stilldone/mcp/mission_status.py` preserving `MissionId`, `MissionState`, and timezone-aware UTC timestamps;
- bounded wire serialization `MissionStatusPayload` projects strictly `mission_id`, `state`, `created_at`, `updated_at`;
- privacy minimization strictly enforced: zero user intent text, zero action contracts, zero target IDs, zero evidence payloads, zero approval material, zero secrets;
- official `ToolAnnotations` marks tool as read-only (`read_only_hint=True`, `destructive_hint=False`, `idempotent_hint=True`, `open_world_hint=False`);
- zero mutation: mission_status performs zero ledger writes, zero state alterations, zero attempt/grant creation;
- zero provider/model calls: 0 Google calls, 0 AWS/Bedrock/AgentCore calls, 0 Open-Meteo calls, 0 LLM calls;
- deterministic ledger fact pass-through across multiple canonical `MissionState` members with zero model prose rewriting;
- business surface updated from 0 tools to exactly 1 tool (`mission_status`); `mission_start` remains absent, prompts remain empty (0), resources remain empty (0);
- full test coverage added in `tests/test_mcp_mission_status.py` (30 focused tests, 63 total MCP tests, 694 total tests passing in suite).

### P-05.04 — Expose mission-start tool without live mutation yet
Status: DONE — independent QA PASS (Verified SHA: `e208ebf93e11863c64d886f3de3462fc427ed3e1`)

Acceptance:
- StillDone's second business MCP tool registered: `mission_start` using official MCPServer tool API;
- business surface contains exactly 2 business tools: `mission_status` and `mission_start`; zero aliases (`start_mission`, `create_mission`, `execute_mission`); prompts remain empty (0), resources remain empty (0);
- input schema contains strictly `intent: str` with `additionalProperties: false`; unexpected extra arguments (e.g. caller-supplied `mission_id`, `state`, `created_at`, `actions`, `approval`) fail closed at both schema and runtime levels with redacted values (`[REDACTED]`), leaving ledger completely unmutated;
- blank and whitespace-only intents fail closed with bounded safe tool errors;
- canonical domain creation path reused: runtime-generated `MissionId`, verbatim `UserIntentSnapshot`, `MissionContract`, initial `MissionRecord(state=MissionState.DRAFT)`, appended via `MissionLedgerPort.append_mission()`;
- zero second `MissionId`, intent object, lifecycle enum, MCP mission store, or parallel domain model;
- initial state is strictly `MissionState.DRAFT`; no promotion to `PLANNED`, `EXECUTING`, `VERIFYING`, or `READY`;
- deterministic timestamp ownership: single UTC timestamp used across `captured_at`, `contract.created_at`, `record.created_at`, `record.updated_at`;
- shared ledger law enforced: `mission_start` and `mission_status` share the exact same `MissionLedgerPort` instance within the MCP server; calling `mission_start` then immediately `mission_status` returns matching `DRAFT` record without extra mutation;
- strictly zero live / external mutation: 0 Google calls, 0 Tasks calls, 0 AWS/AgentCore/Bedrock calls, 0 model planning, 0 action execution, 0 provider reads, 0 reconciliation;
- zero ActionRecord, EvidenceRecord, ApprovalGrant, or ExecutionAttempt created;
- output contract privacy minimization: typed immutable projection `MissionStartView` and wire payload `MissionStartPayload` returning strictly `mission_id`, `state` ("DRAFT"), `created_at`; verbatim user intent and internal ledger repr are strictly excluded from output;
- official `ToolAnnotations` marks tool truthfully: `read_only_hint=False`, `destructive_hint=False`, `idempotent_hint=False`, `open_world_hint=False`;
- duplicate call truth documented and tested: two calls with identical intent generate two distinct `MissionId`s and two independent records; no silent deduplication;
- shared strict-input helper `src/stilldone/mcp/strict_input.py` extracted and reused across `mission_status` and `mission_start`;
- full test coverage in `tests/test_mcp_mission_start.py` (19 focused test methods covering all 45 requirements); 82 total MCP tests, 713 total tests passing in suite.

### P-05.05 — Add auth/rate-limit boundary appropriate to the proven judge path
Status: DONE — independent QA PASS (Verified SHA: `85f251c32d4ecd1622e04a4d80be9b8c2b1e8f24`)

Acceptance:
- StillDone OAuth 2.0 Resource Server boundary implemented in `src/stilldone/mcp/auth.py` via official MCP SDK primitives (`AuthSettings`, `TokenVerifier`, `AccessToken`); StillDone is RS only (zero token minting, zero login UI, zero authorization server implementation);
- `MCPAuthConfig` immutable configuration frozen (`issuer_url`, `resource_server_url`, `required_scopes`, `validate_token_resource=True`, `alexa_profile=True`);
- Auth fail-closed configuration enforced: `create_mcp_app` and `create_mcp_server` reject `auth_config` without effective `token_verifier` with `ValueError` before serving /mcp; `required_scopes` strictly rejects empty collections, duplicates, and blank strings;
- Explicit local unprotected mode permitted only when `auth_config is None`;
- Alexa+ 401 compatibility layer `Alexa401CompatibilityMiddleware` implemented: suppresses `WWW-Authenticate` header specifically on HTTP 401 responses, while preserving 403 Forbidden and other response headers with `WWW-Authenticate`;
- RFC 9728 Protected Resource Metadata (PRM) published at canonical `/.well-known/oauth-protected-resource/mcp`, declaring canonical resource URL, external authorization server issuer, supported scopes, and `header` bearer method;
- External Authorization Server status strictly declared as `AUTHORIZATION_SERVER_LIVE_COMPATIBILITY = "NOT_ESTABLISHED"`;
- Current Alexa+ two-tier auth model documented: Tier 1 M2M `client_credentials` (`mcp:service`) and Tier 2 user `authorization_code` + PKCE;
- Sentinel token protection: bearer tokens are never logged or leaked into error messages or response bodies;
- Caller classification law preserved: authenticated public clients remain `CallerClass.PUBLIC_UNTRUSTED`;
- Request exposure classification: `RequestExposureClass.NO_PAID_CAPABILITY` (zero paid providers wired; `live_paid_path_enabled=False`);
- Persistent atomic rate limiting implemented in `src/stilldone/mcp/rate_limit.py` using stdlib `sqlite3` in WAL mode with `BEGIN IMMEDIATE` (zero race window);
- Rate limit fail-closed configuration enforced: Mode A (no rate protection: all None) vs Mode B (policy + exactly one store source: either injected `rate_limit_store` or `rate_limit_db_path`); partial or ambiguous configurations reject with `ValueError` at construction before serving;
- Canonical P-04.06 contracts strictly reused: `EndpointProtectionPolicy`, `RateSnapshot`, `EndpointRequestAssessment`, `EndpointAdmissionDecision`, `evaluate_endpoint_admission`;
- Half-open window rollover law enforced: `[window_start, window_end)`; counts persist across store reconstruction;
- Privacy minimization in storage: zero tokens, zero user intents, zero contracts, zero external IDs stored; stores strictly integer request counters per window;
- Fail-closed storage behavior: database errors return bounded HTTP 500 (`rate_limit_unavailable`) without leaking file paths or internals;
- Quota isolation: `/health`, `/ready`, and RFC 9728 PRM endpoints are strictly exempt from rate limiting;
- Strict ordering: unauthenticated callers fail with HTTP 401 at the auth boundary before reaching rate limit evaluation (unauthenticated requests never consume rate quota);
- Full cross-boundary real loopback Streamable HTTP test executed: valid bearer + quota -> `mission_start` -> `mission_status` -> quota exhausted -> HTTP 429 (`retry_after_seconds` included) with zero ledger mutation;
- Zero cloud/provider calls ($0.00 spend); 0 personal spend;
- Full test coverage in `tests/test_mcp_auth_rate_limit.py` (42 focused tests including 13 fail-closed configuration tests); 755 total tests passing in suite.

### P-05.06 — Validate with current MCP inspector/client and remote deployment
Status: DONE — independent QA PASS (Verified SHA: `8ad1ec7a91a78ba593da7aa8c364bf4dd9b5c458`)

Acceptance:
- single authorized bounded live AWS AgentCore deployment campaign executed in `us-east-1` under strict operator limits: maximum gross cost risk $\le \$0.05\text{ USD}$ (reconciled two-session conservative authorization-risk bound $\approx \$0.0476\text{ USD}$), target personal spend strictly $\$0.00\text{ USD}$, 1 deployment attempt, 1 runtime, 2 logical proof sessions (`OPERATOR_SCOPE_DEVIATION_RECORDED`), `idleRuntimeSessionTimeout = 60`s, `maxLifetime = 300`s, local ARM64 build, IAM/SigV4 ingress authentication, local SigV4 signing/CLI bridge for Inspector, and mandatory immediate teardown;
- zero Amazon Cognito, zero AWS CodeBuild, zero customer-managed KMS keys used;
- explicit `agentcore` deployment profile implemented in `src/stilldone/mcp/server.py` (`host=0.0.0.0`, `port=8000`, `path=/mcp`, `stateless_http=False`) selected solely via explicit CLI/config flag without widening the local default loopback binding (`127.0.0.1`);
- bounded `/ping` health endpoint implemented in `src/stilldone/mcp/health.py` returning strictly `{"status": "Healthy"}` (HTTP 200) without secrets, tokens, AWS identifiers, or environment dumps, preserving `/health` and `/ready`;
- local ARM64 container image packaged via `docker buildx` and pushed to AWS ECR (`cdk-hnb659fds-container-assets-[REDACTED]-us-east-1:9a9ecc5`, manifest digest `sha256:e0be0c190b8409e0a94bc07fea76f013d594bd2b103bf7009ea535172c81b8c0`);
- minimal IAM execution role `StillDoneAgentCoreExecutionRole` created with trust principal `bedrock-agentcore.amazonaws.com` and managed policies `AmazonEC2ContainerRegistryReadOnly` and `AWSLambdaBasicExecutionRole`;
- single AgentCore runtime `stilldone_mcp_runtime-oS0aWdAWg3` deployed and reached `READY` in `us-east-1` (Platform V1, Server-Sent Events / Streamable HTTP on port 8000);
- direct data-plane wire invocations via `aws bedrock-agentcore invoke-agent-runtime`:
  - `initialize`: HTTP 200 OK, protocol `2024-11-05`, server `StillDone` v0.1.0;
  - `tools/list`: HTTP 200 OK, lists `mission_status` and `mission_start`;
  - `mission_start`: HTTP 200 OK, initialized mission in `DRAFT` state;
  - `mission_status`: HTTP 200 OK, read back exact `DRAFT` record from container memory within same session;
- local SigV4 signing/CLI bridge (`scripts/sigv4_proxy.py` on `127.0.0.1:8080/mcp`) verified: forwards MCP POST payloads to AgentCore InvokeAgentRuntime data plane without synthetic MCP business responses; GET /ping and /health fail closed (405) without fabricating remote health;
- official `@modelcontextprotocol/inspector@2.9.0` CLI proof executed: `tools/list` and `tools/call mission_status` successfully reached real AgentCore MCP endpoint through local SigV4 bridge;
- deployed rate limiting (HTTP 429) verified: deployed `/mcp` path returned HTTP 429 after quota consumption (`ValidationException: Received error (429) from runtime`), proving the rate limiter was active on the deployed remote container;
- immediate complete teardown executed: AgentCore runtime deleted (`agentRuntimes: []`), ECR repository images purged (`imageIds: []`), IAM execution role deleted (`NoSuchEntity`), local proxy terminated, AWS session revoked (`aws logout`);
- AWS Cost Explorer observed: `$0.00 USD` (estimated/billing-latency subject; actual billed cost and personal spend delta preserved as `NOT_OBSERVED`);
- all unit and integration tests passing;
- durable evidence documented in `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`.

### P-05.07 — Measure protocol latency and document Alexa+ direct-access compatibility gap
Status: DONE — independent QA PASS (Verified SHA: `6503127af61015b656fff4f44ebae2e4576ad74c`)

Acceptance:
- Deterministic measurement utility created in `scripts/measure_mcp_latency.py` with pure local loopback execution over real Streamable HTTP transport;
- Real loopback Uvicorn/Starlette MCP server + official current MCP Python client (`mcp==2.2.0`);
- Current `mission_status` tool measured against pre-populated canonical `InMemoryNonDurableLedger` (`MissionRecord` in `DRAFT` state); setup time strictly excluded from latency;
- Monotonic high-resolution clock (`time.perf_counter_ns()`) used for all measurements;
- Bounded deterministic campaign executed: 5 warmup + 30 measured requests per operation;
- Observed local protocol latency metrics against committed source SHA `4751ac0b87071f9178e0da184135b6fa2559d857` with clean working tree:
  - `initialize`: min 5.64ms, mean 8.15ms, p50 8.05ms, p95 10.59ms, max 11.06ms
  - `tools/list`: min 5.46ms, mean 7.86ms, p50 7.33ms, p95 10.50ms, max 10.81ms
  - `mission_status`: min 7.54ms, mean 14.88ms, p50 15.18ms, p95 18.56ms, max 20.47ms
- Provenance separation strictly maintained: local measurement classified as `LOCAL_LATENCY_HEADROOM_OBSERVED` under `LOCAL_EXECUTION`; historical remote echo (`61.26ms`) preserved as `RECORDED_LIVE`; current AgentCore deployed latency classified as `NOT_MEASURED`; current remote endpoint is `NONE`;
- Explicit non-certification statement enforced: local loopback latency does not certify remote production or Alexa+ production performance;
- Comprehensive Alexa+ direct-access compatibility gap matrix documented in `docs/P05_07_LATENCY_ALEXA_GAP.md`:
  - Transport (Streamable HTTP): PROVEN
  - Remote HTTPS MCP: PROVEN HISTORICALLY / RECORDED_LIVE (runtime torn down)
  - Tool Discovery: PROVEN (`mission_status`, `mission_start`)
  - Remote Tool Execution: PROVEN (`mission_start` -> `DRAFT`, `mission_status` read-back)
  - Latency (<500ms): DIRECT PRODUCTION CERTIFICATION = NOT_ESTABLISHED (Local p50 7.33-15.18ms, Historical remote echo 61.26ms, AgentCore NOT_MEASURED)
  - Service-Level Auth: INCOMPATIBLE AS DIRECT ALEXA+ AUTH PATH (P-05.06 deployment used IAM/SigV4; AgentCore JWT bearer 401 includes WWW-Authenticate while IAM returns 403; neither satisfies Alexa+ client_credentials discovery/auth)
  - User-Level Auth: NOT_ESTABLISHED (OAuth RS proven locally; external Authorization Server / account linking not established)
  - 401 Discovery Semantics: INCOMPATIBLE WITH CURRENT AGENTCORE INGRESS (Alexa+ requires 401 without WWW-Authenticate; AgentCore OAuth emits WWW-Authenticate; IAM returns 403)
  - RFC 9728 PRM: PROVEN LOCALLY; hosted PRM NOT_ESTABLISHED
  - Authorization Server Metadata: NOT_ESTABLISHED (StillDone is RS only)
  - DCR / OIDC / Step-Up: NOT_IMPLEMENTED (strictly compliant with Alexa+ unsupported mechanisms)
  - Partner / Add-On Access: NOT_ESTABLISHED / NOT_RUN (public docs limit Category SDK / MCP Toolkit to select partners)
- Protocol version truth analyzed: official SDK client negotiated `2025-11-25`, AgentCore handshake used `2024-11-05`, docs cite examples; no hard requirement exists in Alexa+ docs (`PROTOCOL_VERSION_BLOCKER = NOT_ESTABLISHED`);
- Deterministic compatibility verdict: `ALEXA_PLUS_DIRECT_ACCESS_COMPATIBILITY = INCOMPATIBLE_WITH_CURRENT_AGENTCORE_INGRESS` based on objective IAM SigV4 and OAuth 401 WWW-Authenticate header conflicts;
- Future architecture options documented only (Option A: dedicated edge proxy; Option B: AWS ingress adapter; Option C: simulated Alexa+ client with real AWS backend); zero future components implemented;
- Competition submission-safe wording preserved;
- Bounded unit and boundary tests added in `tests/test_mcp_latency.py` (10 tests passing); zero wall-clock thresholds asserted in CI to prevent flakiness.

Phase exit:
Phase P-05 is CLOSED — independent QA PASS (Verified closure SHA: `6503127af61015b656fff4f44ebae2e4576ad74c`).

Phase exit truth:
- real MCP Streamable HTTP server spine works;
- typed mission_status and mission_start exist;
- OAuth RS / PRM / fail-closed auth boundary proven locally;
- persistent atomic rate limiting proven locally;
- real AWS AgentCore remote MCP deployment proven historically / RECORDED_LIVE;
- real remote initialize/tools/list/mission_start/mission_status read-back proven;
- MCP Inspector 2.9.0 interoperability proven through the truthfully labeled local SigV4 signing/CLI bridge;
- current remote AgentCore endpoint = NONE after teardown;
- current AgentCore latency = NOT_MEASURED;
- local protocol latency headroom measured on committed source (`MEASURED_SOURCE_SHA = 4751ac0b87071f9178e0da184135b6fa2559d857`);
- Alexa+ direct access compatibility = INCOMPATIBLE_WITH_CURRENT_AGENTCORE_INGRESS;
- Alexa+ partner access = NOT_ESTABLISHED / NOT_RUN;
- no false Alexa+ integration claim;
- preserved historical OPERATOR_SCOPE_DEVIATION_RECORDED for the two logical P-05.06 sessions.

---

# P-06 — Real External Service Adapters

Goal:
prove external state can be read, mutated safely, and read back.

### P-06.01 — Implement Google Calendar read adapter against dedicated demo calendar
Status: DONE — awaiting independent QA PASS

Acceptance:
- bounded Google Calendar read adapter implemented in `src/stilldone/adapters/calendar.py` (`GoogleCalendarReadAdapter`);
- strictly restricted to configured dedicated demo calendar ID (`DemoResourceScope`);
- reuses P-04 action validation (`validate_action_contract`) and static demo isolation (`verify_demo_resource_isolation`);
- fails closed on out-of-scope calendar IDs (`CalendarOutOfScopeError`), missing parent ID (`MissingParentContainerError`), and strictly rejects 'primary' and 'default' (`CalendarScopeError`);
- exact event identity required (matching event summary text as identity is strictly rejected);
- pluggable transport boundary (`CalendarTransport` Protocol) with in-memory deterministic fake (`FakeGoogleCalendarTransport`) and official client wrapper (`GoogleApiClientCalendarTransport`);
- normalized observation (`CalendarEventObservation`) and result (`CalendarReadResult`) masking sensitive IDs in repr/str;
- event-not-found and cancelled status correctly mapped to `CalendarReadStatus.NOT_FOUND`;
- provider failure mapped to `CalendarReadStatus.PROVIDER_ERROR` without leaking secrets or tokens;
- provider read success does NOT imply `VERIFIED` or `READY`; zero mission state mutation;
- optional read-only live smoke test marked `NOT_RUN` (no stored local credentials);
- comprehensive unit tests in `tests/test_calendar_read_adapter.py` passing without network dependency.

### P-06.02 — Implement Google Calendar bounded update adapter with idempotency strategy
Status: DONE — awaiting independent QA PASS

Acceptance:
- bounded Google Calendar update adapter implemented in `src/stilldone/adapters/calendar.py` (`GoogleCalendarUpdateAdapter`);
- strictly restricted to canonical `calendar.update` action (`ActionType.CALENDAR_UPDATE`) and dedicated demo calendar scope;
- authority policy strictly enforced: requires bound `ApprovalGrant` (`AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED`); missing, expired, or mismatched approval fails closed before any provider read/write (`ApprovalRequiredError`, `ApprovalExpiredError`, `ApprovalBindingMismatchError`);
- demo isolation strictly enforced before any provider call;
- bounded update parameters: accepts only canonical `summary`, `start_time`, `all_day`; arbitrary injected payload fields fail closed (`UnknownParameterError`);
- read-before-write performed against exact event ID before any mutation;
- adapter-level idempotency strategy: deterministically compares currently observed fields with requested update; if already applied, performs zero provider write and returns `CalendarUpdateStatus.NOOP_ALREADY_APPLIED` with `writes_performed=0`;
- repeated identical invocation after successful update performs zero second write (`writes_performed=0`);
- conditional modification enforced: sends `If-Match: <etag>` with observed event ETag (never `*`);
- HTTP 412 / ETag mismatch handled gracefully producing `CalendarUpdateStatus.CONFLICT` with zero blind overwrite;
- preserves unrelated provider fields (`description`, `location`, `transparency`, etc.) across full event resource replacement;
- suppresses attendee notification side effects (`sendUpdates="none"`);
- mutation response alone does NOT create `VERIFIED` or `READY`; zero mission state mutation;
- comprehensive unit tests in `tests/test_calendar_update_adapter.py` passing with zero live Google mutation.

### P-06.03 — Implement Calendar independent read-back verifier
Status: DONE — awaiting independent QA PASS

Acceptance:
- Calendar-specific independent read-back verifier implemented in `src/stilldone/adapters/calendar.py` (`GoogleCalendarReadbackVerifier`);
- Independence law enforced: initiates a distinct, fresh provider read through `GoogleCalendarReadAdapter`; update response payload and provider-write success CANNOT substitute for read-back verification;
- compares freshly observed provider state deterministically against `ExpectedCalendarState` (`summary`, `start_time`, `all_day`);
- returns typed immutable `CalendarReadbackResult` (`CalendarReadbackStatus.MATCH`, `MISMATCH`, `NOT_FOUND`, `PROVIDER_ERROR`) with capture timestamp and explicit mismatch explanations;
- external drift after write verified: simulated operator drift between write and read-back produces `MISMATCH`, proving write success alone does not verify;
- verifier performs zero writes and zero mission/ledger state mutations;
- zero generic P-09 predicate engine, zero multi-provider dispatch, and zero mission `READY` promotion implemented;
- comprehensive unit tests in `tests/test_calendar_readback_verifier.py` passing.


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
