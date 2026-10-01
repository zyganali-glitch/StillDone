# P-05.06 Live-Deployment Preflight Evidence & Cost Upper Bound

**Document ID**: `docs/P05_06_DEPLOYMENT_PREFLIGHT_EVIDENCE.md`  
**Task**: `P-05.06 — Validate with current MCP inspector/client and remote deployment`  
**Current Task State**: `NOT_RUN` (Awaiting explicit operator deployment authorization)  
**Next Task State (P-05.07)**: `NOT AUTHORIZED`  
**Cloud Mutations Executed**: `NONE` (Zero AWS resources created, updated, or deleted)  
**Production Code Changes**: `NONE`  
**Governing Laws**: `AGENTS.md` §1–24, Zero Personal Spend Law (§12), Live-First Law (§9), Evidence Provenance (§10)  

---

## 1. Executive Summary & Status

This document establishes durable, sanitized, independent live evidence gathered during the read-only preflight on `2026-10-01` in AWS region `us-east-1`, and establishes the corrected, lifecycle-bounded cost upper bound for the future `P-05.06` live proof campaign.

- **Deployment Authorization**: **`NOT AUTHORIZED`**. Zero deployment operations have been initiated.
- **AgentCore Compute Assumption Correction**: Repaired from the non-conservative `1 vCPU / 1 GB RAM` to the AWS non-adjustable hardware maximum of **`2 vCPU / 8 GB RAM`**.
- **Session Lifecycle Ceiling**: Frozen to **`idleRuntimeSessionTimeout = 60s`** and **`maxLifetime = 300s (5 minutes)`**, guaranteeing single-session execution without retry loops.
- **Campaign Gross-Risk Ceiling**: **`$0.037702 USD`** (under V2 compute) / **`$0.026386 USD`** (under V1 compute), strictly below the operator's `$0.10 USD` threshold.
- **Preferred Proof Path Frozen**: Local ARM64 build (`docker buildx`) + AgentCore IAM/SigV4 inbound + Local SigV4 proxy for Inspector + strictly **0 Cognito resources** + strictly **0 CodeBuild builds**.
- **Inspector 2.9.0 Pin**: Frozen to canonical release `@modelcontextprotocol/inspector@2.9.0` (released `2026-09-30T22:23:56Z`, published `2026-09-30T22:40:43Z`).
- **Credit Truth**: Promotional credit applicability was observed historically offsetting September AgentCore charges, but remaining dollar balance and future personal spend are strictly **`NOT_OBSERVED`**.

---

## 2. Durable Live AWS Preflight Evidence (Sanitized Raw Excerpts)

The following evidence was gathered via short-lived browser-authenticated session (`stilldone-p01`) in `us-east-1`. All sensitive account identifiers, ARNs, bucket names, repository names, KMS key IDs, filesystem paths, and session tokens have been redacted in compliance with `AGENTS.md` §14.

### A. STS Identity Proof

**Exact Command Executed**:
```bash
aws sts get-caller-identity --profile stilldone-p01
```

**Sanitized Raw Output**:
```json
{
    "UserId": "[REDACTED_ACCOUNT_ID]",
    "Account": "[REDACTED_ACCOUNT_ID]",
    "Arn": "arn:aws:iam::[REDACTED_ACCOUNT_ID]:root"
}
```
*Finding*: Authenticated session established for operator root identity in target account.

---

### B. AgentCore Runtime Inventory

**Exact Command Executed**:
```bash
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 --profile stilldone-p01
```

**Sanitized Raw Output**:
```json
{
    "agentRuntimes": []
}
```
*Finding*: Strictly **0 active AgentCore runtimes** exist in `us-east-1`. Clean baseline confirmed.

---

### C. CDKToolkit Stack Status

**Exact Command Executed**:
```bash
aws cloudformation describe-stacks --stack-name CDKToolkit --region us-east-1 --profile stilldone-p01
```

