"""E3's quiet-machine precondition must be checked per call, not once at startup.

E3 reports latencies, and a latency is only a claim about concurrency if the daemon was
not competing for the same machine-wide governor slots while it was timed. `run()` refuses
to start without `store/scheduler/PAUSE`, which proves the fence existed at t=0 and nothing
more. Observed on E1's run `bo2mosjog` (2026-08-08): the PAUSE file created at 00:25Z was
gone by 00:35Z with the run still in flight and the daemon (pid 66223) live. Nothing in this
repo unlinks it, so the deleter cannot be prevented from here — but it can be RECORDED, and
for a latency probe it must be.

Recorded, not aborted: an abort discards the levels already measured, and a partial sweep is
not comparable across levels anyway.

The CLI is stubbed, so this test spends nothing.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
E3_PATH = REPO / "tools" / "experiments" / "e3_concurrency_knee.py"


def _load_e3():
    spec = importlib.util.spec_from_file_location("_e3_fence_under_test", E3_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stub_cli(monkeypatch):
    def run_claude_cli(prompt, timeout=None, retries=0, **kw):
        return prompt.rsplit(": ", 1)[-1]           # echo the token: outcome == "ok"

    fake = types.ModuleType("prospector.claude_cli")
    fake._MAX_CLI = 4
    fake.run_claude_cli = run_claude_cli
    monkeypatch.setitem(sys.modules, "prospector.claude_cli", fake)


def _fence_after(mod, monkeypatch, n_quiet: int):
    """Make the pause file vanish after `n_quiet` reads (warm calls read it too)."""
    seen = {"i": 0}

    def _state():
        seen["i"] += 1
        live = seen["i"] <= n_quiet
        return {"PAUSE": live, "PAUSE_GENERATION": False}

    monkeypatch.setattr(mod, "_quiet_state", _state)


# --------------------------------------------------------------------------- the report

def test_a_fully_fenced_run_is_reported_as_held():
    e3 = _load_e3()
    rep = e3._quiet_report([{"quiet": True}] * 5)
    assert rep["held"] is True
    assert (rep["calls_observed"], rep["calls_unfenced"]) == (5, 0)
    assert rep["lost_at_call"] is None and rep["note"] == ""


def test_the_report_names_the_call_where_the_fence_was_lost():
    e3 = _load_e3()
    rep = e3._quiet_report([{"quiet": True}, {"quiet": True},
                            {"quiet": False}, {"quiet": False}])
    assert rep["held"] is False
    assert rep["lost_at_call"] == 3, "1-indexed, so it reads as 'call 3 of 4'"
    assert rep["calls_unfenced"] == 2
    assert "must not be quoted" in rep["note"], (
        "a contaminated run has to say so, or the table gets quoted anyway")


def test_an_unstamped_receipt_is_not_reported_as_held():
    """Receipts written before the per-call fence can only speak for the startup check.

    Defaulting them to `held: True` would launder a startup-only guarantee into a
    per-call one — silently, and for exactly the historic runs whose numbers are
    already in the register.
    """
    e3 = _load_e3()
    rep = e3._quiet_report([{"i": 0, "latency_s": 1.0}, {"i": 1, "latency_s": 1.1}])
    assert rep["held"] is False
    assert rep["calls_observed"] == 0 and rep["lost_at_call"] is None
    assert "predates the per-call fence" in rep["note"]


def test_no_calls_at_all_is_not_held():
    assert _load_e3()._quiet_report([])["held"] is False


# --------------------------------------------------------------------------- the stamp

def test_every_measured_call_carries_its_own_fence_reading(monkeypatch):
    e3 = _load_e3()
    _stub_cli(monkeypatch)
    _fence_after(e3, monkeypatch, n_quiet=99)
    res = e3._worker(n=1, calls=3, warm_waves=1)

    assert [c["quiet"] for c in res["calls"]] == [True, True, True]
    assert e3._quiet_report(res["calls"])["held"] is True


def test_a_fence_lost_mid_sweep_is_caught_where_startup_alone_would_pass(monkeypatch):
    """The regression itself: quiet at t=0, gone by the third measured call.

    A startup-only check sees a pause file and reports four clean latencies. Serialised
    at n=1, the reads are: 1 warm call, then measured calls 1..4.
    """
    e3 = _load_e3()
    _stub_cli(monkeypatch)
    _fence_after(e3, monkeypatch, n_quiet=3)        # warm + measured 1,2 -> then gone
    res = e3._worker(n=1, calls=4, warm_waves=1)

    assert [c["quiet"] for c in res["calls"]] == [True, True, False, False]
    fence = e3._quiet_report(res["calls"])
    assert fence["held"] is False and fence["lost_at_call"] == 3
    assert res["aborted"] is None, "a lost fence is recorded, never an abort"
    assert len(res["calls"]) == 4, "and the measured calls are all still reported"
