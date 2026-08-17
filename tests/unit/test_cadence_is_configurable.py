"""The production cadence and the tick deadline are config, not a plist and an env var.

Until 2026-08-17 the two numbers that set how much this engine produces lived outside config:
the cadence was `--interval 7200` in com.prospector.scheduler.plist, and the tick deadline was
`PROSPECTOR_TICK_DEADLINE_S` read once at import. Neither was reachable from the ops console, so
"50 ideas every two hours" read as a property of the design rather than as two numbers somebody
picked. These tests pin that both are now `schedule.*` keys, that the old inputs still work as
fallbacks, and that the optional queue-following policy stays OFF unless it is asked for.
"""

import json
import types

import pytest

from prospector.scheduler import run_scheduled


def _cfg(**schedule):
    return types.SimpleNamespace(schedule=schedule)


# --------------------------------------------------------------------------- cadence


def test_interval_falls_back_to_argv_when_unset():
    """No config key: the plist argument still decides, exactly as before this change."""
    assert run_scheduled._interval_s(_cfg(), 7200) == 7200


def test_config_interval_beats_argv():
    assert run_scheduled._interval_s(_cfg(interval_s=600), 7200) == 600


@pytest.mark.parametrize("raw", [None, "", 0])
def test_blank_interval_is_the_argv_fallback(raw):
    """0/blank means 'unset', not 'spin as fast as possible'."""
    assert run_scheduled._interval_s(_cfg(interval_s=raw), 7200) == 7200


def test_interval_is_floored():
    """A cadence below one batch overlaps the previous batch: the daemon holds no lock."""
    assert run_scheduled._interval_s(_cfg(interval_s=1), 7200) == run_scheduled._MIN_INTERVAL_SECONDS


def test_junk_interval_falls_back_rather_than_raising():
    assert run_scheduled._interval_s(_cfg(interval_s="soon"), 7200) == 7200


