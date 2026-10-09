# P-11.05 Evidence: Calendar Existing-Event Update Remains NOT_RUN Before Approval

## 1. Executive Summary

- **Task**: `P-11.05 — Prove Calendar existing-event update remains NOT_RUN before approval`
- **Execution Mode**: `Independent-QA-directed consolidated evidence-integrity repair` (Defects 1 through 5 resolved)
- **Execution Timing**: Dynamic runtime timestamps recorded per execution run (derived from timezone-aware `read_at` and `evaluated_at` fields in each generated `UnapprovedActionReceipt`). The previous unsupported static timestamp (`2026-10-08T20:40:00+00:00`) has been eliminated.
- **Last Independently Verified Remote SHA**: `4ec4475f006207ec5840880bb9476f6d169442cd`
- **Target Event Identity**: `evt_leave_for_school_001` on dedicated demo calendar `c_1880abc123demo@group.calendar.google.com`
- **Action Type**: `ActionType.CALENDAR_UPDATE` (`calendar.update`)
- **Authority Classification**: `AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED`
- **Pending Approval ID**: Content-addressed SHA-256 (`PendingApprovalId`)
- **Approval Decision Status**: `PendingApprovalStatus.PENDING` (`is_approved=False`)
- **Approval Grant Present**: `False` (`approval=None`; zero grant created or submitted)
- **Approval Consumption Negative Proof Boundary**:
  - Exactly bounded: no `ApprovalGrant` supplied, zero approval-consumption operations recorded for the target `action_id` in `ApprovalLedger`, and no authorization granted.
  - Eliminated invalid `PendingApprovalId` lookups in `ApprovalLedger` (which indexes by `ApprovalId`).
  - Silent `ledger=None` assumption eliminated; receipt creation strictly requires explicit `ApprovalLedger` evidence and fails closed otherwise.
  - No global unobserved claim of historical approval consumption outside observed ledger records.
- **Provider Mutation Entry-Point Invocations**: Strictly `0` across all three mutation entry points:
  - `router_mutation_invocations == 0`
  - `handler_mutation_invocations == 0`
  - `transport_mutation_invocations == 0`
  - Independently instrumented and measured via `CalendarMutationSpy`, not an arbitrary caller-supplied zero integer.
- **Provider Writes Count**: Strictly `0` (`FakeGoogleCalendarTransport.writes_count == 0`; zero HTTP `PUT`/`PATCH`/`POST` calls).
- **Deterministic Execution State**: `ActionExecutionStatus.NOT_RUN` (`is_authorized=False`, `attempt=None`).
- **Bounded External State Observed**:
  - The observed state contract explicitly covers a bounded subset: `event_id`, `calendar_id`, `summary`, `start_time`, `end_time`, `all_day`, `etag`, and `status`.
  - Does not claim that all conceivable Google Calendar provider fields were observed.
  - Provenance: `LOCAL_EXECUTION` / `FIXTURE` on `FakeGoogleCalendarTransport`.
  - Before-State: `start_time: 2026-10-09T07:45:00+03:00`
  - Proposed State: `start_time: 2026-10-09T07:30:00+03:00`
  - After-State: `start_time: 2026-10-09T07:45:00+03:00` (100% identical; state completely unchanged)
- **Chronological Ordering**:
  - Strictly enforced and verified: `before_read.read_at` $\le$ `gate_decision.evaluated_at` $\le$ `after_read.read_at`.
  - Distinct instances and non-identical timestamps required (`before_read.read_at < after_read.read_at`).
  - Timezone awareness enforced across all timestamps (`read_at`, `observed_at`, `evaluated_at`).
  - Freshness contract enforced ($\le 24$h stale boundary).
- **External State Drift**: `0` (before-state observation strictly equals after-state observation).
- **Mission Lifecycle State Claim**: `READY` is **STRICTLY NOT CLAIMED** (`is_ready_claimed=False`).
- **Cost and Billing Reporting**:
  - Observed API spending during this task: `$0.00` (zero live API calls executed, zero paid capabilities invoked).
  - This observed task spending is strictly distinguished from unverified account-level billing claims or promotional credit balances.
- **Live vs Local Boundary**:
  - Deterministic execution gating, tracker verification, and receipt generation executed via `LOCAL_EXECUTION` / `FIXTURE`.
  - Live Google Calendar credentials are not cached in the environment; interactive `InstalledAppFlow` cannot run headlessly. The live read portion is faithfully reported as `NOT_RUN / BLOCKED (token not cached)`.
  - Zero live mutations were attempted or executed.

---

## 2. Core Invariant & Negative Proof Thesis

StillDone enforces the foundational invariant:

> **NO APPROVAL ≠ FAILED EXECUTION**
>
> An unapproved action is **NOT_RUN**. The provider mutation is never attempted. Provider mutation entry-point calls and write count are strictly **0**.

