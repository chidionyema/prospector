"""The always-on daemon must generate when permitted, skip when guarded, and never die on a
single batch failure."""
from __future__ import annotations

import json
import types
from pathlib import Path

from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, cap=20.0, batch=3):
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        spend=types.SimpleNamespace(daily_cap_usd=cap, warn_at_usd=cap * 0.75),
        # decay off: these are GENERATION tests, and a real decay sweep would try to build a
        # brain from this SimpleNamespace. The decay rail has its own file, test_tick_decay.py.
        # Pack recovery off for the same reason: it shells out to recover_stranded_passes.py,
        # which needs a real catalogue. Left on, the child's sqlite error came back as a
        # `recovered` key on every tick result, so these assertions failed on any machine
        # without the operator's own store -- every clone, and CI.
        schedule={"batch_size": batch, "decay_per_tick": 0, "recover_per_tick": 0},
    )


def _ticks(tmp_path):
    p = Path(tmp_path) / "scheduler" / "ticks.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_tick_runs_when_permitted(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n) or {"dossiers": n})
    assert tick["allowed"]
    assert calls == [3]  # config batch_size
    assert tick["result"] == {"dossiers": 3}
    assert len(_ticks(tmp_path)) == 1


def test_candidates_override_batch_size(tmp_path):
    calls = []
    rs.run_tick(_cfg(tmp_path), candidates=7, generate_fn=lambda c, n: calls.append(n))
    assert calls == [7]


def test_tick_skips_when_paused(tmp_path):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "PAUSE").write_text("")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n))
    assert not tick["allowed"]
    assert calls == []
    assert "paused" in tick["reason"]


def test_dry_run_never_generates(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), dry_run=True, generate_fn=lambda c, n: calls.append(n))
    assert tick["allowed"]
    assert calls == []


def test_tick_survives_generation_error(tmp_path):
    def boom(c, n):
        raise RuntimeError("moat exhausted")

    tick = rs.run_tick(_cfg(tmp_path), generate_fn=boom)
    assert tick["error"] and "moat exhausted" in tick["error"]
    # Still logged, so the audit trail records the failure.
    assert len(_ticks(tmp_path)) == 1


def test_daemon_runs_max_cycles(tmp_path):
    calls = []
    n = rs.run_daemon(
        _cfg(tmp_path), interval=0,
        generate_fn=lambda c, k: calls.append(k),
        max_cycles=2, sleep_fn=lambda s: None,
    )
    assert n == 2
    assert calls == [3, 3]


def test_daemon_idles_when_paused(tmp_path):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "PAUSE").write_text("")
    calls = []
    n = rs.run_daemon(
        _cfg(tmp_path), interval=0,
        generate_fn=lambda c, k: calls.append(k),
        max_cycles=3, sleep_fn=lambda s: None,
    )
    assert n == 3
    assert calls == []  # paused every cycle, never generated


# ---------------------------------------------------------------------------
# Retry escalation. The retry used to be FLAT: every unproductive tick slept
# _RETRY_BACKOFF_S (300s), forever. Right for the blip it was written for, wrong for an
# outage — measured on 2026-08-01/02, when 131 of 144 real ticks failed
# `moat_preflight: no trusted moat brain answered: cursor_cli: ProviderExhaustedError`
# and the daemon re-probed every 5 minutes for two days at 24x its normal cadence.
# ---------------------------------------------------------------------------

def test_first_retry_is_still_fast():
    """The blip case must not regress — a single bad tick still retries in 5 minutes."""
    assert rs._retry_sleep_s(1, interval=7200) == rs._RETRY_BACKOFF_S


def test_retry_doubles_and_caps_at_the_normal_cadence():
    assert [rs._retry_sleep_s(n, interval=7200) for n in range(1, 7)] == \
        [300, 600, 1200, 2400, 4800, 7200]
    # Capped: a sustained outage settles to the ordinary heartbeat, never slower. A
    # recovered moat must not wait longer than a healthy daemon would to notice.
    assert rs._retry_sleep_s(50, interval=7200) == 7200
    # A short interval clamps immediately rather than exceeding it.
    assert rs._retry_sleep_s(3, interval=120) == 120


def test_two_day_outage_costs_probes_not_hundreds():
    """The quantified claim behind the change, as an assertion rather than a comment."""
    interval, day = 7200, 86400
    flat = day // rs._RETRY_BACKOFF_S              # what the old code did: 288 probes/day
    slept, escalated, n = 0, 0, 0
    while slept < day:
        n += 1
        slept += rs._retry_sleep_s(n, interval)
        escalated += 1
    assert flat == 288
    # Measured, not guessed: 300+600+1200+2400+4800 covers the first 9300s in 5 probes,
    # then it settles to the 2h cadence for the remaining 77100s — 11 more, 16 in all.
    assert escalated == 16
    assert escalated < flat / 15


def test_daemon_escalates_across_consecutive_unproductive_ticks(tmp_path):
    """Drives the REAL loop: the escalation must be wired in, not just computable."""
    def boom(c, k):
        raise RuntimeError("moat exhausted")

    slept = []
    rs.run_daemon(_cfg(tmp_path), interval=7200, generate_fn=boom,
                  max_cycles=4, sleep_fn=slept.append)
    # Sleeps happen after cycles 1..3 (the 4th breaks on max_cycles before sleeping), and
    # run_daemon sleeps in <=5s slices, so the sum is what the cycle actually waited.
    assert sum(slept) == 300 + 600 + 1200


