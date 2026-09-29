# Cost & Access Policy

Snapshot date: `2026-09-29`

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

### Operator Credit Status (as of 2026-09-29)

- **Redemption & Status**: The official `$150.00` Hackathon Promotional Credit (`Amazon Devices Global Hackathon - Teams A4`, type: Promotion) is successfully redeemed and **Active** in the operator's AWS account.
- **Balance & Usage**: `$150.00` granted, `$150.00` remaining, `$0.00` used at observation checkpoint (`2026-09-27`).
- **Expiration Date**: Billing detail expiration: `2028-09-01`. Hackathon email wording: `2028-08-31`. Discrepancy: `OBSERVED`. Cause: `UNKNOWN / NOT_ESTABLISHED`. For operational safety, future automation must not assume the later date when a one-day discrepancy exists; where expiry matters for execution, the conservative boundary (`2028-08-31`) applies unless current AWS Billing/API truth is freshly re-observed.
- **Applicable Products Coverage**: Directly inspected in the live AWS Billing "Applicable products" list. Explicitly confirmed to cover `Amazon Bedrock Service`, `AmazonBedrockFoundationModels`, `Amazon Bedrock`, `Amazon Bedrock Managed Knowledge Base`, and `Amazon Bedrock AgentCore`.
- **Separate AWS Signup Credit**: A separate `AWS Free Tier` signup credit of `$100.00` (Active, expires `2027-09-27`, `$0.00` used) was also observed. Total account remaining credit is `$250.00`. The hackathon promotion remains the canonical credit basis for StillDone.
- **Account Plan & Support**: Paid account plan explicitly chosen by the operator to permit promotional-credit redemption, with Basic (free) support plan.
- **Current Account Charges**: `NOT_OBSERVED / UNKNOWN` in P-01 evidence (Bills / current account charges were not separately inspected; credit usage at checkpoint observed at `$0.00`; credit usage is not equivalent to account charges).
- **Binding Policy**: No automatic paid fallback. Credits are a payment offset, NOT a hard spending cap. If credits exhaust or unexpected charges appear, execution halts immediately. Personal-spend exposure remains strictly `$0.00`.

Official rules explicit warning:
> “Additional charges incurred by the Entrant for the use of AWS products are the responsibility of the Entrant. Entrants are encouraged to monitor their usage of services so as to not incur additional charges.”

This does NOT mean:
- all AWS services are free;
- credits hard-stop automatically;
- post-credit usage cannot bill;
- credits necessarily last through judging.

## Phase P-01 Cumulative Cost Reconciliation & Cost Freeze

Audit of all live operations executed across Phase P-01:

| Operation / Micro-Task | Observed Resource Consumption | Conservative Gross Usage Estimate | Promotional Offset Coverage | Net Personal Spend |
|---|---|---|---|---|
| **Bedrock Converse (P-01.02)** | 3 cycles; 1 Converse call; 11 tokens (8 in, 3 out) | $\approx \$0.00000070\text{ USD}$ | Bedrock Foundation Models | **$0.00** |
| **Strands SDK (P-01.03)** | 1 agent execution; 13 tokens (8 in, 5 out) | $\approx \$0.00000098\text{ USD}$ | Bedrock Foundation Models | **$0.00** |
| **AgentCore Runtime & CDK (P-01.04)** | 2 deployments, 2 invocations, full teardown; CDK bootstrap customer KMS key active 1.143 hrs ($1.00/mo prorated) remediated to `PendingDeletion`; retained template storage < 30 KB | $\approx \$0.00521\text{ USD}$ | AgentCore & S3 / ceiling <= $0.10 | **$0.00** |
| **Google Calendar & Tasks (P-01.05)** | 4 read queries; standard courtesy quotas | $\$0.00$ | Free courtesy tier | **$0.00** |
| **Open-Meteo Forecast (P-01.06)** | 1 HTTP GET forecast query; public endpoint | $\$0.00$ | Free evaluation tier | **$0.00** |
| **Cloudflare Quick Tunnel (P-01.07)** | Ephemeral public HTTPS tunnel; full teardown | $\$0.00$ | Free temporary service | **$0.00** |
| **Cumulative P-01 Total** | Conservative gross usage upper bound: | **$\approx \$0.00521\text{ USD}$** | Active Credit Offset | **$0.00 (Target Met)** |

### Retained CDK Bootstrap Cost Truth
- The shared `CDKToolkit` CloudFormation stack was provisioned during P-01.04.
- An initial default customer-managed KMS key was identified by QA and remediated in P-01.04 via `cdk bootstrap --no-bootstrap-customer-key`.
- The customer KMS key was deleted from CloudFormation and is `PendingDeletion` in KMS ($0 ongoing storage fee).
- The retained S3 bootstrap staging bucket holds only CloudFormation templates (< 30 KB total); ongoing gross storage fee is estimated at `~$0.0000007/month`.
- Actual billed cost and personal-spend delta remain `NOT_OBSERVED / UNKNOWN`.

### Cost Freeze Verdict:
$$\mathbf{ZERO\_PERSONAL\_SPEND\_PATH = CREDIBLE\_THROUGH\_JUDGING}$$

*(Target personal spend is strictly $0.00. No guarantee is claimed; billing truth freshness will be re-verified before enabling any live cloud mutations in future phases).*

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
