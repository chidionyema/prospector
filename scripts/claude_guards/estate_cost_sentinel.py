#!/usr/bin/env python3
"""Estate cost sentinel — the automatic rail that 2026-08-06 proved was missing.

$852 became $1,008 in one day with nobody watching, because every existing rail either
measured the wrong money or depended on our own code remembering to log it (see
`estate_spend.py` for the three that failed). This closes the loop:

    MEASURE  estate_spend.scan()  — ground truth from Claude Code's own transcripts
    SHOW     Telegram digest      — pushed, not pulled; a dashboard nobody opens is not a rail
    HALT     store/scheduler/PAUSE — the existing, proven kill switch

Three levels, all thresholds in `~/.claude/estate-budget.json` so changing the policy is
never a code edit:

    warn_usd   -> Telegram warning, debounced to once an hour
    halt_usd   -> Telegram alarm + write the daemon's PAUSE file. 0 disables (default).
    digest     -> a scheduled "here is the number" push, sent even when nothing is wrong

WHY HALT DEFAULTS TO DISARMED
-----------------------------
`PAUSE` stops the entire prospector tick — generation AND the re-vet drain (CLAUDE.md keeps
it that way deliberately: "a rail with exceptions is not a rail"). That is the correct
response to runaway spend and the wrong thing to trigger by surprise on a live business, so
the threshold is a deliberate operator act, exactly as `guard.py:43` argues for the
subscription cap it mirrors. The mechanism is armed; the number is the founder's.

WHAT THIS CANNOT DO
-------------------
It cannot halt an interactive Claude Code session — no such kill switch exists, and inventing
one that kills the founder mid-sentence would be worse than the spend. Interactive burn is
covered by visibility only (the statusline, and this digest naming it as a line item). On
2026-08-06 interactive was $426.93 of $1,008.73, so that is a real, stated gap, not a
rounding error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))

import estate_spend  # noqa: E402

CONFIG = os.path.expanduser("~/.claude/estate-budget.json")
HISTORY = os.path.expanduser("~/.claude/estate-spend-history.jsonl")
DEFAULTS = {
    "warn_usd": 120.0,
    "halt_usd": 0.0,
    "pause_files": ["~/Documents/code/prospector/store/scheduler/PAUSE"],
    "digest_debounce_s": 3600,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as e:
        # A malformed budget file must not silently fall back to defaults that might be
        # laxer than what the operator wrote — say so on stderr, loudly.
        print(f"[sentinel] WARNING: {CONFIG} unreadable ({e}); using defaults", file=sys.stderr)
    return cfg


def alert(text: str, *, key: str | None = None, debounce_s: float = 3600.0,
          dry_run: bool = False) -> bool:
    """Push to Telegram. Never raises: a broken alerter must not break the sentinel."""
    try:
        from estate_alert import send_operator_alert
    except ImportError as e:
        print(f"[sentinel] telegram unavailable ({e}); printing instead\n{text}")
        return False
    try:
        return send_operator_alert(text, debounce_key=key, debounce_s=debounce_s,
                                   dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — alerting is best-effort by contract
        print(f"[sentinel] telegram send failed ({e}); printing instead\n{text}")
        return False


def write_pause(paths: list[str], reason: str, dry_run: bool) -> list[str]:
    """Write the daemon's kill switch. Idempotent — an existing PAUSE is left untouched so
    the sentinel never overwrites a human's reason with its own."""
    done = []
    for p in paths:
        path = os.path.expanduser(p)
        if os.path.exists(path):
            done.append(f"{path} (already paused)")
            continue
        if dry_run:
            done.append(f"{path} (DRY RUN — not written)")
            continue
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(reason + "\n")
            done.append(path)
        except OSError as e:
            done.append(f"{path} (FAILED: {e})")
    return done


def record(res: dict) -> None:
    """Append one row per run so spend becomes a time series, not a spot reading.

    The audit could only say "$852 today" because no history existed — the shape of the
    curve, which is what tells you a fix worked, had to be reconstructed from transcripts.
    """
    try:
        with open(HISTORY, "a") as fh:
            fh.write(json.dumps({
                "at": dt.datetime.now().isoformat(timespec="seconds"),
                "day": res["day"], "total": res["total"], "requests": res["requests"],
                "by_owner": {k: round(v, 2) for k, v in res["by_owner"].items()},
                "reqs_by_owner": res.get("reqs_by_owner", {}),
            }) + "\n")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="report and show what WOULD be sent/paused; change nothing")
    ap.add_argument("--digest", action="store_true",
                    help="push the number even when no threshold is crossed")
    ap.add_argument("--day", default=dt.date.today().isoformat())
    args = ap.parse_args()

    cfg = load_config()
    res = estate_spend.scan(args.day)
    record(res)

    total = res["total"]
    # WARN on the estate total — that is the number the founder needs to see.
    # HALT on the daemon's own spend, because PAUSE can only stop the daemon. Keying the halt
    # to the estate total would let interactive coding — $430.82 of $1,020.47 on 2026-08-06,
    # and unstoppable by any switch we have — trip a brake that then punishes the daemon for
    # burn it did not cause. A rail keyed to a number it cannot influence is not a rail.
    haltable = sum(v for k, v in res["by_owner"].items() if k.startswith("prospector-daemon"))
    warn, halt = float(cfg["warn_usd"]), float(cfg["halt_usd"])
    body = estate_spend.fmt(res, cap=halt or warn)
    print(body)
    print(f"  haltable (daemon only): ${haltable:,.2f}"
          + (f" of ${halt:,.2f}" if halt else "  [halt DISARMED]"))

    breached = halt > 0 and haltable >= halt
    warned = warn > 0 and total >= warn

    if breached:
        reason = (f"estate cost sentinel: ${total:,.2f} >= halt cap ${halt:,.2f} "
                  f"on {res['day']}")
        paused = write_pause(cfg["pause_files"], reason, args.dry_run)
        sent = alert(f"\U0001f6d1 SPEND HALT\n{body}\n\nPaused: " + ", ".join(paused),
                     key="estate-halt", debounce_s=1800, dry_run=args.dry_run)
        print(f"[sentinel] HALT: {reason}\n[sentinel] paused: {paused}")
        print(f"[sentinel] HALT alert delivered: {sent}"
              + ("" if sent else "  ← NOT DELIVERED (debounced or send failed)"))
        return 2

    if warned:
        # alert() returns False when the send failed OR when the debounce
        # swallowed it. Printing "WARN sent" unconditionally made an undelivered
        # warning indistinguishable from a delivered one — the exact failure this
        # sentinel exists to prevent, one layer up. Report what actually happened.
        sent = alert(f"⚠️ Spend warning\n{body}\n\nHalt cap: "
                     + (f"${halt:,.2f}" if halt else "DISARMED — set halt_usd in " + CONFIG),
                     key="estate-warn", debounce_s=float(cfg["digest_debounce_s"]),
                     dry_run=args.dry_run)
        print(f"[sentinel] WARN delivered: {sent}"
              + ("" if sent else "  ← NOT DELIVERED (debounced or send failed)"))
        return 1

    if args.digest:
        sent = alert(f"\U0001f4b0 Estate spend\n{body}", key="estate-digest",
                     debounce_s=float(cfg["digest_debounce_s"]), dry_run=args.dry_run)
        print(f"[sentinel] digest delivered: {sent}"
              + ("" if sent else "  ← NOT DELIVERED (debounced or send failed)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
