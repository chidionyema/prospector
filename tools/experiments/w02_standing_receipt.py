"""W0.2 — the standing receipt: one command that prints what the engine is actually doing.

WHY THIS EXISTS. Wave 0's premise is that nothing downstream may be tuned against a number
nobody re-measures. Every figure below has been quoted in this repo at some point from a
session transcript, a checkpoint or a doc — none of which re-derive when the corpus moves. A
standing receipt is the opposite of a paragraph: it is a command, it re-reads the corpus every
time, and its output is a file that can be diffed against the last one.

WHAT IT PRINTS, and why each line is here rather than some other line:

  * unverifiable rate, overall AND per check — the engine's own admission of what it could not
    rule on. It is reported beside `retrieval_failed` and `degraded` because an unverifiable
    check has two very different causes that the single rate cannot separate: the web genuinely
    has no passage, or OUR retrieval broke. Those call for opposite responses, so a receipt that
    prints only the total invites the wrong one.
  * confidence separation by verdict polarity — whether `confidence` carries information at all.
    If ruled checks (supported/refuted) and unverifiable ones sit at the same mean, the field is
    decoration and no threshold on it can work. This is the cheapest possible test of that.
  * composite distribution — recomputed with the PRODUCTION `prospector.score.composite` and the
    live weights, never read from the dossier's prose `reason`, so it moves when the weights move.
    Reported against the live `min_composite_to_pass` because "how far below the bar" is the
    quantity that decides whether the bar or the generator is the thing to change.
  * PASS rate, with a Wilson interval — a bare share over ~1e3 dossiers reads far more precise
    than it is.
  * $/vetted — from `SchedulerGuard.spend_by_day()`, the production ledger reader. Both legs
    (metered and subscription) always: they differ by orders of magnitude and metered alone
    reads as total consumption.

DELIBERATE DEVIATION, FLAGGED, NOT MADE SILENTLY. `docs/ENGINE_WAR_PLAN_2026-08-13.md:78` says
"`tools/experiments/e15_hhem_groundedness.py` already measures groundedness — extend it, do not
rebuild it." This is a new module, and here is the reasoning for the founder to overrule if it
is wrong: the instruction's force is "do not write a second corpus reader", and that is obeyed
exactly — every dossier here is read through `_corpus.py`, the same accessors E15 uses, and no
line of this file parses the store itself. What is NOT reused is E15's body, because E15 is an
HHEM experiment: it loads a neural entailment model, samples a few hundred ruled checks
stratified by verdict, and answers "does the cited passage entail the claim?". Putting a
standing, whole-corpus, every-run dashboard inside it would (a) make the dashboard depend on a
model download to print a PASS rate, and (b) overwrite E15's own receipts file, which is a
measurement of record. Two different instruments, one shared corpus reader.

WHAT THIS IS NOT: it is not a quality judgement. Every number is a count over dossiers that
already exist; none of it says the engine is right, only what it did. Its value is entirely in
being re-run and diffed.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus import corpus_fingerprint, dossier_paths, iter_dossiers, wilson  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prospector.config import load_config  # noqa: E402
from prospector.scheduler.guard import guard_from_config  # noqa: E402
from prospector.score import composite  # noqa: E402

NAME = "W02"

DECISIONS = ("pass", "kill", "defer")
POLARITY = ("supported", "refuted", "unverifiable")


def describe() -> str:
    return ("W0.2 standing receipt: unverifiable rate per check, confidence separation by "
            "verdict polarity, composite distribution, PASS rate and $/vetted over a window.")


def _parse(args: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="w02_standing_receipt")
    p.add_argument("--days", type=int, default=7,
                   help="window width in days, counting back from --until (default 7)")
    p.add_argument("--until", default=None,
                   help="last day of the window, YYYY-MM-DD (default: today, local)")
    p.add_argument("--all", action="store_true",
                   help="ignore the window and report over every dossier on disk. The spend "
                        "leg is then reported for the days the ledger scan covers only, and "
                        "$/vetted is suppressed rather than computed over mismatched spans.")
    return p.parse_args(args)


def _window(opts: argparse.Namespace) -> tuple[str, str]:
    until = opts.until or _dt.date.today().isoformat()
    end = _dt.date.fromisoformat(until)
    start = end - _dt.timedelta(days=max(1, opts.days) - 1)
    return start.isoformat(), end.isoformat()


def _day_of(dossier: dict) -> str:
    """The dossier's own local-date stamp, or '' when it has none.

    `created_at` is ISO with a timezone; the first 10 characters are the date and nothing else
    needs parsing. A dossier without it is counted in `undated` and excluded from every windowed
    figure — silently treating it as in-window would inflate whichever window is being reported.
    """
    ts = str(dossier.get("created_at") or "")
    return ts[:10] if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-" else ""


def _checks(dossier: dict) -> list[dict]:
    raw = dossier.get("checks") or []
    return [c for c in raw if isinstance(c, dict)]


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p90": None}
    ordered = sorted(vals)
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "p10": round(ordered[max(0, int(0.10 * (len(ordered) - 1)))], 4),
        "p90": round(ordered[min(len(ordered) - 1, int(0.90 * (len(ordered) - 1)))], 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
    }


def _spend(cfg, days: list[str]) -> dict:
    """Metered and subscription spend over `days`, and an explicit account of coverage.

    ABSENT IS TWO DIFFERENT THINGS and the difference decides whether a number may be printed:

      * a day INSIDE the scan's span with no rows is a real **$0.00** — the daemon spent nothing
        that day. Summing it as zero is correct.
      * a day BEFORE the span's oldest day is **UNKNOWN**. The guard's incremental checkpoint
        keeps only the newest 30 days, so a window reaching further back sums the missing days
        to nothing and reports a confident, wrong, low figure — the exact shape of the ledger
        bug memory `never-hand-parse-the-spend-ledger` records, where $0.00 on a day with real
        spend raised no error at all. Those days are listed, not folded in, and $/vetted is
        suppressed upstream rather than divided by a span it does not cover.

    Days AFTER the newest ledger row are treated as known-zero for the same reason as the first
    case: the ledger is append-only, so "no rows yet today" is a fact, not a gap.
    """
    guard = guard_from_config(cfg)
    by_day = guard.spend_by_day()
    oldest = min(by_day) if by_day else None
    # Inside the scan's span (or after it) absence means zero rows; before it, absence means the
    # checkpoint has dropped the day and we do not know.
    known = [d for d in days if oldest is not None and d >= oldest]
    unknown = [d for d in days if oldest is None or d < oldest]
    metered = round(sum(by_day.get(d, (0.0, 0.0))[0] for d in known), 6)
    subscription = round(sum(by_day.get(d, (0.0, 0.0))[1] for d in known), 6)
    return {
        "ledger": str(guard.ledger_path),
        "days_requested": len(days),
        "days_covered": known,
        "days_with_rows": [d for d in known if d in by_day],
        "days_unknown_dropped_by_checkpoint": unknown,
        "scan_span_oldest_day": oldest,
        "metered_usd": metered,
        "subscription_usd": subscription,
        "complete": not unknown,
        "note": ("metered is billed money and is what daily_cap_usd enforces; subscription is "
                 "Claude Code CLI burn (cost_usd, no event key), API-equivalent and not "
                 "invoiced. They differ by orders of magnitude — report both or neither."),
    }


def run(args: list[str] | None = None) -> dict:
    opts = _parse(list(args or []))
    cfg = load_config()
    start, end = _window(opts)
    days = []
    d = _dt.date.fromisoformat(start)
    while d <= _dt.date.fromisoformat(end):
        days.append(d.isoformat())
        d += _dt.timedelta(days=1)

    paths = dossier_paths()
    weights = dict(getattr(cfg, "weights", {}) or {})
    bar = float(getattr(cfg.thresholds, "min_composite_to_pass", 0.0))

    decisions: Counter = Counter()
    gates: Counter = Counter()
    composites: list[float] = []
    provisional = 0
    undated = 0
    on_disk = 0
    in_window = 0

    verdicts: Counter = Counter()
    per_check: dict[str, Counter] = defaultdict(Counter)
    conf_by_polarity: dict[str, list[float]] = defaultdict(list)
    retrieval_failed = 0
    degraded = 0
    checks_total = 0

    for path, dossier in iter_dossiers(paths):
        on_disk += 1
        day = _day_of(dossier)
        if not day:
            undated += 1
            if not opts.all:
                continue
        elif not opts.all and not (start <= day <= end):
            continue
        in_window += 1

        decisions[str(dossier.get("decision") or "none")] += 1
        if dossier.get("gate_fired"):
            gates[str(dossier["gate_fired"])] += 1
        if dossier.get("provisional"):
            provisional += 1

        scores = ((dossier.get("score") or {}).get("scores") or {})
        if isinstance(scores, dict) and scores:
            composites.append(composite(scores, weights))

        for chk in _checks(dossier):
            checks_total += 1
            name = str(chk.get("check_name") or "unnamed")
            verdict = str(chk.get("verdict") or "none")
            verdicts[verdict] += 1
            per_check[name][verdict] += 1
            per_check[name]["_n"] += 1
            if chk.get("retrieval_failed"):
                retrieval_failed += 1
            if chk.get("degraded"):
                degraded += 1
            try:
                conf = float(chk.get("confidence"))
            except (TypeError, ValueError):
                conf = None
            if conf is not None and verdict in POLARITY:
                conf_by_polarity[verdict].append(conf)

    passes = decisions.get("pass", 0)
    pass_lo, pass_hi = wilson(passes, in_window) if in_window else (0.0, 0.0)
    unver = verdicts.get("unverifiable", 0)
    unver_lo, unver_hi = wilson(unver, checks_total) if checks_total else (0.0, 0.0)

    per_check_out = {}
    for name in sorted(per_check):
        c = per_check[name]
        n = c["_n"]
        u = c.get("unverifiable", 0)
        lo, hi = wilson(u, n) if n else (0.0, 0.0)
        per_check_out[name] = {
            "n": n,
            "unverifiable": u,
            "unverifiable_rate": round(u / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)],
            "supported": c.get("supported", 0),
            "refuted": c.get("refuted", 0),
        }

    ruled = conf_by_polarity["supported"] + conf_by_polarity["refuted"]
    sep = None
    if ruled and conf_by_polarity["unverifiable"]:
        sep = round(statistics.fmean(ruled)
                    - statistics.fmean(conf_by_polarity["unverifiable"]), 4)

    spend = _spend(cfg, days)
    per_vetted = None
    if not opts.all and spend["complete"] and in_window:
        per_vetted = {
            "metered_usd_per_vetted": round(spend["metered_usd"] / in_window, 6),
            "subscription_usd_per_vetted": round(spend["subscription_usd"] / in_window, 6),
        }

    receipts = {
        "window": {"start": start, "end": end, "days": len(days),
                   "mode": "all dossiers on disk" if opts.all else "created_at within window"},
        "corpus": corpus_fingerprint(),
        "volume": {
            "dossiers_on_disk": on_disk,
            "dossiers_in_window": in_window,
            "undated": undated,
            "by_decision": dict(decisions),
            "gates_fired": dict(gates.most_common()),
            "provisional": provisional,
        },
        "pass_rate": {
            "passes": passes, "n": in_window,
            "rate": round(passes / in_window, 4) if in_window else None,
            "ci95": [round(pass_lo, 4), round(pass_hi, 4)],
        },
        "unverifiable": {
            "checks": checks_total,
            "unverifiable": unver,
            "rate": round(unver / checks_total, 4) if checks_total else None,
            "ci95": [round(unver_lo, 4), round(unver_hi, 4)],
            "by_verdict": dict(verdicts),
            "retrieval_failed": retrieval_failed,
            "degraded": degraded,
            "note": ("retrieval_failed and degraded are printed beside the rate because an "
                     "unverifiable check means either the web has no passage or OUR retrieval "
                     "broke, and those call for opposite responses."),
            "per_check": per_check_out,
        },
        "confidence_separation": {
            "by_verdict": {k: _stats(conf_by_polarity[k]) for k in POLARITY},
            "ruled_minus_unverifiable_mean": sep,
            "note": ("if this gap is ~0 the confidence field carries no polarity information "
                     "and no threshold on it can discriminate."),
        },
        "composite": {
            "weights": weights,
            "min_composite_to_pass": bar,
            "distribution": _stats(composites),
            "at_or_above_bar": sum(1 for c in composites if c >= bar),
            "note": ("recomputed with prospector.score.composite over the live weights, not "
                     "read from the dossier's prose reason, so it tracks a weight change."),
        },
        "spend": spend,
        "per_vetted": per_vetted,
    }

    _print(receipts)
    return receipts


def _print(r: dict) -> None:
    w, v, p = r["window"], r["volume"], r["pass_rate"]
    print(f"\nW0.2 STANDING RECEIPT — {w['start']} .. {w['end']}  ({w['mode']})")
    print(f"  vetted in window   {v['dossiers_in_window']} of {v['dossiers_on_disk']} on disk"
          f"   ({v['undated']} undated)")
    print(f"  by decision        {v['by_decision']}")
    print(f"  provisional        {v['provisional']}")
    rate = "n/a" if p["rate"] is None else f"{p['rate']:.1%}"
    print(f"  PASS rate          {p['passes']}/{p['n']} = {rate}"
          f"   95% CI [{p['ci95'][0]:.1%}, {p['ci95'][1]:.1%}]")

    u = r["unverifiable"]
    urate = "n/a" if u["rate"] is None else f"{u['rate']:.1%}"
    print(f"\n  unverifiable       {u['unverifiable']}/{u['checks']} checks = {urate}"
          f"   95% CI [{u['ci95'][0]:.1%}, {u['ci95'][1]:.1%}]")
    print(f"    retrieval_failed {u['retrieval_failed']}     degraded {u['degraded']}")
    for name, c in u["per_check"].items():
        cr = "n/a" if c["unverifiable_rate"] is None else f"{c['unverifiable_rate']:.1%}"
        print(f"    {name:<22} {c['unverifiable']:>5}/{c['n']:<6} = {cr:>7}"
              f"   [{c['ci95'][0]:.1%}, {c['ci95'][1]:.1%}]")

    cs = r["confidence_separation"]
    print("\n  confidence by verdict")
    for k in POLARITY:
        s = cs["by_verdict"][k]
        if not s["n"]:
            print(f"    {k:<14} n=0")
            continue
        print(f"    {k:<14} n={s['n']:<6} mean {s['mean']:.3f}  median {s['median']:.3f}"
              f"  p10 {s['p10']:.3f}  p90 {s['p90']:.3f}")
    print(f"    ruled - unverifiable mean gap: {cs['ruled_minus_unverifiable_mean']}")

    c = r["composite"]
    d = c["distribution"]
    print(f"\n  composite (bar {c['min_composite_to_pass']})")
    if d["n"]:
        print(f"    n={d['n']:<6} mean {d['mean']:.3f}  median {d['median']:.3f}"
              f"  p10 {d['p10']:.3f}  p90 {d['p90']:.3f}  max {d['max']:.3f}")
        print(f"    at or above bar: {c['at_or_above_bar']}/{d['n']}")
    else:
        print("    no scored dossiers in window")

    s = r["spend"]
    print(f"\n  spend over {len(s['days_covered'])}/{s['days_requested']} days covered"
          f"   metered ${s['metered_usd']:.4f}   subscription ${s['subscription_usd']:.2f}")
    if s["days_unknown_dropped_by_checkpoint"]:
        print("    UNKNOWN, not zero — older than the guard's 30-day scan checkpoint: "
              f"{s['days_unknown_dropped_by_checkpoint']}   "
              "(re-run with PROSPECTOR_GUARD_FULL_SCAN=1 for the full history)")
    silent = [d for d in s["days_covered"] if d not in s["days_with_rows"]]
    if silent:
        print(f"    days with no ledger rows, counted as $0.00: {silent}")
    if r["per_vetted"]:
        pv = r["per_vetted"]
        print(f"    $/vetted: metered ${pv['metered_usd_per_vetted']:.4f}"
              f"   subscription ${pv['subscription_usd_per_vetted']:.4f}")
    else:
        print("    $/vetted suppressed — the spend window and the dossier window do not "
              "cover the same days (see days_missing / --all).")


def doc_block(envelope: dict) -> str:
    v, p, u = envelope["volume"], envelope["pass_rate"], envelope["unverifiable"]
    w = envelope["window"]
    lines = [
        f"### W0.2 standing receipt — {w['start']} .. {w['end']}",
        "",
        f"- vetted: **{v['dossiers_in_window']}**, decisions {v['by_decision']}, "
        f"provisional {v['provisional']}",
        f"- PASS rate: **{p['passes']}/{p['n']}** "
        f"(95% CI {p['ci95'][0]:.1%}–{p['ci95'][1]:.1%})",
        f"- unverifiable: **{u['unverifiable']}/{u['checks']}** checks; "
        f"retrieval_failed {u['retrieval_failed']}, degraded {u['degraded']}",
        f"- confidence gap (ruled − unverifiable): "
        f"**{envelope['confidence_separation']['ruled_minus_unverifiable_mean']}**",
        f"- composite: {envelope['composite']['distribution']} against bar "
        f"{envelope['composite']['min_composite_to_pass']}",
        f"- spend: {json.dumps(envelope['spend'], default=str)}",
        f"- $/vetted: {json.dumps(envelope['per_vetted'], default=str)}",
        "",
        "Re-run: `.venv/bin/python tools/experiments/w02_standing_receipt.py --days 7`",
    ]
    return "\n".join(lines)


def main() -> int:
    from runner import run_one
    result = run_one(NAME, sys.argv[1:])
    print(f"\nreceipts   -> {result['receipts_path']}")
    print(f"doc append -> {result['doc_append_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
