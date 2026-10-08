# P-11.05 Evidence: Calendar Existing-Event Update Remains NOT_RUN Before Approval

## 1. Executive Summary

- **Task**: `P-11.05 — Prove Calendar existing-event update remains NOT_RUN before approval`
- **Execution Mode**: `Independent-QA-directed surgical repair` (Repairs A through E)
- **Execution Timestamp**: `2026-10-08T20:40:00+00:00` (UTC)
- **Last Independently Verified Remote SHA**: `4ec4475f006207ec5840880bb9476f6d169442cd`
- **Audited P-11.05 Implementation SHA**: `12b42e4f0f92a08518b1e6efe4fd030912477bc9`
- **Target Event Identity**: `evt_leave_for_school_001` on dedicated demo calendar `c_1880abc123demo@group.calendar.google.com`
- **Action Type**: `ActionType.CALENDAR_UPDATE` (`calendar.update`)
- **Authority Classification**: `AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED`
- **Pending Approval ID**: Content-addressed SHA-256 (`PendingApprovalId`)
- **Approval Decision Status**: `PendingApprovalStatus.PENDING` (`is_approved=False`)
- **Approval Grant Present**: `False` (zero grant created or submitted)
- **Approval Consumed**: `False` (`ApprovalLedger` and `UsedApprovalRegistry` records == 0)
- **Provider Mutation Call Count**: `0` (`FakeGoogleCalendarTransport.writes_count == 0`; zero HTTP `PUT`/`PATCH`/`POST` calls)
- **Deterministic Execution State**: `ActionExecutionStatus.NOT_RUN`
- **Before-State Start Time**: `2026-10-09T07:45:00+03:00`
- **Proposed Start Time**: `2026-10-09T07:30:00+03:00`
- **After-State Start Time**: `2026-10-09T07:45:00+03:00` (100% identical; state completely unchanged)
- **External State Drift**: `0` (before-state observation strictly equals after-state observation)
- **Mission Lifecycle State Claim**: `READY` is **STRICTLY NOT CLAIMED** (`is_ready_claimed=False`)
- **Live vs Local Boundary**:
  - Deterministic execution gating, tracker verification, and receipt generation executed via `LOCAL_EXECUTION` / `FIXTURE`.
  - Live Google Calendar credentials are not cached in the environment; interactive `InstalledAppFlow` cannot run headlessly. The live read portion is faithfully reported as `NOT_RUN / BLOCKED (token not cached)`.
  - Zero live mutations were attempted or executed.

---

## 2. Core Invariant & Negative Proof Thesis

StillDone enforces the foundational invariant:

> **NO APPROVAL ≠ FAILED EXECUTION**
>
> An unapproved action is **NOT_RUN**. The provider mutation is never attempted. Provider mutation call count is strictly **0**.

### 2.1 The Negative Proof
This task is NOT: "call Google Calendar update and expect Google API to reject it with 401 or 403."
The mutation call must **NEVER HAPPEN**.
The execution authority gate (`evaluate_execution_gate` / `execute_gated_action`) evaluates the frozen P-11.01 policy table:
1. `policy.requires_bound_approval == True`
2. `policy.permit_execution_without_grant == False`
3. `approval is None`
4. Result: Immediate fail-closed stop returning `ActionExecutionStatus.NOT_RUN` with `is_authorized=False`.
5. Router and adapter write methods are **NEVER INVOKED** (call count == 0; verified by spies on router, handler, and transport).
6. Tracker records `ActionExecutionStatus.NOT_RUN` without fabricating an execution attempt (`attempt=None`).
7. Result is strictly NOT mislabeled `FAILED`, `EXECUTION_FAILED`, `PARTIAL`, `SUCCESS`, or `READY`.

---

## 3. Consolidated Same-Scope Repairs (Repairs A–E)

### Repair A — Privacy-Safe Rejection
- Raw string/repr reflection of arbitrary action or approval inputs in exceptions eliminated.
- Rejection messages are static, bounded, and privacy-safe:
  - `"String or conversational prose cannot act as authority gate action; must be a canonical ActionContract or ValidatedActionContract"`
  - `"String prose cannot act as an ApprovalGrant; model/conversational text has ZERO authority"`
- Exceptions raised using `from None` to prevent leaking sensitive values via `__cause__`, `__context__`, or chained tracebacks.
- Hostile custom objects with secrets in `__repr__` and `__str__` rejected safely, displaying only `type(obj).__name__`.

### Repair B — Correct Authority and State Boundaries
- `PendingApproval` validated against complete exact action binding: `action_id`, `mission_id`, `action_type`, `authority_class`, `target`, `parameters`, `parameters_digest`, and `pending_approval_id`.
- Mismatched pending approvals rejected without exposing sensitive target or parameter contents.
- Unexpected `ApprovalGrant` on actions not requiring approval (e.g. `CALENDAR_READ`) rejected with `UnexpectedApprovalGrantError` before tracker or attempt generation is touched.
- Premature `IN_PROGRESS` transitions prevented by generating `ExecutionAttempt` before updating tracker state.
- Spies verify router, handler, and transport receive strictly 0 mutation calls.

### Repair C — Evidence Derived From Observed Facts
- `create_unapproved_action_receipt` binds facts directly to `ExecutionGateDecision`, canonical `action`, `PendingApproval`, and real `CalendarReadResult` observations.
- Rejects loose unverified dictionaries. Requires `CalendarReadStatus.SUCCESS` with non-None observations targeting the exact event.
- Verifies external event state did not mutate to the proposed parameters.
- Provider mutation invocations verified from actual measured instrumentation (`writes_count == 0`).
- Receipts are deeply frozen (`MappingProxyType`, `tuple`, `frozenset`) against post-creation mutation.
- `to_dict()` sanitizes strings recursively with `redact_text`.
- False claims of `LIVE_*` provenance rejected fail-closed.

### Repair D — Trustworthy Proof Execution and Source Provenance
- `scripts/p11_05_proof.py` replaced all bare `assert`s with `ProofVerificationError` runtime checks effective under `python -O`.
- Fails closed if Git SHA cannot be established (no `UNKNOWN_SHA` fallback).
- Tracks worktree cleanliness and distinguishes `COMMITTED_SOURCE` from `LOCAL_DIRTY_WORKTREE`.
- Supports `--expected-sha` argument for post-commit CI verification.

### Repair E — Adversarial Proof Strengthening
- Expanded test suite from 15 to 34 automated unit & adversarial tests in `tests/test_phase_p11_05_calendar_update_not_run.py`.

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
| **6** | Do NOT consume grant | `ApprovalLedger` inspection | `approval_ledger.is_used(...) == False`, `is_consumed(...) == False`, status == `UNUSED` |
| **7** | Submit candidate action | `execute_gated_action(action, router, tracker, approval=None)` | Routed through execution authority gate; stops before adapter router dispatch |
| **8** | Provider write prevented | `cal_transport.writes_count` assertion | Writes count == `0` (before count: 0, after count: 0; spy verified) |
| **9** | Deterministic NOT_RUN | `ExecutionStateTracker.get_status(aid)` | Recorded as strictly `ActionExecutionStatus.NOT_RUN` (`is_authorized=False`) |
| **10** | Independent read-back | Separate `cal_read_adapter.read_event` | Read-back succeeds independently (`status == CalendarReadStatus.SUCCESS`) |
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

- **Personal Spend**: `$0.00`
- **Paid Resources / APIs**: `0`
- **Secrets / Tokens in Git / Evidence**: Strictly `0` (sanitized IDs, zero OAuth secrets, zero credentials logged)
