"""Tests for P-18.07: Verify judge-period availability plan and credit expiry.

Verifies:
- docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md exists and contains all required architectural sections.
- Distinction between official competition requirements and recommendations/assumptions.
- Historical credit record preservation ($150 promotion, conservative expiry 2028-08-31).
- Credit balance uncertainty acknowledged; current balance is NOT_OBSERVED offline.
- Zero personal spend law ($0.00) strictly upheld.
- Dual-surface architecture: public read-only exhibit separated from authenticated execution.
- Cloudflare Pages Free option evaluated: static-only, no domain purchase, does NOT execute Python.
- Bounded fallback plan defined.
- Zero infrastructure deployed, zero credentials exposed, zero paid services activated.
"""

from __future__ import annotations

from pathlib import Path


def test_judge_period_availability_plan_document_exists() -> None:
    """Verify that the availability plan document exists and has non-trivial content."""
    plan_path = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md")
    assert plan_path.is_file(), "docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md must exist"
    content = plan_path.read_text(encoding="utf-8")
    assert len(content) > 1000, "Plan document must have substantial content"


def test_plan_distinguishes_official_requirements_from_assumptions() -> None:
    """Verify official Devpost rules are distinguished from optional recommendations."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "Official Competition Requirement" in content
    assert "Platform Recommendation" in content
    assert "Unverified Assumption" in content
    assert "October 23, 2026" in content
    assert "3 minutes" in content or "max 3 minutes" in content
    assert "public code repository" in content.lower()


def test_plan_preserves_historical_credit_truth_and_expiry() -> None:
    """Verify credit grant ($150), conservative boundary (2028-08-31), and uncertainty."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "$150.00" in content
    assert "2028-08-31" in content  # Conservative expiry date
    assert "2028-09-01" in content  # Discrepancy acknowledged
    assert "NOT_OBSERVED" in content
    assert "Uncertainty" in content or "uncertainty" in content
    assert "hard cap" in content.lower() or "spending cap" in content.lower()


def test_plan_enforces_zero_personal_spend_law() -> None:
    """Verify Zero Personal Spend Law ($0.00) is explicitly preserved."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "$0.00" in content
    assert "Zero Personal Spend Law" in content


def test_plan_separates_public_exhibit_from_authenticated_runtime() -> None:
    """Verify dual-surface architecture separating exhibit from authenticated execution."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "Surface 1" in content or "SURFACE 1" in content
    assert "Surface 2" in content or "SURFACE 2" in content
    assert "Read-Only" in content or "read-only" in content
    assert "Authenticated" in content or "authenticated" in content
    assert "Operator" in content or "operator" in content


def test_plan_evaluates_cloudflare_pages_free_boundary() -> None:
    """Verify Cloudflare Pages Free boundary: static only, no domain purchase, no Python."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "Cloudflare Pages" in content
    assert "pages.dev" in content
    assert "no domain purchase" in content.lower() or "zero domain purchase" in content.lower()
    assert "not execute the python" in content.lower() or "no python execution" in content.lower()


def test_plan_defines_bounded_fallback_plan() -> None:
    """Verify three-tier bounded fallback plan if continuous cloud hosting cannot be proven safe."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "Bounded Fallback Plan" in content
    assert "Fallback Tier 1" in content
    assert "Fallback Tier 2" in content
    assert "Fallback Tier 3" in content
    assert "clean-checkout" in content.lower() or "local reproduction" in content.lower()


def test_plan_verifies_zero_infrastructure_deployment() -> None:
    """Verify that this task produces an implemented plan without deploying cloud infrastructure."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "IMPLEMENTED / QA_PENDING" in content
    has_deploy_notice = (
        "No infrastructure is provisioned" in content or "Zero infrastructure deployed" in content
    )
    assert has_deploy_notice


def test_plan_records_exact_official_deadline_and_judging_period() -> None:
    """Verify official deadline (Oct 23, 12:00 PM PDT / 22:00 TRT) and judging window (Nov 9–20)."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "October 23, 2026 at 12:00 PM PDT" in content
    assert "22:00 Europe/Istanbul" in content
    assert "November 9–20, 2026" in content


def test_plan_records_devpost_faq_vs_forum_visibility_ambiguity() -> None:
    """Verify documentation of Devpost FAQ vs Community Forum topics 45493 and 45411 conflict."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "Devpost FAQ vs. Community Forum Live-Hosting Conflict" in content
    assert "45493" in content
    assert "45411" in content
    assert "FAQ" in content
    assert "UNRESOLVED" in content
    assert "sanitized" in content.lower()


def test_plan_documents_rate_limiter_and_judge_interaction_model() -> None:
    """Verify persistent fixed-window rate limiter and judge interaction model."""
    content = Path("docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "RateLimitMiddleware" in content
    assert "fixed-window" in content.lower() or "fixed window" in content.lower()
    assert "no_paid_capability" in content.lower()
    assert "not_integrated" in content.lower()
    assert "max 3 minutes" in content
    assert "on-demand" in content.lower()
    # Confirm burst 20 / max 2 concurrent claims were removed
    assert "burst 20" not in content
    assert "2 concurrent" not in content
    # Confirm 60 req/min and token bucket claims were removed and profile defaults documented
    assert "60 req/min" not in content
    assert "token bucket" not in content.lower()
    assert "max_requests_per_window=10" in content
    assert "60-second window" in content
    assert "optional" in content.lower()
