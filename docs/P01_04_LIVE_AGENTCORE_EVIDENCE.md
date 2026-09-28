# P-01.04 Live AgentCore Runtime Feasibility Evidence

**Date & Time (UTC)**: `2026-09-28T19:14:00Z`  
**Governing Rule**: [AGENTS.md](../AGENTS.md) § 1–24; [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md)  
**Task**: `P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence`  
**Status**: `DONE — awaiting independent QA review` (Runtime deployment, READY state, remote execution, and teardown proven; single invocation executed; semantic payload mismatch noted)  

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

## 2. Pre-Deploy Cost Gate & $0.10 Financial Boundary

- **Operator Authorized Gross Ceiling**: `$0.10 USD`
- **Target Personal Spend**: `$0.00 USD`
- **Conservative Gross Cost Estimation**:
  - Active vCPU (1 minute conservative @ $0.0895/vCPU-hr): `$0.00149 USD`
  - Active Memory (1 GB for 1 minute @ $0.00945/GB-hr): `$0.00016 USD`
  - S3 CodeZip storage (31.7 MB for < 1 hour @ $0.023/GB-month): `$0.000001 USD`
  - S3 requests (PUT/GET): `$0.00001 USD`
  - CloudWatch Logs ingestion (< 10 KB @ $0.50/GB): `$0.000005 USD`
  - Total Conservative Expected Cost: `~$0.00168 USD` (well below $0.10 limit)
- **Financial Decision**: **`COST_GATE = PASS`**

---

## 3. Read-Only Preflight Verification

- Authenticated Caller: `arn:aws:iam::[REDACTED]:root` via `aws login --profile stilldone-p01 --remote`.
- Region: `us-east-1`.
- AgentCore Service Accessibility: `aws bedrock-agentcore-control list-agent-runtimes --region us-east-1` returned HTTP 200 with `{ "agentRuntimes": [] }`.
- CDK Bootstrap Pre-Existing Check: `aws cloudformation describe-stacks --stack-name CDKToolkit` returned `Stack with id CDKToolkit does not exist`. CDK bootstrap was **NOT PREEXISTING**.

---

## 4. Mandatory Dry-Run & Resource Planning

Dry-run command:
```bash
agentcore deploy --dry-run -y
```
Synthesized CloudFormation template (`AgentCore-p01agent-default.template.json`) inspection:
- `ApplicationAgentP01agentRuntimeBC9CB6FB`: `AWS::BedrockAgentCore::Runtime`
  - CodeConfiguration: Runtime `PYTHON_3_13`, EntryPoint `["opentelemetry-instrument", "main.py"]`, S3 CodeZip asset.
  - NetworkConfiguration: `PUBLIC`
- `ApplicationAgentP01agentRuntimeExecutionRole5083B770`: `AWS::IAM::Role`
- `ApplicationAgentP01agentRuntimeExecutionRoleDefaultPolicyD42759CE`: `AWS::IAM::Policy`
- `CDKMetadata`: `AWS::CDK::Metadata`

**Forbidden Resource Audit**:
- ECR / container builds: `0` (CodeZip build used)
- EC2 Runtime Instances: `0` (Serverless microVM used)
- Gateways / MCP servers: `0`
- Memory stores / vector databases: `0`
- Browser tools / Code Interpreter / Cognito / Lambda tools: `0`
- Foundation Models: `0`

**Dry-Run Decision**: **`DRY_RUN = PASS`**

---

## 5. Deployment Evidence (Single Attempt)

- Deployment Command: `npx @aws/agentcore deploy -y -v`
- Execution Timestamp: `2026-09-28T22:07:20Z` (CDK build & synthesis: ~13s; CloudFormation stack deployment: ~1m 56s)
- Exit Code: `0` (SUCCESS)
- Created CloudFormation Stack: `AgentCore-p01agent-default` (Status: `CREATE_COMPLETE` at 22:09:16)
- Created AgentCore Runtime ID: `p01agent_p01agent-or9Fbj3Agb` (Status: `CREATE_COMPLETE` at 22:09:14)
- Runtime Read-Back Verification (`aws bedrock-agentcore-control get-agent-runtime`):
  - `status`: **`READY`**
  - `agentRuntimeArn`: `arn:aws:bedrock-agentcore:us-east-1:[REDACTED]:runtime/p01agent_p01agent-or9Fbj3Agb`
  - `platformVersion`: **`V1`** (observed from live service response)
  - `runtimeVersion`: **`PYTHON_3_13`**
  - `networkMode`: `PUBLIC`
  - `createdAt`: `2026-09-28T19:08:56.681690+00:00`
  - `lastUpdatedAt`: `2026-09-28T19:09:10.873971+00:00`

---

## 6. Remote Invocation Evidence (Exactly One Attempt)