### 2.1 The Negative Proof
This task is NOT: "call Google Calendar update and expect Google API to reject it with 401 or 403."
The mutation call must **NEVER HAPPEN**.
The execution authority gate (`evaluate_execution_gate` / `execute_gated_action`) evaluates the frozen P-11.01 policy table:
1. `policy.requires_bound_approval == True`
2. `policy.permit_execution_without_grant == False`
3. `approval is None`
4. Result: Immediate fail-closed stop returning `ActionExecutionStatus.NOT_RUN` with `is_authorized=False`.
5. Router, handler, and transport write methods are **NEVER INVOKED** (call count == 0; verified by `CalendarMutationSpy` across all 3 entry points).
6. Tracker records `ActionExecutionStatus.NOT_RUN` without fabricating an execution attempt (`attempt=None`).
7. Result is strictly NOT mislabeled `FAILED`, `EXECUTION_FAILED`, `PARTIAL`, `SUCCESS`, or `READY`.

---

## 3. Consolidated Evidence-Integrity Repairs (Repairs A–E)

### Repair A / Defect 1 — Observation Chronology Enforcement
- **Ordering Constraint**: `create_unapproved_action_receipt()` and `scripts/p11_05_proof.py` strictly enforce:
  `before_read.read_at <= gate_decision.evaluated_at <= after_read.read_at`
- **Distinct Observations**: Rejects pre-gate after-reads, reversed reads (`before_read.read_at > after_read.read_at`), and same-operation reads (identical observation objects or identical timestamps).
- **Timezone Awareness**: Rejects naive datetimes across all timestamps (`read_at`, `observed_at`, `evaluated_at`).
- **Freshness**: Rejects before-reads older than 24 hours relative to gate evaluation.
- **Instrumented Proof**: Proof script explicitly performs two separate Calendar reads separated by the gate decision.
- **Regression Suite**: Automated regression tests verify that two reads taken before gate evaluation cannot produce a valid receipt.

### Repair B / Defect 3 — Mandatory Mutation Observation
- **Mandatory Explicit Observation**: Eliminated unverified defaults (`measured_provider_mutations=0`, `mutation_observation=None`). Receipts strictly require an explicit `ProviderMutationObservation`.
- **Counter Consistency**: Enforces `transport_writes <= transport_mutation_invocations` and rejects negative or boolean counters.
- **Runtime Instrumentation Truth**: Clearly documents that `ProviderMutationObservation` represents local process runtime instrumentation (`LOCAL_EXECUTION` / `FIXTURE`), not cryptographic hardware proof.
- **CalendarMutationSpy**: Captures method invocations across router, handler, transport, and completed writes. Accurately records method invocations that raise before completing writes (e.g., target error during `update_event`), which the receipt factory strictly rejects.
- **Adversarial Tests**: Comprehensive tests verify rejection of missing observations, non-observation types, conflicting counts, and non-zero invocations.

### Repair C / Defect 2 — Restored ApprovalLedger Public Boundary
- **Encapsulation Restored**: Completely eliminated private-member access (`_lock`, `_registry`, `_records`) from `gate.py` and proof scripts.
- **Minimal Read-Only Public API**: Added thread-safe public queries `has_consumed_approval_for_action(action_id)` and `get_consumed_records_for_action(action_id)` to both `UsedApprovalRegistry` and `ApprovalLedger`.
- **Identity Distinction**: Preserves strict separation between `PendingApprovalId` and `ApprovalId`.
- **Scoped Negative Proof**: Verifies that no approval has been consumed for the denied action in the ledger, while safely permitting unrelated historical approvals.
- **Durable History Consistency**: Verified that reloaded durable ledgers hydrated via `ApprovalLedger.from_ledger` reject consumed actions and allow unrelated actions.

### Repair D — Receipt Authority Consistency
- **Canonical Policy Binding**: `create_unapproved_action_receipt` enforces that `gate_decision.action_type == ActionType.CALENDAR_UPDATE` and `gate_decision.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED`, matching the frozen P-11.01 policy table.
- **Contradictory Decision Rejection**: Fails closed if gate decisions are manually constructed with mismatched authority classes (e.g. `READ_ONLY`, `REVERSIBLE_AUTO`), wrong action types (e.g. `TASK_CREATE`), or mismatched action/pending IDs.
- **Pending Approval Binding**: Rejects pending approvals with mismatched authority class, action type, target, or parameters.
- **Constructor Validation**: `UnapprovedActionReceipt` constructor enforces canonical action type and authority class directly.

