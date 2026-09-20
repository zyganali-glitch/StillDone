# AGENTS.md — StillDone Coding-Agent Constitution

## 1. Authority and source of truth

Intended canonical repository: `zyganali-glitch/StillDone`
Canonical branch: `main`.

Until the repository is created and the first commit is pushed, this starter pack is the bootstrap input, not canonical remote truth.

After bootstrap, before every edit:
1. inspect/fetch remote `main`;
2. record starting remote SHA;
3. read `plans/STILLDONE_MASTER_EXECUTION_PLAN.md`;
4. read `docs/HANDOFF.md`;
5. read only architecture/security/evidence docs relevant to the exact active task.

Never trust an agent report over canonical remote state.

## 2. Exact-task execution

Work on exactly one active Master Plan micro-task unless the task explicitly defines a bounded batch.

Do not:
- rename exact Master Plan tasks;
- merge/split/reinterpret them silently;
- pre-implement later phases;
- broaden scope because an adjacent improvement looks useful.

If a required external dependency blocks the active live gate, follow the bounded parallelization law in the Master Plan. Never improvise phase skipping.

## 3. Closure contract

Edited ≠ validated.
Local commit ≠ remote closure.
Green tests ≠ live proof.
Recorded live ≠ current live.
Fixture ≠ live.
Model confidence ≠ fact.
`NOT_RUN` ≠ `PASS`.

Every completion report must include:
- exact task;
- starting remote SHA;
- final remote SHA;
- changed files;
- exact commands executed;
- command results and exit status;
- evidence provenance;
- checks explicitly `NOT_RUN`;
- live integrations actually exercised;
- donor reuse, if any;
- final push confirmation;
- remote SHA re-check.

Do not self-award independent QA `PASS`.

## 4. Core product invariant

StillDone exists to enforce:

> **An outcome is not complete until the resulting state is independently observed, and completion can be revoked if reality later drifts.**

A successful execute/tool response MUST NOT directly produce `VERIFIED`.

Required success chain for a mutable real-world step:

`INTENT → CONTRACT → AUTHORITY → EXECUTE → INDEPENDENT READBACK → PREDICATE EVALUATION → VERIFIED`

If the read-back cannot prove the expected state:
- keep the step unverified or contradicted;
- do not let model prose promote it.

## 5. Desired-state authority

The model may:
- interpret user intent;
- propose a mission plan;
- propose supported actions;
- explain discrepancies.

The model may NOT:
- assign deterministic evidence state;
- mark a mutation verified;
- override read-back mismatches;
- erase `NOT_RUN`, `BLOCKED`, `FAILED`, `STALE`, or `DRIFTED`;
- fabricate external identifiers;
- fabricate approvals.

Mission `READY` is computed by deterministic code from required predicates and freshness rules.

## 6. Drift law

`READY` is not permanent.

If a previously verified external fact later fails its predicate or freshness contract:
- the mission must be downgraded;
- historical verification remains recorded as history;
- current truth becomes authoritative;
- user-facing output must state what changed.

Historical receipts never override current system-of-record state.

## 7. Idempotency and recovery

Every supported mutation must define:
- an idempotency key or equivalent deduplication strategy;
- bounded retry policy;
- independent verification;
- duplicate prevention or explicit duplicate detection;
- safe resume semantics.

A retry is not allowed to create a second effect merely because the first response was lost.

## 8. Approval compression

Human approval is reserved for bounded authority boundaries, not every small step.

Initial action classes:
- `READ_ONLY`
- `REVERSIBLE_AUTO`
- `REVERSIBLE_APPROVAL_REQUIRED`
- `EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED`
- `IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED`

Approval must bind to:
- mission ID;
- action ID;
- normalized action parameters;
- target identity;
- expiry/validity window.

A chat message such as “yes” is not enough unless it is bound to the exact pending approval object.

## 9. Live-first law

Required live paths must execute real technology.

For the competition core:
- real self-hosted MCP server over Streamable HTTP;
- real AWS model/runtime where required by the active task;
- real Google Calendar / Tasks calls for the killer mission;
- real Open-Meteo read;
- independent real read-back after mutation.

No silent fallback from live to fixture/simulation.

The Alexa+ **client surface** may be simulated if direct Alexa+ partner access is unavailable. If simulated, it must be visibly labeled. A simulated client may still call a real backend.

## 10. Evidence provenance

Provenance is separate from result.

Canonical provenance values:
- `FIXTURE`
- `LOCAL_EXECUTION`
- `LIVE_AWS`
- `LIVE_GOOGLE`
- `LIVE_EXTERNAL`
- `RECORDED_LIVE`

`RECORDED_LIVE` is historical evidence and never presented as a fresh call.

## 11. AWS truth boundary

Do not assume:
- model IDs;
- enabled regions;
- AgentCore availability;
- Strands behavior;
- free-tier coverage;
- promotional-credit balance;
- post-credit billing behavior.

Current AWS facts must come from:
1. official current AWS docs; and/or
2. live account/runtime discovery.

Do not hard-code the final AWS architecture before `P-01` feasibility closure.

## 12. Zero Personal Spend Law

