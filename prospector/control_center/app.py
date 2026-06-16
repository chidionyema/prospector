"""Prospector Control Center — Streamlit entrypoint.

Launch: streamlit run prospector/control_center/app.py --server.port 8601
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on the Python path so prospector imports resolve
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from prospector.control_center import state as _state
from prospector.control_center import pages as _pages_mod

# Page modules — each exposes a render() function
_PAGE_MODULES = {
    "overview": _pages_mod._overview,
    "catalogue": _pages_mod._catalogue,
    "launcher": _pages_mod._launcher,
    "diagnostics": _pages_mod._diagnostics,
    "parameters": _pages_mod._parameters,
    "reports": _pages_mod._reports,
    "resume": _pages_mod._resume,
}

_PAGES_LIST = [
    ("🛰 Overview", "overview"),
    ("📋 Catalogue", "catalogue"),
    ("🚀 Launch", "launcher"),
    ("🔬 Diagnostics", "diagnostics"),
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
        initial_sidebar_state="expanded",
    )

    _state.init_state(
        active_page="overview",
        selected_dossier=None,
        staged_config=None,
    )

    # ── Sidebar nav ─────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("🛰 Prospector")
        st.caption("Control Center")

        # Radio persists selected index in session_state
        labels = [p[0] for p in _PAGES_LIST]
        idx = next((i for i, p in enumerate(_PAGES_LIST) if p[1] == st.session_state.active_page), 0)
        selected_label = st.radio(
            "Navigate", labels, index=idx,
            format_func=lambda p: p,
        )
        key = next((p[1] for p in _PAGES_LIST if p[0] == selected_label), _DEFAULT_KEY)

        if st.session_state.active_page != key:
            st.session_state.active_page = key
            st.rerun()

        st.divider()
        st.caption(f"Project: `{_ROOT.name}`")
        st.caption(f"Store: `store/`")

    # ── Active page ──────────────────────────────────────────────────────────
    mod = _PAGE_MODULES.get(st.session_state.active_page, _PAGE_MODULES[_DEFAULT_KEY])
    try:
        mod.render()
    except Exception as e:
        st.error(f"Error rendering {st.session_state.active_page}: {e}")
        import traceback
        st.code(traceback.format_exc(), language="python")


if __name__ == "__main__":
    main()