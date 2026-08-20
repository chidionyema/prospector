#!/usr/bin/env python3
"""The founder's task list, so it survives a session ending.

Measured 2026-08-20. Tasks were already written to disk, at `~/.claude/tasks/<session-id>/<n>.json`.
Persistence was never the problem; discovery was. The store is keyed by SESSION, so a new session
opens on an empty list. Across 45 prospector session directories there were 231 open tasks and 231
distinct subjects: zero overlap, because no session could ever see another one's.

The obvious fix is the wrong one. Injecting those 231 at session start (97 of them written in the
previous six hours) would spend a screen of every agent's context on another session's scratch
work at every start, forever, and would set six agents chasing each other.

So the durable list is GitHub issues labelled `founder-task`. They are already the estate's claim
mechanism (`dupe-work-fence.py` refuses an unclaimed `gh pr create`), the founder can read them
without a terminal, and the label bounds the size by construction rather than by a cap someone
picked.

The state probe runs before every session and its own header forbids network calls, for the
reason that a probe must never be why a session fails to start. So there are two modes and only
one of them touches the network:

    scripts/founder_tasks.py              print the cache. No network, ever. Always exits 0.
    scripts/founder_tasks.py --refresh    ask GitHub, rewrite the cache. Network. Not for hooks.

A stale cache says so, out loud, with the command that fixes it. It never pretends to be current,
because a task list that is quietly three days old is worse than no task list.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CACHE = Path(os.environ.get("FOUNDER_TASKS_CACHE",
                            Path.home() / ".claude" / "state" / "founder-tasks.json"))
LABEL = "founder-task"
REPO = "chidionyema/prospector"
STALE_AFTER_S = 24 * 3600
REFRESH_CMD = ".venv/bin/python scripts/founder_tasks.py --refresh"


def refresh() -> int:
    """Ask GitHub and rewrite the cache. The only mode that touches the network."""
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--repo", REPO, "--label", LABEL, "--state", "open",
             "--limit", "50", "--json", "number,title,assignees,updatedAt"],
            capture_output=True, text=True, timeout=30, check=True).stdout
        rows = json.loads(out)
    except FileNotFoundError:
        print("founder_tasks: `gh` is not installed, so the cache cannot be refreshed.",
              file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        # Print the stderr rather than a summary of it. A refresh that fails for an auth reason
        # and a refresh that fails for a network reason need different actions from a person.
        print(f"founder_tasks: gh failed (exit {exc.returncode}): {exc.stderr.strip()}",
              file=sys.stderr)
        return 1
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"founder_tasks: refresh failed: {exc}", file=sys.stderr)
        return 1

    payload = {
        "fetched_at": time.time(),
        "label": LABEL,
        "repo": REPO,
        "tasks": [
            {
                "number": r["number"],
                "title": r["title"],
                "assignees": [a["login"] for a in r.get("assignees") or []],
                "updated_at": r.get("updatedAt", ""),
            }
            for r in sorted(rows, key=lambda r: r["number"])
        ],
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    # Write through a temp file: the probe reads this at session start, and a half-written cache
    # read by a starting session is exactly the kind of failure that gets blamed on something else.
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(CACHE)
    print(f"founder_tasks: cached {len(payload['tasks'])} open {LABEL} issue(s) to {CACHE}")
    return 0


def _age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def show() -> int:
    """Print the cache. Never calls the network. Never fails a session start."""
    if not CACHE.exists():
        print(f"FOUNDER TASKS: no cache yet. Build it with:  {REFRESH_CMD}")
        return 0
    try:
        payload = json.loads(CACHE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"FOUNDER TASKS: cache unreadable ({exc}). Rebuild it with:  {REFRESH_CMD}")
        return 0

    tasks = payload.get("tasks") or []
    age_s = max(0.0, time.time() - float(payload.get("fetched_at") or 0))
    stale = age_s > STALE_AFTER_S

    if not tasks:
        print(f"FOUNDER TASKS: none open (cache {_age(age_s)} old).")
        return 0

    head = f"FOUNDER TASKS ({len(tasks)} open, cache {_age(age_s)} old)"
    print(head + (" — STALE, refresh before trusting it:  " + REFRESH_CMD if stale else ":"))
    for t in tasks:
        who = ", ".join(t.get("assignees") or []) or "unclaimed"
        print(f"      #{t['number']}  {t['title']}   [{who}]")
    print("      Claim one before the first edit; the PR fence refuses an unclaimed PR.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true",
                    help="ask GitHub and rewrite the cache (network; not for session hooks)")
    args = ap.parse_args()
    return refresh() if args.refresh else show()


if __name__ == "__main__":
    sys.exit(main())
