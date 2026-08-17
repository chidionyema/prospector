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


def report() -> int:
    """Print live state. Returns 0 when production is on origin/main and healthy."""
    problems: list[str] = []

    print("== the checkout the daemons are actually running from ==")
    for job in JOBS:
        pid, cwd = job_cwd(job)
        if pid is None:
            print(f"  {job:26s} NOT RUNNING")
            problems.append(f"{job} is not running")
            continue
        flag = "" if cwd == str(LIVE) else "   <- NOT the live checkout"
        print(f"  {job:26s} pid={pid:<7s} cwd={cwd}{flag}")
        if cwd != str(LIVE):
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

#: Workflow runs this gate ignores. Deploys and smoke tests run AFTER a merge and describe
#: the deployment, not the code; requiring them would deadlock the deploy on itself.
_IGNORED_WORKFLOWS = ("deploy", "smoke", "e2e")


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
    if not relevant:
        return "none", "no CI run recorded against this commit"

    waiting = [r[0] for r in relevant if r[1] != "completed"]
    if waiting:
        return "pending", f"still {relevant[0][1]}: {', '.join(waiting[:5])}"
    bad = [f"{r[0]}={r[2]}" for r in relevant if r[2] != "success"]
    if bad:
        return "fail", ", ".join(bad[:5])
    return "pass", f"{len(relevant)} run(s) green"


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
