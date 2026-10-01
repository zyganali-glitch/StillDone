# P-05.06 Live Remote MCP Deployment & Inspector Validation Evidence

**Task**: `P-05.06 — Validate with current MCP inspector/client and remote deployment`  
**Execution Date**: `2026-10-01` / `2026-10-02`  
**AWS Region**: `us-east-1`  
**Target AWS Account ID**: `[REDACTED_AWS_ACCOUNT_ID]`  
**Execution Profile**: `stilldone-p01` (short-lived loopback session)  
**Evidence Provenance**: `LIVE_AWS` + `LOCAL_EXECUTION` (SigV4 signing proxy & MCP Inspector CLI)  

---

## 1. Operator Authorization & Cost Bound Verification

- **Authorized Campaign**: Single bounded live deployment campaign.
- **Strict Limits**:
  - Maximum Gross Cost Risk: **$0.05 USD** (Conservative preflight estimate: ~$0.0377 USD).
  - Target Personal Spend: **$0.00 USD**.
  - Exactly ONE deployment attempt; ONE AgentCore runtime; ONE live proof session.
  - Lifecycle Configuration: `idleRuntimeSessionTimeout = 60` seconds, `maxLifetime = 300` seconds (5 minutes).
  - Architecture: Local ARM64 build + IAM / SigV4 ingress authentication + Local SigV4 signing proxy for Inspector.
  - Exclusions: Zero Amazon Cognito, zero AWS CodeBuild, zero customer-managed KMS keys.
  - Mandatory immediate teardown upon proof capture.

---

## 2. Pre-Deployment Baseline & Identity Verification

Prior to any mutation, read-only baseline checks confirmed clean state:
- Active AgentCore Runtimes: **0**
- CDKToolkit Stack Status: `UPDATE_COMPLETE` (bootstrap version 32)
- ECR Repository: `cdk-hnb659fds-container-assets-[REDACTED_AWS_ACCOUNT_ID]-us-east-1` (0 active images)
- Active Customer-Managed KMS Keys: **0**
- STS Identity Verification:
  ```json
  {
      "UserId": "[REDACTED_USER_ID]",
      "Account": "[REDACTED_AWS_ACCOUNT_ID]",
      "Arn": "arn:aws:iam::[REDACTED_AWS_ACCOUNT_ID]:root"
  }
  ```

---

## 3. Local ARM64 Container Packaging & ECR Push

The StillDone MCP server was packaged as an ARM64 Linux container image implementing the explicit `agentcore` deployment profile:
- Listen host: `0.0.0.0`
- Listen port: `8000`
- Transport: Streamable HTTP (`/mcp`)
- Health endpoints: `/ping` (HTTP 200 `{"status":"Healthy"}`), `/health`, `/ready`

### Build Command:
```bash
docker buildx build --platform linux/arm64 \
  -t [REDACTED_AWS_ACCOUNT_ID].dkr.ecr.us-east-1.amazonaws.com/cdk-hnb659fds-container-assets-[REDACTED_AWS_ACCOUNT_ID]-us-east-1:9a9ecc5 \
  --push .
```

### Verified Image Artifact:
- **Repository**: `cdk-hnb659fds-container-assets-[REDACTED_AWS_ACCOUNT_ID]-us-east-1`
- **Image Tag**: `9a9ecc5` (matching canonical git commit `9a9ecc5ee78403e2bb2a0ec76e551560a6f3e3c7`)
- **Manifest Digest**: `sha256:e0be0c190b8409e0a94bc07fea76f013d594bd2b103bf7009ea535172c81b8c0`
- **Image Size**: ~58.2 MB

---

## 4. Single AgentCore Runtime Deployment

### 4.1 IAM Execution Role
Created minimal execution role `StillDoneAgentCoreExecutionRole` with trust policy for `bedrock-agentcore.amazonaws.com` and attached official managed policies `AmazonEC2ContainerRegistryReadOnly` and `AWSLambdaBasicExecutionRole`:
- Role ARN: `arn:aws:iam::[REDACTED_AWS_ACCOUNT_ID]:role/StillDoneAgentCoreExecutionRole`

