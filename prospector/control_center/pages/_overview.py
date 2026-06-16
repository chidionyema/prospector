"""Overview — the cockpit.

Purpose: one-glance health + activity. The "is the engine alive and producing?" screen.

Refresh: st.fragment(run_every="10s") on the KPI strip + active runs panel only.
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
    st.title("🛰 Prospector Control Center")
    
    # Empty state: no dossiers yet
    if not readers.catalogue_index():
        st.info("No dossiers yet — launch your first vet run.")
        # Link to Launch page
        st.page_link("pages/_launch.py", label="🚀 Go to Launch page", icon="🚀")
        return
    
    _render_kpi_strip()
    st.divider()
    _render_moat_status()
    st.divider()
    _render_recent_runs()
    st.divider()
    _render_active_alarms()


# ---------------------------------------------------------------------------
# KPI strip — auto-refreshes every 10 seconds
# ---------------------------------------------------------------------------

@st.fragment(run_every="10s")
def _render_kpi_strip():
    """The live KPI strip. Refreshed every 10s."""
    cfg = readers.load_config_typed()
    stats = readers.catalogue_stats()
    audit = readers.load_audit_log()
    spend = readers.today_spend(audit)
    golden = readers.latest_golden()
    pending = readers.load_pending_signals()
    daily_cap = 50.0  # default; real value from config
    if cfg and hasattr(cfg, "spend_guard"):
        daily_cap = cfg.spend_guard.daily_cap_usd
    elif cfg and hasattr(cfg, "spend"):
        daily_cap = cfg.spend.daily_cap_usd

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("✅ PASS", stats.get("n_pass", 0))
        st.metric("🛑 KILL", stats.get("n_kill", 0))
    with col2:
        st.metric("⏸ DEFER", stats.get("n_defer", 0))
        # Provisional metric removed per spec
    with col3:
        disc = golden.get("discrimination_score") if golden else None
        ok = golden.get("passed", False) if golden else False
        if disc is not None:
            st.metric("🎯 Golden discrimination",
                     f"{disc:.3f}",
                     delta="✅ PASS" if ok else "❌ FAIL")
        else:
            st.metric("🎯 Golden discrimination", "— no runs")
    with col4:
        cap_pct = min(100, round(spend["total_usd"] / daily_cap * 100, 1)) if daily_cap else 0
        st.metric("💰 Today spend",
                 f"${spend['total_usd']:.2f}",
                 delta=f"{cap_pct}% of ${daily_cap:.0f} cap")
        st.progress(min(1.0, spend["total_usd"] / daily_cap),
                   caption=f"{cap_pct}% of ${daily_cap:.0f} daily cap")
        st.metric("⏳ Pending signals", len(pending))

    st.caption("KPI strip auto-refreshes every 10s")


# ---------------------------------------------------------------------------
# Moat status
# ---------------------------------------------------------------------------

def _render_moat_status():
    health = readers.load_provider_health()
    now = datetime.now(timezone.utc).timestamp()

    st.subheader("⚡ Moat Status")
    moat_down = readers.moat_down(health)
    if moat_down:
        st.error("🚨 MOAT DOWN — both Claude and Gemini are exhausted. "
                 "Runs will DEFER at the moat. Re-vet buttons are disabled.")
    else:
        st.success("✅ Moat is healthy — at least one moat operator is available.")

    # Per-operator state table
    if health:
        rows = []
        for op, state in health.items():
            if not isinstance(state, dict):
                continue
            du = state.get("dead_until", 0)
            remaining = max(0, du - now) if du else 0
            state_label = ("🔴 DEAD" if remaining > 0 else
                           "🟡 RECOVERING" if du > 0 else "🟢 HEALTHY")
            rows.append({"operator": op, "state": state_label,
                         "dead_for_s": round(state.get("dead_for_s", 0)),
                         "remaining_s": round(remaining)})
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No provider health data yet — run the engine first.")


# ---------------------------------------------------------------------------
# Recent runs
# ---------------------------------------------------------------------------

def _render_recent_runs():
    st.subheader("📋 Recent Runs")
    jobs = readers.load_jobs()
    if not jobs:
        st.info("No runs recorded yet. Launch your first run from the **Launch** page.")
        return

    # Show last 10, newest first
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
            "argv": " ".join(j.get("argv", []))[:60],
            "elapsed_s": round(elapsed) if elapsed else "—",
            "cost_usd": j.get("cost_usd", "—"),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True,
                 column_config={
                     "job_id": st.column_config.TextColumn("job", width="small"),
                     "status": st.column_config.TextColumn("status", width="small"),
                     "argv": st.column_config.TextColumn("command"),
                     "elapsed_s": st.column_config.TextColumn("elapsed (s)", width="small"),
                     "cost_usd": st.column_config.TextColumn("cost", width="small"),
                 })


# ---------------------------------------------------------------------------
# Active alarms
# ---------------------------------------------------------------------------

def _render_active_alarms():
    st.subheader("🚨 Active Calibration Alarms")
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

    for a in alarms:
        col1, col2 = st.columns([1, 4])
        with col1:
            st_severity_badge(a.get("level", "warn"))
        with col2:
            lane = a.get("lane")
            lane_tag = f" **[{lane}]**" if lane else ""
            st.markdown(f"{a.get('message', '')}{lane_tag}")
        st.divider()

    st.caption(f"{len(alarms)} alarm(s) — see **Diagnostics** page for details and remediation.")
