# Donor & Provenance Policy

## Default

All listed existing projects are **conceptual donors only**.

No donor source code is authorized for import by this document.

Default reuse class:
`CONCEPT_ONLY`

Competition-defining logic should be:
`CLEAN_ROOM_REIMPLEMENTED`

## Donor inventory

### Universal Agent OS
Repo:
https://github.com/zyganali-glitch/Universal-Agent-OS

Current inspected main SHA at planning time:
`6b83b06212101c238ec28076a2ba7ae819f483f2`

Useful concepts:
- `NOT_RUN ≠ PASS`;
- edited ≠ validated;
- evidence-first closure;
- durable handoff;
- plan-before-code.

Do not import:
- heavyweight multi-agent governance ceremony into product UX;
- broad adapter/config surface without a StillDone need.

Reuse:
`CONCEPT_ONLY`

### ChangeMesh
Repo:
https://github.com/zyganali-glitch/ChangeMesh

Useful concepts:
- long-lived distributed workflow;
- idempotency;
- partial failure;
- retries/resume;
- reversibility;
- approval compression;
- evidence passport thinking.

Critical lesson:
a sophisticated simulation does not replace a real execution path.

Reuse:
`CONCEPT_ONLY`

### Codex Control Tower
Repo:
https://github.com/zyganali-glitch/codex-control-tower

Useful concepts:
- deterministic facts outrank model prose;
- blind semantic challenge as advisory, not authority;
- evidence freshness;
- clear judge path.

Do not import:
- developer-tool framing;
- a second LLM as final verifier.

Reuse:
`CONCEPT_ONLY`

### ContextSeal
Repo:
https://github.com/zyganali-glitch/ContextSeal

Useful concepts:
- write → independent read-back;
- bounded authority;
- stale context;
- approval binding;
- evidence/passport integrity;
- fixture/live separation.

Reuse:
`CONCEPT_ONLY`

### ZeroKit AI Control Plane
Repo:
https://github.com/zyganali-glitch/zerokit-ai-control-plane

Useful concepts:
- privacy-bounded model context;
- sanitize before model exposure;
- strict generated-artifact validation;
- local truth around model output.

Reuse:
`CONCEPT_ONLY`

### Basebreak
Repo:
https://github.com/zyganali-glitch/Basebreak

Useful concepts:
- claim is not proof;
- independent verification;
- exact-state/hash binding;
- live-first;
- strict donor manifest;
- zero-cost law;
- canonical remote truth;
- one exact task at a time.

StillDone governance intentionally uses Basebreak as a structural reference, but does not copy Basebreak product implementation.

Reuse:
`CONCEPT_ONLY / CLEAN_ROOM_GOVERNANCE_ADAPTATION`

### Universal Agent OS — UiPath Edition
Repo:
https://github.com/zyganali-glitch/universal-agent-os-uipath

Useful concepts:
- approval must be read from the authority system, not trusted from chat alone;
- strict real mode / no mock fallback;
- evidence manifest separating live, portable, and simulated surfaces.

Reuse:
`CONCEPT_ONLY`

### Universal Agent OS — GitLab Edition
Repo:
https://gitlab.com/zyganali/universal-agent-os-gitlab-edition

Useful concepts:
- translate governance into a simple non-technical user experience;
- reviewable human-approved workflow;
- strong idea quality through understandable value.

Planning-time GitLab immutable SHA:
`NOT_PINNED`

Reason:
current research environment could not reliably retrieve raw GitLab branch metadata. Since code reuse is not authorized, this does not block product planning. `P-00.03` must pin the exact current commit/license before any reuse decision.

Reuse:
`CONCEPT_ONLY`

### Universal Agent OS — Qwen Cloud MemoryAgent
Repo:
https://gitlab.com/zyganali/universal-agent-os-qwen

Useful concepts:
- durable state;
- memory freshness;
- forgetting/decay;
- mistake prevention;
- cross-session continuity.

Do not import:
- general-purpose “remember everything” product scope.

Planning-time GitLab immutable SHA:
`NOT_PINNED`

`P-00.03` must pin commit/license before any non-concept reuse.

Reuse:
`CONCEPT_ONLY`

## Reuse classes

- `CONCEPT_ONLY`
- `CLEAN_ROOM_REIMPLEMENTED`
- `ADAPTED_WITH_PROVENANCE`
- `UNCHANGED_INFRASTRUCTURE`

Any move beyond `CONCEPT_ONLY` requires a pre-implementation provenance record.

## Required provenance record for actual code reuse

- donor repo;
- immutable SHA;
- root license;
- source path(s);
- exact reused concept/code;
- reuse class;
- target path(s);
- transformation;
- tests;
- introduction commit;
- compatibility/security review.

## Donor soup prohibition

StillDone must not become a bundle of old product terminology.

Avoid carrying names such as:
- passport;
- shadow lab;
- control tower;
- code soul;
- capability passport;
- causal world;
- ZeroKit registry;

unless StillDone independently needs the concept and introduces domain-appropriate language.
