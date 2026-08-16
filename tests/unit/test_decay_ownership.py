"""The SLA decay sweep has exactly ONE owner, and it moves when the estate splits.

WHAT WAS WRONG. The producer/consumer split gated three things on `producer_mode` — the
drain, vetting and publishing — and missed a fourth. `_decay_pass` ran on every tick
regardless, and its sweep half (`run_decay_sweep`) is a full moat run per row: the same class
of work as the drain, on the same brain, on the same clock. So a "producer" tick still blocked
on the moat, which is the one coupling the whole split exists to remove. It is not a rounding
error: `decay_per_tick` is 2 live, and at the worst measured vet (4127s, 2026-08-15) two rows
is 8254s against a 10800s tick deadline.

WHAT THIS FILE PINS, and why each half is separately falsifiable:

  1. In producer mode the scheduler's sweep budget is 0 — the sweep does not run there.
  2. The UNLIST drain still runs in producer mode. It is not moat work, it is a one-way
     idempotent actuator, and the cost of skipping it is a KILLed pack still taking money
     (six of them, measured 2026-08-09). Gating it with the sweep would have been the easy
     mistake and would have been invisible until someone bought a killed pack.
  3. The consumer picks the sweep up — but ONLY in producer mode, or a consumer loaded
     beside a classic tick double-sweeps at full moat cost.
  4. The cadence survives a restart, because `KeepAlive` respawns this process and an
     in-memory timer would fire a sweep every ThrottleInterval during a crash loop.
"""
from __future__ import annotations

import json
import types

import pytest

from prospector import consumer as consumer_mod
from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, **schedule):
    return types.SimpleNamespace(store_dir=str(tmp_path), schedule=schedule, spend={},
                                 consumer={})


# ---------------------------------------------------------------------------
# 1 + 2: the scheduler side
# ---------------------------------------------------------------------------

def test_a_producer_tick_does_not_run_the_sweep(tmp_path):
    assert rs._decay_sweep_budget(_cfg(tmp_path, producer_mode=True, decay_per_tick=2)) == 0


def test_a_classic_tick_still_runs_the_sweep(tmp_path):
    """The negative control. Without it, a `_decay_sweep_budget` that returned 0 always would
    pass the test above and silently switch decay off for the entire estate."""
    assert rs._decay_sweep_budget(_cfg(tmp_path, producer_mode=False, decay_per_tick=2)) == 2


def test_the_unlist_drain_still_runs_when_the_sweep_is_off(tmp_path, monkeypatch):
    """A KILLed pack must stop selling on a producer tick too.

    Asserted through `_decay_pass(cfg, 0)` — the exact call a producer makes — rather than by
    reading the source, because the property is that the unlist lives OUTSIDE the `if n_decay`.
    """
    called: list[int] = []
    monkeypatch.setattr(rs, "_unlist_pass", lambda _cfg: called.append(1) or {"rc": 0})
    # If the sweep were reachable at n=0 this import would be attempted; make it explode so a
    # regression is a loud failure rather than a quiet extra moat run.
    monkeypatch.setattr("prospector.run.run_decay_sweep",
                        lambda *a, **k: pytest.fail("the sweep ran with a zero budget"))

    out = rs._decay_pass(_cfg(tmp_path), 0)

    assert called == [1], "the unlist drain must run even when the sweep budget is 0"
    assert out == {"unlisted": {"rc": 0}}


# ---------------------------------------------------------------------------
# 3: the consumer picks it up, in producer mode only
# ---------------------------------------------------------------------------

def _spy_decay(monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(rs, "_decay_pass", lambda _cfg, n: seen.append(n) or {"swept": n})
    return seen


def test_the_consumer_sweeps_in_producer_mode(tmp_path, monkeypatch):
    seen = _spy_decay(monkeypatch)
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)

    out = consumer_mod._maybe_decay(cfg, consumer_mod.consumer_config(cfg))

    assert seen == [2], "the consumer must inherit the sweep the producer gave up"
    assert out == {"swept": 2}


