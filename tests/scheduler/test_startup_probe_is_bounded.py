"""The startup grounding probe was the one blocking call with no timeout and no heartbeat.

`_startup_grounding_check` runs BEFORE the first tick, so before any heartbeat exists, and it made
a network call with no bound of its own. A provider that accepts the TCP connection and never
answers wedges the daemon there permanently — and every recovery mechanism reads past it:

  * launchd `KeepAlive` restarts on process EXIT. A wedged-but-alive process never exits.
  * `_liveness` reads the heartbeat, which still holds the PREVIOUS run's `sleeping`/`idle` beat,
    so the watchdog's kill targets the OLD pid.
  * `_kill_stale_daemon` finds that pid gone (launchd already replaced it), logs "already exited;
    launchd will relaunch" and returns satisfied — while the process it should have killed hangs
    on. launchd HAS relaunched. The relaunch IS the wedge.

Two independent fixes, and a test for each: the probe is time-bounded so a hang becomes an exit,
and a `starting` heartbeat is written before the probe so the file names the pid actually at risk
and `_liveness` has a phase to judge.
"""
from __future__ import annotations

import json
import os
import threading
import time
import types
from datetime import datetime, timedelta, timezone

import pytest

from prospector.scheduler import run_scheduled as rs

#: The real probe, bound at import. `_startup_grounding_check` was refactored on 2026-08-06 to
#: delegate to the shared `_probe_grounding_once` (so the startup refusal and the per-tick
#: generation gate cannot drift on what "grounding is up" means), which put it behind
#: tests/conftest.py's autouse `_no_live_grounding_probe` stub. This file is about the probe
#: MECHANISM — the bound, the daemon thread, the pre-probe heartbeat — so it needs the genuine one.
_REAL_PROBE = rs._probe_grounding_once


@pytest.fixture(autouse=True)
def _use_the_real_probe(monkeypatch):
    monkeypatch.setattr(rs, "_probe_grounding_once", _REAL_PROBE)


def _cfg(tmp_path):
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule={"batch_size": 15},
        operator=["claude_cli"],
    )


def _beat_path(tmp_path):
    return tmp_path / "scheduler" / "heartbeat.json"


def _write_beat(tmp_path, *, phase: str, age_min: float, **extra):
    p = _beat_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    p.write_text(json.dumps({"ts": ts.isoformat(), "pid": 999999, "phase": phase, **extra}),
                 encoding="utf-8")


class _Provider:
    """A grounding provider whose `search` blocks until released."""

    def __init__(self, gate: threading.Event | None = None, on_call=None):
        self._gate = gate
        self._on_call = on_call

    def search(self, *_a, **_k):
        if self._on_call is not None:
            self._on_call()
        if self._gate is not None and not self._gate.wait(60):
            raise AssertionError("test gate was never released")
        return [{"url": "https://example.com", "snippet": "ok"}]


# ---------------------------------------------------------------------------
# Fix 1 — the probe is bounded, so a hang becomes an exit launchd can heal
# ---------------------------------------------------------------------------

def test_a_hanging_probe_raises_instead_of_wedging_forever(tmp_path, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr("prospector.retrieval.make_provider", lambda cfg: _Provider(gate))
    monkeypatch.setattr(rs, "_STARTUP_PROBE_TIMEOUT_S", 1)

    t0 = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="did not answer within"):
            rs._startup_grounding_check(_cfg(tmp_path))
        elapsed = time.monotonic() - t0
    finally:
        gate.set()
    assert elapsed < 15, (
        f"the probe must return control at its bound; it took {elapsed:.1f}s. Unbounded, this "
        f"call is where the daemon sat with launchd unable to help it."
    )


def test_the_probe_thread_cannot_hold_the_process_open(tmp_path, monkeypatch):
    """The bound is only an exit if the wedged thread does not join on the way out — a non-daemon
    thread stuck in a socket read would keep the interpreter alive and re-create the wedge one
    layer down, with the RuntimeError already raised and invisible."""
    started: list[threading.Thread] = []
    real_thread = threading.Thread

    def _capture(*a, **k):
        t = real_thread(*a, **k)
        started.append(t)
        return t

    gate = threading.Event()
    monkeypatch.setattr("prospector.retrieval.make_provider", lambda cfg: _Provider(gate))
    monkeypatch.setattr(rs.threading, "Thread", _capture)
    monkeypatch.setattr(rs, "_STARTUP_PROBE_TIMEOUT_S", 1)
    try:
        with pytest.raises(RuntimeError):
            rs._startup_grounding_check(_cfg(tmp_path))
    finally:
        gate.set()
    assert started and all(t.daemon for t in started)