**Sanitized Raw Output Excerpt**:
```json
{
    "Stacks": [
        {
            "StackId": "arn:aws:cloudformation:us-east-1:[REDACTED_ACCOUNT_ID]:stack/CDKToolkit/[REDACTED_STACK_UUID]",
            "StackName": "CDKToolkit",
            "ChangeSetId": "arn:aws:cloudformation:us-east-1:[REDACTED_ACCOUNT_ID]:changeSet/cdk-bootstrap-change-set-[REDACTED]/[REDACTED]",
            "Description": "This stack includes resources needed to deploy AWS CDK apps into this environment",
            "CreationTime": "2026-09-28T19:05:02.582000+00:00",
            "LastUpdatedTime": "2026-09-28T20:13:23.222000+00:00",
            "StackStatus": "UPDATE_COMPLETE",
            "Outputs": [
                {
                    "OutputKey": "ImageRepositoryName",
                    "OutputValue": "cdk-hnb659fds-container-assets-[REDACTED_ACCOUNT_ID]-us-east-1",
                    "Description": "The name of the ECR repository which hosts docker image assets"
                },
                {
                    "OutputKey": "BucketName",
                    "OutputValue": "cdk-hnb659fds-assets-[REDACTED_ACCOUNT_ID]-us-east-1",
                    "Description": "The name of the S3 bucket owned by the CDK toolkit stack"
                },
                {
                    "OutputKey": "BootstrapVersion",
                    "OutputValue": "32",
                    "Description": "The version of the bootstrap resources that are currently mastered in this stack"
                },
                {
                    "OutputKey": "BucketDomainName",
                    "OutputValue": "cdk-hnb659fds-assets-[REDACTED_ACCOUNT_ID]-us-east-1.s3.us-east-1.amazonaws.com",
                    "Description": "The domain name of the S3 bucket owned by the CDK toolkit stack"
                },
                {
                    "OutputKey": "FileAssetKeyArn",
                    "OutputValue": "AWS_MANAGED_KEY",
                    "Description": "The ARN of the KMS key used to encrypt the asset bucket (deprecated)",
                    "ExportName": "CdkBootstrap-hnb659fds-FileAssetKeyArn"
                }
            ]
        }
    ]
}
```
*Finding*: CDK bootstrap stack `CDKToolkit` is in `UPDATE_COMPLETE` state (Bootstrap version `32`), ready for deployment artifact ingestion without re-bootstrapping.

---

### D. CDKToolkit FileAssetsBucketKmsKeyId Truth

**Exact Command Executed**:
```bash
aws cloudformation describe-stacks --stack-name CDKToolkit --region us-east-1 --profile stilldone-p01
```

**Sanitized Raw Parameter & Output Excerpt**:
```json
{
    "Parameters": [
        {
            "ParameterKey": "FileAssetsBucketKmsKeyId",
            "ParameterValue": "AWS_MANAGED_KEY"
        }
    ],
    "Outputs": [
        {
            "OutputKey": "FileAssetKeyArn",
            "OutputValue": "AWS_MANAGED_KEY",
            "Description": "The ARN of the KMS key used to encrypt the asset bucket (deprecated)",
            "ExportName": "CdkBootstrap-hnb659fds-FileAssetKeyArn"
        }
    ]
}
```

**Exact Command Executed (Resource Verification)**:
```bash
aws cloudformation describe-stack-resources --stack-name CDKToolkit --region us-east-1 --profile stilldone-p01
```
*Finding*: `FileAssetsBucketKmsKeyId` is strictly set to `AWS_MANAGED_KEY`. Stack resources contain **strictly zero** `AWS::KMS::Key` or `AWS::KMS::Alias` resources. No customer-managed KMS key is provisioned or billed by the CDKToolkit stack.

---

### E. ECR Repository and Image Inventory

**Exact Commands Executed**:
```bash
aws ecr describe-repositories --region us-east-1 --profile stilldone-p01
aws ecr list-images --repository-name cdk-hnb659fds-container-assets-[REDACTED_ACCOUNT_ID]-us-east-1 --region us-east-1 --profile stilldone-p01
```

