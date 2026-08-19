#!/usr/bin/env python3
"""Report and update the checkout the production daemons actually run from.

Why this exists (2026-08-17): production ran from the shared developer checkout
/Users/chidionyema/Documents/code/prospector. That checkout sits on whatever branch a
session left it on. On 2026-08-17 it was 75 commits behind origin/main, so the daemon
executed 17-hour-old code, and nobody could tell without running lsof by hand.

Production now runs from a dedicated checkout pinned to origin/main. Runtime state does
not move: PROSPECTOR_STORE_DIR (config.py, "redirects every store read/write") keeps the
catalogue, ledger, dossiers and scheduler files in the canonical store directory.

Report by default. --update fast-forwards the live checkout to origin/main and restarts
the daemons. It refuses to touch a checkout with local modifications.

    python3 scripts/live_checkout.py             # what is live right now
    python3 scripts/live_checkout.py --update    # roll it forward to origin/main
"""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEV = Path("/Users/chidionyema/Documents/code/prospector")
LIVE = Path("/Users/chidionyema/Documents/code/prospector-live")
STORE = DEV / "store"
JOBS = ("com.prospector.scheduler", "com.prospector.consumer", "com.prospector.ops-console")
# untracked files the daemon needs that git will never bring across
SECRETS = (".env", ".lux/keys/agent.pem")

#: The Fly app that runs the engine. Same default and same override as deploy/targets/fly.sh,
#: which is the only other file in this repo that knows the word "fly".
FLY_APP = os.environ.get("PROSPECTOR_FLY_APP", "prospector-engine")

#: Where the image records the commit it was built from. deploy/engine/Dockerfile writes it.
#: An image built before that existed has no file, which reads as "unknown" and is reported as
#: a problem: not being able to say what production runs is the condition this probe exists for.
IMAGE_STAMP = Path("/app/GIT_SHA")

#: A full sha, optionally marked as built from a dirty tree. Matched rather than sliced because
#: `fly ssh console` writes "Connecting to fdaa:73:..." on stderr and run() merges the streams.
#: An IPv6 group is four hex characters at most, so it can never match forty.
_STAMP_RE = re.compile(r"\b([0-9a-f]{40})(-dirty)?\b")

#: Where a Fly deploy is built FROM. It must be a clean checkout at origin/main: `fly deploy`
#: uploads the working tree, so deploying from the shared developer checkout would ship whatever
#: branch a session happened to leave it on -- the exact defect that moved production off it.
DEPLOY_SOURCE = LIVE


#: The ops console is a Next.js app served by `next start`, which reads a build directory and
#: never rebuilds. Rolling the code forward therefore changes nothing the operator can see
#: until this directory is regenerated, and restarting the job alone does not do it.
#:
#: Measured 2026-08-17: the console was serving a build made at 16:52 the previous day, out of
#: the SHARED developer checkout on a retired branch, with eight console commits on main newer
#: than it -- including the offsite-backup button merged that morning. The founder had to ask
#: why his console work was not deployed. That is the failure this file already exists to
#: prevent, happening in a second place because JOBS named only the two python daemons.
CONSOLE = Path("store_platform/src/Ops.Console")
CONSOLE_JOB = "com.prospector.ops-console"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
    """Run a command with a clean git environment and return (rc, output).

    stdin is closed and the credential prompt disabled: a git subprocess that asks for a
    password with no terminal attached hangs until the timeout, which is how the first
    version of this probe took 180 seconds to print nothing.
    """
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "/usr/bin/true"
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(cmd)}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


#: The two status columns of `git status --porcelain`, however many of them survived.
_STATUS_RE = re.compile(r"^\s*[MTADRCU?!]{1,2}\s+")