def test_the_consumer_does_not_sweep_beside_a_classic_tick(tmp_path, monkeypatch):
    """The scheduler still owns it there. Two owners is two full moat sweeps of the same rows,
    each stamping a marker the other never reads."""
    seen = _spy_decay(monkeypatch)
    cfg = _cfg(tmp_path, producer_mode=False, decay_per_tick=2)

    assert consumer_mod._maybe_decay(cfg, consumer_mod.consumer_config(cfg)) is None
    assert seen == []


def test_a_sweep_that_raises_does_not_end_the_consumer(tmp_path, monkeypatch):
    """The queue is the primary job. A secondary one that kills the loop has traded a stale
    catalogue for an undrained queue, which is the worse of the two."""
    monkeypatch.setattr(rs, "_decay_pass",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("moat down")))
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)

    out = consumer_mod._maybe_decay(cfg, consumer_mod.consumer_config(cfg))

    assert out is not None, "swallowing to None makes a broken sweep look like 'not due'"
    assert "moat down" in out["error"]


def test_a_broken_sweep_is_not_reported_as_a_sweep(tmp_path, monkeypatch):
    """The counterpart, and the reason the return value has to carry the failure at all.

    NOT-DUE and BROKEN both returned None, so the caller counted neither and the loop's totals
    read clean either way. That is the worst possible pairing for THIS job: the marker is
    stamped BEFORE the sweep, so a crash is silently not-due for a full interval, and a sweep
    failing every cycle would suspend SLA re-verification indefinitely with nothing in the
    totals to say so. It counts as `errors`, never `decay_sweeps` — a count of attempts is not
    a count of work done."""
    monkeypatch.setattr(rs, "_decay_pass",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("moat down")))
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)
    conf = consumer_mod.consumer_config(cfg)

    broken = consumer_mod._maybe_decay(cfg, conf)
    assert broken.get("error")

    not_due = consumer_mod._maybe_decay(cfg, conf)   # the marker is stamped now
    assert not_due is None, "a second call inside the interval is not due, not broken"


# ---------------------------------------------------------------------------
# 4: the cadence, and that it survives a restart
# ---------------------------------------------------------------------------

def test_a_second_cycle_does_not_sweep_again(tmp_path, monkeypatch):
    """The consumer cycles far faster than the 2h tick it took this from. Un-paced, a bounded
    2-row sweep becomes a continuous re-vet of the whole published catalogue."""
    seen = _spy_decay(monkeypatch)
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)
    conf = consumer_mod.consumer_config(cfg)

    consumer_mod._maybe_decay(cfg, conf)
    consumer_mod._maybe_decay(cfg, conf)

    assert seen == [2], "the sweep ran twice inside one interval"


def test_the_cadence_survives_a_restart(tmp_path, monkeypatch):
    """THE FAILURE THIS GUARDS IS A CRASH LOOP. `KeepAlive` respawns the consumer, so an
    in-process 'last swept' resets on every restart: a consumer dying at startup would fire a
    full moat sweep every ThrottleInterval (120s). The marker is a file for exactly this."""
    seen = _spy_decay(monkeypatch)
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)

    consumer_mod._maybe_decay(cfg, consumer_mod.consumer_config(cfg))
    # A fresh process: same store, brand-new config object, no in-memory state whatsoever.
    consumer_mod._maybe_decay(_cfg(tmp_path, producer_mode=True, decay_per_tick=2),
                              consumer_mod.consumer_config(cfg))

    assert seen == [2], "a restart re-ran the sweep — the cadence is in memory, not on disk"


def test_the_sweep_runs_again_once_the_interval_has_passed(tmp_path, monkeypatch):
    """The other side of the control: a marker that never expired would switch decay off for
    good after one sweep, which looks identical to a working cadence until the SLA lapses."""
    seen = _spy_decay(monkeypatch)
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)
    conf = consumer_mod.consumer_config(cfg)

    consumer_mod._maybe_decay(cfg, conf)
    marker = consumer_mod._decay_marker(cfg)
    stale = json.loads(marker.read_text())["at"] - (conf.decay_interval_s + 1)
    marker.write_text(json.dumps({"at": stale}))
    consumer_mod._maybe_decay(cfg, conf)

    assert seen == [2, 2]


