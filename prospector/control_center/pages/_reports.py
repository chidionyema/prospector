"""Reports & Economics — read-only demand metrics. Never loads full audit on open."""
from __future__ import annotations

import streamlit as st

from prospector.control_center import readers
from prospector.control_center.components.chrome import go_page, page_hero


def render():
    kpis = readers.load_overview_kpis()
    spend = float(kpis.get("today_spend") or 0.0)
    cap = float(kpis.get("daily_cap") or 50.0)
    total = int(kpis.get("total") or 0)
    glance = (
        f"Today ${spend:.2f} / ${cap:.0f} · "
        f"PASS {kpis.get('pass_count', 0)} · KILL {kpis.get('kill_count', 0)} · "
        f"{total} dossiers"
    )
    page_hero("Reports", glance, tone="warn" if spend > 0.8 * cap else "idle")
    st.caption("Read-only. Demand never overrides truth — tune gates on Parameters.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spend today", f"${spend:.2f}")
    c2.metric("Daily cap", f"${cap:.0f}")
    c3.metric("PASS", kpis.get("pass_count", 0))
    c4.metric("KILL", kpis.get("kill_count", 0))

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Open Catalogue", use_container_width=True):
            go_page("catalogue")
    with b2:
        load_lifetime = st.button(
            "Load lifetime costs (slow)",
            use_container_width=True,
            help="Scans full store/prospector.jsonl — avoid on every refresh",
        )

    cfg = readers.load_config_typed()
    st.markdown("**Throughput**")
    if cfg:
        try:
            from prospector.report import metrics_data
            from prospector.store import Store
            m = metrics_data(Store(cfg))
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Dossiers", m.get("total", 0))
            r2.metric("PASS", m.get("n_pass", 0))
            r3.metric("KILL", m.get("n_kill", 0))
            r4.metric("Kill rate", f"{m.get('kill_rate', 0):.1f}%")
            per_lane = m.get("per_lane") or []
            if per_lane:
                st.dataframe(per_lane, use_container_width=True, hide_index=True, height=200)
            gates = m.get("kill_gate_distribution") or []
            if gates:
                with st.expander("Kill gate distribution", expanded=False):
                    for g in gates:
                        bar = g.get("bar", "█" * int(g.get("share", 0) * 24))
                        st.markdown(
                            f"`{g.get('gate', ''):<22}` {g.get('count', 0):>3}  {bar}"
                        )
        except Exception as e:
            st.warning(f"Metrics unavailable: {e}")
    else:
        st.caption("Config unavailable.")

    with st.expander("Generation quality", expanded=False):
        _render_gen_quality(cfg)

    with st.expander("Rolling cohort trend", expanded=False):
        _render_trend(cfg)

    if load_lifetime or st.session_state.get("_reports_lifetime"):
        st.session_state["_reports_lifetime"] = True
        st.markdown("**Lifetime costs**")
        _render_lifetime_costs()
    else:
        st.caption("Lifetime economics stay collapsed until you ask — keeps the page fast.")


def _render_lifetime_costs():
    try:
        from prospector.report import costs_data as _costs_data
        costs = _costs_data("store/prospector.jsonl")
    except Exception as e:
        st.warning(f"Cost scan failed: {e}")
        return
    if not costs or costs.get("error"):
        st.caption(costs.get("error") if costs else "No cost data.")
        return
    total = costs.get("total_spend_usd", 0)
    calls = costs.get("total_calls", 0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Lifetime spend", f"${total:.4f}")
    c2.metric("API calls", calls)
    c3.metric("Errors excluded", costs.get("errors_excluded", 0))
    providers = costs.get("providers") or []
    if providers:
        rows = [{
            "provider": p.get("name", "?"),
            "cost_usd": f"${p.get('cost_usd', 0):.4f}",
            "calls": p.get("calls", 0),
            "input": p.get("input", 0),
            "output": p.get("output", 0),
        } for p in providers]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    slowest = costs.get("slowest_ops") or []
    if slowest:
        with st.expander("Slowest ops", expanded=False):
            st.dataframe(slowest, use_container_width=True, hide_index=True)


def _render_gen_quality(cfg):
    if not cfg:
        st.caption("No config.")
        return
    try:
        from prospector.report import generation_quality_data
        from prospector.store import Store
        gq = generation_quality_data(Store(cfg))
        c1, c2 = st.columns(2)
        c1.metric("Candidates", gq.get("n_candidates", 0))
        c1.metric("Forms", gq.get("form_count", 0))
        c2.metric("Prescreen pass", f"{gq.get('prescreen_pass_rate', 0):.0f}%")
        c2.metric(
            "Keep/reject",
            f"{gq.get('prescreen_keep', 0)}/{gq.get('prescreen_reject', 0)}",
        )
        forms = gq.get("forms") or []
        if forms:
            st.caption("Forms: " + ", ".join(forms))
        for w in gq.get("warnings") or []:
            st.warning(f"[{w.get('code', '')}] {w.get('message', '')}")
    except Exception as e:
        st.warning(str(e))


def _render_trend(cfg):
    if not cfg:
        st.caption("No config.")
        return
    try:
        from prospector.report import trend_data
        from prospector.store import Store
        t = trend_data(Store(cfg))
        windows = t.get("windows") or {}
        if not windows:
            st.caption("No trend windows.")
            return
        cols = st.columns(len(windows))
        for i, (days, data) in enumerate(windows.items()):
            with cols[i]:
                st.metric(
                    f"{days}d n={data.get('n', 0)}",
                    f"KILL {data.get('kill_rate', 0):.0f}%",
                    delta=f"PASS {data.get('pass_rate', 0):.0f}%",
                )
    except Exception as e:
        st.warning(str(e))
