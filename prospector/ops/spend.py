"""R21 — where today's money went, against the ceiling that stops the daemon.

One view, `spend_view`: both spend LEGS for the local calendar day, each against the cap declared
for it in `config.yaml spend:`, each with a projected hit-time; plus what of that spend can be
attributed to a ROLE (verdict / noncritical / artifact / marketing / grounding), and what cannot.

Four rules this module exists to keep, every one of them a scar:

1. **There is exactly ONE reader of `store/prospector.jsonl`.** `scheduler/guard.py` — the same
   object the daemon's rail evaluates — and this module reaches the figure only through
   `SchedulerGuard.scan_today()` / `spend_by_day()`. The ledger is 193 MB; a hand-rolled sum over
   it returns a confident **$0.00 on a day with real spend**, because the rows are keyed
   `timestamp` (not `date`) and the metered leg is `event: "spend"` + `amount_usd` — a wrong key
   matches nothing, raises nothing, and fails in the safe-LOOKING direction (memory:
   `never-hand-parse-the-spend-ledger`). `tests/ops/test_spend.py` asserts that every open of the
   ledger during a `spend_view` call is made by `guard.py`, so a second parse added here is red
   before it is wrong.

2. **It reads the CACHED scan, not the whole file.** `guard._scan` resumes from the byte-offset
   checkpoint in `store/scheduler/spend_scan.cache.json`; the uncached pass measured 108 s on the
   157 MB ledger and is what made the hourly guard probe die on a 110 s timeout. The view reports
   the checkpoint it found (`cache.offset`, `cache.lag_bytes`) so "this figure came from the
   cache" is a number on screen, not a claim in a docstring. This module never sets
   `PROSPECTOR_GUARD_FULL_SCAN`; the escape hatch stays the operator's.

3. **Both legs, always, and they are NOT one number.** `metered` is billed money and is the only
   thing `spend.daily_cap_usd` enforces; `subscription` is Claude Code CLI burn (`cost_usd`, no
   `event` key), API-equivalent and not invoiced. They differ by orders of magnitude ($8.47 vs
   $258.89 on 2026-08-15, live cache), so printing the metered leg alone reads as total
   consumption — which is exactly how a rail covering 2% of the day's consumption got reported as
   if it covered all of it (`guard.py` module docstring, 2026-08-05).

4. **An unmeasurable projection is a null WITH A REASON, never an extrapolation.** No spend yet, a
   day only twenty minutes old, an absent ledger, a cap of 0, a clock behind the ledger — each
   produces `hit_at: None` and a sentence saying which. A confident null is the failure mode
   (memory: `a-saturated-metric-prints-as-a-confident-null`): the operator must be able to tell
   "not measured" from "measured, and there is time".

Nothing here writes, arms or disarms anything. The only file this module's call path touches is
`guard`'s own scan checkpoint, which `guard` refreshes for its own bookkeeping (tmp + `os.replace`,
so a racing daemon can only replace it with another self-consistent snapshot) — no rail, no
config, no catalogue row.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

#: Config keys, quoted on screen so a figure is never read against a cap nobody can find.
CAP_KEY = "spend.daily_cap_usd"
WARN_KEY = "spend.warn_at_usd"
SUBSCRIPTION_CAP_KEY = "spend.daily_subscription_cap_usd"

#: Below this much of the local day elapsed, no rate is reported at all. $5 in the first ten
#: minutes is not "$720/day"; a floor keeps one burst from minting a hit-time an operator would
#: plan around. Same reasoning as `readmodel._MIN_RATE_WINDOW_S`, in hours.
MIN_ELAPSED_H = 1.0

#: Tiers whose usage is recorded by `claude_cli.py::_record_claude_usage` — a `cost_usd` row with
#: NO `event` key, which is precisely what `guard._scan` counts as the subscription leg. This is a
#: statement about the code path that writes the ledger row, not a preference about the roster: a
#: tier is metered iff `telemetry.get_price` gives it a non-zero price (the condition
#: `telemetry.record_usage:289-305` actually tests before emitting `event: "spend"`).
SUBSCRIPTION_TIERS = frozenset({"claude_cli"})


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()


def load_cfg(path: Optional[str] = None):
    """Config loaded the way the engine loads it — see `readmodel.load_cfg` for why that matters
    (it installs the `moat_primary` process global this view's role table is keyed to)."""
    from prospector.ops import readmodel as _rm

    return _rm.load_cfg(path)


# --------------------------------------------------------------------------- #
# The local calendar day, because that is the day the cap sums over
# --------------------------------------------------------------------------- #
def _local_day_bounds(now: float) -> tuple[str, float, float]:
    """(day, elapsed_h, hours_left_today) for the LOCAL calendar day containing `now`.

    Local, not UTC, because `guard._today_str()` is `date.today()` and ledger timestamps are local
    asctime. Reading one figure against the other calendar is how a spend total falling $1.64 ->
    $0.13 at 23:00 UTC read as a daemon restart defeating the rail, when it was the local day
    rolling an hour early (`guard.py` module docstring).

    Both edges go through `.timestamp()` rather than arithmetic on 86400, so a DST day is 23 or 25
    hours here exactly as it is on the wall clock.
    """
    local = datetime.fromtimestamp(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = midnight + timedelta(days=1)
    elapsed_s = now - midnight.timestamp()
    left_s = next_midnight.timestamp() - now
    return local.date().isoformat(), max(elapsed_s, 0.0) / 3600.0, max(left_s, 0.0) / 3600.0


# --------------------------------------------------------------------------- #
# Projection — a rate, or a stated reason there is none
# --------------------------------------------------------------------------- #
def _project(*, usd: float, cap_usd: float, cap_key: str, elapsed_h: float,
             hours_left_today: float, now: float, blocked: str = "") -> dict:
    """Hours until this leg hits its cap at today's measured rate, or a null and why not.

    The order of the refusals is the order of the questions an operator asks, and EVERY branch
    that cannot produce a number produces a sentence instead. `rate_per_h` is deliberately absent
    (None) in those branches too: a rate printed beside "no projection" invites the reader to do
    the division themselves on a denominator we just said was too small.
    """
    out = {"rate_per_h": None, "hit_in_h": None, "hit_at": None,
           "hits_today": None, "reason": "", "caveat": ""}
    if blocked:
        out["reason"] = blocked
        return out
    if cap_usd <= 0:
        out["reason"] = (f"no ceiling configured ({cap_key} = {cap_usd:g}) — this leg is reported, "
                         f"not enforced, so there is nothing to project a hit against")
        return out
    if usd >= cap_usd:
        out["reason"] = (f"already at or above the ceiling: ${usd:.4f} >= ${cap_usd:.2f} "
                         f"({cap_key}). The rail is refusing work NOW, not at a projected time")
        return out
    if elapsed_h < MIN_ELAPSED_H:
        out["reason"] = (f"only {elapsed_h * 60:.0f} min of the local day has elapsed; a rate "
                         f"measured over less than {MIN_ELAPSED_H:g}h is one burst, not a trend")
        return out
    if usd <= 0:
        out["reason"] = (f"no spend recorded in the {elapsed_h:.1f}h of the day so far, so there "
                         f"is no rate to project — this is a measured zero, not an unread one")
        return out

    rate = usd / elapsed_h
    hit_in_h = (cap_usd - usd) / rate
    out["rate_per_h"] = round(rate, 6)
    out["hit_in_h"] = round(hit_in_h, 3)
    out["hit_at"] = _iso(now + hit_in_h * 3600.0)
    out["hits_today"] = hit_in_h <= hours_left_today
    if not out["hits_today"]:
        # THE COUNTER RESETS AT LOCAL MIDNIGHT. A projection that lands past it describes a cap
        # that will not be reached today at this rate — saying "hits in 19h" without that is a
        # true number that answers a different question than the one being asked.
        out["caveat"] = (f"projection lands ~{hit_in_h - hours_left_today:.1f}h past local "
                         f"midnight, when the daily counter resets; at today's rate this "
                         f"ceiling is not reached today")
    return out


# --------------------------------------------------------------------------- #
# Roles — what a leg's money can honestly be attributed to
# --------------------------------------------------------------------------- #
def _leg_for_tier(cfg, name: str) -> str:
    """'metered' | 'subscription' | 'unmetered' — which leg of the ledger this tier writes to."""
    if name in SUBSCRIPTION_TIERS:
        return "subscription"
    try:
        from prospector import telemetry as _t

        price = _t.get_price(name, cfg=cfg)
        if float(price.get("input", 0) or 0) > 0 or float(price.get("output", 0) or 0) > 0:
            return "metered"
    except Exception:  # noqa: BLE001 — a pricing lookup may never take the panel down
        return "unmetered"
    return "unmetered"


def _chains(cfg) -> list[tuple[str, list[str], str]]:
    """The configured chains, from the read model — NOT rebuilt here.

    `readmodel._configured_chains` already asks `run._noncritical_order(cfg)` rather than reading
    the config value, because that function STRIPS forbidden tiers: the config line and the chain
    the process builds are different lists. Deriving the roster a second time in this module is
    precisely what R23 forbids, and the way a console comes to name a chain the engine does not
    run. An empty list (an older read model) degrades to no role table, never to a guess.
    """
    from prospector.ops import readmodel as _rm

    builder = getattr(_rm, "_configured_chains", None)
    if not callable(builder):
        return []
    try:
        return list(builder(cfg))
    except (AttributeError, KeyError, TypeError, ValueError):
        # An OLDER read model whose shape this call does not fit — the documented degraded
        # mode above. Narrow, so a real bug in `_configured_chains` is not read as one.
        return []


def _tier_split(cfg, leg_usd: dict[str, float], chains) -> list[dict]:
    """Per-TIER spend — the finest split the cached scan can actually support.

    WHY THIS LAYER EXISTS. On the live roster (2026-08-16) `minimax` serves verdict, noncritical,
    artifact and marketing, so `_role_split` is honestly null for every role and a panel showing
    only that answers nothing. But a LEG carrying exactly one tier is fully attributable to it: on
    that same roster the whole metered leg is minimax's and the whole subscription leg is
    claude_cli's, and those two numbers are exact rather than apportioned. When a leg carries two
    metered tiers (minimax + deepseek, the shape this estate had until 2026-08-15) the split
    between them is not in the cache and the honest answer is a null naming the sharer — the same
    rule, applied one level down.
    """
    tiers: dict[str, dict] = {}
    for role, names, _file in chains:
        for pos, name in enumerate(names):
            entry = tiers.setdefault(name, {"name": name, "leg": _leg_for_tier(cfg, name),
                                            "roles": []})
            entry["roles"].append(f"{role}#{pos}")

    on_leg: dict[str, list[str]] = {}
    for entry in tiers.values():
        on_leg.setdefault(entry["leg"], []).append(entry["name"])

    for entry in tiers.values():
        leg = entry["leg"]
        if leg == "unmetered":
            entry.update(usd=0.0, attributable=True,
                         reason="unpriced — this tier emits no ledger spend row at all")
            continue
        sharers = [n for n in on_leg[leg] if n != entry["name"]]
        if sharers:
            entry.update(usd=None, attributable=False,
                         reason=f"the {leg} leg is shared with {', '.join(sorted(sharers))}; the "
                                f"cached scan buckets by day and leg, not by provider")
        else:
            entry.update(usd=round(float(leg_usd.get(leg, 0.0) or 0.0), 6), attributable=True,
                         reason=f"sole tier on the {leg} leg, so the whole leg is its spend")
    return sorted(tiers.values(), key=lambda t: (t["leg"], t["name"]))


def _role_split(cfg, leg_usd: dict[str, float], chains) -> list[dict]:
    """Per-role spend, attributed only where the attribution is SOUND.

    WHAT CAN AND CANNOT BE KNOWN, exactly. The cached scan buckets the ledger by calendar day and
    by leg — it does not bucket by provider or by phase (`guard._scan`). So a role's dollar figure
    is derivable only when that role is the SOLE role billing into a leg; when one tier serves two
    roles (live on 2026-08-16: `minimax` heads both `verdict` and `noncritical`) the leg's money
    cannot be split between them from anything cached, and the honest output is a null naming the
    tier that makes it ambiguous.

    The alternative — a second, provider-keyed parse of the 193 MB ledger — is the thing rule 1 of
    this module forbids, and `telemetry`'s in-process `by_provider` counters are worse than
    nothing here: a freshly-started console reads ~0 for a day the daemon really spent on, which
    is the exact failure `guard`'s docstring records for in-process telemetry.
    """
    roles: list[dict] = []
    # leg -> the roles that bill into it, and the tiers that put them there.
    owners: dict[str, dict[str, list[str]]] = {}
    for role, tiers, _file in chains:
        entry = {"role": role,
                 "tiers": [{"name": n, "position": i, "leg": _leg_for_tier(cfg, n)}
                           for i, n in enumerate(tiers)]}
        entry["legs"] = sorted({t["leg"] for t in entry["tiers"] if t["leg"] != "unmetered"})
        roles.append(entry)
        for t in entry["tiers"]:
            if t["leg"] == "unmetered":
                continue
            owners.setdefault(t["leg"], {}).setdefault(role, []).append(t["name"])

    for entry in roles:
        usd = 0.0
        reasons: list[str] = []
        for leg in entry["legs"]:
            sharers = owners.get(leg, {})
            if len(sharers) == 1:
                usd += float(leg_usd.get(leg, 0.0) or 0.0)
                continue
            shared_tiers = sorted({n for r, names in sharers.items()
                                   if r != entry["role"] for n in names
                                   if n in set(t["name"] for t in entry["tiers"])})
            others = sorted(r for r in sharers if r != entry["role"])
            reasons.append(
                f"the {leg} leg is shared with {', '.join(others)}"
                + (f" via {', '.join(shared_tiers)}" if shared_tiers else "")
                + "; the cached scan buckets by day and leg, not by provider, so its "
                  "${:.4f} cannot be split between them".format(float(leg_usd.get(leg, 0.0) or 0.0))
            )
        if not entry["legs"]:
            entry.update(usd=0.0, attributable=True,
                         reason="no metered or subscription tier in this chain — it writes no "
                                "spend rows at all")
        elif reasons:
            entry.update(usd=None, attributable=False, reason=" · ".join(reasons))
        else:
            entry.update(usd=round(usd, 6), attributable=True,
                         reason=f"sole role billing into: {', '.join(entry['legs'])}")
    return roles


# --------------------------------------------------------------------------- #
# The view
# --------------------------------------------------------------------------- #
def spend_view(cfg, *, now: Optional[float] = None) -> dict:
    """Today's two spend legs against their configured ceilings, with projections and roles.

    The metered figure is `SchedulerGuard.scan_today()[0]` verbatim — the same call, on the same
    store, that `guard.evaluate()` gates the daemon on. Not "reconciles to": IS. `today` is pinned
    to the local day derived from `now` and handed to the guard, so the view and the rail can
    never sum different calendar days by accident.
    """
    from prospector.scheduler import guard as _guard

    now = time.time() if now is None else now
    day, elapsed_h, hours_left = _local_day_bounds(now)
    guard = _guard.guard_from_config(cfg, today=day)

    ledger = guard.ledger_path
    try:
        ledger_size = ledger.stat().st_size
        ledger_present = True
    except OSError:
        ledger_size, ledger_present = None, False

    # The checkpoint AS FOUND, read before the scan refreshes it — so `lag_bytes` describes what
    # this page inherited rather than what it left behind.
    cache = _cache_state(guard, ledger_size)

    metered, subscription = guard.scan_today()   # THE probe call. One reader, no second parse.
    days = guard.spend_by_day()

    warnings: list[str] = []
    blocked = ""
    if not ledger_present:
        # ABSENT IS UNREADABLE, NOT UNSPENT. `scan_today()` answers (0.0, 0.0) for a missing file
        # exactly as it does for a quiet day, and only the caller can tell the operator which.
        blocked = (f"no ledger at {ledger} — $0.00 here means UNREADABLE, not unspent")
        warnings.append(blocked)
    newest = max(days) if days else ""
    if newest and day < newest:
        # The clock-fault gate `guard.evaluate()` refuses to generate on: the cap is summing a day
        # the ledger cannot have rows for, so it reads $0.00 whatever was really spent.
        blocked = (f"clock is behind the ledger: today reads {day} but this store already has "
                   f"rows dated {newest}, so today's figure is structurally $0.00 and neither "
                   f"the cap nor a projection means anything until the clock is fixed")
        warnings.append(blocked)
    if not cache["present"] and ledger_present:
        warnings.append(
            f"no scan checkpoint at {cache['path']} — the next read is a FULL pass over the "
            f"{(ledger_size or 0) / 1e6:.0f} MB ledger (measured 108 s on 157 MB)")

    spend_cfg = getattr(cfg, "spend", None)
    warn_at = _f(getattr(spend_cfg, "warn_at_usd", 0.0))
    legs = {
        "metered": _leg(
            usd=metered, cap_usd=guard.daily_cap_usd, cap_key=CAP_KEY, warn_at=warn_at,
            warn_key=WARN_KEY, enforced=guard.daily_cap_usd > 0, now=now, elapsed_h=elapsed_h,
            hours_left=hours_left, blocked=blocked,
            what="billed money — metered API providers. This is the liability rail: at the cap "
                 "the guard refuses the tick, which stalls the queue rather than overspending."),
        "subscription": _leg(
            usd=subscription, cap_usd=guard.daily_subscription_cap_usd,
            cap_key=SUBSCRIPTION_CAP_KEY, warn_at=0.0, warn_key="",
            enforced=guard.daily_subscription_cap_usd > 0, now=now, elapsed_h=elapsed_h,
            hours_left=hours_left, blocked=blocked,
            what="Claude Code CLI burn (`cost_usd`, no `event` key) — subscription-equivalent, "
                 "NOT invoiced. Reported always; enforced only if a cap is armed."),
    }

    # The roster is derived ONCE and handed to both splits: asking for it twice is the second
    # derivation R23 forbids, and is how two tables on one page come to disagree about the chain.
    chains = _chains(cfg)
    leg_usd = {"metered": metered, "subscription": subscription}

    history = {d: {"metered": v[0], "subscription": v[1]}
               for d, v in sorted(days.items(), reverse=True)}
    return {
        "now": _iso(now),
        "day": day,
        "day_note": "LOCAL calendar day — the day the cap sums over (guard uses date.today())",
        "elapsed_h": round(elapsed_h, 3),
        "hours_left_today": round(hours_left, 3),
        "source": "prospector.scheduler.guard.SchedulerGuard.scan_today()",
        "ledger": {"path": str(ledger), "present": ledger_present, "size_bytes": ledger_size},
        "cache": cache,
        "legs": legs,
        "roles": _role_split(cfg, leg_usd, chains),
        "tiers": _tier_split(cfg, leg_usd, chains),
        "history": history,
        "history_horizon_note": (
            "the checkpoint keeps only the newest 30 days; an older day being absent here is "
            "'not retained', never $0. PROSPECTOR_GUARD_FULL_SCAN=1 forces the whole file."),
        "warnings": warnings,
    }


def _f(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _leg(*, usd: float, cap_usd: float, cap_key: str, warn_at: float, warn_key: str,
         enforced: bool, now: float, elapsed_h: float, hours_left: float, blocked: str,
         what: str) -> dict:
    """One spend leg: the figure, its ceiling (from config), its state and its projection."""
    cap_usd = _f(cap_usd)
    pct = round(100.0 * usd / cap_usd, 2) if cap_usd > 0 else None
    if not enforced:
        state = "uncapped"
    elif usd >= cap_usd:
        state = "at_cap"
    elif warn_at > 0 and usd >= warn_at:
        state = "warn"
    else:
        state = "ok"
    return {
        "usd": usd,
        "cap_usd": cap_usd,
        "cap_key": cap_key,
        "warn_at_usd": warn_at or None,
        "warn_key": warn_key or None,
        "enforced": enforced,
        "pct_of_cap": pct,
        # The renderer draws a bar from this rather than dividing by 100 itself: every number on
        # the page comes from the model, so there is one place a cap arithmetic bug can live.
        "fraction_of_cap": round(min(usd / cap_usd, 1.0), 6) if cap_usd > 0 else None,
        "remaining_usd": round(cap_usd - usd, 6) if cap_usd > 0 else None,
        "state": state,
        "what": what,
        "projection": _project(usd=usd, cap_usd=cap_usd, cap_key=cap_key, elapsed_h=elapsed_h,
                               hours_left_today=hours_left, now=now, blocked=blocked),
    }


def _cache_state(guard, ledger_size: Optional[int]) -> dict:
    """The scan checkpoint as found on disk. Unreadable/absent is reported, never raised.

    This is the receipt for "reads the cached scan, never the 193 MB ledger inline": `offset` is
    how far into the ledger the last scan got, and `lag_bytes` is what the next incremental pass
    must still read. A torn or foreign checkpoint reads as absent here for the same reason
    `guard._load_scan_cache` treats it as a full re-scan — a cache that cannot be proven to
    describe this file is worth less than the seconds it saves.
    """
    path = guard.scan_cache_path
    out = {"path": str(path), "present": False, "offset": None, "lag_bytes": None,
           "newest_day": None}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    try:
        offset = int(raw.get("offset", 0))
    except (TypeError, ValueError):
        return out
    out["present"] = True
    out["offset"] = offset
    out["newest_day"] = raw.get("newest") or None
    if ledger_size is not None:
        out["lag_bytes"] = max(ledger_size - offset, 0)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m prospector.ops.spend [--json]` — the same view, for a surface that is not Python."""
    import argparse

    ap = argparse.ArgumentParser(description="Per-role spend split vs the cap (R21)")
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)
    print(json.dumps(spend_view(load_cfg(args.config)), indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
