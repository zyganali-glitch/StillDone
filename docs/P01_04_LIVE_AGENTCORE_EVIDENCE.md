# P-01.04 Live AgentCore Runtime Feasibility Evidence

**Date & Time (UTC)**: Cycle 1: `2026-09-28T19:14:00Z` | Repair Cycle: `2026-09-28T19:35:54Z`  
**Governing Rule**: [AGENTS.md](../AGENTS.md) § 1–24; [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md)  
**Task**: `P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence`  
**Status**: `DONE — awaiting independent QA PASS`  

---

## 1. Official AWS AgentCore Sources

Facts verified against current official external sources on `2026-09-28`:

| Item | Authority / URL | Verified Observation |
|---|---|---|
| **AgentCore CLI** | `@aws/agentcore` on npm (`https://www.npmjs.com/package/@aws/agentcore`) | Version `0.30.0`. CLI provides `create`, `deploy`, `invoke`, `status`, `remove`, `telemetry`. Requires Node.js >= 20. |
| **AgentCore Python SDK** | `bedrock-agentcore` on PyPI (`https://pypi.org/project/bedrock-agentcore/`) | Version `1.24.0`. Provides `from bedrock_agentcore.runtime import BedrockAgentCoreApp` runtime decorator pattern. |
| **CDK Construct Library** | `@aws/agentcore-cdk` on npm (`https://www.npmjs.com/package/@aws/agentcore-cdk`) | Version `0.1.0-alpha.54`. L3 construct library synthesizing `AWS::BedrockAgentCore::Runtime` CloudFormation resources. |
| **AgentCore Regions** | AWS Docs: `https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html` | Officially supported in 21 regions including `us-east-1` (US East - N. Virginia). |
| **AgentCore Pricing** | AWS Pricing: `https://aws.amazon.com/bedrock/agentcore/pricing/` | Consumption-based active-compute pricing: vCPU at `$0.0895` per active vCPU-hour; Memory at `$0.00945` per GB-hour. I/O wait time not billed. S3 standard storage `$0.023`/GB-month. |
| **Platform Version V2** | AWS Announcement (2026-09-18) | Platform Version V2 uses serverless microVM snapshot-based execution (~1.9s cold start) and elastic memory. Available in `us-east-1`. Default remains `V1` when unspecified in CLI schema. |

---

## 2. Financial Authority & Cost Gate

- **Operator Authorized Gross Ceiling**: `$0.10 USD` (cumulative across P-01.04)
- **Target Personal Spend**: `$0.00 USD`
- **Cumulative Conservative Cost Calculation**:
  - Cycle 1 Conservative Gross Usage: `~$0.00168 USD`
  - Repair Cycle Conservative Gross Usage: `~$0.00168 USD`
  - Retained Shared Bootstrap S3 Storage (< 15 KB @ $0.023/GB-mo): `< $0.00001 USD`
  - Cumulative Conservative Expected Gross Total: `~$0.00337 USD` (well below authorized `$0.10` limit)
- **Financial Decision**: **`COST_GATE = PASS`**

---

## 3. Read-Only Bootstrap Reconciliation (Shared Infrastructure)

Prior to the repair cycle, the existing `CDKToolkit` CloudFormation stack was audited read-only:

- **CDK Bootstrap State**: `CREATED_DURING_P01_04 / RETAINED_SHARED_INFRASTRUCTURE`
- **Observed Resource Classes in CDKToolkit**:
  - `AWS::SSM::Parameter` (Bootstrap version tracking)
  - `AWS::IAM::Role` (Deployment, lookup, and publishing execution roles)
  - `AWS::IAM::Policy` (Role execution policies)
  - `AWS::ECR::Repository` (Container assets repository)
  - `AWS::KMS::Key` (Asset encryption key)
  - `AWS::KMS::Alias` (Asset encryption key alias)
  - `AWS::S3::Bucket` (CDK file assets staging bucket)
  - `AWS::S3::BucketPolicy` (Bucket access policy)
