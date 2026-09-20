# Donor & Provenance Policy — StillDone

Verification & Snapshot Date: `2026-09-20`  
Governing Authority: AGENTS.md § 16, STILLDONE_MASTER_EXECUTION_PLAN.md P-00.03

---

## 1. Core Provenance Law & Global Default

1. **Global Default Reuse Class**:
   ```text
   CONCEPT_ONLY
   ```
2. **Competition-Defining Logic**:
   All core mission, contract, verification, drift, and authority logic in StillDone must be:
   ```text
   CLEAN_ROOM_REIMPLEMENTED
   ```
   No donor implementation code may be copied or adapted to bypass the live engineering spine.
3. **P-00.03 Authorization Boundary**:
   **P-00.03 authorizes ZERO donor source code import.**
   - Zero runtime files introduced;
   - Zero donor functions, classes, schemas, or configs copied;
   - Zero donor packages imported or vendored;
   - Zero "starter code" or scaffolding pulled from donor repositories.
   This document records an auditable conceptual inventory only.

---

## 2. Auditable Donor Inventory Table

Every donor was independently inspected on its canonical remote on `2026-09-20` via `git ls-remote` and direct root license verification:

| # | Donor Name | Canonical Repository URL | Default Branch | Immutable Commit SHA | Root License (SPDX) | Public? | Reuse Class | Source Code Imported? |
|---|---|---|---|---|---|---|---|---|
| 1 | **Universal Agent OS** | https://github.com/zyganali-glitch/Universal-Agent-OS | `main` | `6b83b06212101c238ec28076a2ba7ae819f483f2` | MIT | Yes | `CONCEPT_ONLY` | **NO** |
| 2 | **ChangeMesh** | https://github.com/zyganali-glitch/ChangeMesh | `main` | `7b349f0e005ccb416034df318baae67f43a1099d` | Proprietary (All Rights Reserved) | Yes | `CONCEPT_ONLY` | **NO** |
| 3 | **Codex Control Tower** | https://github.com/zyganali-glitch/codex-control-tower | `main` | `65ee1b72faf9a7202d9166eed43fb671804815a8` | MIT | Yes | `CONCEPT_ONLY` | **NO** |
| 4 | **ContextSeal** | https://github.com/zyganali-glitch/ContextSeal | `main` | `b8d87ad05e323b7366c8e0817839e01034c4438d` | Apache-2.0 | Yes | `CONCEPT_ONLY` | **NO** |
| 5 | **ZeroKit AI Control Plane** | https://github.com/zyganali-glitch/zerokit-ai-control-plane | `main` | `d663db8c706cb914e1af5caf651df08edb5c50c0` | MIT | Yes | `CONCEPT_ONLY` | **NO** |
| 6 | **Basebreak** | https://github.com/zyganali-glitch/Basebreak | `main` | `0a83be7a0e8c8fbb6eda278b6b4c1016ae6cef2b` | Apache-2.0 | Yes | `CONCEPT_ONLY` | **NO** |
| 7 | **Universal Agent OS UiPath** | https://github.com/zyganali-glitch/universal-agent-os-uipath | `main` | `dc2267939c2aef0aba2737da65f53352c5cf8fb2` | MIT | Yes | `CONCEPT_ONLY` | **NO** |
| 8 | **Universal Agent OS GitLab** | https://gitlab.com/zyganali/universal-agent-os-gitlab-edition | `main` | `3c4a412b6040d8a8154c15325943c409be9105f2` | MIT | Yes | `CONCEPT_ONLY` | **NO** |
| 9 | **Universal Agent OS Qwen** | https://gitlab.com/zyganali/universal-agent-os-qwen | `main` | `a43b3411856f41a4be9424d11c01a5e637cdc410` | MIT | Yes | `CONCEPT_ONLY` | **NO** |

---

## 3. Detailed Per-Donor Records

### 3.1 Universal Agent OS
- **Canonical Repo URL**: https://github.com/zyganali-glitch/Universal-Agent-OS
- **Default Branch**: `main`
- **Immutable Commit SHA**: `6b83b06212101c238ec28076a2ba7ae819f483f2`
- **Root License**: `LICENSE` — MIT License (Copyright (c) 2026 Mehmet Aydogan)
- **Relevant Concepts**:
  - `NOT_RUN ≠ PASS` (unexecuted checks remain explicitly unexecuted);
  - `edited ≠ validated` (syntax or file changes are not proof of correct behavior);
  - Evidence-first closure (conclusions require deterministic audit logs);
  - Durable handoff and strict micro-plan phase discipline.
