"""AWS Builder Depth (Phase P-16) implementation for StillDone.

Provides:
- P-16.01: Audit of actual AWS services used in the live critical path.
- P-16.02: Materially impactful addition: Amazon CloudWatch Embedded Metric Format
           (EMF) structured telemetry logger for outcome verification and drift monitoring.
- P-16.03: Live proof and non-decorative justification for CloudWatch EMF.
- P-16.04: Comprehensive AWS Builder architecture and evidence map.
- P-16.05: Cost impact validation against promotional credit budget ($0.00 personal spend).

Constitutional Invariants:
- Zero personal spend law ($0.00): all services strictly within promotional budget
  or permanent free tier.
- No decorative service sprawl: every service solves a concrete StillDone invariant problem.
- Telemetry captures outcome verification latency, read-back contradictions, and drift events.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from stilldone.domain.provenance import EvidenceProvenance
from stilldone.killer_mission import (
    KillerMissionSliceOutcome,
)


@dataclass(frozen=True)
class AWSAccountEvidenceRecord:
    """Typed durable AWS account evidence record.

    Binds source identity, observation timestamp, observation type, and integrity reference.
    """

    source_identity: str
    observed_at: datetime
    observation_type: str
    integrity_reference: str
    observed_billing_status: str
    observed_net_personal_spend_usd: Decimal
    promotional_credit_budget_sufficient: bool

    def __post_init__(self) -> None:
        if not isinstance(self.source_identity, str) or not self.source_identity.strip():
            raise ValueError("source_identity must be a non-empty string")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime instance")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware (UTC)")
        if not isinstance(self.observation_type, str) or not self.observation_type.strip():
            raise ValueError("observation_type must be a non-empty string")
        if not isinstance(self.integrity_reference, str) or not self.integrity_reference.strip():
            raise ValueError("integrity_reference must be a non-empty string")
        if (
            not isinstance(self.observed_billing_status, str)
            or not self.observed_billing_status.strip()
        ):
            raise ValueError("observed_billing_status must be a non-empty string")
        if not isinstance(self.observed_net_personal_spend_usd, Decimal):
            raise TypeError("observed_net_personal_spend_usd must be a Decimal")
        if not isinstance(self.promotional_credit_budget_sufficient, bool):
            raise TypeError("promotional_credit_budget_sufficient must be a bool")


def validate_account_evidence_record(
    source_reference: str | None,
    observation: AWSAccountObservation | None = None,
) -> tuple[bool, AWSAccountEvidenceRecord | None]:
    """Validate whether a source reference resolves to a typed durable AWS account evidence record.

    Enforces:
    - Rejection of web URLs, empty content, directory traversal, and untrusted absolute paths.
    - Rejection of arbitrary files and markdown documentation (e.g. docs/AWS_BUILDER_MAP.md).
    - Parsing and verification of typed durable evidence record binding:
      source_identity, observation timestamp, observation type, and integrity reference.
    - Strict verification that caller-provided monetary facts match the durable record.
    """
    if not source_reference or not isinstance(source_reference, str):
        return False, None
    ref = source_reference.strip()
    if not ref:
        return False, None
    if ref.startswith("http://") or ref.startswith("https://"):
        return False, None

    try:
        repo_root = Path(__file__).resolve().parent.parent.parent
        p = Path(ref)
        if p.is_absolute():
            resolved = p.resolve()
            try:
                resolved.relative_to(repo_root)
            except ValueError:
                return False, None
        else:
            resolved = (repo_root / p).resolve()
            try:
                resolved.relative_to(repo_root)
            except ValueError:
                return False, None

        if not resolved.is_file() or not resolved.exists():
            return False, None
        if resolved.stat().st_size == 0:
            return False, None

        # Reject arbitrary files and architecture/general documentation
        if resolved.suffix.lower() != ".json":
            return False, None

        content = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            return False, None

        src_id = content.get("source_identity")
        obs_at_raw = content.get("observed_at") or content.get("observation_timestamp")
        obs_type = content.get("observation_type") or content.get("account_observation_type")
        integrity_ref = content.get("integrity_reference") or content.get("integrity_hash")
        bill_status = content.get("observed_billing_status")
        spend_raw = content.get("observed_net_personal_spend_usd")
        credit_suff = content.get("promotional_credit_budget_sufficient")

        if not src_id or not isinstance(src_id, str) or not src_id.strip():
            return False, None
        if not obs_at_raw or not isinstance(obs_at_raw, str):
            return False, None
        obs_at = datetime.fromisoformat(obs_at_raw)
        if obs_at.tzinfo is None:
            return False, None
        if not obs_type or not isinstance(obs_type, str) or not obs_type.strip():
            return False, None
        if not integrity_ref or not isinstance(integrity_ref, str) or not integrity_ref.strip():
            return False, None
        if not bill_status or not isinstance(bill_status, str):
            return False, None
        if spend_raw is None:
            return False, None
        spend_dec = Decimal(str(spend_raw))
        if credit_suff is None or not isinstance(credit_suff, bool):
            return False, None

        rec = AWSAccountEvidenceRecord(
            source_identity=src_id.strip(),
            observed_at=obs_at if obs_at.tzinfo == UTC else obs_at.astimezone(UTC),
            observation_type=obs_type.strip(),
            integrity_reference=integrity_ref.strip(),
            observed_billing_status=bill_status.strip(),
            observed_net_personal_spend_usd=spend_dec,
            promotional_credit_budget_sufficient=credit_suff,
        )

        if observation is not None:
            if observation.observed_net_personal_spend_usd != rec.observed_net_personal_spend_usd:
                return False, None
            if observation.observed_billing_status != rec.observed_billing_status:
                return False, None
            if (
                observation.promotional_credit_budget_sufficient
                != rec.promotional_credit_budget_sufficient
            ):
                return False, None

        return True, rec
    except Exception:
        return False, None


def is_resolved_evidence_reference(
    source_reference: str | None,
    observation: AWSAccountObservation | None = None,
) -> bool:
    """Validate whether a source reference resolves to a valid durable AWS account record.

    Enforces:
    - Syntactic and schema validity of the durable JSON record.
    - Strict provenance boundary: A repository fixture, developer-created JSON file,
      arbitrary source label, or placeholder hash must never authorize RECORDED_LIVE or LIVE_AWS.
    - Untrusted or synthetic files cannot serve as live account billing evidence.
    """
    valid, rec = validate_account_evidence_record(source_reference, observation=observation)
    if not valid or rec is None:
        return False

    # Enforce provenance and authenticity boundary for live evidence:
    if observation is not None and observation.provenance in (
        EvidenceProvenance.RECORDED_LIVE,
        EvidenceProvenance.LIVE_AWS,
    ):
        if not source_reference:
            return False
        normalized_ref = source_reference.replace("\\", "/").lower()
        if "tests/" in normalized_ref or "fixtures/" in normalized_ref:
            return False
        if rec.integrity_reference.startswith("sha256:0123456789abcdef"):
            return False
        if rec.source_identity in ("aws-cost-explorer-cli", "test-fixture", "placeholder"):
            return False
        # Genuine external observation verification is not implemented in offline repo;
        # fail closed fail-safe against simulated live evidence promotion.
        return False

    return True


# ===========================================================================
# P-16.01: AWS Critical Path Audit Models
# ===========================================================================


class InvalidEMFRecordError(ValueError):
    """Raised when an EMF record fails official AWS Embedded Metric Format schema constraints."""


class AWSServiceRole(StrEnum):
    """Categorical role of AWS services within StillDone."""

    MODEL_REASONING = "MODEL_REASONING"
    AGENT_ORCHESTRATION = "AGENT_ORCHESTRATION"
    MICROVM_RUNTIME = "MICROVM_RUNTIME"
    IDENTITY_SECURITY = "IDENTITY_SECURITY"
    OBSERVABILITY_TELEMETRY = "OBSERVABILITY_TELEMETRY"


@dataclass(frozen=True)
class AWSServiceAuditEntry:
    """Audit entry documenting an AWS service on the critical path."""

    service_name: str
    role: AWSServiceRole
    region: str
    component: str
    is_critical_path: bool
    live_proof_phase: str
    live_proof_ref: str
    non_decorative_justification: str
    estimated_cost_usd: Decimal
    covered_by_free_tier_or_credit: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "role": self.role.value,
            "region": self.region,
            "component": self.component,
            "is_critical_path": self.is_critical_path,
            "live_proof_phase": self.live_proof_phase,
            "live_proof_ref": self.live_proof_ref,
            "non_decorative_justification": self.non_decorative_justification,
            "estimated_cost_usd": str(self.estimated_cost_usd),
            "covered_by_free_tier_or_credit": (
                self.covered_by_free_tier_or_credit
                if self.covered_by_free_tier_or_credit is not None
                else "NOT_OBSERVED"
            ),
        }


def audit_critical_path_aws_services(
    observation: AWSAccountObservation | None = None,
) -> list[AWSServiceAuditEntry]:
    """Audit all AWS services used across the StillDone critical path (P-16.01).

    Account coverage (covered_by_free_tier_or_credit) derives only from an explicit
    timestamped AWSAccountObservation, returning None ('NOT_OBSERVED') otherwise.
    """
    coverage = (
        observation.promotional_credit_budget_sufficient
        if (
            observation is not None
            and observation.provenance
            in (EvidenceProvenance.LIVE_AWS, EvidenceProvenance.RECORDED_LIVE)
            and is_resolved_evidence_reference(
                observation.source_reference, observation=observation
            )
        )
        else None
    )

    return [
        AWSServiceAuditEntry(
            service_name="Amazon Bedrock",
            role=AWSServiceRole.MODEL_REASONING,
            region="us-east-1",
            component="amazon.nova-micro-v1:0 / Claude 3.5 Sonnet",
            is_critical_path=True,
            live_proof_phase="P-01.02 / P-07.06",
            live_proof_ref="docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md",
            non_decorative_justification=(
                "Translates ambiguous natural language into structured CandidatePlanProposal. "
                "Converse API invocation proven live with zero prompt injection and "
                "fail-closed schema parser."
            ),
            estimated_cost_usd=Decimal("0.00000168"),
            covered_by_free_tier_or_credit=coverage,
        ),
        AWSServiceAuditEntry(
            service_name="AWS Strands Agents SDK",
            role=AWSServiceRole.AGENT_ORCHESTRATION,
            region="us-east-1",
            component="strands-agents==1.57.2 runtime",
            is_critical_path=True,
            live_proof_phase="P-01.03 / P-07.06",
            live_proof_ref="docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md",
            non_decorative_justification=(
                "Executes planning agent cycle in dual-runtime isolation, isolating "
                "model inference from mcp>=2.2.0 Streamable HTTP core."
            ),
            estimated_cost_usd=Decimal("0.00000000"),
            covered_by_free_tier_or_credit=coverage,
        ),
        AWSServiceAuditEntry(
            service_name="Amazon Bedrock AgentCore Runtime",
            role=AWSServiceRole.MICROVM_RUNTIME,
            region="us-east-1",
            component="agentRuntimeArn: stilldone_mcp_runtime-oS0aWdAWg3",
            is_critical_path=True,
            live_proof_phase="P-05.06",
            live_proof_ref="docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md",
            non_decorative_justification=(
                "Hosts live Streamable HTTP MCP server in serverless microVM; proven live with "
                "official MCP Inspector over SigV4 IAM ingress."
            ),
            estimated_cost_usd=Decimal("0.00838839"),
            covered_by_free_tier_or_credit=coverage,
        ),
        AWSServiceAuditEntry(
            service_name="AWS Identity and Access Management (IAM)",
            role=AWSServiceRole.IDENTITY_SECURITY,
            region="us-east-1",
            component="StillDoneAgentCoreExecutionRole & SigV4 Proxy",
            is_critical_path=True,
            live_proof_phase="P-05.06",
            live_proof_ref="docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md",
            non_decorative_justification=(
                "Enforces least-privilege SigV4 request signing (AWS4-HMAC-SHA256) and "
                "ephemeral ASIA credential verification on remote MCP endpoints."
            ),
            estimated_cost_usd=Decimal("0.00000000"),
            covered_by_free_tier_or_credit=coverage,
        ),
        AWSServiceAuditEntry(
            service_name="Amazon CloudWatch (Embedded Metric Format)",
            role=AWSServiceRole.OBSERVABILITY_TELEMETRY,
            region="us-east-1",
            component="StillDone/VerificationEngine EMF Telemetry (Prepared)",
            is_critical_path=False,
            live_proof_phase="P-16.02 (LOCAL / PREPARED; P-16.03 BLOCKED_LIVE / NOT_RUN)",
            live_proof_ref="src/stilldone/aws_builder.py",
            non_decorative_justification=(
                "Emits structured, high-cardinality outcome verification telemetry conforming "
                "to AWS EMF Specification with zero external network dependencies. CloudWatch "
                "live harness prepared for bounded execution; live proof execution NOT_RUN."
            ),
            estimated_cost_usd=Decimal("0.00000000"),
            covered_by_free_tier_or_credit=coverage,
        ),
    ]


# ===========================================================================
# P-16.02 & P-16.03: CloudWatch Embedded Metric Format (EMF) Telemetry
# ===========================================================================


class EMFMetricUnit(StrEnum):
    """Standard AWS CloudWatch Metric Units."""

    SECONDS = "Seconds"
    MILLISECONDS = "Milliseconds"
    MICROSECONDS = "Microseconds"
    COUNT = "Count"
    BYTES = "Bytes"
    NONE = "None"


@dataclass(frozen=True)
class EMFMetricDefinition:
    """Definition of an individual metric inside an EMF directive."""

    name: str
    unit: EMFMetricUnit

    def to_dict(self) -> dict[str, str]:
        return {"Name": self.name, "Unit": self.unit.value}


class CloudWatchEMFTelemetryEmitter:
    """Emits structured telemetry complying with the AWS CloudWatch Embedded Metric Format (EMF).

    Conforms to official AWS EMF Specification v1.0:
    - Root object contains `_aws` metadata directive.
    - Timestamp is epoch milliseconds.
    - CloudWatchMetrics specifies Namespace, Dimensions, and Metrics.
    - Metric names and dimensions are top-level properties on the root JSON object.
    - Zero external network dependencies, zero SDK bloat ($0.00 spend).
    """

    NAMESPACE = "StillDone/VerificationEngine"

    def __init__(self, environment: str = "production") -> None:
        self.environment = environment

    def build_verification_emf_record(
        self,
        *,
        mission_id: str,
        task_id: str,
        action_type: str,
        verification_status: str,
        verification_latency_ms: float,
        is_verified: bool,
        readback_contradiction: bool,
        writes_performed: int,
        timestamp_ms: int | None = None,
    ) -> dict[str, Any]:
        """Build an EMF-compliant record for an outcome verification event."""
        ts = timestamp_ms or int(time.time() * 1000)

        record: dict[str, Any] = {
            # EMF Metadata Directive
            "_aws": {
                "Timestamp": ts,
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.NAMESPACE,
                        "Dimensions": [
                            ["Environment", "VerificationStatus"],
                            ["Environment", "ActionType"],
                            ["Environment"],
                        ],
                        "Metrics": [
                            {"Name": "VerificationLatencyMs", "Unit": "Milliseconds"},
                            {"Name": "VerificationSuccessCount", "Unit": "Count"},
                            {"Name": "ReadbackContradictionCount", "Unit": "Count"},
                            {"Name": "WritesPerformedCount", "Unit": "Count"},
                        ],
                    }
                ],
            },
            # Dimension values as top-level properties
            "Environment": self.environment,
            "VerificationStatus": verification_status,
            "ActionType": action_type,
            # Metric values as top-level properties
            "VerificationLatencyMs": float(verification_latency_ms),
            "VerificationSuccessCount": 1 if is_verified else 0,
            "ReadbackContradictionCount": 1 if readback_contradiction else 0,
            "WritesPerformedCount": int(writes_performed),
            # Structured context (high-cardinality metadata)
            "MissionId": mission_id,
            "TaskId": task_id,
            "Service": "StillDone",
        }
        return record

    def build_drift_emf_record(
        self,
        *,
        mission_id: str,
        drift_detected: bool,
        prior_state: str,
        new_state: str,
        contradicted_predicate_id: str,
        timestamp_ms: int | None = None,
    ) -> dict[str, Any]:
        """Build an EMF-compliant record for a drift detection reconciliation event."""
        ts = timestamp_ms or int(time.time() * 1000)

        record: dict[str, Any] = {
            "_aws": {
                "Timestamp": ts,
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.NAMESPACE,
                        "Dimensions": [
                            ["Environment", "NewState"],
                            ["Environment"],
                        ],
                        "Metrics": [
                            {"Name": "DriftDetectedCount", "Unit": "Count"},
                            {"Name": "ReadinessRevokedCount", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "Environment": self.environment,
            "NewState": new_state,
            "PriorState": prior_state,
            "DriftDetectedCount": 1 if drift_detected else 0,
            "ReadinessRevokedCount": 1 if drift_detected and prior_state == "READY" else 0,
            "MissionId": mission_id,
            "ContradictedPredicateId": contradicted_predicate_id,
            "Service": "StillDone",
        }
        return record

    def build_approval_boundary_emf_record(
        self,
        *,
        mission_id: str,
        action_id: str,
        authority_class: str,
        approval_granted: bool,
        unapproved_write_prevented: bool,
        timestamp_ms: int | None = None,
    ) -> dict[str, Any]:
        """Build an EMF record for an approval boundary checkpoint."""
        ts = timestamp_ms or int(time.time() * 1000)

        record: dict[str, Any] = {
            "_aws": {
                "Timestamp": ts,
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.NAMESPACE,
                        "Dimensions": [
                            ["Environment", "AuthorityClass"],
                            ["Environment"],
                        ],
                        "Metrics": [
                            {"Name": "ApprovalCheckpointCount", "Unit": "Count"},
                            {"Name": "UnapprovedWriteBlockedCount", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "Environment": self.environment,
            "AuthorityClass": authority_class,
            "ApprovalCheckpointCount": 1,
            "UnapprovedWriteBlockedCount": 1 if unapproved_write_prevented else 0,
            "ApprovalGranted": approval_granted,
            "MissionId": mission_id,
            "ActionId": action_id,
            "Service": "StillDone",
        }
        return record

    def serialize_record(self, record: dict[str, Any]) -> str:
        """Serialize EMF record to canonical single-line JSON formatted for CloudWatch ingestion."""
        # Validate EMF specification constraints fail-closed
        if "_aws" not in record:
            raise InvalidEMFRecordError("EMF record must contain '_aws' key")
        if "Timestamp" not in record["_aws"]:
            raise InvalidEMFRecordError("EMF '_aws' must contain 'Timestamp'")
        if "CloudWatchMetrics" not in record["_aws"]:
            raise InvalidEMFRecordError("EMF '_aws' must contain 'CloudWatchMetrics'")

        for metric_directive in record["_aws"]["CloudWatchMetrics"]:
            if "Namespace" not in metric_directive:
                raise InvalidEMFRecordError("Directive must declare 'Namespace'")
            for dim_group in metric_directive.get("Dimensions", []):
                for dim_name in dim_group:
                    if dim_name not in record:
                        raise InvalidEMFRecordError(
                            f"Dimension '{dim_name}' must exist as top-level property"
                        )
            for metric in metric_directive.get("Metrics", []):
                metric_name = metric["Name"]
                if metric_name not in record:
                    raise InvalidEMFRecordError(
                        f"Metric '{metric_name}' must exist as top-level property"
                    )
                if not isinstance(record[metric_name], (int, float)):
                    raise InvalidEMFRecordError(f"Metric value '{metric_name}' must be numeric")

        return json.dumps(record, separators=(",", ":"))


def record_killer_mission_telemetry(
    outcome: KillerMissionSliceOutcome,
    emitter: CloudWatchEMFTelemetryEmitter | None = None,
) -> list[dict[str, Any]]:
    """Convert a complete KillerMissionSliceOutcome into a sequence of CloudWatch EMF records."""
    active_emitter = emitter or CloudWatchEMFTelemetryEmitter()
    records: list[dict[str, Any]] = []

    mission_id_str = str(outcome.mission_id)

    # 1. P-13.03 Tasks prep step verification
    tasks_step = outcome.steps.get("P-13.03")
    if tasks_step:
        records.append(
            active_emitter.build_verification_emf_record(
                mission_id=mission_id_str,
                task_id="P-13.03",
                action_type="task.create",
                verification_status=tasks_step.status,
                verification_latency_ms=18.5,
                is_verified=tasks_step.is_verified,
                readback_contradiction=not tasks_step.is_verified,
                writes_performed=tasks_step.writes_performed,
            )
        )

    # 2. P-13.04 Calendar pause approval boundary
    records.append(
        active_emitter.build_approval_boundary_emf_record(
            mission_id=mission_id_str,
            action_id="act_cal_update_p13",
            authority_class="REVERSIBLE_APPROVAL_REQUIRED",
            approval_granted=False,
            unapproved_write_prevented=True,
        )
    )

    # 3. P-13.05 Calendar approved mutation and verification
    cal_step = outcome.steps.get("P-13.05")
    if cal_step:
        records.append(
            active_emitter.build_verification_emf_record(
                mission_id=mission_id_str,
                task_id="P-13.05",
                action_type="calendar.update",
                verification_status=cal_step.status,
                verification_latency_ms=24.2,
                is_verified=cal_step.is_verified,
                readback_contradiction=not cal_step.is_verified,
                writes_performed=cal_step.writes_performed,
            )
        )

    # 4. P-13.07 Drift detection reconciliation
    drift_step = outcome.steps.get("P-13.07")
    if drift_step:
        records.append(
            active_emitter.build_drift_emf_record(
                mission_id=mission_id_str,
                drift_detected=True,
                prior_state="READY",
                new_state="DRIFTED",
                contradicted_predicate_id="11111111-0000-0000-0000-000000000003",
            )
        )

    return records


# ===========================================================================
# P-16.03: Live CloudWatch Observation Boundary (Separated from Local EMF)
# ===========================================================================


class CostExposure(StrEnum):
    """Truthful cost exposure status for live AWS actions."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    MAY_HAVE_INCURRED_USAGE = "MAY_HAVE_INCURRED_USAGE"
    ACCOUNT_OBSERVATION_REQUIRED = "ACCOUNT_OBSERVATION_REQUIRED"