- Invocation Command: `npx @aws/agentcore invoke --prompt '{"prompt": "PING"}' --json`
- Timestamp: `2026-09-28T19:10:14.477Z`
- Exit Code: `0`
- Invocation Duration: `6720 ms` (Total process elapsed: `14711 ms`)
- Session ID: `d6f6360b-0ce3-48a3-99ad-1af6822f5f2c`
- Invocation Request Log:
  ```json
  {
    "timestamp": "2026-09-28T19:10:14.484Z",
    "agent": "p01agent",
    "runtimeArn": "arn:aws:bedrock-agentcore:us-east-1:[REDACTED]:runtime/p01agent_p01agent-or9Fbj3Agb",
    "region": "us-east-1",
    "prompt": "{prompt: PING}"
  }
  ```
- Invocation Response Log:
  ```json
  {
    "timestamp": "2026-09-28T19:10:21.205Z",
    "durationMs": 6720,
    "success": true,
    "response": "UNKNOWN_PROMPT"
  }
  ```
- **Deterministic Code Execution Analysis**:
  - The deployed Python application code in `main.py` defined:
    ```python
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
    ```
  - PowerShell argument evaluation unquoted `'{"prompt": "PING"}'` to `{prompt: PING}`. The AgentCore CLI packaged this as `{"prompt": "{prompt: PING}"}`.
  - The remote AgentCore Runtime received the payload, executed our Python handler, evaluated `prompt == "PING"` as False (received `"{prompt: PING}"`), and executed the deterministic `else` branch returning `"UNKNOWN_PROMPT"`.
  - This proves end-to-end execution of custom Python code on the remote AWS AgentCore Runtime.
- **Model Invocations Inside Runtime**: **`0`** (strictly zero foundation models or LLMs called).
- **Secondary Invocation / Retries**: **`0`** (strictly zero retries per zero-retry contract).

---

## 7. Teardown & Cleanup Evidence

Teardown was executed immediately in the same cycle:
1. `npx @aws/agentcore remove all -y`: Reset project configuration to empty state.
2. `npx @aws/agentcore deploy -y -v`: Applied teardown CloudFormation changeset.
   - Deleted `AWS::BedrockAgentCore::Runtime` (Status: `DELETE_COMPLETE`).
   - Deleted `AWS::IAM::Role` (Status: `DELETE_COMPLETE`).
   - Deleted `AWS::CloudFormation::Stack` `AgentCore-p01agent-default` (Status: `DELETE_COMPLETE`).
3. Post-cleanup Verification:
   - `aws bedrock-agentcore-control list-agent-runtimes --region us-east-1` returned `{ "agentRuntimes": [] }` (Zero runtimes active).
   - `aws cloudformation describe-stacks --stack-name AgentCore-p01agent-default` returned `Stack with id AgentCore-p01agent-default does not exist`.
4. S3 Asset Cleanup:
   - Deleted task-created CodeZip asset `30d092352e61fafd363357da8e4829026d8f5ab615768a1366237e8392e6ec89.zip` from CDK bucket `cdk-hnb659fds-assets-[REDACTED]-us-east-1`.
5. CDK Bootstrap Infrastructure Status:
   - State: `CREATED_DURING_P01_04` (Shared account-level CDK bootstrap infrastructure; S3 bucket + IAM roles preserved per Section 16).
6. AWS Logout:
   - `aws logout --profile stilldone-p01` executed and verified. Cached credentials removed.
7. Local Scratch Cleanup:
   - Deleted entire ephemeral directory `C:\Users\MEHMET\.gemini\antigravity\scratch\scratch_agentcore_probe`.
   - StillDone repository working tree audited: 0 uncommitted files, 0 secrets, 0 AgentCore dependencies added.

---

## 8. Billing Truth

- **Usage-Derived Estimated Gross Total Cost**: `~$0.00168 USD` (well below $0.10 gross limit).
- **Fresh Billing / Credit State**: Not separately read from AWS Billing console in this cycle.
- **Actual Billed Request / Runtime Cost**: `NOT_OBSERVED / UNKNOWN` (AWS Billing asynchronously updates every 8–12 hours).
- **Personal-Spend Delta**: `NOT_OBSERVED / UNKNOWN` ($0.00 target preserved via hackathon promotional credits).

---

## 9. Provenance & State

- **Evidence Provenance**: `LIVE_AWS + LIVE_AGENTCORE_RUNTIME`
- **NOT_RUN Items**:
  - Live Google Calendar / Tasks read (P-01.05) — `PENDING / NOT_STARTED`
  - Live Open-Meteo call (P-01.06) — `NOT_RUN`
  - Live MCP Streamable HTTP proof (P-01.07) — `NOT_RUN`
  - P-02 domain model implementations — `NOT_RUN`
- **Status Classification**: `DONE — awaiting independent QA review` (executor completed real deployment, live execution, and full teardown; semantic response `"UNKNOWN_PROMPT"` submitted for QA assessment).
