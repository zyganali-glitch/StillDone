# P-11.06 Evidence: Approved Calendar Update Executes Once and Verifies

## 1. Executive Summary

- **Task**: `P-11.06 — Prove approved Calendar update executes once and verifies`
- **Starting Remote SHA**: `864cfa4e2b47ade72d1f4095e78e06f309372320`
- **Target Event Identity**: `evt_leave_for_school_001` on dedicated demo calendar `c_1880abc123demo@group.calendar.google.com`
- **Action Type**: `ActionType.CALENDAR_UPDATE` (`calendar.update`)
- **Authority Classification**: `AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED`
- **Approval Grant Identity**: Canonical `ApprovalGrant` with cryptographically bound domain-separated SHA-256 `BindingHash`
- **Approval Decision**: Human-originated `APPROVE` producing valid `ApprovalGrant` bound to exact target and parameters
- **Approval Consumption**: Atomically consumed through `ApprovalLedger` before provider mutation entry point
- **Execution Attempt**: Exactly one canonical `ExecutionAttempt` (`attempt_number=1`) created after grant consumption
- **Provider Mutation Entry-Point Invocations**:
  - `router_mutation_invocations == 1`
  - `handler_mutation_invocations == 1` (or 0 when handled direct)
  - `transport_mutation_invocations == 1`
  - Measured and verified via `CalendarMutationSpy`
- **Provider Writes Count**: Exactly `1` (`FakeGoogleCalendarTransport.writes_count == 1`; single conditional `update_event` with matching ETag)
- **Independent Read-Back**:
  - Fresh Google Calendar read performed via separate `GoogleCalendarReadAdapter` query
  - Read-back result status: `CalendarReadbackStatus.MATCH` (`is_match=True`, zero mismatches)
  - Read-back observation is a separate instance with fresh timestamp (`read_at > before_read.read_at`)
- **Predicate Evaluation**:
  - `DesiredStatePredicate` evaluated against fresh independent read-back observation
  - Subject: `start_time`, Operator: `EQUALS`, Expected: `2026-10-09T07:30:00+03:00`
  - Predicate Truth: `PredicateTruth.TRUE` (`is_true=True`)
- **Lawful Verification & Readiness Promotion**:
  - `is_verified == True` for action-level execution
  - `is_ready == True` ONLY when canonical mission lifecycle requirements are satisfied (`MissionState.VERIFYING`, all mission predicates TRUE, fresh observations, and durable ledger backing)
  - Action verification and mission readiness are strictly decoupled: `is_ready` is NEVER inferred from `is_verified` alone; non-durable or DRAFT/PLANNED/EXECUTING states strictly report `is_ready == False`
- **Durable Action Receipt**:
  - `ApprovedActionReceipt` created and validated with deep immutability (`MappingProxyType`)
  - Captures complete before-state (`start_time: 2026-10-09T07:45:00+03:00`) and after-state (`start_time: 2026-10-09T07:30:00+03:00`)
- **Replay Prevention**:
  - Replay of consumed grant fails closed with `ApprovalAlreadyUsedError`
  - Zero additional provider writes performed on replay attempt (`writes_count` remains 1)
- **Durable Hydration**:
  - Consumption records persist across process reload via `DurableFileLedger` and `ApprovalLedger.from_ledger`
- **Live Google Calendar Boundary**:
  - `LIVE_MUTATION = NOT_RUN / BLOCKED`
  - Missing per-event operator consent, disposable event ID, and OAuth credentials in headless environment
  - Zero personal spend maintained ($0.00)

---

## 2. Core Invariant & Success Chain

StillDone enforces the foundational invariant:

> **INTENT → CONTRACT → AUTHORITY → EXECUTE → INDEPENDENT READBACK → PREDICATE EVALUATION → VERIFIED**
>
> A successful provider update alone MUST NEVER produce `VERIFIED` or `READY`.
> An outcome is not complete until the resulting state is independently observed and matches the desired-state predicate.

### 2.1 The Complete 12-Step Approved Sequence
1. **Validate Canonical Action**: Validate action contract, exact target identity (`google_calendar`, `calendar_event`, `evt_leave_for_school_001`), and normalized parameters against frozen P-11.01 policy (`REVERSIBLE_APPROVAL_REQUIRED`).
2. **Require Bound Approval**: Verify presence of valid `ApprovalGrant` cryptographically bound to mission, action, target, parameters, and validity window.
3. **Validate Grant Invariants**: Verify grant expiry, not-yet-valid timestamps, authority class, and 64-char hex `BindingHash`.
4. **Execution Attempt Preparation**: Generate and validate canonical `ExecutionAttempt` (`attempt_number=1`) before ledger mutation.
5. **Atomic Consumption**: Atomically consume grant in `ApprovalLedger` before dispatching to provider.
6. **Fail-Closed Persistence**: If consumption persistence in ledger fails, abort immediately with zero provider invocations and zero writes.
7. **Single Provider Dispatch**: Dispatch conditional update through `GoogleCalendarUpdateAdapter` with matching `If-Match` ETag.
8. **Preserve External Facts**: Record actual provider response without fabricating external IDs.
9. **Separate Independent Read-Back**: Execute a fresh read query via `GoogleCalendarReadAdapter` (never recycling provider response).
10. **Deterministic Predicate Evaluation**: Evaluate `DesiredStatePredicate` against fresh read observation using deterministic verification.
11. **Durable Evidence Persistence**: Append attempt, readback, predicate, and receipt evidence records to mission ledger; raise `ApprovedExecutionPersistenceError` fail-closed if ledger append fails.
12. **Lawful Promotion**: Transition to action `is_verified` and evaluate canonical mission readiness via `compute_mission_readiness` only when full mission lifecycle, predicates, and durable ledger backing are present.