def _code_changes(porcelain: str) -> list[str]:
    """Modified TRACKED CODE, ignoring tracked runtime state.

    store/ and storage/ are tracked but are written by every run, so `git status` in a
    working production checkout is never empty. Counting those as local modifications
    would make the clean-mirror check fire permanently and mean nothing.

    The path is matched, never sliced at a fixed offset. `run()` strips the whole command
    output, so the FIRST porcelain line loses its leading space whenever the index column
    is blank -- which is the normal case for an unstaged change. `line[3:]` then read
    "ore/provider_health.json", which does not start with "store/", so the checkout was
    reported dirty and --update refused on the exact runtime state this function exists to
    ignore. Measured 2026-08-17: the single "local modification" blocking the live checkout
    at 14 commits behind origin/main was ` T store/provider_health.json`.
    """
    out = []
    for line in porcelain.splitlines():
        if line.lstrip().startswith("??"):
            continue
        path = _STATUS_RE.sub("", line, count=1).strip().strip('"')
        if " -> " in path:                    # a rename is judged by its destination
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if path.startswith(("store/", "storage/")):
            continue
        out.append(line)
    return out


def job_cwd(job: str) -> tuple[str | None, str | None]:
    """Return (pid, cwd) for a launchd job, read from the process, not from config."""
    rc, out = run(["launchctl", "print", f"gui/{os.getuid()}/{job}"])
    if rc != 0:
        return None, None
    pid = None
    for line in out.splitlines():
        if line.strip().startswith("pid = "):
            pid = line.split("=", 1)[1].strip()
            break
    if not pid:
        return None, None
    rc, out = run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"])
    cwd = None
    for line in out.splitlines():
        if line.startswith("n/"):
            cwd = line[1:]
    return pid, cwd


def _npm() -> str | None:
    """Absolute path to npm, or None.

    launchd hands a job a minimal PATH that does not include /usr/local/bin, so a bare
    "npm" resolves interactively and fails under the scheduled job -- the difference that
    makes a deploy step work when a human runs it and silently not when the machine does.
    """
    found = shutil.which("npm")
    if found:
        return found
    for candidate in ("/usr/local/bin/npm", "/opt/homebrew/bin/npm"):
        if Path(candidate).exists():
            return candidate
    return None


def console_build_is_stale() -> tuple[bool, str]:
    """Is the directory `next start` serves older than the console code in this checkout?

    Compared against the COMMIT DATE of the newest commit touching the console, not against
    source file mtimes. `git checkout` rewrites the mtime of every file it changes, so an
    mtime comparison would call the build stale immediately after a successful rebuild.
    """
    build = LIVE / CONSOLE / ".next"
    if not build.exists():
        return True, "no build directory: the console has never been built in this checkout"
    rc, out = run(["git", "log", "-1", "--format=%ct", "--", str(CONSOLE)], cwd=LIVE)
    stamp = out.strip()
    if rc != 0 or not stamp.isdigit():
        return False, "could not read the console's last commit date, so not judging it"
    code_at, built_at = int(stamp), int(build.stat().st_mtime)
    if built_at >= code_at:
        return False, "build is newer than the console code it serves"
    return True, f"build predates the console code by {(code_at - built_at) // 3600}h"


def build_console() -> int:
    """Regenerate the build `next start` serves. Returns 0 on success.

    `npm ci` when a lockfile is present, never `npm install`: a roll-forward that quietly
    resolves different dependency versions than CI tested is a deploy nobody can reason
    about. The timeouts are minutes rather than this module's 30-second default, because an
    install and a Next build are the two slowest things here by a wide margin.
    """
    cwd = LIVE / CONSOLE
    if not (cwd / "package.json").exists():
        print(f"  no console at {cwd} — nothing to build")
        return 0
    npm = _npm()
    if npm is None:
        print("  npm not found on PATH — cannot rebuild the console")
        return 1
    install = [npm, "ci"] if (cwd / "package-lock.json").exists() else [npm, "install"]
    rc, out = run(install, cwd=cwd, timeout=900)
    if rc != 0:
        print(f"  console dependency install failed (rc={rc}): {out[-800:]}")
        return rc
    rc, out = run([npm, "run", "build"], cwd=cwd, timeout=1800)
    if rc != 0:
        print(f"  console build failed (rc={rc}): {out[-800:]}")
        return rc
    print("  console rebuilt")
    return 0


def plist_store_dir(job: str) -> str | None:
    path = Path.home() / "Library/LaunchAgents" / f"{job}.plist"
    if not path.exists():
        return None
    data = plistlib.loads(path.read_bytes())
    return (data.get("EnvironmentVariables") or {}).get("PROSPECTOR_STORE_DIR")


