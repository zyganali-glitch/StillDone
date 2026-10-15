"""Tests for Phase P-21.01 Demo Video Script & Shot List.

Validates:
- Document existence, governance, and metadata integrity.
- Official Devpost timing rule (< 3:00 / < 180s) vs internal editorial target (2:30–2:50).
- Contiguous 8-scene structure covering exactly 165 seconds (2:45).
- Exact per-scene narration text parity between Section 2 and Section 3.
- Authoritative word counts per scene and aggregate speaking cadence (~129.5 WPM, 356 words).
- Canonical departure evolution (07:45 -> 07:30 -> 08:00) narrative structure.
- Six canonical execution provenance values and SIMULATED ALEXA+ presentation disclosure.
- Negative bounds and truthfulness disclosures (no live partner Alexa+, no TTS in repo,
  no physical task completion, zero visitor backend execution on static site).
- UI parity: Baseline shots use actual static exhibit sections and details/summary controls;
  Scene 5 uses title card/callout; Scene 6 baseline uses exhibit departure tracker and drift card.
- Baseline HTML selectors actually exist in generated exhibit output (no .header or Server: /mcp).
- Listed evidence details in Section 2 actually appear in generated exhibit output.
- Rejection of unsupported visitor-side live execution and physical backpack claims.
- Canonical media directories structure and paths.
- Live preflight requirements accurately stated (not just --live --operator-approved).
- Honest phase status: Future video/audio/playback gates are NOT marked PASS.
- All relative markdown file links resolve to existing files on disk.
- Turkish screen-by-screen guidance for non-expert operator.
- Conditional replacement shot plan for P-21.02 and P-21.03.
- Targeted credential pattern checks (absence of credential prefixes).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "P21_01_DEMO_SCRIPT_AND_SHOT_LIST.md"
EXHIBIT_PATH = REPO_ROOT / "artifacts" / "judge_exhibit" / "index.html"

EXPECTED_SCENE_DURATIONS = [15, 25, 25, 30, 20, 20, 20, 10]
EXPECTED_SCENE_WORD_COUNTS = [36, 52, 54, 62, 44, 43, 43, 22]
EXPECTED_TOTAL_WORDS = 356


def test_p21_01_document_exists_and_metadata() -> None:
    """Verifies that the P-21.01 document exists and has valid metadata."""
    assert DOC_PATH.is_file(), f"Missing required document: {DOC_PATH}"
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "P-21.01" in content
    assert "Competition Demo Video Script & Shot List" in content
    assert "zyganali-glitch/StillDone" in content
    assert "AGENTS.md" in content
    assert "KILLER_DEMO_CONTRACT.md" in content


def test_p21_01_official_devpost_timing_vs_internal_target() -> None:
    """Verifies official Devpost video rule (< 3:00) vs internal editorial target (2:30-2:50)."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Official Devpost rule distinction
    assert "Under 3 minutes (< 3:00 / < 180s)" in content or "under 3 minutes" in content.lower()
    assert "Devpost" in content

    # Internal editorial target
    assert "2:30–2:50" in content or "2:30-2:50" in content
    assert "165 seconds" in content or "165s" in content
    assert "2 minutes 45 seconds" in content or "2:45" in content


def test_p21_01_scene_timestamps_and_continuity() -> None:
    """Verifies that 8 contiguous scenes cover exactly 0:00 to 2:45 (165s)."""
    content = DOC_PATH.read_text(encoding="utf-8")

    scene_matches = re.findall(r"\[(\d+):(\d\d)\s*[-–]\s*(\d+):(\d\d)\]", content)
    assert len(scene_matches) >= 8, f"Expected at least 8 scene timecodes, got {len(scene_matches)}"

    parsed_scenes: list[tuple[int, int]] = []
    for start_m, start_s, end_m, end_s in scene_matches[:8]:
        start_sec = int(start_m) * 60 + int(start_s)
        end_sec = int(end_m) * 60 + int(end_s)
        parsed_scenes.append((start_sec, end_sec))

    assert parsed_scenes[0][0] == 0, f"First scene must start at 0s, got {parsed_scenes[0][0]}"

    for i in range(len(parsed_scenes) - 1):
        curr_end = parsed_scenes[i][1]
        next_start = parsed_scenes[i + 1][0]
        assert curr_end == next_start, (
            f"Scene {i + 1} end ({curr_end}s) does not match Scene {i + 2} start ({next_start}s)"
        )

    for i, (start_sec, end_sec) in enumerate(parsed_scenes):
        dur = end_sec - start_sec
        expected_dur = EXPECTED_SCENE_DURATIONS[i]
        assert dur == expected_dur, (
            f"Scene {i + 1} duration {dur}s does not match expected {expected_dur}s"
        )

    total_duration = parsed_scenes[-1][1]
    assert total_duration == 165, f"Total video duration must be 165s (2:45), got {total_duration}s"


