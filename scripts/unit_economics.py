#!/usr/bin/env python3
"""What does it cost to produce one sellable pack, and what is the margin?

The founder's objection on 2026-08-14 was that the price ladder is "silly, predictable and
unscientific" because "we don't even know how much it costs to generate and list a pack, we are
making up numbers, we don't know what our margin and cost is". That was correct, and the reason
is that the cost was recorded in two channels and only one of them was ever summed.

  METERED    `event: "spend"` rows. Two months to 2026-08-14: $87.74. This is what
             `scheduler/guard.py` counts against `spend.daily_cap_usd`, and it is the number
             that gets quoted as "our spend". It covers deepseek, minimax and gemini.

  SUBSCRIPTION-EQUIVALENT
             `message: "Claude CLI usage"` rows carrying the CLI's own `cost_usd`
             (`claude_cli.py:101`). Same window: $3,929.51 -- forty-five times the metered
             figure. claude_cli is deliberately kept out of the spend channel, and the reason is
             sound: `guard.py:36-39` measured that folding subscription burn into the metered cap
             "would halt the daemon within about two hours of every day for spend that is never
             invoiced". But a number excluded from the CAP is not a number that should be
             excluded from the P&L, and excluding it here is why the ledger could not answer
             what a pack costs.

  UNATTRIBUTED
             2,780 rows of exactly $0.01 with no provider and no tokens, from
             `run.py:1236`'s `guard.add(0.01)` -- a flat penny per submitted candidate, labelled
             in the source as "Rough cost estimate increment". At $27.80 that is 32% of the
             metered total and it is an assumption, not a measurement. Reported separately here
             so it can never again be mistaken for one.

The two cost bases answer different questions and this script refuses to merge them:

  * MARGINAL CASH is metered spend only. It is what an extra pack costs today, given the
    subscription is already being paid. It is the right basis for "should we generate more".
  * FULL ECONOMIC cost includes the subscription-equivalent at API rates. It is what the pack
    would cost if the subscription went away or the work moved to metered APIs. It is the right
    basis for "is this business viable at this price".

The gap between them is the subsidy the whole catalogue currently rests on, and naming it is the
point of this script.

Usage: python3 scripts/unit_economics.py [--ledger store/prospector.jsonl] [--api URL]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GRN, RED, YEL, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def read_ledger(path: Path) -> dict:
    """One pass over the ledger, splitting the channels rather than summing them together."""
    metered = 0.0
    metered_by_provider: Counter[str] = Counter()
    flat_penny = 0.0
    flat_penny_rows = 0
    cli_cost = 0.0
    cli_rows = 0
    cli_tokens = Counter()
    cli_by_phase: dict[str, float] = defaultdict(float)
    first_ts = last_ts = None

    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue

            ts = d.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts

            if d.get("event") == "spend":
                amt = float(d.get("amount_usd") or 0)
                provider = d.get("provider")
                if not provider:
                    # `guard.add(0.01)` — an estimate, kept out of the measured total.
                    flat_penny += amt
                    flat_penny_rows += 1
                else:
                    metered += amt
                    metered_by_provider[provider] += amt
            elif (d.get("message") or "").startswith("Claude CLI usage"):
                cli_rows += 1
                cli_cost += float(d.get("cost_usd") or 0)
                for k in ("input", "output", "cached", "cache_write"):
                    cli_tokens[k] += int(d.get(k) or 0)
                cli_by_phase[d.get("phase") or "?"] += float(d.get("cost_usd") or 0)

    return {
        "metered": metered,
        "metered_by_provider": metered_by_provider,
        "flat_penny": flat_penny,
        "flat_penny_rows": flat_penny_rows,
        "cli_cost": cli_cost,
        "cli_rows": cli_rows,
        "cli_tokens": cli_tokens,
        "cli_by_phase": dict(cli_by_phase),
        "window": (first_ts, last_ts),
    }


def live_shelf(api: str) -> list[dict] | None:
    try:
        with urllib.request.urlopen(f"{api.rstrip('/')}/catalog", timeout=60) as r:
            rows = json.loads(r.read())
        return rows if isinstance(rows, list) else None
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def count_dossiers() -> tuple[int, int]:
    """Passes and kills on disk. Kills are not waste: the filter has to kill to find a pass, so
    their cost belongs in the cost of the passes that survived.

    Counted by explicit suffix. `store/dossiers/` also holds 61 `.lint.json` sidecars and a few
    `gate-*` test stubs; a "everything that is not a kill is a pass" count scoops those up and
    reports 135 passes where there are 62 -- which then halves the measured cost per pass and
    invents a 76-idea gap between what passed and what reached the shelf."""
    d = REPO / "store" / "dossiers"
    if not d.is_dir():
        return (0, 0)
    return (len(list(d.glob("*.pass.json"))), len(list(d.glob("*.kill.json"))))


def money(x: float) -> str:
    return f"${x:,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", default=str(REPO / "store" / "prospector.jsonl"))
    ap.add_argument("--api", default="https://api.mumchimp.com")
    ap.add_argument("--gbp-usd", type=float, default=1.27, help="FX for pricing the shelf in USD")
    args = ap.parse_args()

    path = Path(args.ledger)
    if not path.exists():
        print(f"{RED}ledger not found: {path}{OFF}")
        return 2

    print(f"==> Reading {path.name} ({path.stat().st_size / 1e6:,.0f} MB)")
    led = read_ledger(path)
    passes, kills = count_dossiers()
    rows = live_shelf(args.api)

    lo, hi = led["window"]
    print(f"    window {lo} -> {hi}")

    print("\n--- what the pipeline consumed ---")
    print(f"  metered (counts against daily_cap_usd)   {money(led['metered']):>12}")
    for p, v in led["metered_by_provider"].most_common(5):
        print(f"{DIM}      {p:<38} {money(v):>10}{OFF}")
    print(f"  subscription-equivalent (claude_cli)     {money(led['cli_cost']):>12}   {led['cli_rows']:,} calls")
    t = led["cli_tokens"]
    print(
        f"{DIM}      {t['input']:,} in / {t['output']:,} out / {t['cached']:,} cached{OFF}"
    )
    print(
        f"{YEL}  ESTIMATE, not measured (run.py:1236)     {money(led['flat_penny']):>12}"
        f"   {led['flat_penny_rows']:,} rows x $0.01{OFF}"
    )

    full = led["metered"] + led["cli_cost"]
    share = (led["metered"] / full * 100) if full else 0
    print(f"\n  FULL ECONOMIC COST                       {money(full):>12}")
    print(
        f"{DIM}      the metered ledger is {share:.1f}% of it; quoting metered spend as "
        f"'our cost' understates it {full / led['metered']:.0f}x{OFF}"
        if led["metered"]
        else ""
    )

    print("\n--- what it bought ---")
    print(f"  dossiers produced        {passes + kills:,}   ({passes:,} pass, {kills:,} kill)")
    listed = len(rows) if rows is not None else None
    if listed is None:
        print(f"{YEL}  live shelf UNREADABLE — cost per listed pack cannot be computed{OFF}")
    else:
        print(f"  live on the shelf        {listed}")

    if listed:
        print("\n--- cost per sellable pack ---")
        marg = led["metered"] / listed
        econ = full / listed
        print(f"  marginal cash   (metered / listed)       {money(marg):>12}")
        print(f"  full economic   (metered + CLI / listed)  {money(econ):>12}")
        print(
            f"{DIM}      a listed pack carries the cost of the {kills / max(passes, 1):.0f} kills "
            f"it took to find a pass; that is the filter working, not waste{OFF}"
        )

        prices = [r.get("pricePence") or 0 for r in rows if r.get("pricePence")]
        if prices:
            avg_gbp = sum(prices) / len(prices) / 100
            avg_usd = avg_gbp * args.gbp_usd

            # Deliberately NOT a margin. Margin needs units sold, and nothing has sold yet, so
            # any per-unit margin printed here would be a rate on a denominator of zero -- the
            # exact species of made-up number this script was written to retire. What CAN be
            # stated without a sale is how many sales the production already spent would take to
            # repay, which is the same arithmetic pointed at a question the data can answer.
            print("\n--- what the shelf has to do to repay what it cost ---")
            print(f"  average listed price     £{avg_gbp:,.2f}  (~{money(avg_usd)} at {args.gbp_usd})")
            print(
                f"  sales needed to recover  {full / avg_usd:>12,.0f}   units, at that average price"
            )
            print(
                f"{DIM}      = {full / avg_usd / listed * 100:.0f}% of the shelf selling once. A pack is a "
                f"digital good: its cost is paid once, so every sale after the\n"
                f"      first is nearly all margin. The number above is the breakeven, not the "
                f"ceiling.{OFF}"
            )
            print(
                f"{DIM}  Revenue is not in this ledger and is not fetched. Cost is knowable from "
                f"what we spent; margin is not knowable until something sells.{OFF}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
