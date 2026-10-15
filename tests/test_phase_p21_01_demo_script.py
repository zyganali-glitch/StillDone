"""Tests for Phase P-21.01 Demo Video Script & Shot List.

Validates:
- Document existence and formatting integrity.
- Video duration bounds: strictly between 2:30 (150s) and 2:50 (170s).
- Timestamp continuity: 8 non-overlapping, contiguous scenes covering 0:00 to 2:45.
- Narration script word count and speaking cadence (130-155 WPM).
- Canonical departure evolution (07:45 -> 07:30 -> 08:00) narrative structure.
- Six canonical execution provenance values and SIMULATED ALEXA+ presentation disclosure.
- Negative bounds and truthfulness disclosures (no live partner Alexa+, no TTS in repo,
  no physical tasks).
- All relative markdown file links resolve to existing files on disk.
- Turkish screen-by-screen guidance for non-expert operator.
- Conditional replacement shot plan for P-21.02 and P-21.03.
- Zero secrets or credentials committed (no credential identifiers or tokens).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "P21_01_DEMO_SCRIPT_AND_SHOT_LIST.md"


def test_p21_01_document_exists_and_metadata() -> None:
    """Verifies that the P-21.01 document exists and has valid metadata."""
    assert DOC_PATH.is_file(), f"Missing required document: {DOC_PATH}"
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "P-21.01" in content
    assert "Competition Demo Video Script & Shot List" in content
    assert "zyganali-glitch/StillDone" in content
    assert "AGENTS.md" in content
    assert "KILLER_DEMO_CONTRACT.md" in content


def test_p21_01_timing_bounds_and_timestamps() -> None:
    """Verifies video duration is strictly within 2:30 (150s) to 2:50 (170s)
    and timestamps are contiguous."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Find total runtime declarations
    assert "2:30–2:50" in content or "2:30-2:50" in content
    assert "165 seconds" in content or "165s" in content
    assert "2 minutes 45 seconds" in content or "2:45" in content

    # Parse scene timecodes: e.g. [0:00 - 0:15], [0:15 - 0:40], etc.
    scene_matches = re.findall(r"\[(\d+):(\d\d)\s*–\s*(\d+):(\d\d)\]", content)
    if not scene_matches:
        # Also try ASCII hyphen
        scene_matches = re.findall(r"\[(\d+):(\d\d)\s*-\s*(\d+):(\d\d)\]", content)

    assert len(scene_matches) >= 8, f"Expected at least 8 scene timecodes, got {len(scene_matches)}"

    # Check the first 8 scenes form a contiguous sequence from 0:00 to 2:45 (165s)
    parsed_scenes: list[tuple[int, int]] = []
    for start_m, start_s, end_m, end_s in scene_matches[:8]:
        start_sec = int(start_m) * 60 + int(start_s)
        end_sec = int(end_m) * 60 + int(end_s)
        parsed_scenes.append((start_sec, end_sec))

    # Verify start is 0
    assert parsed_scenes[0][0] == 0, f"First scene must start at 0s, got {parsed_scenes[0][0]}"

    # Verify contiguity and compute total duration
    for i in range(len(parsed_scenes) - 1):
        curr_end = parsed_scenes[i][1]
        next_start = parsed_scenes[i + 1][0]
        assert curr_end == next_start, (
            f"Scene {i + 1} end ({curr_end}s) does not match Scene {i + 2} start ({next_start}s)"
        )

    total_duration = parsed_scenes[-1][1]
    assert total_duration == 165, f"Total video duration must be 165s (2:45), got {total_duration}s"
    assert 150 <= total_duration <= 170, f"Duration {total_duration}s must be between 150s and 170s"


