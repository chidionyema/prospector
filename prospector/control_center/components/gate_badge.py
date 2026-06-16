"""Decision badge renderer — PASS/KILL/DEFER with color coding."""
from __future__ import annotations

import streamlit as st


def render_gate_badge(decision: str) -> str:
    """Return an HTML snippet for the decision badge."""
    d = (decision or "").lower()
    if d == "pass":
        return "✅ <span style='color:#22c55e;font-weight:bold'>PASS</span>"
    elif d == "kill":
        return "🛑 <span style='color:#ef4444;font-weight:bold'>KILL</span>"
    elif d == "defer":
        return "⏸ <span style='color:#eab308;font-weight:bold'>DEFER</span>"
    else:
        return str(decision or "—")


def st_gate_badge(decision: str) -> None:
    """Render the decision badge using st.html for coloured text."""
    html = f"""
    <div style='display:inline-flex;align-items:center;gap:4px;
                font-size:0.9em;font-weight:bold'>
        {render_gate_badge(decision)}
    </div>
    """
    st.html(html)


def st_decision_badge(decision: str, key: str | None = None) -> None:
    """Render the decision as a coloured badge using st.container."""
    d = (decision or "").lower()
    col1, col2, col3 = st.columns([1, 1, 1])
    if d == "pass":
        with col1:
            st.success("✅ PASS")
    elif d == "kill":
        with col1:
            st.error("🛑 KILL")
    elif d == "defer":
        with col1:
            st.warning("⏸ DEFER")
    else:
        with col1:
            st.info(str(decision or "—"))


def st_severity_badge(level: str) -> None:
    """Render a calibration alarm severity badge."""
    if level == "alarm":
        st.error("🚨 ALARM")
    elif level == "warn":
        st.warning("⚠️ WARN")
    else:
        st.info(level)
