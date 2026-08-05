"""Tests for causal attribution."""

import tempfile
from pathlib import Path

from prospector.metrics_store import MetricsStore
from prospector.self_modify import SelfModificationLog
from prospector.attribution import measure_effect, attribute_all_active


def test_measure_effect_positive():
    """A change that improves yield should be detected as positive."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_store = MetricsStore(tmp_path / "test_metrics.db")

        # Record runs before change (low yield)
        for i in range(10):
            metrics_store.record_run(f"before_{i}", {
                "yield_rate": 0.3,
                "health_score": 0.5,
                "diversity_score": 0.6,
                "candidates_generated": 10,
                "candidates_passed": 3,
                "kill_rate_by_gate": {},
            })

        # Record a modification
        mod_log = SelfModificationLog(tmp_path / "self_modifications.db")
        cid = mod_log.record("gen", "prompt", "v1", "v2", "low_yield", "improve")

        # Record runs after change (higher yield)
        for i in range(10):
            metrics_store.record_run(f"after_{i}", {
                "yield_rate": 0.6,
                "health_score": 0.7,
                "diversity_score": 0.7,
                "candidates_generated": 10,
                "candidates_passed": 6,
                "kill_rate_by_gate": {},
            })

        effect = measure_effect(cid, metrics_store)
        assert effect["direction"] == "positive"
        assert effect["significant"] is True


def test_measure_effect_negative():
    """A change that hurts yield should be detected as negative."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_store = MetricsStore(tmp_path / "test_metrics.db")

        for i in range(10):
            metrics_store.record_run(f"before_{i}", {
                "yield_rate": 0.6,
                "health_score": 0.7,
                "diversity_score": 0.6,
                "candidates_generated": 10,
                "candidates_passed": 6,
                "kill_rate_by_gate": {},
            })

        mod_log = SelfModificationLog(tmp_path / "self_modifications.db")
        cid = mod_log.record("gen", "steer", "good", "bad", "test", "test")

        for i in range(10):
            metrics_store.record_run(f"after_{i}", {
                "yield_rate": 0.2,
                "health_score": 0.4,
                "diversity_score": 0.4,
                "candidates_generated": 10,
                "candidates_passed": 2,
                "kill_rate_by_gate": {},
            })

        effect = measure_effect(cid, metrics_store)
        assert effect["direction"] == "negative"
        assert effect["significant"] is True
        assert "rollback" in effect["recommendation"]


def test_insufficient_data():
    """Not enough runs should return insufficient_data."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_store = MetricsStore(tmp_path / "test_metrics.db")

        metrics_store.record_run("run_1", {
            "yield_rate": 0.5,
            "health_score": 0.5,
            "diversity_score": 0.5,
            "candidates_generated": 10,
            "candidates_passed": 5,
            "kill_rate_by_gate": {},
        })

        mod_log = SelfModificationLog(tmp_path / "self_modifications.db")
        cid = mod_log.record("test", "x", "a", "b")

        effect = measure_effect(cid, metrics_store)
        assert "insufficient" in effect["recommendation"].lower()


def test_attribute_all_active():
    """Should measure effects for all active modifications."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_store = MetricsStore(tmp_path / "test_metrics.db")
        mod_log_path = tmp_path / "self_modifications.db"
        mod_log = SelfModificationLog(mod_log_path)

        # Record baseline
        for i in range(10):
            metrics_store.record_run(f"base_{i}", {
                "yield_rate": 0.4,
                "health_score": 0.5,
                "diversity_score": 0.5,
                "candidates_generated": 10,
                "candidates_passed": 4,
                "kill_rate_by_gate": {},
            })

        # Create two active modifications
        cid1 = mod_log.record("a", "x", "old", "new")
        cid2 = mod_log.record("b", "y", "old", "new")

        # Record post-change runs (better yield)
        for i in range(10):
            metrics_store.record_run(f"post_{i}", {
                "yield_rate": 0.6,
                "health_score": 0.7,
                "diversity_score": 0.6,
                "candidates_generated": 10,
                "candidates_passed": 6,
                "kill_rate_by_gate": {},
            })

        results = attribute_all_active(metrics_store, mod_log_path)
        assert len(results) == 2
        for r in results:
            assert "change_id" in r
            assert "direction" in r