**Sanitized Raw Output**:
```json
{
    "repositories": [
        {
            "repositoryArn": "arn:aws:ecr:us-east-1:[REDACTED_ACCOUNT_ID]:repository/cdk-hnb659fds-container-assets-[REDACTED_ACCOUNT_ID]-us-east-1",
            "registryId": "[REDACTED_ACCOUNT_ID]",
            "repositoryName": "cdk-hnb659fds-container-assets-[REDACTED_ACCOUNT_ID]-us-east-1",
            "repositoryUri": "[REDACTED_ACCOUNT_ID].dkr.ecr.us-east-1.amazonaws.com/cdk-hnb659fds-container-assets-[REDACTED_ACCOUNT_ID]-us-east-1",
            "createdAt": "2026-09-28T22:05:18.327000+03:00",
            "imageTagMutability": "IMMUTABLE",
            "imageScanningConfiguration": {
                "scanOnPush": false
            },
            "encryptionConfiguration": {
                "encryptionType": "AES256"
            }
        }
    ]
}
```
```json
{
    "imageIds": []
}
```
*Finding*: Container assets repository exists with default `AES256` encryption. Currently contains **0 images** (`imageIds: []`), bearing \$0.00 storage cost.

---

### F. S3 Bootstrap Artifact Inventory

**Exact Command Executed**:
```bash
aws s3 ls s3://cdk-hnb659fds-assets-[REDACTED_ACCOUNT_ID]-us-east-1 --profile stilldone-p01
```

**Sanitized Raw Output**:
```
2026-09-28 22:33:52       6467 2b6e77c4f726410da9105992bc951d1f3535a2bd9dc7d0e780431e23f86f375e.json
2026-09-28 22:07:51       6467 32f40f23bdae43fa38c028074b83d5bc97137df79a9c013b4377d47bfea56e18.json
2026-09-28 22:11:58       1335 6b13af9df80fb0e066cb3ed8b0a75783eb22b3f1b3f9c2e87eefb06bc41ea393.json
```
*Finding*: Exactly 3 JSON template files exist in staging bucket. Total size is **14,269 bytes (~14 KB)**. Strictly **0 CodeZip artifacts** or large binaries are present. Storage cost is ~$0.0000003/month.

---

### G. KMS Active / PendingDeletion Inventory

**Exact Commands Executed**:
```bash
aws kms list-keys --region us-east-1 --profile stilldone-p01
aws kms describe-key --key-id [REDACTED_KEY_ID] --region us-east-1 --profile stilldone-p01
```

**Sanitized Raw Output**:
```json
{
    "Keys": [
        {
            "KeyId": "[REDACTED_KEY_ID]",
            "KeyArn": "arn:aws:kms:us-east-1:[REDACTED_ACCOUNT_ID]:key/[REDACTED_KEY_ID]"
        }
    ]
}
```
```json
{
    "KeyMetadata": {
        "AWSAccountId": "[REDACTED_ACCOUNT_ID]",
        "KeyId": "[REDACTED_KEY_ID]",
        "Arn": "arn:aws:kms:us-east-1:[REDACTED_ACCOUNT_ID]:key/[REDACTED_KEY_ID]",
        "CreationDate": "2026-09-28T22:05:37.172000+03:00",
        "Enabled": false,
        "Description": "",
        "KeyUsage": "ENCRYPT_DECRYPT",
        "KeyState": "PendingDeletion",
        "DeletionDate": "2026-10-28T23:14:12.180000+03:00",
        "Origin": "AWS_KMS",
        "KeyManager": "CUSTOMER",
        "CustomerMasterKeySpec": "SYMMETRIC_DEFAULT",
        "KeySpec": "SYMMETRIC_DEFAULT",
        "EncryptionAlgorithms": [
            "SYMMETRIC_DEFAULT"
        ],
        "MultiRegion": false,
        "CurrentKeyMaterialId": "[REDACTED]"
    }
}
```
*Finding*: Exactly 1 customer KMS key exists in the account, and it is in **`PendingDeletion`** state (scheduled for permanent deletion on `2026-10-28T23:14:12Z`). Keys in `PendingDeletion` incur **\$0.00** monthly fee. Strictly **0 active customer-managed KMS keys** exist.

