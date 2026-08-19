#!/usr/bin/env python3
"""Measure rework, so the efficiency scoreboard cannot be gamed by cutting corners.

`/method` grades the agents on cost: output tokens per tool call, peak resident context, round
trips per session. Every one of those improves if the work gets sloppier. An agent that skips a
test, ships the first guess and moves on scores BETTER on all of them, and the scoreboard would
call that progress right up until production broke.

So the cost numbers need a guard beside them, from a different source -- git history rather than
session transcripts -- because a metric and its guard sharing a source can fail together.

WHAT THIS MEASURES, and the two things it deliberately does NOT
--------------------------------------------------------------
It reports ONE number per month: the share of conventionally-labelled commits that are fixes or
reverts. The denominator is the labelled commits, not all commits, and that matters -- see the
second dead end below.

Two earlier versions of this metric were built, measured, and found to have no power. Both are
recorded here because both look obviously right and neither is.

**Dead end 1: "a fix touching a file another commit touched in the last fortnight."** This reads
as the definition of rework of recent work. Measured 2026-08-19 on 420 first-parent commits, with
the same test run over EVERY commit as a control: fix commits hit recently-touched files 96.0% of
the time in August, and so did 93.5% of all commits. Lift 1.03. Swept across windows from six
hours to fourteen days the lift never left 0.99-1.16. In a repository this hot every commit
touches recently-touched code, so the test has no discriminating power at any window. The
continuous version -- median hours since the previous touch -- failed the same way: 1.6h for
fixes against 1.1h for everything else.

**Dead end 2: fixes as a share of ALL commits.** That number read 9.6% in June, 7.7% in July and
40.6% in August, which looks like a collapse in quality. It is substantially a labelling change:
conventional-commit prefixes were on 37% of June's commits, 28% of July's and 60% of August's,
and the unlabelled ones cannot be classified at all. Founder, 2026-08-19: "we did a lot more work
in august". Comparing labelled commits with labelled commits removes that confound; it does not
remove all of them, and the caveats below still stand.

WHAT IT STILL CANNOT TELL YOU
-----------------------------
A fix commit may repair a two-year-old bug. Workflow changes move the number without quality
moving: one PR per fix produces more fix commits than one PR per batch of fixes. Read it as a
trend with a known floor of noise, never as a score.

How to read it TOGETHER with the cost numbers, which is the only way it means anything:

  cost down, fix share flat or down   the method genuinely improved
  cost down, fix share UP             the loop is training for cheapness at the cost of correctness
  cost up,   fix share down           bought quality with tokens; a choice, not a failure

Read-only. Writes one JSON file and prints a summary. Never touches the working tree.

  .venv/bin/python scripts/rework_metrics.py            # print, and write store/ops/rework_metrics.json
  .venv/bin/python scripts/rework_metrics.py --json -   # print the JSON to stdout instead
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: The CHECKOUT. Used as git's working directory, which is the one thing that genuinely belongs
#: to the code. The OUTPUT below is state and does not.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prospector.config import store_root  # noqa: E402  (needs ROOT on sys.path first)

#: Written where PROSPECTOR_STORE_DIR says, never beside this file. It was `ROOT / "store"` until
#: 2026-08-19, which put the receipt in /app/store on the engine while the store was the volume at
#: /data/store -- so the console read a file the scoreboard never wrote. That is the trap
#: CLAUDE.md documents and `test_no_store_path_is_derived_from_file.py` grades; this line was the
#: one offender that test found on main.
DEFAULT_OUT = store_root() / "ops" / "rework_metrics.json"

#: How far back to measure. Longer costs nothing extra (one git call) but dilutes the trend with
#: a period whose method no longer exists.
WINDOW_DAYS = 180

#: A commit is rework if its subject starts one of these.
_REWORK_PREFIXES = ("fix(", "fix:", "revert", "hotfix")

#: The DENOMINATOR. Only commits carrying one of these type prefixes are classifiable, so only
#: they are counted. An unlabelled subject cannot be called a fix or not-a-fix, and counting it
#: as not-a-fix is what made this metric track prefix adoption instead of quality: 37% of June's
#: commits were labelled against 60% of August's. `Merge pull request ...` commits are excluded
#: by the same rule, which is right -- a merge commit is a container, not a unit of work.
_TYPE_PREFIXES = ("feat", "fix", "chore", "docs", "test", "refactor", "perf", "ci", "build",
                  "style", "revert", "process", "land", "ship", "guard", "hotfix")

_IGNORED_PREFIXES = ("store/", "storage/", "graphify-out/", "docs/doc_lint_baseline.json")


def _git(args: list[str]) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _is_rework(subject: str) -> bool:
    s = subject.strip().lower()
    return s.startswith(_REWORK_PREFIXES)


def _is_labelled(subject: str) -> bool:
    """Does this subject carry a conventional type prefix, so it can be classified at all?"""
    s = subject.strip().lower()
    return any(s.startswith(t + "(") or s.startswith(t + ":") for t in _TYPE_PREFIXES)


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

    One pass. The expensive version of this script indexed every file's touch history to answer
    "was this file touched recently"; that test was measured to have no discriminating power
    (see the module docstring), so the index is gone and so is the cost.
    """
    per_month: dict[str, dict] = defaultdict(
        lambda: {"commits": 0, "labelled": 0, "rework": 0})
    examples: list[dict] = []

    for c in commits:
        row = per_month[c["iso"][:7]]
        row["commits"] += 1
        if not _is_labelled(c["subject"]):
            continue
        row["labelled"] += 1
        if not _is_rework(c["subject"]):
            continue
        row["rework"] += 1
        if len(examples) < 8:
            examples.append({"sha": c["sha"][:8], "date": c["iso"][:10],
                             "subject": c["subject"][:90],
                             "file": (c["files"] or ["--"])[0]})

    months = []
    for m in sorted(per_month):
        r = per_month[m]
        n, lab, rw = r["commits"], r["labelled"], r["rework"]
        months.append({
            "month": m,
            "commits": n,
            "labelled": lab,
            "rework": rw,
            #: The headline. Fixes as a share of the commits that can be classified at all.
            "fix_share": round(100 * rw / lab, 1) if lab else None,
            #: Shown so the reader can see how much of the month is being judged. A month where
            #: only a third of commits carry a prefix is a thin sample, whatever the share says.
            "labelled_share": round(100 * lab / n, 1) if n else None,
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
            "labelled_share": latest.get("labelled_share"),
            "labelled": latest.get("labelled"),
        },
        "by_month": months,
        "examples": examples,
        "note": ("Fixes as a share of the commits that CAN be classified -- the ones carrying a "
                 "conventional type prefix. Against all commits instead, this number tracked "
                 "prefix adoption rather than quality (37% of June's commits were labelled "
                 "against 60% of August's). It is a trend with real noise in it, not a score: a "
                 "fix may repair an old bug, and one PR per fix produces more fix commits than "
                 "one PR per batch. Read it beside the cost numbers -- cost falling while this "
                 "rises means the method got cheaper by getting worse."),
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
    print(snap["coverage_note"])
    print(f"{'month':<9}{'commits':>9}{'labelled':>10}{'labelled %':>12}"
          f"{'fix':>6}{'fix % of labelled':>19}")
    for m in snap["by_month"]:
        print(f"{m['month'] + ('*' if m.get('partial') else ''):<9}{m['commits']:>9}"
              f"{m['labelled']:>10}"
              f"{m['labelled_share'] if m['labelled_share'] is not None else '-':>12}"
              f"{m['rework']:>6}"
              f"{m['fix_share'] if m['fix_share'] is not None else '-':>19}")

    if snap["examples"]:
        print("\nmost recent fix commits:")
        for e in snap["examples"]:
            print(f"  {e['date']}  {e['sha']}  {e['subject']}\n"
                  f"              via {e['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
