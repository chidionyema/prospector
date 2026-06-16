"""Session-state helpers for the Control Center.

All durable state lives on disk; session_state is only for ephemeral UI state
(selected dossier, staged config edits, active page).
"""
from __future__ import annotations

import streamlit as st
from typing import Any


def init_state(**defaults: Any) -> None:
    """Initialise session_state keys that don't exist yet."""
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_state(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)


def set_state(key: str, value: Any) -> None:
    st.session_state[key] = value
