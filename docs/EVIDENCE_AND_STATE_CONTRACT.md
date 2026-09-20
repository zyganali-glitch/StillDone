# Evidence & State Contract

## 1. Non-negotiable invariant

A real mutation is not `VERIFIED` merely because its execute call returned success.

For mutable steps:

`EXECUTE → READBACK → PREDICATE`

All three are required.

## 2. Independent read-back definition

Independent read-back means:
- a separate provider/API operation after execution;
- source-of-truth retrieval by resource ID or bounded query;
- no reuse of the executor's success payload as proof;
- no model-generated “confirmation” as proof.

Where provider semantics permit, the verifier should use a separate adapter method and fresh network call.

## 3. Result states

### `NOT_RUN`
Action/check did not execute.

### `EXECUTED_UNVERIFIED`
The action call completed or may have completed, but required resulting state has not yet been independently proven.

### `VERIFIED`
Fresh independent observation satisfies the expected predicate.

### `CONTRADICTED`
Fresh independent observation exists and does not satisfy the expected predicate.

### `BLOCKED`
Policy/authority prevented execution. Execution remains `NOT_RUN`.

### `FAILED`
A named attempted operation failed.

### `STALE`
Evidence existed but exceeded its freshness contract.

### `DRIFTED`
A mission/step that had been verified no longer satisfies required current predicates.

## 4. Provenance

- `FIXTURE`
- `LOCAL_EXECUTION`
- `LIVE_AWS`
- `LIVE_GOOGLE`
- `LIVE_EXTERNAL`
- `RECORDED_LIVE`

Provenance is not a verdict.

Examples:
- `LIVE_GOOGLE + FAILED`
- `LIVE_GOOGLE + VERIFIED`
- `RECORDED_LIVE + VERIFIED_AT_CAPTURE_TIME`
- `FIXTURE + VERIFIED`

Only the provenance required by the active task can close that task.

## 5. Mission readiness

A mission may be `READY` only when:
- every required predicate is currently satisfied;
- every required observation is within freshness bounds;
- no required action is `BLOCKED`, `FAILED`, `CONTRADICTED`, `STALE`, or `NOT_RUN`;
- approval-required actions were bound to valid approval;
- the mission contract itself is valid.

Optional steps may remain incomplete if the contract marks them optional and the UI shows them honestly.

## 6. Reconciliation

Reconciliation re-evaluates current system-of-record state.

It must:
1. load the immutable mission contract;
2. perform fresh observations required by the contract;
3. evaluate deterministic predicates;
4. compare with previous verified state;
5. emit drift facts;
6. downgrade status where required.

Historical success cannot suppress drift.

## 7. Idempotency evidence

For mutations, evidence should bind:
- mission ID;
- action ID;
- idempotency key;
- target resource;
- execute attempt(s);
- provider response metadata;
- read-back call;
- predicate outcome.

A lost HTTP response must not justify blind duplicate creation.

## 8. Receipt

A mission receipt is a compact projection of the evidence ledger.

It is not the source of truth.

Recommended judge-visible fields:
- mission ID;
- current mission state;
- verified count;
- blocked count;
- failed count;
- not-run count;
- drift count;
- last reconciliation timestamp;
- provider provenance badges;
- expandable evidence IDs.

## 9. Tamper resistance

At minimum:
- canonical serialization;
- SHA-256 content hashes;
- immutable evidence IDs;
- exact mission-contract hash;
- exact action hash;
- exact approval hash where applicable.

Cryptographic signing is optional unless later architecture justifies it. Do not add signatures as decoration.
