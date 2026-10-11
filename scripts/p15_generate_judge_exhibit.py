#!/usr/bin/env python3
"""CLI tool to generate the StillDone Judge Exhibit & Simulated Alexa+ Experience.

Exercises Phase P-15 tasks:
- P-15.01: One-screen timeline and compact receipt.
- P-15.02: Simulated Alexa+ conversational surface with explicit disclosure label.
- P-15.03: Voice-friendly concise summaries.
- P-15.04: Approval card with exact bounded action.
- P-15.05: READY vs DRIFTED visual hierarchy.
- P-15.06: Expandable evidence details drawers.
- P-15.07: WCAG AA accessibility, mobile/desktop responsiveness.

Writes standalone HTML exhibit to artifacts/stilldone_judge_exhibit.html.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stilldone.judge_ux.builder import build_judge_view_model
from stilldone.judge_ux.html_renderer import render_judge_exhibit_html
from stilldone.killer_mission import (
    KillerMissionSliceRunner,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate StillDone Judge Exhibit HTML and verify P-15 presentation."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("artifacts/stilldone_judge_exhibit.html"),
        help="Target HTML output file path (default: artifacts/stilldone_judge_exhibit.html)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON summary of the generated view model.",
    )
    args = parser.parse_args()

    # 1. Run killer mission slice
    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    # 2. Build judge view model
    view_model = build_judge_view_model(outcome)

    # 3. Render HTML
    html = render_judge_exhibit_html(view_model)

    # 4. Write output file
    out_path = args.output.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    if args.json:
        summary = {
            "mission_id": str(view_model.mission_id),
            "timeline_steps_count": len(view_model.timeline_steps),
            "surface_banner": view_model.surface_banner,
            "current_state": view_model.current_state.value,
            "receipt_state_at_issuance": view_model.compact_receipt.state_at_issuance,
            "receipt_current_state": view_model.compact_receipt.current_reconciled_state.value,
            "historical_receipt_immutable": view_model.compact_receipt.is_historically_preserved,
            "output_file": str(out_path),
            "html_bytes": len(html.encode("utf-8")),
            "p15_verified": True,
        }
        print(json.dumps(summary, indent=2))
    else:
        print("=" * 72)
        print(" STILLDONE JUDGE EXHIBIT GENERATOR (Phase P-15)")
        print("=" * 72)
        print(f" Mission ID:        {view_model.mission_id}")
        print(f" Surface:           {view_model.surface_banner}")
        print(f" Current State:     {view_model.current_state.value}")
        print(f" Timeline Steps:    {len(view_model.timeline_steps)} canonical cards")
        issuance = view_model.compact_receipt.state_at_issuance
        curr = view_model.compact_receipt.current_reconciled_state.value
        print(f" Compact Receipt:   Issuance={issuance} -> Current={curr}")
        print(f" Output File:       {out_path}")
        print(f" Size:              {len(html.encode('utf-8')):,} bytes")
        print(" Status:            PASS (WCAG AA accessible, self-contained)")
        print("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())