def test_p21_01_narration_parity_counts_and_cadence() -> None:
    """Verifies exact per-scene narration parity, word counts, and speaking cadence."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Extract Section 3 continuous script
    script_section_match = re.search(
        r"## 3\. Full Continuous Narration Script.*?\n```text\n(.*?)```",
        content,
        re.DOTALL,
    )
    assert script_section_match, "Could not find Section 3 continuous script"
    script_text = script_section_match.group(1).strip()

    # Split Section 3 into scene blocks by [MM:SS - MM:SS]
    blocks = re.split(r"\[\d+:\d\d\s*[-–]\s*\d+:\d\d\]\n", script_text)
    # Filter empty blocks
    scene_texts = [b.strip() for b in blocks if b.strip()]
    assert len(scene_texts) == 8, (
        f"Expected 8 narration blocks in Section 3, got {len(scene_texts)}"
    )

    total_words = 0
    for idx, (scene_text, expected_count, expected_dur) in enumerate(
        zip(scene_texts, EXPECTED_SCENE_WORD_COUNTS, EXPECTED_SCENE_DURATIONS, strict=True), 1
    ):
        words = scene_text.split()
        word_count = len(words)
        total_words += word_count

        assert word_count == expected_count, (
            f"Scene {idx} word count {word_count} does not match expected {expected_count}"
        )

        wpm = word_count / (expected_dur / 60)
        assert 115 <= wpm <= 150, (
            f"Scene {idx} cadence {wpm:.1f} WPM is outside comfortable presentation bounds"
        )

    assert total_words == EXPECTED_TOTAL_WORDS, (
        f"Total word count must be exactly {EXPECTED_TOTAL_WORDS} words, got {total_words}"
    )
    avg_wpm = total_words / (165 / 60)
    assert 125 <= avg_wpm <= 135, f"Average cadence {avg_wpm:.1f} WPM must be around ~129.5 WPM"


def test_p21_01_exact_narration_parity_section2_and_section3() -> None:
    """Verifies exact word-for-word parity between Section 2 scene narration
    and Section 3 script."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Extract Section 2 narration blocks
    sec2_matches = re.findall(
        r"-\s*\*\*Spoken Voiceover Narration \(English\)\*\*:\s*\n\s*>\s*\*(.*?)\*",
        content,
    )
    assert len(sec2_matches) == 8, (
        f"Expected 8 narration blocks in Section 2, got {len(sec2_matches)}"
    )

    # Extract Section 3 continuous script blocks
    script_section_match = re.search(
        r"## 3\. Full Continuous Narration Script.*?\n```text\n(.*?)```",
        content,
        re.DOTALL,
    )
    assert script_section_match, "Could not find Section 3 continuous script"
    script_text = script_section_match.group(1).strip()
    blocks = re.split(r"\[\d+:\d\d\s*[-–]\s*\d+:\d\d\]\n", script_text)
    sec3_texts = [b.strip() for b in blocks if b.strip()]
    assert len(sec3_texts) == 8, f"Expected 8 blocks in Section 3, got {len(sec3_texts)}"

    for idx, (raw_sec2, raw_sec3) in enumerate(zip(sec2_matches, sec3_texts, strict=True), 1):
        # Clean quotes and normalize internal whitespace
        clean_sec2 = raw_sec2.strip().strip('"').strip("'")
        clean_sec3 = raw_sec3.strip().strip('"').strip("'")
        norm_sec2 = " ".join(clean_sec2.split())
        norm_sec3 = " ".join(clean_sec3.split())

        assert norm_sec2 == norm_sec3, (
            f"Narration mismatch in Scene {idx}:\nSection 2: {norm_sec2}\nSection 3: {norm_sec3}"
        )


