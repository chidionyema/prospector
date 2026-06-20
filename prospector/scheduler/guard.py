"""Automated safety backstop for the always-on generation daemon.

The daemon runs unattended (founder decision, 2026-06-20), so these two automated rails REPLACE
human supervision; neither is optional:

  1. A hard **daily spend ceiling** (config `spend.daily_cap_usd`). Computed from the persistent
     audit ledger `store/prospector.jsonl`, summing today's `spend` events. When today's spend is
     at or above the cap, no new batch starts until the calendar day rolls over.
  2. A filesystem **kill switch**: the presence of `store/scheduler/PAUSE` halts all batches. The
     daemon keeps looping and re-checking, so `rm`-ing the file resumes it with no restart.

Why the ledger and not in-process telemetry: the daemon (and any per-tick subprocess) may be a
fresh process whose in-process counter is ~0, which would make the cap never fire. Reading the
on-disk ledger is correct across restarts. The ledger only accrues spend if generation routes its
telemetry there — `run_scheduled` calls `route_logs_to_file(<store>/prospector.jsonl)` to ensure
exactly that.

The ceiling is a pre-run check, so a single in-flight batch can overshoot by at most one batch's
worth of spend — bounded by `schedule.batch_size`. That is the intended, acceptable slack.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

PAUSE_FILENAME = "PAUSE"


@dataclass(frozen=True)
class GuardDecision:
    can_run: bool
    reason: str
    today_spend_usd: float
    daily_cap_usd: float
    paused: bool


class SchedulerGuard:
    """Decides whether the daemon may start another generation batch right now."""

    def __init__(self, store_dir: str | Path, daily_cap_usd: float, *, today: str | None = None):
        self.store_dir = Path(store_dir)
        self.daily_cap_usd = float(daily_cap_usd)
        self._today_override = today  # 'YYYY-MM-DD' injection point for tests

    @property
    def scheduler_dir(self) -> Path:
        return self.store_dir / "scheduler"

    @property
    def pause_file(self) -> Path:
        return self.scheduler_dir / PAUSE_FILENAME

    @property
    def ledger_path(self) -> Path:
        return self.store_dir / "prospector.jsonl"

    def _today_str(self) -> str:
        return self._today_override or _dt.date.today().isoformat()

    def is_paused(self) -> bool:
        return self.pause_file.exists()

    def today_spend_usd(self) -> float:
        """Sum today's `spend` events from the persistent audit ledger.

        Robust to a missing/partly-written ledger: unparseable lines are skipped. Timestamps are
        matched by their `YYYY-MM-DD` date prefix, which holds for both ISO and asctime formats.
        """
        p = self.ledger_path
        if not p.exists():
            return 0.0
        day = self._today_str()
        total = 0.0
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("event") != "spend":
                    continue
                ts = str(d.get("timestamp") or d.get("asctime") or "")
                if not ts.startswith(day):
                    continue
                try:
                    total += float(d.get("amount_usd", 0) or 0)
                except (TypeError, ValueError):
                    continue
        return round(total, 6)

    def evaluate(self) -> GuardDecision:
        paused = self.is_paused()
        spend = self.today_spend_usd()
        if paused:
            return GuardDecision(
                can_run=False,
                reason=f"paused: {self.pause_file} present",
                today_spend_usd=spend,
                daily_cap_usd=self.daily_cap_usd,
                paused=True,
            )
        if spend >= self.daily_cap_usd:
            return GuardDecision(
                can_run=False,
                reason=f"daily cap reached: ${spend:.4f} >= ${self.daily_cap_usd:.2f}",
                today_spend_usd=spend,
                daily_cap_usd=self.daily_cap_usd,
                paused=False,
            )
        return GuardDecision(
            can_run=True,
            reason=f"ok: ${spend:.4f} of ${self.daily_cap_usd:.2f} spent today",
            today_spend_usd=spend,
            daily_cap_usd=self.daily_cap_usd,
            paused=False,
        )


def _store_dir(cfg) -> Path:
    return Path(getattr(cfg, "store_dir", "store"))


def _daily_cap(cfg) -> float:
    spend = getattr(cfg, "spend", None)
    return float(getattr(spend, "daily_cap_usd", 0.0) or 0.0)


def guard_from_config(cfg, *, today: str | None = None) -> SchedulerGuard:
    return SchedulerGuard(_store_dir(cfg), _daily_cap(cfg), today=today)


def guard_check(cfg) -> tuple[bool, str]:
    """Compatibility wrapper: (allowed, reason) for callers that don't need the full decision.

    A non-positive `daily_cap_usd` means "no cap configured" — the spend rail is then disabled and
    only the PAUSE kill switch applies. Configure `spend.daily_cap_usd` to arm the ceiling.
    """
    guard = guard_from_config(cfg)
    if guard.is_paused():
        return False, f"paused: {guard.pause_file} present"
    if guard.daily_cap_usd <= 0:
        return True, "no daily cap configured (spend rail disabled; PAUSE switch still applies)"
    decision = guard.evaluate()
    return decision.can_run, decision.reason
