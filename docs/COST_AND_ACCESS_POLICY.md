# Cost & Access Policy

Snapshot date: `2026-09-20`

## Principle

StillDone must have a credible zero-personal-spend development and judging path.

Target:
`$0.00 personal spend`

## Competition AWS credits

The hackathon official rules and resources pages state that registered participants can request `$150` in AWS Promotional Credits while building, while supplies last.

Official sources:
- Resources: https://amazonappdev2026.devpost.com/resources
- Official Rules: https://amazonappdev2026.devpost.com/rules
- Credit Request Form: https://forms.gle/GaHFxSbBQNG9Kti6A
- Request Deadline: Wednesday, October 21, 2026 at 12:00 PM PT
- Credit Terms: https://aws.amazon.com/awscredits/

### Operator Credit Request Status (as of 2026-09-20)

- **Submission**: Successfully submitted on 2026-09-20 via official Google Form (`https://forms.gle/GaHFxSbBQNG9Kti6A`).
- **Confirmation**: Google Form displayed confirmation message "Yanıtınız kaydedildi."
- **Processing Window**: Official form states credit processing may take up to 5 business days.
- **Current Operational Truth**: Processing is pending. Credit availability is NOT yet observed or proven in an AWS account.
- **P-01.01 Observation Outcome**: Verified on 2026-09-20. No authenticated AWS session or credentials configured in environment. Credit presence remains `NOT_OBSERVABLE`. Spend decision is `BLOCKED_ZERO_SPEND`. Next live task P-01.02 remains blocked until credit arrival is verified in the AWS console.
- **Binding Policy**: Do NOT submit another credit request. Do NOT enable pay-as-you-go, credit card billing, paid quotas, or auto-fallback. Personal-spend exposure remains `$0.00`.

Official rules explicit warning:
> “Additional charges incurred by the Entrant for the use of AWS products are the responsibility of the Entrant. Entrants are encouraged to monitor their usage of services so as to not incur additional charges.”

This does NOT mean:
- all AWS services are free;
- credits hard-stop automatically;
- post-credit usage cannot bill;
- credits necessarily last through judging.

P-01 verification status:
- actual account credit balance: `NOT_OBSERVABLE` (pending disbursement);
- expiry: `NOT_OBSERVABLE`;
- billing behavior: AWS Budgets updates asynchronously every 8–12 hours, not a hard real-time cap;
- service availability: candidate region `us-east-1` selected; Bedrock control plane blocked without credentials;
- safety decision: `BLOCKED_ZERO_SPEND`;
- practical kill switch / budget strategy: documented in `docs/P01_LIVE_FEASIBILITY.md`.

## AWS AgentCore

Current official pricing states consumption-based pricing with no upfront commitments or minimum fees.

Source:
https://aws.amazon.com/bedrock/agentcore/pricing/

This is not a zero-cost guarantee. Promotional-credit and account billing reality must be checked live.

## Google Calendar

Current docs:
- standard use is available at no additional cost below current threshold;
- current documented threshold for new projects is 1,000,000 requests/day before planned charges for over-threshold usage later in 2026.

Source:
https://developers.google.com/workspace/calendar/api/guides/quota

StillDone must stay orders of magnitude below the threshold and must not request paid quota increases.

## Google Tasks

Current courtesy limit:
- 50,000 queries/day.

Source:
https://developers.google.com/workspace/tasks/limits

## Gmail

Not required for canonical core.

Current docs state standard API use is available at no additional cost under current thresholds, with later-2026 billing changes planned for over-threshold use.

Source:
https://developers.google.com/workspace/gmail/api/reference/quota

Because Gmail adds privacy/OAuth/communication complexity without improving the core proof, it is deferred.

## Open-Meteo

Free API currently:
- no API key;
- no sign-up;
- no credit card;
- non-commercial use;
- up to 10,000 calls/day;
- attribution required.

Sources:
https://open-meteo.com/
https://open-meteo.com/en/pricing
https://open-meteo.com/en/terms

## Public endpoint budget law

No unauthenticated live endpoint may have an unbounded path to paid AWS inference/runtime.

Public judge experience should prefer:
- static/read-only evidence;
- sanitized recorded-live artifacts;
- bounded demo actions;
- operator-controlled live execution;
- strict rate limits/auth where live runtime is exposed.

## Billing truth freshness

Pricing/quota facts change.

Before any live paid-capable service is enabled, re-check current official documentation and live account settings.

If safe zero-personal-spend operation cannot be proven:
`BLOCKED / OPERATOR_DECISION_REQUIRED`.