def test_p21_01_ui_parity_and_shootability() -> None:
    """Verifies that baseline shots map to static exhibit elements and no live animations."""
    content = DOC_PATH.read_text(encoding="utf-8")
    norm_content = " ".join(content.split())

    # Verifies static exhibit references
    assert "artifacts/judge_exhibit/index.html" in content
    assert "<summary>" in content or "summary" in content.lower()
    assert "departure-story-card" in content or "departure lifecycle" in content.lower()
    assert "#approval-title" in content
    assert "#receipt-title" in content
    assert "#drift-title" in content
    assert "#prov-title" in content

    # Verifies Scene 5 uses title card / milestone callout, not interactive state transition
    assert "READY AT ISSUANCE" in content
    assert (
        "not attempt to click" in norm_content.lower() or "no interactive" in norm_content.lower()
    )

    # Verifies Scene 6 baseline uses static exhibit, not unapproved live Google Calendar
    assert (
        "baseline uses static exhibit" in norm_content.lower()
        or "baseline recording uses the static exhibit" in norm_content.lower()
    )
    assert "conditional" in norm_content.lower()


def test_p21_01_referenced_selectors_exist_in_exhibit() -> None:
    """Verifies that referenced baseline HTML selectors actually exist in exhibit output."""
    assert EXHIBIT_PATH.is_file(), f"Missing generated exhibit at: {EXHIBIT_PATH}"
    exhibit_html = EXHIBIT_PATH.read_text(encoding="utf-8")
    content = DOC_PATH.read_text(encoding="utf-8")

    # Positive selector checks: referenced classes, IDs, and tags must exist in exhibit HTML
    expected_selectors = [
        "brand-header",
        "fixture-notice",
        "intent-title",
        "departure-story-card",
        "approval-title",
        "receipt-title",
        "drift-title",
        "prov-title",
        "status-hero-bar",
        "voice-card",
        "footer",
    ]
    for selector in expected_selectors:
        assert selector in exhibit_html, (
            f"Referenced selector '{selector}' not found in exhibit HTML"
        )

    # Specific repair checks: nonexistent .header and Server: /mcp must NOT be referenced
    assert "`.header`" not in content, (
        "Scene 1 references nonexistent .header (must use .brand-header)"
    )
    assert "Server: /mcp" not in content, "Scene 2 references nonexistent 'Server: /mcp' text"

    # Scene 8 describes provenance card, not a table
    sec2_scene8_match = re.search(r"### Scene 8:.*?(?=---|\Z)", content, re.DOTALL)
    assert sec2_scene8_match, "Scene 8 section not found"
    scene8_text = sec2_scene8_match.group(0)
    assert "provenance table" not in scene8_text.lower(), (
        "Scene 8 should describe provenance card, not table"
    )


def test_p21_01_listed_evidence_details_appear_in_exhibit() -> None:
    """Verifies that listed evidence properties from Section 2 appear in exhibit output."""
    assert EXHIBIT_PATH.is_file(), f"Missing generated exhibit at: {EXHIBIT_PATH}"
    exhibit_html = EXHIBIT_PATH.read_text(encoding="utf-8")

    expected_evidence_facts = [
        ("start_time", "07:45:00 UTC"),
        ("prep_task_absent", "True"),
        ("weather", "mild/rainy"),
        ("model_authority", "ZERO"),
        ("task_title", "Pack backpacks"),
        ("status", "needsAction"),
        ("approval_required", "True"),
        ("calendar_writes", "0"),
        ("start_time", "07:30:00 UTC"),
        ("writes_performed", "1"),
        ("predicates_count", "3"),
        ("observed_start", "08:00:00 UTC"),
        ("predicate_truth", "False"),
    ]
    for key, val in expected_evidence_facts:
        assert key in exhibit_html, f"Expected evidence key '{key}' not found in exhibit HTML"
        assert val in exhibit_html, f"Expected evidence value '{val}' not found in exhibit HTML"