Target personal spend is `$0.00`.

Allowed:
- hackathon promotional credits;
- free tiers;
- free/open-source tools;
- local development;
- services that remain below free thresholds.

Forbidden without explicit operator approval:
- paid subscriptions;
- pay-as-you-go continuation after promotional/free budget;
- deposits/pre-authorizations;
- paid upgrades;
- automatic paid fallback;
- public unmetered endpoints that can consume paid credits.

Promotional credit is a finite budget, not permission to incur personal spend.

If a provider cannot be safely bounded to zero personal spend, mark the live task `BLOCKED` or `OPERATOR_DECISION_REQUIRED`.

## 13. Google/third-party billing boundary

Current documentation indicates standard Calendar/Gmail use is free below daily thresholds, with later-2026 billing changes planned for over-threshold use. Therefore:
- keep StillDone dramatically below standard thresholds;
- do not request paid quota increases;
- do not enable billing merely to raise quotas unless the operator explicitly approves;
- re-verify pricing before live setup.

Google Tasks courtesy quota and Open-Meteo free non-commercial limits must also be re-verified before use.

## 14. Security

Never commit:
- OAuth client secrets;
- access/refresh tokens;
- AWS credentials;
- session cookies;
- personal calendar/task contents;
- private email addresses used for demo;
- `.env` files.

Secrets are runtime-only.

Use a dedicated disposable StillDone demo calendar and task list whenever possible.

Public evidence must sanitize:
- account identifiers;
- emails;
- calendar IDs;
- OAuth material;
- tokens;
- private event text unrelated to the demo.

## 15. Privacy minimization

Persist the smallest mission state necessary.

Prefer storing:
- mission contract;
- normalized predicates;
- external resource IDs where required;
- hashes/digests;
- verification timestamps;
- authority state;
- bounded evidence metadata.

Do not build a general “copy my whole life into AI memory” product.

## 16. Donor policy

Existing user repositories are donors only.

Default reuse class: `CONCEPT_ONLY`.

Competition-defining logic should prefer:
- `CONCEPT_ONLY`; or
- `CLEAN_ROOM_REIMPLEMENTED`.

Any copied/adapted source requires a provenance record BEFORE closure:
- donor repository;
- immutable SHA;
- license;
- exact source/concept;
- reuse class;
- target path;
- transformation;
- tests;
- introduction commit.

Never import old product terminology merely because a donor used it.

## 17. Test integrity

Do not weaken tests to obtain green.

Builder-authored tests are development evidence, not automatically independent proof.

For verification logic, test at minimum:
- success;
- write success/read-back mismatch;
- timeout after write;
- duplicate retry;
- stale evidence;
- resource changed externally;
- blocked approval;
- wrong approval binding;
- missing external resource;
- provider error;
- model malformed plan;
- model unsupported action;
- replay/tamper attempt.

## 18. Documentation sync

Update immediately when critical truth changes:
- Master Plan active task/status;
- HANDOFF verified SHA and blocker;
- competition eligibility/access facts;
- architecture/security/evidence boundary;
- donor provenance;
- live-vs-recorded evidence;
- pricing/billing risk.

Batch harmless wording and duplicated counts.

Wrong SHA, false live claim, wrong evidence provenance, security/licensing/eligibility error is never minor.

## 19. Product-feedback/friction logging

Every real Amazon/AWS/Alexa+/MCP friction event must be recorded factually in:
`docs/COMPETITION_FEEDBACK_LOG.md`

Record:
- task attempted;
- expected behavior;
- actual behavior;
- severity;
- workaround;
- actionable suggestion;
- source/evidence.

Never invent friction for bonus points.

## 20. Git

After canonical bootstrap:
- commit messages identify exact task, e.g. `docs(p00.01): ...`;
- push to `origin/main` unless active task says otherwise;
- remote SHA must be independently re-checked.

A local commit is not task closure.

## 21. P-Ω integrity audits

Run focused integrity checks continuously.

Run broader audits at:
- P-00 closure;
- P-01 live feasibility closure;
- first complete live mutation/read-back slice;
- first drift/reconciliation proof;
- security/authority boundary changes;
- donor code introduction;
- release candidate;
- submission freeze.

Do not turn every micro-task into maximal ceremony.

## 22. Operator guidance

The operator is non-expert.

For every external account/service step, provide Turkish screen-by-screen guidance:
- official URL;
- exact page/menu;
- exact button;
- exact fields;
- what to enter;
- what NOT to enable;
- card/payment risk;
- secret storage location;
- success verification;
- fallback if UI differs.

Never ask the operator to paste credentials into chat.

## 23. Antigravity report format

Every executor report must contain:
- Task
- Starting remote SHA
- Final remote SHA
- Changed files
- Implementation
- Commands and results
- Evidence provenance
- Live integrations actually exercised
- NOT_RUN
- Donor reuse
- Risks/blockers
- Remote push confirmation

If blocked, report the smallest blocker. Do not invent a fallback.

## 24. Competition priority order

Protect equally:
1. Technological Implementation
2. Design
3. Potential Impact
4. Quality of Idea

Do not sacrifice a working live spine for decorative features.
