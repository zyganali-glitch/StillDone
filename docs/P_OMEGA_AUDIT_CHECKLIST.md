# P-Ω Integrity Checklist

Run focused checks continuously and broader checks at defined phase boundaries.

## Canonical state
- [ ] remote `main` inspected
- [ ] starting SHA recorded
- [ ] final SHA pushed and re-checked
- [ ] HANDOFF last verified baseline accurate
- [ ] active exact task matches Master Plan

## Scope
- [ ] no future-phase leakage
- [ ] exact task title unchanged
- [ ] changed files are in-scope
- [ ] no unrelated refactor

## Evidence
- [ ] no `NOT_RUN` presented as PASS
- [ ] no fixture presented as live
- [ ] no recorded live presented as current live
- [ ] execute response not used as verification
- [ ] required read-back call actually occurred
- [ ] deterministic predicate result preserved
- [ ] drift/freshness semantics correct

## AWS / competition
- [ ] required technology actually called
- [ ] current official rules still align
- [ ] AWS service/model/runtime identity verified
- [ ] no unverified preview feature claimed

## Security/privacy
- [ ] no secrets committed
- [ ] no tokens in logs/evidence/screenshots
- [ ] demo resources contain no unrelated personal content
- [ ] public endpoint budget bounded
- [ ] OAuth scopes minimal

## Cost
- [ ] zero-personal-spend boundary preserved
- [ ] promo/free balance checked when required
- [ ] no paid fallback enabled
- [ ] no quota increase requiring billing enabled accidentally

## Donors/licensing
- [ ] donor class recorded
- [ ] any reused code has immutable pin/license/provenance
- [ ] no donor terminology leakage
- [ ] Apache-2.0 remains present for public repo

## Tests
- [ ] focused tests run
- [ ] assertions not weakened
- [ ] required negative paths tested
- [ ] full suite run at planned closure gate

## Judge truth
- [ ] README matches implemented reality
- [ ] live/recorded/simulated surfaces clearly labeled
- [ ] demo claim has named evidence
- [ ] friction log contains only observed facts