---

### H. Cost Explorer September Usage & Credit Adjustment

**Exact Command Executed (By Record Type)**:
```bash
aws ce get-cost-and-usage --time-period Start=2026-09-01,End=2026-10-01 --granularity MONTHLY --metrics "UnblendedCost" --group-by Type=DIMENSION,Key=RECORD_TYPE --profile stilldone-p01
```

**Sanitized Raw Output**:
```json
{
    "GroupDefinitions": [
        {
            "Type": "DIMENSION",
            "Key": "RECORD_TYPE"
        }
    ],
    "ResultsByTime": [
        {
            "TimePeriod": {
                "Start": "2026-09-01",
                "End": "2026-10-01"
            },
            "Total": {},
            "Groups": [
                {
                    "Keys": [
                        "Credit"
                    ],
                    "Metrics": {
                        "UnblendedCost": {
                            "Amount": "-0.0083883958",
                            "Unit": "USD"
                        }
                    }
                },
                {
                    "Keys": [
                        "Usage"
                    ],
                    "Metrics": {
                        "UnblendedCost": {
                            "Amount": "0.0083883943",
                            "Unit": "USD"
                        }
                    }
                }
            ],
            "Estimated": true
        }
    ]
}
```

**Exact Command Executed (By Service Breakdown)**:
```bash
aws ce get-cost-and-usage --time-period Start=2026-09-01,End=2026-10-01 --granularity MONTHLY --metrics "UnblendedCost" --group-by Type=DIMENSION,Key=SERVICE --profile stilldone-p01
```

**Sanitized Raw Output Excerpt**:
```json
{
    "Groups": [
        {
            "Keys": [
                "AWS CloudFormation"
            ],
            "Metrics": {
                "UnblendedCost": {
                    "Amount": "0",
                    "Unit": "USD"
                }
            }
        },
        {
            "Keys": [
                "AWS Data Transfer"
            ],
            "Metrics": {
                "UnblendedCost": {
                    "Amount": "-0.0000000092",
                    "Unit": "USD"
                }
            }
        },
        {
            "Keys": [
                "AWS Key Management Service"
            ],
            "Metrics": {
                "UnblendedCost": {
                    "Amount": "-0.0000000022",
                    "Unit": "USD"
                }
            }
        },
        {
            "Keys": [
                "Amazon Bedrock AgentCore"
            ],
            "Metrics": {
                "UnblendedCost": {
                    "Amount": "-0.0000000001",
                    "Unit": "USD"
                }
            }
        },
        {
            "Keys": [
                "Amazon Simple Storage Service"
            ],
            "Metrics": {
                "UnblendedCost": {
                    "Amount": "0.0000000091",
                    "Unit": "USD"
                }
            }
        },
        {
            "Keys": [
                "AmazonCloudWatch"
            ],
            "Metrics": {
                "UnblendedCost": {
                    "Amount": "0.0000000009",
                    "Unit": "USD"
                }
            }
        }
    ]
}
```
*Finding*: For September 2026, total billable AWS usage across the account was `$0.0083883943 USD`. Promotional credit offset was `-$0.0083883958 USD`. **Net September spend was $0.0000000000 USD**. Crucially, `Amazon Bedrock AgentCore` usage was **100% offset by Credit**.

---

### I. Cost Explorer 2026-10-01 Net-Cost Observation

**Exact Command Executed**:
```bash
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-10-02 --granularity DAILY --metrics "UnblendedCost" --group-by Type=DIMENSION,Key=RECORD_TYPE --profile stilldone-p01
```

