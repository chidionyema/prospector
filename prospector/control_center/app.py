"""Prospector Control Center — Streamlit entrypoint.

Launch (loopback-bound, behind the operator gate): scripts/run_control_center.sh
That requires CONTROL_CENTER_PASSWORD to be set; the portal fails closed without it.
Remote access is an SSH tunnel to the localhost port, never a public bind. See DEPLOYMENT.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on the Python path so prospector imports resolve
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from prospector.control_center import pages as _pages_mod
from prospector.control_center import state as _state
from prospector.control_center.auth import require_auth
from prospector.control_center.theme import inject_theme

# Page modules — each exposes a render() function
_PAGE_MODULES = {
    "overview": _pages_mod._overview,
    "catalogue": _pages_mod._catalogue,
    "launcher": _pages_mod._launcher,
    "diagnostics": _pages_mod._diagnostics,
    "engine": _pages_mod._engine,
    "runs": _pages_mod._runs,
    "metrics": _pages_mod._metrics,
    "spend": _pages_mod._spend,
    "parameters": _pages_mod._parameters,
    "reports": _pages_mod._reports,
    "resume": _pages_mod._resume,
}

_PAGES_LIST = [
    ("🛰 Overview", "overview"),
    ("📋 Catalogue", "catalogue"),
    ("🚀 Launch", "launcher"),
    ("🔬 Diagnostics", "diagnostics"),
    ("🛠 Engine", "engine"),
    ("🔎 Runs", "runs"),
    ("📈 Outcomes", "metrics"),
    ("💵 Spend", "spend"),
    ("⚙️ Parameters", "parameters"),
    ("📊 Reports", "reports"),
    ("⏳ Resume", "resume"),
]

_DEFAULT_KEY = "overview"


def main():
    st.set_page_config(
        page_title="Prospector Control Center",
        page_icon="🛰",
        layout="wide",
        # Collapsed by default. The console's primary surface is a phone over the tailnet,
        # where an expanded sidebar OCCLUDES the page instead of reflowing it: every control
        # renders off-screen behind the nav until the operator finds the collapse chevron.
        initial_sidebar_state="collapsed",
    )

    # Theme BEFORE the gate. The gate halts the script with st.stop(), so a theme injected
    # after it never reaches the one screen every operator is guaranteed to see.
    inject_theme()

    # Fail-closed operator gate. Must run before any page (config editor, run launcher,
    # cost data) can render. Halts via st.stop() until authenticated.
    require_auth()

    # Land on Engine, not Overview. Overview's headline is built from the last MANUAL
    # launcher job, which is silent about the daemon — on 2026-08-16 it read
    # "Engine idle · last generate k=5 failed" from a job dated 2026-07-31 while the
    # consumer was live and ruling. The first screen must report the process that is running.
    _state.init_state(
        active_page="engine",
        selected_dossier=None,
        staged_config=None,
    )

    # ── Sidebar nav ─────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("**Prospector**")
        st.caption("Operator console")

        labels = [p[0] for p in _PAGES_LIST]
        # Radio is source of truth for sidebar clicks. Programmatic nav (go_page)
        # sets _sync_nav_radio so we align the widget *before* it is instantiated —
        # never overwrite a fresh radio click with a stale active_page.
        if st.session_state.pop("_sync_nav_radio", False) or "nav_radio" not in st.session_state:
            want = next(
                (p[0] for p in _PAGES_LIST if p[1] == st.session_state.active_page),
                labels[0],
            )
            st.session_state["nav_radio"] = want

        selected_label = st.radio(
            "Navigate",
            labels,
            key="nav_radio",
            format_func=lambda p: p,
        )
        key = next((p[1] for p in _PAGES_LIST if p[0] == selected_label), _DEFAULT_KEY)
        st.session_state.active_page = key

        st.divider()
        st.caption(f"Project: `{_ROOT.name}`")
        st.caption("Store: `store/`")

    # ── Active page ──────────────────────────────────────────────────────────
    mod = _PAGE_MODULES.get(key, _PAGE_MODULES[_DEFAULT_KEY])
    try:
        mod.render()
    except Exception as e:
        st.error(f"Error rendering {key}: {e}")
        import traceback
        st.code(traceback.format_exc(), language="python")


if __name__ == "__main__":
    main()