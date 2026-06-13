"""Spend guard (Part 9). Simple daily-cap tracker — real token accounting later.

SpendGuard tracks accumulated USD spend against a daily cap and a warn threshold.
Call .add(usd) after each model call; .check() raises if the cap is exceeded.
"""
from __future__ import annotations

from .telemetry import logger


class SpendGuard:
    """Track cumulative USD spend against a daily cap.

    Args:
        daily_cap_usd:  Hard stop — .check() raises RuntimeError above this.
        warn_at_usd:    Soft warning threshold (callers can inspect .total()).
    """

    def __init__(self, daily_cap_usd: float, warn_at_usd: float) -> None:
        self._cap = float(daily_cap_usd)
        self._warn = float(warn_at_usd)
        self._total: float = 0.0
        self._warned = False

    def add(self, usd: float) -> None:
        """Accumulate spend. Does NOT auto-raise — call .check() explicitly."""
        self._total += float(usd)
        logger.info("Spend accumulated", extra={"event": "spend", "amount_usd": usd, "total_usd": self._total})
        
        if self._total > self._warn and not self._warned:
            logger.warning(f"Spend warning threshold reached: ${self._total:.2f}", 
                           extra={"event": "spend_warning", "total_usd": self._total, "threshold": self._warn})
            self._warned = True

    def total(self) -> float:
        """Return total USD accumulated so far."""
        return self._total

    def tripped(self) -> bool:
        """Return True when total exceeds the daily cap."""
        return self._total > self._cap

    def check(self) -> None:
        """Raise RuntimeError if the daily cap has been exceeded."""
        if self.tripped():
            logger.error(f"Spend cap tripped: ${self._total:.4f} > cap ${self._cap:.2f}", 
                         extra={"event": "spend_limit_tripped", "total_usd": self._total, "cap": self._cap})
            raise RuntimeError(
                f"spend cap tripped: ${self._total:.4f} > cap ${self._cap:.2f}"
            )

    @property
    def warn_threshold(self) -> float:
        return self._warn

    @property
    def cap(self) -> float:
        return self._cap


def estimate_cost(n_model_calls: int, per_call_usd: float = 0.002) -> float:
    """Rough cost estimate for a batch of model calls."""
    return round(float(n_model_calls) * float(per_call_usd), 6)