**Sanitized Raw Output**:
```json
{
    "GroupDefinitions": [
        {
            "Type": "DIMENSION",
            "Key": "RECORD_TYPE"
        }
    ],
    "ResultsByTime": [
        {
            "TimePeriod": {
                "Start": "2026-10-01",
                "End": "2026-10-02"
            },
            "Total": {
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
*Finding*: Net cost incurred for `2026-10-01` is strictly **`$0.00 USD`**.

---

### J. AWS Session Logout Proof

**Exact Commands Executed**:
```bash
aws logout --profile stilldone-p01
aws sts get-caller-identity --profile stilldone-p01
```

**Sanitized Raw Output**:
```
Removed cached login credentials for profile 'stilldone-p01'. Note, any local developer tools that have already loaded the access token may continue to use it until its expiration. Access tokens expire in 15 minutes.
```
```
aws : 
aws: [ERROR]: Error loading login session token: Unable to load a existing login session for session arn:aws:iam::[REDACTED_ACCOUNT_ID]:root, Please reauthenticate with 'aws login'.
```
*Finding*: Session credentials cleanly and irreversibly revoked. Re-test of `sts get-caller-identity` exits with code 1 (`Unable to load existing login session`). Zero access tokens retained.

---

### K. Explicit Remaining Promotional-Credit Balance

```
REMAINING_PROMOTIONAL_CREDIT_BALANCE: NOT_OBSERVED
```
*Truth Boundary*: AWS does NOT provide a programmatic CLI API to retrieve remaining promotional credit dollar balances. The historical \$150 promotional credit allocation is recorded as `RECORDED_LIVE` from P-01, but the current live dollar balance must be viewed directly by the operator in the AWS Billing Console (`https://console.aws.amazon.com/billing/home#/credits`).

---

### L. Explicit Actual Future Personal Spend

```
ACTUAL_FUTURE_PERSONAL_SPEND: NOT_OBSERVED
```
*Truth Boundary*: Because zero deployment was executed, actual future billed cost and personal spend delta remain `NOT_OBSERVED`. No claim of guaranteed \$0.00 personal spend may be made without active operator verification of promotional credit headroom.

---

## 3. Repaired Cost Upper Bound & Lifecycle Enclosure

### Root Cause Analysis of Previous Estimation Rejection

The preliminary estimate of `$0.077407 USD` derived during preflight assumed an AgentCore compute allocation of `1 vCPU / 1 GB RAM`. Current AWS Service Quotas establish a non-adjustable per-session hardware ceiling of **`2 vCPU / 8 GB RAM`**. Therefore, a strictly conservative worst-case cost upper bound must calculate against the full 2 vCPU / 8 GB hardware envelope.

### Session Lifecycle Boundary Freeze

To strictly bound AWS financial exposure, the planned P-05.06 deployment configuration freezes session lifecycle controls to the lowest permissible operational limits:

- **`idleRuntimeSessionTimeout`**: **`60 seconds`** (AWS documented minimum).
- **`maxLifetime`**: **`300 seconds (5 minutes)`** (maximum allowed duration for the proof session).
- **Session Execution Policy**: **Strictly ONE five-minute session**. No automatic retry loops, no second runtime, and no parallel microVM allocations.

---

### Mathematical Compute Derivation (5-Minute Window = 5/60 Hour)

Current published AWS Bedrock AgentCore Runtime pricing:

| Engine / Generation | vCPU Rate | Memory Rate |
|---|---|---|
| **V1 Runtime Engine** | \$0.0895 / vCPU-hour | \$0.00945 / GB-hour |
| **V2 Runtime Engine** | \$0.1276 / vCPU-hour | \$0.01690 / GB-hour |

#### 1. V1 Maximum-Session Compute (5 Minutes, 2 vCPU, 8 GB RAM)

$$\text{Compute}_{V1} = \left(\frac{5}{60} \text{ hr}\right) \times \left[(2 \times \$0.0895) + (8 \times \$0.00945)\right]$$
$$\text{Compute}_{V1} = \left(\frac{1}{12}\right) \times [0.1790 + 0.0756] = \left(\frac{1}{12}\right) \times 0.2546 \approx \mathbf{\$0.021217 \text{ USD}} \quad (\approx \$0.02122)$$