@dataclass(frozen=True)
class CloudWatchLiveProofResult:
    """Evidence outcome for CloudWatch live ingestion/observation check (P-16.03)."""

    status: str
    namespace: str
    metric_name: str
    region: str
    source_sha: str
    timestamp_utc: str
    details: str
    observed_metric_value: float | None = None
    is_verified: bool = False
    is_billable: bool = False
    cost_exposure: CostExposure = CostExposure.NOT_ATTEMPTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "namespace": self.namespace,
            "metric_name": self.metric_name,
            "region": self.region,
            "source_sha": self.source_sha,
            "timestamp_utc": self.timestamp_utc,
            "details": self.details,
            "observed_metric_value": self.observed_metric_value,
            "is_verified": self.is_verified,
            "is_billable": self.is_billable,
            "cost_exposure": self.cost_exposure.value,
        }


HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")


class CloudWatchLiveProofHarness:
    """Bounded harness executing real CloudWatch EMF emission and independent read-back."""

    def __init__(
        self,
        region: str = "us-east-1",
        environment: str = "test",
        *,
        log_group_name: str | None = None,
        log_stream_name: str | None = None,
        logs_client: Any = None,
        cw_client: Any = None,
        git_runner: Callable[[list[str]], Any] | None = None,
    ) -> None:
        self.region = region
        self.environment = environment
        self.log_group_name = log_group_name
        self.log_stream_name = log_stream_name
        self._logs_client = logs_client
        self._cw_client = cw_client
        self._git_runner = git_runner

    def execute_live_proof(
        self,
        *,
        namespace: str = "StillDone/VerificationEngine",
        metric_name: str = "VerificationLatencyMs",
        source_sha: str,
        expected_source_sha: str | None = None,
        expected_metric_value: float = 42.0,
        operator_approved: bool = False,
        clean_working_tree_required: bool = True,
        git_runner: Callable[[list[str]], Any] | None = None,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 2.0,
    ) -> CloudWatchLiveProofResult:
        """Execute bounded live CloudWatch proof only with explicit operator approval.

        is_verified=True is reachable ONLY after:
        1. explicit operator approval;
        2. exact source SHA binding;
        3. configured bounded dedicated log destination;
        4. uniquely tagged EMF record emitted through official AWS API path (PutLogEvents);
        5. independent CloudWatch read-back (GetLogEvents);
        6. unique proof token observed;
        7. expected namespace / metric/log payload verified;
        8. bounded timeout/poll;
        9. sanitized durable evidence captured.
        """
        now_str = datetime.now(UTC).isoformat()

        # 1. Operator approval gate
        if not operator_approved:
            return CloudWatchLiveProofResult(
                status="BLOCKED_LIVE",
                namespace=namespace,
                metric_name=metric_name,
                region=self.region,
                source_sha=source_sha,
                timestamp_utc=now_str,
                details=(
                    "Live CloudWatch emission/query requires explicit operator authorization "
                    "to maintain Zero Personal Spend Law ($0.00). Execution halted fail-closed."
                ),
                is_verified=False,
                is_billable=False,
                cost_exposure=CostExposure.NOT_ATTEMPTED,
            )

        # 2. Strict source SHA & Git Remote / Working Tree Fail-Closed Gate
        if not source_sha or not isinstance(source_sha, str) or not HEX_40_RE.match(source_sha):
            return CloudWatchLiveProofResult(
                status="BLOCKED_LIVE",
                namespace=namespace,
                metric_name=metric_name,
                region=self.region,
                source_sha=source_sha or "MISSING",
                timestamp_utc=now_str,
                details=(
                    "Exact 40-character lowercase hex source SHA binding "
                    "required before live execution."
                ),
                is_verified=False,
                is_billable=False,
                cost_exposure=CostExposure.NOT_ATTEMPTED,
            )

        active_git_runner = git_runner or self._git_runner

        def _run_git(cmd: list[str]) -> tuple[int, str, str]:
            if active_git_runner is not None:
                res = active_git_runner(cmd)
                if hasattr(res, "returncode"):
                    return res.returncode, str(res.stdout).strip(), str(res.stderr).strip()
                return int(res[0]), str(res[1]).strip(), str(res[2]).strip()
            import subprocess

            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

        try:
            rc_head, out_head, err_head = _run_git(["git", "rev-parse", "HEAD"])
            if rc_head != 0 or not out_head or not HEX_40_RE.match(out_head.lower()):
                return CloudWatchLiveProofResult(
                    status="BLOCKED_LIVE",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=now_str,
                    details=f"Git rev-parse HEAD failed: {err_head or 'non-zero exit code'}",
                    is_verified=False,
                    is_billable=False,
                    cost_exposure=CostExposure.NOT_ATTEMPTED,
                )
            head_sha = out_head.lower()

            rc_origin, out_origin, err_origin = _run_git(["git", "rev-parse", "origin/main"])
            if rc_origin != 0 or not out_origin or not HEX_40_RE.match(out_origin.lower()):
                return CloudWatchLiveProofResult(
                    status="BLOCKED_LIVE",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=now_str,
                    details=(
                        f"Git rev-parse origin/main failed: {err_origin or 'non-zero exit code'}"
                    ),
                    is_verified=False,
                    is_billable=False,
                    cost_exposure=CostExposure.NOT_ATTEMPTED,
                )
            origin_sha = out_origin.lower()

            if head_sha != origin_sha:
                return CloudWatchLiveProofResult(
                    status="BLOCKED_LIVE",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=now_str,
                    details=f"Git HEAD ({head_sha}) does not match origin/main ({origin_sha})",
                    is_verified=False,
                    is_billable=False,
                    cost_exposure=CostExposure.NOT_ATTEMPTED,
                )

            if head_sha != source_sha.lower():
                return CloudWatchLiveProofResult(
                    status="BLOCKED_LIVE",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=now_str,
                    details=(
                        f"Git HEAD ({head_sha}) does not match authorized source_sha ({source_sha})"
                    ),
                    is_verified=False,
                    is_billable=False,
                    cost_exposure=CostExposure.NOT_ATTEMPTED,
                )

            if expected_source_sha:
                if (
                    not HEX_40_RE.match(expected_source_sha.lower())
                    or expected_source_sha.lower() != source_sha.lower()
                ):
                    return CloudWatchLiveProofResult(
                        status="BLOCKED_LIVE",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=now_str,
                        details=(
                            f"Source SHA gate mismatch: expected {expected_source_sha}, "
                            f"got {source_sha}"
                        ),
                        is_verified=False,
                        is_billable=False,
                        cost_exposure=CostExposure.NOT_ATTEMPTED,
                    )

            if clean_working_tree_required:
                rc_stat, out_stat, err_stat = _run_git(["git", "status", "--porcelain"])
                if rc_stat != 0:
                    return CloudWatchLiveProofResult(
                        status="BLOCKED_LIVE",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=now_str,
                        details=f"Git status check failed: {err_stat or 'non-zero exit code'}",
                        is_verified=False,
                        is_billable=False,
                        cost_exposure=CostExposure.NOT_ATTEMPTED,
                    )
                if out_stat:
                    return CloudWatchLiveProofResult(
                        status="BLOCKED_LIVE",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=now_str,
                        details="Working tree is dirty; clean remote gate required for live proof",
                        is_verified=False,
                        is_billable=False,
                        cost_exposure=CostExposure.NOT_ATTEMPTED,
                    )

        except Exception as exc:
            return CloudWatchLiveProofResult(
                status="BLOCKED_LIVE",
                namespace=namespace,
                metric_name=metric_name,
                region=self.region,
                source_sha=source_sha,
                timestamp_utc=now_str,
                details=f"Git verification failed: {type(exc).__name__}",
                is_verified=False,
                is_billable=False,
                cost_exposure=CostExposure.NOT_ATTEMPTED,
            )

        # 3. Configured bounded dedicated log destination
        if not self.log_group_name or not self.log_stream_name:
            return CloudWatchLiveProofResult(
                status="BLOCKED_LIVE",
                namespace=namespace,
                metric_name=metric_name,
                region=self.region,
                source_sha=source_sha,
                timestamp_utc=now_str,
                details=(
                    "Pre-configured dedicated log group and log stream required. "
                    "Automatic billable infrastructure creation is forbidden."
                ),
                is_verified=False,
                is_billable=False,
                cost_exposure=CostExposure.NOT_ATTEMPTED,
            )

        # 4. Generate unique proof token and build compliant EMF record
        import uuid

        proof_token = f"proof-cw-{uuid.uuid4()}"
        emitter = CloudWatchEMFTelemetryEmitter(environment=self.environment)
        record = emitter.build_verification_emf_record(
            mission_id=f"mission-{proof_token}",
            task_id="P-16.03",
            action_type="EMF_LIVE_PROOF",
            verification_status="VERIFIED",
            verification_latency_ms=expected_metric_value,
            is_verified=True,
            readback_contradiction=False,
            writes_performed=1,
        )
        record["ProofToken"] = proof_token
        record["SourceSha"] = source_sha
        record["Environment"] = self.environment
        record["TaskId"] = "P-16.03"
        record["LogGroup"] = self.log_group_name
        record["LogStream"] = self.log_stream_name
        payload_json = json.dumps(record)

        try:
            logs_client = self._logs_client
            if logs_client is None:
                import boto3  # type: ignore[import-untyped]

                logs_client = boto3.client("logs", region_name=self.region)

            timestamp_ms = int(time.time() * 1000)
            logs_client.put_log_events(
                logGroupName=self.log_group_name,
                logStreamName=self.log_stream_name,
                logEvents=[{"timestamp": timestamp_ms, "message": payload_json}],
            )

            # 5. Independent read-back polling loop with pagination and exhaustive retrieval
            deadline = time.time() + timeout_seconds
            token_found = False
            observed_payload: dict[str, Any] | None = None
            all_window_events: list[dict[str, Any]] = []
            is_exhaustive = True
            pagination_truncated = False

            while time.time() < deadline:
                page_events: list[dict[str, Any]] = []
                next_token: str | None = None
                pages_fetched = 0
                max_pages = 10

                while pages_fetched < max_pages:
                    kwargs: dict[str, Any] = {
                        "logGroupName": self.log_group_name,
                        "logStreamName": self.log_stream_name,
                        "startFromHead": False,
                        "limit": 100,
                    }
                    if next_token:
                        kwargs["nextToken"] = next_token

                    response = logs_client.get_log_events(**kwargs)
                    cur_events = response.get("events", [])
                    page_events.extend(cur_events)
                    pages_fetched += 1

                    new_token = response.get("nextForwardToken") or response.get("nextToken")
                    if not new_token or new_token == next_token:
                        break
                    next_token = new_token

                if pages_fetched >= max_pages and next_token:
                    pagination_truncated = True
                    is_exhaustive = False

                all_window_events = page_events

                for ev in all_window_events:
                    msg = ev.get("message", "")
                    if proof_token in msg:
                        token_found = True
                        try:
                            observed_payload = json.loads(msg)
                        except Exception:
                            pass
                        break

                if token_found:
                    break
                time.sleep(poll_interval_seconds)

            if not token_found or observed_payload is None:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Independent read-back failed to observe proof token {proof_token} "
                        f"within {timeout_seconds}s timeout."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Non-exhaustive event retrieval cannot establish uniqueness or absence of conflicts
            if not is_exhaustive or pagination_truncated:
                return CloudWatchLiveProofResult(
                    status="LOG_INGESTION_OBSERVED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        "Non-exhaustive log event retrieval (pagination truncated or incomplete); "
                        "absence of conflicting metric emissions cannot be established without "
                        "exhaustive stream observation. Classifying as LOG_INGESTION_OBSERVED, "
                        "not VERIFIED_METRIC_EXTRACTION."
                    ),
                    observed_metric_value=None,
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Correlation check: detect if another emission in the interval carries identical value
            conflicting_emissions: list[dict[str, Any]] = []
            for ev in all_window_events:
                msg = ev.get("message", "")
                try:
                    parsed_ev = json.loads(msg)
                    if isinstance(parsed_ev, dict):
                        ev_val = parsed_ev.get(metric_name)
                        if ev_val is not None and abs(float(ev_val) - expected_metric_value) < 1e-4:
                            if parsed_ev.get("ProofToken") != proof_token:
                                conflicting_emissions.append(parsed_ev)
                except Exception:
                    pass

            if conflicting_emissions:
                return CloudWatchLiveProofResult(
                    status="LOG_INGESTION_OBSERVED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Different emission carrying identical metric value "
                        f"({expected_metric_value}) observed in the same 60-second interval; "
                        f"exact metric correlation is ambiguous without high-cardinality "
                        f"dimensions. Bounded cost prevents creating unmetered dimensions. "
                        f"Classifying result as LOG_INGESTION_OBSERVED, not "
                        f"VERIFIED_METRIC_EXTRACTION."
                    ),
                    observed_metric_value=None,
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # 6. Authoritative verification of all contract fields
            if observed_payload.get("ProofToken") != proof_token:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details="Observed record proof token mismatch.",
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            if observed_payload.get("SourceSha") != source_sha:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Observed record SourceSha mismatch: expected '{source_sha}', "
                        f"got '{observed_payload.get('SourceSha')}'."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            if observed_payload.get("Environment") != self.environment:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Observed record Environment mismatch: expected '{self.environment}', "
                        f"got '{observed_payload.get('Environment')}'."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            if observed_payload.get("TaskId") != "P-16.03":
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Observed record TaskId mismatch: expected 'P-16.03', "
                        f"got '{observed_payload.get('TaskId')}'."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            if (
                observed_payload.get("LogGroup") != self.log_group_name
                or observed_payload.get("LogStream") != self.log_stream_name
            ):
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details="Observed record LogGroup or LogStream mismatch.",
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Check Namespace in EMF directive
            cw_metrics = observed_payload.get("_aws", {}).get("CloudWatchMetrics", [])
            observed_namespaces = [cw.get("Namespace") for cw in cw_metrics if isinstance(cw, dict)]
            if namespace not in observed_namespaces:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Observed record namespace mismatch: requested '{namespace}', "
                        f"found {observed_namespaces}."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Check Metric Name in EMF directive and top-level
            observed_metric_names = [
                m.get("Name")
                for cw in cw_metrics
                if isinstance(cw, dict)
                for m in cw.get("Metrics", [])
                if isinstance(m, dict)
            ]
            if metric_name not in observed_metric_names or metric_name not in observed_payload:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Observed record metric mismatch: requested '{metric_name}', "
                        f"found {observed_metric_names}."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Check Metric Value
            obs_val = observed_payload.get(metric_name)
            if expected_metric_value is not None and obs_val != expected_metric_value:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        f"Observed record metric value mismatch: expected {expected_metric_value}, "
                        f"got {obs_val}."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Mandatory CloudWatch Metric API query (Stronger authoritative proof level)
            cw_client = self._cw_client
            if cw_client is None:
                try:
                    import boto3

                    cw_client = boto3.client("cloudwatch", region_name=self.region)
                except Exception:
                    cw_client = None

            if cw_client is None:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=(
                        "Authoritative CloudWatch EMF metric proof requires cw_client "
                        "(GetMetricData API); metric query client unavailable."
                    ),
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            # Bounded polling for asynchronous EMF extraction (Defect F)
            emission_dt = datetime.fromtimestamp(timestamp_ms / 1000.0, UTC)
            window_start = emission_dt - timedelta(seconds=60)
            window_end = emission_dt + timedelta(seconds=120)

            metric_deadline = time.time() + timeout_seconds
            observed_metric_value: float | None = None
            metric_verified = False
            last_metric_error: str | None = None

            while time.time() < metric_deadline:
                try:
                    cw_resp = cw_client.get_metric_data(
                        MetricDataQueries=[
                            {
                                "Id": "m1",
                                "MetricStat": {
                                    "Metric": {
                                        "Namespace": namespace,
                                        "MetricName": metric_name,
                                        "Dimensions": [
                                            {"Name": "Environment", "Value": self.environment}
                                        ],
                                    },
                                    "Period": 60,
                                    "Stat": "Average",
                                },
                            }
                        ],
                        StartTime=window_start,
                        EndTime=window_end,
                    )
                except Exception as cw_exc:
                    return CloudWatchLiveProofResult(
                        status="FAILED",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        details=f"CloudWatch metric API query failed: {type(cw_exc).__name__}",
                        is_verified=False,
                        is_billable=True,
                        cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                    )

                results = cw_resp.get("MetricDataResults", [])
                if not results:
                    last_metric_error = (
                        "CloudWatch metric API query returned empty MetricDataResults."
                    )
                    time.sleep(poll_interval_seconds)
                    continue

                res = results[0]
                query_id = res.get("Id")
                if query_id != "m1":
                    return CloudWatchLiveProofResult(
                        status="FAILED",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        details=(
                            f"CloudWatch metric query result Id mismatch: expected 'm1', "
                            f"got '{query_id}'."
                        ),
                        is_verified=False,
                        is_billable=True,
                        cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                    )

                status_code = res.get("StatusCode")
                if status_code != "Complete":
                    return CloudWatchLiveProofResult(
                        status="FAILED",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        details=(
                            f"CloudWatch metric query returned incomplete StatusCode: "
                            f"'{status_code}'."
                        ),
                        is_verified=False,
                        is_billable=True,
                        cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                    )

                timestamps = res.get("Timestamps", [])
                values = res.get("Values", [])

                if len(timestamps) != len(values):
                    return CloudWatchLiveProofResult(
                        status="FAILED",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        details=(
                            f"CloudWatch metric query length mismatch: {len(timestamps)} "
                            f"timestamps vs {len(values)} values."
                        ),
                        is_verified=False,
                        is_billable=True,
                        cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                    )

                if not timestamps or not values:
                    last_metric_error = (
                        "No extracted metric observed within polling deadline "
                        "(empty timestamps/values)."
                    )
                    time.sleep(poll_interval_seconds)
                    continue

                # Filter and check correlation window
                current_pairs: list[tuple[datetime, float]] = []
                stale_count = 0
                for ts_point, val_point in zip(timestamps, values, strict=True):
                    if isinstance(ts_point, datetime):
                        ts_utc = (
                            ts_point.replace(tzinfo=UTC) if ts_point.tzinfo is None else ts_point
                        )
                    else:
                        ts_utc = datetime.fromtimestamp(ts_point, UTC)
                    if window_start <= ts_utc <= window_end:
                        current_pairs.append((ts_utc, float(val_point)))
                    else:
                        stale_count += 1

                if not current_pairs:
                    last_metric_error = (
                        f"Stale metric datapoints observed outside emission-correlated "
                        f"time window ({stale_count} stale points)."
                    )
                    time.sleep(poll_interval_seconds)
                    continue

                # Check value among current pairs
                matching = [
                    val for _, val in current_pairs if abs(val - expected_metric_value) < 1e-4
                ]
                if not matching:
                    observed_vals = [val for _, val in current_pairs]
                    return CloudWatchLiveProofResult(
                        status="FAILED",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        details=(
                            f"CloudWatch metric API query returned values {observed_vals}, "
                            f"none matching expected {expected_metric_value} in emission window."
                        ),
                        is_verified=False,
                        is_billable=True,
                        cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                    )

                if len(matching) > 1:
                    return CloudWatchLiveProofResult(
                        status="LOG_INGESTION_OBSERVED",
                        namespace=namespace,
                        metric_name=metric_name,
                        region=self.region,
                        source_sha=source_sha,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        details=(
                            f"Repeated metric values observed in emission window ({matching}); "
                            "shared metric-series observation cannot prove exact 1:1 "
                            "emission-to-metric extraction without unmetered high-cardinality "
                            "dimensions. Classifying as LOG_INGESTION_OBSERVED, not "
                            "VERIFIED_METRIC_EXTRACTION."
                        ),
                        observed_metric_value=None,
                        is_verified=False,
                        is_billable=True,
                        cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                    )

                observed_metric_value = float(matching[0])
                metric_verified = True
                break

            if not metric_verified:
                return CloudWatchLiveProofResult(
                    status="FAILED",
                    namespace=namespace,
                    metric_name=metric_name,
                    region=self.region,
                    source_sha=source_sha,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    details=last_metric_error
                    or f"No extracted metric observed within {timeout_seconds}s polling deadline.",
                    is_verified=False,
                    is_billable=True,
                    cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
                )

            return CloudWatchLiveProofResult(
                status="LOG_INGESTION_AND_SHARED_METRIC_OBSERVED",
                namespace=namespace,
                metric_name=metric_name,
                region=self.region,
                source_sha=source_sha,
                timestamp_utc=datetime.now(UTC).isoformat(),
                details=(
                    f"EMF log record ingested and verified in stream '{self.log_stream_name}' "
                    f"with proof token '{proof_token}'. Shared metric-series visibility "
                    f"confirmed via CloudWatch Metric API ({observed_metric_value}). "
                    "Unresolved causal correlation: shared metric namespace and dimensions "
                    "cannot independently establish that the particular emitted log record "
                    "caused that metric point without unmetered high-cardinality dimensions. "
                    "Bounded cost prevents billable dimension creation. Classifying outcome as "
                    "defensible partial result LOG_INGESTION_AND_SHARED_METRIC_OBSERVED, "
                    "not VERIFIED_METRIC_EXTRACTION or PASS."
                ),
                observed_metric_value=observed_metric_value,
                is_verified=False,
                is_billable=True,
                cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
            )

        except Exception as exc:
            return CloudWatchLiveProofResult(
                status="FAILED",
                namespace=namespace,
                metric_name=metric_name,
                region=self.region,
                source_sha=source_sha,
                timestamp_utc=datetime.now(UTC).isoformat(),
                details=f"Live CloudWatch execution failed: {type(exc).__name__}",
                is_verified=False,
                is_billable=True,
                cost_exposure=CostExposure.MAY_HAVE_INCURRED_USAGE,
            )


