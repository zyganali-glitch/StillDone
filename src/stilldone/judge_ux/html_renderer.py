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

from stilldone.judge_ux.models import (
    JudgeExhibitViewModel,
)


def render_judge_exhibit_html(model: JudgeExhibitViewModel) -> str:
    """Render a fully self-contained, accessible, responsive HTML document."""
    intent_escaped = html.escape(model.user_intent)
    mission_id_short = html.escape(model.mission_id[:8])
    status_class = model.current_state.value.lower()

    # Timeline cards HTML
    timeline_items_html: list[str] = []
    for step in model.timeline_steps:
        s_val = html.escape(step.state.value)
        s_cls = step.state.value.lower()
        step_state_badge = f'<span class="badge badge-{s_cls}">{s_val}</span>'
        prov_badge = f'<span class="badge badge-prov">{html.escape(step.provenance)}</span>'

        # Expandable evidence details
        props_rows = "".join(
            f"<tr><th>{html.escape(str(k))}</th><td><code>{html.escape(str(v))}</code></td></tr>"
            for k, v in step.evidence_properties.items()
        )
        hash_p = ""
        if step.cryptographic_hash:
            h_esc = html.escape(step.cryptographic_hash)
            hash_p = (
                f'<p class="hash-trace"><strong>Receipt Hash:</strong> <code>{h_esc}</code></p>'
            )

        evidence_html = f"""
        <details class="evidence-details">
            <summary class="evidence-summary">
                Inspect Evidence &amp; Read-back Facts ({len(step.evidence_properties)} properties)
            </summary>
            <div class="evidence-content">
                <table class="evidence-table">
                    <tbody>{props_rows}</tbody>
                </table>
                {hash_p}
            </div>
        </details>
        """

        drift_cls = "drifted-item" if step.is_drifted else ""
        step_aria = f"Step {step.step_number}: {html.escape(step.title)}"
        rb_text = html.escape(step.readback_status)

        timeline_items_html.append(f"""
        <article class="timeline-item {drift_cls}" aria-label="{step_aria}">
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
                    <span>Read-back: <strong>{rb_text}</strong></span>
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
        app_status = "APPROVED" if card.is_approved else "PENDING"
        act_esc = html.escape(card.action_type)
        sys_esc = html.escape(card.target_system)
        desc_esc = html.escape(card.proposed_change_description)
        fp_esc = html.escape(card.fingerprint[:32])

        approval_html = f"""
        <section class="card approval-card" aria-labelledby="approval-title">
            <header class="card-header">
                <h3 id="approval-title" class="card-title">Human Authorization Boundary</h3>
                <span class="badge badge-approved">{app_status}</span>
            </header>
            <div class="approval-body">
                <p class="approval-desc">
                    <strong>Target Action:</strong>
                    <code>{act_esc}</code> on <strong>{sys_esc}</strong>
                </p>
                <p class="approval-proposal">{desc_esc}</p>
                <div class="fingerprint-box">
                    <span class="fingerprint-label">
                        Tamper-Evident Binding Hash (Derived from Fixture Action Outcome):
                    </span>
                    <code class="fingerprint-hash">{fp_esc}...</code>
                </div>
                <div class="approval-footer">
                    <span class="auth-notice">
                        Single-Use Grant bound to target identity, mission ID, and
                        normalized payload parameters. Replays strictly rejected.
                    </span>
                </div>
            </div>
        </section>
        """

    # Compact receipt HTML
    receipt = model.compact_receipt
    r_issuance = html.escape(receipt.state_at_issuance)
    r_hash = html.escape(receipt.receipt_hash)
    r_curr_cls = receipt.current_reconciled_state.value.lower()
    r_curr_val = receipt.current_reconciled_state.value

    receipt_html = f"""
    <section class="card receipt-card" aria-labelledby="receipt-title">
        <header class="card-header">
            <h3 id="receipt-title" class="card-title">Immutable Historical Receipt</h3>
            <span class="badge badge-ready">{r_issuance} AT ISSUANCE</span>
        </header>
        <div class="receipt-body">
            <p class="receipt-callout">
                Receipt hash remains permanently unchanged even when reality later drifts.
            </p>
            <div class="receipt-hash-block">
                <label>Canonical Receipt SHA-256:</label>
                <code>{r_hash}</code>
            </div>
            <div class="receipt-meta-grid">
                <div>
                    <span>Predicates:</span>
                    <strong>{receipt.predicates_evaluated_count} Verified</strong>
                </div>
                <div>
                    <span>Current Reality:</span>
                    <strong class="state-{r_curr_cls}">{r_curr_val}</strong>
                </div>
            </div>
        </div>
    </section>
    """

    # Drift explanation HTML
    drift_expl_html = """
    <section class="card explanation-card" aria-labelledby="drift-title">
        <header class="card-header">
            <h3 id="drift-title" class="card-title">Drift Law &amp; State Invariant</h3>
            <span class="badge badge-drift_detected">RECONCILED</span>
        </header>
        <div class="card-body">
            <p class="explanation-lead">
                <strong>Why is current truth DRIFTED while the receipt was READY?</strong>
            </p>
            <p class="explanation-text">
                In Step 6, all required predicates matched (7:30 departure, backpacks task
                needsAction, mild weather). The mission was deterministically promoted
                to <code>READY</code> and issued an immutable receipt hash.
            </p>
            <p class="explanation-text" style="margin-top: 0.5rem;">
                In Step 7, an external change moved the calendar departure to 08:00 AM.
                StillDone detected the contradiction during independent read-back and
                downgraded the mission to <code>DRIFTED</code>.
            </p>
            <div class="receipt-callout" style="margin-top: 0.6rem;">
                <strong>Core Invariant:</strong> Historical receipts remain permanently unchanged
                as audit history, but current system-of-record state reflects live observed truth.
            </div>
        </div>
    </section>
    """

    # Provenance breakdown HTML
    provenance_html = """
    <section class="card provenance-card" aria-labelledby="prov-title">
        <header class="card-header">
            <h3 id="prov-title" class="card-title">Evidence Provenance Breakdown</h3>
            <span class="badge badge-prov">TRANSPARENT</span>
        </header>
        <div class="card-body">
            <div class="prov-item">
                <span class="badge badge-prov" style="display:inline-block; margin-bottom:0.2rem;">
                    RECORDED_LIVE
                </span>
                <p class="explanation-text">
                    Real AWS Bedrock Nova Micro reasoning (P-01/P-07), real AgentCore Streamable
                    HTTP microVM (P-05), and Google Calendar/Tasks OAuth mutations were exercised
                    in bounded live sessions and preserved in <code>docs/</code>.
                </p>
            </div>
            <div class="prov-item" style="margin-top: 0.6rem;">
                <span class="badge badge-prov" style="display:inline-block; margin-bottom:0.2rem;">
                    FIXTURE / SIMULATION
                </span>
                <p class="explanation-text">
                    This interactive exhibit replays the canonical mission in deterministic
                    fixture mode. Zero external credentials, zero AWS API charges, and strictly
                    $0.00 personal spend.
                </p>
            </div>
            <div class="prov-item" style="margin-top: 0.6rem;">
                <span class="badge badge-prov" style="display:inline-block; margin-bottom:0.2rem;">
                    STATIC EXHIBIT
                </span>
                <p class="explanation-text">
                    Compatible with Cloudflare Pages Free (<code>*.pages.dev</code>).
                    No public unmetered execution endpoints.
                </p>
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
            --text-muted: #94a3b8;
            --border-color: #334155;
            --color-ready: #10b981;
            --color-drifted: #f59e0b;
            --color-partial: #38bdf8;
            --color-blocked: #ef4444;
            --accent-alexa: #06b6d4;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                Roboto, Helvetica, Arial, sans-serif;
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
        .intent-label {{
            font-size: 0.8rem;
            text-transform: uppercase;
            color: var(--text-muted);
            font-weight: 700;
        }}
        .intent-text {{
            font-size: 1.35rem;
            font-weight: 600;
            color: #ffffff;
            margin-top: 0.25rem;
        }}

        /* Voice Card */
        .voice-card {{
            background-color: #0f172a;
            border-left: 4px solid var(--accent-alexa);
            padding: 0.85rem 1rem;
            border-radius: 0 6px 6px 0;
        }}
        .voice-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            color: var(--accent-alexa);
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}
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
        .status-hero-bar.ready {{
            border-color: var(--color-ready);
            background-color: rgba(16, 185, 129, 0.08);
        }}
        .status-hero-bar.drifted {{
            border-color: var(--color-drifted);
            background-color: rgba(245, 158, 11, 0.08);
        }}
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
        .task-tag {{
            font-size: 0.75rem;
            color: #94a3b8;
            font-weight: 700;
            font-family: monospace;
        }}
        .step-title {{ font-size: 1rem; font-weight: 600; color: #ffffff; }}
        .timeline-desc {{ font-size: 0.88rem; color: #cbd5e1; margin-bottom: 0.5rem; }}
        .timeline-meta {{
            font-size: 0.78rem;
            color: var(--text-muted);
            display: flex;
            gap: 1rem;
            margin-bottom: 0.5rem;
        }}

        /* Badges */
        .badge {{
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }}
        .badge-verified {{ background-color: rgba(16, 185, 129, 0.2); color: #34d399; }}
        .badge-paused_approval {{ background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; }}
        .badge-approved {{ background-color: rgba(56, 189, 248, 0.2); color: #38bdf8; }}
        .badge-drift_detected {{ background-color: rgba(239, 68, 68, 0.2); color: #f87171; }}
        .badge-observed {{ background-color: rgba(148, 163, 184, 0.2); color: #cbd5e1; }}
        .badge-prov {{ background-color: #0f172a; color: #94a3b8; border: 1px solid #334155; }}
        .badge-ready {{ background-color: rgba(16, 185, 129, 0.2); color: #34d399; }}

        /* Expandable Evidence */
        .evidence-details {{ margin-top: 0.4rem; font-size: 0.82rem; }}
        .evidence-summary {{
            color: #38bdf8;
            cursor: pointer;
            user-select: none;
            font-weight: 600;
        }}
        .evidence-content {{
            background-color: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 0.65rem;
            margin-top: 0.35rem;
        }}
        .evidence-table {{ width: 100%; border-collapse: collapse; }}
        .evidence-table th, .evidence-table td {{
            padding: 0.25rem 0.5rem;
            text-align: left;
            border-bottom: 1px solid #1e293b;
        }}
        .evidence-table th {{ color: #94a3b8; width: 40%; font-weight: 500; }}
        .hash-trace {{
            margin-top: 0.4rem;
            font-size: 0.75rem;
            word-break: break-all;
            color: #64748b;
        }}

        /* Side Cards */
        .sidebar {{ display: flex; flex-direction: column; gap: 1.25rem; }}
        .card {{
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1.15rem;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
        }}
        .card-title {{ font-size: 0.95rem; font-weight: 700; color: #ffffff; }}
        .approval-desc {{ font-size: 0.85rem; color: #cbd5e1; margin-bottom: 0.4rem; }}
        .approval-proposal {{
            font-size: 0.92rem;
            font-weight: 600;
            color: #f8fafc;
            margin-bottom: 0.75rem;
        }}
        .fingerprint-box {{
            background-color: #0f172a;
            padding: 0.5rem;
            border-radius: 4px;
            margin-bottom: 0.6rem;
        }}
        .fingerprint-label {{ font-size: 0.7rem; color: #64748b; display: block; }}
        .fingerprint-hash {{ font-size: 0.75rem; color: #38bdf8; }}
        .auth-notice {{ font-size: 0.75rem; color: #94a3b8; display: block; }}

        .receipt-callout {{ font-size: 0.8rem; color: #94a3b8; margin-bottom: 0.6rem; }}
        .receipt-hash-block {{
            background-color: #0f172a;
            padding: 0.5rem;
            border-radius: 4px;
            margin-bottom: 0.75rem;
        }}
        .receipt-hash-block label {{ font-size: 0.7rem; color: #64748b; display: block; }}
        .receipt-hash-block code {{ font-size: 0.75rem; color: #34d399; word-break: break-all; }}
        .receipt-meta-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.5rem;
            font-size: 0.8rem;
        }}
        .state-drifted {{ color: var(--color-drifted); }}
        .state-ready {{ color: var(--color-ready); }}

        .explanation-lead {{ font-size: 0.85rem; color: #f8fafc; margin-bottom: 0.35rem; }}
        .explanation-text {{ font-size: 0.82rem; color: #cbd5e1; line-height: 1.45; }}
        .prov-item {{ font-size: 0.8rem; color: #cbd5e1; }}

        footer {{
            margin-top: 2rem;
            text-align: center;
            font-size: 0.8rem;
            color: var(--text-muted);
            border-top: 1px solid #1e293b;
            padding-top: 1rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- P-15.02 Surface Disclosure Banner -->
        <aside class="header-banner" aria-label="Surface Disclosure">
            <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
                <span class="badge-simulated">SIMULATED ALEXA+ EXPERIENCE</span>
                <span class="badge badge-prov"
                      style="background:#0369a1; color:#ffffff; font-weight:700;
                             padding:0.25rem 0.65rem; border-radius:4px; font-size:0.85rem;">
                    FIXTURE PLAYBACK
                </span>
            </div>
            <span class="backend-label">BACKEND: REAL STILLDONE DETERMINISTIC ENGINE</span>
        </aside>

        <!-- Evaluation Provenance Notice -->
        <div class="fixture-notice"
             style="background:var(--bg-secondary); border-left:4px solid var(--accent-alexa);
                    padding:0.75rem 1rem; margin-bottom:1.25rem; border-radius:0 6px 6px 0;
                    font-size:0.85rem; color:#cbd5e1;">
            <strong>Evaluation Provenance Disclosure:</strong> This interactive exhibit displays
            deterministic <strong>FIXTURE / SIMULATION</strong> playback of the canonical killer
            mission. It executes offline with zero live Google Calendar/Tasks mutations, zero AWS
            Bedrock/AgentCore API calls, and zero credentials required. Authentic historical live
            integration executions are preserved separately in the <code>docs/</code> ledger
            (marked <code>RECORDED_LIVE</code>).
        </div>

        <!-- P-15.01 & P-15.03 Hero Intent and Voice Summary -->
        <section class="hero-section" aria-labelledby="intent-title">
            <div class="intent-block">
                <span class="intent-label">Canonical Intent (Mission {mission_id_short}):</span>
                <h1 id="intent-title" class="intent-text">&ldquo;{intent_escaped}&rdquo;</h1>
            </div>
            <div class="voice-card">
                <div class="voice-label">
                    Alexa+ Spoken Response ({model.voice_summary.estimated_duration_sec}s):
                </div>
                <p class="voice-speech">
                    &ldquo;{html.escape(model.voice_summary.spoken_phrase)}&rdquo;
                </p>
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

            <!-- Sidebar Cards: P-15.04 Approval Card, P-15.01 Compact Receipt -->
            <!-- Drift Explanation & Evidence Provenance Breakdown -->
            <aside class="sidebar">
                {approval_html}
                {receipt_html}
                {drift_expl_html}
                {provenance_html}
            </aside>
        </main>

        <footer>
            <p>
                StillDone Hackathon Exhibit &bull; Zero Personal Spend ($0.00) &bull;
                Verified Provenance &bull; Generated: {model.generated_at_iso}
            </p>
        </footer>
    </div>
</body>
</html>"""
