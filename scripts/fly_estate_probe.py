#!/usr/bin/env python3
"""Every app running on Fly must be described by a file in this repo.

WHY THIS EXISTS. Founder, 2026-08-19, on finding Hermes half-migrated: "we have this blind spot",
"a business risk for infra move", "everyone stepping on toes".

Measured that morning: six `prospector-*` apps were running on Fly. Five had a committed
`fly.toml`. `prospector-hermes` had none -- an app created by a session whose config was never
committed, running since 2026-08-18, emitting nothing but SSH login lines. Meanwhile the laptop
still ran all eleven Hermes launchd jobs. `docs/ESTATE_MAP.md:178` asserted in prose that the Fly
app runs "cockpit, coordinator, otto-server, progress, rsi and submodule-backup". Nothing checked.

THE CLASS. Infrastructure that no branch describes cannot be reviewed, rebuilt, or moved to
another provider. That is the no-lock-in constraint failing silently. It fails silently because
each session has its own worktree and cannot see the others, so "I created the app" is knowledge
that dies with the session unless it is committed.

WHAT IT DOES. It asks Fly what is running, asks git what is described, and prints the difference.
READ ONLY. There is no --fix: writing a fly.toml for an app nobody documented would be guessing at
what it is meant to run, and a wrong one is worse than a missing one.

USAGE
    .venv/bin/python scripts/fly_estate_probe.py           # the report
    .venv/bin/python scripts/fly_estate_probe.py --json    # the receipt
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Apps this repo is not responsible for. `tie-*` are a separate product the founder keeps
#: (directive 2026-08-18); they are reported as out of scope, never as a defect.
OUT_OF_SCOPE = ("tie-",)

#: `app = "name"`, tolerating single quotes and a trailing comment.
APP_LINE = re.compile(r'^\s*app\s*=\s*[\'"]([^\'"]+)[\'"]')


def _git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                       timeout=60, check=False)
    return p.stdout


def described_apps(ref: str = "HEAD") -> dict[str, str]:
    """app name -> the tracked file that declares it.

    Read from a git REF rather than the working tree on purpose. An app described only by an
    uncommitted file is exactly the failure this probe exists to catch, so the working tree must
    not be allowed to answer.
    """
    found: dict[str, str] = {}
    for path in _git("ls-tree", "-r", "--name-only", ref).splitlines():
        if not path.endswith(".toml") or "fly" not in path.lower():
            continue
        for line in _git("show", f"{ref}:{path}").splitlines():
            m = APP_LINE.match(line)
            if m:
                found.setdefault(m.group(1), path)
                break
    return found


def live_apps() -> list[str]:
    """Every app the Fly account is running. Raises rather than returning an empty list.

    An empty list would read as "nothing is running", which grades every missing config as fine.
    A probe that passes when it cannot measure is worse than no probe.
    """
    p = subprocess.run(["fly", "apps", "list", "--json"], capture_output=True, text=True,
                       timeout=120, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"cannot ask Fly what is running: {p.stderr.strip() or p.stdout.strip()}")
    try:
        rows = json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"fly apps list returned no JSON: {exc}") from exc
    return sorted(str(r["Name"]) for r in rows if r.get("Name"))


def audit(ref: str = "HEAD") -> dict:
    described = described_apps(ref)
    live = live_apps()
    ours = [a for a in live if not a.startswith(OUT_OF_SCOPE)]
    return {
        "ref": ref,
        "live": live,
        "out_of_scope": [a for a in live if a.startswith(OUT_OF_SCOPE)],
        "described": described,
        "undescribed": [a for a in ours if a not in described],
        "described_but_not_running": sorted(set(described) - set(live)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="the full receipt")
    ap.add_argument("--ref", default="origin/main",
                    help="git ref to read configs from (default: origin/main)")
    args = ap.parse_args()

    try:
        result = audit(args.ref)
    except RuntimeError as exc:
        print(f"CANNOT ESTABLISH: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 1 if result["undescribed"] else 0

    print(f"Fly apps running: {len(result['live'])}  "
          f"({len(result['out_of_scope'])} out of scope)")
    for app in result["live"]:
        if app in result["out_of_scope"]:
            print(f"  -  {app:<26} out of scope (tie-*)")
        elif app in result["described"]:
            print(f"  ok {app:<26} {result['described'][app]}")
        else:
            print(f"  XX {app:<26} NOTHING IN {result['ref']} DESCRIBES THIS APP")

    if result["described_but_not_running"]:
        print("\nDescribed but not running (a config for an app that does not exist):")
        for app in result["described_but_not_running"]:
            print(f"     {app:<26} {result['described'][app]}")

    if not result["undescribed"]:
        print("\nEvery running app is described by a committed file.")
        return 0

    print(f"\n{len(result['undescribed'])} app(s) run on Fly that this repo does not describe.")
    print("That infrastructure cannot be reviewed, rebuilt, or moved to another provider.")
    print("Commit a fly.toml for each, or destroy the app.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
