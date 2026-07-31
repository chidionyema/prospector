"""Diagnostics — calibration alarms, golden set, operator health."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import streamlit as st

from prospector.control_center import readers
from prospector.control_center.components.chrome import go_page, page_hero
from prospector.control_center.components.gate_badge import st_severity_badge


def render():
    cfg = readers.load_config_typed()
    if cfg is None:
        page_hero("Diagnostics", "Config unloadable", tone="fail")
        st.error("Could not load engine config.")
        return

    latest_g = readers.latest_golden()
    health = readers.load_provider_health()
    moat = readers.moat_down(health)
    disc = latest_g.get("discrimination_score") if latest_g else None
    if moat:
        glance = "Moat down · check operator health"
        tone = "fail"
    elif disc is not None:
        ok = latest_g.get("passed", False)
        glance = f"Golden discrimination {disc:.3f} · {'PASS' if ok else 'FAIL'}"
        tone = "ok" if ok else "warn"
    else:
        glance = "No golden run yet · alarms load on demand"
        tone = "idle"

    page_hero("Diagnostics", glance, tone=tone)

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Run golden (offline)", type="primary", use_container_width=True):
            _run_golden_offline()
    with c2:
        if st.button("Open Parameters", use_container_width=True):
            go_page("parameters")
    with c3:
        load_alarms = st.button("Load calibration alarms", use_container_width=True)

    st.markdown("**Operator health**")
    _render_operator_health(health)

    if load_alarms or st.session_state.get("_diag_alarms_loaded"):
        st.session_state["_diag_alarms_loaded"] = True
        _render_alarms(cfg)
    else:
        st.caption("Calibration alarms are slow on a large store — click to load.")

    st.markdown("**Golden-set**")
    _render_golden(cfg)

    with st.expander("Generative alpha benchmark (paid)", expanded=False):
        _render_alpha(cfg)


def _render_operator_health(health: dict):
    watched = readers.watched_operators()
    now = time.time()
    if not health and not watched:
        st.caption("No provider health data.")
        return

    rows = []
    seen = set()
    # Prefer watched ops; skip spam for unrelated dead openrouter free models
    # unless they appear in watched names.
    for op in watched:
        seen.add(op.lower())
        state = health.get(op) if isinstance(health, dict) else None
        if not isinstance(state, dict):
            for k, v in (health or {}).items():
                if isinstance(v, dict) and k.lower().split("/")[0] == op.lower():
                    state = v
                    break
        if not isinstance(state, dict):
            rows.append({"operator": op, "state": "healthy", "remaining": "—"})
            continue
        du = state.get("dead_until", 0) or 0
        remaining = max(0, du - now)
        if remaining > 0:
            rows.append({
                "operator": op,
                "state": "DEAD",
                "remaining": f"{remaining:.0f}s",
            })
        elif du > 0:
            rows.append({"operator": op, "state": "recovering", "remaining": "—"})
        else:
            rows.append({"operator": op, "state": "healthy", "remaining": "—"})

    st.dataframe(rows, use_container_width=True, hide_index=True, height=220)

    # Other circuit keys collapsed
    extras = []
    for op, state in sorted((health or {}).items()):
        if not isinstance(state, dict):
            continue
        if op.lower().split("/")[0] in seen or op.lower() in seen:
            continue
        du = state.get("dead_until", 0) or 0
        remaining = max(0, du - now)
        if remaining <= 0 and not du:
            continue
        extras.append({
            "operator": op,
            "state": "DEAD" if remaining > 0 else "recovering",
            "remaining": f"{remaining:.0f}s" if remaining > 0 else "—",
        })
    if extras:
        with st.expander(f"Other breakers ({len(extras)})", expanded=False):
            st.dataframe(extras, use_container_width=True, hide_index=True)


def _render_alarms(cfg):
    st.markdown("**Calibration alarms**")
    try:
        from prospector.store import Store
        from prospector.diagnostics import diagnostics_data
        data = diagnostics_data(Store(cfg), cfg)
        alarms = data.get("alarms", [])
        st.session_state["_diag_data"] = data
    except Exception as e:
        st.error(f"Diagnostics failed: {e}")
        return

    if not alarms:
        st.success("No calibration pathologies detected.")
        return
    for a in alarms:
        col1, col2 = st.columns([1, 5])
        with col1:
            st_severity_badge(a.get("level", "warn"))
        with col2:
            lane_tag = f" [{a.get('lane')}]" if a.get("lane") else ""
            st.markdown(f"**{a.get('code', '')}**: {a.get('message', '')}{lane_tag}")


def _render_golden(cfg):
    data = st.session_state.get("_diag_data") or {}
    latest = data.get("latest_golden") or readers.latest_golden()
    golden_trend = data.get("golden_trend") or []

    if latest:
        # readers.latest_golden vs diagnostics shape
        disc = latest.get("discrimination")
        if disc is None:
            disc = latest.get("discrimination_score") or 0
        floor = latest.get("floor", 0.75)
        ok = latest.get("ok", latest.get("passed", False))
        c1, c2 = st.columns(2)
        c1.metric("Discrimination", f"{float(disc):.0%}", delta="OK" if ok else f"below {float(floor):.0%}")
        c2.metric("Floor", f"{float(floor):.0%}")

        cases = latest.get("cases") or []
        if cases:
            rows = [{
                "idea": (c.get("idea") or "")[:40],
                "expected": c.get("expected", "?"),
                "actual": c.get("actual", "?"),
                "passed": "Y" if c.get("passed") else "N",
                "lane": c.get("lane", ""),
            } for c in cases]
            st.dataframe(rows, use_container_width=True, hide_index=True, height=220)
    else:
        st.caption("No golden-set runs yet.")

    if golden_trend:
        trend_df = [{
            "run": i + 1,
            "discrimination": g.get("discrimination") or 0,
            "operator": g.get("operator", "?"),
            "ok": "Y" if g.get("ok") else "N",
        } for i, g in enumerate(reversed(golden_trend[:20]))]
        st.line_chart(trend_df, x="run", y="discrimination", height=180)

    with st.expander("Live golden promotion (costs API)", expanded=False):
        st.caption("Use CLI `prospector.run` golden promotion when you intend to spend.")


def _run_golden_offline():
    root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        result = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "tests/", "-k", "golden",
             "--tb=short", "-q"],
            capture_output=True, text=True, timeout=300, cwd=str(root),
        )
        out = (result.stdout or result.stderr or "")[-2000:]
        st.code(out)
        st.metric("exit", result.returncode)
    except Exception as e:
        st.error(f"Regression failed: {e}")


def _render_alpha(cfg):
    st.caption("Grades generator depth vs curated high-alpha targets.")
    if st.button("Run strategic benchmark (paid)", key="alpha_btn"):
        with st.status("Grading…", expanded=True) as status:
            try:
                from prospector.golden_gen import run_generative_golden
                from prospector.operator import make_operator
                op = make_operator(cfg)
                report = run_generative_golden(op, op, cfg)
                st.metric("Batch Alpha", f"{report['overall_alpha']}/5.0")
                for case in report.get("cases", []):
                    with st.expander(f"Signal: {case['signal'][:40]}…"):
                        st.write(f"Score: {case['alpha_score']}/5.0")
                        st.write(case.get("rationale", ""))
                status.update(label="Done", state="complete")
            except Exception as e:
                st.error(str(e))
                status.update(label="Failed", state="error")