def active_side() -> str:
    """Which platform runs the engine right now: `fly`, `laptop`, or `unknown`.

    Read from `~/.prospector/ACTIVE`, which is deliberately outside both platforms, so the answer
    survives either of them being down. `engine_failover.py` is the writer.

    This probe used to assume the laptop. After the 2026-08-18 cutover it graded a correctly
    migrated estate as broken: `com.prospector.scheduler is not running` is the DESIRED state when
    Fly is active and the laptop is fenced, and printing it as a problem trains the operator to
    ignore the probe.
    """
    marker = Path.home() / ".prospector" / "ACTIVE"
    try:
        side = marker.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "unknown"
    return side if side in ("fly", "laptop") else "unknown"


def report() -> int:
    """Print live state. Returns 0 when production is on origin/main and healthy."""
    problems: list[str] = []
    side = active_side()

    # Grade the platform that is actually serving. Reporting on the standby and calling its
    # stopped jobs healthy is not the same as answering "which commit is production running?",
    # and after the 2026-08-18 cutover only the second question had a subject.
    if side == "fly":
        return fly_report()

    print("== the checkout the daemons are actually running from ==")
    for job in JOBS:
        pid, cwd = job_cwd(job)
        if pid is None:
            print(f"  {job:26s} NOT RUNNING")
            problems.append(f"{job} is not running")
            continue
        # A subdirectory of the live checkout counts. The console runs `next start` from
        # store_platform/src/Ops.Console, so an exact match reported the correctly deployed
        # console as running from the wrong checkout, next to a real finding about the wrong
        # checkout. A probe that cries wolf about its own healthy case teaches the reader to
        # skip the section.
        inside = cwd is not None and (cwd == str(LIVE) or cwd.startswith(str(LIVE) + os.sep))
        flag = "" if inside else "   <- NOT the live checkout"
        print(f"  {job:26s} pid={pid:<7s} cwd={cwd}{flag}")
        if not inside:
            problems.append(f"{job} runs from {cwd}, not {LIVE}")
        store = plist_store_dir(job)
        if store != str(STORE):
            print(f"  {' ':26s} PROSPECTOR_STORE_DIR={store}   <- expected {STORE}")
            problems.append(f"{job} writes state to {store}, not the canonical store")

    print()
    print("== is the live checkout on origin/main? ==")
    if not LIVE.exists():
        print(f"  MISSING: {LIVE}")
        return 1
    rc, out = run(["git", "fetch", "--quiet", "origin", "main"], cwd=LIVE, timeout=25)
    if rc != 0:
        print(f"  (could not reach origin: {out.splitlines()[0] if out else 'rc=%d' % rc})")
        print("  comparing against the last fetched origin/main instead")
    _, head = run(["git", "rev-parse", "HEAD"], cwd=LIVE)
    _, main = run(["git", "rev-parse", "origin/main"], cwd=LIVE)
    _, subject = run(["git", "log", "-1", "--format=%h %ad %s", "--date=short"], cwd=LIVE)
    print(f"  live HEAD   {subject}")
    if head == main:
        print("  origin/main SAME COMMIT")
    else:
        _, behind = run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=LIVE)
        _, ahead = run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=LIVE)
        print(f"  origin/main {main[:12]}   live is {behind} behind, {ahead} ahead")
        problems.append(f"live checkout is {behind} commits behind origin/main")

    _, dirty = run(["git", "status", "--porcelain"], cwd=LIVE)
    tracked = _code_changes(dirty)
    if tracked:
        print(f"  local modifications: {len(tracked)} tracked file(s) changed")
        problems.append("live checkout has local modifications")

    print()
    print("== was the code in production ever tested? ==")
    # The question this probe could not answer until 2026-08-17, which is how an untested
    # commit ran production for hours without anyone being able to see it.
    verdict, detail = ci_verdict(head)
    print(f"  live commit {head[:12]}   CI {verdict}: {detail}")
    if verdict in ("fail", "none"):
        problems.append(f"production runs {head[:12]}, whose CI verdict is {verdict}")
    if ALLOW_UNVERIFIED_DEPLOY.exists():
        print(f"  {ALLOW_UNVERIFIED_DEPLOY.name} is present — the CI gate is BYPASSED")
        problems.append("the CI deploy gate is bypassed")
    if NO_AUTO_UPDATE.exists():
        print(f"  {NO_AUTO_UPDATE.name} is present — auto roll-forward is PAUSED")

    print()
    print("== untracked files the daemon needs (git never brings these across) ==")
    for rel in SECRETS:
        target = LIVE / rel
        state = "present" if target.exists() else "MISSING"
        if target.is_symlink():
            state += f" -> {os.readlink(target)}"
        print(f"  {rel:24s} {state}")
        if not target.exists():
            problems.append(f"{rel} missing from the live checkout")
    venv = LIVE / ".venv/bin/python"
    print(f"  {'.venv/bin/python':24s} {'present' if venv.exists() else 'MISSING'}")
    if not venv.exists():
        problems.append(".venv missing from the live checkout")
    modules = LIVE / CONSOLE / "node_modules"
    print(f"  {'console node_modules':24s} {'present' if modules.exists() else 'MISSING'}")
    if not modules.exists():
        problems.append("the console's node_modules is missing, so it cannot be built here")

    print()
    print("== is the console serving current code? ==")
    stale, why = console_build_is_stale()
    print(f"  {why}")
    if stale:
        problems.append(f"the ops console is serving a stale build ({why})")

    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        print("\nRun with --update to roll the live checkout onto origin/main and restart.")
        return 1
    print("OK: production runs origin/main from the live checkout, state in the canonical store.")
    return 0


