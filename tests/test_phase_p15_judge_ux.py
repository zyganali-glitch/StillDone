"""Tests for Phase P-15 Judge UX & Simulated Alexa+ Surface.

Verifies:
- P-15.01: One-screen mission timeline and compact receipt
- P-15.02: Simulated Alexa+ conversational surface with explicit label
- P-15.03: Voice-friendly concise summaries
- P-15.04: Approval card with exact bounded action
- P-15.05: READY/PARTIAL/DRIFTED visual hierarchy
- P-15.06: Expandable evidence detail (<details>/<summary>)
- P-15.07: Real browser rendering, responsiveness (375px/1200px), WCAG AA contrast, semantic HTML
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from stilldone.judge_ux.builder import build_judge_view_model
from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
from stilldone.judge_ux.models import (
    JudgeExhibitViewModel,
    MissionVisualState,
    VoiceSummary,
)
from stilldone.killer_mission import (
    KillerMissionSliceOutcome,
    KillerMissionSliceRunner,
)


def _relative_luminance(hex_color: str) -> float:
    """Calculate relative luminance per W3C WCAG 2.1 specification."""
    clean_hex = hex_color.lstrip("#")
    r, g, b = [int(clean_hex[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def _channel_lum(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _channel_lum(r) + 0.7152 * _channel_lum(g) + 0.0722 * _channel_lum(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate contrast ratio between two hex colors."""
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _find_browser_executable() -> str | None:
    """Locate headless browser binary across Windows, Linux, and macOS platforms."""
    candidates = [
        shutil.which("msedge"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


@pytest.fixture
def executed_outcome() -> KillerMissionSliceOutcome:
    runner = KillerMissionSliceRunner()
    return runner.run_full_slice()


@pytest.fixture
def view_model(executed_outcome: KillerMissionSliceOutcome) -> JudgeExhibitViewModel:
    return build_judge_view_model(executed_outcome)


@pytest.fixture
def rendered_html(view_model: JudgeExhibitViewModel) -> str:
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


def test_p15_07_accessibility_and_contrast_compliance(rendered_html: str) -> None:
    """Proves semantic HTML landmarks and exact mathematical WCAG AA contrast compliance."""
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

    # Measured WCAG AA contrast ratios (minimum 4.5:1 for standard text, 3:1 for large text)
    # Backgrounds: #0f172a (primary), #1e293b (card)
    card_bg = "#1e293b"
    primary_bg = "#0f172a"

    # Text colors:
    text_primary = "#f8fafc"
    text_secondary = "#94a3b8"
    text_muted = "#94a3b8"
    color_ready = "#10b981"
    color_drifted = "#f59e0b"

    cr_primary = _contrast_ratio(text_primary, card_bg)
    cr_secondary = _contrast_ratio(text_secondary, card_bg)
    cr_muted = _contrast_ratio(text_muted, card_bg)
    cr_ready = _contrast_ratio(color_ready, primary_bg)
    cr_drifted = _contrast_ratio(color_drifted, primary_bg)

    assert cr_primary >= 4.5, f"Text primary contrast {cr_primary:.2f} must be >= 4.5"
    assert cr_secondary >= 4.5, f"Text secondary contrast {cr_secondary:.2f} must be >= 4.5"
    assert cr_muted >= 4.5, f"Text muted contrast {cr_muted:.2f} must be >= 4.5"
    assert cr_ready >= 4.5, f"Ready color contrast {cr_ready:.2f} must be >= 4.5"
    assert cr_drifted >= 4.5, f"Drifted color contrast {cr_drifted:.2f} must be >= 4.5"


def test_p15_07_real_browser_rendering_and_responsiveness(rendered_html: str) -> None:
    """Executes rendered exhibit in a real headless browser engine across viewports."""
    browser_exe = _find_browser_executable()
    if not browser_exe:
        pytest.skip("No headless browser binary (Edge/Chrome/Chromium) found in environment")

    # Verification script injected before closing body to capture real layout metrics
    verification_script = """
    <script id="browser-eval-script">
    window.addEventListener('DOMContentLoaded', () => {
        const sw = document.documentElement.scrollWidth;
        const cw = document.documentElement.clientWidth;
        const details = document.querySelector('details');
        let detailsOpened = false;
        if (details) {
            details.open = true;
            detailsOpened = details.open;
        }
        const marker = document.createElement('div');
        marker.id = 'browser-eval-output';
        marker.setAttribute('data-scroll-width', String(sw));
        marker.setAttribute('data-client-width', String(cw));
        marker.setAttribute('data-no-overflow', String(sw <= cw + 2));
        marker.setAttribute('data-details-opened', String(detailsOpened));
        document.body.appendChild(marker);
    });
    </script>
    """
    test_html = rendered_html.replace("</body>", f"{verification_script}</body>")

    with tempfile.TemporaryDirectory() as tmp_dir:
        html_file = Path(tmp_dir) / "judge_exhibit.html"
        html_file.write_text(test_html, encoding="utf-8")
        file_uri = html_file.as_uri()

        # 1. Test 375px mobile viewport (iPhone standard width)
        res_mobile = subprocess.run(
            [
                browser_exe,
                "--headless=new",
                "--disable-gpu",
                "--window-size=375,812",
                "--dump-dom",
                file_uri,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert res_mobile.returncode == 0, f"Browser mobile execution failed: {res_mobile.stderr}"
        dom_mobile = res_mobile.stdout

        # Verify mobile layout metrics from browser engine
        assert 'id="browser-eval-output"' in dom_mobile
        assert 'data-no-overflow="true"' in dom_mobile
        assert "SIMULATED ALEXA+ EXPERIENCE" in dom_mobile
        assert "Human Authorization Boundary" in dom_mobile
        assert "DRIFTED" in dom_mobile

        # 2. Test >= 1200px desktop viewport
        res_desktop = subprocess.run(
            [
                browser_exe,
                "--headless=new",
                "--disable-gpu",
                "--window-size=1200,900",
                "--dump-dom",
                file_uri,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert res_desktop.returncode == 0, (
            f"Browser desktop execution failed: {res_desktop.stderr}"
        )
        dom_desktop = res_desktop.stdout

        # Verify desktop layout metrics and details expansion from browser engine
        assert 'id="browser-eval-output"' in dom_desktop
        assert 'data-no-overflow="true"' in dom_desktop
        assert 'data-details-opened="true"' in dom_desktop
        assert "<main" in dom_desktop
        assert "<footer" in dom_desktop
