"""A/B testing (canary mode) for Prospector's self-modifications.

Before a self-modification goes to production, it runs in canary mode:
a subset of runs use the proposed change while the rest use the current
production config. After enough data, the canary is automatically
promoted (if it wins) or reverted (if it loses).

Part of the production-grade self-improvement infrastructure (Priority 6).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from .attribution import measure_effect
from .metrics_store import MetricsStore
from .self_modify import SelfModificationLog


class CanaryVerdict(str, Enum):
    PROMOTE = "promote"
    REVERT = "revert"
    EXTEND = "extend"


@dataclass
class CanaryState:
    """Current state of a canary experiment."""

    change_id: str
    status: str  # running, promoted, reverted
    started_at: str
    canary_runs: int = 0
    control_runs: int = 0
    canary_metrics: dict = field(default_factory=dict)
    control_metrics: dict = field(default_factory=dict)
    verdict: Optional[str] = None
    verdict_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "status": self.status,
            "started_at": self.started_at,
            "canary_runs": self.canary_runs,
            "control_runs": self.control_runs,
            "canary_metrics": self.canary_metrics,
            "control_metrics": self.control_metrics,
            "verdict": self.verdict,
            "verdict_at": self.verdict_at,
        }


class CanaryRunner:
    """Manages A/B testing of self-modifications.

    Usage:
        runner = CanaryRunner(store_dir, metrics_store, mod_log)
        runner.start_canary(change_id)
        # ... run vet with --canary flag for each canary run ...
        runner.record_canary_run(...)
        verdict = runner.evaluate()  # promote, revert, or extend
    """

    def __init__(
        self,
        store_dir: Path,
        metrics_store: MetricsStore,
        mod_log: SelfModificationLog,
        min_canary_runs: int = 20,
        significance_threshold: float = 0.1,
    ):
        self.store_dir = Path(store_dir)
        self.metrics_store = metrics_store
        self.mod_log = mod_log
        self.min_canary_runs = min_canary_runs
        self.significance_threshold = significance_threshold
        self._state_file = self.store_dir / "canary_state.json"

    def start_canary(self, change_id: str) -> CanaryState:
        """Begin a canary experiment for a modification."""
        state = CanaryState(
            change_id=change_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save_state(state)
        return state

    def record_run(
        self,
        is_canary: bool,
        yield_rate: float,
        health_score: float,
        diversity_score: float,
        candidates_generated: int,
        candidates_passed: int,
        **extra_metrics,
    ) -> None:
        """Record a run result for either the canary or control group.

        Call this after each vet run completes, passing is_canary=True if
        the run used the proposed change.
        """
        state = self._load_state()
        if state is None or state.status != "running":
            return

        if is_canary:
            state.canary_runs += 1
        else:
            state.control_runs += 1

        self._save_state(state)

        # Also record to metrics store for later analysis
        self.metrics_store.record_run(
            f"canary_{state.change_id}_{state.canary_runs + state.control_runs}",
            {
                "yield_rate": yield_rate,
                "health_score": health_score,
                "diversity_score": diversity_score,
                "candidates_generated": candidates_generated,
                "candidates_passed": candidates_passed,
                "lane": "canary" if is_canary else "control",
            },
        )

    def evaluate(self) -> dict:
        """Evaluate the canary experiment. Returns verdict dict.

        Decision rules:
        - If canary wins with p < significance_threshold → PROMOTE
        - If canary loses with p < significance_threshold → REVERT
        - If p >= significance_threshold and min_runs reached → EXTEND (keep running)
        - If ambiguous with enough runs → EXTEND
        """
        state = self._load_state()
        if state is None:
            return {"verdict": "no_experiment", "reason": "No canary state found"}

        if state.status != "running":
            return {
                "verdict": state.status,
                "reason": f"Canary already {state.status}",
            }

        # Need minimum runs to evaluate
        min_runs = max(self.min_canary_runs, 10)
        if state.canary_runs < min_runs or state.control_runs < min_runs:
            return {
                "verdict": CanaryVerdict.EXTEND.value,
                "reason": (
                    f"Insufficient data: {state.canary_runs} canary, "
                    f"{state.control_runs} control (need {min_runs} each)"
                ),
            }

        # Measure effect using attribution
        effect = measure_effect(
            state.change_id,
            self.metrics_store,
            window_before=state.control_runs,
            window_after=state.canary_runs,
        )

        direction = effect["direction"]
        significant = effect["significant"]

        if significant and direction == "positive":
            verdict = CanaryVerdict.PROMOTE
            reason = f"Canary significantly improves yield (p < {self.significance_threshold})"
        elif significant and direction == "negative":
            verdict = CanaryVerdict.REVERT
            reason = f"Canary significantly degrades yield (p < {self.significance_threshold})"
        else:
            verdict = CanaryVerdict.EXTEND
            reason = "Effect not statistically significant — extending observation"

        # Apply verdict
        now = datetime.now(timezone.utc).isoformat()
        if verdict == CanaryVerdict.PROMOTE:
            state.status = "promoted"
            state.verdict = "promoted"
            state.verdict_at = now
            self._save_state(state)
        elif verdict == CanaryVerdict.REVERT:
            state.status = "reverted"
            state.verdict = "reverted"
            state.verdict_at = now
            self._save_state(state)
            # Rollback the change
            self.mod_log.rollback(state.change_id)

        return {
            "verdict": verdict.value,
            "reason": reason,
            "effect": effect,
            "canary_runs": state.canary_runs,
            "control_runs": state.control_runs,
        }

    def promote(self) -> bool:
        """Manually promote the canary change to production."""
        state = self._load_state()
        if state is None:
            return False

        state.status = "promoted"
        state.verdict = "promoted"
        state.verdict_at = datetime.now(timezone.utc).isoformat()
        self._save_state(state)
        return True

    def revert(self) -> bool:
        """Manually revert the canary change."""
        state = self._load_state()
        if state is None:
            return False

        state.status = "reverted"
        state.verdict = "reverted"
        state.verdict_at = datetime.now(timezone.utc).isoformat()
        self._save_state(state)

        # Rollback the change
        self.mod_log.rollback(state.change_id)
        return True

    def status(self) -> Optional[dict]:
        """Get current canary status."""
        state = self._load_state()
        if state is None:
            return {"status": "no_experiment"}
        return state.to_dict()

    def _load_state(self) -> Optional[CanaryState]:
        if not self._state_file.is_file():
            return None
        try:
            data = json.loads(self._state_file.read_text())
            return CanaryState(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def _save_state(self, state: CanaryState):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(state.to_dict(), indent=2))
