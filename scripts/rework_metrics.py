#!/usr/bin/env python3
"""Measure rework, so the efficiency scoreboard cannot be gamed by cutting corners.

`/method` grades the agents on cost: output tokens per tool call, peak resident context, round
trips per session. Every one of those improves if the work gets sloppier. An agent that skips a
test, ships the first guess and moves on scores BETTER on all of them, and the scoreboard would
call that progress right up until production broke.

So the cost numbers need a guard beside them. This is that guard, and it is deliberately a
different kind of measurement -- git history rather than session transcripts -- because a metric
and its guard sharing a source can fail together.

Two numbers, per month, over a bounded window:

  fix_share      fix/revert commits as a share of all commits. Blunt: a fix commit may be
                 repairing a two-year-old bug, which is not rework of recent work at all.

  fast_rework    fix/revert commits that touch a file some other commit touched within the
                 previous FAST_WINDOW_DAYS. This is the honest one. It says: we changed this
                 file, and within a fortnight we had to come back and fix it.

How to read them TOGETHER with the cost numbers, which is the only way they mean anything:

  cost down, rework flat or down   the method genuinely improved
  cost down, rework UP             the loop is training for cheapness at the cost of correctness
  cost up,   rework down           bought quality with tokens; a choice, not a failure

Read-only. Writes one JSON file and prints a summary. Never touches the working tree.

  .venv/bin/python scripts/rework_metrics.py            # print, and write store/ops/rework_metrics.json
  .venv/bin/python scripts/rework_metrics.py --json -   # print the JSON to stdout instead
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "store" / "ops" / "rework_metrics.json"

#: How recently a file must have been touched for a later fix to count as rework of recent work.
#: A fortnight, because that is roughly the horizon over which this estate ships and re-ships a
#: thing. Widen it and every fix looks like rework; narrow it and only same-week churn counts.
FAST_WINDOW_DAYS = 14

#: How far back to measure. Longer costs nothing extra (one git call) but dilutes the trend with
#: a period whose method no longer exists.
WINDOW_DAYS = 180

#: A commit is rework if its subject starts one of these. This repo uses conventional commits, so
#: the prefix is reliable; `revert` covers the case where the fix was to undo the change entirely.
_REWORK_PREFIXES = ("fix(", "fix:", "revert", "hotfix")

#: Files whose churn says nothing about engineering quality. Runtime state and generated output
#: change on every run, so a fix that touches them would count as rework of work nobody did.
_IGNORED_PREFIXES = ("store/", "storage/", "graphify-out/", "docs/doc_lint_baseline.json")


def _git(args: list[str]) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _is_rework(subject: str) -> bool:
    s = subject.strip().lower()
    return s.startswith(_REWORK_PREFIXES)


def read_history(ref: str, days: int) -> list[dict]:
    """Every commit on `ref`'s first-parent line in the window, with the files it touched.

    First-parent on purpose: a merge brings a branch's commits in, and counting both the branch
    commits and the merge would double-count the same work. First-parent counts each merged
    branch once, which is the unit a PR ships.

    One git call for the whole window. The alternative -- asking git per commit -- is hundreds of
    process spawns and was the reason an earlier draft of this took minutes.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    raw = _git(["log", "--first-parent", ref, f"--since={since}",
                "--pretty=format:\x01%H\t%aI\t%s", "--name-only"])
    commits: list[dict] = []
    cur: dict | None = None
    for line in raw.splitlines():
        if line.startswith("\x01"):
            sha, iso, subject = (line[1:].split("\t", 2) + ["", ""])[:3]
            cur = {"sha": sha, "iso": iso, "subject": subject, "files": []}
            commits.append(cur)
        elif line.strip() and cur is not None:
            f = line.strip()
            if not f.startswith(_IGNORED_PREFIXES):
                cur["files"].append(f)
    return commits


