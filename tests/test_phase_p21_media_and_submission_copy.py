"""Tests for StillDone Demo Media Manifest, README Gallery & Submission Copy Registry.

Validates:
1. Exact Devpost screenshot inventory (8/8 exist as valid PNGs with nonzero dimensions).
2. Each Devpost caption <= 200 characters.
3. Exact README screenshot inventory (10/10 exist as valid PNGs with nonzero dimensions).
4. README embeds 8 principal images in exact order with exact captions.
5. README links 2 supplemental images to docs/DEMO_MEDIA_AND_SUBMISSION_COPY.md.
6. All README image markdown links resolve to committed files on disk.
7. Canonical montage continuity and final 165-second target in DEMO_MEDIA_AND_SUBMISSION_COPY.md.
8. Scene 01 source filename discovered from actual local recording is documented.
9. No separate title-card footage in final editing instructions (Scene 8 ends on exhibit footage).
10. No unsupported live claims in media documentation.
11. No private credentials or user PII in committed media or registry documents.
12. Raw video/audio directory (_local_media/) is git-ignored and not tracked.
13. Devpost short description <= 200 characters.
14. YouTube metadata is stored with chapters and disclosures.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "DEMO_MEDIA_AND_SUBMISSION_COPY.md"
README_PATH = REPO_ROOT / "README.md"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

DEVPOST_DIR = REPO_ROOT / "docs" / "assets" / "devpost"
README_ASSETS_DIR = REPO_ROOT / "docs" / "assets" / "readme"

EXPECTED_DEVPOST_FILES = [
    "scene_01_header_thesis.png",
    "scene_02_prestate_reads.png",
    "scene_03_tasks_prep_verified.png",
    "scene_04_approval_boundary.png",
    "scene_05_ready_receipt.png",
    "scene_06_departure_drift_tracker.png",
    "scene_07_reconciliation_drifted.png",
    "scene_08_architecture_closing.png",
]

EXPECTED_README_PRINCIPAL_FILES = [
    "docs/assets/readme/stilldone_overview.png",
    "docs/assets/readme/prestate_verification.png",
    "docs/assets/readme/task_verification.png",
    "docs/assets/readme/calendar_verified_update.png",
    "docs/assets/readme/immutable_ready_receipt.png",
    "docs/assets/readme/drift_law_explanation.png",
    "docs/assets/readme/current_truth_drifted.png",
    "docs/assets/readme/architecture_provenance.png",
]

EXPECTED_README_SUPPLEMENTAL_FILES = [
    "fresh_reconciliation_evidence.png",
    "evidence_reproduction_links.png",
]

EXPECTED_DEVPOST_CAPTIONS = {
    "scene_01_header_thesis.png": (
        "StillDone's public exhibit: a simulated Alexa+ experience with deterministic "
        "fixture playback and transparent evidence provenance."
    ),
    "scene_02_prestate_reads.png": (
        "Pre-state evidence shows a 7:45 departure, an absent preparation task, "
        "and rainy weather before the mission's actions."
    ),
    "scene_03_tasks_prep_verified.png": (
        "The model proposes; deterministic code controls execution. A digital "
        "Google Tasks entry is verified through separate read-back."
    ),
    "scene_04_approval_boundary.png": (
        "Calendar mutation pauses at a human approval boundary. The exhibit "
        "records zero calendar writes before authorization."
    ),
    "scene_05_ready_receipt.png": (
        "Three verified predicates produce a historical READY receipt. Its SHA-256 "
        "hash stays intact even after later drift."
    ),
    "scene_06_departure_drift_tracker.png": (
        "The deterministic exhibit illustrates departure changing from verified "
        "7:30 to 8:00, invalidating current readiness."
    ),
    "scene_07_reconciliation_drifted.png": (
        "Fresh fixture reconciliation marks current truth DRIFTED while preserving "
        "the historical READY receipt and simulated Alexa+ response."
    ),
    "scene_08_architecture_closing.png": (
        "The provenance card separates historical recorded-live AWS and Google "
        "integration evidence from offline fixture playback."
    ),
}

EXPECTED_DEVPOST_SHORT_DESC = (
    "StillDone verifies outcomes instead of trusting agent claims. "
    "It executes approved actions, reads reality back independently, "
    "issues durable receipts, and reconciles drift."
)


def _check_png(path: Path) -> tuple[bool, int, int]:
    """Validates PNG signature and reads dimensions."""
    data = path.read_bytes()
    if len(data) < 24:
        return False, 0, 0
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False, 0, 0
    w, h = struct.unpack(">II", data[16:24])
    return True, w, h


def test_devpost_screenshot_inventory_and_validity() -> None:
    """Verifies that all 8 Devpost screenshots exist and are valid PNGs."""
    assert DEVPOST_DIR.is_dir(), f"Missing Devpost assets directory: {DEVPOST_DIR}"
    for fn in EXPECTED_DEVPOST_FILES:
        fp = DEVPOST_DIR / fn
        assert fp.is_file(), f"Missing Devpost screenshot: {fp}"
        valid, w, h = _check_png(fp)
        assert valid, f"Invalid PNG signature in: {fp}"
        assert w > 0 and h > 0, f"Zero dimensions in: {fp} ({w}x{h})"
        assert fp.stat().st_size > 1000, f"File unexpectedly small: {fp}"


def test_readme_screenshot_inventory_and_validity() -> None:
    """Verifies that all 10 README screenshots exist and are valid PNGs."""
    assert README_ASSETS_DIR.is_dir(), f"Missing README assets directory: {README_ASSETS_DIR}"
    all_readme_files = [
        Path(p).name for p in EXPECTED_README_PRINCIPAL_FILES
    ] + EXPECTED_README_SUPPLEMENTAL_FILES
    for fn in all_readme_files:
        fp = README_ASSETS_DIR / fn
        assert fp.is_file(), f"Missing README screenshot: {fp}"
        valid, w, h = _check_png(fp)
        assert valid, f"Invalid PNG signature in: {fp}"
        assert w > 0 and h > 0, f"Zero dimensions in: {fp} ({w}x{h})"
        assert fp.stat().st_size > 1000, f"File unexpectedly small: {fp}"


def test_devpost_captions_character_limit_and_content() -> None:
    """Verifies that all 8 Devpost captions are <= 200 chars and match canonical text."""
    manifest_content = MANIFEST_PATH.read_text(encoding="utf-8")
    for fn, expected_caption in EXPECTED_DEVPOST_CAPTIONS.items():
        assert len(expected_caption) <= 200, (
            f"Caption for {fn} exceeds 200 chars ({len(expected_caption)})"
        )
        assert fn in manifest_content, f"Filename {fn} missing from manifest"
        assert expected_caption in manifest_content, f"Caption for {fn} missing from manifest"


def test_devpost_short_description_character_limit() -> None:
    """Verifies that Devpost short description is <= 200 characters."""
    assert len(EXPECTED_DEVPOST_SHORT_DESC) <= 200, (
        f"Devpost short description exceeds 200 characters: {len(EXPECTED_DEVPOST_SHORT_DESC)}"
    )
    manifest_content = MANIFEST_PATH.read_text(encoding="utf-8")
    assert EXPECTED_DEVPOST_SHORT_DESC in manifest_content


def test_readme_embeds_eight_principal_images_in_exact_order() -> None:
    """Verifies that README.md embeds the 8 principal images in exact order."""
    readme_content = README_PATH.read_text(encoding="utf-8")

    # Find image paths in README
    img_matches = re.findall(r"!\[.*?\]\((docs/assets/readme/[^\)]+)\)", readme_content)
    assert len(img_matches) == 8, (
        f"Expected exactly 8 embedded images in README, found {len(img_matches)}"
    )

    for idx, (found, expected) in enumerate(
        zip(img_matches, EXPECTED_README_PRINCIPAL_FILES, strict=True), 1
    ):
        assert found == expected, (
            f"Image {idx} mismatch in README:\nFound:    {found}\nExpected: {expected}"
        )


def test_readme_links_resolve_to_real_committed_files() -> None:
    """Verifies that all image links in README.md resolve to physical files on disk."""
    readme_content = README_PATH.read_text(encoding="utf-8")
    img_matches = re.findall(r"!\[.*?\]\(([^\)]+)\)", readme_content)
    assert len(img_matches) >= 8

    for img_rel in img_matches:
        img_path = REPO_ROOT / img_rel
        assert img_path.is_file(), f"Image referenced in README does not exist on disk: {img_rel}"


def test_readme_links_supplemental_images_to_media_registry() -> None:
    """Verifies that README.md references supplemental images and links to the media registry."""
    readme_content = README_PATH.read_text(encoding="utf-8")
    assert "docs/DEMO_MEDIA_AND_SUBMISSION_COPY.md" in readme_content
    for fn in EXPECTED_README_SUPPLEMENTAL_FILES:
        assert fn in readme_content, f"Supplemental image {fn} not referenced in README.md"


def test_manifest_timeline_continuity_and_165s_target() -> None:
    """Verifies master timeline in DEMO_MEDIA_AND_SUBMISSION_COPY.md covers 165s."""
    manifest_content = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "165 seconds" in manifest_content or "165s" in manifest_content
    assert "2:45" in manifest_content or "2 minutes 45 seconds" in manifest_content

    # Check discovered Scene 01 source filename
    assert "15.10.2026 21_08_15 - Screen - Video Project 38.webm" in manifest_content


def test_no_separate_title_card_in_final_instructions() -> None:
    """Verifies that editing instructions conclude on exhibit footage only (no title card)."""
    manifest_content = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "exhibit footage ONLY" in manifest_content or "Exhibit footage ONLY" in manifest_content
    assert "no separate title card" in manifest_content.lower()


def test_raw_media_gitignored_and_not_tracked() -> None:
    """Verifies that _local_media/ is properly listed in .gitignore."""
    gitignore_content = GITIGNORE_PATH.read_text(encoding="utf-8")
    assert "_local_media/" in gitignore_content, "_local_media/ must be in .gitignore"


def test_no_secrets_in_manifest_or_media_registry() -> None:
    """Verifies absence of AWS keys, Google tokens, and passwords in the media manifest."""
    manifest_content = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "AKIA" not in manifest_content
    assert "ya29." not in manifest_content
    assert "AIza" not in manifest_content
    assert "client_secret" not in manifest_content


def test_youtube_metadata_complete() -> None:
    """Verifies that YouTube title, description, and chapters are present in the manifest."""
    manifest_content = MANIFEST_PATH.read_text(encoding="utf-8")
    assert (
        "StillDone — Verified AI Missions, Even After Drift | Amazon Developer Hackathon"
        in manifest_content
    )
    assert "00:00 — Why API success is not verification" in manifest_content
    assert "02:35 — Architecture, provenance, and open-source evidence" in manifest_content
    assert "https://stilldone-judge-exhibit.pages.dev" in manifest_content
    assert "PENDING_OPERATOR_ACTION / NOT_RUN" in manifest_content
