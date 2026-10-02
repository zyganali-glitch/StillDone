# P-05.06 Live Remote MCP Deployment & Inspector Validation Evidence

**Task**: `P-05.06 — Validate with current MCP inspector/client and remote deployment`  
**Execution Date**: `2026-10-01` / `2026-10-02`  
**AWS Region**: `us-east-1`  
**Target AWS Account ID**: `[REDACTED_AWS_ACCOUNT_ID]`  
**Execution Profile**: `stilldone-p01` (short-lived loopback session)  
**Evidence Provenance**: `LIVE_AWS` + `LOCAL_EXECUTION` (SigV4 signing/CLI bridge & MCP Inspector CLI)  

---

## 1. Operator Authorization & Cost Bound Verification

- **Authorized Campaign**: Single bounded live deployment campaign.
- **Strict Limits**:
  - Maximum Gross Cost Risk: **$0.05 USD** (Conservative preflight estimate: ~$0.0377 USD).
  - Target Personal Spend: **$0.00 USD**.
  - Exactly ONE deployment attempt; ONE AgentCore runtime.
  - Lifecycle Configuration: `idleRuntimeSessionTimeout = 60` seconds, `maxLifetime = 300` seconds (5 minutes).
  - Architecture: Local ARM64 build + IAM / SigV4 ingress authentication + Local SigV4 signing/CLI bridge for Inspector.
  - Exclusions: Zero Amazon Cognito, zero AWS CodeBuild, zero customer-managed KMS keys.
  - Mandatory immediate teardown upon proof capture.

### 1.1 Session-Count Truth & Procedural Deviation Record
The operator authorized ONE live proof session. Canonical evidence and runtime bridge behavior confirm that at least **TWO** logical AgentCore runtime sessions were actually exercised:
1. **Session A**: Direct `aws bedrock-agentcore invoke-agent-runtime` proof session.
2. **Session B**: Inspector validation session via the local SigV4 signing/CLI bridge (`scripts/sigv4_proxy.py`).

**Reason**: `scripts/sigv4_proxy.py` starts with `_active_session_id = None`. On its first incoming Inspector MCP request, no previous session ID was passed, so the first upstream invocation created/obtained a distinct runtime session from AgentCore. Current official Amazon Bedrock AgentCore documentation states that each distinct `runtimeSessionId` receives its own dedicated microVM/session lifecycle.

**Classification**:
`OPERATOR_SCOPE_DEVIATION_RECORDED`

- Exactly ONE AgentCore runtime / deployment occurred.
- At least two logical runtime sessions were exercised, which exceeded the operator's procedural "one session" authorization.
- No second deployment or additional runtime was created.
- In accordance with the non-proliferation of cloud calls, no further AWS activity will be performed to alter or repeat this historical execution.

### 1.2 Cost-Bound Reconciliation for Two Sessions
Because the deployed runtime was observed as Platform V1 with a hardware ceiling of 2 vCPU and 8 GB RAM, and lifecycle max was bounded to 300 seconds (5 minutes), the conservative two-session authorization-risk bound is reconciled using official AWS AgentCore pricing:
- Platform V1 vCPU rate: **$0.0895** / vCPU-hour
- Platform V1 Memory rate: **$0.00945** / GB-hour
- Hardware ceiling: **2 vCPU / 8 GB**

One 5-minute maximum session:
$$\left(\frac{5}{60}\right) \times \left[(2 \times 0.0895) + (8 \times 0.00945)\right] \approx \$0.021217\text{ USD}$$

Two maximum sessions:
$$2 \times \$0.021217 \approx \$0.042434\text{ USD}$$

Pre-frozen conservative non-compute allowances:
- CloudWatch: **$0.005000 USD**
- ECR: **$0.000068 USD**
- S3: **$0.000101 USD**
- Network data transfer: **$0.000000 USD**
- CodeBuild: **$0.00 USD**
- Cognito: **$0.00 USD**
- Customer KMS: **$0.00 USD**

**Conservative Campaign Authorization-Risk Bound**:
$$\$0.042434 + \$0.005169 \approx \mathbf{\$0.047603\text{ USD}}$$

This bound strictly remains below the operator's **$0.05 USD** gross ceiling.

> [!NOTE]
> This figure represents a conservative theoretical authorization-risk upper bound based on maximum session lifetimes and hardware ceilings, NOT an actual measured billing quantity. Actual consumed CPU/memory values were not metered or claimed.

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
- **Assigned Runtime Session ID**: `[REDACTED_SESSION_ID]`

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
- **Verdict**: Successfully proved stateful session persistence and independent read-back within the direct proof session on the live remote container.

---

## 6. Local SigV4 Signing Bridge & Official MCP Inspector 2.9.0 Proof

To validate compatibility with official MCP ecosystem tools without compromising AgentCore's IAM/SigV4 ingress boundary, StillDone executed a local MCP POST bridge (`scripts/sigv4_proxy.py` on `127.0.0.1:8080/mcp`).

**Architectural Contract**:
- Inspector reached the real AgentCore MCP endpoint through a local SigV4 signing/CLI bridge.
- The bridge forwards MCP payloads to the real AgentCore `InvokeAgentRuntime` data plane using the short-lived AWS profile and returns the remote MCP payload to Inspector.
- It synthesizes ZERO successful MCP business responses.
- It does NOT claim Inspector directly authenticated to AgentCore.
- It does NOT fabricate `/ping` or `/health` responses (unsupported GET requests fail locally with HTTP 405 Method Not Allowed; the bridge does not claim to prove remote health endpoints).
- Incoming Inspector invocations through this bridge initiated a distinct logical runtime session (Session B), as recorded in `OPERATOR_SCOPE_DEVIATION_RECORDED`.

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
- **Verdict**: Proven seamless interoperability with `@modelcontextprotocol/inspector@2.9.0` via the local SigV4 signing/CLI bridge.

---

## 7. Deployed Rate Limiting Proof (HTTP 429 Enforcement)

To verify that the deployed container's endpoint protection policy remained active behind AgentCore:
- A burst of rapid requests was directed to the live runtime endpoint.
- The deployed `/mcp` path returned **HTTP 429** after quota consumption (`ValidationException: Received error (429) from runtime`).
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

## 9. Cost Explorer Verification & Billing Truth

AWS Cost Explorer daily usage query for `2026-10-01` returned:
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

### Deterministic Billing Classification:
- **CURRENT COST EXPLORER OBSERVATION**: `$0.00 USD`
- **STATUS**: `ESTIMATED / BILLING-LATENCY SUBJECT`
- **ACTUAL_BILLED_COST**: `NOT_OBSERVED`
- **PROMOTIONAL_CREDIT_OFFSET FOR THIS CAMPAIGN**: `NOT_OBSERVED`
- **PERSONAL_SPEND_DELTA**: `NOT_OBSERVED`

> [!IMPORTANT]
> The same-day Cost Explorer record is flagged as `Estimated: true` due to AWS billing ingestion latency. Final zero personal spend cannot be deterministically asserted from this preliminary report alone. Instead, financial containment is bounded by the conservative campaign authorization-risk bound ($\approx \mathbf{\$0.047603\text{ USD}}$), which remains safely within promotional credit limits and strictly below the authorized $\$0.05\text{ USD}$ gross ceiling. Exact runtime CPU/memory consumption was not measured.