- **Runtime-Specific Task Resources after Cycle 1 Cleanup**: `0 observed active`
- **Retained P-01.04-Created Shared Bootstrap Infrastructure**: `PRESENT`
- **Continuing Cost Assessment**: Staging bucket contains only small CloudFormation metadata templates (< 15 KB total); continuing monthly storage cost is `~$0.00000018/month`, fully compatible with the Zero Personal Spend Law.

---

## 4. Cycle 1: Historical Execution & Quoting Defect (Preserved Facts)

- **Execution Timestamp**: `2026-09-28T19:10:14Z`
- **Deployment**: Stack `AgentCore-p01agent-default`, runtime `[REDACTED_RUNTIME_ID]`, status `READY` in `us-east-1` (CodeZip build, Python 3.13, platform version `V1`).
- **Invocation Command**: `agentcore invoke --prompt '{"prompt": "PING"}' --json`
- **Observed Result**: HTTP 200 returned in 6720ms with session ID `[REDACTED_SESSION_ID]`. Response payload returned deterministic validation string `"UNKNOWN_PROMPT"`.
- **Root Cause**: Windows PowerShell argument evaluation unquoted `'{"prompt": "PING"}'` to `{prompt: PING}` before forwarding to the CLI.
- **Teardown**: Complete runtime-specific resource teardown verified; runtime deleted, stack deleted, CodeZip removed.
- **QA Finding**: Did not satisfy semantic acceptance (`AGENTCORE_OK`), requiring a bounded repair cycle.

---

## 5. Repair Cycle: Minimal Scratch Project & Single Deployment

The minimal probe was recreated in an ephemeral scratch directory outside the canonical repository (`[REDACTED_SCRATCH_DIR]`) reusing the shared CDK bootstrap.

- **Deterministic Entrypoint (`main.py`)**:
  ```python
  from bedrock_agentcore.runtime import BedrockAgentCoreApp

  app = BedrockAgentCoreApp()


  @app.entrypoint
  def invoke(payload, context=None):
      prompt = ""
      if isinstance(payload, dict):
          prompt = payload.get("prompt", "")
      elif isinstance(payload, str):
          prompt = payload

      if prompt == "PING":
          return {"result": "AGENTCORE_OK"}
      return {"result": "UNKNOWN_PROMPT", "received": prompt}


  if __name__ == "__main__":
      app.run()
  ```
- **Deployment Command**:
  ```powershell
  $env:AWS_PROFILE="stilldone-p01"; $env:AWS_DEFAULT_REGION="us-east-1"; $env:AWS_REGION="us-east-1"; npx @aws/agentcore deploy -y -v
  ```
- **Deployment Timestamp**: `2026-09-28T19:35:19Z`
- **Exit Code**: `0` (SUCCESS)
- **Deployment Attempts**: Exactly `1`
- **Read-Back Runtime Status (`aws bedrock-agentcore-control get-agent-runtime`)**:
  - `status`: **`READY`**
  - `agentRuntimeArn`: `arn:aws:bedrock-agentcore:us-east-1:[REDACTED_ACCOUNT_ID]:runtime/[REDACTED_RUNTIME_ID]`
  - `platformVersion`: **`V1`**
  - `runtimeVersion`: **`PYTHON_3_14`**
  - `networkMode`: `PUBLIC`

---

## 6. Repair Cycle: Data-Plane Invocation & Deterministic Acceptance

To prevent Windows PowerShell JSON quoting alterations, the payload was passed via a binary file using the official AWS Bedrock AgentCore data-plane CLI:

- **Payload File (`payload.json`)**:
  ```json
  {"prompt":"PING"}
  ```