#: Kill switch for the unattended roll-forward. Present => --update reports and refuses,
#: exactly like the scheduler's PAUSE file, which is the convention on this estate.
#: A rail with no off switch gets uninstalled the first time it is wrong.
NO_AUTO_UPDATE = DEV / "store" / "scheduler" / "NO_AUTO_UPDATE"

#: Bypass for the CI gate below. Present => a commit with no green verdict ships anyway.
#: Same convention as PAUSE and NO_AUTO_UPDATE: a file the operator can create from the
#: console, not a flag that needs a code edit. It exists because a GitHub outage must not be
#: able to freeze production deploys indefinitely with no way out.
ALLOW_UNVERIFIED_DEPLOY = DEV / "store" / "scheduler" / "ALLOW_UNVERIFIED_DEPLOY"

#: Workflow runs this gate ignores. Two kinds, for two different reasons.
#:
#: Deploys and smoke tests run AFTER a merge and describe the deployment, not the code;
#: requiring them would deadlock the deploy on itself.
#:
#: `automerge` and `cancel` are repository plumbing. They act on pull requests and never
#: test anything, and `automerge.yml` concludes `skipped` on almost every run by design.
#: Measured 2026-08-18 on 48f3cfb9, the commit production was running: `CI=success`,
#: `Deploy Engine=success`, and eighteen "Auto-merge green PRs" rows of which two were
#: `cancelled`. This gate read that as `fail` and refused to roll production forward onto
#: a commit whose tests had all passed. A green build cannot be allowed to read as red
#: because an unrelated automation was cancelled.
_IGNORED_WORKFLOWS = ("deploy", "smoke", "e2e", "auto-merge", "automerge", "cancel")