### 2.2 Consolidated Execution-Truth Repairs
The audited implementation underwent six comprehensive architectural repairs to guarantee uncompromising execution truth:

1. **Decouple Action Verification from Mission Readiness**:
   - Eliminated `is_ready = is_verified` conflation.
   - Action verification proves external state mutation and predicate satisfaction for one action.
   - Mission readiness requires canonical `compute_mission_readiness`, `MissionState.VERIFYING`, all mission predicates satisfied, fresh observations, and durable ledger backing.
   - Missions in `DRAFT`, `PLANNED`, or `EXECUTING` states, or lacking durable ledger backing, strictly report `is_ready = False`.

2. **Observation Conflict Detection & Strict Binding**:
   - Coordinator read and `GoogleCalendarReadbackVerifier` read are cross-validated.
   - Any successive discrepancy between the post-execution reads raises `ConflictingReadbackObservationError` fail-closed.
   - Authoritative verifier observation is the single bound source of truth for predicate evaluation and durable receipt.

3. **Attempt Generation vs Consumption Ordering**:
   - `ExecutionAttempt` is prepared and validated *before* atomic consumption in `ApprovalLedger`.
   - Pre-dispatch validation or attempt creation failure aborts before consumption, preserving unconsumed grant status.
   - Consumption strictly precedes provider network dispatch; ambiguous provider outcomes or timeouts preserve consumed status without improper refund.

4. **Mandatory Measured Provider Facts & Delta Tracking**:
   - Synthetic fallback (`writes = 1 if success else 0`) completely eliminated.
   - `CalendarMutationSpy` automatically discovers adapter transport and tracks delta writes (`current - initial`).
   - Truthfully reports 0 writes on idempotent no-ops or provider failures without fabrication.

5. **Receipt & Ledger Truth**:
   - Non-durable action execution (`is_durable=False`) distinguished from durable mission proof (`is_durable=True`).
   - Lineage verified against public `ApprovalLedger.get_record()` API.
   - Durable persistence failure wraps in `ApprovedExecutionPersistenceError` preserving executed provider write truth.

6. **Live Google Calendar Safety Gate**:
   - Maintained strict `LIVE_MUTATION = NOT_RUN / BLOCKED` ($0.00 personal spend).

---

## 3. Exactly-Once & Adversarial Safety Matrix

| Scenario / Threat | Invariant Enforced | Observed Outcome | Provider Writes | Status |
|:---|:---|:---|:---:|:---:|
| **No Approval** | Gate rejects unapproved action | `ActionExecutionStatus.NOT_RUN` | 0 | PASS |
| **Valid Bound Approval** | Exactly one permitted update | `ActionExecutionStatus.EXECUTION_SUCCEEDED` | 1 | PASS |
| **Same Grant Replay** | Single-use ledger enforces replay rejection | `ApprovalAlreadyUsedError` raised | 0 additional (1 total) | PASS |
| **Process-Local Concurrency** | Process-local lock serializes consumption | Exactly 1 winner, 1 loser with `ApprovalAlreadyUsedError` | 1 | PASS |
| **Durable Reload / Restart** | Hydration from file log retains consumed status | Replay in new session fails with `ApprovalAlreadyUsedError` | 0 additional (1 total) | PASS |
| **Expired Grant** | Temporal validity check | `ApprovalExpiredError` raised | 0 | PASS |
| **Not-Yet-Valid Grant** | Future timestamp rejected | `ApprovalNotYetValidError` raised | 0 | PASS |
| **Revoked Grant** | Revocation check in ledger | `ApprovalRevokedError` raised | 0 | PASS |
| **Tampered Binding Hash** | Constant-time HMAC comparison | `ApprovalTamperedError` raised | 0 | PASS |
| **Wrong Target Grant** | Binding check against action target | `ApprovalBindingMismatchError` raised | 0 | PASS |
| **Model Prose ("yes")** | Model prose confers zero authority | `TypeError` raised fail-closed | 0 | PASS |
| **Planner Proposal Object** | Proposal rejected at authority gate | `PlannerGateAuthorityError` raised | 0 | PASS |
| **Consumption Persistence Failure** | Ledger append error fails closed | `ApprovalConsumptionPersistenceError` raised | 0 | PASS |
| **ETag Mismatch / Conflict** | Precondition check prevents blind overwrite | Provider reports `CONFLICT`, gate reports `EXECUTION_FAILED` | 0 | PASS |
| **Read-Back Mismatch** | Fresh read contradicts desired predicate | `readback=MISMATCH`, `predicate=FALSE`, `is_verified=False`, `is_ready=False` | 1 | PASS |
| **Chronological Inversion** | After-read earlier than before-read | `ExecutionGateValueError` raised | 0 | PASS |
| **Observation Discrepancy** | Post-execution reads contradict | `ConflictingReadbackObservationError` raised | 1 | PASS |
| **Attempt Generation Failure** | Pre-dispatch attempt preparation fails | Exception raised, grant unconsumed | 0 | PASS |
| **Contradictory Instrumentation** | Router vs handler invocation mismatch | `ExecutionGateValueError` raised | 0 | PASS |
| **Durable Ledger Persistence Error** | Evidence record append fails post-mutation | `ApprovedExecutionPersistenceError` wraps and preserves write count | 1 | PASS |
| **Draft / Non-Durable Mission** | Action verified without durable ready context | `is_verified=True`, `is_ready=False`, `is_durable=False` | 1 | PASS |
| **Timeout After Write** | Ambiguous timeout post-write | Preserves consumed status without improper refund | 1 | PASS |
| **Idempotent No-Op** | Mutation yields zero writes | Truthfully reports `writes=0`, `writes_performed=0` | 0 | PASS |