def test_a_productive_tick_resets_the_escalation(tmp_path):
    """Recovery is immediate. Otherwise a healthy daemon inherits the outage's backoff.

    Must run a FIFTH cycle to mean anything. A shorter version of this test passed even with
    the reset deleted: the recovery cycle sleeps the full interval either way, so the reset
    is only observable on the NEXT failure. Caught by mutation, not by reading it.
    """
    seq = iter([False, False, True, False, False])   # fail, fail, succeed, fail, fail

    def flaky(c, k):
        if next(seq):
            return {"dossiers": 3, "passes": 1, "defers": 0, "provisional": 0}
        raise RuntimeError("moat exhausted")

    slept = []
    rs.run_daemon(_cfg(tmp_path), interval=7200, generate_fn=flaky,
                  max_cycles=5, sleep_fn=slept.append)
    # 300 (1st fail), 600 (2nd), 7200 (success -> full cadence), then 300 again because the
    # counter reset — NOT 1200, which is what a persisted count would give. The 5th cycle
    # breaks on max_cycles before sleeping.
    assert sum(slept) == 300 + 600 + 7200 + 300


# ── Code freshness ────────────────────────────────────────────────────────────────────────
# The daemon imports the engine in-process and loads config once, so a running daemon serves
# the code it STARTED with. On 2026-08-08 that left the pre-fix money rail (`bridge.py`) live
# for hours after the fix was committed. These pin the rail that ends that.


def test_fingerprint_tracks_content_not_mtime(tmp_path):
    """A touch must not force a re-exec: a re-exec mid-cadence costs a real grounded batch."""
    import os

    conf = tmp_path / "config.yaml"
    conf.write_text("schedule: {}\n")
    first = rs.code_fingerprint(conf)
    assert first

    os.utime(conf, (0, 0))  # mtime moves a decade; bytes do not
    assert rs.code_fingerprint(conf) == first

    conf.write_text("schedule: {batch_size: 4}\n")
    assert rs.code_fingerprint(conf) != first


def test_daemon_redeploys_at_the_tick_boundary_when_code_changes(tmp_path):
    """The swap happens BETWEEN ticks — the in-flight batch is never killed mid-run."""
    conf = tmp_path / "config.yaml"
    conf.write_text("schedule: {}\n")
    execs, ran = [], []

    def generate(cfg, n):
        ran.append(n)
        conf.write_text("schedule: {batch_size: 9}\n")  # a deploy lands while the tick runs
        return {"dossiers": n}

    cycles = rs.run_daemon(_cfg(tmp_path), interval=1, generate_fn=generate,
                           max_cycles=5, sleep_fn=lambda s: None, config_path=conf,
                           exec_fn=lambda path, argv: execs.append(argv))

    assert ran == [3], "the tick that was already running must complete first"
    assert cycles == 1, "and the loop must stop there rather than tick again on stale code"
    assert len(execs) == 1
    assert execs[0][1:3] == ["-m", rs._DAEMON_MODULE], "relaunch keeps the plist's -m form"


def test_daemon_does_not_redeploy_when_code_is_unchanged(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text("schedule: {}\n")
    execs = []
    cycles = rs.run_daemon(_cfg(tmp_path), interval=1,
                           generate_fn=lambda c, n: {"dossiers": n},
                           max_cycles=3, sleep_fn=lambda s: None, config_path=conf,
                           exec_fn=lambda path, argv: execs.append(argv))
    assert cycles == 3 and execs == []


def test_reload_is_on_by_default_and_can_be_switched_off(tmp_path):
    """Default ON — a rail that ships off is an inert rail — but the switch must really cut it."""
    assert rs._reload_on_code_change(_cfg(tmp_path)) is True

    conf = tmp_path / "config.yaml"
    conf.write_text("schedule: {}\n")
    cfg = _cfg(tmp_path)
    cfg.schedule["reload_on_code_change"] = False
    execs = []

    def generate(cfg_, n):
        conf.write_text("schedule: {batch_size: 9}\n")
        return {"dossiers": n}

    cycles = rs.run_daemon(cfg, interval=1, generate_fn=generate, max_cycles=3,
                           sleep_fn=lambda s: None, config_path=conf,
                           exec_fn=lambda path, argv: execs.append(argv))
    assert cycles == 3 and execs == []


def test_heartbeat_names_the_code_the_daemon_is_running(tmp_path):
    """So a monitor can compare loaded-vs-disk by EQUALITY, not by a start-time heuristic."""
    conf = tmp_path / "config.yaml"
    conf.write_text("schedule: {}\n")
    rs.run_daemon(_cfg(tmp_path), interval=1, generate_fn=lambda c, n: {"dossiers": n},
                  max_cycles=1, sleep_fn=lambda s: None, config_path=conf,
                  exec_fn=lambda path, argv: None)
    beat = json.loads((Path(tmp_path) / "scheduler" / "heartbeat.json").read_text())
    assert beat["code"] == rs.code_fingerprint(conf)[:12]
