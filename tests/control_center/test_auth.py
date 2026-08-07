"""The Control Center operator gate must fail closed and only pass on the right password."""
from __future__ import annotations

import streamlit as st
from streamlit.testing.v1 import AppTest

from prospector.control_center.auth import _AUTHED_KEY, _PASSWORD_ENV, require_auth


def _gated_app():
    """Driver: run the gate, then reveal a sentinel only if it lets us through.

    AppTest.from_function re-execs this source in a bare module, so every name it uses must
    be imported inside the body — module-level imports of the test file are not visible here.
    """
    import streamlit as st  # noqa: F811

    from prospector.control_center.auth import require_auth  # noqa: F811

    require_auth()
    st.write("PAST_GATE")


# AppTest's default deadline is 3 WALL-CLOCK seconds (`local_script_runner.require_widgets_deltas`),
# which on a loaded box measures the machine, not the gate. It blocked a commit at `load averages:
# 210.54` with `RuntimeError: AppTest script run timed out after 3(s)` — and whichever of these
# tests ran FIRST was the one that failed, which is the tell. None of the assertions below is about
# speed, so the deadline is raised to a value that still catches a genuine hang.
_RUN_TIMEOUT = 60


def _app() -> AppTest:
    return AppTest.from_function(_gated_app, default_timeout=_RUN_TIMEOUT)


def _past_gate(at) -> bool:
    return any("PAST_GATE" in (md.value or "") for md in at.markdown)


def _authed(at) -> bool:
    # AppTest's session_state supports item access but not .get().
    try:
        return bool(at.session_state[_AUTHED_KEY])
    except (KeyError, AttributeError):
        return False


def test_unconfigured_portal_fails_closed(monkeypatch):
    monkeypatch.delenv(_PASSWORD_ENV, raising=False)
    at = _app().run()
    assert not _past_gate(at)
    assert len(at.error) >= 1
    assert not _authed(at)


def test_configured_portal_requires_signin(monkeypatch):
    monkeypatch.setenv(_PASSWORD_ENV, "s3cret")
    at = _app().run()
    assert not _past_gate(at)
    assert not _authed(at)
    # A sign-in field is offered.
    assert len(at.text_input) >= 1


def test_preauthed_session_passes_through(monkeypatch):
    monkeypatch.setenv(_PASSWORD_ENV, "s3cret")
    at = _app()
    at.session_state[_AUTHED_KEY] = True
    at.run()
    assert _past_gate(at)


def test_wrong_password_blocks(monkeypatch):
    monkeypatch.setenv(_PASSWORD_ENV, "s3cret")
    at = _app().run()
    at.text_input[0].set_value("nope")
    at.button[0].click().run()
    assert not _authed(at)
    assert not _past_gate(at)


def test_correct_password_authenticates(monkeypatch):
    monkeypatch.setenv(_PASSWORD_ENV, "s3cret")
    at = _app().run()
    at.text_input[0].set_value("s3cret")
    at.button[0].click().run()
    assert _authed(at)
    assert _past_gate(at)
