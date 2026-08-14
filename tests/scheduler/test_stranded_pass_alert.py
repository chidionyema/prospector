"""The engine must report a PASS the buyer cannot reach, without being asked.

On 2026-08-14 three PASSes sat unbuyable — `25363e54b649587a` blocked on a title initialism,
plus `3d20db251950c20a` and `5b8720247589ae96` — while every tick reported healthy. Nothing
alerted, because the condition is invisible to `alerts_for_tick`: a pack strands at PUBLISH
time and the tick that made it records `passes: 1`. The only reader of
`tools/verify_pass_shelf_coverage.py` was the session-start probe, so the check ran when a
human was already looking. The founder found it by asking.

These tests pin the four behaviours that make it monitoring rather than decoration.
"""
from __future__ import annotations

import subprocess

import pytest

from prospector.scheduler import run_scheduled


class _Cfg:
    """Minimal stand-in — emit_alert/resolve_alert are patched, so nothing reads it."""


def _proc(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["x"], returncode, stdout, "")


@pytest.fixture
def emitted(monkeypatch):
    """Capture emit_alert / resolve_alert calls instead of writing or pushing anything."""
    calls: dict[str, list] = {"emit": [], "resolve": []}
    import prospector.scheduler.alerts as alerts

    monkeypatch.setattr(alerts, "emit_alert", lambda cfg, **kw: calls["emit"].append(kw) or kw)
    monkeypatch.setattr(alerts, "resolve_alert", lambda cfg, **kw: calls["resolve"].append(kw))
    return calls


_STRANDED_STDOUT = (
    "stranded passes: 3\n"
    "[25363e54b649587a] PASS, not listed: lint_ok=false\n"
    "[3d20db251950c20a] PASS, no listing row\n"
    "[5b8720247589ae96] PASS, no listing row\n"
)


def test_a_stranded_pass_raises_a_critical_alert(monkeypatch, emitted):
    monkeypatch.setattr(run_scheduled, "_run_coverage_check", lambda: _proc(1, _STRANDED_STDOUT))
    run_scheduled._emit_stranded_pass_alert(_Cfg(), {"allowed": True, "ts": "T"})

    assert len(emitted["emit"]) == 1, emitted
    alert = emitted["emit"][0]
    assert alert["key"] == "stranded_passes"
    assert alert["severity"] == "critical"
    assert "3" in alert["title"], alert["title"]
    assert "25363e54b649587a" in alert["message"]
    # A standing condition, not an event: 6h, or a strand that lasts a day mutes the channel.
    assert alert["throttle_s"] == 21600


def test_a_clean_shelf_resolves_instead_of_staying_red(monkeypatch, emitted):
    """ALERT.txt showing yesterday's critical is how a real one gets ignored."""
    monkeypatch.setattr(run_scheduled, "_run_coverage_check", lambda: _proc(0, "stranded passes: 0\n"))
    run_scheduled._emit_stranded_pass_alert(_Cfg(), {"allowed": True, "ts": "T"})

    assert emitted["emit"] == []
    assert [c["key"] for c in emitted["resolve"]] == ["stranded_passes"]


def test_an_unreadable_shelf_alerts_nothing(monkeypatch, emitted):
    """Exit 2 is "could not look", which is not "found something". Alerting on it trains the
    reader to ignore the line — the exact failure that makes a red dashboard worthless."""
    monkeypatch.setattr(run_scheduled, "_run_coverage_check", lambda: _proc(2, "catalogue unreachable\n"))
    run_scheduled._emit_stranded_pass_alert(_Cfg(), {"allowed": True, "ts": "T"})

    assert emitted["emit"] == [] and emitted["resolve"] == []


def test_a_dry_run_or_skipped_tick_checks_nothing(monkeypatch, emitted):
    def _boom():
        raise AssertionError("the coverage script must not run on a dry/skipped tick")

    monkeypatch.setattr(run_scheduled, "_run_coverage_check", _boom)
    run_scheduled._emit_stranded_pass_alert(_Cfg(), {"allowed": True, "dry_run": True})
    run_scheduled._emit_stranded_pass_alert(_Cfg(), {"allowed": False})
    assert emitted["emit"] == [] and emitted["resolve"] == []


def test_a_broken_check_never_breaks_the_daemon(monkeypatch, emitted):
    """Monitoring that can kill the thing it monitors is a downgrade."""
    def _raise(*a, **k):
        raise subprocess.TimeoutExpired("x", 30)

    monkeypatch.setattr(subprocess, "run", _raise)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    run_scheduled._emit_stranded_pass_alert(_Cfg(), {"allowed": True})   # must not raise
    assert emitted["emit"] == []


def test_the_alert_reaches_the_founder_off_machine():
    """File-only is how this stayed invisible. A strand does not clear on its own — the engine
    has no republish retry — so it belongs on the Telegram allowlist by that rail's own rule."""
    from prospector.scheduler.alerts import TELEGRAM_KEYS

    assert "stranded_passes" in TELEGRAM_KEYS


def test_the_check_is_wired_into_every_tick():
    """Written but never called is the state this function was in for one session. It must be
    invoked ABOVE the recovery path's early returns, so an errored tick still reports a strand."""
    import inspect

    src = inspect.getsource(run_scheduled._emit_tick_alerts)
    assert "_emit_stranded_pass_alert(cfg, tick)" in src, src
    body = src.split('"""')[2]                      # everything after the docstring
    code = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    call_at = next(i for i, ln in enumerate(code) if "_emit_stranded_pass_alert" in ln)
    returns = [i for i, ln in enumerate(code) if ln.strip().startswith("return")]
    # Matching on CODE lines only: the first version of this test matched the word "return"
    # inside the comment above the call and asserted 588 < 224 — a vacuous failure on a
    # correctly-wired function.
    assert returns, "the recovery path's early returns are gone; re-check this assertion"
    assert call_at < returns[0], "the check must run before any early return"


def test_the_check_never_reaches_production_from_a_test_run():
    """The fence, asserted directly. Wiring this into `_emit_tick_alerts` immediately made
    test_alert_resolution.py and test_tick_hard_deadline.py fetch the LIVE catalogue and go red
    on a real finding about three real packs. Passing tests that talk to production are still a
    defect — same class as `alerts._load_hermes_sender`, which refuses to load under pytest."""
    assert run_scheduled._run_coverage_check() is None