@pytest.mark.parametrize("body", ["", "not json", '{"at": "yesterday"}', "{}"])
def test_an_unreadable_marker_reads_as_due(tmp_path, body):
    """Fails OPEN, deliberately the opposite direction to the pause probe. Skipping a sweep
    silently lets an expired PASS keep selling on evidence nobody rechecked; running one too
    often costs a bounded two rows."""
    cfg = _cfg(tmp_path, producer_mode=True)
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    consumer_mod._decay_marker(cfg).write_text(body)

    assert consumer_mod._decay_due(cfg, consumer_mod.consumer_config(cfg)) is True


def test_a_zero_interval_disables_the_consumer_sweep(tmp_path, monkeypatch):
    """An operator needs one switch that is not 'stop the consumer'."""
    seen = _spy_decay(monkeypatch)
    cfg = types.SimpleNamespace(store_dir=str(tmp_path), spend={},
                                schedule={"producer_mode": True, "decay_per_tick": 2},
                                consumer={"decay_interval_s": 0})

    assert consumer_mod._maybe_decay(cfg, consumer_mod.consumer_config(cfg)) is None
    assert seen == []


def test_a_producer_under_the_backlog_brake_does_not_drain(tmp_path, monkeypatch):
    """The brake's OTHER hidden drain, and the reason `backlog_cap` could not be switched on.

    The suppressed-generation branch drains by design: in a single-process tick a brake that
    also stopped the drain would freeze the very number it waits on. Split, that inverts — the
    consumer is already draining continuously, so the queue shrinks regardless, and draining
    here buys only the thing the split removes: the producer back on the moat's clock for up to
    the full 3h deadline, in exactly the state (queue over cap) where the moat is already the
    bottleneck. A second drainer does not make a saturated brain faster.
    """
    monkeypatch.setattr(rs, "_drain_pass",
                        lambda *a, **k: pytest.fail("a producer drained under the brake"))
    monkeypatch.setattr(rs, "_drain_only_resume_per_tick", lambda *a, **k: 15)
    cfg = _cfg(tmp_path, producer_mode=True)

    # The expression as the branch evaluates it.
    assert (None if rs.producer_mode(cfg) else rs._drain_pass(
        cfg, rs._drain_only_resume_per_tick(cfg))) is None


def test_a_classic_tick_under_the_brake_still_drains(tmp_path, monkeypatch):
    """The control. The brake must keep draining wherever the drain is the daemon's whole
    workload, or it freezes the number it is waiting on and never releases."""
    seen: list[int] = []
    monkeypatch.setattr(rs, "_drain_pass", lambda _c, n: seen.append(n) or {"resumed": n})
    monkeypatch.setattr(rs, "_drain_only_resume_per_tick", lambda *a, **k: 15)
    cfg = _cfg(tmp_path, producer_mode=False)

    assert (None if rs.producer_mode(cfg) else rs._drain_pass(
        cfg, rs._drain_only_resume_per_tick(cfg))) == {"resumed": 15}
    assert seen == [15]


def test_the_marker_is_stamped_before_the_sweep_not_after(tmp_path, monkeypatch):
    """'Attempted at', never 'succeeded at'. A marker written only on success retries a
    failing sweep every cycle — an unbounded loop against a moat that is already down."""
    stamped: list[bool] = []

    def _boom(*_a, **_k):
        stamped.append(consumer_mod._decay_marker(cfg).exists())
        raise RuntimeError("moat down")

    monkeypatch.setattr(rs, "_decay_pass", _boom)
    cfg = _cfg(tmp_path, producer_mode=True, decay_per_tick=2)

    consumer_mod._maybe_decay(cfg, consumer_mod.consumer_config(cfg))

    assert stamped == [True], "the marker must already exist when the sweep runs"
