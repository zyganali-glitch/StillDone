# Architecture & Patterns Memory — StillDone

## Frozen patterns

### Execute/verify separation
Executor returns execution facts.
Verifier performs fresh read-back.
Predicate evaluator computes verification.

### Desired-state contract
Mission success is derived from required predicates, not checklist prose.

### Provider-neutral domain
Core contracts must not depend on AWS/Google SDK classes.

### Bounded model output
Model output must conform to a strict typed schema and supported action vocabulary.

### Drift
Previous verified state is historical.
Reconciliation produces current mission truth.

### Dedicated demo resources
Use isolated demo calendar/task list.

### Ports/adapters
Provider-specific APIs stay behind adapters.

### Honest mode/provenance
No live adapter may silently substitute fixture output.