def ci_verdict(sha: str) -> tuple[str, str]:
    """Did CI pass on `sha`? Returns (verdict, detail) where verdict is one of
    "pass", "fail", "pending", "none", "unknown".

    WHY THIS EXISTS. There is no branch protection on this repo — both
    `/branches/main/protection` and `/rulesets` return 403 "Upgrade to GitHub Pro or make
    this repository public", measured 2026-08-17 on this account. So nothing stops a red or
    an untested commit reaching main, and the follower above ships main to production within
    60 seconds of it landing.

    That is not hypothetical. On 2026-08-17 four merges landed on main between 20:11 and
    20:36. Three of their CI runs were cancelled by the next merge landing on top, and the
    one run that reached a verdict concluded failure. Main's tip `5b8d010` — the commit the
    daemons were executing — had ZERO check runs against it. Nothing had ever tested the
    code in production.

    "none" is deliberately its own verdict rather than folded into "unknown". A commit with
    no run at all is the exact shape of the cancelled-by-the-next-merge case, and it is the
    one the gate most needs to refuse. "unknown" means the question could not be asked (no
    `gh`, no network, API error) and is a different decision for the caller to make.

    It reads `actions/runs`, not `commits/{sha}/check-runs`. A run that is QUEUED has no
    check runs yet, so the check-runs endpoint reports it as an empty list — indistinguishable
    from a commit nobody ever tested. Measured 2026-08-17 on `5b8d010`: check-runs returned
    nothing while `actions/runs` showed run 32066671248 sitting in `queued`. Those are
    "wait 60 seconds" and "this was never tested"; a gate that cannot tell them apart cannot
    report the truth about production.
    """
    if not shutil.which("gh"):
        return "unknown", "gh CLI not on PATH"
    # `head_sha` matches on the FULL 40 characters and returns an empty list for an
    # abbreviation — silently, with rc 0. Measured 2026-08-17: `5b8d010` returned nothing
    # while `5b8d0106d4223a83dbce19c765385d571454c0dc` returned its in-progress run. An
    # abbreviated sha would therefore read as "never tested" and hold every deploy forever.
    if len(sha) < 40:
        rc, full = run(["git", "rev-parse", sha], cwd=DEV, timeout=10)
        if rc != 0:
            return "unknown", f"could not resolve {sha}: {full[:120]}"
        sha = full.strip()
    rc, out = run(
        ["gh", "api", f"repos/:owner/:repo/actions/runs?head_sha={sha}&per_page=50",
         "--jq", ".workflow_runs[] | \"\\(.name)\\t\\(.status)\\t\\(.conclusion)\""],
        cwd=DEV, timeout=25,
    )
    if rc != 0:
        return "unknown", f"gh api failed: {out[:200]}"
    rows = [ln.split("\t") for ln in out.splitlines() if ln.strip()]
    relevant = [r for r in rows
                if not any(w in r[0].lower() for w in _IGNORED_WORKFLOWS)]
    # A skipped run tested nothing, so it has no opinion about the code. Counting it as a
    # failure is how one workflow with a path filter walls every deploy. Dropping the rows
    # BEFORE the emptiness check keeps the safe answer: a commit whose only run was skipped
    # is "none", which this gate refuses, not "pass".
    relevant = [r for r in relevant if r[2] != "skipped"]
    if not relevant:
        return "none", "no CI run recorded against this commit"

    waiting = [r[0] for r in relevant if r[1] != "completed"]
    if waiting:
        return "pending", f"still {relevant[0][1]}: {', '.join(waiting[:5])}"
    bad = [f"{r[0]}={r[2]}" for r in relevant if r[2] != "success"]
    if bad:
        return "fail", ", ".join(bad[:5])
    return "pass", f"{len(relevant)} run(s) green"


def fly_machine_state() -> str:
    """State of the engine machine, or a word explaining why it could not be read.

    `fly status` reports an app whose machine is stopped, so the app is not the question.
    Same JSON read as deploy/targets/fly.sh t_health, for the same reason.
    """
    if not shutil.which("fly"):
        return "unknown (fly CLI not on PATH)"
    rc, out = run(["fly", "machines", "list", "-a", FLY_APP, "--json"], timeout=60)
    if rc != 0:
        return f"unknown (fly machines list rc={rc})"
    try:
        import json
        machines = json.loads(out[out.index("["):])
    except Exception:  # noqa: BLE001 - any parse failure means the same thing: cannot tell
        return "unknown (could not parse fly machines list)"
    if not machines:
        return "none (the app has no machine)"
    return str(machines[0].get("state") or "unknown")


def deployed_commit() -> tuple[str, str]:
    """The commit the running engine was built from, and how it was read.

    Two paths, because this probe runs in two places. Inside the engine image -- which is where
    the ops console runs, so this is the path the console button takes -- the stamp is a local
    file and costs nothing. From a laptop it needs one `fly ssh console`, which is slow enough
    to be worth not doing twice.
    """
    if IMAGE_STAMP.exists():
        try:
            return IMAGE_STAMP.read_text(encoding="utf-8").strip(), "read inside the container"
        except OSError as exc:
            return "", f"{IMAGE_STAMP} unreadable: {exc}"
    if not shutil.which("fly"):
        return "", "fly CLI not on PATH and not running inside the image"
    rc, out = run(["fly", "ssh", "console", "-a", FLY_APP, "-C",
                   f"/bin/cat {IMAGE_STAMP}"], timeout=120)
    match = _STAMP_RE.search(out)
    if match:
        return match.group(0), "read over fly ssh"
    if "unknown" in out:
        return "unknown", "the image was built without a GIT_SHA build argument"
    if "No such file" in out or "cat:" in out:
        return "", ("the running image predates commit stamping "
                    "(deploy/engine/Dockerfile writes /app/GIT_SHA)")
    return "", f"could not read the stamp (rc={rc}): {out.splitlines()[-1][:120] if out else ''}"