- **Invocation Command**:
  ```powershell
  aws bedrock-agentcore invoke-agent-runtime `
    --agent-runtime-arn "arn:aws:bedrock-agentcore:us-east-1:[REDACTED_ACCOUNT_ID]:runtime/[REDACTED_RUNTIME_ID]" `
    --runtime-session-id "[REDACTED_SESSION_ID]" `
    --qualifier DEFAULT `
    --content-type application/json `
    --accept application/json `
    --payload fileb://payload.json `
    --profile stilldone-p01 `
    --region us-east-1 `
    response.json
  ```
- **Invocation Timestamp**: `2026-09-28T19:35:54Z`
- **Invocation Attempts**: Exactly `1` (zero retries)
- **API Response**:
  ```json
  {
      "runtimeSessionId": "[REDACTED_SESSION_ID]",
      "contentType": "application/json",
      "statusCode": 200
  }
  ```
- **Deterministic Response Payload (`response.json`)**:
  ```json
  {"result": "AGENTCORE_OK"}
  ```
- **Acceptance Outcome**:
  - HTTP 200: **`PASS`**
  - Semantic Response `{"result": "AGENTCORE_OK"}`: **`PASS`**
  - Foundation Model / LLM Calls inside Runtime: **`Strictly 0`**
  - External HTTP / MCP / Google Calls: **`Strictly 0`**

---

## 7. Mandatory Teardown & Residual-Resource Verification

Teardown was executed immediately following the repair invocation:

1. **Teardown Deployment**:
   - `npx @aws/agentcore remove all -y`
   - `npx @aws/agentcore deploy -y -v`
   - CloudFormation stack deleted `UPDATE_COMPLETE` -> `DELETE_COMPLETE`.
2. **Read-Only Verification**:
   - `aws bedrock-agentcore-control list-agent-runtimes --region us-east-1`: returned `{ "agentRuntimes": [] }` (**0 active runtimes**).
   - `aws cloudformation describe-stacks --stack-name AgentCore-p01agent-default`: returned `ValidationError: Stack with id AgentCore-p01agent-default does not exist`.
3. **S3 CodeZip Asset Cleanup**:
   - `aws s3 rm s3://[REDACTED_BUCKET]/[REDACTED_CODEZIP].zip` executed and verified.
   - S3 asset bucket audited: 0 zip assets remaining.
4. **Local Scratch Deletion**:
   - Ephemeral scratch directory `[REDACTED_SCRATCH_DIR]` removed completely from disk.
5. **AWS Session Logout**:
   - `aws logout --profile stilldone-p01` executed and verified.
   - Subsequent `aws sts get-caller-identity` confirmed credentials revoked (`Error loading login session token`).

### Residual Resource Truth Summary

| Resource Category | State |
|---|---|
| Runtime-Specific Application Stack (`AgentCore-p01agent-default`) | **REMOVED** (0 active) |
| Runtime-Specific Bedrock AgentCore Runtime | **REMOVED** (0 active) |
| Runtime-Specific IAM Execution Role & Policy | **REMOVED** (0 active) |
| Runtime-Specific S3 CodeZip Asset | **DELETED** (0 active) |
| Shared CDK Bootstrap Infrastructure (`CDKToolkit`) | **RETAINED** (`CREATED_DURING_P01_04`) |

---

## 8. Billing Truth

- **Cumulative Usage-Derived Conservative Gross Estimate**: `~$0.00337 USD` (well below `$0.10` limit).
- **Actual Billed Request / Runtime Cost**: `NOT_OBSERVED / UNKNOWN` (AWS Billing console updates asynchronously; post-call charges not immediately observed in billing dashboards).
- **Personal-Spend Delta**: `NOT_OBSERVED / UNKNOWN` (`$0.00` target preserved via promotional credits).

---

## 9. Provenance & State

- **Evidence Provenance**: `LIVE_AWS + LIVE_AGENTCORE_RUNTIME`
- **NOT_RUN Items**:
  - Live Google Calendar / Tasks read (P-01.05) — `PENDING / NOT_STARTED`
  - Live Open-Meteo call (P-01.06) — `NOT_RUN`
  - Live MCP Streamable HTTP proof (P-01.07) — `NOT_RUN`
  - P-02 domain model implementations — `NOT_RUN`
- **Status Classification**: `DONE — awaiting independent QA PASS`