### Repair E / Defect 5 — Complete Privacy and State Integrity
- **Raw Repr Elimination**: Removed `{val!r}` string formatting from `ProviderMutationObservation` exception messages, using type names only to prevent secret reflection.
- **Deep Key & Value Sanitization**: Sanitizes nested mappings, lists, tuples, and sets. Recursively validates that all mapping keys are strings; non-string keys fail closed with `ExecutionGateTypeError` without raw value or repr leakage.
- **Hostile Sentinel Immunity**: Tested hostile objects with malicious `__str__` and `__repr__` implementations as keys and values. Verified zero leakage in exception messages, exception causes (`from None`), and serialized JSON receipts.
- **Synchronous Exception Handling**: `execute_gated_action` marks tracker as `EXECUTION_FAILED` on synchronous exceptions, preventing misleading terminal-looking `IN_PROGRESS` states.

---

## 4. The 12-Step Proof Chain

The complete proof was verified deterministically via `scripts/p11_05_proof.py` and unit test suite `tests/test_phase_p11_05_calendar_update_not_run.py`:

| Step | Dimension | Verification Method | Outcome |
|:---|:---|:---|:---|
| **1** | Establish before-state | `GoogleCalendarReadAdapter.read_event` | `start_time: 2026-10-09T07:45:00+03:00`, `summary: 'Leave for school'`, `etag: 'etag_initial_1001'` |
| **2** | Construct canonical action | `ActionContract.create` | `CALENDAR_UPDATE` targeting `evt_leave_for_school_001` with proposed `07:30:00` start time |
| **3** | Authority classification | `get_action_authority_policy(ActionType.CALENDAR_UPDATE)` | `REVERSIBLE_APPROVAL_REQUIRED`, `requires_bound_approval=True`, `permit_execution_without_grant=False` |
| **4** | Produce PendingApproval | `create_pending_approval(validated_action)` | Deterministic content-addressed `PendingApprovalId` created; status is `PENDING` |
| **5** | Do NOT approve | Explicit parameter check | `approval=None`; no `ApprovalGrant` instance created or supplied |
| **6** | Do NOT consume grant | `ApprovalLedger` inspection | `approval_ledger` records for target `action_id` == `0`; `is_used(...) == False`, status == `UNUSED` |
| **7** | Submit candidate action | `execute_gated_action(action, router, tracker, approval=None)` | Routed through execution authority gate; stops before adapter router dispatch |
| **8** | Provider write prevented | `CalendarMutationSpy` assertion | Router calls == `0`, handler calls == `0`, transport calls == `0`, transport writes == `0` |
| **9** | Deterministic NOT_RUN | `ExecutionStateTracker.get_status(aid)` | Recorded as strictly `ActionExecutionStatus.NOT_RUN` (`is_authorized=False`, `attempt=None`) |
| **10** | Independent read-back | Separate `cal_read_adapter.read_event` | Read-back succeeds independently (`status == CalendarReadStatus.SUCCESS`); monotonic chronology verified |
| **11** | External state unchanged | Equality assertion on before/after states | `before_state == after_state` (`start_time: 07:45:00+03:00` preserved; not changed to proposed `07:30:00`) |
| **12** | Durable receipt created | `create_unapproved_action_receipt(...)` | Complete `UnapprovedActionReceipt` generated from observed facts with zero secrets |

---

## 5. Live vs Local Truth Boundary

- **Live Access Status**: `NOT_RUN / BLOCKED`
- **Reason**: Live Google Calendar OAuth tokens from P-06.08 were cleaned up after that task's run per Rule 14 (secrets are runtime-only; never committed to git). Interactive `InstalledAppFlow` requires browser interaction and cannot be run headlessly in CI/automated execution.
- **Reporting Truth**:
  - The live read portion is explicitly declared as `NOT_RUN / BLOCKED`.
  - Provenance for the test suite is strictly documented as `LOCAL_EXECUTION` / `FIXTURE`.
  - Zero live mutations were attempted or executed.

---

## 6. Checks Explicitly NOT_RUN

The following operations were explicitly **NOT_RUN** during Phase P-11.05:
1. **P-11.06 Approved Execution Path**: Strictly pending authorization (`NotImplementedError` enforced).
2. **Live Google Calendar Mutations**: Strictly 0 live writes performed (spend $0.00, 0 notifications, 0 attendee updates).
3. **Live Google Calendar Read Execution**: Blocked due to lack of cached OAuth token in runtime.
4. **Creation of Human ApprovalGrant**: Intentionally omitted to test the unapproved path.
5. **Retry Orchestrator Invocation**: Unapproved actions consume 0 retries and do not invoke retry logic.

---

## 7. Financial and Privacy Auditing

- **Observed Task API Spend**: `$0.00`
- **Paid Resources / Capabilities Invoked**: `0`
- **Account-Level Billing**: Unverified / not observed by this runtime (distinguished from observed $0.00 task spend).
- **Secrets / Tokens in Git / Evidence**: Strictly `0` (sanitized IDs, zero OAuth secrets, zero credentials logged).