def fly_report() -> int:
    """Grade the platform production actually runs on.

    Until 2026-08-18 this probe graded the laptop checkout whatever `~/.prospector/ACTIVE` said,
    so after the cutover it answered "MISSING: /Users/chidionyema/Documents/code/prospector-live"
    and exited 1 -- a permanent red about a directory production no longer uses, while the
    question it was built to answer, which commit is live, had no answer at all on Fly.
    """
    problems: list[str] = []
    print(f"== the engine runs on FLY ({FLY_APP}) ==")

    state = fly_machine_state()
    print(f"  machine state   {state}")
    if state != "started":
        problems.append(f"the {FLY_APP} machine is {state}, not started")

    sha, how = deployed_commit()
    print(f"  deployed commit {sha or '(unknown)'}   ({how})")
    if not sha or sha == "unknown":
        problems.append("cannot tell which commit production runs")
    elif sha.endswith("-dirty"):
        problems.append("production runs an image built from a modified working tree")

    bare = sha[:40] if sha and sha != "unknown" else ""
    if bare and (DEV / ".git").exists():
        run(["git", "fetch", "--quiet", "origin", "main"], cwd=DEV, timeout=25)
        rc, main_sha = run(["git", "rev-parse", "origin/main"], cwd=DEV, timeout=15)
        if rc == 0 and main_sha:
            if main_sha == bare:
                print("  origin/main     SAME COMMIT")
            else:
                rc, behind = run(["git", "rev-list", "--count", f"{bare}..origin/main"], cwd=DEV)
                gap = behind if rc == 0 and behind.isdigit() else "?"
                print(f"  origin/main     {main_sha[:12]}   production is {gap} commit(s) behind")
                problems.append(f"production is {gap} commit(s) behind origin/main")
        _, subject = run(["git", "log", "-1", "--format=%h %ad %s", "--date=short", bare],
                         cwd=DEV, timeout=15)
        if subject:
            print(f"  which is        {subject}")

    if bare:
        verdict, detail = ci_verdict(bare)
        print(f"  CI on it        {verdict}: {detail}")
        if verdict in ("fail", "none"):
            problems.append(f"production runs {bare[:12]}, whose CI verdict is {verdict}")

    print()
    print("== the laptop standby ==")
    if DEPLOY_SOURCE.exists():
        _, dirty = run(["git", "status", "--porcelain"], cwd=DEPLOY_SOURCE)
        tracked = _code_changes(dirty)
        _, head = run(["git", "rev-parse", "--short", "HEAD"], cwd=DEPLOY_SOURCE)
        print(f"  {DEPLOY_SOURCE} at {head}"
              f"{', %d local change(s)' % len(tracked) if tracked else ', clean'}")
    else:
        # Not counted as a problem. Production is up; this is the failover source, and
        # recreating it is a decision, not a repair this probe should imply is urgent.
        print(f"  {DEPLOY_SOURCE} is MISSING, so --update has nothing to deploy from and")
        print("  failing back to the laptop is not possible. Recreate with:")
        print(f"    git clone {DEV} {DEPLOY_SOURCE}")

    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nRun with --update to build origin/main and release it to Fly.")
        return 1
    print(f"OK: {FLY_APP} runs origin/main, machine started, CI green on that commit.")
    return 0


