"""Tests for Phase P-15 Judge UX & Simulated Alexa+ Surface.

Verifies:
- P-15.01: One-screen mission timeline and compact receipt
- P-15.02: Simulated Alexa+ conversational surface with explicit label
- P-15.03: Voice-friendly concise summaries
- P-15.04: Approval card with exact bounded action
- P-15.05: READY/PARTIAL/DRIFTED visual hierarchy
- P-15.06: Expandable evidence detail (<details>/<summary>)
- P-15.07: Accessibility, responsive layout, semantic HTML
"""

from __future__ import annotations

import re

import pytest

from stilldone.judge_ux.builder import build_judge_view_model
from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
from stilldone.judge_ux.models import (
    BoundedApprovalAction,
    CompactReceiptView,
    JudgeExhibitViewModel,
    MissionVisualState,
    StepExecutionState,
    SurfaceMode,
    TimelineStepCard,
    VoiceSummary,
)
from stilldone.killer_mission import KillerMissionSliceRunner


@pytest.fixture
def executed_outcome():
    runner = KillerMissionSliceRunner()
    return runner.run_full_slice()


@pytest.fixture
def view_model(executed_outcome):
    return build_judge_view_model(executed_outcome)


@pytest.fixture
def rendered_html(view_model):
    return render_judge_exhibit_html(view_model)


def test_p15_01_one_screen_timeline_and_compact_receipt(
    view_model: JudgeExhibitViewModel, rendered_html: str
) -> None:
    # Timeline steps count: 7 canonical steps
    assert len(view_model.timeline_steps) == 7
    step_numbers = [s.step_number for s in view_model.timeline_steps]
    assert step_numbers == [1, 2, 3, 4, 5, 6, 7]

    # Compact receipt present and separated from current truth
    assert view_model.compact_receipt.state_at_issuance == "READY"
    assert view_model.compact_receipt.current_reconciled_state == MissionVisualState.DRIFTED
    assert view_model.compact_receipt.is_historically_preserved is True

    # Rendered HTML assertions
    assert "Immutable Historical Receipt" in rendered_html
    assert view_model.compact_receipt.receipt_hash in rendered_html
    assert "Receipt hash remains permanently unchanged" in rendered_html


def test_p15_02_simulated_alexa_conversational_surface_label(
    view_model: JudgeExhibitViewModel, rendered_html: str
) -> None:
    # Explicit disclosure badge
    assert "SIMULATED ALEXA+ EXPERIENCE" in view_model.surface_banner
    assert "SIMULATED ALEXA+ EXPERIENCE" in rendered_html
    assert "BACKEND: REAL STILLDONE DETERMINISTIC ENGINE" in rendered_html


def test_p15_03_voice_friendly_concise_summaries(
    view_model: JudgeExhibitViewModel, rendered_html: str
) -> None:
    voice = view_model.voice_summary
    assert isinstance(voice, VoiceSummary)
    assert len(voice.spoken_phrase) > 10
    assert voice.estimated_duration_sec > 0
    assert "Alexa+ Spoken Response" in rendered_html
    assert voice.spoken_phrase in rendered_html


def test_p15_04_approval_card_with_exact_bounded_action(
    view_model: JudgeExhibitViewModel, rendered_html: str
) -> None:
    card = view_model.approval_card
    assert card is not None
    assert card.action_type == "calendar.update"
    assert card.target_system == "Google Calendar"
    assert card.is_approved is True
    assert "Human Authorization Boundary" in rendered_html
    assert "Single-Use Grant" in rendered_html
    assert "calendar.update" in rendered_html


def test_p15_05_ready_vs_drifted_visual_hierarchy(
    view_model: JudgeExhibitViewModel, rendered_html: str
) -> None:
    # In killer mission final state is DRIFTED
    assert view_model.current_state == MissionVisualState.DRIFTED
    assert 'class="status-pill drifted"' in rendered_html
    assert 'class="status-hero-bar drifted"' in rendered_html
    assert "DRIFTED" in rendered_html


def test_p15_06_expandable_evidence_details(rendered_html: str) -> None:
    # Must use HTML5 semantic <details> and <summary>
    assert "<details" in rendered_html
    assert "<summary" in rendered_html
    assert "Inspect Evidence &amp; Read-back Facts" in rendered_html
    assert 'class="evidence-table"' in rendered_html


def test_p15_07_accessibility_and_responsive_checks(rendered_html: str) -> None:
    # Semantic landmark tags
    assert "<main" in rendered_html
    assert "<header" in rendered_html
    assert "<section" in rendered_html
    assert "<article" in rendered_html
    assert "<footer" in rendered_html

    # ARIA labels
    assert 'aria-label="Mission Timeline"' in rendered_html
    assert 'aria-label="Current Mission State"' in rendered_html

    # Responsive viewport meta tag
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in rendered_html

    # Zero external CDN script or stylesheet links (works offline)
    assert not re.search(r'<script\s+src="http', rendered_html)
    assert not re.search(r'<link\s+[^>]*href="http', rendered_html)
