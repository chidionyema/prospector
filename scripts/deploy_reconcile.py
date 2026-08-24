#!/usr/bin/env python3
"""Notice when production is not running main, and put it right.

WHY THIS EXISTS. Three holes, all measured on 2026-08-21 after the ops-console outage:

  1. THE DEPLOY DOES NOT WAIT FOR CI. `deploy-engine.yml` fires on PUSH to main, and its only
     gate is a `test` job that runs the Ops.Console lane. Our own probe printed the proof:
     production ran 61cfb7d1 while `scripts/live_checkout.py` reported "CI on it  pending:
     still in_progress" for that same commit. A commit reaches production before it is graded.
  2. ONE OF THE TWO MAIN GUARDS REVERTS WITHOUT RE-DEPLOYING. `main-admission-guard.yml` does
     the right thing -- its "Put the estate back, not just git" step dispatches the deploys the
     bad commit had already set off. `main-green-guard.yml` does not: it reverts with
     GITHUB_TOKEN, which starts no workflow runs, and then dispatches CI and only CI. Its own
     header says so: "WHAT IT DOES TO PRODUCTION. Nothing directly." Eight reverts landed on
     main in the three days to 2026-08-21, so this is not theoretical.
  3. NOTHING COMPARED PRODUCTION TO MAIN. Before this file, `rg deployed_commit` and `rg
     GIT_SHA` matched exactly one file in the repo -- `scripts/live_checkout.py` -- which runs
     when a person runs it. `com.prospector.live-update`, the launchd job that would have run
     it every 60 seconds, is not loaded.

Put together: a red commit can reach production, be reverted on main, and KEEP RUNNING, with
every instrument in the estate reporting green.

WHY A RECONCILER RATHER THAN A FIX TO EACH ROUTE. Every deploy route can drop a release for its
own reason, and each new route brings a new reason. This asks the only question that stays true
whatever the cause: is the image production is running the one main says it should be? It is
also the only check in the estate that can see an action that DID NOT HAPPEN -- a missing deploy
leaves no failing run for an alert to fire on.

WHAT IT REFUSES TO DO.
  - It will not deploy a commit CI has not passed. "pending" is not a problem, it is a deploy
    that has not happened yet, so it exits quiet and waits for the next cycle. "fail" and "none"
    are refusals, because shipping an ungraded commit to close a drift is worse than the drift.
  - It will not deploy while a deploy is already running, for the reason `deploy-engine.yml`
    sets `cancel-in-progress: false`: a half-finished release must not be raced.
  - It will not deploy when it cannot read what production runs. "I could not tell" must never
    be handled as "it is fine".
  - It will not deploy when the commits differ but nothing the image SHIPS does. A docs merge is
    not a drift, and a Fly build costs money every time it runs.

WHAT IT NEVER DOES. It never builds, and it never pushes. It dispatches the existing deploy
workflow, so there is still exactly one route to production and every gate and the rollback in
`deploy-engine.yml` still apply to every release.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_checkout as lc  # noqa: E402

#: The workflow that owns every release. This script dispatches it and never deploys itself.
DEPLOY_WORKFLOW = "deploy-engine.yml"

REPO = os.environ.get("GITHUB_REPOSITORY", "chidionyema/prospector")

#: Where the failover marker lives. `scripts/engine_failover.py:64` reads the same env var and
#: the same default, so the two cannot disagree about which side is serving.
CTRL = Path(os.environ.get("PROSPECTOR_CTRL_DIR", Path.home() / ".prospector"))


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def point_live_checkout_at_this_checkout() -> str:
    """Make the helpers usable off the founder's laptop.

    `live_checkout.DEV` is the hardcoded path of the developer checkout, and `run(..., cwd=DEV)`
    does not catch a missing directory -- `subprocess.run` raises FileNotFoundError before the
    timeout handling is reached. On a CI runner that path does not exist, so `ci_verdict` and
    `_deployed_changes` would both crash rather than answer. Repointing it at whatever checkout
    this script is running from is the whole of the portability fix, and on the laptop it
    resolves to the same directory it already had.
    """
    rc, top = run(["git", "rev-parse", "--show-toplevel"], timeout=15)
    if rc == 0 and top.strip():
        lc.DEV = Path(top.strip())
    return str(lc.DEV)


def main_sha() -> str:
    """The commit main points at, asked of the remote rather than of a local ref.

    `git rev-parse origin/main` answers out of a checkout that may not have been fetched this
    hour, which is the exact class of mistake LAW 7 exists for. The API cannot be stale.
    """
    rc, out = run(["gh", "api", f"repos/{REPO}/git/ref/heads/main", "--jq", ".object.sha"])
    if rc == 0 and len(out.strip()) == 40:
        return out.strip()
    rc, out = run(["git", "rev-parse", "origin/main"])
    return out.strip() if rc == 0 and len(out.strip()) == 40 else ""


def ships_a_change(live: str, target: str) -> tuple[bool, str]:
    """Does the gap between these two commits change anything the image contains?

    The path filter is NOT copied here. `live_checkout._deployed_changes` already reads it out
    of `deploy-engine.yml` on origin/main, for the same reason and with the same wording, and a
    second copy would drift silently in the one direction that matters: production graded
    current while a real change sits unshipped.

    Returns (yes/no, one line saying why). When the question cannot be answered -- a shallow
    clone, an unreadable filter, an image built from a commit that was later force-pushed away
    -- the answer is YES. An unanswerable question about production is a reason to reconcile,
    not a reason to assume it is fine.
    """
    if not live or live == "unknown":
        return True, "production could not name its own commit"
    rc, _ = run(["git", "cat-file", "-e", f"{live}^{{commit}}"])
    if rc != 0:
        return True, f"{live[:12]} is not in this checkout, so the diff cannot be taken"
    rc, out = run(["git", "diff", "--name-only", f"{live}..{target}"])
    if rc != 0:
        return True, f"git diff failed: {out[:120]}"
    hits = lc._deployed_changes(out)
    if hits is None:
        return True, "the deploy path filter could not be read, so nothing rules this out"
    if not hits:
        return False, "the commits differ but nothing the image ships does"
    head = ", ".join(hits[:4])
    more = f" (+{len(hits) - 4} more)" if len(hits) > 4 else ""
    return True, f"{len(hits)} shipped file(s) changed: {head}{more}"


def deploy_in_flight() -> bool:
    """Is a release already running? Racing one is how a machine ends up on two images."""
    rc, out = run(["gh", "run", "list", "-R", REPO, "--workflow", DEPLOY_WORKFLOW,
                   "--limit", "10", "--json", "status", "--jq",
                   '[.[] | select(.status != "completed")] | length'])
    return rc == 0 and out.strip() not in ("0", "")


#: How many deploys this script may set off in STORM_WINDOW before it stops and asks for a
#: person. Three is the number because two is a plausible bad hour -- a deploy that raced a merge
#: -- and three of them means the deploy is not fixing what this script thinks it is fixing.
STORM_LIMIT = 3
STORM_WINDOW = timedelta(hours=6)


def dispatch_storm() -> tuple[bool, str]:
    """Have we already deployed this way several times recently, and it did not take?

    THE LOOP THIS PREVENTS, which is the worst thing this script could do. If the image stops
    carrying /app/GIT_SHA -- and every release up to v15 on 2026-08-18 was in exactly that state
    -- production can never name its own commit, so the drift can never close. Deploying is the
    correct response to drift and it would then be the wrong response forever, once an hour,
    each one a paid Fly build. A reconciler that cannot converge must stop, not keep trying.
    """
    rc, out = run(["gh", "run", "list", "-R", REPO, "--workflow", DEPLOY_WORKFLOW,
                   "--event", "workflow_dispatch", "--limit", "20",
                   "--json", "createdAt"])
    if rc != 0:
        return False, ""
    try:
        runs = json.loads(out or "[]")
    except ValueError:
        return False, ""
    cutoff = datetime.now(timezone.utc) - STORM_WINDOW
    recent = 0
    for entry in runs:
        stamp = (entry.get("createdAt") or "").replace("Z", "+00:00")
        try:
            if datetime.fromisoformat(stamp) >= cutoff:
                recent += 1
        except ValueError:
            continue
    if recent < STORM_LIMIT:
        return False, ""
    return True, (f"{recent} deploys were already dispatched in the last "
                  f"{int(STORM_WINDOW.total_seconds() // 3600)}h and production still does not "
                  f"match main")


def dispatch() -> tuple[bool, str]:
    """Ask the deploy workflow to run. One deploy path, so one set of gates."""
    rc, out = run(["gh", "workflow", "run", DEPLOY_WORKFLOW, "-R", REPO, "--ref", "main"])
    return rc == 0, out


def serving_side() -> tuple[str, str]:
    """Which side is serving, read from the file `engine_failover.py` writes.

    Returns ("fly" | "other" | "unknown", detail).

    WHY IT MATTERS. AUTOFAILOVER is armed (`~/.prospector/AUTOFAILOVER` held a timestamp when
    this was measured, 2026-08-21), so the serving side can move with no human in the path. If
    it moves off fly, this app's image stops deciding anything, and every deploy dispatched
    after that restarts four processes on a box nobody is using -- hourly, forever.

    ABSENT IS NOT A REFUSAL, and that is the whole subtlety. The marker lives in a home
    directory on the founder's laptop. This reconciler runs on a GitHub runner, where the file
    can never exist. Refusing on absence would make the robot permanently inert in the only
    place it actually runs, which is a worse failure than the one this check prevents. So the
    check bites where it can see: readable AND not `fly`.
    """
    path = CTRL / "ACTIVE"
    try:
        side = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return "unknown", f"{path} unreadable ({type(exc).__name__}); assuming fly still serves"
    if not side:
        return "unknown", f"{path} is empty; assuming fly still serves"
    if side == "fly":
        return "fly", f"{path} says fly"
    return "other", f"{path} says {side!r}, so {lc.FLY_APP} is not the side serving traffic"


def staged_secrets() -> tuple[list[str] | None, str]:
    """The secrets that the next deploy would APPLY.

    A Fly deploy applies staged secrets. So a robot that deploys on a schedule quietly turns
    "some session staged a credential" into "that credential is live in production", with no
    human anywhere in the path at the moment it happens. That is a larger blast radius than
    restarting known code, and it is not hypothetical on this app: TELEGRAM_BOT_TOKEN and
    TELEGRAM_HOME_CHANNEL were staged here on 2026-08-20 precisely so they would NOT go live
    until somebody chose to ship them.

    `None` means the answer could not be read, and the caller refuses on it. Unlike the ACTIVE
    marker above, this one is reachable everywhere this script runs -- the workflow installs
    flyctl and already puts FLY_API_TOKEN in the step's environment -- so a failure here is a
    real fault, not a foreseeable absence.
    """
    code, out = run(["fly", "secrets", "list", "-a", lc.FLY_APP, "--json"])
    if code != 0:
        return None, f"could not list secrets on {lc.FLY_APP}: {out[:160]}"
    try:
        rows = json.loads(out)
    except (ValueError, TypeError):
        return None, f"could not read the secret list for {lc.FLY_APP} as JSON"
    if not isinstance(rows, list):
        return None, f"the secret list for {lc.FLY_APP} was not a list"
    pending = [str(r.get("name", "?")) for r in rows
               if isinstance(r, dict) and str(r.get("status", "")) != "Deployed"]
    return pending, f"{len(rows)} on the app, {len(pending)} waiting for a deploy to apply them"


def _outcome(kind: str) -> None:
    """Tell the workflow WHICH kind of exit this was.

    The step exits 0 for five different reasons and only two of them mean production matches
    main; the other three are "waiting for CI", "a deploy is already running" and "I have just
    dispatched one". `if: success()` cannot tell those apart, so the issue-closer commented
    "Production matches `main` again" and closed the drift issue on runs where production had
    not moved at all. A machine writing a false statement into the issue tracker is worse than
    the drift it was hired to report, and it is the same class as the alarm this file's own
    header was written to prevent: every instrument reporting green while production drifts.

    Silent when GITHUB_OUTPUT is unset, so a laptop run behaves exactly as before.
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"outcome={kind}\n")
    except OSError:
        pass  # a report that cannot be filed must not turn a good run into a failure