def test_a_healthy_probe_still_starts_the_daemon(tmp_path, monkeypatch):
    monkeypatch.setattr("prospector.retrieval.make_provider", lambda cfg: _Provider())
    rs._startup_grounding_check(_cfg(tmp_path))  # must not raise
    assert json.loads(_beat_path(tmp_path).read_text())["phase"] == "starting"


def test_a_dead_probe_still_refuses_to_start(tmp_path, monkeypatch):
    """No regression on the behaviour this function exists for: a provider that ERRORS (402,
    keyless, down) must still stop the daemon before it burns a generation batch per relaunch."""
    class _Dead:
        def search(self, *_a, **_k):
            raise RuntimeError("402 Payment Required")

    monkeypatch.setattr("prospector.retrieval.make_provider", lambda cfg: _Dead())
    with pytest.raises(RuntimeError, match="dead on arrival"):
        rs._startup_grounding_check(_cfg(tmp_path))


# ---------------------------------------------------------------------------
# Fix 2 — the wedged pid is on disk BEFORE the call that can wedge
# ---------------------------------------------------------------------------

def test_the_heartbeat_names_this_pid_before_the_probe_runs(tmp_path, monkeypatch):
    """The mutation proof: without the pre-probe heartbeat write this read raises FileNotFoundError.

    That absence was the whole defect — a wedge here left the watchdog reading the previous run's
    pid, which launchd had already replaced, so the kill landed on nothing.
    """
    seen: dict = {}

    def _during_probe():
        seen["beat"] = json.loads(_beat_path(tmp_path).read_text(encoding="utf-8"))

    monkeypatch.setattr("prospector.retrieval.make_provider",
                        lambda cfg: _Provider(on_call=_during_probe))
    rs._startup_grounding_check(_cfg(tmp_path))

    assert seen["beat"]["phase"] == "starting"
    assert seen["beat"]["pid"] == os.getpid(), "the pid at risk is THIS process, not the last one"
    assert seen["beat"]["probe_timeout_s"] == rs._STARTUP_PROBE_TIMEOUT_S, (
        "_liveness reads its budget from the beat, so the bound has to travel with it"
    )


def test_liveness_calls_a_stale_starting_heartbeat_dead(tmp_path):
    """Pre-fix, `starting` matched no branch in `_liveness` and fell through to the `alive`
    return — the same fall-through that reported a wedged `draining` tick healthy forever."""
    _write_beat(tmp_path, phase="starting", age_min=30, probe_timeout_s=120)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok
    assert "starting" in reason and "wedged" in reason


def test_liveness_leaves_a_normal_startup_alone(tmp_path):
    """A daemon 30 seconds into a 120-second probe is healthy; killing it would be the 47-SIGKILL
    false-positive class this file must not add to."""
    _write_beat(tmp_path, phase="starting", age_min=0.5, probe_timeout_s=120)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert ok, reason


def test_the_starting_budget_tracks_the_probe_bound_in_the_beat(tmp_path):
    """A hardcoded budget strands the coupling when the bound changes — the exact bug already
    recorded on the old hardcoded `55` for the generating stall threshold."""
    _write_beat(tmp_path, phase="starting", age_min=20, probe_timeout_s=3600)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert ok, "a 1h declared bound must not be judged against the 2m default"

    _write_beat(tmp_path, phase="starting", age_min=20, probe_timeout_s=60)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert not ok


def test_a_stale_starting_beat_gives_the_watchdog_a_pid_to_act_on(tmp_path):
    """`_kill_stale_daemon` reads the pid out of the heartbeat. The point of writing `starting`
    before the probe is that the pid it reads is the wedged process rather than a recycled one."""
    _write_beat(tmp_path, phase="starting", age_min=30, probe_timeout_s=120)
    beat = json.loads(_beat_path(tmp_path).read_text())
    assert isinstance(beat["pid"], int)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert not ok, "the kill path is only reached if liveness fails first"
