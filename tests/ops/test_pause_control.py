"""R17 — three pause scopes, and each one stops the role it claims to stop.

THE PROBE, from the programme: *arm each → the right role stops, the other keeps running.*

So these tests do not assert against a table of prose. Each one arms a real file in a real store
and then calls **the engine's own readers** — `guard.is_paused` (both roles),
`run_scheduled._generation_suppressed` (the producer's half-stop) and `consumer._blocked_reason`
(the consumer's) — because a control panel that describes a fence it does not share code with is
a doc, and docs drift. `PAUSE_CONSUMER` had NO hits in either surface before this: it was a real
rail with no way to arm it and no screen that admitted it existed.
"""
from __future__ import annotations

import json
import types

import pytest

from prospector import consumer as C
from prospector.ops import pause as P
from prospector.ops import readmodel as R
from prospector.scheduler import guard as G
from prospector.scheduler import run_scheduled as RS


def _cfg(tmp_path):
    return types.SimpleNamespace(store_dir=tmp_path, consumer={})


def _generation_stopped(cfg, monkeypatch) -> str:
    """`_generation_suppressed`, with the three NON-pause triggers silenced.

    The money brake, the grounding gate and the backlog cap can each suppress generation for
    their own good reasons — and the grounding gate runs a LIVE search. Stubbing them is what
    makes the remaining signal attributable to the pause file (memory:
    `attribute-at-the-actuators-grain`).
    """
    monkeypatch.setattr(RS, "_subscription_soft_cap_reason", lambda cfg, d=None: "")
    monkeypatch.setattr(RS, "_grounding_degraded_reason", lambda cfg: "")
    monkeypatch.setattr(RS, "_backlog_brake_reason", lambda *a, **k: "", raising=False)
    return RS._generation_suppressed(cfg)


def _guard(cfg) -> G.SchedulerGuard:
    """The guard is constructed with an explicit cap, not from cfg — `guard.py:111`. 0.0 disables
    the spend rail, which is what leaves `is_paused()` reading the PAUSE file and nothing else."""
    return G.SchedulerGuard(cfg.store_dir, 0.0)


def _consumer_stopped(cfg) -> str:
    return C._blocked_reason(cfg) or ""


# --------------------------------------------------------------------------- #
# The three scopes, each against the reader that decides
# --------------------------------------------------------------------------- #
def test_pause_consumer_stops_the_consumer_and_leaves_generation_running(tmp_path, monkeypatch):
    """The half-stop that had no surface. Arming it must NOT touch the producer — the queue is
    supposed to keep filling, which is exactly why the queue-depth panel sits next to it."""
    cfg = _cfg(tmp_path)
    P.arm(cfg, "consumer", actor="test", reason="looking at the moat")

    assert "PAUSE_CONSUMER" in _consumer_stopped(cfg)
    assert _generation_stopped(cfg, monkeypatch) == ""
    assert _guard(cfg).is_paused() is False


def test_pause_generation_stops_the_producer_and_leaves_the_drain_running(tmp_path, monkeypatch):
    """The producer's half-stop. The drain must survive it: CLAUDE.md — generation must not
    outrun its own drain, and the drain must never be collateral damage of a decision to skip
    generation."""
    cfg = _cfg(tmp_path)
    P.arm(cfg, "generation", actor="test")

    assert "generation paused" in _generation_stopped(cfg, monkeypatch)
    assert _consumer_stopped(cfg) == ""
    assert _guard(cfg).is_paused() is False


def test_pause_stops_both_roles(tmp_path, monkeypatch):
    """The liability rail. A rail with exceptions is not a rail, so this one is read by the
    guard — which BOTH loops consult — rather than by either loop's own check."""
    cfg = _cfg(tmp_path)
    P.arm(cfg, "all", actor="test", reason="incident")

    assert _guard(cfg).is_paused() is True
    assert "paused" in _consumer_stopped(cfg).lower()


def test_nothing_armed_stops_nothing(tmp_path, monkeypatch):
    """The before-state. Without this the three tests above would pass on a store where every
    reader refuses for an unrelated reason — a suite that proves the rails work by proving
    nothing works (memory: `prove-the-probe-fires-on-the-before-state`)."""
    cfg = _cfg(tmp_path)

    assert _consumer_stopped(cfg) == ""
    assert _generation_stopped(cfg, monkeypatch) == ""
    assert _guard(cfg).is_paused() is False


# --------------------------------------------------------------------------- #
# The writer's own fences
# --------------------------------------------------------------------------- #
def test_an_unknown_scope_is_refused_by_the_writer(tmp_path):
    """The fence is in the WRITER, not in the keyboard (§6). A typo'd scope must not produce a
    file no reader consults — a control that reports success and stops nothing."""
    with pytest.raises(P.UnknownScope):
        P.arm(_cfg(tmp_path), "producer", actor="test")
    assert list((tmp_path / "scheduler").glob("PAUSE*")) == []