def test_p21_01_reject_unsupported_live_claims_and_backpack_physical_claims() -> None:
    """Verifies rejection of unsupported visitor live execution and physical claims."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Extract all narration text (Section 2 and Section 3)
    script_section_match = re.search(
        r"## 3\. Full Continuous Narration Script.*?\n```text\n(.*?)```",
        content,
        re.DOTALL,
    )
    assert script_section_match
    continuous_script = script_section_match.group(1)

    # 1. No unqualified live claims in fixture playback narration
    assert "live in Google Calendar" not in continuous_script, (
        "Scene 4 narration must not claim 'live in Google Calendar' during fixture playback"
    )

    # 2. No claims of physical backpack completion
    assert "backpacks verified" not in continuous_script.lower(), (
        "Scene 5 narration must not claim 'backpacks verified' (use digital prep task)"
    )

    # 3. Explicit references to digital prep task
    assert "digital prep task" in continuous_script.lower()

    # 4. Truthful qualification of read-back proof
    assert "recorded Google Calendar proof" in continuous_script
    assert "evaluates fresh read-back proof" in continuous_script


def test_p21_01_canonical_media_directories() -> None:
    """Verifies that all 6 canonical media capture destinations are specified and structured."""
    content = DOC_PATH.read_text(encoding="utf-8")

    canonical_dirs = [
        "docs/assets/devpost/",
        "docs/assets/readme/",
        "_local_media/raw_clips/",
        "_local_media/voiceover/",
        "_local_media/captions/",
        "_local_media/final_export/",
    ]
    for media_dir in canonical_dirs:
        assert media_dir in content, f"Missing canonical media directory in doc: {media_dir}"

    # Verifies that screenshot targets use docs/assets/devpost/
    for i in range(1, 9):
        pattern = f"docs/assets/devpost/scene_{i:02d}_"
        assert pattern in content, f"Scene {i} screenshot target does not use {pattern}"

    # Verifies tracked directory structure exists
    assert (REPO_ROOT / "docs" / "assets" / "devpost").is_dir()
    assert (REPO_ROOT / "docs" / "assets" / "readme").is_dir()


def test_p21_01_provenance_and_negative_disclosures() -> None:
    """Verifies canonical provenance values, presentation disclosures, and negative bounds."""
    content = DOC_PATH.read_text(encoding="utf-8")

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

    assert "SIMULATED ALEXA+ EXPERIENCE" in content

    norm_content = " ".join(content.split())
    assert "zero model authority" in norm_content.lower()
    assert "not_established" in norm_content.lower() or "no live partner" in norm_content.lower()
    assert "no live voice device or audio synthesis" in norm_content.lower()
    assert "zero visitor backend execution" in norm_content.lower()
    assert (
        "never claims physical" in norm_content.lower()
        or "digital preparation task" in norm_content.lower()
    )


def test_p21_01_live_preflight_accuracy() -> None:
    """Verifies that live execution preflight requirements are accurately specified."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Verifies required live flags in Section 5
    assert "--operator-approved" in content
    assert "--source-sha" in content
    assert "--storage-dir" in content
    assert "--demo-calendar-id" in content
    assert "--demo-task-list-id" in content
    assert "alone will halt fail-closed" in content or "halt fail-closed" in content


def test_p21_01_honest_phase_status() -> None:
    """Verifies that future execution gates are NOT falsely marked as PASS."""
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "SCRIPT_FROZEN" in content
    assert "PLANNED / NOT_RUN" in content
    assert "DOCUMENTED_AND_VERIFIED" in content
    assert "POLICY_VERIFIED" in content
    assert "VERIFIED_TARGETED_SCAN" in content


def test_p21_01_markdown_link_integrity() -> None:
    """Verifies that all internal repository file paths referenced in the document exist."""
    content = DOC_PATH.read_text(encoding="utf-8")

    referenced_paths = set(re.findall(r"`((?:docs|artifacts|src|tests|scripts)/[^`\s]+)`", content))
    assert len(referenced_paths) >= 10, (
        f"Expected multiple referenced files, got {len(referenced_paths)}"
    )

    for rel_path_str in referenced_paths:
        clean_rel = rel_path_str.split("#")[0]
        clean_rel = clean_rel.rstrip(".,;:)")
        if clean_rel.startswith("docs/assets/"):
            target_dir = (REPO_ROOT / clean_rel).parent
            assert target_dir.is_dir(), f"Asset destination directory does not exist: {target_dir}"
        else:
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
    """Verifies existence and modular swap structure for P-21.02 and P-21.03."""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "Conditional Replacement Shot Plan" in content
    assert "P-21.02" in content
    assert "P-21.03" in content
    assert "Scene 3 Swap" in content
    assert "Scene 4 Swap" in content
    assert "Scene 6 Swap" in content
    assert "Scene 7 Swap" in content


def test_p21_01_targeted_secrets_check() -> None:
    """Verifies targeted absence of AWS and Google credential prefixes."""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "AKIA" not in content
    assert "ya29." not in content
    assert "AIza" not in content
    assert "client_secret" not in content
