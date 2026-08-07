"""Metrics store for Prospector's recursive self-improvement system.

Records per-run metrics, computes trends, and fires alerts when the
self-improvement loop shows signs of degradation.

Part of the production-grade self-improvement infrastructure (Priority 3).
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


class MetricsStore:
    """Time-series metrics for production-grade self-improvement observability.

    Records every run's yield, kill rates, diversity, and health scores.
    Provides trend computation and automatic alert detection.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open, commit-or-rollback, then CLOSE. See `store.Store._connect` for the full
        story: `with sqlite3.Connection` ends the transaction and leaves the socket open,
        so this shape leaked two fds per call at every site in this file too. Fixed here
        at the same time because a fix applied only where the symptom appeared is how the
        same defect survives in its siblings."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    yield_rate REAL NOT NULL DEFAULT 0.0,
                    kill_rate_by_gate TEXT NOT NULL DEFAULT '{}',
                    diversity_score REAL NOT NULL DEFAULT 0.0,
                    health_score REAL NOT NULL DEFAULT 0.0,
                    health_sub_scores TEXT NOT NULL DEFAULT '{}',
                    candidates_generated INTEGER NOT NULL DEFAULT 0,
                    candidates_passed INTEGER NOT NULL DEFAULT 0,
                    lane TEXT DEFAULT '',
                    active_changes TEXT DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_run_metrics_ts
                ON run_metrics(timestamp DESC)
            """)

    def record_run(self, run_id: str, metrics: dict) -> int:
        """Record a completed run's metrics. Returns row id."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR REPLACE INTO run_metrics
                   (run_id, timestamp, yield_rate, kill_rate_by_gate, diversity_score,
                    health_score, health_sub_scores, candidates_generated,
                    candidates_passed, lane, active_changes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    metrics.get("timestamp", now),
                    metrics.get("yield_rate", 0.0),
                    json.dumps(metrics.get("kill_rate_by_gate", {})),
                    metrics.get("diversity_score", 0.0),
                    metrics.get("health_score", 0.0),
                    json.dumps(metrics.get("health_sub_scores", {})),
                    metrics.get("candidates_generated", 0),
                    metrics.get("candidates_passed", 0),
                    metrics.get("lane", ""),
                    json.dumps(metrics.get("active_changes", [])),
                ),
            )
            return cursor.lastrowid

    def trend(self, window: int = 50) -> dict:
        """Compute trends over the last N runs.

        Returns dict with yield_trend, kill_rate_by_gate_trend, diversity_trend,
        and health_trend — each as a list of (timestamp, value) tuples.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_metrics ORDER BY timestamp DESC LIMIT ?",
                (window,),
            ).fetchall()

        if not rows:
            return {
                "yield_trend": [],
                "diversity_trend": [],
                "health_trend": [],
                "summary": {"total_runs": 0},
            }

        yield_trend = [(r["timestamp"], r["yield_rate"]) for r in reversed(rows)]
        diversity_trend = [(r["timestamp"], r["diversity_score"]) for r in reversed(rows)]
        health_trend = [(r["timestamp"], r["health_score"]) for r in reversed(rows)]

        # Aggregate kill rates
        gate_totals: dict[str, float] = {}
        for r in rows:
            try:
                gates = json.loads(r["kill_rate_by_gate"])
                for gate, rate in gates.items():
                    gate_totals[gate] = gate_totals.get(gate, 0.0) + rate
            except (json.JSONDecodeError, TypeError):
                pass

        n = len(rows)
        avg_gates = {g: v / n for g, v in gate_totals.items()}

        return {
            "yield_trend": yield_trend,
            "diversity_trend": diversity_trend,
            "health_trend": health_trend,
            "avg_kill_rates": avg_gates,
            "summary": {
                "total_runs": n,
                "mean_yield": sum(y for _, y in yield_trend) / n if n else 0,
                "mean_health": sum(h for _, h in health_trend) / n if n else 0,
            },
        }

    def alert_check(self, window: int = 50) -> list[dict]:
        """Check for alert conditions. Returns list of alert dicts.

        Alert types:
        - yield_decline: yield declining 3+ consecutive windows
        - gate_dominance: any gate >85% of kills
        - diversity_collapse: diversity below 0.3 floor
        - health_decline: health declining 3+ consecutive windows
        """
        alerts = []
        trend_data = self.trend(window)

        if trend_data["summary"]["total_runs"] < 5:
            return alerts  # Not enough data

        # Yield decline (3+ consecutive drops)
        yields = [y for _, y in trend_data["yield_trend"]]
        if len(yields) >= 6:
            recent = yields[-6:]
            declines = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
            if declines >= 3 and recent[-1] < recent[0] * 0.7:
                alerts.append(
                    {
                        "type": "yield_decline",
                        "severity": "warning",
                        "message": (
                            f"Yield declining: {recent[0]:.2f} → {recent[-1]:.2f} "
                            f"over last {len(recent)} runs ({declines}/{len(recent)-1} declines)"
                        ),
                    }
                )

        # Gate dominance (>85% of kills from one gate)
        avg_gates = trend_data.get("avg_kill_rates", {})
        if avg_gates:
            total_kill = sum(avg_gates.values())
            if total_kill > 0:
                for gate, rate in avg_gates.items():
                    pct = (rate / total_kill) * 100 if total_kill > 0 else 0
                    if pct > 85:
                        alerts.append(
                            {
                                "type": "gate_dominance",
                                "severity": "warning",
                                "message": (
                                    f"Gate '{gate}' dominates: {pct:.0f}% of all kills "
                                    f"(threshold: 85%)"
                                ),
                                "gate": gate,
                                "percentage": round(pct, 1),
                            }
                        )

        # Diversity collapse
        diversities = [d for _, d in trend_data["diversity_trend"]]
        if diversities:
            recent_div = diversities[-5:] if len(diversities) >= 5 else diversities
            avg_div = sum(recent_div) / len(recent_div)
            if avg_div < 0.3 and avg_div > 0:  # > 0 to avoid false alarm on unset
                alerts.append(
                    {
                        "type": "diversity_collapse",
                        "severity": "critical",
                        "message": f"Diversity collapsed to {avg_div:.3f} (floor: 0.3)",
                        "diversity": round(avg_div, 3),
                    }
                )

        # Health decline
        healths = [h for _, h in trend_data["health_trend"]]
        if len(healths) >= 6:
            recent_h = healths[-6:]
            h_declines = sum(
                1 for i in range(1, len(recent_h)) if recent_h[i] < recent_h[i - 1]
            )
            if h_declines >= 3 and recent_h[-1] < recent_h[0] - 0.05:
                alerts.append(
                    {
                        "type": "health_decline",
                        "severity": "warning",
                        "message": (
                            f"Health declining: {recent_h[0]:.3f} → {recent_h[-1]:.3f} "
                            f"over last {len(recent_h)} runs"
                        ),
                    }
                )

        return alerts

    def latest(self) -> Optional[dict]:
        """Return the most recent run's metrics, or None if empty."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_metrics ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()

        if not row:
            return None

        return self._row_to_dict(row)

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for json_col in ("kill_rate_by_gate", "health_sub_scores", "active_changes"):
            try:
                d[json_col] = json.loads(d[json_col])
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        return d