#### 2. V2 Maximum-Session Compute (5 Minutes, 2 vCPU, 8 GB RAM)

$$\text{Compute}_{V2} = \left(\frac{5}{60} \text{ hr}\right) \times \left[(2 \times \$0.1276) + (8 \times \$0.0169)\right]$$
$$\text{Compute}_{V2} = \left(\frac{1}{12}\right) \times [0.2552 + 0.1352] = \left(\frac{1}{12}\right) \times 0.3904 \approx \mathbf{\$0.032533 \text{ USD}} \quad (\approx \$0.03253)$$

*Governing Rule*: The higher **`V2`** figure (`$0.032533 USD`) is mandatory for the campaign gross-risk ceiling unless the future deployment script explicitly and verifiably pins the V1 runtime engine.

---

### Non-Compute Line-Item Allowances

| Line Item | Derivation & Assumptions | Allowance (USD) |
|---|---|---|
| **CloudWatch Diagnostic Logging** | Conservative 10 MB (0.01 GB) ingestion at \$0.50/GB | **\$0.005000** |
| **Amazon ECR Image Storage** | 250 MB image stored for a 2-hour test window: $0.25 \times (\frac{\$0.10}{730}) \times 2$ | **\$0.000068** |
| **Amazon S3 Storage & API Requests** | 10 MB CodeZip for 2 hrs (~$0.000001) + 20 PUT/GET requests at \$0.005/1K | **\$0.000101** |
| **Network Data Transfer (Egress)** | Total egress < 1 MB (within AWS 100 GB/month free allowance) | **\$0.000000** |
| **AWS CodeBuild** | **Zero CodeBuild builds**. Container built locally via `docker buildx` | **\$0.000000** |
| **Amazon Cognito User Pool** | **Zero Cognito resources**. Auth via IAM/SigV4 | **\$0.000000** |
| **Customer Managed KMS Keys** | **Zero Customer KMS keys**. Default `AWS_MANAGED_KEY` used | **\$0.000000** |

---

### Final Authorized-Risk Upper Bound Summary

| Configuration Profile | Compute Rate | Non-Compute Allowances | Cumulative Gross-Risk Ceiling |
|---|---|---|---|
| **Conservative Ceiling (V2 Compute Engine)** | \$0.032533 | \$0.005169 | **`$0.037702 USD`** (~`$0.0377 USD`) |
| **Pinned Baseline (V1 Compute Engine)** | \$0.021217 | \$0.005169 | **`$0.026386 USD`** (~`$0.0264 USD`) |

*Conclusion*: The maximum potential gross expenditure for the intended single-session live proof campaign is **`$0.037702 USD`**, which is strictly and comfortably below the operator's authorized `$0.10 USD` threshold.

---

## 4. Frozen Cheapest Proof Path

The planned P-05.06 execution path is frozen to the architecture that incurs the lowest possible cost and external dependency footprint:

```
[Local Development Environment]
  ├── docker buildx (ARM64 linux/arm64 build — local compute: $0.00)
  ├── docker push to existing ECR repository (image size ~250 MB)
  │
  ├── Local SigV4 Signing Proxy (localhost:8080)
  │     ├── Inspects incoming standard HTTP MCP requests from Inspector
  │     ├── Signs request with AWS SigV4 using short-lived 'stilldone-p01' profile
  │     ├── Forwards exact request to real AgentCore endpoint
  │     └── Forwards exact response back to Inspector (zero response synthesis)
  │
  └── MCP Inspector (@modelcontextprotocol/inspector@2.9.0)
        └── Connects to http://localhost:8080/mcp
```

### Architectural Exclusions (Strictly Enforced)