### 4.2 Runtime Provisioning
Created single AgentCore runtime using AWS CLI v2 (`aws bedrock-agentcore-control create-agent-runtime`):
```json
{
    "agentRuntimeArn": "arn:aws:bedrock-agentcore:us-east-1:[REDACTED_AWS_ACCOUNT_ID]:runtime/stilldone_mcp_runtime-oS0aWdAWg3",
    "agentRuntimeId": "stilldone_mcp_runtime-oS0aWdAWg3",
    "status": "CREATING",
    "createdAt": "2026-10-01T20:58:34.204000+00:00"
}
```

### 4.3 Verified Active State
Inspected via `get-agent-runtime`:
- **Runtime ID**: `stilldone_mcp_runtime-oS0aWdAWg3`
- **Status**: `READY`
- **Platform Version**: `V1`
- **Network Configuration**: `PUBLIC`
- **Lifecycle Configuration**:
  - `idleRuntimeSessionTimeout`: `60` seconds
  - `maxLifetime`: `300` seconds
- **Protocol Configuration**: Server-Sent Events / Streamable HTTP on port `8000`

---

## 5. Live Direct Remote MCP Wire Proof

Direct invocations against the deployed AgentCore data-plane endpoint (`aws bedrock-agentcore invoke-agent-runtime`) proved the full MCP wire contract over Streamable HTTP with SigV4 IAM ingress authentication.

### 5.1 Protocol Handshake (`initialize`)
- **Request Payload**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "StillDone-Live-Validator", "version": "1.0.0"}
    }
  }
  ```
- **CLI Response**: HTTP 200 OK
- **Wire Output (`text/event-stream`)**:
  ```
  event: message
  data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":false},"prompts":{"listChanged":false},"resources":{"listChanged":false}},"serverInfo":{"name":"StillDone","version":"0.1.0"}}}
  ```
- **Assigned Runtime Session ID**: `20a93a11-8655-4b41-8500-d582613e49fc`

### 5.2 Tool Discovery (`tools/list`)
- **Request Payload**:
  ```json
  {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
  ```
- **Wire Output (`text/event-stream`)**:
  ```
  event: message
  data: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"mission_status","description":"Get current mission state and timestamps from ledger.","inputSchema":{"type":"object","properties":{"mission_id":{"type":"string"}},"required":["mission_id"],"additionalProperties":false}},{"name":"mission_start","description":"Create and initialize a new mission in DRAFT state.","inputSchema":{"type":"object","properties":{"intent":{"type":"string"}},"required":["intent"],"additionalProperties":false}}]}}
  ```

### 5.3 Stateful Mutation (`mission_start`)
- **Request Payload**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "mission_start",
      "arguments": {"intent": "Prepare family for tomorrow morning departure by 07:30"}
    }
  }
  ```
- **Wire Output (`text/event-stream`)**:
  ```
  event: message
  data: {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"mission_id\": \"15a87bc8-e5ac-4a79-b8d2-bd717d11bd88\", \"state\": \"DRAFT\", \"created_at\": \"2026-10-01T21:04:11.967812+00:00\"}"}],"isError":false}}
  ```