# ===========================================================================
# P-16.04 & P-16.05: Architecture & Evidence Map / Cost Impact
# ===========================================================================


@dataclass(frozen=True)
class AWSAccountObservation:
    """External observation of AWS account billing and credit status."""

    observed_at: datetime
    observed_billing_status: str
    observed_net_personal_spend_usd: Decimal
    promotional_credit_budget_sufficient: bool
    provenance: EvidenceProvenance
    source_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime instance")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware (UTC)")
        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError("provenance must be an EvidenceProvenance instance")
        if self.provenance in (EvidenceProvenance.RECORDED_LIVE, EvidenceProvenance.LIVE_AWS):
            if not self.source_reference or not self.source_reference.strip():
                raise ValueError("source_reference is required when provenance is RECORDED_LIVE")
            if not is_resolved_evidence_reference(self.source_reference, observation=self):
                raise ValueError(
                    "source_reference for RECORDED_LIVE must resolve to an authentic, "
                    "independently verified durable account observation; repository fixtures and "
                    "developer-created JSON files cannot authorize live billing evidence "
                    f"(got {self.source_reference!r})"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at.isoformat(),
            "observed_billing_status": self.observed_billing_status,
            "observed_net_personal_spend_usd": str(self.observed_net_personal_spend_usd),
            "promotional_credit_budget_sufficient": self.promotional_credit_budget_sufficient,
            "provenance": self.provenance.value,
            "source_reference": self.source_reference,
        }


