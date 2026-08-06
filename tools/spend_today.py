"""Print today's spend against the cap, computed LIVE from the persistent ledger.

Why this exists — it replaces a hand-rolled parse that silently reported $0.00.

The daily spend ceiling is one of the two automated rails CLAUDE.md requires in place of a
human supervising unattended generation. Until now there were only two ways to read it, and
neither answers "what is spent right now?":

  * the state probe prints `ticks[-1]["today_spend_usd"]` — a value RECORDED at the last
    tick. The daemon ticks on a multi-hour interval, so anything spent since (a backfill, a
    manual vet, a drain) is invisible. It is a snapshot, correct only at the moment it was
    written.
  * `run_scheduled.py:717` prints a live figure, but only inside the scheduler's own
    diagnostics, which means running the scheduler.

With no live read available, the tempting move is to parse `store/prospector.jsonl` by hand,
and that is a trap with no error message. A hand parse written on 2026-08-06 keyed off a
`date` field and summed `metered_usd`/`amount_usd`. The ledger has no `date` field — the key
is `timestamp` — so the filter matched zero rows and the script printed a confident
"$0.00 of $20.00" for a day with real spend on it. A cap that reads $0.00 is not a degraded
cap, it is no cap, and it fails silently in the safe-looking direction.

So this delegates every number to `SchedulerGuard.evaluate()` — the same object the daemon
gates on (`run_scheduled.py:344`). There is no arithmetic in this file on purpose. If the
figures here are wrong, the daemon is gated on the same wrong figures, which is the property
you want from a probe.

Both legs are always printed. Metered is billed money and is what the cap enforces;
subscription-equivalent is Claude Code CLI burn, which is not invoiced and is usually the far
larger number (measured 2026-08-05: metered $1.64, subscription $71.94 — the rail covered 2%
of what the engine actually burned). Reporting metered alone reads as total consumption.

Exit codes:
    0  the guard would allow a run
    1  the guard would refuse (cap reached, PAUSE present, or clock behind the ledger)

Usage:
    .venv/bin/python tools/spend_today.py [--config config.yaml] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import os
import sys

# Same as the sibling tools (backfill_listing_copy.py:60): tools/ is not on the path when the
# script is invoked by path, so the package import below fails without this.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.config import load_config  # noqa: E402
from prospector.scheduler.guard import guard_from_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="config path (default: repo config.yaml)")
    parser.add_argument("--today", default=None,
                        help="override the local day, 'YYYY-MM-DD' (testing / clock faults)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    guard = guard_from_config(cfg, today=args.today)
    d = guard.evaluate()

    sub_cap = f"of ${d.daily_subscription_cap_usd:.2f}" if d.daily_subscription_cap_usd > 0 \
        else "UNCAPPED"

    print(f"ledger        {guard.ledger_path}")
    print(f"local day     {d.day}")
    print(f"metered       ${d.today_spend_usd:.4f} of ${d.daily_cap_usd:.2f}   (billed money — "
          f"this is what the cap enforces)")
    print(f"subscription  ${d.today_subscription_usd:.4f} {sub_cap}   (Claude Code CLI "
          f"equivalent, not invoiced)")
    print(f"paused        {d.paused}   ({guard.pause_file})")
    print()
    print(f"{'ALLOW' if d.can_run else 'REFUSE'}: {d.reason}")
    return 0 if d.can_run else 1


if __name__ == "__main__":
    sys.exit(main())
