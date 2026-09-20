# Environment & API Memory — StillDone

## Current status

PRE-BOOTSTRAP.

No runtime/toolchain language has been frozen.

Do not assume Python/Node/TypeScript until P-00.04 chooses a minimal stack based on MCP/AWS SDK reality and developer ergonomics.

## Intended external systems

Primary track/runtime:
- MCP Streamable HTTP

Preferred AWS path, pending P-01:
- Amazon Bedrock
- Strands SDK
- Amazon Bedrock AgentCore

Canonical external demo systems:
- Google Calendar API
- Google Tasks API
- Open-Meteo

Deferred:
- Gmail
- payments
- browser automation
- health APIs

## Secrets

Expected future secrets/config may include:
- AWS auth through approved local/account mechanism;
- Google OAuth client configuration;
- Google OAuth tokens.

Never commit them.

Use `.env.example` only after exact variables exist.