- **Allowed StillDone Target Concept**: Master Plan and governance integrity discipline (`plans/STILLDONE_MASTER_EXECUTION_PLAN.md`, `docs/HANDOFF.md`).
- **Forbidden Terminology / Scope Leakage**: Heavy multi-agent governance ceremony in consumer UX; fleet role taxonomy (`lead-governor`, `spec-architect`, `qa-auditor`, `security-officer`); sprawling multi-agent orchestration configs.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.2 ChangeMesh
- **Canonical Repo URL**: https://github.com/zyganali-glitch/ChangeMesh
- **Default Branch**: `main`
- **Immutable Commit SHA**: `7b349f0e005ccb416034df318baae67f43a1099d`
- **Root License**: `LICENSE` — **Proprietary / All Rights Reserved** (Copyright (c) 2026 Mehmet Aydogan). Explicitly declares: *"No open-source license is granted for the ChangeMesh source code. No permission is granted to copy, modify, distribute, sublicense, or commercially use ChangeMesh source code..."*
- **Legal & Reuse Consequence**: **Strictly CONCEPT_ONLY.** Zero code reuse is legally or architecturally permissible.
- **Relevant Concepts**:
  - Saga / distributed workflow execution across heterogeneous services;
  - Mutation idempotency keys and deduplication semantics;
  - Partial failure handling and bounded retry/resume policies;
  - Action reversibility contracts;
  - Approval compression (consolidating required human sign-offs);
  - **Critical negative lesson**: A sophisticated simulation environment does not substitute for real execution and live observation.
- **Allowed StillDone Target Concept**: Idempotent mutation lifecycle and approval compression design (§ 7 & § 8 of AGENTS.md).
- **Forbidden Terminology / Scope Leakage**: `Change Evidence Passport`, `ShadowLab`, `Capability Passport`, `Mesh Agent Fleet`, `Policy Engine` shadow rehearsal vocabulary.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.3 Codex Control Tower
- **Canonical Repo URL**: https://github.com/zyganali-glitch/codex-control-tower
- **Default Branch**: `main`
- **Immutable Commit SHA**: `65ee1b72faf9a7202d9166eed43fb671804815a8`
- **Root License**: `LICENSE` — MIT License (Copyright (c) 2026 Codex Control Tower contributors)
- **Relevant Concepts**:
  - Deterministic observed facts outrank model prose;
  - Evidence freshness windows (TTL / stale evidence detection);
  - Advisory semantic interpretations cannot overwrite or promote deterministic evidence;
  - Clean, unadorned judge verification path.
- **Allowed StillDone Target Concept**: Deterministic desired-state predicate evaluation outranking LLM prose (StillDone Law 9 & Law 13).
- **Forbidden Terminology / Scope Leakage**: `Control Tower`, developer brownfield Git PR framing, GPT-5.6 / dual-LLM verifier as authority, `Fact Lock` schema.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.4 ContextSeal
- **Canonical Repo URL**: https://github.com/zyganali-glitch/ContextSeal
- **Default Branch**: `main`
- **Immutable Commit SHA**: `b8d87ad05e323b7366c8e0817839e01034c4438d`
- **Root License**: `LICENSE` — Apache License Version 2.0
- **Relevant Concepts**:
  - Strict success chain: `INTENT → CONTRACT → AUTHORITY → EXECUTE → INDEPENDENT READBACK → PREDICATE EVALUATION → VERIFIED`;
  - Mutation execute response is never accepted directly as verification;
  - Stale context invalidation upon real-world state changes;
  - Bounded authority binding approvals to exact targets, parameters, and time windows;
  - Strict separation between fixture/recorded evidence and live execution.
- **Allowed StillDone Target Concept**: Independent readback and predicate evaluation loop (§ 4 of AGENTS.md).
- **Forbidden Terminology / Scope Leakage**: `DataHub`, schema certification agent, `ContextSeal passport`, upstream/downstream blast radius GraphQL terminology.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.5 ZeroKit AI Control Plane
- **Canonical Repo URL**: https://github.com/zyganali-glitch/zerokit-ai-control-plane
- **Default Branch**: `main`
- **Immutable Commit SHA**: `d663db8c706cb914e1af5caf651df08edb5c50c0`
- **Root License**: `LICENSE` — MIT License (Copyright (c) 2026 ZeroKit Build Week contributors)
- **Relevant Concepts**:
  - Privacy-minimizing model context boundaries (minimizing personal data passed to LLMs);
  - Sanitization of private/sensitive fields before external inference;
  - Strict validation of model-generated structured outputs;
  - Keeping production/personal secrets outside AI memory.