def measure(commits: list[dict]) -> dict:
    """Fold the history into per-month counts.

    `fast_rework` needs, for each file, the times it was touched. Building that index once and
    binary-searching it keeps this linear; scanning the history per fix commit would be quadratic
    and this runs on a console request.
    """
    touched: dict[str, list[str]] = defaultdict(list)
    for c in reversed(commits):  # oldest first, so each list is already sorted
        for f in c["files"]:
            touched[f].append(c["iso"])

    per_month: dict[str, dict] = defaultdict(
        lambda: {"commits": 0, "rework": 0, "fast_rework": 0})
    examples: list[dict] = []

    for c in commits:
        month = c["iso"][:7]
        row = per_month[month]
        row["commits"] += 1
        if not _is_rework(c["subject"]):
            continue
        row["rework"] += 1

        try:
            when = datetime.fromisoformat(c["iso"])
        except ValueError:
            continue
        cutoff = (when - timedelta(days=FAST_WINDOW_DAYS)).isoformat()
        hit = None
        for f in c["files"]:
            stamps = touched.get(f) or []
            i = bisect_left(stamps, cutoff)
            # Any touch of this file in [cutoff, this commit) is prior recent work.
            if any(cutoff <= s < c["iso"] for s in stamps[i:]):
                hit = f
                break
        if hit:
            row["fast_rework"] += 1
            if len(examples) < 8:
                examples.append({"sha": c["sha"][:8], "date": c["iso"][:10],
                                 "subject": c["subject"][:90], "file": hit})

    months = []
    for m in sorted(per_month):
        r = per_month[m]
        n = r["commits"]
        months.append({
            "month": m,
            "commits": n,
            "rework": r["rework"],
            "fast_rework": r["fast_rework"],
            "fix_share": round(100 * r["rework"] / n, 1) if n else None,
            "fast_rework_share": round(100 * r["fast_rework"] / n, 1) if n else None,
        })

    latest = months[-1] if months else {}

    # A shallow clone truncates the window without saying so. Measured 2026-08-19: a worktree
    # shallow to 2026-08-14 answered a 180-day request with 5 days of history and bucketed it
    # as the month "2026-08" -- a partial month read as a monthly rate is a wrong number, not a
    # missing one. The oldest commit actually seen is the honest bound, so it travels, and the
    # month containing it is flagged partial.
    oldest = commits[-1]["iso"] if commits else None
    shallow = _git(["rev-parse", "--is-shallow-repository"]).strip() == "true"
    for m in months:
        m["partial"] = bool(oldest) and m["month"] == oldest[:7] and (shallow or len(months) == 1)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": WINDOW_DAYS,
        "fast_window_days": FAST_WINDOW_DAYS,
        "oldest_commit": oldest,
        "shallow_clone": shallow,
        "coverage_note": (
            f"History starts at {oldest[:10] if oldest else '?'}"
            + (" because this clone is SHALLOW -- the earliest month is a partial window and "
               "its percentages are not a monthly rate. `git fetch --unshallow` to fix."
               if shallow else ". Earlier months are outside the requested window.")),
        "headline": {
            "month": latest.get("month"),
            "fix_share": latest.get("fix_share"),
            "fast_rework_share": latest.get("fast_rework_share"),
        },
        "by_month": months,
        "examples": examples,
        "note": ("The guard on the cost numbers. Cost falling while rework rises means the "
                 "method is getting cheaper by getting worse. fast_rework counts a fix that "
                 "touches a file some other commit touched within %d days, which is rework of "
                 "recent work rather than an old bug being repaired. First-parent history, so a "
                 "merged branch counts once. Runtime state and generated output are excluded, "
                 "because they change on every run and would inflate every number here."
                 % FAST_WINDOW_DAYS),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="origin/main",
                    help="branch to measure (default origin/main -- what actually shipped)")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--json", metavar="PATH", default=str(DEFAULT_OUT),
                    help="where to write the snapshot; '-' for stdout")
    args = ap.parse_args()

    try:
        commits = read_history(args.ref, args.days)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"rework: cannot read history: {exc}", file=sys.stderr)
        return 1
    if not commits:
        print(f"rework: no commits on {args.ref} in the last {args.days} days", file=sys.stderr)
        return 1

    snap = measure(commits)

    if args.json == "-":
        print(json.dumps(snap, indent=2))
        return 0

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")

    print(f"REWORK  {args.ref}  last {args.days}d  ->  {out}")
    print(f"{'month':<9}{'commits':>9}{'fix':>6}{'fix %':>8}{'recent':>8}{'recent %':>10}")
    print(snap["coverage_note"])
    for m in snap["by_month"]:
        print(f"{m['month'] + ('*' if m.get('partial') else ''):<9}{m['commits']:>9}{m['rework']:>6}"
              f"{m['fix_share'] if m['fix_share'] is not None else '-':>8}"
              f"{m['fast_rework']:>8}"
              f"{m['fast_rework_share'] if m['fast_rework_share'] is not None else '-':>10}")
    if snap["examples"]:
        print("\nrework of recent work, most recent first:")
        for e in snap["examples"]:
            print(f"  {e['date']}  {e['sha']}  {e['subject']}\n"
                  f"              via {e['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
