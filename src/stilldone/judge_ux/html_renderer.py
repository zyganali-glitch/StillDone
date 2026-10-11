"""HTML and CSS Renderer for StillDone Judge Exhibit & Simulated Alexa+ Surface.

Phase P-15 Requirements:
- P-15.01: One-screen mission timeline and compact receipt
- P-15.02: Prominent "SIMULATED ALEXA+ EXPERIENCE" label
- P-15.03: Voice-friendly concise summaries
- P-15.04: Bounded approval card
- P-15.05: READY/PARTIAL/DRIFTED visual hierarchy
- P-15.06: Expandable evidence details (<details>/<summary>)
- P-15.07: WCAG AA contrast, responsive mobile/desktop layout, 0 external dependencies
"""

from __future__ import annotations

import html
from typing import Any

from stilldone.judge_ux.models import (
    JudgeExhibitViewModel,
    MissionVisualState,
    StepExecutionState,
)


def render_judge_exhibit_html(model: JudgeExhibitViewModel) -> str:
    """Render a fully self-contained, accessible, responsive HTML document."""
    intent_escaped = html.escape(model.user_intent)
    mission_id_short = html.escape(model.mission_id[:8])
    status_class = model.current_state.value.lower()

    # Timeline cards HTML
    timeline_items_html: list[str] = []
    for step in model.timeline_steps:
        step_state_badge = f'<span class="badge badge-{step.state.value.lower()}">{html.escape(step.state.value)}</span>'
        prov_badge = f'<span class="badge badge-prov">{html.escape(step.provenance)}</span>'

        # Expandable evidence details
        props_rows = "".join(
            f"<tr><th>{html.escape(str(k))}</th><td><code>{html.escape(str(v))}</code></td></tr>"
            for k, v in step.evidence_properties.items()
        )
        evidence_html = f"""
        <details class="evidence-details">
            <summary class="evidence-summary">Inspect Evidence &amp; Read-back Facts ({len(step.evidence_properties)} properties)</summary>
            <div class="evidence-content">
                <table class="evidence-table">
                    <tbody>{props_rows}</tbody>
                </table>
                {f'<p class="hash-trace"><strong>Receipt Hash:</strong> <code>{html.escape(step.cryptographic_hash)}</code></p>' if step.cryptographic_hash else ''}
            </div>
        </details>
        """

        timeline_items_html.append(f"""
        <article class="timeline-item {'drifted-item' if step.is_drifted else ''}" aria-label="Step {step.step_number}: {html.escape(step.title)}">
            <div class="timeline-marker">{step.step_number}</div>
            <div class="timeline-body">
                <header class="timeline-header">
                    <div class="timeline-title-row">
                        <span class="task-tag">{html.escape(step.task_id)}</span>
                        <h3 class="step-title">{html.escape(step.title)}</h3>
                    </div>
                    <div class="timeline-badges">
                        {prov_badge}
                        {step_state_badge}
                    </div>
                </header>
                <p class="timeline-desc">{html.escape(step.summary)}</p>
                <div class="timeline-meta">
                    <span>Writes: <strong>{step.writes_performed}</strong></span>
                    <span>Read-back: <strong>{'Verified' if step.independent_readback_verified else 'None'}</strong></span>
                </div>
                {evidence_html}
            </div>
        </article>
        """)

    timeline_html = "\n".join(timeline_items_html)

    # Approval card HTML
    approval_html = ""
    if model.approval_card:
        card = model.approval_card
        approval_html = f"""
        <section class="card approval-card" aria-labelledby="approval-title">
            <header class="card-header">
                <h3 id="approval-title" class="card-title">Human Authorization Boundary</h3>
                <span class="badge badge-approved">{'APPROVED' if card.is_approved else 'PENDING'}</span>
            </header>
            <div class="approval-body">
                <p class="approval-desc"><strong>Target Action:</strong> <code>{html.escape(card.action_type)}</code> on <strong>{html.escape(card.target_system)}</strong></p>
                <p class="approval-proposal">{html.escape(card.proposed_change_description)}</p>
                <div class="fingerprint-box">
                    <span class="fingerprint-label">Tamper-Evident Fingerprint:</span>
                    <code class="fingerprint-hash">{html.escape(card.fingerprint[:32])}...</code>
                </div>
                <div class="approval-footer">
                    <span class="auth-notice">Single-Use Grant bound to target and payload hash. Replays strictly rejected.</span>
                </div>
            </div>
        </section>
        """

    # Compact receipt HTML
    receipt = model.compact_receipt
    receipt_html = f"""
    <section class="card receipt-card" aria-labelledby="receipt-title">
        <header class="card-header">
            <h3 id="receipt-title" class="card-title">Immutable Historical Receipt</h3>
            <span class="badge badge-ready">{html.escape(receipt.state_at_issuance)} AT ISSUANCE</span>
        </header>
        <div class="receipt-body">
            <p class="receipt-callout">Receipt hash remains permanently unchanged even when reality later drifts.</p>
            <div class="receipt-hash-block">
                <label>Canonical Receipt SHA-256:</label>
                <code>{html.escape(receipt.receipt_hash)}</code>
            </div>
            <div class="receipt-meta-grid">
                <div><span>Predicates:</span> <strong>{receipt.predicates_evaluated_count} Verified</strong></div>
                <div><span>Current Reality:</span> <strong class="state-{receipt.current_reconciled_state.value.lower()}">{receipt.current_reconciled_state.value}</strong></div>
            </div>
        </div>
    </section>
    """

    # Assemble complete page
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>StillDone — Judge Exhibit &amp; Simulated Alexa+ Surface</title>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --border-color: #334155;
            --color-ready: #10b981;
            --color-drifted: #f59e0b;
            --color-partial: #38bdf8;
            --color-blocked: #ef4444;
            --accent-alexa: #06b6d4;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.5;
            padding: 1.5rem 1rem;
        }}
        .container {{ max-width: 1040px; margin: 0 auto; }}
        
        /* Banner Header */
        .header-banner {{
            background: linear-gradient(135deg, #0c4a6e 0%, #1e293b 100%);
            border: 1px solid #0284c7;
            border-radius: 8px;
            padding: 0.75rem 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
        }}
        .badge-simulated {{
            background-color: #0284c7;
            color: #ffffff;
            font-weight: 700;
            font-size: 0.85rem;
            padding: 0.25rem 0.65rem;
            border-radius: 4px;
            letter-spacing: 0.05em;
        }}
        .backend-label {{ font-size: 0.85rem; color: #bae6fd; font-weight: 600; }}

        /* Hero Intent & Voice Section */
        .hero-section {{
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1.25rem;
            margin-bottom: 1.5rem;
        }}
        .intent-block {{ margin-bottom: 1rem; }}
        .intent-label {{ font-size: 0.8rem; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }}
        .intent-text {{ font-size: 1.35rem; font-weight: 600; color: #ffffff; margin-top: 0.25rem; }}
        
        /* Voice Card */
        .voice-card {{
            background-color: #0f172a;
            border-left: 4px solid var(--accent-alexa);
            padding: 0.85rem 1rem;
            border-radius: 0 6px 6px 0;
        }}
        .voice-label {{ font-size: 0.75rem; text-transform: uppercase; color: var(--accent-alexa); font-weight: 700; margin-bottom: 0.25rem; }}
        .voice-speech {{ font-size: 1rem; color: #e2e8f0; font-style: italic; }}

        /* Status Visual Hierarchy */
        .status-hero-bar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background-color: var(--bg-secondary);
            border: 2px solid;
            border-radius: 8px;
            padding: 0.85rem 1.25rem;
            margin-bottom: 1.5rem;
        }}
        .status-hero-bar.ready {{ border-color: var(--color-ready); background-color: rgba(16, 185, 129, 0.08); }}
        .status-hero-bar.drifted {{ border-color: var(--color-drifted); background-color: rgba(245, 158, 11, 0.08); }}
        .status-title {{ font-size: 1.15rem; font-weight: 700; }}
        .status-pill {{
            padding: 0.35rem 0.85rem;
            border-radius: 9999px;
            font-weight: 800;
            font-size: 0.9rem;
            letter-spacing: 0.05em;
        }}
        .status-pill.ready {{ background-color: var(--color-ready); color: #042f2e; }}
        .status-pill.drifted {{ background-color: var(--color-drifted); color: #451a03; }}

        /* Layout Grid */
        .main-grid {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
        }}
        @media (max-width: 820px) {{
            .main-grid {{ grid-template-columns: 1fr; }}
        }}

        /* Timeline */
        .timeline-container {{ display: flex; flex-direction: column; gap: 0.85rem; }}
        .timeline-item {{
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            display: flex;
            gap: 0.85rem;
        }}
        .timeline-item.drifted-item {{ border-left: 4px solid var(--color-drifted); }}
        .timeline-marker {{
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background-color: #334155;
            color: #ffffff;
            font-weight: 700;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}
        .timeline-body {{ flex: 1; }}
        .timeline-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-bottom: 0.35rem;
        }}
        .timeline-title-row {{ display: flex; align-items: center; gap: 0.5rem; }}
        .task-tag {{ font-size: 0.75rem; color: #94a3b8; font-weight: 700; font-family: monospace; }}
        .step-title {{ font-size: 1rem; font-weight: 600; color: #ffffff; }}
        .timeline-desc {{ font-size: 0.88rem; color: #cbd5e1; margin-bottom: 0.5rem; }}
        .timeline-meta {{ font-size: 0.78rem; color: var(--text-muted); display: flex; gap: 1rem; margin-bottom: 0.5rem; }}
        
        /* Badges */
        .badge {{ font-size: 0.72rem; font-weight: 700; padding: 0.2rem 0.5rem; border-radius: 4px; }}
        .badge-verified {{ background-color: rgba(16, 185, 129, 0.2); color: #34d399; }}
        .badge-paused_approval {{ background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; }}
        .badge-approved {{ background-color: rgba(56, 189, 248, 0.2); color: #38bdf8; }}
        .badge-drift_detected {{ background-color: rgba(239, 68, 68, 0.2); color: #f87171; }}
        .badge-observed {{ background-color: rgba(148, 163, 184, 0.2); color: #cbd5e1; }}
        .badge-prov {{ background-color: #0f172a; color: #94a3b8; border: 1px solid #334155; }}
        .badge-ready {{ background-color: rgba(16, 185, 129, 0.2); color: #34d399; }}

        /* Expandable Evidence */
        .evidence-details {{ margin-top: 0.4rem; font-size: 0.82rem; }}
        .evidence-summary {{ color: #38bdf8; cursor: pointer; user-select: none; font-weight: 600; }}
        .evidence-content {{
            background-color: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 0.65rem;
            margin-top: 0.35rem;
        }}
        .evidence-table {{ width: 100%; border-collapse: collapse; }}
        .evidence-table th, .evidence-table td {{ padding: 0.25rem 0.5rem; text-align: left; border-bottom: 1px solid #1e293b; }}
        .evidence-table th {{ color: #94a3b8; width: 40%; font-weight: 500; }}
        .hash-trace {{ margin-top: 0.4rem; font-size: 0.75rem; word-break: break-all; color: #64748b; }}

        /* Side Cards */
        .sidebar {{ display: flex; flex-direction: column; gap: 1.25rem; }}
        .card {{
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1.15rem;
        }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }}
        .card-title {{ font-size: 0.95rem; font-weight: 700; color: #ffffff; }}
        .approval-desc {{ font-size: 0.85rem; color: #cbd5e1; margin-bottom: 0.4rem; }}
        .approval-proposal {{ font-size: 0.92rem; font-weight: 600; color: #f8fafc; margin-bottom: 0.75rem; }}
        .fingerprint-box {{ background-color: #0f172a; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.6rem; }}
        .fingerprint-label {{ font-size: 0.7rem; color: #64748b; display: block; }}
        .fingerprint-hash {{ font-size: 0.75rem; color: #38bdf8; }}
        .auth-notice {{ font-size: 0.75rem; color: #94a3b8; display: block; }}
        
        .receipt-callout {{ font-size: 0.8rem; color: #94a3b8; margin-bottom: 0.6rem; }}
        .receipt-hash-block {{ background-color: #0f172a; padding: 0.5rem; border-radius: 4px; margin-bottom: 0.75rem; }}
        .receipt-hash-block label {{ font-size: 0.7rem; color: #64748b; display: block; }}
        .receipt-hash-block code {{ font-size: 0.75rem; color: #34d399; word-break: break-all; }}
        .receipt-meta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.8rem; }}
        .state-drifted {{ color: var(--color-drifted); }}
        .state-ready {{ color: var(--color-ready); }}

        footer {{ margin-top: 2rem; text-align: center; font-size: 0.8rem; color: var(--text-muted); border-top: 1px solid #1e293b; padding-top: 1rem; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- P-15.02 Surface Disclosure Banner -->
        <aside class="header-banner" aria-label="Surface Disclosure">
            <span class="badge-simulated">SIMULATED ALEXA+ EXPERIENCE</span>
            <span class="backend-label">BACKEND: REAL STILLDONE DETERMINISTIC ENGINE</span>
        </aside>

        <!-- P-15.01 & P-15.03 Hero Intent and Voice Summary -->
        <section class="hero-section" aria-labelledby="intent-title">
            <div class="intent-block">
                <span class="intent-label">Canonical Intent (Mission {mission_id_short}):</span>
                <h1 id="intent-title" class="intent-text">&ldquo;{intent_escaped}&rdquo;</h1>
            </div>
            <div class="voice-card">
                <div class="voice-label">Alexa+ Spoken Response ({model.voice_summary.estimated_duration_sec}s):</div>
                <p class="voice-speech">&ldquo;{html.escape(model.voice_summary.spoken_phrase)}&rdquo;</p>
            </div>
        </section>

        <!-- P-15.05 Visual State Hierarchy Bar -->
        <section class="status-hero-bar {status_class}" aria-label="Current Mission State">
            <div class="status-title">Current System-of-Record Truth:</div>
            <div class="status-pill {status_class}">{model.current_state.value}</div>
        </section>

        <!-- Main Workspace -->
        <main class="main-grid">
            <!-- P-15.01 One-Screen Mission Timeline -->
            <section class="timeline-container" aria-label="Mission Timeline">
                {timeline_html}
            </section>

            <!-- Sidebar Cards: P-15.04 Approval Card & P-15.01 Compact Receipt -->
            <aside class="sidebar">
                {approval_html}
                {receipt_html}
            </aside>
        </main>

        <footer>
            <p>StillDone Hackathon Exhibit &bull; Zero Personal Spend ($0.00) &bull; Verified Provenance &bull; Generated: {model.generated_at_iso}</p>
        </footer>
    </div>
</body>
</html>"""
