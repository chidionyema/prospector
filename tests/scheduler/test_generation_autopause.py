"""Generation must STOP itself when it is producing nothing.

Founder directive 2026-08-20, verbatim: "we eed it to autopause whe this happens", "we can
restat fron adnindashboard hwen we are able to", "so we dont get into this situation again".

WHAT WENT WRONG. The MiniMax token plan ran out and every call returned HTTP 429.
`errors.classify_exhaustion` grades a bare 429 TRANSIENT, so the adapter slept 5s/10s/20s/40s
and retried instead of benching the brain; `_moat_blind_reason` only skips a tick when EVERY
verdict brain carries a dead mark, so it never fired; and the scheduler generated again on the
next tick, and the one after. Measured on the container: 90.7% steal, four `claude -p` runtimes
spawned by the fallthrough, ZERO candidates produced, and 20 of 34 ops-console reads hitting a
30s ceiling. The founder could not open his own dashboard.

The CRITICAL `barren_streak` alert — "Generation DEAD: N consecutive barren ticks" — fired
correctly through all of it. It just did not stop anything. These tests grade the actuator that
alert never had, and the two properties the founder asked for by name: it arms itself, and it
does NOT clear itself.
"""
from __future__ import annotations

import json
import types

from prospector.ops import pause
from prospector.scheduler import run_scheduled as rs
from prospector.scheduler.alerts import CRITICAL, alerts_for_tick


def _cfg(tmp_path, **schedule):
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=dict(schedule),
        operator=["minimax"],
    )


def _barren_specs():
    """The specs the real alerter emits for a barren tick at the outage threshold."""
    tick = {"allowed": True, "dry_run": False, "result": {"dossiers": 0}}
    specs = alerts_for_tick(tick, consecutive_barren=3)
    assert any(s["key"] == "barren_streak" and s["severity"] == CRITICAL for s in specs), specs
    return specs


def _armed(cfg) -> bool:
    return pause.pause_path(cfg, "generation").exists()


# --------------------------------------------------------------------------- #
# The property the founder asked for: it stops itself.
# --------------------------------------------------------------------------- #

def test_a_barren_streak_arms_the_generation_pause(tmp_path):
    cfg = _cfg(tmp_path)
    assert not _armed(cfg)
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)
    assert _armed(cfg), "a declared generation outage must stop generation"


def test_the_pause_says_why_and_names_the_way_back(tmp_path):
    """An unexplained pause reads as a crash, and the founder has to be able to undo it."""
    cfg = _cfg(tmp_path)
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)
    body = json.loads(pause.pause_path(cfg, "generation").read_text())
    assert body["actor"] == "autopause:barren_streak"
    assert "4 consecutive barren generation ticks" in body["reason"]
    assert "/engine" in body["reason"], "the reason must name the resume control"
    assert body["keeps_running"] == "the consumer's drain, and re-vet"


def test_it_stops_generation_only_and_never_the_drain(tmp_path):
    """CLAUDE.md: generation must not outrun its drain. Stopping the drain too is the opposite
    fix — the backlog this outage created is exactly the work still needing to be finished."""
    cfg = _cfg(tmp_path)
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)
    assert not pause.pause_path(cfg, "all").exists()
    assert not pause.pause_path(cfg, "consumer").exists()


# --------------------------------------------------------------------------- #
# The property the founder asked for twice: it does NOT start itself.
# --------------------------------------------------------------------------- #

def test_it_does_not_self_clear(tmp_path):
    """"we can restat fron adnindashboard hwen we are able to". A barren streak means something
    outside the engine is spent; self-resuming puts the box straight back into the state that
    took the console down. Only `pause.disarm` clears it."""
    cfg = _cfg(tmp_path)
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)
    for _ in range(5):
        rs._autopause_generation_on_barren_streak(cfg, [], 0)   # healthy ticks
    assert _armed(cfg), "nothing but the operator may resume generation"
    pause.disarm(cfg, "generation", actor="founder", nonce="n1")
    assert not _armed(cfg), "the console's Start it again button must clear it"


def test_re_arming_keeps_the_first_reason(tmp_path):
    cfg = _cfg(tmp_path)
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)
    first = pause.pause_path(cfg, "generation").read_text()
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 40)
    assert pause.pause_path(cfg, "generation").read_text() == first


# --------------------------------------------------------------------------- #
# It must not fire on anything else, and it must not be able to kill the daemon.
# --------------------------------------------------------------------------- #

