# Competition Contract — Build, Ship, Shape: Amazon Developer Hackathon

Verification & Snapshot Date: `2026-09-20`  
Governing Authority: Current Official External Rules and Documentation

---

## 1. Official Sources & Attribution

All facts recorded in this contract were retrieved and verified against the following current official sources on `2026-09-20`:

| Source | Official URL | Scope / Authority |
|---|---|---|
| Hackathon Official Rules | https://amazonappdev2026.devpost.com/rules | Official binding contract, eligibility, criteria, prizes, submission rules (updated Sep 16, 2026) |
| Hackathon Home | https://amazonappdev2026.devpost.com/ | Track definitions, overview, timeline, sponsor info |
| Hackathon Resources | https://amazonappdev2026.devpost.com/resources | Tooling guides, starter samples, AWS credit form link |
| Alexa+ Add-ons Home | https://developer.amazon.com/docs/alexaplus/add-ons/home.html | Developer access boundary, Category SDK vs MCP Toolkit (updated Jul 10, 2026) |
| Alexa+ MCP QuickStart | https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html | MCP technical spec (Streamable HTTP, OAuth 2.1, PRM, <500ms latency) |
| Alexa+ Integration Approach | https://developer.amazon.com/docs/alexaplus/add-ons/choose-the-proper-alexaplus-integration-approach.html | Integration path selection |
| AWS Promotional Credits Terms | https://aws.amazon.com/awscredits/ | Terms governing competition promotional credits |

---

## 2. Timeline & Competition Milestones

All times are based on U.S. Pacific Time (PT).

| Milestone | Exact Date & Time | Notes / Timezone Details |
|---|---|---|
| **Submission Period Start** | Monday, August 31, 2026, 10:15 am PT | Submissions open on Devpost |
| **AWS Credit Request Deadline** | Wednesday, October 21, 2026, 12:00 pm PT | Form closes; while supplies last |
| **Submission Deadline** | Friday, October 23, 2026, 12:00 pm PDT | Hard stop (3:00 pm EDT / 22:00 TRT) |
| **Judging Period** | Monday, November 9, 2026 (12:00 pm PT) – Friday, November 20, 2026 (12:00 pm PT) | Two-stage evaluation process |
| **Winner Announcement** | On or around Thursday, December 3, 2026, 12:00 pm PT | Public announcement |
| **Winner Affidavit Return** | Within 10 business days after Required Forms are sent | Failure to return may cause disqualification/forfeiture |
| **Prize Delivery** | Within 60 days of receipt of completed Required Forms | Cash and AWS credits delivered to verified entrants |

---

## 3. Eligibility & Operator Standing

- **Eligible Entrants**:
  - Individuals of legal age of majority in their jurisdiction of residence.
  - Teams of eligible individuals (must appoint one authorized Representative).
  - Registered organizations / legal entities.
  - An eligible individual may enter individually and also join more than one team/organization.
- **Excluded Jurisdictions**:
  - Residents/domiciles of Brazil, Quebec, Russia, Crimea, Cuba, Iran, North Korea, and any country/territory comprehensively sanctioned by U.S. Treasury OFAC or prohibited by law.
- **Operator Jurisdiction**:
  - Turkey (TR) is not an excluded territory; the operator meets age-of-majority criteria.
- **Excluded Parties**:
  - Sponsor (Amazon Developer), Administrator (Devpost), and Promotion Entity employees, representatives, agents, judges, and immediate family/household members.
- **Conflict of Interest / Support**:
  - Projects must not have received prior funding, commercial contract, or preferential support from Sponsor/Devpost before the submission window.

---

## 4. Track Selection: Alexa+ (Primary Track)

### 4.1 Qualification Routes
The official rules define three valid qualification routes for the Alexa+ Track:
1. **Agent Skill**: A working Agent Skill.
2. **Self-Hosted MCP Server**: A self-hosted MCP server implementing MCP specification version `2025-11-25` (or later once confirmed) over Streamable HTTP.
3. **Simulated Alexa+ Experience**: Developers can simulate the Alexa+ experience in a web app using their own preferred agentic tools.

### 4.2 Runtime Hook vs. Simulation Boundary
- **Standard MCP / Skill Route**:
  - The repository must demonstrate runtime use in code: imported and actually called (library import, entry point, loaded agent/flow/MCP config), not just mentioned in README.