def test_re_arming_keeps_the_first_armer(tmp_path):
    """Who stopped the engine, and when, is the whole value of the body. A refresh loop that
    re-posted the intent would overwrite it with its own timestamp."""
    cfg = _cfg(tmp_path)
    first = P.arm(cfg, "consumer", actor="chidi", reason="the real reason")
    body = json.loads(P.pause_path(cfg, "consumer").read_text())

    again = P.arm(cfg, "consumer", actor="a-refresh-loop", reason="")

    assert first["changed"] is True and again["changed"] is False
    assert json.loads(P.pause_path(cfg, "consumer").read_text()) == body
    assert body["actor"] == "chidi"


def test_a_replayed_nonce_does_not_act_twice(tmp_path):
    """Idempotent by STORED nonce, not by a TTL cache (memory:
    `idempotency-keys-expire-they-are-not-dedup`). A double-tap on a phone keyboard is the case."""
    cfg = _cfg(tmp_path)
    P.arm(cfg, "consumer", actor="phone", nonce="n-1")
    P.disarm(cfg, "consumer", actor="phone")           # someone clears it in between
    replay = P.arm(cfg, "consumer", actor="phone", nonce="n-1")

    assert replay.get("replayed") is True
    assert not P.pause_path(cfg, "consumer").exists(), "the replay re-armed a cleared pause"


def test_disarm_clears_it_and_both_actions_leave_a_receipt(tmp_path):
    """One append-only intent log, shared by both surfaces (§4.1): a pause armed from the phone
    is inspectable at the desk."""
    cfg = _cfg(tmp_path)
    P.arm(cfg, "consumer", actor="phone", reason="why")
    out = P.disarm(cfg, "consumer", actor="desk")

    assert out["changed"] is True and not P.pause_path(cfg, "consumer").exists()
    receipts = [json.loads(ln) for ln in P.intents_path(cfg).read_text().splitlines() if ln.strip()]
    assert [r["actuator"] for r in receipts] == ["engine.pause.arm", "engine.pause.disarm"]
    assert [r["actor"] for r in receipts] == ["phone", "desk"]


def test_disarming_something_that_was_not_armed_is_a_no_op_receipt(tmp_path):
    """`changed: False` rather than an error. An operator clearing a pause that someone else
    already cleared has got what they wanted."""
    out = P.disarm(_cfg(tmp_path), "all", actor="test")
    assert out["changed"] is False and out["armed"] is False


def test_a_hand_touched_pause_file_behaves_identically(tmp_path, monkeypatch):
    """Every runbook says `touch store/scheduler/PAUSE`. The control writes a JSON body for
    provenance, but the READERS decide on existence alone — so a hand-armed pause must be just as
    effective, and the view must render it with a null actor rather than hiding it."""
    cfg = _cfg(tmp_path)
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / "PAUSE_CONSUMER").write_text("")

    assert "PAUSE_CONSUMER" in _consumer_stopped(cfg)
    scope = next(s for s in R.pause_view(cfg)["scopes"] if s["scope"] == "consumer")
    assert scope["armed"] is True and scope["actor"] is None


# --------------------------------------------------------------------------- #
# The table itself
# --------------------------------------------------------------------------- #
def test_every_scope_names_a_reader_that_actually_exists(tmp_path):
    """The panel's "what this stops" text is only trustworthy if the function it credits is real.
    This resolves each `module::function` string, so deleting or renaming a reader reddens the
    suite instead of leaving a screen quietly describing a fence that no longer exists."""
    import importlib

    for scope, meta in R.PAUSE_SCOPES.items():
        module_path, _, func = meta["reader"].partition("::")
        mod = importlib.import_module(
            "prospector." + module_path.removesuffix(".py").replace("/", "."))
        target = mod
        for part in func.split("."):
            target = getattr(target, part, None) or getattr(
                getattr(mod, part.split(".")[0], mod), part, None)
            assert target is not None, f"{scope}: {meta['reader']} does not resolve"


def test_the_view_reports_who_armed_it(tmp_path):
    cfg = _cfg(tmp_path)
    P.arm(cfg, "generation", actor="chidi", reason="storefront deploy")
    scope = next(s for s in R.pause_view(cfg)["scopes"] if s["scope"] == "generation")

    assert scope["armed"] is True
    assert scope["actor"] == "chidi" and scope["reason"] == "storefront deploy"
    assert R.pause_view(cfg)["any_armed"] is True