def reconcile(*, apply: bool) -> int:
    """0 = production is where it should be, or is on its way there. 1 = a human is needed."""
    checkout = point_live_checkout_at_this_checkout()
    target = main_sha()
    if not target:
        print("UNKNOWN: could not read what main points at; not touching production")
        return 1

    live, how = lc.deployed_commit()
    print(f"checkout        {checkout}")
    print(f"main            {target[:12]}")
    print(f"deployed        {live[:12] if live else '(unreadable)'}   ({how})")

    # `-dirty` is appended by the build when the tree it shipped was not clean. The commit in
    # front of it is still the commit, and comparing the raw string would report permanent drift.
    if live and live.split("-")[0] == target:
        print(f"OK: {lc.FLY_APP} runs main.")
        _outcome("ok")
        return 0

    if not live:
        print("PROBLEM: production cannot be read, so drift cannot be ruled out.")
        print("  Nothing is dispatched: a deploy decided on a missing measurement is a guess.")
        return 1

    ships, why = ships_a_change(live, target)
    print(f"drift           {why}")
    if not ships:
        print("OK: production is behind main by commits that change nothing it ships.")
        _outcome("ok")
        return 0

    verdict, detail = lc.ci_verdict(target)
    print(f"CI on main      {verdict}: {detail}")
    if verdict == "pending":
        print("WAITING: main is still being graded, and the push deploy may still be running.")
        _outcome("waiting")
        return 0
    if verdict != "pass":
        print(f"REFUSING: main's CI verdict is {verdict}, so shipping it does not fix this.")
        print("  Production stays where it is. Fix main first.")
        return 1

    if deploy_in_flight():
        print("WAITING: a deploy is already running; not racing it.")
        _outcome("waiting")
        return 0

    storming, detail = dispatch_storm()
    if storming:
        print(f"REFUSING: {detail}.")
        print("  Deploying again would not close it either. Read the image stamp by hand:")
        print(f"    fly ssh console -a {lc.FLY_APP} -C '/bin/cat {lc.IMAGE_STAMP}'")
        return 1

    side, detail = serving_side()
    print(f"serving side    {detail}")
    if side == "other":
        print(f"REFUSING: {lc.FLY_APP} is not the side serving traffic.")
        print("  Deploying it restarts four processes on a box nobody is using. Read the marker:")
        print(f"    cat {CTRL / 'ACTIVE'}")
        return 1

    pending, detail = staged_secrets()
    print(f"staged secrets  {detail}")
    if pending is None:
        print("REFUSING: a deploy applies staged secrets, and I cannot tell whether any wait.")
        print(f"  {detail}")
        return 1
    if pending:
        print(f"REFUSING: {', '.join(pending)} would go live with this deploy.")
        print("  Nobody chose to ship a credential change now. Apply them deliberately, or")
        print("  unstage them, and this reconciler will pick the drift up on its next pass:")
        print(f"    fly secrets deploy -a {lc.FLY_APP}")
        return 1

    if not apply:
        print(f"WOULD DISPATCH {DEPLOY_WORKFLOW} (run with --apply to do it)")
        return 1

    ok, out = dispatch()
    if not ok:
        print(f"FAILED to dispatch {DEPLOY_WORKFLOW}: {out[:200]}")
        return 1
    print(f"DISPATCHED {DEPLOY_WORKFLOW} to bring {lc.FLY_APP} to {target[:12]}")
    _outcome("dispatched")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="dispatch the deploy; without it, report only, and exit nonzero "
                             "when a deploy is what the report asks for")
    return parser


if __name__ == "__main__":
    sys.exit(reconcile(apply=build_parser().parse_args().apply))