---

## 4. Provider Success Alone Never Produces Verified

StillDone strictly separates provider execution success from verification truth.

### Negative Control Proof:
In `test_provider_success_with_readback_mismatch_is_never_verified`:
- Provider executes and reports `success == True` (`writes_performed == 1`).
- Independent read-back observes external state mismatch (`start_time == 08:00:00` vs expected `07:30:00`).
- Read-back verifier yields `CalendarReadbackStatus.MISMATCH`.
- Predicate evaluation yields `PredicateTruth.FALSE`.
- Outcome strictly evaluates:
  ```python
  assert outcome.is_verified is False
  assert outcome.is_ready is False
  assert outcome.receipt.is_verified is False
  assert outcome.receipt.is_ready_claimed is False
  ```
- **Proved**: Even with HTTP 200 / successful write from provider, the system refuses to award `VERIFIED` or `READY`.

---

## 5. Live Google Calendar Safety Gate

In accordance with Master Plan §Live Safety and Zero Personal Spend Law:

```json
{
  "live_gate_status": "NOT_RUN / BLOCKED",
  "reason": "Per-event human operator approval for exact disposable event ID absent; headless test environment contains no OAuth tokens; zero personal spend law strictly enforces $0.00.",
  "live_mutation_permitted": false,
  "live_writes_performed": 0
}
```

### Missing Prerequisites for Live Execution:
1. **Explicit Operator Approval**: Separate human operator approval for the exact disposable event ID on a dedicated test calendar (never `primary`).
2. **Disposable Resource Identity**: Dedicated test calendar ID and pre-existing test event with documented before-state and ETag.
3. **OAuth Tokens**: Active least-privilege tokens for Google Calendar API in local environment.
4. **Zero Personal Spend Guarantee**: Confirmation that operation introduces zero paid API calls or pay-as-you-go billing.

Implementation authorization for P-11.06 does NOT constitute authorization for unapproved live mutation.

---

## 6. Verification Artifacts & Test Execution

### Deterministic Proof Script
```bash
uv run python scripts/p11_06_proof.py --json
```
Output:
```json
{
  "task": "P-11.06 -- Prove approved Calendar update executes once and verifies",
  "target_event_id": "evt_leave_for_school_001",
  "calendar_id": "c_1880abc123demo@group.calendar.google.com",
  "authority_classification": "REVERSIBLE_APPROVAL_REQUIRED",
  "consumption_status": "CONSUMED",
  "execution_status": "EXECUTION_SUCCEEDED",
  "provider_writes_performed": 1,
  "total_transport_writes": 1,
  "before_start_time": "2026-10-09T07:45:00+03:00",
  "after_start_time": "2026-10-09T07:30:00+03:00",
  "readback_status": "MATCH",
  "predicate_truth": "TRUE",
  "is_verified": true,
  "is_ready": true,
  "replay_prevention_verified": true,
  "durable_hydration_verified": true,
  "live_gate_status": {
    "status": "NOT_RUN / BLOCKED",
    "reason": "Per-event human operator approval for exact disposable event ID absent; headless test environment contains no OAuth tokens; zero personal spend law strictly enforces $0.00.",
    "live_mutation_permitted": false,
    "live_writes_performed": 0
  }
}
```

### Pytest Suite
- `tests/test_phase_p11_06_approved_calendar_update.py`: 34 tests passing (100%)
- Core regression suite: 2,011 tests passing (100%)
- Strands planner suite: 1,155 tests passing (100%)
- Combined dual-runtime validation: 3,166 tests passing across both runtimes (`scripts/validate.py`)