- **Simulated Alexa+ Route**:
  - "Entrants may submit a simulated Alexa+ experience instead — built using any AI or agentic tool of their choice, no specific framework, SDK, or MCP-shaped surface required. This alternate path is exempt from the runtime-technology-hook requirement above; the code repository must still include the simulation's source code, and the demo video must clearly show the simulated experience."

### 4.3 Alexa+ Developer Access Boundary (Partner-Only Restriction)
- Current official documentation (`developer.amazon.com/docs/alexaplus/add-ons/home.html`, updated Jul 10, 2026) states:
  > **Important:** At this time, Category SDK and MCP Toolkit are available to select partners only.
- **StillDone Strategy & Law**:
  - Direct Alexa+ developer console / add-on deployment is **optional** and **not a dependency** for StillDone.
  - StillDone builds a **real self-hosted MCP server over Streamable HTTP** (compliant with MCP 2025-11-25) and provides a clearly labeled, fully functional **simulated Alexa+ web client surface**.
  - This satisfies both the standard MCP server technical requirements and the official simulated-experience qualification route, completely decoupling the project from private partner approval while maintaining technical depth.

### 4.4 Technical Specs for Direct Connection (Reference)
- **Transport**: Streamable HTTP (standalone HTTP+SSE deprecated by MCP 2025-11-25).
- **Public URL**: Remote HTTPS URL required (cloudflared tunneling acceptable in development).
- **Authentication**: OAuth 2.1 authorization code flow with PKCE (S256).
  - Protected Resource Metadata (PRM) document according to RFC 9728.
  - Auth server metadata at `/.well-known/oauth-authorization-server`.
  - `code_challenge_methods_supported` must include `S256`.
  - 401 Unauthorized returned without `WWW-Authenticate` header.
- **Latency Requirement**: Round-trip query response latency target of less than 500 ms.

---

## 5. AWS Builder Mini Challenge

- **Eligibility**: Any primary-track project that incorporates AWS services with documented integrations.
  - Mini-challenges build on top of a primary track submission; they are not standalone projects.
  - Supported services explicitly named: Amazon Bedrock, AgentCore, Strands SDK, Kiro Crew, SageMaker, etc.
  - Kiro Crew qualifies on its own as a development tool used during the hackathon (without requiring an additional runtime AWS call).
- **Judging Criteria (Obvious vs. Creative)**:
  - *Obvious*: Single Bedrock call for text generation, S3 for storage.
  - *Creative*: Multi-service pipeline (Bedrock + AgentCore + Strands SDK), agentic architecture with Claude/Kiro for development workflow, agent orchestration patterns.
- **StillDone Fit**:
  - Uses Amazon Bedrock for planning inference, Strands SDK for agentic decomposition/contracts, evaluates AgentCore runtime (subject to P-01 zero-cost feasibility), and provides complete documented integration. Directly targets the official "Creative" standard.
- **Submission Evidence**:
  - Entrant must describe which AWS service(s) were used and how in the Product Feedback submission field.

---

## 6. Open Source Mini Challenge

- **Eligibility**: Create a new, additional open-source project (with an open-source license) OR contribute to an existing public repository during the hackathon window (August 31 – October 23, 2026), alongside a primary track submission.
- **Permitted Contribution Forms**:
  - New repository with an open-source license;
  - Branch, fork, or pull request.
- **PR Merge Requirement**:
  - PRs do **NOT** need to be merged; sharing an unmerged forked version is explicitly permitted.
- **Judging Criteria (Obvious vs. Creative)**:
  - *Obvious*: README update, typo fix, minor formatting.
  - *Creative*: Meaningful feature addition with tests, bug fix that unblocks other developers, new integration pattern.
- **Required Submission Fields**:
  1. Contribution URL;
  2. Project repository URL;
  3. GitHub username;
  4. Short description of what was done, how it works, and why it matters.
- **Multiple Prize Rule Interaction**:
  - A project can win at most one (1) track prize and one (1) mini challenge prize.
  - Entering both AWS Builder and Open Source provides two opportunities to win a mini challenge, but only one mini challenge prize can be awarded to StillDone.

---

## 7. Submission Artifacts & Repository Rules

### 7.1 GitHub Code Repository (Updated September 16, 2026)
- The repository must contain all source code, assets, and instructions required for functionality.
- **Public Path**: Must include an open-source license file, detectable and visible at the top of the repository page (About section). StillDone targets Public + Apache-2.0.
- **Private Path**: If kept private, must be shared with `testing@devpost.com` and the 6 Amazon DevRel GitHub users:
  `chris-trag`, `knmeiss`, `giolaq`, `anishamalde`, `mosesroth`, `emersonsklar`.
  (Invitations expire after 7 days; must be invited at submission time).