def test_a_single_barren_tick_does_not_pause(tmp_path):
    """One barren tick is WARNING `barren_generation`, not an outage. Pausing on it would stop
    the engine for a provider blip."""
    cfg = _cfg(tmp_path)
    specs = alerts_for_tick({"allowed": True, "result": {"dossiers": 0}}, consecutive_barren=0)
    assert [s["key"] for s in specs] == ["barren_generation"], specs
    rs._autopause_generation_on_barren_streak(cfg, specs, 0)
    assert not _armed(cfg)


def test_a_healthy_tick_does_not_pause(tmp_path):
    cfg = _cfg(tmp_path)
    rs._autopause_generation_on_barren_streak(cfg, [], 0)
    assert not _armed(cfg)


def test_the_switch_turns_it_off(tmp_path):
    """`schedule.autopause_on_barren_streak` — configurable, per the founder's standing rule that
    the engine is driven from the portal rather than from a source edit."""
    cfg = _cfg(tmp_path, autopause_on_barren_streak=False)
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)
    assert not _armed(cfg)


def test_it_defaults_to_on(tmp_path):
    assert "autopause_on_barren_streak" not in _cfg(tmp_path).schedule
    rs._autopause_generation_on_barren_streak(cfg := _cfg(tmp_path), _barren_specs(), 3)
    assert _armed(cfg)


def test_config_yaml_ships_it_on():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    assert cfg["schedule"]["autopause_on_barren_streak"] is True


def test_a_failing_pause_never_kills_the_daemon(tmp_path, monkeypatch):
    """An autopause that raises is worse than the outage it was written for."""
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pause, "arm", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)   # must not raise
    assert not _armed(cfg)


def test_a_failing_pause_says_so_at_CRITICAL(tmp_path, monkeypatch):
    """The one state worse than not stopping: the log says stopped and generation is running.

    Returning quietly here would hand the caller exactly the silence a healthy tick hands it
    (tools/audit_swallow_sites.py, tier 1), so the failure gets its own alert key and its own
    named flag. This test is what makes that path load-bearing rather than decorative.
    """
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pause, "arm", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))

    seen = []
    import prospector.scheduler.alerts as A
    monkeypatch.setattr(A, "emit_alert", lambda cfg, **kw: seen.append(kw) or {})

    rs._autopause_generation_on_barren_streak(cfg, _barren_specs(), 3)

    assert len(seen) == 1, "a stop that failed to arm must not pass silently: %r" % (seen,)
    alert = seen[0]
    assert alert["severity"] == A.CRITICAL, alert["severity"]
    assert alert["key"] == "autopause_failed", alert["key"]
    assert "read-only" in alert["autopause_failed"], alert["autopause_failed"]
    assert alert["barren_ticks"] == 4, alert["barren_ticks"]
    # On-call has to be able to act on it without reading this file.
    assert "STILL RUNNING" in alert["message"], alert["message"]
    assert "PAUSE_GENERATION" in alert["message"], alert["message"]


# --------------------------------------------------------------------------- #
# The wiring. The function above is only worth anything if the tick path calls it.
# --------------------------------------------------------------------------- #

def test_the_tick_path_actually_calls_it(tmp_path, monkeypatch):
    """Grades the wire, not the unit: three barren real ticks on disk, then one more barren tick
    through `_emit_tick_alerts`, and the pause must be armed at the end."""
    cfg = _cfg(tmp_path)
    ticks = tmp_path / "scheduler"
    ticks.mkdir(parents=True, exist_ok=True)
    with (ticks / "ticks.jsonl").open("w") as fh:
        for _ in range(4):        # 3 counted + the current one, which the counter drops
            fh.write(json.dumps({"allowed": True, "result": {"dossiers": 0}}) + "\n")

    monkeypatch.setattr(rs, "_emit_stranded_pass_alert", lambda *a, **k: None)
    import prospector.scheduler.alerts as A
    monkeypatch.setattr(A, "emit_alert", lambda *a, **k: None)
    monkeypatch.setattr(A, "resolve_alert", lambda *a, **k: None)
    monkeypatch.setattr(A, "reconcile_alert_txt", lambda *a, **k: None)

    rs._emit_tick_alerts(cfg, {"allowed": True, "result": {"dossiers": 0}})
    assert _armed(cfg), "the alert fired for months and stopped nothing; the wire is the fix"