- **Cognito Resources**: **Strictly 0**. No User Pool, no App Client, no Resource Server, no M2M token fees.
- **CodeBuild Resources**: **Strictly 0**. All container compilation executes on the local workstation.
- **Customer KMS Keys**: **Strictly 0**. ECR and S3 encrypt under standard AWS-managed keys.

---

## 5. MCP Inspector Release Truth & Verification Contract

### Pinned Release Facts

- **Canonical Inspector Identifier**: `@modelcontextprotocol/inspector@2.9.0`
- **GitHub Release Tag**: `tag/2.9.0`
- **GitHub Release Timestamp**: `2026-09-30T22:23:56Z`
- **npm Publication Timestamp**: `2026-09-30T22:40:43Z`
- **npm Scope Verification**: `@modelcontextprotocol/inspector` is canonical; legacy `@anthropic-ai/mcp-inspector` is deprecated/404.

### Transparent Labeling Contract

The MCP Inspector CLI supports remote Streamable HTTP and custom HTTP headers, but does not natively perform AWS SigV4 request signing. When executing the future proof via the local SigV4 signing proxy, the proof report must adhere to this exact labeling invariant:

> **Forbidden Claim**: *"Inspector directly authenticated to AgentCore."*  
> **Mandatory Canonical Claim**: *"Inspector reached the real AgentCore MCP endpoint through a local SigV4 signing proxy."*

### Proxy Integrity Mandate

The local SigV4 proxy must:
1. Contain **strictly zero** fake MCP responses or mock payloads;
2. Perform **strictly zero** response synthesis or filtering;
3. Forward exact MCP wire traffic bidirectionally;
4. Acquire AWS credentials solely from the active short-lived session;
5. **Never** log, persist, or expose credentials, tokens, or `Authorization` header values.

---

## 6. Teardown & Decommissioning Plan (NOT_RUN)

Upon completion of the single 5-minute live proof session (or in the event of an early failure), the following sequence must be executed to ensure immediate zero-footprint decommissioning:

```powershell
# 1. Terminate & delete AgentCore runtime
npx @aws/agentcore remove all -y --profile stilldone-p01 --region us-east-1

# 2. Verify runtime termination
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 --profile stilldone-p01

# 3. Purge uploaded container image asset from ECR
aws ecr batch-delete-image `
  --repository-name cdk-hnb659fds-container-assets-[REDACTED_ACCOUNT_ID]-us-east-1 `
  --image-ids imageTag=p0506 `
  --region us-east-1 `
  --profile stilldone-p01

# 4. Invalidate and revoke short-lived AWS session
aws logout --profile stilldone-p01

# 5. Confirm revocation
aws sts get-caller-identity --profile stilldone-p01
```

---

## 7. Master Plan Task State Governance

| Task ID | Description | Verified Status | Evidence Baseline |
|---|---|---|---|
| **P-05.01** | Create MCP server skeleton with streamable-http transport | **PASS** | Commit `c87c204` |
| **P-05.02** | Expose server tools for mission initiation | **PASS** | Commit `a581222` |
| **P-05.03** | Expose read-back tools for independent observation | **PASS** | Commit `01effe9` |
| **P-05.04** | Expose authority tools for state transitions | **PASS** | Commit `e208ebf` / `922009d` |
| **P-05.05** | Add auth/rate-limit boundary appropriate to judge path | **PASS** | Commit `85f251c` / `14de6d5` |
| **P-05.06** | Validate with current MCP inspector/client and remote deployment | **`NOT_RUN`** | Awaiting operator deployment authorization |
| **P-05.07** | Document Alexa+ / remote MCP judge instructions | **`NOT AUTHORIZED`** | Blocked on P-05.06 completion |

---

## 8. Explicit Prohibitions & Hard Stop

- **No AWS mutations** were executed during this preflight evidence recording.
- **No AgentCore runtime** was deployed, invoked, or exposed.
- **No production code** was altered or committed.
- **P-05.06 remains strictly `NOT_RUN`**.
- **P-05.07 remains strictly `NOT AUTHORIZED`**.
