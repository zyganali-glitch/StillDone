# Security & Privacy Boundary

## Protected assets

- AWS credentials and promotional budget
- Google OAuth client secrets/tokens
- calendar IDs and private event details
- task list IDs and private task details
- approval intent
- mission-state integrity
- evidence-state integrity
- external resource identifiers
- public judge endpoint budget

## Main threats

| Threat | Control |
|---|---|
| Hallucinated completion | execute ≠ verify, independent read-back, deterministic predicates |
| Duplicate action after timeout | idempotency/dedup contract + read-before-retry where appropriate |
| Approval replay | approval hash binds mission/action/params/target/expiry |
| Stale success | freshness contract + reconciliation + `DRIFTED` |
| Fixture presented as live | explicit provenance and visible mode labels |
| Secret leakage | environment/secret store only; redaction tests; no durable prompt secrets |
| Personal calendar disclosure | dedicated demo calendar; bounded queries; sanitized evidence |
| Public endpoint credit drain | auth/rate limit/budget kill switch; read-only static exhibit preferred |
| Model proposes unsupported action | allowlisted typed action schema; compiler rejection |
| Model overwrites facts | deterministic state store final authority |
| OAuth overreach | least privilege scopes; dedicated demo resources |
| Provider error hides partial failure | per-step states; no all-or-nothing narrative |
| External drift after success | fresh reconciliation; current truth outranks receipt |

## OAuth rule

Use the narrowest feasible scopes.

Do not request Gmail scopes in the core unless the product contract later requires them.

Calendar and Tasks integration must be isolated to the demo resources where provider capabilities permit.

## Evidence sanitation

Public evidence must not contain:
- refresh/access tokens;
- client secrets;
- AWS keys;
- personal email addresses;
- unrelated calendar event titles;
- unrelated task contents;
- full OAuth callback URLs containing secrets/codes;
- private account IDs.

## Human authority

The demo may safely auto-execute creation of a new reversible demo task.

Modification of an existing calendar commitment is initially classified as `REVERSIBLE_APPROVAL_REQUIRED`.

This demonstrates approval compression without sending email, spending money, or creating safety-critical consequences.

## Out of scope

StillDone is not:
- an emergency response system;
- a medical device;
- a financial transaction agent;
- a security certification;
- a guarantee that third-party providers themselves are correct.