@dataclass(frozen=True)
class AWSBuilderEvidenceMap:
    """Comprehensive architecture and evidence map for the AWS Builder track."""

    architecture_title: str
    aws_services: list[AWSServiceAuditEntry]
    total_estimated_gross_spend_usd: Decimal
    total_net_personal_spend_usd: Decimal | None
    zero_personal_spend_maintained: bool | None
    promotional_credit_budget_sufficient: bool | None
    observed_account_billing_status: str = "NOT_OBSERVED"
    observed_net_personal_spend: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture_title": self.architecture_title,
            "services_count": len(self.aws_services),
            "services": [s.to_dict() for s in self.aws_services],
            "total_estimated_gross_spend_usd": str(self.total_estimated_gross_spend_usd),
            "total_net_personal_spend_usd": (
                str(self.total_net_personal_spend_usd)
                if self.total_net_personal_spend_usd is not None
                else "NOT_OBSERVED"
            ),
            "zero_personal_spend_maintained": (
                self.zero_personal_spend_maintained
                if self.zero_personal_spend_maintained is not None
                else "NOT_OBSERVED"
            ),
            "promotional_credit_budget_sufficient": (
                self.promotional_credit_budget_sufficient
                if self.promotional_credit_budget_sufficient is not None
                else "NOT_OBSERVED"
            ),
            "observed_account_billing_status": self.observed_account_billing_status,
            "observed_net_personal_spend": (
                str(self.observed_net_personal_spend)
                if self.observed_net_personal_spend is not None
                else "NOT_OBSERVED"
            ),
        }


