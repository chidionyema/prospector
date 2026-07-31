"""Operator authentication gate for the Control Center.

The portal exposes config editing, run launching, and cost data with no other access
control, so it MUST sit behind a gate before it is ever reachable off the loopback. This is
fail-closed by design (mirrors the engine API's `require_admin`): if no password is
configured, the portal refuses to render at all rather than defaulting to open.

Set the password out of band, never committed:

    export CONTROL_CENTER_PASSWORD='…'

Remote access is an SSH tunnel to the localhost-bound port, never a public bind. See
DEPLOYMENT.md.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

_PASSWORD_ENV = "CONTROL_CENTER_PASSWORD"
_AUTHED_KEY = "cc_authed"
_ATTEMPTS_KEY = "cc_auth_attempts"
_MAX_ATTEMPTS = 5


def _configured_password() -> str | None:
    pw = os.environ.get(_PASSWORD_ENV)
    return pw if pw else None


def require_auth() -> None:
    """Block all downstream rendering until the operator authenticates.

    Call once at the top of the app, before any page renders. Returns normally only when the
    session is authenticated; otherwise renders the gate and halts the script via st.stop().
    """
    if st.session_state.get(_AUTHED_KEY):
        return

    expected = _configured_password()
    if expected is None:
        # Fail closed: an unconfigured portal is a locked portal, never an open one.
        st.title("🛰 Prospector Control Center")
        st.error(
            f"Portal not configured. Set the `{_PASSWORD_ENV}` environment variable to a "
            "secret value and relaunch. The portal will not render without it."
        )
        st.stop()

    st.title("🛰 Prospector Control Center")
    st.caption("Operator sign-in")

    attempts = st.session_state.get(_ATTEMPTS_KEY, 0)
    if attempts >= _MAX_ATTEMPTS:
        st.error("Too many failed attempts. Restart the session to try again.")
        st.stop()

    with st.form("cc_auth", clear_on_submit=True):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        # Timing-safe compare so a wrong password can't be probed character by character.
        if hmac.compare_digest(entered or "", expected):
            st.session_state[_AUTHED_KEY] = True
            st.session_state[_ATTEMPTS_KEY] = 0
            st.rerun()
        else:
            st.session_state[_ATTEMPTS_KEY] = attempts + 1
            st.error("Incorrect password.")

    # Whether or not a (wrong) password was just submitted, nothing past the gate may render.
    st.stop()
