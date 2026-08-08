"""The daemon must not mint work the moat cannot finish.

2026-08-06, live: `store/scheduler/ALERT.txt` at 09:23Z read `15/15 verdicts ruled by FALLBACK
brain`, while a `vet --resume` drain had been running two hours to clear exactly that backlog.
`store/prospector.db` moved 229 -> 230 provisional rows across the drain — net FLAT. Generation
had no moat-health precondition at all (`run_scheduled.py` called `gen()` unconditionally), so
the daemon manufactured provisional passes as fast as the drain retired them, both processes
competing for the same subscription CLI slots.

A provisional pass is not a cheap answer, it is a DOUBLE-CHARGED one: it can never publish
(CLAUDE.md, "Publish only on PASS"), so it costs a full verdict run now AND a full re-vet later
to reach the same conclusion a DEFER reaches once. Skipping the tick is strictly cheaper than
running it, and the backlog it declines to create is the backlog the drain is trying to clear.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import prospector.health as H
from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, operator=("claude_cli",)):
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule={"batch_size": 3},
        operator=list(operator),
    )


def _ticks(tmp_path):
    p = Path(tmp_path) / "scheduler" / "ticks.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def test_tick_is_skipped_when_every_trusted_brain_is_dead(tmp_path):
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n))

    assert calls == [], "generation must not run into a blind moat"
    assert tick["moat_blind"] is True
    assert "moat blind" in tick["reason"]
    assert "claude_cli" in tick["reason"], "the reason must name the brain and its window"
    assert len(_ticks(tmp_path)) == 1, "a skipped tick is still an audited tick"


def test_one_live_trusted_brain_is_enough_to_run(tmp_path):
    """The guard is a floor, not a fair-weather switch: a degraded moat still works."""
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path, operator=("claude_cli", "claude")),
                       generate_fn=lambda c, n: calls.append(n))

    assert calls == [3]
    assert not tick.get("moat_blind")


def test_a_live_untrusted_brain_now_unblinds_generation(tmp_path):
    """REVERSED 2026-08-08 by founder directive ("veridt should also have fallback").

    Until 2026-08-08 this asserted the opposite: minimax being up did NOT unblind the tick,
    because a provisional ruling costs a verdict run now AND a re-vet later (2x) to reach the
    answer a DEFER reaches once (1x). That arithmetic is unchanged and still true — see
    config.yaml — but the founder accepted the 2x cost, because a DEFER stops the line
    entirely: on 2026-08-08 claude_cli hit a monthly spend limit and the daemon produced
    nothing rulable for the duration.

    This test is the one that makes the re-add REACH the daemon. Had the preflight stayed
    trusted-only, `operator: [claude_cli, minimax]` would have been inert in exactly the
    situation the fallback exists for — claude_cli dead — and the config change would have
    looked shipped while changing nothing.
    """
    H.get_health().mark_exhausted("claude_cli", 3600.0, error="usage limit")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path, operator=("claude_cli", "minimax")),
                       generate_fn=lambda c, n: calls.append(n))

    assert calls == [3], "a live provisional tail can rule, so the tick has work worth doing"
    assert not tick.get("moat_blind")


def test_generation_is_still_blind_when_the_provisional_tail_dies_too(tmp_path):
    """The converse, and the reason `trusted_only=False` is not simply "never blind".

    A preflight that unblinded on a configured-but-dead tail would be worse than none: it
    would mint candidates no brain at all can rule.
    """
    h = H.get_health()
    h.mark_exhausted("claude_cli", 3600.0, error="usage limit")
    h.mark_exhausted("minimax", 3600.0, error="usage limit")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path, operator=("claude_cli", "minimax")),
                       generate_fn=lambda c, n: calls.append(n))

    assert calls == []
    assert tick["moat_blind"] is True
    assert "minimax" in tick["reason"], "the reason must name every dead brain, not just the head"


def test_healthy_moat_runs_normally(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n))
    assert calls == [3]
    assert not tick.get("moat_blind")
    assert tick["allowed"]


def test_the_preflight_does_not_burn_the_half_open_probe(tmp_path):
    """Bookkeeping must read the RAW mark (`dead_until`), never `is_dead` — the latter CLAIMS
    the one probe slot, so a status check would spend the recovery attempt that a real verdict
    call should get, and re-arm the backoff. Self-healing would then depend on nobody looking."""
    h = H.get_health()
    h.mark_exhausted("claude_cli", 3600.0, error="usage limit")
    # Advance past the probe window by rewinding the mark rather than the clock.
    data = json.loads(Path(h._path).read_text())
    data["claude_cli"]["probe_at"] = 0
    Path(h._path).write_text(json.dumps(data))

    rs._moat_blind_reason(_cfg(tmp_path))
    rs._moat_blind_reason(_cfg(tmp_path))

    assert h.is_dead("claude_cli") is False, "the probe must still be available to a real call"


def test_moat_blind_counts_as_unproductive(tmp_path):
    """So the daemon's escalating retry (5m/10m/20m) applies instead of hammering a dead moat
    every full interval."""
    assert rs._tick_unproductive({"moat_blind": True, "allowed": False})