def fly_update(unattended: bool = False) -> int:
    """Build origin/main and release it to Fly, behind the same gates as the laptop path.

    The deploy SOURCE is the clean mirror, never the shared developer checkout: `fly deploy`
    uploads a working tree, so building from a tree with a branch checked out ships that branch
    to production without saying so.
    """
    if unattended and NO_AUTO_UPDATE.exists():
        print(f"PAUSED: {NO_AUTO_UPDATE} exists - reporting only, not deploying.")
        return fly_report()
    if not DEPLOY_SOURCE.exists():
        print(f"MISSING: {DEPLOY_SOURCE} - nothing to build from.")
        print(f"  git clone {DEV} {DEPLOY_SOURCE}")
        return 1

    rc, out = run(["git", "fetch", "origin", "main"], cwd=DEPLOY_SOURCE)
    if rc != 0:
        print(f"fetch failed: {out}")
        return 1
    _, dirty = run(["git", "status", "--porcelain"], cwd=DEPLOY_SOURCE)
    tracked = _code_changes(dirty)
    if tracked:
        print(f"REFUSING: {DEPLOY_SOURCE} has local modifications, so the image would not be")
        print("the commit it claims. Changes belong in a branch and a PR:")
        for line in tracked[:10]:
            print(f"  {line}")
        return 1

    _, target = run(["git", "rev-parse", "origin/main"], cwd=DEPLOY_SOURCE)
    live_sha, _ = deployed_commit()
    if live_sha[:40] == target and target:
        print(f"already deployed: {target[:12]} is what Fly is running")
        return fly_report()

    verdict, detail = ci_verdict(target)
    if verdict == "pass":
        print(f"CI green on {target[:12]}: {detail}")
    elif ALLOW_UNVERIFIED_DEPLOY.exists():
        print(f"CI {verdict} on {target[:12]}: {detail}")
        print(f"shipping anyway - {ALLOW_UNVERIFIED_DEPLOY.name} is present")
    else:
        print(f"REFUSING to deploy {target[:12]}: CI {verdict} - {detail}")
        print(f"To ship regardless: touch {ALLOW_UNVERIFIED_DEPLOY}")
        return 1

    rc, out = run(["git", "checkout", "--detach", "--force", target], cwd=DEPLOY_SOURCE)
    if rc != 0:
        print(f"checkout failed: {out}")
        return 1
    print(f"deploy source at {target[:12]}; building and releasing to {FLY_APP}")
    # 25 minutes: the image builds a Next.js console and a python environment. A shorter
    # timeout kills a deploy that is working, which leaves the app mid-release.
    rc, out = run(["bash", str(DEPLOY_SOURCE / "deploy/targets/fly.sh"), "t_release"],
                  cwd=DEPLOY_SOURCE, timeout=1500)
    print(out[-2000:] if out else "")
    if rc != 0:
        print(f"fly release failed (rc={rc})")
        return 1
    print()
    return fly_report()


