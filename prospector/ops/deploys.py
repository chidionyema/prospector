"""What is actually deployed, per deployable, and how old it is.

THE BLIND SPOT THIS CLOSES. On 2026-08-17 production ran 17-hour-old code and the only way to
find that out was to run `lsof` on the pid by hand. Every screen read green, because every screen
was reporting what the repository said rather than what the machines were running. A deploy that
succeeded months ago and a deploy that succeeded this morning look identical in a workflow badge.

So every number here comes from a probe, never from a stored sentence:

  Store.Web / Store.Api   the last SUCCESSFUL run of their deploy workflow on main, read from
                          the GitHub API. That run's head SHA is what Fly built, and its
                          completion time is when the machines took it.
  engine                  the prospector-live checkout's own HEAD and that commit's date. The
                          daemons execute this working tree, so it is the only honest source.
  ops-console             the mtime of the `.next` directory `next start` serves, because the
                          console serves a BUILD, not the source next to it.

A deployable that cannot be probed reads `unknown`. It never reads "up to date": the whole point
is that silence and freshness stopped being the same thing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

#: Production checkout. Pinned rather than derived from `__file__`: this module can be imported
#: from either checkout, and the answer must not follow the code.
LIVE = Path("/Users/chidionyema/Documents/code/prospector-live")
DEV = Path("/Users/chidionyema/Documents/code/prospector")
CONSOLE_BUILD = LIVE / "store_platform/src/Ops.Console/.next"

#: Anything older than this is called out. Not a failure -- a quiet week is legitimate -- but a
#: deployable nobody has shipped in three days is the state that hid the 17-hour-old daemon.
STALE_AFTER_S = 3 * 24 * 3600

WORKFLOWS = (
    ("store-web", "Deploy Store.Web", "deploy-web.yml"),
    ("store-api", "Deploy Store.Api", "deploy-api.yml"),
)


def _gh() -> str | None:
    """Find the gh CLI.

    launchd does not give a job the login shell's PATH, so a bare "gh" resolves under a terminal
    and is missing under the ops-console job -- the console would report every Fly deployable
    unknown while the same command worked by hand. The explicit paths are the two Homebrew
    prefixes.
    """
    found = shutil.which("gh")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout or p.stderr or "").strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, f"{type(e).__name__}: {e}"


_LIVE_CHECKOUT: Any = None


def live_checkout_module() -> Any:
    """`scripts/live_checkout.py`, loaded by path.

    It is a script rather than a package, and it is imported here rather than copied because it
    owns the definition of a dirty live checkout -- the same definition `--update` refuses on.
    A second definition of that fact drifts from the first, and this module proved it within an
    hour of being written: a hand-rolled `git status --porcelain` check called the live checkout
    "LOCAL EDITS (1 path)" over an untracked `.venv`, while `_code_changes` correctly ignores
    untracked paths and called the same tree clean. The console would have shown a red row for a
    checkout the updater was perfectly happy to fast-forward.
    """
    global _LIVE_CHECKOUT
    if _LIVE_CHECKOUT is None:
        from importlib import util

        path = DEV / "scripts" / "live_checkout.py"
        spec = util.spec_from_file_location("_live_checkout_for_deploys", path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"cannot load {path}")
        mod = util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LIVE_CHECKOUT = mod
    return _LIVE_CHECKOUT


def _unknown(name: str, kind: str, why: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "sha": None,
        "deployed_at": None,
        "age_s": None,
        "behind_main": None,
        "status": "unknown",
        "detail": why,
    }


def _behind_main(sha: str | None) -> int | None:
    """How many commits on origin/main this deploy does not have.

    Counted in the DEV checkout because that is the one with a remote-tracking ref. A count of
    None means the SHA is not in this clone -- a force-push, or a deploy from a fork -- which is
    itself worth seeing rather than papering over with 0.
    """
    if not sha:
        return None
    rc, out = _run(["git", "rev-list", "--count", f"{sha}..origin/main"], cwd=DEV)
    if rc != 0 or not out.isdigit():
        return None
    return int(out)


#: A deploy stamp this far ahead of our clock is the clock disagreeing, not time travel.
SKEW_TOLERANCE_S = 120


def _age(deployed_at: float | None, row: dict[str, Any]) -> float | None:
    """Seconds since the deploy, clamped at zero, with skew called out rather than hidden.

    Measured 2026-08-19: the first live run of this view printed `age=-1h` for Store.Web, because
    GitHub's completion stamp was ahead of this machine's clock. A negative age is not a cosmetic
    problem -- it sorts to the top as the freshest deploy and grades `ok`, which is the one answer
    this module exists to stop handing out for free.
    """
    if deployed_at is None:
        return None
    age = time.time() - deployed_at
    if age < -SKEW_TOLERANCE_S:
        row["detail"] = (
            f"{row.get('detail', '')} [clock skew: the deploy stamp is "
            f"{int(-age)}s ahead of this machine]"
        ).strip()
    return max(0.0, age)


def _grade(row: dict[str, Any]) -> dict[str, Any]:
    age = row.get("age_s")
    behind = row.get("behind_main")
    if age is None:
        row["status"] = "unknown"
    elif behind:
        row["status"] = "behind"
    elif age > STALE_AFTER_S:
        row["status"] = "stale"
    else:
        row["status"] = "ok"
    return row


def _fly_deployable(name: str, workflow_name: str, workflow_file: str) -> dict[str, Any]:
    gh = _gh()
    if not gh:
        return _unknown(name, "fly", "gh CLI not found on PATH or in the Homebrew prefixes")

    rc, out = _run(
        [
            gh, "run", "list",
            "--workflow", workflow_file,
            "--branch", "main",
            "--status", "success",
            "--limit", "1",
            "--json", "headSha,updatedAt,displayTitle,url",
        ],
        cwd=DEV,
        timeout=30,
    )
    if rc != 0:
        return _unknown(name, "fly", f"gh run list failed: {out[:200]}")
    try:
        runs = json.loads(out)
    except json.JSONDecodeError:
        return _unknown(name, "fly", f"gh returned no JSON: {out[:200]}")
    if not runs:
        return _unknown(name, "fly", f"no successful run of {workflow_name} on main")

    run = runs[0]
    sha = run.get("headSha")
    # GitHub stamps UTC as a trailing Z, which fromisoformat rejects before 3.11.
    stamp = (run.get("updatedAt") or "").replace("Z", "+00:00")
    try:
        from datetime import datetime

        deployed_at = datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        deployed_at = None

    row: dict[str, Any] = {
        "name": name,
        "kind": "fly",
        "sha": sha,
        "deployed_at": deployed_at,
        "behind_main": _behind_main(sha),
        "detail": run.get("displayTitle") or "",
        "url": run.get("url"),
    }
    row["age_s"] = _age(deployed_at, row)
    return _grade(row)


def _engine_deployable() -> dict[str, Any]:
    """The daemons execute the prospector-live working tree, so that tree IS the deploy."""
    if not (LIVE / ".git").exists():
        return _unknown("engine", "checkout", f"no checkout at {LIVE}")

    rc, sha = _run(["git", "rev-parse", "HEAD"], cwd=LIVE)
    if rc != 0:
        return _unknown("engine", "checkout", f"could not read HEAD: {sha[:200]}")
    rc, at = _run(["git", "log", "-1", "--format=%ct"], cwd=LIVE)
    committed_at = float(at) if rc == 0 and at.isdigit() else None

    # Local edits mean the running code matches no commit at all, which no SHA can express, and
    # they also wedge the updater: `live_checkout.py --update` refuses a dirty live checkout.
    rc, porcelain = _run(["git", "status", "--porcelain"], cwd=LIVE)
    detail = "clean mirror of a commit"
    if rc != 0:
        detail = "could not read the live checkout's status"
    elif porcelain:
        try:
            changed = live_checkout_module()._code_changes(porcelain)
        except Exception as e:  # noqa: BLE001 - an unreadable rule must not become a green row
            detail = f"could not load the clean-mirror rule ({type(e).__name__})"
            changed = []
        if changed:
            detail = f"LOCAL EDITS block --update ({len(changed)} paths: {changed[0].strip()[:60]})"

    row: dict[str, Any] = {
        "name": "engine",
        "kind": "checkout",
        "sha": sha,
        "deployed_at": committed_at,
        "behind_main": _behind_main(sha),
        "detail": detail,
    }
    row["age_s"] = _age(committed_at, row)
    return _grade(row)


def _console_deployable() -> dict[str, Any]:
    """`next start` serves a BUILD directory. Its mtime is when the console last shipped."""
    if not CONSOLE_BUILD.exists():
        return _unknown("ops-console", "build", f"no build at {CONSOLE_BUILD}")
    built_at = CONSOLE_BUILD.stat().st_mtime

    # The build carries no SHA, so the comparison is against the console's newest commit date --
    # the same test `scripts/live_checkout.py::console_build_is_stale` makes.
    rc, at = _run(
        ["git", "log", "-1", "--format=%ct", "--", "store_platform/src/Ops.Console"], cwd=LIVE
    )
    detail = "build is newer than the console code it serves"
    if rc == 0 and at.isdigit() and float(at) > built_at:
        detail = f"build predates the console code by {int((float(at) - built_at) // 3600)}h"

    row = {
        "name": "ops-console",
        "kind": "build",
        "sha": None,
        "deployed_at": built_at,
        "behind_main": None,
        "detail": detail,
    }
    row["age_s"] = _age(built_at, row)
    row = _grade(row)
    if detail.startswith("build predates"):
        row["status"] = "behind"
    return row


def deploys_view(cfg: Any = None, args: dict | None = None) -> dict[str, Any]:
    """Every deployable on the stack, newest deploy first."""
    rows = [_fly_deployable(*w) for w in WORKFLOWS]
    rows.append(_engine_deployable())
    rows.append(_console_deployable())

    rows.sort(key=lambda r: (r["age_s"] is None, r["age_s"] or 0))
    return {
        "generated_at": time.time(),
        "stale_after_s": STALE_AFTER_S,
        "rows": rows,
        # A count the panel can lead with, so "everything is fine" is a number rather than an
        # absence of red.
        "unknown": sum(1 for r in rows if r["status"] == "unknown"),
        "behind": sum(1 for r in rows if r["status"] == "behind"),
    }