def test_daemon_reads_the_interval_from_config_not_argv(monkeypatch, tmp_path):
    """End to end through `run_daemon`: the sleep the loop actually takes is the config one.

    The argv value is deliberately 100x the config value, so a passing assertion cannot be the
    fallback path succeeding by luck.
    """
    cfg = types.SimpleNamespace(schedule={"interval_s": 120}, store_dir=tmp_path)
    slept: list[int] = []
    monkeypatch.setattr(run_scheduled, "run_tick",
                        lambda *a, **k: {"allowed": True, "result": {"dossiers": 1}})
    monkeypatch.setattr(run_scheduled, "_write_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(run_scheduled, "code_fingerprint", lambda *a, **k: None)
    run_scheduled.run_daemon(cfg, interval=12000, max_cycles=2,
                             sleep_fn=lambda s: slept.append(s))
    assert sum(slept) == 120, f"slept {sum(slept)}s; expected the configured 120s"


# --------------------------------------------------------------------------- deadline


def test_tick_deadline_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("PROSPECTOR_TICK_DEADLINE_S", raising=False)
    assert run_scheduled._refresh_tick_deadline(_cfg()) == 10800


def test_config_sets_the_tick_deadline(monkeypatch):
    monkeypatch.delenv("PROSPECTOR_TICK_DEADLINE_S", raising=False)
    assert run_scheduled._refresh_tick_deadline(_cfg(tick_deadline_s=3600)) == 3600


def test_env_still_beats_config(monkeypatch):
    """An operator debugging one tick by hand is not overridden by the file."""
    monkeypatch.setenv("PROSPECTOR_TICK_DEADLINE_S", "900")
    assert run_scheduled._refresh_tick_deadline(_cfg(tick_deadline_s=3600)) == 900


def test_refresh_updates_the_module_constant_every_reader_uses(monkeypatch):
    """Seventeen call sites read the module name; the refresher is what makes them agree."""
    monkeypatch.delenv("PROSPECTOR_TICK_DEADLINE_S", raising=False)
    monkeypatch.setattr(run_scheduled, "_TICK_HARD_DEADLINE_S", 10800)
    run_scheduled._refresh_tick_deadline(_cfg(tick_deadline_s=1800))
    assert run_scheduled._TICK_HARD_DEADLINE_S == 1800


def test_an_unset_deadline_leaves_the_running_value_alone(monkeypatch):
    """`run_tick` refreshes this every tick, so a config with no key must not stamp the default
    over a value set for this process. 26 references across 8 test files set the constant
    directly to drive a sub-second deadline, and a deadline test whose deadline was quietly
    reset to three hours still passes while testing nothing."""
    monkeypatch.delenv("PROSPECTOR_TICK_DEADLINE_S", raising=False)
    monkeypatch.setattr(run_scheduled, "_TICK_HARD_DEADLINE_S", 0.1)
    assert run_scheduled._refresh_tick_deadline(_cfg()) == 0.1


def test_tick_deadline_is_floored(monkeypatch):
    """Shorter than a single vet is a crash loop under launchd KeepAlive, not a tight budget."""
    monkeypatch.delenv("PROSPECTOR_TICK_DEADLINE_S", raising=False)
    assert run_scheduled._refresh_tick_deadline(_cfg(tick_deadline_s=1)) == 60


# --------------------------------------------------------------------------- queue target


def test_queue_following_is_off_by_default():
    """The default must stay OFF: it makes the rate an observation instead of a setting."""
    assert run_scheduled._queue_target_depth(_cfg()) == 0


def test_queue_target_reads_config():
    assert run_scheduled._queue_target_depth(_cfg(queue_target_depth=200)) == 200


def test_junk_queue_target_is_off():
    assert run_scheduled._queue_target_depth(_cfg(queue_target_depth="lots")) == 0


def test_queue_full_tick_is_not_counted_unproductive():
    """A full queue is the system obeying the operator, so it must not inherit the outage
    backoff — which would also retry SOONER exactly when there is least reason to."""
    assert run_scheduled._tick_unproductive({"queue_full": True, "allowed": True}) is False


def test_moat_blind_still_counts_unproductive():
    """Guard against the queue_full early-return swallowing the cases above it."""
    assert run_scheduled._tick_unproductive({"moat_blind": True}) is True


# --------------------------------------------------------------------------- duration


def test_every_tick_records_its_duration(tmp_path, monkeypatch):
    """4559 rows carried no duration, so the cadence and the deadline could not be sized from
    data. Derived in `_append_tick` so all eight of `run_tick`'s returns get it."""
    cfg = types.SimpleNamespace(store_dir=tmp_path)
    monkeypatch.setattr(run_scheduled, "audit_run_id", lambda: "test")
    run_scheduled._append_tick(cfg, {"ts": "2026-08-17T00:00:00+00:00", "allowed": True})
    row = json.loads((tmp_path / "scheduler" / "ticks.jsonl").read_text().strip())
    assert "duration_s" in row and isinstance(row["duration_s"], float)


def test_a_tick_with_an_unparseable_timestamp_still_writes(tmp_path, monkeypatch):
    """The duration is a nice-to-have; losing the tick row would not be."""
    cfg = types.SimpleNamespace(store_dir=tmp_path)
    monkeypatch.setattr(run_scheduled, "audit_run_id", lambda: "test")
    run_scheduled._append_tick(cfg, {"ts": None, "allowed": True})
    row = json.loads((tmp_path / "scheduler" / "ticks.jsonl").read_text().strip())
    assert row["allowed"] is True and "duration_s" not in row


# --------------------------------------------------------------------------- the console

def test_every_new_knob_resolves_against_the_real_config():
    """A console knob whose path is not in config.yaml renders as a dead control.

    `_probe_all` asks the real YAML rewriter whether it can locate each path, and it skips any
    key whose current value is None — so a typo'd path does not fail loudly, it just quietly
    never appears. This asserts the value is really there to be edited.
    """
    from pathlib import Path

    import yaml

    from prospector.ops.console_api import KNOBS_BY_KEY

    root = Path(__file__).resolve().parents[2]
    raw = yaml.safe_load((root / "config.yaml").read_text())
    new = ["schedule.interval_s", "schedule.queue_target_depth", "schedule.tick_deadline_s",
           "schedule.producer_mode", "schedule.gen_budget_frac", "schedule.vet_budget_frac",
           "schedule.drain_budget_frac", "schedule.artifact_budget_frac",
           "schedule.artifact_budget_floor_s"]
    for key in new:
        assert key in KNOBS_BY_KEY, f"{key} is not registered in KNOBS"
        node = raw
        for part in key.split("."):
            assert isinstance(node, dict) and part in node, f"{key} is missing from config.yaml"
            node = node[part]
        assert node is not None, f"{key} is null in config.yaml, so the console will skip it"


def test_landing_the_keys_changed_no_behaviour():
    """The values written to config.yaml are exactly what the plist and the env default were."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    sched = yaml.safe_load((root / "config.yaml").read_text())["schedule"]
    assert sched["interval_s"] == 7200, "the plist passed --interval 7200"
    assert sched["tick_deadline_s"] == 10800, "PROSPECTOR_TICK_DEADLINE_S defaulted to 10800"
    assert sched["queue_target_depth"] == 0, "queue-following must ship OFF"