### 7.2 Demonstration Video
- **Length**: Under three (3) minutes (< 3:00). Judges are not required to watch past 3 minutes.
- **Hosting**: Publicly visible on YouTube or Vimeo.
- **Content**: Must show the project functioning on the intended platform/device.
- **Language**: English (or provide an English translation/subtitles).
- **IP Protection**: No third-party trademarks or copyrighted music/media without permission.

### 7.3 Testing & Judge Accessibility
- The project must be accessible free of charge and without restriction for testing and evaluation until the Judging Period ends (November 20, 2026).
- If private login/testing credentials are required, they must be supplied in testing instructions.
- **Official Evaluation Rule**: "Judges are not required to test the Project and may choose to judge based solely on the text description, images, and video provided in the Submission."
- StillDone provides clear local reproduction steps and honest live vs. recorded evidence boundaries.

---

## 8. Product Feedback & Friction Log Bonus Contract

### 8.1 Mandatory Product Feedback
Feedback must be provided for each developer tool, API, or SDK used, covering 5 mandatory questions:
1. Which developer tools, APIs, and SDKs did you use and for what? (Include AWS services description here).
2. What worked well? (setup, documentation, testing, performance, reliability).
3. What needs work? (system errors, doc sections, missing features, compatibility issues, tool limitations, required workarounds).
4. How was your onboarding experience? (getting from zero to hello world).
5. Would you build with these devices and services again? (Yes/No and explain why).

### 8.2 Optional Feature Requests
- Description of feature wanted, why it matters, and priority rating (`Critical`, `Important`, or `Nice-to-have`).

### 8.3 Optional Friction Logs (Up to 10% Judging Bonus)
- **Bonus Mechanics**: During Stage 1 downselection, Amazon's internal review team evaluates friction log entries and recommends a bonus — up to 10% — to the Stage 2 judging panel. The Stage 2 panel applies this bonus to the final spreadsheet score.
- **Required Fields for Factual Friction Entries**:
  - Specific task attempted;
  - Steps taken;
  - Expected result vs. actual result;
  - Severity rating;
  - Workaround used;
  - Actionable suggestion for Amazon/AWS teams.
- **Logging Rule**: Factual logging throughout development into `docs/COMPETITION_FEEDBACK_LOG.md`. Never invent or fabricate friction.

---

## 9. Judging Criteria & Tie-Breaking Contract

### 9.1 Two-Stage Judging Structure
- **Stage One**: Pass/fail baseline viability assessment (theme fit and required API/SDK application). Amazon review team reviews friction logs and calculates recommended bonus.
- **Stage Two**: Panel evaluation on four (4) equally weighted criteria.

### 9.2 The Four Equally Weighted Criteria (25% Each)
1. **Tech Implementation**:
   - How well is the project built, and how effectively does it use the required tech? Does it effectively leverage the required APIs, SDKs, or device capabilities for the specified track or mini-challenge?
2. **Design**:
   - Does the project deliver a complete, coherent product experience? Is the interaction model intuitive and well-considered for the target device or platform?
3. **Potential Impact**:
   - Does the project make a credible, specific case for solving customer needs? Could it realistically serve an audience beyond the hackathon?
4. **Quality of the Idea**:
   - Is this a creative, imaginative use of the required tools? Does the team demonstrate a genuine understanding of the developer ecosystem and the end-user needs? (Obvious vs. creative standard applied).

### 9.3 Tie-Breaking Hierarchy
In case of a tie between two or more submissions:
1. Highest score in **Tech Implementation** wins.
2. If still tied, highest score in **Design** wins.
3. If still tied, highest score in **Potential Impact** wins.
4. If still tied, highest score in **Quality of the Idea** wins.
5. If still tied across all four criteria, the panel of Judges votes to break the tie.

---

## 10. Prize Structure