def update(unattended: bool = False) -> int:
    """Fast-forward the live checkout to origin/main, relink secrets, restart the jobs.

    `unattended` is what the scheduled job passes. It changes two things and nothing else:
    the kill switch is honoured, and being already up to date is a silent success rather
    than a thing to report. The roll-forward itself is identical, because a scheduled path
    that behaves differently from the hand-run one is a second code path to trust.

    WHY THIS RUNS ON A SCHEDULE AT ALL. Production runs from prospector-live, detached at
    origin/main. Nothing rolled it forward, so it drifted: on 2026-08-17 it was 17 hours
    behind, and later the same day 7 commits behind again, and both times the founder had
    to run this by hand because it was reported to him rather than fixed. A fix that needs
    a human to press it is not a fix; it is a dashboard.
    """
    if active_side() == "fly":
        return fly_update(unattended=unattended)

    if not LIVE.exists():
        print(f"MISSING: {LIVE} — create it with: git clone {DEV} {LIVE}")
        return 1

    if unattended and NO_AUTO_UPDATE.exists():
        print(f"PAUSED: {NO_AUTO_UPDATE} exists — reporting only, not rolling forward.")
        return report()

    _, dirty = run(["git", "status", "--porcelain"], cwd=LIVE)
    tracked = _code_changes(dirty)
    if tracked:
        print("REFUSING: the live checkout has local modifications. It must stay a clean")
        print("mirror of origin/main. Changes belong in a branch and a PR:")
        for ln in tracked[:10]:
            print(f"  {ln}")
        return 1

    rc, out = run(["git", "fetch", "origin", "main"], cwd=LIVE)
    if rc != 0:
        print(f"fetch failed: {out}")
        return 1
    _, before = run(["git", "rev-parse", "--short", "HEAD"], cwd=LIVE)

    # The CI gate. Only the roll-forward is gated, and only when it would actually move:
    # a hand-run --update on an already-current checkout must not be blocked by a red
    # verdict on code that is already live, or the operator loses the restart button
    # during exactly the incident where they need it.
    _, target = run(["git", "rev-parse", "origin/main"], cwd=LIVE)
    _, current = run(["git", "rev-parse", "HEAD"], cwd=LIVE)
    if target and target != current:
        verdict, detail = ci_verdict(target)
        if verdict == "pass":
            print(f"CI green on {target[:12]}: {detail}")
        elif ALLOW_UNVERIFIED_DEPLOY.exists():
            print(f"CI {verdict} on {target[:12]}: {detail}")
            print(f"shipping anyway — {ALLOW_UNVERIFIED_DEPLOY.name} is present")
        elif verdict == "unknown":
            # Could not ask. Refuse: an unverified deploy is the failure this gate exists
            # to stop, and the next scheduled run is 60 seconds away.
            print(f"HOLDING at {before}: could not read CI for {target[:12]} — {detail}")
            print(f"To ship regardless: touch {ALLOW_UNVERIFIED_DEPLOY}")
            return 1
        else:
            print(f"REFUSING to deploy {target[:12]}: CI {verdict} — {detail}")
            print(f"Production stays at {before}. Fix main, or: "
                  f"touch {ALLOW_UNVERIFIED_DEPLOY}")
            return 1
    # --force, and the refusal check above is what makes it safe. `_code_changes` has
    # already proved there is no modified tracked CODE here; everything left dirty is
    # tracked runtime state under store/ and storage/, which every run rewrites. A plain
    # checkout aborts on exactly those files -- measured 2026-08-17, the first scheduled
    # run exited 1 with "Please commit your changes or stash them before you switch
    # branches" over 18 store/scheduler/audit/*.jsonl files -- so without --force this job
    # can never once succeed. Discarding them loses nothing: the daemons write the
    # canonical store via PROSPECTOR_STORE_DIR, which points at the main checkout, so
    # these copies are stale duplicates that were never read.
    rc, out = run(["git", "checkout", "--detach", "--force", "origin/main"], cwd=LIVE)
    if rc != 0:
        print(f"checkout failed: {out}")
        return 1
    _, after = run(["git", "rev-parse", "--short", "HEAD"], cwd=LIVE)
    print(f"live checkout {before} -> {after}")

    if unattended and before == after:
        # Already current. Restarting the daemons for nothing would kill a tick in flight
        # every time the job runs, which is a worse outage than the drift it prevents.
        #
        # The console is the exception, and it is the case that actually happened. Code being
        # current says nothing about the build being current: `next start` serves a directory
        # that only a build writes, so a console build made before the code it serves stays
        # stale forever behind this early return. Rebuild for that, and only that.
        stale, why = console_build_is_stale()
        if not stale:
            print("already at origin/main — no restart")
            return 0
        print(f"already at origin/main, but the console build is stale ({why}) — rebuilding")
        if build_console() != 0:
            return 1
        rc, out = run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{CONSOLE_JOB}"])
        print(f"restarted {CONSOLE_JOB} (rc={rc}){' ' + out if out else ''}")
        return report()

    for rel in SECRETS:
        target = LIVE / rel
        source = DEV / rel
        if not target.exists() and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source)
            print(f"linked {rel} -> {source}")

    console_rc = build_console()

    for job in JOBS:
        if job == CONSOLE_JOB and console_rc != 0:
            # A failed build must not take the console down. `next start` keeps serving the
            # previous build directory, so not restarting leaves the operator with the old
            # console rather than no console.
            print(f"NOT restarting {job}: its build failed, so the previous build stays up")
            continue
        rc, out = run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{job}"])
        print(f"restarted {job} (rc={rc}){' ' + out if out else ''}")

    print()
    return report()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update", action="store_true",
        help="fast-forward the live checkout to origin/main and restart the daemons",
    )
    parser.add_argument(
        "--unattended", action="store_true",
        help="scheduled mode: honour the NO_AUTO_UPDATE kill switch and do not restart "
             "the daemons when the live checkout is already at origin/main",
    )
    args = parser.parse_args()
    if args.update or args.unattended:
        return update(unattended=args.unattended)
    return report()


if __name__ == "__main__":
    sys.exit(main())
