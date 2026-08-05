"""Tests for A/B canary mode."""

import tempfile
from pathlib import Path

from prospector.metrics_store import MetricsStore
from prospector.self_modify import SelfModificationLog
from prospector.canary import CanaryRunner, CanaryVerdict


def test_canary_start_and_status():
    """Canary should start and report status."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = MetricsStore(tmp_path / "metrics.db")
        mod_log = SelfModificationLog(tmp_path / "mods.db")

        runner = CanaryRunner(tmp_path / "canary", store, mod_log)
        cid = mod_log.record("gen", "prompt", "v1", "v2", "test", "test_canary")

        state = runner.start_canary(cid)
        assert state.status == "running"
        assert state.change_id == cid

        status = runner.status()
        assert status["status"] == "running"


def test_canary_extends_with_insufficient_data():
    """Canary should extend when not enough runs collected."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = MetricsStore(tmp_path / "metrics.db")
        mod_log = SelfModificationLog(tmp_path / "mods.db")

        runner = CanaryRunner(tmp_path / "canary", store, mod_log, min_canary_runs=50)
        cid = mod_log.record("gen", "x", "old", "new")
        runner.start_canary(cid)

        # Record only 5 runs of each
        for i in range(5):
            runner.record_run(is_canary=True, yield_rate=0.6, health_score=0.7,
                             diversity_score=0.5, candidates_generated=10, candidates_passed=6)
            runner.record_run(is_canary=False, yield_rate=0.4, health_score=0.6,
                             diversity_score=0.5, candidates_generated=10, candidates_passed=4)

        verdict = runner.evaluate()
        assert verdict["verdict"] == CanaryVerdict.EXTEND.value


def test_canary_promotes_better_config():
    """Canary with clearly better results should promote or extend."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = MetricsStore(tmp_path / "metrics.db")
        mod_log = SelfModificationLog(tmp_path / "mods.db")

        runner = CanaryRunner(tmp_path / "canary", store, mod_log, min_canary_runs=10)
        cid = mod_log.record("gen", "prompt", "baseline", "improved")
        runner.start_canary(cid)

        # Control: lower yield
        for i in range(15):
            runner.record_run(is_canary=False, yield_rate=0.35, health_score=0.5,
                             diversity_score=0.5, candidates_generated=10, candidates_passed=3)

        # Canary: higher yield
        for i in range(15):
            runner.record_run(is_canary=True, yield_rate=0.65, health_score=0.7,
                             diversity_score=0.6, candidates_generated=10, candidates_passed=6)

        verdict = runner.evaluate()
        # Should either promote or extend (not revert)
        assert verdict["verdict"] in (CanaryVerdict.PROMOTE.value, CanaryVerdict.EXTEND.value)


def test_canary_reverts_bad_config():
    """Canary with clearly worse results should revert or extend."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = MetricsStore(tmp_path / "metrics.db")
        mod_log = SelfModificationLog(tmp_path / "mods.db")

        runner = CanaryRunner(tmp_path / "canary", store, mod_log, min_canary_runs=10)
        cid = mod_log.record("gen", "prompt", "good", "broken")
        runner.start_canary(cid)

        # Control: higher yield
        for i in range(15):
            runner.record_run(is_canary=False, yield_rate=0.6, health_score=0.7,
                             diversity_score=0.5, candidates_generated=10, candidates_passed=6)

        # Canary: lower yield
        for i in range(15):
            runner.record_run(is_canary=True, yield_rate=0.2, health_score=0.3,
                             diversity_score=0.5, candidates_generated=10, candidates_passed=2)

        verdict = runner.evaluate()
        # Should either revert or extend (not promote)
        assert verdict["verdict"] in (CanaryVerdict.REVERT.value, CanaryVerdict.EXTEND.value)


def test_manual_promote_and_revert():
    """Manual promote/revert should update state."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = MetricsStore(tmp_path / "metrics.db")
        mod_log = SelfModificationLog(tmp_path / "mods.db")

        runner = CanaryRunner(tmp_path / "canary", store, mod_log)
        cid = mod_log.record("gen", "x", "a", "b")
        runner.start_canary(cid)

        # Manual promote
        assert runner.promote() is True
        status = runner.status()
        assert status["status"] == "promoted"

        # Start new canary and manual revert
        cid2 = mod_log.record("gen", "y", "c", "d")
        runner.start_canary(cid2)
        assert runner.revert() is True
        status = runner.status()
        assert status["status"] == "reverted"