- **Allowed StillDone Target Concept**: Minimal mission state persistence and credential/data minimization (§ 14 & § 15 of AGENTS.md).
- **Forbidden Terminology / Scope Leakage**: `ZeroKit registry`, multi-tenant SaaS control-plane framing, RBAC generator schemas.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.6 Basebreak
- **Canonical Repo URL**: https://github.com/zyganali-glitch/Basebreak
- **Default Branch**: `main`
- **Immutable Commit SHA**: `0a83be7a0e8c8fbb6eda278b6b4c1016ae6cef2b`
- **Root License**: `LICENSE` — Apache License Version 2.0
- **Relevant Concepts**:
  - Claim is not proof (`claim ≠ proof`);
  - Independent observation and verification;
  - Exact state/hash binding;
  - Live-first engineering law;
  - Canonical remote truth as single authority over agent reports;
  - Zero Personal Spend Law ($0.00 personal spend discipline);
  - Bounded single-task execution discipline.
- **Allowed StillDone Target Concept**: StillDone engineering governance and remote verification discipline (AGENTS.md §§ 1, 3, 12, 16).
- **Forbidden Terminology / Scope Leakage**: `BASE / CANDIDATE / COUNTERFACTUAL` triad vocabulary, causal mutation testing framework, delta gate breaking terminology.
- **Reuse Class**: `CONCEPT_ONLY / CLEAN_ROOM_GOVERNANCE_ADAPTATION`
- **Source Code Imported**: `NO`

---

### 3.7 Universal Agent OS — UiPath Edition
- **Canonical Repo URL**: https://github.com/zyganali-glitch/universal-agent-os-uipath
- **Default Branch**: `main`
- **Immutable Commit SHA**: `dc2267939c2aef0aba2737da65f53352c5cf8fb2`
- **Root License**: `LICENSE` — MIT License (Copyright (c) 2026 Zyganali Group)
- **Relevant Concepts**:
  - Human approvals must be independently read from the authority system of record, never inferred from chat messages like "yes";
  - Strict Real Mode with zero silent mock/fixture fallback on required live paths;
  - Evidence manifest separating live, portable, and simulated surfaces.
- **Allowed StillDone Target Concept**: Authority engine independent verification and honest live failure reporting (§ 8 & § 9 of AGENTS.md).
- **Forbidden Terminology / Scope Leakage**: `Maestro BPMN` orchestration vocabulary, RPA / robot execution terms, enterprise workflow process templates.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.8 Universal Agent OS — GitLab Edition
- **Canonical Repo URL**: https://gitlab.com/zyganali/universal-agent-os-gitlab-edition
- **Default Branch**: `main`
- **Immutable Commit SHA**: `3c4a412b6040d8a8154c15325943c409be9105f2`
- **Root License**: `LICENSE` — MIT License (Copyright (c) 2024-2026 Mehmet Aydogan)
- **Relevant Concepts**:
  - Translating rigorous governance into an understandable, non-technical user experience;
  - Reviewable human authority without friction;
  - High idea quality through accessible user value rather than visible developer complexity.
- **Allowed StillDone Target Concept**: Non-expert operator guidance and compact receipt UI (§ 22 of AGENTS.md).
- **Forbidden Terminology / Scope Leakage**: GitLab Duo / CI/CD pipeline gating terms, merge request governance terminology.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

### 3.9 Universal Agent OS — Qwen Cloud MemoryAgent
- **Canonical Repo URL**: https://gitlab.com/zyganali/universal-agent-os-qwen
- **Default Branch**: `main`
- **Immutable Commit SHA**: `a43b3411856f41a4be9424d11c01a5e637cdc410`
- **Root License**: `LICENSE` — MIT License (Copyright (c) 2026 Mehmet)
- **Relevant Concepts**:
  - Durable state across sessions;
  - Memory freshness, time decay, and invalidation;
  - Mistake prevention and cross-session continuity;
  - Avoiding unbounded "remember everything" scope creep.
- **Allowed StillDone Target Concept**: Mission ledger cross-session persistence and drift detection (§ 6 & § 15 of AGENTS.md).
- **Forbidden Terminology / Scope Leakage**: Qwen Cloud MemoryAgent vocabulary, vector database embedding recall terms, generic conversational memory stores.
- **Reuse Class**: `CONCEPT_ONLY`
- **Source Code Imported**: `NO`

