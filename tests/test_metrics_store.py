"""Tests for MetricsStore — time-series metrics and alert detection."""

import tempfile
from pathlib import Path

from prospector.metrics_store import MetricsStore


def test_record_and_retrieve():
    """Basic record and retrieve cycle."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_metrics.db")

        store.record_run("run_1", {
            "yield_rate": 0.45,
            "health_score": 0.72,
            "candidates_generated": 20,
            "candidates_passed": 9,
            "kill_rate_by_gate": {"source_check": 0.3, "market_size": 0.7},
            "diversity_score": 0.65,
        })

        latest = store.latest()
        assert latest is not None
        assert latest["run_id"] == "run_1"
        assert latest["yield_rate"] == 0.45
        assert latest["health_score"] == 0.72
        assert latest["candidates_generated"] == 20
        assert latest["candidates_passed"] == 9
        assert latest["kill_rate_by_gate"]["source_check"] == 0.3


def test_trend_computation():
    """Trend should return ordered time series."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_trend.db")

        for i in range(10):
            store.record_run(f"run_{i}", {
                "yield_rate": 0.3 + i * 0.02,
                "health_score": 0.5 + i * 0.01,
                "candidates_generated": 10,
                "candidates_passed": int(3 + i * 0.2),
                "diversity_score": 0.6,
                "kill_rate_by_gate": {},
            })

        trend = store.trend(window=10)
        assert trend["summary"]["total_runs"] == 10
        assert len(trend["yield_trend"]) == 10
        # Yield should be increasing
        yields = [y for _, y in trend["yield_trend"]]
        assert yields[-1] > yields[0]


def test_yield_decline_alert():
    """Declining yield over 3+ runs should trigger alert."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_alert.db")

        for i in range(8):
            yield_rate = 0.6 - i * 0.08  # Steadily declining
            store.record_run(f"run_{i}", {
                "yield_rate": max(yield_rate, 0.01),
                "health_score": 0.5,
                "candidates_generated": 10,
                "candidates_passed": 2,
                "diversity_score": 0.6,
                "kill_rate_by_gate": {},
            })

        alerts = store.alert_check(window=10)
        alert_types = [a["type"] for a in alerts]
        assert "yield_decline" in alert_types


def test_gate_dominance_alert():
    """Single gate >85% of kills should trigger alert."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_gate.db")

        for i in range(5):
            store.record_run(f"run_{i}", {
                "yield_rate": 0.1,
                "health_score": 0.5,
                "candidates_generated": 10,
                "candidates_passed": 1,
                "diversity_score": 0.5,
                "kill_rate_by_gate": {"source_check": 90, "market_size": 10},
            })

        alerts = store.alert_check(window=10)
        alert_types = [a["type"] for a in alerts]
        assert "gate_dominance" in alert_types


def test_diversity_collapse_alert():
    """Diversity below 0.3 floor should trigger critical alert."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_div.db")

        for i in range(5):
            store.record_run(f"run_{i}", {
                "yield_rate": 0.2,
                "health_score": 0.5,
                "candidates_generated": 10,
                "candidates_passed": 2,
                "diversity_score": 0.15,  # Well below 0.3 floor
                "kill_rate_by_gate": {},
            })

        alerts = store.alert_check(window=10)
        alert_types = [a["type"] for a in alerts]
        assert "diversity_collapse" in alert_types


def test_health_decline_alert():
    """Declining health over 3+ runs should trigger alert."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_health.db")

        for i in range(8):
            store.record_run(f"run_{i}", {
                "yield_rate": 0.5,
                "health_score": 0.8 - i * 0.05,
                "candidates_generated": 10,
                "candidates_passed": 5,
                "diversity_score": 0.6,
                "kill_rate_by_gate": {},
            })

        alerts = store.alert_check(window=10)
        alert_types = [a["type"] for a in alerts]
        assert "health_decline" in alert_types


def test_empty_store_no_alerts():
    """Empty store should not fire alerts."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_empty.db")
        alerts = store.alert_check()
        assert len(alerts) == 0


def test_insufficient_data_no_alerts():
    """Less than 5 runs should not fire alerts."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_few.db")
        for i in range(3):
            store.record_run(f"run_{i}", {
                "yield_rate": 0.0,
                "health_score": 0.0,
                "candidates_generated": 0,
                "candidates_passed": 0,
                "diversity_score": 0.0,
                "kill_rate_by_gate": {},
            })
        alerts = store.alert_check()
        assert len(alerts) == 0


def test_active_changes_preserved():
    """JSON fields should round-trip correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MetricsStore(Path(tmp) / "test_json.db")
        store.record_run("run_1", {
            "yield_rate": 0.5,
            "health_score": 0.7,
            "health_sub_scores": {"auto_fixes": 0.6, "injection_relevance": 0.9},
            "candidates_generated": 10,
            "candidates_passed": 5,
            "diversity_score": 0.5,
            "active_changes": ["change-001", "change-002"],
            "kill_rate_by_gate": {"moat": 0.5},
        })

        latest = store.latest()
        assert latest["health_sub_scores"]["auto_fixes"] == 0.6
        assert latest["active_changes"] == ["change-001", "change-002"]
