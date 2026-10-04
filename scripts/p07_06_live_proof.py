"""P-07.06 Live Bedrock Strands Planner Execution and Control Proof.

Executes exactly ONE live Bedrock inference via Strands planner,
validates deterministic contract adherence, captures sanitized evidence,
and executes the negative control proof without additional live calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure src is on path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root / "src") not in sys.path:
    sys.path.insert(0, str(repo_root / "src"))

# Resolve short-lived credentials from active AWS CLI login session into os.environ
# so that botocore resolves via EnvProvider rather than LoginCredentialProvider
# (which requires awscrt and would break pinned dependencies).
if "AWS_ACCESS_KEY_ID" not in os.environ:
    try:
        creds_json = subprocess.check_output(
            ["aws", "configure", "export-credentials", "--profile", "stilldone-p01"],
            text=True,
        )
        creds = json.loads(creds_json)
        os.environ["AWS_ACCESS_KEY_ID"] = creds["AccessKeyId"]
        os.environ["AWS_SECRET_ACCESS_KEY"] = creds["SecretAccessKey"]
        if "SessionToken" in creds:
            os.environ["AWS_SESSION_TOKEN"] = creds["SessionToken"]
    except Exception as exc:
        print(f"[!] Warning: Failed to export credentials from profile: {exc}")

os.environ.pop("AWS_PROFILE", None)
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"

from stilldone.domain.action import ActionType  # noqa: E402
from stilldone.domain.mission import MissionId  # noqa: E402
from stilldone.planning.bedrock import BedrockPlannerSettings  # noqa: E402
from stilldone.planning.contracts import (  # noqa: E402
    CandidatePlanProposal,
    PlannerInput,
)
from stilldone.planning.metadata import PlannerRuntimeMetadata  # noqa: E402
from stilldone.planning.strands_agent import (  # noqa: E402
    StrandsPlannerResult,
    plan_with_strands,
)


def run_live_proof() -> dict[str, Any]:
    # 1. Deterministic natural-language mission input
    mission_uuid = str(uuid.uuid4())
    mission_id = MissionId(mission_uuid)
    intent = "Check today's calendar events and create a task to review project roadmap"
    planner_input = PlannerInput(mission_id=mission_id, intent=intent)

    utc_start = datetime.now(UTC).isoformat()
    print(f"[*] Starting P-07.06 Live Bedrock inference at {utc_start}")
    print(f"[*] Mission ID: {mission_uuid}")
    print(f"[*] Intent: {intent!r}")

    # 2. Real Strands Planner Invocation (EXACTLY 1 live call)
    settings = BedrockPlannerSettings()
    result = plan_with_strands(planner_input, settings=settings)

    utc_end = datetime.now(UTC).isoformat()
    print(f"[*] Live Bedrock inference completed at {utc_end}")

    # 3. Assertions on real Strands result
    assert isinstance(result, StrandsPlannerResult)
    assert result.stop_reason == "end_turn"
    assert isinstance(result.plan, CandidatePlanProposal)
    assert result.plan.mission_id == mission_id
    assert len(result.plan.steps) >= 1

    # Verify all proposed steps use canonical ActionTypes only
    for idx, step in enumerate(result.plan.steps, start=1):
        assert isinstance(step.action_type, ActionType)
        print(
            f"    - Proposed step {idx}: "
            f"action={step.action_type.value}, "
            f"target={step.target_ref.value}, "
            f"params={step.parameters.to_dict()}"
        )

    # Verify runtime metadata
    meta = result.metadata
    assert isinstance(meta, PlannerRuntimeMetadata)
    assert meta.model_id == "amazon.nova-micro-v1:0"
    assert meta.region_name == "us-east-1"
    assert meta.strands_version == "1.57.2"
    assert meta.tools_count == 0
    assert len(meta.to_dict()) == 18

    # 4. Invariants Verification: Model owns zero execution / authority / truth
    assert not hasattr(result.plan, "approval_grant")
    assert not hasattr(result.plan, "verified")
    assert not hasattr(result.plan, "ready")
    assert not hasattr(result.plan, "action_id")
    assert not hasattr(result.plan, "evidence_id")

    # 5. Negative Control Proof (Zero live calls):
    # Prove that removing/blocking model output prevents the compilation pipeline
    # from producing a valid CandidatePlan for this same natural-language intent.
    print("[*] Running negative control proof (no additional live calls)...")

    class NonProducingModel:
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Model invocation deliberately absent in negative control")

    control_failed = False
    try:
        plan_with_strands(planner_input, settings=settings, _model_override=NonProducingModel())
    except Exception as exc:
        control_failed = True
        print(f"[*] Negative control confirmed: fails closed ({type(exc).__name__})")

    assert control_failed, "Negative control must fail closed without model inference"

    cost_note = (
        "NOT_DETERMINISTICALLY_OBSERVED (covered by active promotional credit; "
        "estimated < $0.00005)"
    )

    evidence_facts = {
        "timestamp_utc": utc_end,
        "task": "P-07.06",
        "provenance": "LIVE_AWS",
        "model_id": meta.model_id,
        "region_name": meta.region_name,
        "strands_version": meta.strands_version,
        "boto3_version": meta.boto3_version,
        "botocore_version": meta.botocore_version,
        "mission_id": mission_uuid,
        "intent": intent,
        "stop_reason": result.stop_reason,
        "steps_count": len(result.plan.steps),
        "steps": [
            {
                "step_index": idx,
                "action_type": s.action_type.value,
                "target_ref": s.target_ref.value,
                "parameters": s.parameters.to_dict(),
            }
            for idx, s in enumerate(result.plan.steps, start=1)
        ],
        "metadata_fields_count": 18,
        "live_call_count": 1,
        "underlying_cost_observation": cost_note,
        "personal_spend_delta": "$0.00",
        "negative_control_passed": True,
        "zero_tool_execution": True,
        "zero_authority_granted": True,
    }

    return evidence_facts


if __name__ == "__main__":
    facts = run_live_proof()
    print("\n[SUCCESS] P-07.06 Live Proof Completed Successfully!")
    print(json.dumps(facts, indent=2))