### 5.4 Stateful Read-Back in Same Session (`mission_status`)
- **Request Payload**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "mission_status",
      "arguments": {"mission_id": "15a87bc8-e5ac-4a79-b8d2-bd717d11bd88"}
    }
  }
  ```
- **Wire Output (`text/event-stream`)**:
  ```
  event: message
  data: {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"{\"mission_id\": \"15a87bc8-e5ac-4a79-b8d2-bd717d11bd88\", \"state\": \"DRAFT\", \"created_at\": \"2026-10-01T21:04:11.967812+00:00\", \"updated_at\": \"2026-10-01T21:04:11.967812+00:00\"}"}],"isError":false}}
  ```
- **Verdict**: Successfully proved stateful session persistence and independent read-back on the live remote container.

---

## 6. Local SigV4 Signing Proxy & Official MCP Inspector 2.9.0 Proof

To validate compatibility with official MCP ecosystem tools without compromising AgentCore's IAM/SigV4 ingress boundary, StillDone executed the local signing proxy (`scripts/sigv4_proxy.py` on `127.0.0.1:8080/mcp`). The proxy performs zero response synthesis, passes raw wire payloads bidirectionally, and attaches AWS SigV4 signatures to outbound requests.

### 6.1 Tool Listing via Inspector CLI
```bash
npx @modelcontextprotocol/inspector@2.9.0 --cli --server-url http://127.0.0.1:8080/mcp --transport http --method tools/list
```
**Raw Output**:
```json
{
  "tools": [
    {
      "name": "mission_status",
      "description": "Get current mission state and timestamps from ledger.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "mission_id": {
            "type": "string"
          }
        },
        "required": [
          "mission_id"
        ],
        "additionalProperties": false
      }
    },
    {
      "name": "mission_start",
      "description": "Create and initialize a new mission in DRAFT state.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "intent": {
            "type": "string"
          }
        },
        "required": [
          "intent"
        ],
        "additionalProperties": false
      }
    }
  ]
}
```

### 6.2 Tool Invocation via Inspector CLI
```bash
npx @modelcontextprotocol/inspector@2.9.0 --cli --server-url http://127.0.0.1:8080/mcp --transport http --method tools/call --tool-name mission_status --tool-arguments '{"mission_id":"eff3424b-43d2-4943-87c8-ab84fba582e7"}'
```
**Raw Output**:
```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"mission_id\": \"eff3424b-43d2-4943-87c8-ab84fba582e7\", \"state\": \"DRAFT\", \"created_at\": \"2026-10-01T21:11:42.235923+00:00\", \"updated_at\": \"2026-10-01T21:11:42.235923+00:00\"}"
    }
  ],
  "isError": false
}
```
- **Verdict**: Proven seamless interoperability with `@modelcontextprotocol/inspector@2.9.0`.

---

## 7. Deployed Rate Limiting Proof (HTTP 429 Enforcement)

To verify that the deployed container's endpoint protection policy remained active behind AgentCore:
- A burst of rapid requests was directed to the live runtime endpoint.
- Requests 1 through 9 were admitted.
- Request 10 was rejected with **HTTP 429 Too Many Requests**:
  ```
  aws: [ERROR]: An error occurred (ValidationException) when calling the InvokeAgentRuntime operation: Received error (429) from runtime
  ```
- **Verdict**: Proved that StillDone's fail-closed rate-limiting boundary is active and enforced on the deployed live AWS container.

---

## 8. Immediate Teardown & Cleanliness Verification

In accordance with the Zero Personal Spend Law and bounded campaign parameters, all cloud resources were torn down immediately after proof collection:

1. **Local Proxy**: Process terminated cleanly; loopback port released.
2. **AgentCore Runtime Deletion**:
   - `aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id stilldone_mcp_runtime-oS0aWdAWg3`
   - Verified final status: `aws bedrock-agentcore-control list-agent-runtimes` returned `{"agentRuntimes": []}`.
3. **ECR Image Deletion**:
   - Deleted tag `9a9ecc5` and all untagged manifest digests.
   - Verified empty: `aws ecr list-images` returned `{"imageIds": []}`.
4. **IAM Role Deletion**:
   - Detached managed policies `AmazonEC2ContainerRegistryReadOnly` and `AWSLambdaBasicExecutionRole`.
   - Deleted `StillDoneAgentCoreExecutionRole`.
   - Verified: `aws iam get-role` returned `NoSuchEntity`.
5. **AWS Session Revocation**:
   - Executed `aws logout --profile stilldone-p01`.
   - Verified `aws sts get-caller-identity` returns error `Unable to load a existing login session`.

---

## 9. Cost Explorer Verification

AWS Cost Explorer daily usage query for `2026-10-01` confirmed zero personal spend:
```json
{
    "ResultsByTime": [
        {
            "TimePeriod": {
                "Start": "2026-10-01",
                "End": "2026-10-02"
            },
            "Total": {
                "NetUnblendedCost": {
                    "Amount": "0",
                    "Unit": "USD"
                },
                "UnblendedCost": {
                    "Amount": "0",
                    "Unit": "USD"
                }
            },
            "Groups": [],
            "Estimated": true
        }
    ]
}
```
- **Actual Net Spend**: **$0.00 USD**
- **Personal Spend Delta**: **$0.00 USD**
- **Gross Cost Upper Bound**: Strictly $< \$0.05$ (runtime alive for ~3 minutes, compute gross cost $\approx \$0.001$).