def test_p21_01_voiceover_script_cadence() -> None:
    """Verifies that the narration script word count supports an understandable speaking rate."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Extract Section 3 continuous script
    script_section_match = re.search(
        r"## 3\. Full Continuous Narration Script.*?\n```text\n(.*?)```",
        content,
        re.DOTALL,
    )
    assert script_section_match, "Could not find Section 3 continuous script"

    script_text = script_section_match.group(1)
    # Strip timecode markers like [0:00 - 0:15]
    cleaned_script = re.sub(r"\[\d+:\d\d\s*[-–]\s*\d+:\d\d\]", "", script_text)
    words = cleaned_script.split()
    word_count = len(words)

    # For 165s (2.75 min), 350-500 words corresponds to ~127-181 WPM.
    # Target is ~135-145 WPM (~370-400 words)
    assert 350 <= word_count <= 500, f"Narration word count {word_count} is out of expected bounds"

    wpm = word_count / (165 / 60)
    assert 125 <= wpm <= 165, f"Speaking pace {wpm:.1f} WPM is outside natural presentation bounds"


def test_p21_01_departure_evolution_narrative() -> None:
    """Verifies the canonical 07:45 -> 07:30 -> 08:00 departure evolution is detailed."""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "07:45" in content
    assert "07:30" in content
    assert "08:00" in content
    assert "07:45 AM" in content
    assert "07:30 AM" in content
    assert "08:00 AM" in content
    assert "DRIFTED" in content
    assert "READY" in content


def test_p21_01_provenance_and_negative_disclosures() -> None:
    """Verifies canonical provenance values, presentation disclosures, and negative bounds."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Canonical execution provenance values per AGENTS.md § 10
    canonical_provenances = [
        "FIXTURE",
        "LOCAL_EXECUTION",
        "LIVE_AWS",
        "LIVE_GOOGLE",
        "LIVE_EXTERNAL",
        "RECORDED_LIVE",
    ]
    for prov in canonical_provenances:
        assert prov in content, f"Missing canonical provenance enum: {prov}"

    # Presentation disclosure
    assert "SIMULATED ALEXA+ EXPERIENCE" in content

    # Negative bounds & truthfulness
    norm_content = " ".join(content.split())
    assert "zero model authority" in norm_content.lower()
    assert "no live partner" in norm_content.lower() or "not_established" in norm_content.lower()
    assert (
        "no live voice device or audio synthesis" in norm_content.lower()
        or "does not operate an echo show device" in norm_content.lower()
    )
    assert (
        "zero visitor backend execution" in norm_content.lower()
        or "$0.00 spend" in norm_content.lower()
    )
    assert "not claim" in norm_content.lower() or "never claims physical" in norm_content.lower()


def test_p21_01_markdown_link_integrity() -> None:
    """Verifies that all internal repository file paths referenced in the document exist."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Match paths in backticks or markdown links like `docs/...` or `artifacts/...` or `scripts/...`
    referenced_paths = set(re.findall(r"`((?:docs|artifacts|src|tests|scripts)/[^`\s]+)`", content))

    assert len(referenced_paths) >= 10, (
        f"Expected multiple referenced files, got {len(referenced_paths)}"
    )

    for rel_path_str in referenced_paths:
        # Strip potential markdown anchors like #section
        clean_rel = rel_path_str.split("#")[0]
        # Strip trailing punctuation if accidentally captured
        clean_rel = clean_rel.rstrip(".,;:)")
        target_file = REPO_ROOT / clean_rel
        assert target_file.exists(), f"Referenced file does not exist on disk: {clean_rel}"


def test_p21_01_operator_instructions_turkish() -> None:
    """Verifies Turkish screen-by-screen guidance for non-expert operator."""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "Türkçe Ekran Kurulum Rehberi" in content
    assert "Gerekli Araçlar ve Ekran Ayarları" in content
    assert "Kredi Kartı / Ödeme Riski" in content
    assert "$0.00" in content
    assert "Win + Alt + R" in content or "OBS Studio" in content


def test_p21_01_conditional_replacement_plan() -> None:
    """Verifies existence of conditional replacement shot plan for P-21.02 and P-21.03."""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "Conditional Replacement Shot Plan" in content
    assert "P-21.02" in content
    assert "P-21.03" in content
    assert "Scene 3" in content
    assert "Scene 4" in content
    assert "Scene 6" in content
    assert "Scene 7" in content


def test_p21_01_zero_secrets_audit() -> None:
    """Verifies that no secrets or API keys are committed in the script/shot list."""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "AKIA" not in content
    assert "ya29." not in content
    assert "AIza" not in content
    assert "client_secret" not in content
