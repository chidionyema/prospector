"""An unreadable canary state file must not read as "there is no canary".

MEASURED 2026-08-15. `CanaryRunner._load_state` returned `None` both when the state file was
absent and when it was corrupt, and every caller branches on that single `None`:

  * `evaluate()`  -> {"verdict": "no_experiment"}
  * `status()`    -> {"status": "no_experiment"}
  * `revert()`    -> False, and `mod_log.rollback` is never called
  * `record_run()`-> the sample is silently dropped

So a torn write during a live experiment leaves a self-modification in production, reports
that nothing is running, and never rolls back. The load still fails safe — a corrupt file is
never turned into a fabricated state — but the two Nones are now distinguishable.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from prospector.canary import CanaryRunner
from prospector.metrics_store import MetricsStore
from prospector.self_modify import SelfModificationLog


def _runner(tmp_path: Path) -> CanaryRunner:
    return CanaryRunner(tmp_path / "canary",
                        MetricsStore(tmp_path / "metrics.db"),
                        SelfModificationLog(tmp_path / "mods.db"))


def test_no_state_file_still_reports_no_experiment(tmp_path):
    runner = _runner(tmp_path)
    assert runner.status()["status"] == "no_experiment"
    assert runner.evaluate()["verdict"] == "no_experiment"


def test_a_corrupt_state_file_is_reported_as_unreadable_not_as_no_experiment(tmp_path, caplog):
    runner = _runner(tmp_path)
    runner.start_canary("change-1")
    runner._state_file.write_text("{ not json", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="prospector.canary"):
        status = runner.status()
        verdict = runner.evaluate()

    assert status["status"] == "state_unreadable"
    assert status["status"] != "no_experiment"
    assert verdict["verdict"] == "state_unreadable"
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_a_state_file_with_the_wrong_shape_is_also_unreadable(tmp_path):
    """`CanaryState(**data)` raises TypeError on unknown/missing keys — same class of lie."""
    runner = _runner(tmp_path)
    runner.start_canary("change-1")
    runner._state_file.write_text(json.dumps({"unexpected": 1}), encoding="utf-8")

    assert runner.status()["status"] == "state_unreadable"


def test_a_live_experiment_still_reports_itself(tmp_path):
    runner = _runner(tmp_path)
    runner.start_canary("change-1")
    assert runner.status()["status"] == "running"
