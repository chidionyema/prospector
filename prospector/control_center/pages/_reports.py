"""Reports & Economics — demand loop (read-only, cannot apply changes)."""
from __future__ import annotations

import streamlit as st

from .. import readers
from .. import runner as _runner_mod  # for future use


def render():
    st.title("📊 Reports & Economics")
    st.info("ℹ️ This page is **read-only**. Demand metrics inform what to offer — "
           "they never influence what may ship. To change parameters, go to **Parameters**.")

    # ── Load all data ─────────────────────────────────────────────────────
    cfg = readers.load_config_typed()
    audit = readers.load_audit_log()
    from prospector.report import costs_data as _costs_data
    costs = _costs_data("store/prospector.jsonl")

    # ── Economics ──────────────────────────────────────────────────────────
    st.subheader("💰 Economics")
    if costs:
        total = costs.get("total_spend_usd", 0)
        calls = costs.get("total_calls", 0)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Lifetime spend", f"${total:.4f}")
        with col2:
            st.metric("Total API calls", calls)
        with col3:
            errs = costs.get("errors_excluded", 0)
            st.metric("Errors excluded", errs)

        providers = costs.get("providers", [])
        if providers:
            st.markdown("**Spend by provider:**")
            rows = []
            for p in providers:
                rows.append({
                    "provider": p.get("name", "?"),
                    "cost_usd": f"${p.get('cost_usd', 0):.4f}",
                    "calls": p.get("calls", 0),
                    "input": p.get("input", 0),
                    "output": p.get("output", 0),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

        slowest = costs.get("slowest_ops", [])
        if slowest:
            st.markdown("**Slowest operations:**")
            st.dataframe(slowest, use_container_width=True, hide_index=True)
    else:
        st.info("No cost data yet — run something first.")

    st.divider()

    # ── Throughput / metrics ───────────────────────────────────────────────
    st.subheader("📈 Throughput & Metrics")
    if cfg:
        try:
            from prospector.store import Store
            from prospector.report import metrics_data
            store = Store(cfg)
            m = metrics_data(store)
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total dossiers", m.get("total", 0))
            with col2:
                st.metric("✅ PASS", m.get("n_pass", 0))
            with col3:
                st.metric("🛑 KILL", m.get("n_kill", 0))
            with col4:
                kr = m.get("kill_rate", 0)
                st.metric("Kill rate", f"{kr:.1f}%")

            per_lane = m.get("per_lane", [])
            if per_lane:
                st.markdown("**Per-lane breakdown:**")
                st.dataframe(per_lane, use_container_width=True, hide_index=True)

            gates = m.get("kill_gate_distribution", [])
            if gates:
                st.markdown("**Kill gate distribution:**")
                for g in gates:
                    bar = g.get("bar", "█" * int(g.get("share", 0) * 24))
                    st.markdown(f" `{g.get('gate', ''):<22}` {g.get('count', 0):>3}  {bar}")
        except Exception as e:
            st.warning(f"Could not load metrics: {e}")

    st.divider()

    # ── Generation quality ──────────────────────────────────────────────────
    st.subheader("🎨 Generation quality")
    if cfg:
        try:
            from prospector.store import Store
            from prospector.report import generation_quality_data
            store = Store(cfg)
            gq = generation_quality_data(store)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Candidates", gq.get("n_candidates", 0))
                st.metric("Structural forms", gq.get("form_count", 0))
            with col2:
                st.metric("Prescreen pass rate",
                         f"{gq.get('prescreen_pass_rate', 0):.0f}%")
                st.metric("Prescreen keep/reject",
                         f"{gq.get('prescreen_keep', 0)}/{gq.get('prescreen_reject', 0)}")

            forms = gq.get("forms", [])
            if forms:
                st.markdown(f"**Forms seen:** {', '.join(forms)}")

            warnings = gq.get("warnings", [])
            for w in warnings:
                st.warning(f"[{w.get('code', '')}] {w.get('message', '')}")
        except Exception as e:
            st.warning(f"Could not load generation quality: {e}")

    st.divider()

    # ── Trend ───────────────────────────────────────────────────────────────
    st.subheader("📉 Rolling cohort trend")
    if cfg:
        try:
            from prospector.store import Store
            from prospector.report import trend_data
            store = Store(cfg)
            t = trend_data(store)
            cols = st.columns(len(t.get("windows", {})))
            for i, (days, data) in enumerate(t.get("windows", {}).items()):
                with cols[i] if i < len(cols) else st:
                    st.metric(f"{days}d: n={data.get('n', 0)}",
                             f"KILL {data.get('kill_rate', 0):.0f}%",
                             delta=f"PASS {data.get('pass_rate', 0):.0f}%")
        except Exception as e:
            st.warning(f"Could not load trend: {e}")