---

## 4. Donor-Soup Protection & Terminology Isolation

StillDone maintains its own clean, focused domain vocabulary. The following boundary is enforced across all documentation, interfaces, and future code:

| Forbidden Donor Terminology | StillDone Domain Language | Architectural Rationale |
|---|---|---|
| `Change Evidence Passport` / `Capability Passport` / `Passport` | `Mission Ledger` / `Evidence Store` | StillDone tracks state verification, not generic enterprise travel documents. |
| `ShadowLab` / `Simulated Fleet` | `Simulated Alexa+ Client Surface` | Web client simulation is an optional judge surface, not an autonomous rehearsal sandbox. |
| `Control Tower` / `Fact Lock` | `Authority Engine` / `Contract Compiler` | StillDone is an assistant mission runtime, not an IT operational monitoring tower. |
| `Code Soul` / `Agent Fleet Roles` | Model-Planner & Deterministic Runtime | Single-agent / model decomposition with deterministic verification, no fleet bureaucracy. |
| `ZeroKit Registry` / `RBAC Generator` | `Authority / Approval Boundary` | Scoped action authorization (5 bounded action classes), not enterprise tenant RBAC. |
| `BASE / CANDIDATE / COUNTERFACTUAL` | `Contract / Readback / Predicate` | StillDone verifies real-world state against user intent, not git patch regressions. |
| `Maestro BPMN` / `Robot Process` | `Mission Executor` / `Service Adapters` | Bounded API calls to Google Calendar, Google Tasks, and Open-Meteo. |
| `MemoryAgent` / `Vector Embedding Store` | `Durable Mission State` / `Drift Engine` | Minimal typed predicate contracts, not unconstrained conversation memory. |

### StillDone Canonical Domain States:
- **Result States**: `NOT_RUN`, `EXECUTED_UNVERIFIED`, `VERIFIED`, `CONTRADICTED`, `BLOCKED`, `FAILED`, `STALE`, `DRIFTED`.
- **Mission Overall States**: `DRAFT`, `PENDING_APPROVAL`, `IN_PROGRESS`, `READY`, `DRIFTED`, `FAILED`.
- **Evidence Provenance Values**: `FIXTURE`, `LOCAL_EXECUTION`, `LIVE_AWS`, `LIVE_GOOGLE`, `LIVE_EXTERNAL`, `RECORDED_LIVE`.

---

## 5. Future Actual-Code Reuse Preflight Protocol

If any implementation code is ever proposed for adaptation or reuse from any donor in future phases (e.g., P-10 or P-11), the following 10-point preflight audit must be documented and committed in an audit record **before** any code is introduced:

1. **Donor Repository**: Exact canonical URL;
2. **Immutable SHA**: Exact pinned commit SHA;
3. **Root License**: Verified license permitting the reuse class (Note: `ChangeMesh` is proprietary and prohibited from code reuse);
4. **Source Path(s)**: Exact file and symbol paths in donor;
5. **Target Path(s)**: Exact intended path in StillDone;
6. **Transformation Plan**: Complete description of clean-room adaptations, removal of donor terms, and alignment with StillDone contracts;
7. **Explicit Reuse Class**: Must be `CLEAN_ROOM_REIMPLEMENTED` or `ADAPTED_WITH_PROVENANCE`;
8. **Test Suite**: Dedicated independent unit/property tests covering the adapted logic;
9. **Introduction Git Commit**: Specific isolated commit introducing the adaptation with provenance attribution;
10. **Security & Zero-Cost Review**: Confirmation that the adapted code introduces no external paid API calls, secrets, or telemetry.

---

## 6. Closure Summary

- **All 9 canonical donors** are pinned with verified default branches and immutable commit SHAs.
- **Root licenses** for all 9 donors were fetched and verified from remote repositories.
- `ChangeMesh` was identified as **Proprietary / All Rights Reserved**, reinforcing its strict `CONCEPT_ONLY` classification.
- Donors 8 and 9 (`universal-agent-os-gitlab-edition` and `universal-agent-os-qwen`), previously marked `NOT_PINNED`, are now fully pinned to exact remote commit SHAs and verified MIT licenses.
- **Zero donor source code** has been imported, copied, or vendored.
- All donor lessons are preserved conceptually while strictly forbidding donor-soup terminology leakage.
