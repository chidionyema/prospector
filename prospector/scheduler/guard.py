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

WHAT `daily_cap_usd` DOES AND DOES NOT COVER (measured 2026-08-05)
-----------------------------------------------------------------
It counts ONLY ledger rows tagged `event: "spend"`. Those are emitted by `telemetry.py:225`,
and only when the provider has a non-zero entry in the pricing table — i.e. metered API
providers billed in real dollars (minimax, deepseek).

The Claude Code CLI is not one of them. `claude_cli.py:_record_claude_usage` logs the CLI's own
billed figure under `cost_usd` on a row with **no `event` key at all**, so the loop below skips
every one. On 2026-08-05 that gap was:

    event=="spend" rows (what the rail sees) : $1.6400   (370 rows, all minimax)
    "Claude CLI usage" rows (invisible)      : $71.9393  (315 rows)

so the rail bounded 2% of the day's model consumption and the probe printed "$1.64 of $20.00".

That is NOT a broken liability rail: CLI usage runs inside the Claude Code subscription
(CLAUDE.md: "no hosted service / no API-key calls beyond this repo"), so `cost_usd` there is an
API-equivalent estimate, not billed money. Folding it into `daily_cap_usd` would halt the daemon
within about two hours of every day for spend that is never invoiced.

What was actually wrong is that a number covering 2% of consumption was reported as if it
covered all of it. So the guard now measures BOTH and reports both, and the subscription leg gets
its own OPTIONAL ceiling (`spend.daily_subscription_cap_usd`, default 0 = disabled). Arming it is
a deliberate config act about the Max plan's usage allowance — the thing CLAUDE.md means by "run
bounded batches inside the usage allowance" — not a silent change to what is legal today.

CALENDAR DAY IS LOCAL, NOT UTC. `date.today()` is local and ledger timestamps are local asctime,
so the two agree — but the day rolls at local midnight. On 2026-08-05 this read as a bug: the
spend figure fell $1.64 -> $0.13 at 23:00 UTC, which looked like a daemon restart resetting the
counter (a restart would defeat the rail entirely). It was the local day rolling over, one hour
before the UTC day. `day_str` is reported on the decision so the figure is never read against the
wrong calendar again.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

from prospector.scheduler import paths

PAUSE_FILENAME = "PAUSE"


@dataclass(frozen=True)
class GuardDecision:
    can_run: bool
    reason: str
    today_spend_usd: float
    daily_cap_usd: float
    paused: bool
    # Subscription-equivalent burn (Claude Code CLI `total_cost_usd`) for the same local day.
    # Reported always; enforced only when `daily_subscription_cap_usd` is > 0.
    today_subscription_usd: float = 0.0
    daily_subscription_cap_usd: float = 0.0
    # The local calendar day both figures were summed over. Present so a reader never has to
    # guess whether a figure is UTC-day or local-day (that guess cost a wrong verdict once).
    day: str = ""


class SchedulerGuard:
    """Decides whether the daemon may start another generation batch right now."""

    def __init__(self, store_dir: str | Path, daily_cap_usd: float, *, today: str | None = None,
                 daily_subscription_cap_usd: float = 0.0):
        self.store_dir = Path(store_dir)
        self.daily_cap_usd = float(daily_cap_usd)
        self.daily_subscription_cap_usd = float(daily_subscription_cap_usd or 0.0)
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

    def scan_today(self) -> tuple[float, float]:
        """Return (metered_usd, subscription_usd) for today from the persistent audit ledger.

        One pass, two accumulators, because the ledger is ~350k lines and both figures are read
        on every tick:

          * metered      — rows tagged `event: "spend"`, summing `amount_usd`. Real billed money
                           from metered API providers. This is what `daily_cap_usd` enforces.
          * subscription — rows carrying `cost_usd` and NO `event` key: the Claude Code CLI's own
                           `total_cost_usd` (claude_cli.py:82). API-equivalent, not invoiced.

        The `event` test is what separates them, and it is deliberately exclusive: a future
        provider that emits both keys on one row must not be double-counted.

        Robust to a missing/partly-written ledger: unparseable lines are skipped. Timestamps are
        matched by their `YYYY-MM-DD` date prefix, which holds for both ISO and asctime formats.
        """
        p = self.ledger_path
        if not p.exists():
            return 0.0, 0.0
        day = self._today_str()
        metered = 0.0
        subscription = 0.0
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts = str(d.get("timestamp") or d.get("asctime") or "")
                if not ts.startswith(day):
                    continue
                if d.get("event") == "spend":
                    try:
                        metered += float(d.get("amount_usd", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                elif d.get("cost_usd") is not None:
                    try:
                        subscription += float(d.get("cost_usd") or 0)
                    except (TypeError, ValueError):
                        continue
        return round(metered, 6), round(subscription, 6)

    def today_spend_usd(self) -> float:
        """Today's metered (billed) spend — the figure `daily_cap_usd` enforces."""
        return self.scan_today()[0]

    def today_subscription_usd(self) -> float:
        """Today's subscription-equivalent burn — reported always, capped only if configured."""
        return self.scan_today()[1]

    def evaluate(self) -> GuardDecision:
        paused = self.is_paused()
        spend, subscription = self.scan_today()
        sub_cap = self.daily_subscription_cap_usd

        def _decide(can_run: bool, reason: str, paused: bool = False) -> GuardDecision:
            return GuardDecision(
                can_run=can_run,
                reason=reason,
                today_spend_usd=spend,
                daily_cap_usd=self.daily_cap_usd,
                paused=paused,
                today_subscription_usd=subscription,
                daily_subscription_cap_usd=sub_cap,
                day=self._today_str(),
            )

        if paused:
            return _decide(False, f"paused: {self.pause_file} present", paused=True)
        if spend >= self.daily_cap_usd:
            return _decide(
                False, f"daily cap reached: ${spend:.4f} >= ${self.daily_cap_usd:.2f}")
        if sub_cap > 0 and subscription >= sub_cap:
            # Only reachable when the operator armed it. Named distinctly from the metered cap
            # so a halt is never misread as "we spent real money".
            return _decide(
                False,
                f"daily subscription cap reached: ${subscription:.4f} >= ${sub_cap:.2f} "
                f"(subscription-equivalent, not billed)")
        # Both legs in one line. The metered figure alone read as total consumption for weeks.
        return _decide(
            True,
            f"ok: ${spend:.4f} of ${self.daily_cap_usd:.2f} spent today "
            f"(+${subscription:.4f} subscription-equivalent"
            f"{f' of ${sub_cap:.2f}' if sub_cap > 0 else ', uncapped'})")


def _store_dir(cfg) -> Path:
    # Delegates so the "which store?" answer has ONE definition. It used to default to the
    # relative literal "store", which resolves against the cwd — see prospector/scheduler/
    # paths.py for the 110 fabricated rows that put in the live tick log.
    return paths.store_dir(cfg)


def _daily_cap(cfg) -> float:
    spend = getattr(cfg, "spend", None)
    return float(getattr(spend, "daily_cap_usd", 0.0) or 0.0)


def _daily_subscription_cap(cfg) -> float:
    spend = getattr(cfg, "spend", None)
    return float(getattr(spend, "daily_subscription_cap_usd", 0.0) or 0.0)


def guard_from_config(cfg, *, today: str | None = None) -> SchedulerGuard:
    return SchedulerGuard(_store_dir(cfg), _daily_cap(cfg), today=today,
                          daily_subscription_cap_usd=_daily_subscription_cap(cfg))


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
