"""The off-machine alert sink (Hermes Telegram).

THE FENCE THIS FILE ENFORCES. The Hermes estate has already messaged the founder for real from a
test suite once. `_telegram_push` therefore passes `dry_run=True` whenever `PYTEST_CURRENT_TEST` is
in the environment — pytest sets that on every test, so the suite physically cannot send. The
first test below asserts that fence directly; if someone replaces it with an opt-in env var a test
could forget to set, this fails.
"""
from __future__ import annotations

import os

from prospector.scheduler import alerts as A


def _record(key="liveness", severity="critical"):
    return {"key": key, "severity": severity, "title": "Daemon down",
            "message": "no tick in 4h"}


def test_pytest_forces_dry_run(monkeypatch):
    """The suite must never be able to message the founder."""
    seen = {}

    def fake_send(text, *, debounce_key=None, debounce_s=300.0, dry_run=False):
        seen.update(text=text, debounce_key=debounce_key, dry_run=dry_run)
        return True

    monkeypatch.setattr(A, "_load_hermes_sender", lambda: fake_send)
    assert "PYTEST_CURRENT_TEST" in os.environ, "pytest no longer sets this; the fence is broken"
    A._telegram_push(_record())
    assert seen["dry_run"] is True


def test_only_founder_actionable_keys_are_sent(monkeypatch):
    """Telegram is for states that will NOT clear without a human. Paging on self-healing
    conditions (a DEFER is not an error) gets the channel muted, and a muted rail is an unwired
    rail with extra steps."""
    sent = []
    monkeypatch.setattr(A, "_load_hermes_sender",
                        lambda: lambda text, **kw: sent.append(kw.get("debounce_key")) or True)

    for key in ("liveness", "tick_error", "zero_yield", "barren_streak"):
        A._telegram_push(_record(key=key))
    assert len(sent) == 4

    sent.clear()
    for key in ("moat_deferred", "moat_provisional", "barren_generation"):
        A._telegram_push(_record(key=key))
    assert sent == [], "self-healing conditions must stay local"


def test_debounce_key_is_namespaced(monkeypatch):
    """Hermes' debounce file is shared estate-wide; an un-namespaced key would collide with
    another Hermes alert of the same name and silently swallow one of them."""
    seen = {}
    monkeypatch.setattr(A, "_load_hermes_sender",
                        lambda: lambda text, **kw: seen.update(kw) or True)
    A._telegram_push(_record(key="tick_error"))
    assert seen["debounce_key"] == "prospector:tick_error"


def test_missing_hermes_degrades_silently(monkeypatch):
    """A moved or absent estate must degrade to the four local sinks, never raise: alerting can
    not be allowed to crash the daemon it is meant to guard."""
    monkeypatch.setattr(A, "_load_hermes_sender", lambda: None)
    A._telegram_push(_record())  # must not raise


def test_a_raising_sender_cannot_escape(monkeypatch):
    """Hermes documents send_operator_alert as never-raising, but this sink trusts nothing."""
    def boom(text, **kw):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(A, "_load_hermes_sender", lambda: boom)
    A._telegram_push(_record())  # must not raise


def test_real_loader_does_not_send_on_import(monkeypatch):
    """Loading Hermes' module executes it. Assert that import alone sends nothing by checking the
    loader returns a callable (or None) and does not blow up in this environment."""
    send = A._load_hermes_sender()
    assert send is None or callable(send)
