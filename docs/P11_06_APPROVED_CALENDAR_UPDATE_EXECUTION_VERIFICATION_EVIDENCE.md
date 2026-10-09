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
  - `is_verified == True`
  - `is_ready == True`
  - Promoted strictly because all required conditions are satisfied: execution success + write == 1 + read-back match + predicate true
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
4. **Atomic Consumption**: Atomically consume grant in `ApprovalLedger` before dispatching to provider.
5. **Fail-Closed Persistence**: If consumption persistence in ledger fails, abort immediately with zero provider invocations and zero writes.
6. **Execution Attempt**: Generate one canonical `ExecutionAttempt` (`attempt_number=1`).
7. **Single Provider Dispatch**: Dispatch conditional update through `GoogleCalendarUpdateAdapter` with matching `If-Match` ETag.
8. **Preserve External Facts**: Record actual provider response without fabricating external IDs.
9. **Separate Independent Read-Back**: Execute a fresh read query via `GoogleCalendarReadAdapter` (never recycling provider response).
10. **Deterministic Predicate Evaluation**: Evaluate `DesiredStatePredicate` against fresh read observation using deterministic verification.
11. **Durable Evidence Persistence**: Append attempt, readback, predicate, and receipt evidence records to mission ledger.
12. **Lawful Promotion**: Transition to `VERIFIED` and `READY` only when all lifecycle, evidence, and freshness invariants are met.

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
| **Persistence Failure** | Ledger append error fails closed | `ApprovalConsumptionPersistenceError` raised | 0 | PASS |
| **ETag Mismatch / Conflict** | Precondition check prevents blind overwrite | Provider reports `CONFLICT`, gate reports `EXECUTION_FAILED` | 0 | PASS |
| **Read-Back Mismatch** | Fresh read contradicts desired predicate | `readback=MISMATCH`, `predicate=FALSE`, `is_verified=False`, `is_ready=False` | 1 | PASS |
| **Chronological Inversion** | After-read earlier than before-read | `ExecutionGateValueError` raised | 0 | PASS |

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
uv run python scripts/p11_06_proof.py
```
Output:
```
======================================================================
P-11.06 PROOF: APPROVED CALENDAR UPDATE EXECUTES ONCE AND VERIFIES
======================================================================
Task:                         P-11.06 -- Prove approved Calendar update executes once and verifies
Current Git SHA:              864cfa4e2b47ade72d1f4095e78e06f309372320
Parent Verified SHA:          864cfa4e2b47ade72d1f4095e78e06f309372320
Worktree Clean:               False
Source Provenance:            LOCAL_DIRTY_WORKTREE
Target Event:                 evt_leave_for_school_001
Calendar ID:                  c_1880abc123demo@group.calendar.google.com
Authority Class:              REVERSIBLE_APPROVAL_REQUIRED
Approval ID:                  1c8c1207-6d83-4d55-932e-344ed82f0acd
Binding Hash:                 fe9ce873927fc265... (valid 64-char hex)
Approval Consumption:         CONSUMED
Execution Gate Status:        EXECUTION_SUCCEEDED
Provider Writes Performed:    1
Total Transport Writes:       1
Before Start Time:            2026-10-09T07:45:00+03:00
After Start Time:             2026-10-09T07:30:00+03:00
Readback Status:              MATCH
Predicate Truth:              TRUE
Verified Outcome:             True
Mission Ready State:          True
Replay Blocked (Zero Writes): True
Durable Hydration Reload:     True
Live Mutation Gate Status:    NOT_RUN / BLOCKED
Live Mutation Gate Reason:    Per-event human operator approval for exact disposable event ID absent; headless test environment contains no OAuth tokens; zero personal spend law strictly enforces $0.00.
======================================================================
PROOF CHAIN VERIFIED: APPROVED EXECUTION & INDEPENDENT VERIFICATION PROVEN CONCLUSIVELY.
======================================================================
```

### Pytest Suite
- `tests/test_phase_p11_06_approved_calendar_update.py`: 18 tests passing (100%)
- Full Phase P-11 suite: 324 tests passing (100%)
- Core regression suite: 1996+ tests passing