| Track / Challenge | Place | Cash Prize | AWS Credits | Other Awards |
|---|---|---|---|---|
| **Alexa+ Track** | 1st Place | $25,000 | $15,000 | Meeting with Amazon Developer team, featured on developer channels |
| **Alexa+ Track** | 2nd Place | $15,000 | $5,000 | Featured on Amazon Developer channels |
| **Alexa+ Track** | 3rd Place | $4,000 | $1,000 | Featured on Amazon Developer channels |
| **AWS Builder Mini Challenge** | Winner | $5,000 | $5,000 | Meeting with Amazon Developer team, featured on developer channels |
| **Open Source Mini Challenge** | Winner | $5,000 | $5,000 | Meeting with Amazon Developer team, featured on developer channels |
| *Fire TV Track* | 1st / 2nd / 3rd | $25k / $15k / $4k | $15k / $5k / $1k | Team meeting (1st), featured |
| *Bee Track* | 1st / 2nd | $12,000 / $8,000 | — | Team meeting (1st), featured |
| *Ring Track* | 1st / 2nd | $12,000 / $8,000 | — | Team meeting (1st), featured |

- **Total Hackathon Pool**: $138,000 in cash prizes; $190,000 total value including AWS credits.
- **Multiple Prize Limitation**: A single project can only win one (1) track prize and one (1) mini challenge prize.

---

## 11. AWS Promotional Credits & Zero-Personal-Spend Boundary

- **Credit Offer**: $150 in AWS Promotional Credits.
- **Form URL**: https://forms.gle/5hyhr1u6x3fuV2aW7
- **Request Deadline**: Wednesday, October 21, 2026 at 12:00 pm PT.
- **Availability**: "While supplies last" for registered participants.
- **Binding Rule on Costs**:
  > "Additional charges incurred by the Entrant for the use of AWS products are the responsibility of the Entrant. Entrants are encouraged to monitor their usage of services so as to not incur additional charges."
- **StillDone Personal Spend Law**:
  - Target personal spend remains **$0.00**.
  - Competition promotional credits are a finite safety buffer, not permission to incur post-credit debt.
  - Strict budget alarms, zero-cost development paths, local simulation, and service kill switches must be established in P-01 before enabling live paid AWS services.

---

## 12. Semantic Reconciliation Table

Audit of existing competition claims in the StillDone starter pack against current official facts retrieved on `2026-09-20`:

| Starter Pack Claim | Official Status on 2026-09-20 | Reconciliation Action |
|---|---|---|
| Deadline: Oct 23, 2026 12:00 PM PDT | CONFIRMED | Maintained exactly (added 3:00 PM EDT / start time Aug 31) |
| Judging: Nov 9–20, 2026 | CONFIRMED | Maintained exactly (added 12:00 PM PT start/end) |
| Winners: On or around Dec 3, 2026 | CONFIRMED | Maintained exactly |
| Alexa+ Track allows self-hosted MCP (2025-11-25+) | CONFIRMED | Maintained; Streamable HTTP required |
| Alexa+ Track allows simulated experience in web app | CONFIRMED | Maintained; explicitly exempt from runtime tech hook |
| Alexa+ partner access limited to select partners | CONFIRMED | Maintained from `developer.amazon.com` (updated Jul 10, 2026) |
| MCP round-trip latency target < 500 ms | CONFIRMED | Maintained from official MCP quickstart guide |
| AWS Builder Mini Challenge accepts Bedrock+AgentCore+Strands | CONFIRMED | Maintained; official rules cite this as primary creative example |
| Kiro Crew qualifies AWS Builder on its own | CONFIRMED | Added explicit rule verification |
| Open Source Mini Challenge accepts unmerged PRs/forks | CONFIRMED | Maintained; rules explicitly state PR does not need to be merged |
| GitHub repo public + open source license required | QUALIFIED | Updated Sep 16: Public+OSS OR Private shared with testing@devpost.com + 6 DevRel accounts |
| Demo video under 3 minutes on YouTube/Vimeo | CONFIRMED | Maintained exactly; public, English required |
| Product feedback mandatory on all tools/APIs/SDKs | CONFIRMED | Maintained; 5 explicit questions recorded |
| Friction logs earn up to 10% judging bonus | CONFIRMED | Maintained; Stage 1 Amazon review to Stage 2 panel mechanics recorded |
| Judging criteria equally weighted across 4 areas | CONFIRMED | Maintained (Tech Implementation, Design, Impact, Quality of Idea) |
| Tie-breaking prioritizes Tech Implementation | CONFIRMED | Maintained; explicit 4-tier hierarchy recorded |
| One project may win 1 track + 1 mini challenge | CONFIRMED | Maintained exactly |
| $150 AWS credit form available | CONFIRMED | Added exact Google Form URL, Oct 21 deadline, and while supplies last note |
