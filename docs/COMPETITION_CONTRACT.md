# Competition Contract — Build, Ship, Shape: Amazon Developer Hackathon

Snapshot date: `2026-09-20`

Official rules:
https://amazonappdev2026.devpost.com/rules

Competition home:
https://amazonappdev2026.devpost.com/

Resources:
https://amazonappdev2026.devpost.com/resources

## Dates

Current official rules state:
- Submission deadline: October 23, 2026, 12:00 PM PDT
- Judging: November 9–20, 2026
- Winners announced: on or around December 3, 2026

Re-verify before submission.

## Primary track

**Alexa+**

Current rules allow:
1. working Agent Skill; or
2. self-hosted MCP server using MCP `2025-11-25` or later once confirmed, over Streamable HTTP; or
3. clearly shown simulated Alexa+ experience.

StillDone chooses the stronger guaranteed path:
- real self-hosted MCP server over Streamable HTTP;
- simulated Alexa+ client surface only if actual Alexa+ partner access is unavailable.

## Alexa+ access risk

Current official Alexa+ developer docs state that Category SDK and MCP Toolkit are available to select partners at this time.

Source:
https://developer.amazon.com/docs/alexaplus/add-ons/home.html

Therefore actual Alexa+ add-on connection is OPTIONAL, not a dependency for project viability.

Current MCP quickstart requirements include:
- Streamable HTTP;
- remote URL;
- OAuth 2.1 authorization code + PKCE/S256 for direct Alexa+ connection;
- current documented round-trip response target below 500 ms.

Source:
https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html

## AWS Builder Mini Challenge

Current rules:
any primary-track project that incorporates AWS services with documented integrations qualifies.

Judging guidance distinguishes:
- obvious: single Bedrock call / decorative AWS use;
- creative: multi-service/agentic architecture such as Bedrock + AgentCore + Strands and orchestration patterns.

StillDone target:
real model/agent/runtime usage that materially powers mission planning/execution, not README-only branding.

Final AWS stack is frozen only after live feasibility.

## Open Source Mini Challenge

Current rules:
create a new additional open-source project OR contribute to an existing public repository during the hackathon window.

Contribution forms may include:
- new repo with open-source license;
- branch;
- fork;
- pull request.

PR does not need to be merged.

Required submission fields include:
- contribution URL;
- project repository URL;
- GitHub username;
- what was done;
- how it works;
- why it matters.

StillDone strategy:
defer OSS mini work until the core live mission works. Preferred contribution theme is a generic tested MCP execute→read-back→verify integration pattern/library.

## Repository

Current rules require a GitHub code repository containing source/assets/instructions.

Public path:
- open-source license required;
- license should be visible/detectable.

StillDone target:
public GitHub repository + Apache-2.0.

## Demo

Current rules:
- less than 3 minutes;
- judges are not required to watch beyond 3 minutes;
- project must be shown functioning;
- upload publicly to YouTube or Vimeo;
- avoid unauthorized third-party marks/copyrighted media.

StillDone target final runtime:
approximately 2:30–2:50.

## Product Feedback

Required for tools/APIs/SDKs used:
- what was used and why;
- what worked well;
- what needs work;
- onboarding experience;
- whether we would build with it again.

Log throughout development, not at the end.

## Friction logs

Optional, but current rules say friction logs can contribute up to a 10% judging bonus.

Every real friction event should be appended factually to:
`docs/COMPETITION_FEEDBACK_LOG.md`

Never fabricate friction.

## Judging criteria

Equally weighted:
1. Tech Implementation
2. Design
3. Potential Impact
4. Quality of the Idea

Tie-breaking begins with the first listed criterion, so technical implementation quality matters particularly.

## Multiple prize rule

Current rules state a project may win:
- one track prize; and
- one mini challenge prize.

Entering both AWS Builder and Open Source is still useful even though one project cannot win both mini-challenge prizes.

## Language

Submission materials must be English or include English translation.

## Judge accessibility

The project must remain available free of charge to judges through judging.

Judges may choose to judge solely from:
- text;
- images;
- video.

StillDone must still provide a clear reproduction path and honest live/recorded evidence boundary.
