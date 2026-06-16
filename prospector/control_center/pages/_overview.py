"""Overview — the cockpit.

Purpose: one-glance health + activity. The "is the engine alive and producing?" screen.

Refresh: st.fragment(run_every="10s") on the KPI cards + active runs panel only.
Static elements (alarms, moat status) do NOT auto-refresh — they are expensive calls
but stable enough.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import streamlit as st

from prospector.control_center import readers
from prospector.control_center.components.gate_badge import st_severity_badge


def render():
    # Empty state: no dossiers yet
    if not readers.catalogue_index():
        st.info("No dossiers yet — launch your first vet run.")
        st.page_link("pages/_launch.py", label="🚀 Go to Launch page", icon="🚀")
        return

    _render_header()
    _render_quick_actions()
    _render_kpi_cards()
    _render_alpha_trend()
    _render_moat_pills()
...
# ---------------------------------------------------------------------------
# Alpha Trend
# ---------------------------------------------------------------------------

def _render_alpha_trend():
    """Render Generative Alpha per-axis trend sparklines."""
    cfg = readers.load_config_typed()
    if not cfg: return
    
    try:
        from prospector.store import Store
        store = Store(cfg)
        from prospector.diagnostics import calculate_generative_alpha
        alpha = calculate_generative_alpha(store, window=20)
        avgs = alpha.get("axis_averages", {})
    except Exception:
        return

    if not avgs: return

    st.html('<div style="margin-bottom:0.5rem;font-weight:700;color:var(--cc-text);font-size:0.95rem">💎 Generative Alpha (Axis Breakdown)</div>')
    
    cols = st.columns(len(avgs))
    for i, (axis, val) in enumerate(avgs.items()):
        with cols[i]:
            st.metric(axis.replace("_", " ").title(), f"{val:.1f}/5.0")
    _render_alarm_cards()
    _render_recent_runs()


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

def _render_header():
    """Custom header row: title + engine status + last run time."""
    jobs = readers.load_jobs()
    running = any(j.get("status") == "running" for j in jobs)
    last_ts = max((j.get("start_ts", 0) for j in jobs), default=0) if jobs else 0

    dot_class = "cc-header-status-dot--live" if running else "cc-header-status-dot--idle"
    status_text = "Engine running" if running else "Engine idle"
    last_text = ""
    if last_ts:
        ago_s = int(time.time() - last_ts)
        if ago_s < 60:
            last_text = f"Last run: {ago_s}s ago"
        elif ago_s < 3600:
            last_text = f"Last run: {ago_s // 60}m ago"
        else:
            last_text = f"Last run: {ago_s // 3600}h ago"

    st.html(f"""
    <div class="cc-header">
        <div class="cc-header-title">🛰 PROSPECTOR</div>
        <div class="cc-header-status">
            <span><span class="cc-header-status-dot {dot_class}"></span> {status_text}</span>
            <span class="cc-muted">{last_text}</span>
        </div>
    </div>
    """)


# ---------------------------------------------------------------------------
# Quick actions
# ---------------------------------------------------------------------------

def _render_quick_actions():
    """Row of shortcut buttons for common actions."""
    st.html('<div class="cc-actions">')
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("🚀 New Run", use_container_width=True,
                     key="qa_new_run", help="Go to Launch page"):
            st.session_state["active_page"] = "launcher"
            st.rerun()
    with c2:
        if st.button("📋 Browse Catalogue", use_container_width=True,
                     key="qa_catalogue", help="Browse all dossiers"):
            st.session_state["active_page"] = "catalogue"
            st.rerun()
    with c3:
        if st.button("🔬 Diagnostics", use_container_width=True,
                     key="qa_diag", help="View calibration diagnostics"):
            st.session_state["active_page"] = "diagnostics"
            st.rerun()
    st.html('</div>')


# ---------------------------------------------------------------------------
# KPI cards — auto-refreshes every 10 seconds
# ---------------------------------------------------------------------------

@st.fragment(run_every="10s")
def _render_kpi_cards():
    """Render a row of KPI metric cards using st.html with cc-kpi styling."""
    cfg = readers.load_config_typed()
    stats = readers.catalogue_stats()
    audit = readers.load_audit_log()
    spend = readers.today_spend(audit)
    golden = readers.latest_golden()
    pending = readers.load_pending_signals()
    daily_cap = 50.0
    if cfg and hasattr(cfg, "spend_guard"):
        daily_cap = cfg.spend_guard.daily_cap_usd
    elif cfg and hasattr(cfg, "spend"):
        daily_cap = cfg.spend.daily_cap_usd

    n_pass = stats.get("n_pass", 0)
    n_kill = stats.get("n_kill", 0)
    n_defer = stats.get("n_defer", 0)
    ruled = n_pass + n_kill
    pass_pct = (n_pass / ruled * 100) if ruled > 0 else 0.0
    kill_pct = (n_kill / ruled * 100) if ruled > 0 else 0.0
    cap_pct = min(100, round(spend["total_usd"] / daily_cap * 100, 1)) if daily_cap else 0

    # Golden discrimination
    golden_html = ""
    disc = golden.get("discrimination_score") if golden else None
    if disc is not None:
        ok = golden.get("passed", False)
        delta_class = "cc-kpi-delta--up" if ok else "cc-kpi-delta--down"
        golden_html = f"""
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value">{disc:.3f}</div>
            <div class="cc-kpi-label">🎯 Golden Disc.</div>
            <div class="cc-kpi-delta {delta_class}">{'✅ PASS' if ok else '❌ FAIL'}</div>
        </div>"""
    else:
        golden_html = """
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value">—</div>
            <div class="cc-kpi-label">🎯 Golden Disc.</div>
            <div class="cc-kpi-sub">no golden runs</div>
        </div>"""

    # Generative Alpha (Part 16 principal upgrade)
    from prospector.diagnostics import calculate_generative_alpha
    alpha = calculate_generative_alpha(store)
    alpha_val = alpha.get("rolling_avg", 0.0)
    alpha_color = "var(--cc-success)" if alpha_val >= 3.5 else "var(--cc-warning)" if alpha_val >= 3.0 else "var(--cc-danger)"
    alpha_html = f"""
    <div class="cc-card cc-kpi">
        <div class="cc-kpi-value" style="color:{alpha_color}">{alpha_val:.2f}</div>
        <div class="cc-kpi-label">💎 Generative Alpha</div>
        <div class="cc-kpi-sub">rolling avg score</div>
    </div>"""

    kpi_html = f"""
    <style>
    .cc-kpi-row {{
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 12px;
        margin-bottom: 1rem;
    }}
    @media (max-width: 1400px) {{
        .cc-kpi-row {{ grid-template-columns: repeat(4, 1fr); }}
    }}
    @media (max-width: 900px) {{
        .cc-kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    </style>
    <div class="cc-kpi-row">
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value" style="color:var(--cc-success)">{n_pass}</div>
            <div class="cc-kpi-label">✅ PASS</div>
            <div class="cc-kpi-sub">{pass_pct:.1f}% of ruled</div>
        </div>
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value" style="color:var(--cc-danger)">{n_kill}</div>
            <div class="cc-kpi-label">🛑 KILL</div>
            <div class="cc-kpi-sub">{kill_pct:.1f}% of ruled</div>
        </div>
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value" style="color:var(--cc-warning)">{n_defer}</div>
            <div class="cc-kpi-label">⏸ DEFER</div>
            <div class="cc-kpi-sub">pending retry</div>
        </div>
        {alpha_html}
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value">${spend['total_usd']:.2f}</div>
            <div class="cc-kpi-label">💰 Spend</div>
            <div class="cc-kpi-sub">{cap_pct}% of ${daily_cap:.0f} cap</div>
            <div style="margin-top:8px;height:4px;background:var(--cc-border);border-radius:2px;overflow:hidden">
                <div style="height:100%;width:{min(100, cap_pct)}%;background:var(--cc-primary);border-radius:2px"></div>
            </div>
        </div>
        <div class="cc-card cc-kpi">
            <div class="cc-kpi-value">{len(pending)}</div>
            <div class="cc-kpi-label">⏳ Pending</div>
            <div class="cc-kpi-sub">signals in queue</div>
        </div>
        {golden_html}
    </div>
    <div style="text-align:right;font-size:0.7rem;color:var(--cc-text-muted);margin-bottom:1rem">
        KPI cards auto-refresh every 10s
    </div>
    """
    st.html(kpi_html)


# ---------------------------------------------------------------------------
# Moat status — operator pills
# ---------------------------------------------------------------------------

def _render_moat_pills():
    """Render moat operator status as colored pills instead of a table."""
    health = readers.load_provider_health()
    now = datetime.now(timezone.utc).timestamp()

    st.html('<div style="margin-bottom:1rem">')

    moat_down = readers.moat_down(health)
    if moat_down:
        st.error("🚨 MOAT DOWN — both Claude and Gemini are exhausted. "
                 "Runs will DEFER at the moat. Re-vet buttons are disabled.")
    elif not health:
        st.info("No provider health data yet — run the engine first.")
        st.html('</div>')
        return
    else:
        # Build pill HTML
        pills = []
        for op, state in health.items():
            if not isinstance(state, dict):
                continue
            du = state.get("dead_until", 0)
            remaining = max(0, du - now) if du else 0
            if remaining > 0:
                pill_class = "cc-pill--dead"
                label = f"🔴 {op.upper()} DEAD"
                extra = f" ({round(remaining)}s)"
            elif du > 0:
                pill_class = "cc-pill--recovering"
                label = f"🟡 {op.upper()} RECOVERING"
                extra = ""
            else:
                pill_class = "cc-pill--healthy"
                label = f"🟢 {op.upper()} HEALTHY"
                extra = ""
            pills.append(
                f'<span class="cc-pill {pill_class}">'
                f'<span class="cc-pill-dot"></span>{label}{extra}</span>'
            )

        st.html(f"""
        <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;
                    padding:0.75rem 0">
            <span style="font-weight:700;color:var(--cc-text);font-size:0.95rem">⚡ MOAT</span>
            {''.join(pills)}
        </div>
        """)

    st.html('</div>')


# ---------------------------------------------------------------------------
# Recent runs
# ---------------------------------------------------------------------------

def _render_recent_runs():
    """Styled recent-runs table with status pills."""
    jobs = readers.load_jobs()
    if not jobs:
        st.info("No runs recorded yet. Launch your first run from the **Launch** page.")
        return

    st.html('<div style="margin-bottom:0.5rem;font-weight:700;color:var(--cc-text);font-size:0.95rem">📋 Recent Runs</div>')

    recent = sorted(jobs, key=lambda j: j.get("start_ts", 0), reverse=True)[:10]
    rows = []
    for j in recent:
        status = j.get("status", "?")
        label = {
            "running": "🟡 Running",
            "succeeded": "✅ Succeeded",
            "failed": "❌ Failed",
            "cancelled": "⚠️ Cancelled",
            "deferred": "⏸ Deferred",
            "queued": "⏳ Queued",
            "unknown": "❓ Unknown",
        }.get(status, status)
        start = j.get("start_ts", 0)
        elapsed = (time.time() - start) if (status == "running" and start) else j.get("elapsed_s", 0)
        rows.append({
            "job_id": j.get("job_id", "")[:8],
            "status": label,
            "argv": " ".join(j.get("argv", []))[:70],
            "elapsed_s": round(elapsed) if elapsed else "—",
            "cost_usd": f"${j['cost_usd']:.4f}" if isinstance(j.get("cost_usd"), (int, float)) else "—",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True,
                 column_config={
                     "job_id": st.column_config.TextColumn("Job ID", width="small"),
                     "status": st.column_config.TextColumn("Status", width="small"),
                     "argv": st.column_config.TextColumn("Command", width="large"),
                     "elapsed_s": st.column_config.TextColumn("Elapsed", width="small"),
                     "cost_usd": st.column_config.TextColumn("Cost", width="small"),
                 },
                 height=300)


# ---------------------------------------------------------------------------
# Alarm → catalogue navigation helper
# ---------------------------------------------------------------------------

def _alarm_view_button(alarm: dict):
    """Render a button that navigates to the catalogue pre-filtered for this alarm."""
    code = alarm.get("code", "")
    lane = alarm.get("lane")

    if code == "zero_yield":
        label = "🔍 View KILLs"
        preset_decision = "kill"
    elif code == "dead_gate":
        label = "🔍 View lane"
        preset_decision = "all"
    elif code == "gate_dominance":
        label = "🔍 View KILLs"
        preset_decision = "kill"
    else:
        label = "🔍 View"
        preset_decision = "all"

    if st.button(label, key=f"alarm_view_{code}_{lane or 'all'}",
                 use_container_width=True):
        st.session_state["catalogue_preset_lane"] = lane or ""
        st.session_state["catalogue_preset_decision"] = preset_decision
        st.session_state["active_page"] = "catalogue"
        st.rerun()


# ---------------------------------------------------------------------------
# Alarms — severity-coded cards
# ---------------------------------------------------------------------------

def _render_alarm_cards():
    """Render calibration alarms as severity-colored cards."""
    cfg = readers.load_config_typed()
    if cfg is None:
        st.warning("Could not load engine config — alarms unavailable.")
        return

    try:
        from prospector.store import Store
        store = Store(cfg)
        from prospector.diagnostics import diagnostics_data
        data = diagnostics_data(store, cfg)
        alarms = data.get("alarms", [])
    except Exception as e:
        st.warning(f"Could not load diagnostics: {e}")
        return

    if not alarms:
        st.success("✓ No calibration pathologies detected.")
        return

    st.html('<div style="margin-bottom:0.5rem;font-weight:700;color:var(--cc-text);font-size:0.95rem">🚨 Active Calibration Alarms</div>')

    show_all = len(alarms) <= 4
    visible = alarms if show_all else alarms[:4]

    for a in visible:
        level = a.get("level", "warn")
        severity_class = "cc-alarm--critical" if level == "alarm" else "cc-alarm--warn"
        code = a.get("code", "?").upper()
        lane = a.get("lane")
        lane_tag = f'<span class="cc-alarm-lane">[{lane}]</span>' if lane else ""
        message = a.get("message", "")
        # Truncate long messages
        if len(message) > 140:
            message = message[:137] + "…"

        st.html(f"""
        <div class="cc-alarm {severity_class}">
            <span class="cc-alarm-code">{code}</span>
            <span class="cc-alarm-msg">{message} {lane_tag}</span>
        </div>
        """)

        # View button below each alarm card
        c1, c2, c3 = st.columns([4, 1, 4])
        with c2:
            _alarm_view_button(a)

    if not show_all:
        with st.expander(f"Show all {len(alarms)} alarms"):
            for a in alarms[4:]:
                level = a.get("level", "warn")
                severity_class = "cc-alarm--critical" if level == "alarm" else "cc-alarm--warn"
                code = a.get("code", "?").upper()
                lane = a.get("lane")
                lane_tag = f'<span class="cc-alarm-lane">[{lane}]</span>' if lane else ""
                message = a.get("message", "")
                if len(message) > 140:
                    message = message[:137] + "…"

                st.html(f"""
                <div class="cc-alarm {severity_class}">
                    <span class="cc-alarm-code">{code}</span>
                    <span class="cc-alarm-msg">{message} {lane_tag}</span>
                </div>
                """)
                c1, c2, c3 = st.columns([4, 1, 4])
                with c2:
                    _alarm_view_button(a)

    st.caption(f"{len(alarms)} alarm(s) — see **Diagnostics** page for details.")
