"""Diagnostics & Calibration — truth loop home."""
from __future__ import annotations

import subprocess

import streamlit as st

from .. import readers
from ..components.gate_badge import st_severity_badge


def render():
    st.title("🔬 Diagnostics & Calibration")

    cfg = readers.load_config_typed()
    if cfg is None:
        st.error("Could not load engine config — diagnostics unavailable.")
        return

    # ── Calibration alarms ────────────────────────────────────────────────
    st.subheader("🚨 Calibration alarms")
    try:
        from prospector.store import Store
        store = Store(cfg)
        from prospector.diagnostics import diagnostics_data
        data = diagnostics_data(store, cfg)
        alarms = data.get("alarms", [])
    except Exception as e:
        st.error(f"Could not load diagnostics: {e}")
        return

    if not alarms:
        st.success("✓ No calibration pathologies detected.")
    else:
        for a in alarms:
            with st.container():
                col1, col2 = st.columns([1, 5])
                with col1:
                    st_severity_badge(a.get("level", "warn"))
                with col2:
                    lane_tag = f" **[{a.get('lane', '')}]**" if a.get("lane") else ""
                    st.markdown(f"**{a.get('code', '')}**: {a.get('message', '')}{lane_tag}")
                st.divider()

    st.divider()

    # ── Golden set ──────────────────────────────────────────────────────────
    st.subheader("🎯 Golden-set discrimination")
    golden_trend = data.get("golden_trend", [])
    latest = data.get("latest_golden")

    if latest:
        disc = latest.get("discrimination", 0)
        floor = latest.get("floor", 0.75)
        ok = latest.get("ok", False)
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Discrimination", f"{disc:.0%}",
                     delta="✅ OK" if ok else f"❌ below {floor:.0%} floor")
        with col2:
            st.metric("Floor", f"{floor:.0%}")

        cases = latest.get("cases", [])
        if cases:
            rows = []
            for c in cases:
                rows.append({
                    "idea": c.get("idea", "")[:40],
                    "expected": c.get("expected", "?"),
                    "actual": c.get("actual", "?"),
                    "passed": "✅" if c.get("passed") else "❌",
                    "lane": c.get("lane", ""),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True,
                        column_config={
                            "idea": st.column_config.TextColumn("idea", width="large"),
                            "expected": st.column_config.TextColumn("expected", width="small"),
                            "actual": st.column_config.TextColumn("actual", width="small"),
                            "passed": st.column_config.TextColumn("result", width="tiny"),
                            "lane": st.column_config.TextColumn("lane", width="small"),
                        })
    else:
        st.info("No golden-set runs yet. Run golden regression to establish the baseline.")

    # ── Golden trend sparkline ─────────────────────────────────────────────
    if golden_trend:
        trend_df = []
        for i, g in enumerate(reversed(golden_trend[:20])):
            trend_df.append({
                "run": i + 1,
                "discrimination": g.get("discrimination") or 0,
                "operator": g.get("operator", "?"),
                "ok": "✅" if g.get("ok") else "❌",
            })
        st.line_chart(trend_df, x="run", y="discrimination",
                     color="#4ade80", height=200)
        st.dataframe(trend_df, use_container_width=True, hide_index=True)

    # ── Run golden buttons ─────────────────────────────────────────────────
    st.divider()
    st.subheader("▶ Run golden-set")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run golden regression (offline, free)",
                   help="Runs pytest -k golden — uses fixtures, no API cost"):
            try:
                result = subprocess.run(
                    [".venv/bin/python", "-m", "pytest", "tests/", "-k", "golden",
                     "--tb=short", "-q"],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(Path(__file__).resolve().parent.parent.parent.parent)
                )
                st.code(result.stdout[-2000:] if result.stdout else result.stderr[-2000:])
                st.metric("exit code", result.returncode)
            except Exception as e:
                st.error(f"Regression failed: {e}")

    with col2:
        if st.button("Run golden promotion (live, costs API)",
                   help="Runs the full golden set against the production chain"):
            st.warning("Live golden promotion costs API calls. "
                      "Make sure your operator key has quota.")

    # ── Operator health ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("⚡ Operator health")
    health = readers.load_provider_health()
    if not health:
        st.info("No provider health data yet.")
    else:
        now = __import__("time").time()
        rows = []
        for op, state in sorted(health.items()):
            if not isinstance(state, dict):
                continue
            du = state.get("dead_until", 0)
            remaining = max(0, du - now)
            if remaining > 0:
                label = "🔴 DEAD"
                remaining_str = f"{remaining:.0f}s"
            elif du > 0:
                label = "🟡 RECOVERING"
                remaining_str = "recovering"
            else:
                label = "🟢 HEALTHY"
                remaining_str = "—"
            rows.append({
                "operator": op,
                "state": label,
                "dead_for_s": round(state.get("dead_for_s", 0)),
                "remaining": remaining_str,
            })
        st.dataframe(rows, use_container_width=True, hide_index=True,
                    column_config={
                        "operator": st.column_config.TextColumn("operator", width="large"),
                        "state": st.column_config.TextColumn("state", width="small"),
                        "dead_for_s": st.column_config.NumberColumn(
                            "dead_for_s", format="%d", width="small"),
                        "remaining": st.column_config.TextColumn("remaining", width="small"),
                    })