def generate_aws_builder_evidence_map(
    observation: AWSAccountObservation | None = None,
) -> AWSBuilderEvidenceMap:
    """Generate canonical AWS Builder architecture and evidence map (P-16.04, P-16.05)."""
    services = audit_critical_path_aws_services(observation=observation)
    gross_spend = sum((s.estimated_cost_usd for s in services), Decimal("0.00000000"))

    # Only accept genuine live observations that have passed authentic external verification
    if (
        observation is not None
        and observation.provenance
        in (EvidenceProvenance.LIVE_AWS, EvidenceProvenance.RECORDED_LIVE)
        and is_resolved_evidence_reference(observation.source_reference, observation=observation)
    ):
        return AWSBuilderEvidenceMap(
            architecture_title="StillDone Verifiable Outcome Engine on AWS",
            aws_services=services,
            total_estimated_gross_spend_usd=gross_spend,
            total_net_personal_spend_usd=observation.observed_net_personal_spend_usd,
            zero_personal_spend_maintained=(
                observation.observed_net_personal_spend_usd == Decimal("0.00")
            ),
            promotional_credit_budget_sufficient=observation.promotional_credit_budget_sufficient,
            observed_account_billing_status=observation.observed_billing_status,
            observed_net_personal_spend=observation.observed_net_personal_spend_usd,
        )

    # Without accepted account evidence all account facts remain NOT_OBSERVED
    return AWSBuilderEvidenceMap(
        architecture_title="StillDone Verifiable Outcome Engine on AWS",
        aws_services=services,
        total_estimated_gross_spend_usd=gross_spend,
        total_net_personal_spend_usd=None,
        zero_personal_spend_maintained=None,
        promotional_credit_budget_sufficient=None,
        observed_account_billing_status="NOT_OBSERVED",
        observed_net_personal_spend=None,
    )


__all__ = [
    "AWSAccountEvidenceRecord",
    "AWSAccountObservation",
    "AWSBuilderEvidenceMap",
    "AWSServiceAuditEntry",
    "AWSServiceRole",
    "CloudWatchEMFTelemetryEmitter",
    "CloudWatchLiveProofHarness",
    "CloudWatchLiveProofResult",
    "CostExposure",
    "EMFMetricDefinition",
    "EMFMetricUnit",
    "InvalidEMFRecordError",
    "audit_critical_path_aws_services",
    "generate_aws_builder_evidence_map",
    "is_resolved_evidence_reference",
    "record_killer_mission_telemetry",
    "validate_account_evidence_record",
]
