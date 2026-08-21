#!/usr/bin/env python3
"""Inventory every automated process in this estate and grade it.

The question this answers is "what is running that we do not know about, and what is failing
quietly?". Nothing else answered it. A launchd job that fails leaves no alert, a GitHub workflow
that is never triggered leaves no red run, and a job somebody loaded by hand appears in no file
in this repo. All three are invisible by construction.

Measured 2026-08-19, before this script existed: five loaded launchd jobs carried a non-zero last
exit (two of them 78 = EX_CONFIG), four loaded jobs were declared nowhere in `ops/launchd/`, and
two workflows had never produced a single run since being committed.

What it inspects:

  launchd   declared in `ops/launchd/*.json`, installed in `~/Library/LaunchAgents`, loaded per
            `launchctl list`, last exit status, and the newest receipt in the capability ledger.
  workflows every file in `.github/workflows/`, its most recent run and that run's conclusion.

The documentation test is mechanical, not a judgement: every label and every workflow filename
must appear in `docs/PROCESS_INVENTORY.md`. Adding a process means adding a row there, so a
process cannot enter the estate undocumented.

Read-only. Exits 1 when anything is FAILING, NEVER-RAN, UNDECLARED or UNDOCUMENTED, so it can
gate CI; `--quiet` prints only the problems.

    python3 scripts/process_audit.py
    python3 scripts/process_audit.py --quiet
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import plistlib
import re
from datetime import datetime, timezone
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECLARED_DIR = ROOT / "ops" / "launchd"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
INVENTORY = ROOT / "docs" / "PROCESS_INVENTORY.md"
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
RECEIPTS = Path.home() / ".hermes" / "state" / "capability_receipts.jsonl"

# A job is OURS if this repo declares it, or if its label carries one of our prefixes. The test is
# a whitelist rather than a blocklist of vendors, because a blocklist is never finished: every new
# app installed on this Mac would arrive as an unexplained FAIL until somebody added it.
OWNED_PREFIXES = (
    "ai.hermes.", "com.prospector.", "com.prospector-control.", "com.chidionyema.",
    "com.estate.", "com.haworks.", "com.signalengine.", "com.tie.",
    "actions.runner.chidionyema",
)

OK, WARN, BAD = "ok", "warn", "bad"

#: The Fly app that hosts the self-hosted CI runners. The three mumchimp-mac
#: runners are OFF by founder decision, so this app IS the CI capacity.
CI_FLY_APP = "prospector-ci"

# Production is Fly, not this Mac. `deploy/engine/fly.toml` publishes one port and the image runs
# the scheduler, consumer, watchdog and both backups under supervisord. Every local launchd job
# below was doing that work before 2026-08-18 and is now a duplicate of it.
#
# This map exists because the alternative is worse in both directions. Grading these as FAILING
# raises an alarm every hour about work that is being done correctly somewhere else. Dropping them
# silently loses the fact that a stale, wrong copy is still installed on the laptop -- and
# com.prospector.backup is not merely idle, it fails daily and would write the laptop's store,
# which stopped being the canonical one when the engine moved.
FLY_APP = "prospector-engine"
SUPERSEDED = {
    "com.prospector.scheduler": "supervisord `scheduler` in the prospector-engine image",
    "com.prospector.consumer": "supervisord `consumer` in the prospector-engine image",
    "com.prospector.watchdog": "supervisord `watchdog` in the prospector-engine image",
    "com.prospector.backup": "supervisord `backup` in the prospector-engine image",
    "com.prospector.offsite-backup": "supervisord `offsite-backup`, gated by ENGINE_BACKUPS_ENABLED",
    "com.prospector.ops-console": "the [http_service] on port 8611 of prospector-engine",
    "com.prospector.live-update": "`fly deploy`; there is no local checkout left to roll forward",
}


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a command and return (returncode, stdout). Never raises; a failure is a return value."""
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout


def documented_names() -> set[str]:
    """Every backtick-quoted token in the inventory doc.

    Backticks rather than plain words because a label must be written as code to count -- prose
    that merely mentions a job in passing is not documentation of it.
    """
    if not INVENTORY.exists():
        return set()
    return set(re.findall(r"`([^`\n]+)`", INVENTORY.read_text(encoding="utf-8")))


def declared_labels() -> dict[str, Path]:
    """Label -> the ops/launchd JSON that declares it."""
    out: dict[str, Path] = {}
    for f in sorted(DECLARED_DIR.glob("*.json")):
        try:
            label = json.loads(f.read_text(encoding="utf-8")).get("Label")
        except (OSError, ValueError):
            continue
        if label:
            out[label] = f
    return out


def installed_labels() -> dict[str, Path]:
    """Label -> the plist installed in ~/Library/LaunchAgents.

    Only `*.plist` counts. `.bak` and `.RETIRED-*` copies sitting in that directory are inert to
    launchd, and are reported separately as litter rather than as installed jobs.
    """
    out: dict[str, Path] = {}
    for f in sorted(AGENTS_DIR.glob("*.plist")):
        try:
            label = plistlib.loads(f.read_bytes()).get("Label")
        except (OSError, ValueError):
            continue
        if label:
            out[label] = f
    return out


def loaded_jobs() -> dict[str, tuple[str, str]]:
    """Label -> (pid, last exit status) from `launchctl list`."""
    code, out = sh(["launchctl", "list"])
    if code != 0:
        return {}
    jobs: dict[str, tuple[str, str]] = {}
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3:
            jobs[parts[2].strip()] = (parts[0].strip(), parts[1].strip())
    return jobs


def newest_receipts() -> dict[str, float]:
    """Label -> newest receipt timestamp in the capability ledger."""
    latest: dict[str, float] = {}
    if not RECEIPTS.exists():
        return latest
    with RECEIPTS.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            label = rec.get("label")
            ts = rec.get("ended_at") or rec.get("started_at") or 0
            if label and ts and ts > latest.get(label, 0):
                latest[label] = float(ts)
    return latest


def age(ts: float | None) -> str:
    """A timestamp as a human age, or 'never'."""
    if not ts:
        return "never"
    hours = (time.time() - ts) / 3600
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"



def grade_fly() -> list[tuple[str, str, str]]:
    """Production. One row per Fly app, plus one per supervisord program inside the engine image.

    This section exists because the audit was born grading the wrong host. The laptop's launchd
    jobs looked like the process table and were not; `deploy/engine/fly.toml` runs the scheduler,
    consumer, watchdog and both backups under supervisord, and publishes the ops console on 8611.
    An estate probe that walks only the machine it is running on cannot see production at all.

    `fly ssh console` is a network call and it is slow, so it is asked once and only of the engine.
    A failure to reach Fly is reported as a failure to ASK, never as a healthy answer.
    """
    rows: list[tuple[str, str, str]] = []
    code, out = sh(["fly", "apps", "list", "--json"], timeout=90)
    if code != 0:
        return [(BAD, "fly", f"could not list apps: {out.strip().splitlines()[:1]}")]
    try:
        apps = json.loads(out)
    except ValueError as exc:
        return [(BAD, "fly", f"unreadable app list: {exc}")]

    for app in sorted(apps, key=lambda a: a.get("Name", "")):
        name = app.get("Name", "?")
        if not name.startswith("prospector-"):
            continue  # other products in the same org
        status = (app.get("Status") or "").lower()
        grade = OK if status == "deployed" else BAD
        rows.append((grade, name, f"fly status={status or '?'}"))

    code, out = sh(["fly", "ssh", "console", "-a", FLY_APP, "-C", "supervisorctl status"],
                   timeout=150)
    if code != 0:
        rows.append((BAD, f"{FLY_APP} processes",
                     "could not read supervisorctl -- production's process table is UNKNOWN, "
                     f"which is not the same as healthy: {out.strip().splitlines()[-1:]}"))
        return rows
    seen = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isidentifier() and "-" not in parts[0]:
            continue
        program, state = parts[0], parts[1]
        seen += 1
        rows.append((OK if state == "RUNNING" else BAD,
                     f"{FLY_APP}/{program}", " ".join(parts[1:])[:90]))
    if not seen:
        rows.append((BAD, f"{FLY_APP} processes", "supervisorctl answered, but named no programs"))
    return rows



def grade_deploys() -> list[tuple[str, str, str]]:
    """Is the live stack running what is on `main`?

    The runner row above says whether a job COULD run. This says whether the thing it was
    supposed to ship actually shipped. On 2026-08-19 those two answers came apart: every runner
    was online and busy, so nothing looked wrong, while a merge to main sat undeployed for
    twelve hours behind the queue. Nobody could see it, because no check compared the live Fly
    release to origin/main.

    `scripts/deploy_status.py` owns that comparison. This grades its verdict so it reaches the
    operator on the audit's own schedule, through the audit's own alert path.
    """
    rc, out = sh([sys.executable, str(ROOT / "scripts/deploy_status.py"), "--json"], timeout=300)
    if not out.strip():
        return [(WARN, "deploys", f"deploy_status.py said nothing (rc={rc})")]
    try:
        report = json.loads(out)
    except json.JSONDecodeError as exc:
        return [(WARN, "deploys", f"deploy_status.py returned non-JSON: {exc}")]
    # UNKNOWN grades BAD on purpose. A probe that could not measure is the shape of the failure
    # this row exists to catch, and grading it OK would rebuild the blind spot inside the guard.
    grade_of = {"LIVE": OK, "SHIPPING": OK, "DRIFTED": WARN,
                "STALLED": BAD, "FAILED": BAD, "UNKNOWN": BAD}
    rows = [(grade_of.get(d["state"], BAD), f"deploy {d['name']}", f"{d['state']} -- {d['why']}")
            for d in report.get("deployables", [])]
    fleet = report.get("runners") or {}
    if fleet.get("problem"):
        rows.append((BAD, "deploy queue", fleet["problem"]))
    return rows


def grade_ci_runners() -> list[tuple[str, str, str]]:
    """Ask GitHub which runners can actually take a job.

    This row exists because of a wrong instruction given on 2026-08-19. A PR sat queued, this
    Mac's four `actions.runner.*` launchd jobs showed three NOT LOADED, and the obvious-looking
    conclusion was that CI had no runners. CI runs on the Fly app `prospector-ci`. The three
    Macs are offline on purpose, and the queue was capacity: every online runner was busy.

    The launchd section below cannot answer this. It measures jobs on this Mac, and the answer
    is not on this Mac. So the question goes to the only place that knows -- the GitHub API,
    which sees every runner of every kind and whether it is free.
    """
    rc, out = sh(["gh", "api", "repos/chidionyema/prospector/actions/runners",
                  # Raw: every \( here is jq interpolation, not a Python escape.
                  "--jq", r'.runners[] | "\(.name)\t\(.status)\t\(.busy)\t'
                          r'\(.labels|map(.name)|join(","))"'], timeout=60)
    if rc != 0 or not out.strip():
        return [(WARN, "CI runners", "cannot ask GitHub (gh missing, unauthenticated or offline)")]

    online, busy, rows = [], [], []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, status, is_busy, labels = parts[0], parts[1], parts[2], parts[3]
        where = "Fly" if "fly" in labels else "this Mac"
        if status != "online":
            # The two cases are not the same, and grading them the same is how this row would
            # go unread. A Mac runner offline is the estate's own decision. A Fly runner
            # offline is capacity that used to be there and is not -- either an autostopped
            # machine or one that died, and if every Fly runner goes that way, heavy jobs
            # queue forever with nothing on this Mac able to take them.
            if where == "Fly":
                rows.append((WARN, f"runner {name}",
                             "offline (Fly) -- autostopped or gone: fly status -a prospector-ci"))
            else:
                rows.append((OK, f"runner {name}",
                             "offline (this Mac) -- off by design, CI runs on prospector-ci"))
            continue
        online.append(name)
        if is_busy == "true":
            busy.append(name)
        rows.append((OK, f"runner {name}",
                     f"online ({where}), {'BUSY' if is_busy == 'true' else 'free'} -- {labels}"))

    if not online:
        head = (BAD, "CI runners", "NO runner online -- every workflow will queue forever. "
                                   "CI runs on the Fly app prospector-ci, not on this Mac: "
                                   "fly status -a prospector-ci")
    elif len(busy) == len(online):
        head = (WARN, "CI runners",
                f"all {len(online)} online runner(s) BUSY -- a queued PR is capacity, not a "
                f"dead runner. Do not start the local actions.runner.* jobs; they are off by "
                f"design and CI lives on the Fly app prospector-ci")
    else:
        head = (OK, "CI runners",
                f"{len(online)} online, {len(busy)} busy -- CI runs on the Fly app prospector-ci")
    return [head] + rows


def grade_launchd(docs: set[str]) -> list[tuple[str, str, str]]:
    """One (grade, label, detail) row per launchd job we own."""
    declared, installed, loaded, receipts = (
        declared_labels(), installed_labels(), loaded_jobs(), newest_receipts())
    rows: list[tuple[str, str, str]] = []
    for label in sorted(set(declared) | set(installed) | set(loaded)):
        if label not in declared and not label.startswith(OWNED_PREFIXES):
            continue  # somebody else's software on this Mac
        where = []
        if label in declared:
            where.append("declared")
        if label in installed:
            where.append("installed")
        pid, status = loaded.get(label, ("", ""))
        if label in loaded:
            where.append(f"loaded pid={pid or '-'}")
        seen = f"last receipt {age(receipts.get(label))}"
        detail = f"{', '.join(where)}; exit={status or '-'}; {seen}"

        # A negative status is a signal, which is how a long-running daemon normally stops. Only a
        # positive exit code is a job that ran and failed.
        try:
            failed = int(status) > 0
        except ValueError:
            failed = False

        if label in SUPERSEDED:
            note = f"SUPERSEDED by {SUPERSEDED[label]}"
            if label in installed or label in loaded:
                rows.append((WARN, label, f"{note}; still installed here -- uninstall it -- {detail}"))
            else:
                rows.append((OK, label, f"{note}; correctly absent from this Mac"))
        elif failed:
            rows.append((BAD, label, f"FAILING exit {status} -- {detail}"))
        elif label in installed and label not in loaded:
            # The worst state in the estate, and the one that was invisible until 2026-08-19: the
            # plist is tracked in the repo, the plist is on disk, and launchd is simply not running
            # it. Nothing else looks for this. A grader that walks only LOADED jobs cannot see a job
            # that is absent, and a job that never runs never fails, so it appears nowhere at all.
            # Measured that day: com.prospector.scheduler, .consumer, .watchdog and .ops-console
            # were all installed and none was loaded, while the audit reported 15 other problems.
            # WARN, not FAIL, and the distinction is the point. That the job is not running is a
            # fact this probe measured. That it OUGHT to be running is a claim it cannot make: only
            # one GitHub runner of four is meant to be up at a time, and the ngrok tunnel is off on
            # purpose. An alarm that cries about six deliberate choices is an alarm nobody reads,
            # and the first real outage arrives in a list already full of noise.
            why = ("; off by design -- CI runs on the Fly app prospector-ci"
                   if label.startswith("actions.runner.") else "")
            rows.append((WARN, label,
                         f"NOT LOADED, launchd is not running it -- {detail}{why}"))
        elif label in loaded and label not in declared:
            rows.append((BAD, label, f"UNDECLARED, no ops/launchd JSON -- {detail}"))
        elif label not in docs:
            rows.append((BAD, label, f"UNDOCUMENTED, absent from {INVENTORY.name} -- {detail}"))
        elif label in declared and label not in installed:
            rows.append((BAD, label, f"NOT INSTALLED, declared but no plist on disk -- {detail}"))
        else:
            rows.append((OK, label, detail))
    return rows


def grade_workflows(docs: set[str]) -> list[tuple[str, str, str]]:
    """One (grade, filename, detail) row per GitHub workflow.

    The measurement is `scripts/workflow_health.py`, not a second count of the same fact. Two
    things it fixes here, both of which produced wrong rows on this page.

    DEAD is not FAILING. A workflow GitHub cannot START concludes instantly having run ZERO
    jobs: no log, no annotation, no red check on any pull request. It looks exactly like a
    workflow with a broken test, so `ci-autoscale.yml` sat in this list among the ordinary reds
    for thirty consecutive runs and the CI pool was never scaled automatically once.

    And NEVER-RAN was largely a lie. The old version read one global `gh run list --limit 200`,
    a window that on a busy repository does not reach back to a workflow triggered weekly -- so
    on 2026-08-19 it reported `deploy-api.yml`, `escape-hatch-drill.yml` and
    `weekly-estate-review.yml` as never having run when all three had. Health is asked per
    workflow now, through the workflows API, which has no such window.
    """
    spec = importlib.util.spec_from_file_location("workflow_health", ROOT / "scripts" / "workflow_health.py")
    wfh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wfh)
    try:
        report = wfh.grade(wfh._repo(None), 5)
    except Exception as exc:  # noqa: BLE001 -- "could not ask GitHub" is a WARN, never a green
        return [(WARN, f.name, f"could not ask GitHub ({type(exc).__name__}: {exc})".replace("\n", " ")[:160])
                for f in sorted(WORKFLOW_DIR.glob("*.y*ml"))]

    by_path = {r["path"]: r for r in report["workflows"]}
    rows: list[tuple[str, str, str]] = []
    for f in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        row = by_path.get(f".github/workflows/{f.name}")
        if row is None:
            # GitHub does not know this file yet: a workflow added on a branch and not on main.
            rows.append((WARN, f.name, "GitHub has no workflow for this file yet"))
            continue
        verdict, graded = row["verdict"], row["runs_graded"]
        if verdict.startswith("DEAD"):
            rows.append((BAD, f.name, f"DEAD -- {graded}/{graded} runs produced ZERO jobs, so "
                                      f"GitHub could not start it. Run `actionlint {f.name}`."))
        elif verdict == "failing every run":
            plural = "run" if graded == 1 else "runs"
            rows.append((BAD, f.name, f"FAILING -- the last {graded} {plural} all failed"))
        elif "produced zero jobs" in verdict:
            rows.append((BAD, f.name, f"DEGRADED -- {verdict}"))
        elif verdict == "no recent runs":
            rows.append((WARN, f.name, "no runs at all in the window"))
        elif f.name not in docs:
            rows.append((BAD, f.name, f"UNDOCUMENTED, absent from {INVENTORY.name} -- "
                                      f"{graded} recent runs, ok"))
        else:
            rows.append((OK, f.name, f"{graded} recent runs, ok"))
    return rows


# A worktree this far behind origin/main is not "a bit stale". It is a different estate: the
# CLAUDE.md, the docs and the scripts a session reads there describe an older system, and the
# session cannot tell. 25 is the line because the 2026-08-19 false outage was called from a
# checkout 59 commits behind, and the pre-Fly production section it read had been wrong for a day.
DRIFT_BAD = 25


def grade_worktree_drift() -> list[tuple[str, str, str]]:
    """How far has each worktree drifted from origin/main, and can it close the gap by itself?

    Founder, 2026-08-19: "need to address branch and worktree divergence from main branch, need
    constant refresh". Divergence is measured by scripts/worktree_gc.py, which owns worktrees;
    this only grades what it reports. A tree with no local commits can be fast-forwarded with no
    risk, so leaving it behind is a choice nobody made. A tree with local commits needs a rebase
    its owner must run.
    """
    gc = ROOT / "scripts" / "worktree_gc.py"
    if not gc.exists():
        return [(BAD, "worktree drift", f"MISSING {gc.relative_to(ROOT)}")]
    try:
        r = subprocess.run([sys.executable, str(gc), "--json"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        data = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as e:
        return [(BAD, "worktree drift", f"could not measure: {type(e).__name__}")]

    drift = data.get("drift") or []
    if not drift:
        return [(OK, "worktree drift", "every worktree is level with origin/main")]

    rows: list[tuple[str, str, str]] = []
    far = sorted((d for d in drift if d["behind"] >= DRIFT_BAD),
                 key=lambda d: -d["behind"])
    ff = [d for d in drift if d["action"] == "fast-forward" and d["clean"]]

    rows.append((BAD if far else WARN, "worktree drift",
                 f"{len(drift)} worktree(s) behind origin/main, "
                 f"{len(far)} by {DRIFT_BAD}+ commits -- a session opening in one is briefed "
                 f"on an older estate"))
    for d in far[:8]:
        rows.append((BAD, f"drift: {d['branch']}",
                     f"{d['behind']} behind, {d['ahead']} ahead -- "
                     f"git -C {d['path']} rebase origin/main"))
    if ff:
        rows.append((WARN, "worktree drift (refreshable)",
                     f"{len(ff)} worktree(s) have no local commits and can close the gap with "
                     f"no risk -- .venv/bin/python scripts/worktree_gc.py --refresh"))
    return rows


def grade_enforcement() -> list[tuple[str, str, str]]:
    """Grade the mechanisms that are supposed to be REFUSING bad work.

    This is the collector the other two cannot replace. A launchd job that fails leaves a status,
    and a workflow that fails leaves a red run, but a guard that is switched off leaves nothing at
    all -- no output, no run, no error. It simply stops objecting, and every commit after that
    looks exactly like a commit it approved.

    That is not hypothetical here. The pre-commit gate has been turned off and on twice by hand,
    and on 2026-08-16 a session spent hours reasoning from a doc that said no gate could have
    refused a commit while the gate was refusing it. The point of this collector is that the
    answer becomes a line in a report instead of a paragraph somebody has to remember to distrust.
    """
    rows: list[tuple[str, str, str]] = []

    # The POPDD pre-commit gate. `core.hooksPath`, when set, replaces .git/hooks entirely, so the
    # only honest question is what git resolves -- never what is sitting in .git/hooks.
    code, hooks_path = sh(["git", "rev-parse", "--git-path", "hooks"])
    hook = Path(hooks_path.strip()) / "pre-commit" if code == 0 else None
    if hook and hook.exists():
        rows.append((OK, "pre-commit gate", f"installed at {hook}"))
    else:
        rows.append((WARN, "pre-commit gate",
                     f"NOT installed ({hook or 'could not ask git'}); commits run no local gate"))

    # Graphify keeps every repo's knowledge graph fresh through git and harness hooks.
    code, out = sh([sys.executable, "scripts/graphify_sweep.py", "--check-hooks"], timeout=90)
    rows.append((OK if code == 0 else BAD, "graphify hooks",
                 "wired" if code == 0 else f"NOT wired -- {(out.strip().splitlines() or ['?'])[-1]}"))

    # Every hook the harness is configured to fire must exist. A renamed script leaves a hook that
    # silently never runs.
    settings = Path.home() / ".claude" / "settings.json"
    missing: list[str] = []
    events = 0
    if settings.exists():
        try:
            hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
        except ValueError:
            hooks = {}
        for _event, matchers in hooks.items():
            for matcher in matchers or []:
                for h in matcher.get("hooks", []) or []:
                    cmd = str(h.get("command", ""))
                    events += 1
                    for token in re.findall(r"(/[\w./~-]+\.(?:py|sh))", cmd):
                        target = Path(token.replace("~", str(Path.home())))
                        if not target.exists():
                            missing.append(token)
    rows.append((BAD if missing else OK, "claude hooks",
                 f"{events} registered, missing: {', '.join(missing)}" if missing
                 else f"{events} registered, all present"))

    # The CI guard job is what enforces the repo's ratchets (doc lint, tool registry, baselines).
    ci = WORKFLOW_DIR / "ci.yml"
    has_guard = ci.exists() and re.search(r"^\s{2}guard:", ci.read_text(encoding="utf-8"), re.M)
    rows.append((OK if has_guard else BAD, "ci guard job",
                 "present in ci.yml" if has_guard else "MISSING from ci.yml"))

    # The doc-lint ratchet only ratchets while its baseline is committed AND every suppression in
    # it still has a deadline in front of it. A baseline holding every live finding with no
    # burn-down date is green forever while every finding is real
    # (docs/incidents/INC-2026-08-18-doc-rot-ratchet.json), so the deadline is what is graded here.
    rows.append(_grade_doc_lint_baseline())

    rows.extend(_grade_state_probe())
    rows.extend(_grade_session_hooks())
    rows.extend(_grade_agent_memory())
    rows.extend(_grade_instruction_checkouts())
    rows.extend(_grade_scheduled_workflows())
    rows.extend(_grade_ci_capacity())
    return rows


def _store_root() -> str:
    """The canonical store, asked of prospector.config rather than derived from this file's path.

    A store path built from `__file__` follows the CODE. On 2026-08-17 four constants did that and
    the health marks, the retrieval cache and the scheduler audit trail were written beside a new
    checkout while the ledger went to the real store.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from prospector.config import store_root
        return str(store_root())
    except Exception:  # noqa: BLE001 -- the audit must still run outside a configured checkout
        return os.environ.get("PROSPECTOR_STORE_DIR",
                              str(Path.home() / "Documents" / "code" / "prospector" / "store"))


def _grade_doc_lint_baseline() -> tuple[str, str, str]:
    """Is the doc-lint ratchet still able to go red?

    Three ways it cannot: the baseline is gone, an entry has no burn-down date, or a deadline has
    already passed and nobody burned the findings down. The last one is a real failure and reads
    as one, because a deadline nobody is graded against is the same warning fence again.
    """
    baseline = ROOT / "docs" / "doc_lint_baseline.json"
    if not baseline.exists():
        return (BAD, "doc lint baseline", "MISSING, so the ratchet cannot tighten")
    try:
        raw = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (BAD, "doc lint baseline", f"unreadable: {exc}")

    dates = {rel: v.get("expires") for rel, v in raw.items() if isinstance(v, dict)}
    undated = sorted(set(raw) - {rel for rel, when in dates.items() if when})
    if undated:
        return (BAD, "doc lint baseline",
                f"{len(undated)} suppression(s) with no burn-down date, e.g. {undated[0]} — "
                f"run `python3 scripts/doc_lint.py --write-baseline`")

    today = _dt.date.today().isoformat()
    overdue = sorted(rel for rel, when in dates.items() if when < today)
    if overdue:
        return (BAD, "doc lint baseline",
                f"{len(overdue)} suppression(s) past their burn-down date, e.g. {overdue[0]}")
    if not dates:
        # The empty case, and it is the BEST state the ratchet can be in: every suppression
        # burned down, nothing left to expire. `min()` over it raised
        # `ValueError: min() iterable argument is empty`, which killed the whole audit --
        # see `_section` below for why one grader could do that. Measured 2026-08-20:
        # docs/doc_lint_baseline.json is `{}` on origin/main, so this fired on every run.
        return (OK, "doc lint baseline", "0 doc(s) suppressed -- the ratchet is fully burned down")
    soonest = min(dates.values())
    return (OK, "doc lint baseline",
            f"{len(dates)} doc(s) suppressed, next burn-down due {soonest}")


def _grade_state_probe() -> list[tuple[str, str, str]]:
    """Is every session still being told where production is?

    The SessionStart probe is the only mechanism that beats a stale CLAUDE.md, and it runs from an
    installed copy outside the repo. Two ways it can fail quietly: the copy drifts from the
    reviewed source, or a project directory loses its pointer and those sessions open blind. Both
    are graded here, because an enforcement nobody grades is an enforcement nobody has.
    """
    rows: list[tuple[str, str, str]] = []
    source = ROOT / "ops" / "state_probe.sh"
    installed = Path.home() / ".claude" / "state-probe" / "prospector.sh"

    if not source.exists():
        return [(BAD, "state probe", f"MISSING from the repo at {source.relative_to(ROOT)}")]
    if not installed.exists():
        return [(BAD, "state probe", "NOT INSTALLED -- sessions open on prose, not live state; "
                                     "run bash ops/state_probe.sh --install")]

    src = hashlib.sha256(source.read_bytes()).hexdigest()
    got = hashlib.sha256(installed.read_bytes()).hexdigest()
    if src != got:
        rows.append((BAD, "state probe", "INSTALLED COPY DRIFTED from ops/state_probe.sh -- "
                                         "sessions are briefed by unreviewed text; re-run "
                                         "bash ops/state_probe.sh --install"))
    else:
        rows.append((OK, "state probe", f"installed and matching source ({src[:12]})"))

    # The probe installs a second file: the founder-task reader it calls. One copy graded and the
    # other not is how the first copy came to carry 17 lines that were in no commit anywhere.
    reader_src = ROOT / "scripts" / "founder_tasks.py"
    reader_installed = Path.home() / ".claude" / "state-probe" / "founder_tasks.py"
    if reader_src.exists():
        if not reader_installed.exists():
            rows.append((BAD, "founder task reader",
                         "NOT INSTALLED -- every session opens without the task list; "
                         "run bash ops/state_probe.sh --install"))
        elif (hashlib.sha256(reader_src.read_bytes()).hexdigest()
              != hashlib.sha256(reader_installed.read_bytes()).hexdigest()):
            rows.append((BAD, "founder task reader",
                         "INSTALLED COPY DRIFTED from scripts/founder_tasks.py -- re-run "
                         "bash ops/state_probe.sh --install"))
        else:
            rows.append((OK, "founder task reader", "installed and matching source"))

    projects = Path.home() / ".claude" / "projects"
    targets = [d for d in projects.glob("*") if d.is_dir() and "-private-" not in d.name
               and (d.name.endswith("code-prospector") or "-code-wt-" in d.name)]
    blind = [d.name for d in targets if not (d / ".state-probe").exists()]
    if blind:
        rows.append((BAD, "state probe pointers",
                     f"{len(blind)} project dir(s) have no .state-probe, so sessions started "
                     f"there open blind: {', '.join(sorted(blind)[:3])}"))
    else:
        # A pointer that names no checkout still briefs the session on the estate, but cannot say
        # how stale the code and CLAUDE.md in front of it are -- which is the failure that started
        # this work. Re-running --install matches any new project directory to a checkout on disk.
        vague = [d.name for d in targets
                 if "--checkout" not in (d / ".state-probe").read_text(errors="replace")]
        if vague:
            rows.append((WARN, "state probe pointers",
                         f"{len(targets)} wired, but {len(vague)} name no checkout, so those "
                         f"sessions are not told how far behind their own tree is; re-run "
                         f"bash ops/state_probe.sh --install"))
        else:
            rows.append((OK, "state probe pointers",
                         f"{len(targets)} project dir(s) wired, each naming its checkout"))

    # The probe renders a snapshot. If nothing refreshes that snapshot the probe becomes the
    # stale paragraph it replaced -- correct-looking, months old, no tell from the inside. The
    # probe refreshes it in the background past 6h; this row is the guard on that self-healing,
    # because a background refresh that silently stopped working looks exactly like one that has
    # nothing to do.
    snap = Path(_store_root()) / "ops" / "estate_map.json"
    if not snap.exists():
        rows.append((BAD, "estate snapshot",
                     "MISSING -- sessions are briefed with no measured estate at all; run "
                     ".venv/bin/python scripts/estate_map.py --snapshot"))
    else:
        age_h = (time.time() - snap.stat().st_mtime) / 3600
        if age_h > 24:
            rows.append((BAD, "estate snapshot",
                         f"{age_h/24:.1f} DAYS old -- the probe's background refresh is not "
                         f"running. Every session is being briefed on a stale measurement"))
        elif age_h > 8:
            rows.append((WARN, "estate snapshot",
                         f"{age_h:.0f}h old -- past the probe's 6h refresh threshold, so the "
                         f"next session start should refresh it. Still stale if this persists"))
        else:
            rows.append((OK, "estate snapshot",
                         f"measured {age_h*60:.0f}m ago" if age_h < 1 else
                         f"measured {age_h:.0f}h ago"))
    return rows




# Every checkout on this Mac that carries a CLAUDE.md. The harness loads the one belonging to the
# session's working directory, so a stale checkout does not merely hold old code -- it hands the
# agent an old description of the estate as authoritative instructions.
INSTRUCTION_CHECKOUTS = (
    Path.home() / "Documents" / "code" / "prospector",
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents" / "code"
    / "prospector",
)


def _grade_instruction_checkouts() -> list[tuple[str, str, str]]:
    """A checkout whose CLAUDE.md is behind main is an agent briefed on an estate we no longer run.

    This is the enforcement that was missing on 2026-08-19, and its absence cost a session. The
    iCloud checkout was 59 commits behind `origin/main`. Its CLAUDE.md still said production ran
    from a local `prospector-live` directory; production had moved to Fly the day before. Working
    from that file I read the laptop's launchd jobs as the production process table, found six of
    them unloaded, and reported an outage while the engine was ruling verdicts in lhr.

    Founder, that day: "we can't be guessing how our system works". Nothing was guessed -- the
    instructions were read, and they were 59 commits old. Stale instructions are indistinguishable
    from correct ones from the inside, which is exactly why this has to be a probe.
    """
    rows: list[tuple[str, str, str]] = []
    for checkout in INSTRUCTION_CHECKOUTS:
        if not (checkout / "CLAUDE.md").exists():
            continue
        name = f"instructions: {checkout.name} ({'iCloud' if 'CloudDocs' in str(checkout) else 'local'})"
        code, _ = sh(["git", "-C", str(checkout), "fetch", "-q", "origin", "main"], timeout=90)
        code, out = sh(["git", "-C", str(checkout), "rev-list", "--count", "HEAD..origin/main"])
        if code != 0:
            rows.append((WARN, name, f"could not measure: {out.strip()[:120]}"))
            continue
        try:
            behind = int(out.strip())
        except ValueError:
            rows.append((WARN, name, f"unreadable count {out.strip()[:60]!r}"))
            continue
        if behind == 0:
            rows.append((OK, name, "current with origin/main"))
        else:
            rows.append((BAD, name,
                         f"{behind} commits behind origin/main -- any session started here is "
                         f"briefed on a stale estate"))
    return rows



def _hook_staleness(path: Path) -> str:
    """Is the hook file at this path behind what has been reviewed and merged?

    A hook is executed FROM THE PATH settings.json names, not from whatever branch a session is
    working on. Measured 2026-08-19: two hooks point into a developer checkout that was 60
    commits behind `origin/main`, so every session in the estate was policed by unreviewed,
    out-of-date code -- and there was no tell, because a hook that runs successfully looks the
    same whatever version it is.

    Returns a phrase to append to the row, empty when the file is current or not in a repo.
    """
    rc, top = sh(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], timeout=15)
    if rc != 0 or not top.strip():
        return " -- not in a git repository, so nothing reviews it"
    rc, behind = sh(["git", "-C", top.strip(), "rev-list", "--count", "HEAD..origin/main",
                     "--", str(path)], timeout=20)
    if rc != 0 or not behind.strip().isdigit():
        return ""
    n = int(behind.strip())
    if n == 0:
        return ""
    return (f" -- WARNING: this file is {n} commit(s) behind origin/main in "
            f"{Path(top.strip()).name}; sessions run THIS copy, not main")


def _grade_agent_memory() -> list[tuple[str, str, str]]:
    """Can a session in THIS checkout read what a session in another checkout learned?

    Claude Code stores agent memory per working directory: ~/.claude/projects/<cwd-slug>/memory.
    This estate has three prospector checkouts and about thirty-five worktrees, so it has that
    many separate stores. Counted 2026-08-19: 390 files in one, 13 in another, 1 in a third, and
    zero in every worktree, with no overlap but the index file. A session started anywhere but
    the main checkout could see 13 of 391 lessons.

    The cost is not hypothetical. Two sessions hit the same trap on the same day -- CI runs on
    the Fly app prospector-ci, not on this Mac -- and each wrote its own memory file about it,
    in its own store, neither able to see the other's.

    `bash ops/share_memory.sh --apply` merges them into ~/.claude/memory/prospector and links
    every slug at it. This row says whether that has been done, because a fix nobody applied
    looks exactly like a fix nobody needed.
    """
    projects = Path.home() / ".claude" / "projects"
    shared = Path.home() / ".claude" / "memory" / "prospector"
    if not projects.is_dir():
        return [(WARN, "agent memory", f"no {projects} -- cannot tell what sessions can read")]

    stores = [d / "memory" for d in projects.glob("*")
              if d.is_dir() and "-private-" not in d.name
              and (d.name.endswith("code-prospector") or "-code-wt-" in d.name
                   or d.name == "prospector")]
    stores = [m for m in stores if m.exists()]
    if not stores:
        return [(WARN, "agent memory", "no memory store for any prospector checkout")]

    linked = [m for m in stores if m.is_symlink()]
    split = [m for m in stores if not m.is_symlink()]
    if not split:
        n = len(list(shared.glob("*.md"))) if shared.is_dir() else 0
        return [(OK, "agent memory",
                 f"{len(linked)} checkout(s) share one store of {n} memories at "
                 f"~/.claude/memory/prospector -- a lesson learned in any checkout is readable "
                 f"in all of them")]

    sizes = sorted(((len(list(m.glob("*.md"))), m.parent.name) for m in split), reverse=True)
    biggest = sizes[0][0]
    smallest = sizes[-1][0]
    return [(BAD, "agent memory",
             f"PARTITIONED across {len(split)} store(s): {biggest} memories in one, {smallest} "
             f"in another. A session in the smaller checkout is blind to what the other learned, "
             f"and writes a duplicate instead. Fix: bash ops/share_memory.sh --apply")]


def _grade_session_hooks() -> list[tuple[str, str, str]]:
    """Grade the hooks that police every agent turn, because nothing else did.

    These twelve scripts are the only enforcement that runs on every session in this estate:
    they refuse a forbidden command, stop a drip of one-command turns, block a push with no PR.
    None of them is in a git repository, so none is covered by CI, and a hook that starts
    crashing fails OPEN -- the harness ignores a broken hook and the turn proceeds. That is the
    right failure mode for the session and a silent one for the estate, which is why it belongs
    on this dashboard.

    Two questions per hook. Is the file still where settings.json says it is, and where the hook
    ships a `--selftest`, does that selftest still pass? A hook with no selftest is graded WARN,
    not OK: it is enforcing rules with nothing checking that it enforces the right ones.
    """
    settings = Path.home() / ".claude" / "settings.json"
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [(BAD, "session hooks", f"cannot read {settings}: {exc}")]

    commands: dict[str, list[str]] = {}
    for event, groups in (cfg.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks") or []:
                cmd = str(hook.get("command", ""))
                m = re.search(r"(\S+\.py)", cmd)
                if not m:
                    continue
                path = m.group(1).strip("'\"")
                commands.setdefault(path, []).append(event)

    if not commands:
        return [(BAD, "session hooks", f"no hooks configured in {settings} -- every rule is prose")]

    rows: list[tuple[str, str, str]] = []
    ok = tested = 0
    for raw, events in sorted(commands.items()):
        path = Path(os.path.expandvars(raw)).expanduser()
        name = path.name
        where = "+".join(sorted(set(events)))
        if not path.exists():
            rows.append((BAD, f"hook {name}", f"CONFIGURED for {where} but MISSING at {path} -- "
                                              f"the harness fails open, so this rule is unenforced"))
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append((BAD, f"hook {name}", f"unreadable: {exc}"))
            continue
        stale = _hook_staleness(path)
        if "--selftest" not in body:
            rows.append((WARN, f"hook {name}", f"{where}: no --selftest, so nothing checks it "
                                               f"enforces the right thing{stale}"))
            continue
        tested += 1
        try:
            r = subprocess.run([sys.executable, str(path), "--selftest"],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append((BAD, f"hook {name}", f"selftest did not finish: {exc}"))
            continue
        last = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        verdict = last[-1][:70] if last else "no output"
        if r.returncode == 0:
            ok += 1
            # A passing selftest on a stale file proves the STALE file is self-consistent. It
            # says nothing about whether main has since fixed the rule, so the row must not
            # read green on that alone.
            rows.append((WARN if "WARNING" in stale else OK,
                         f"hook {name}", f"{where}: {verdict}{stale}"))
        else:
            rows.append((BAD, f"hook {name}", f"{where}: SELFTEST FAILING -- {verdict}"))

    head = (OK if tested and ok == tested else WARN,
            "session hooks",
            f"{len(commands)} hook file(s) across {sum(len(v) for v in commands.values())} "
            f"registrations, {tested} carry a selftest, {ok} of those pass. Most live in "
            f"~/.claude/scripts, outside any repository, so CI never sees them; the rows below "
            f"say which are behind main")
    return [head] + rows


def grade_specialists() -> list[tuple[str, str, str]]:
    """Ask each specialist probe for its verdict, and grade the answer.

    This estate is not short of probes. `launchd_plists.py --check` owns drift between the live
    plists and the tracked copies; `supervisor.py` owns whether a job is loaded; the capability
    ledger owns whether a run happened. Every one of them is better at its own question than a
    general script would be, so nothing here re-implements them.

    What nothing did was ask the probes. A probe that starts failing -- or starts erroring before
    it can measure anything -- goes quiet in exactly the same way as the thing it was watching,
    and the estate reads as healthy because no one is left to say otherwise. So this collector
    runs them and reports two different things: the verdict, and whether the probe could answer
    at all.
    """
    rows: list[tuple[str, str, str]] = []
    for name, cmd in (
        ("plist drift", [sys.executable, "scripts/launchd_plists.py", "--check"]),
        ("session hygiene", [sys.executable, "scripts/session_check.py"]),
    ):
        script = ROOT / cmd[1]
        if not script.exists():
            rows.append((BAD, name, f"{cmd[1]} is gone, so this is no longer measured"))
            continue
        code, out = sh(cmd, timeout=180)
        tail = (out.strip().splitlines() or ["no output"])[-1][:140]
        rows.append((OK if code == 0 else WARN, name, f"exit {code} -- {tail}"))
    return rows


def orphaned_worktrees() -> list[tuple[str, str, str]]:
    """Directories that look like git worktrees but whose metadata has been pruned.

    `git worktree list` cannot see these, so every tool built on it reports a clean estate while
    the directories sit there. They are not inert: anything walking the code root and treating a
    `.git` file as a repository breaks on them. Measured 2026-08-19, wt-cardsub and wt-site-pr had
    been orphaned since 2026-08-18 and were crashing the graphify sweep every 30 minutes, which is
    the only reason anybody found them.

    Reported, never removed. A pruned worktree can still hold edits nobody committed, and git can
    no longer tell us whether it does, so deleting one is a decision a person makes.
    """
    rows: list[tuple[str, str, str]] = []
    code, out = sh(["git", "worktree", "list", "--porcelain"])
    live = {ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("worktree ")}
    for entry in sorted(ROOT.parent.iterdir()):
        if not entry.is_dir() or str(entry) in live:
            continue
        dotgit = entry / ".git"
        if not dotgit.is_file():
            continue
        try:
            target = dotgit.read_text(encoding="utf-8").partition("gitdir:")[2].strip()
        except OSError:
            continue
        if target and not Path(target).is_dir():
            rows.append((BAD, entry.name, f"ORPHANED worktree -- gitdir {target} is gone; "
                                          "git cannot see it, and it may hold uncommitted edits"))
    return rows


def alert(payload: dict, cfg=None) -> str:
    """Raise the failing checks through the estate's own alert path, durably.

    It used to import `~/.hermes/scripts/estate_alert.py` directly. That module is outside this
    repository, so on any host without a Hermes checkout -- which includes `prospector-engine`,
    where production actually runs -- the import failed, this function returned the string
    `could not alert: No module named estate_alert`, and NOTHING GRADED THAT STRING. The audit
    printed it, exited 1 for the findings, and no operator was told. An alerting rail whose own
    failure is invisible is worse than no rail, because the estate is then graded as watched.

    `alerts.emit_alert` is this repo's one alert door and it is strictly wider: it appends the
    record to `alerts.jsonl` with an fsync BEFORE any sink is tried, marks it active in
    ALERT.txt, then pushes to desktop, webhook and Telegram -- and its Telegram sink loads the
    same Hermes sender this used to import, so nothing is lost where Hermes IS present. The
    durable record is the point. When every sink is missing there is still a receipt saying the
    estate was failing at this time, and `active_alerts()` can still show it.

    Never raises, and never returns a bland string on failure: a broken alert path says so in
    words a reader cannot mistake for success. Observing a job must not be able to fail it.
    """
    lines = [f"{n}: {d}" for sec in payload["sections"] for g, n, d in
             ((r["grade"], r["name"], r["detail"]) for r in sec["rows"]) if g == BAD]
    if not lines:
        return "nothing to alert"

    names = [ln.split(":", 1)[0] for ln in lines]
    failing = payload["failing"]
    try:
        from prospector.config import load_config
        from prospector.scheduler.alerts import emit_alert
        emit_alert(cfg if cfg is not None else load_config(),
                   severity="critical", key="process-audit",
                   title=f"process audit: {failing} failing",
                   message=f"process audit: {failing} failing\n" + "\n".join(lines[:12]),
                   throttle_s=3600, failing=failing, checks=names[:12])
    except Exception as exc:  # noqa: BLE001 -- see the docstring; this must not fail the audit
        return f"ALERT PATH BROKEN ({type(exc).__name__}: {exc}) -- {failing} failing went unsent"
    return f"alert recorded ({failing} failing: {', '.join(names[:4])})"


def litter() -> list[str]:
    """Non-plist files loitering in ~/Library/LaunchAgents.

    launchd ignores them, so they are not jobs. They are stale copies that make the directory
    unreadable, and each one is a plist somebody meant to keep "just in case".
    """
    return sorted(
        p.name for p in AGENTS_DIR.glob("*")
        if p.is_file() and p.suffix != ".plist" and not p.name.startswith("."))


#: How long after its due time a scheduled workflow may stay silent before the audit calls it
#: stalled. GitHub delays scheduled runs under load, routinely by minutes and occasionally by
#: hours, so one missed slot is noise. Two in a row is not.
_SCHEDULE_GRACE = 2.0


def _cron_period_hours(cron: str) -> float | None:
    """Roughly how often this cron fires, in hours. None when the shape is not one we grade.

    Deliberately crude. It reads three shapes -- weekly, daily, hourly -- because those are the
    three this estate uses, and a wrong answer here would produce a false alarm about a job that
    is fine. Anything else returns None and the row reports the last conclusion without an age.
    """
    f = cron.split()
    if len(f) != 5:
        return None
    minute, hour, dom, _month, dow = f
    if dow != "*":
        return 24 * 7
    if dom != "*":
        return 24 * 30
    if hour != "*":
        return 24
    if minute != "*":
        return 1
    return None


def _scheduled_workflows() -> list[tuple[str, str, str]]:
    """(display name, filename, cron) for every workflow this repo schedules."""
    out = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^\s*schedule:", text, re.M):
            continue
        cron = re.search(r"^\s*-\s*cron:\s*[\"\']?([^\"\'#\n]+)", text, re.M)
        name = re.search(r"^name:\s*(.+)$", text, re.M)
        out.append(((name.group(1).strip().strip("\"\'") if name else path.stem),
                    path.name, (cron.group(1).strip() if cron else "")))
    return out


def _grade_ci_capacity() -> list[tuple[str, str, str]]:
    """Does the CI runner capacity we PAY for match the capacity GitHub can SEE?

    A self-hosted runner fails in a way no dashboard shows: the machine boots, the agent logs
    "Listening for Jobs", and GitHub simply does not have it registered. The machine looks
    healthy from the inside and is dark from the outside, so the only symptom is a queue.

    Measured 2026-08-19 10:50Z: `prospector-ci` had 3 machines `started` and 2 runners
    registered. Twelve runs were queued behind the two while the third idled. Restarting the
    machine re-registered it. Nothing compared those two numbers before this row existed.

    Grades what it got. No `flyctl`, no `gh`, no network -- WARN, never a false OK.
    """
    rows: list[tuple[str, str, str]] = []

    code, out = sh(["gh", "api", "repos/chidionyema/prospector/actions/runners",
                    "-q", '.runners[] | select(.status=="online") | .name'], timeout=45)
    if code != 0:
        return [(WARN, "ci runner capacity",
                 f"`gh api actions/runners` failed, so capacity is UNKNOWN: {out.strip()[:100]}")]
    online = {n.strip() for n in out.splitlines() if n.strip()}

    code, out = sh(["flyctl", "machines", "list", "-a", CI_FLY_APP, "--json"], timeout=60)
    if code != 0:
        rows.append((WARN, "ci runner capacity",
                     f"`flyctl machines list -a {CI_FLY_APP}` failed, so the Fly half of "
                     f"capacity is UNKNOWN: {out.strip()[:100]}"))
    else:
        try:
            machines = json.loads(out)
        except ValueError:
            machines = []
        started = [m for m in machines if (m.get("state") or "") == "started"]
        # The runner agent names itself `runner-<machine id>`, which is what makes the two
        # lists comparable at all.
        dark = [m for m in started
                if f"runner-{m.get('id')}" not in online]
        if dark:
            ids = ", ".join(str(m.get("id")) for m in dark)
            rows.append((BAD, "ci runner capacity",
                         f"{len(dark)} of {len(started)} {CI_FLY_APP} machine(s) are started but "
                         f"NOT registered as runners ({ids}). That capacity is paid for and "
                         f"dark; the machine logs 'Listening for Jobs' and never gets one. "
                         f"Fix: flyctl machine restart {dark[0].get('id')} -a {CI_FLY_APP}"))
        else:
            rows.append((OK, "ci runner capacity",
                         f"{len(started)} {CI_FLY_APP} machine(s) started, all registered"))

    # Queue depth is the symptom this row exists to explain, so report it next to the cause.
    code, out = sh(["gh", "run", "list", "--limit", "100", "--json", "status"], timeout=45)
    if code == 0:
        try:
            runs = json.loads(out)
        except ValueError:
            runs = []
        queued = sum(1 for r in runs if r.get("status") == "queued")
        # Two per online runner is a working queue; beyond that jobs wait longer than they run.
        limit = max(4, 2 * len(online))
        grade = BAD if queued > 2 * limit else (WARN if queued > limit else OK)
        rows.append((grade, "ci queue depth",
                     f"{queued} run(s) queued against {len(online)} online runner(s)"))
    return rows


def _grade_scheduled_workflows() -> list[tuple[str, str, str]]:
    """Is anything watching the watchers?

    A scheduled workflow is an enforcement that runs with nobody in the room. When it goes red
    the only signal is a red dot on a page nobody opens, so it stays red. Measured 2026-08-19:
    `e2e-live-smoke.yml` -- the check that a buyer can see a pack on the live site -- had failed
    every run since 2026-08-18 07:43, 26 hours earlier, with the first pack card 1,363px below
    the fold on a 844px phone and the search palette never opening (issue #384). Two more
    scheduled workflows had never run at all.

    Nothing in this estate looked at any of that. This row does, so a silent enforcement failure
    reaches the ops console instead of waiting for someone to browse the Actions tab.

    One `gh run list` call for the whole repo, not one per workflow, and it grades what it got:
    with no `gh`, no network or no auth the rows read WARN, never a false OK.
    """
    workflows = _scheduled_workflows()
    if not workflows:
        return []

    now = datetime.now(timezone.utc)
    rows: list[tuple[str, str, str]] = []
    for _name, filename, cron in workflows:
        label = f"workflow {filename.removesuffix('.yml')}"
        # Per workflow, not one shared `gh run list --limit 100`. A repo-wide list is cheaper
        # by two calls and wrong: measured 2026-08-19, e2e-live-smoke had failed 6 runs in a
        # row but only 1 of them was inside the newest 100 runs of a busy repo, so the shared
        # query reported a streak of 1. An undercounted streak is what makes a long-running
        # failure read as a blip.
        code, out = sh(["gh", "run", "list", "--workflow", filename, "--limit", "20",
                        "--json", "conclusion,status,createdAt"], timeout=45)
        if code != 0:
            rows.append((WARN, label,
                         f"scheduled `{cron}` but `gh run list` failed, so its health is "
                         f"UNKNOWN rather than fine: {out.strip()[:100]}"))
            continue
        try:
            runs = json.loads(out)
        except ValueError:
            rows.append((WARN, label, "`gh run list` returned no JSON"))
            continue
        mine = [r for r in runs if r.get("status") == "completed"]
        period = _cron_period_hours(cron)
        if not mine:
            # A workflow added yesterday that fires on Sundays has not failed to run; its slot
            # has not arrived. Grading that BAD is a false alarm, and a false alarm is how an
            # audit trains people to skim it. Measured 2026-08-19: both never-fired workflows
            # here were added inside 33 hours and are weekly.
            _, added = sh(["git", "log", "-1", "--format=%aI", "--diff-filter=A",
                           "--", f".github/workflows/{filename}"], timeout=30)
            age = None
            if added.strip():
                age = (now - datetime.fromisoformat(
                    added.strip())).total_seconds() / 3600
            if period and age is not None and age < period:
                rows.append((WARN, label,
                             f"never fired yet, and not yet due -- added {age:.0f}h ago and "
                             f"scheduled `{cron}` (~{period:.0f}h). `gh workflow run "
                             f"{filename} --ref main` proves it works without waiting."))
            else:
                rows.append((BAD, label,
                             f"scheduled `{cron}` and has NEVER completed a run, though its "
                             f"slot has passed. A drill that has never fired is a drill nobody "
                             f"has proven works."))
            continue

        newest = mine[0]
        age_h = (now - datetime.fromisoformat(
            newest["createdAt"].replace("Z", "+00:00"))).total_seconds() / 3600
        # A `skipped` run is not a green run -- the job never reported on the site at all --
        # so it must not break a red streak. Measured 2026-08-19: e2e-live-smoke had failed 7
        # runs in a row with one skip in the middle, and counting the skip as a break reported
        # the streak as 4 and the onset as six hours later than it was.
        streak = 0
        for r in mine:
            c = r.get("conclusion")
            if c == "failure":
                streak += 1
            elif c == "skipped":
                continue
            else:
                break

        if streak:
            reds = [r for r in mine if r.get("conclusion") == "failure"]
            first = reds[streak - 1]["createdAt"]
            red_h = (now - datetime.fromisoformat(
                first.replace("Z", "+00:00"))).total_seconds() / 3600
            rows.append((BAD, label,
                         f"RED for {streak} consecutive run(s), unbroken since "
                         f"{first[:16].replace('T', ' ')}Z -- {red_h:.0f}h. "
                         f"Nothing alerts on this; the audit is the alert."))
        elif period and age_h > period * _SCHEDULE_GRACE:
            rows.append((WARN, label,
                         f"last completed {age_h:.0f}h ago but scheduled `{cron}` "
                         f"(~{period:.0f}h). It may have stopped firing."))
        else:
            rows.append((OK, label,
                         f"last run {newest.get('conclusion')} {age_h:.0f}h ago, "
                         f"scheduled `{cron}`"))
    return rows


def _section(title: str, grader) -> tuple[str, list[tuple[str, str, str]]]:
    """Run one grader, and turn a crash into a FAIL ROW instead of a dead audit.

    The section list used to call all nine graders while building itself, so the first one to
    raise took the other eight with it and the process exited on a traceback. Measured
    2026-08-20: `_grade_doc_lint_baseline` raised `ValueError: min() iterable argument is
    empty` on an empty baseline, and the daily `com.prospector.process-audit` job had been
    printing that traceback instead of grading anything -- on this Mac and on origin/main.

    The reason that is worse than an ordinary bug: this script is what tells the estate its
    docs have drifted. A crash reports nothing, and reporting nothing looks exactly like
    reporting no problems. Both exit non-zero, so even the exit status could not tell them
    apart. A crashing grader is now the loudest row in its own section, and the other eight
    still run.
    """
    try:
        return (title, grader())
    except Exception as exc:  # noqa: BLE001 -- one broken grader must never silence the rest
        return (title, [(BAD, f"{title}: grader crashed",
                         f"{type(exc).__name__}: {exc} -- this section graded NOTHING, so treat "
                         "its silence as unknown rather than clean")])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true", help="print only problems")
    ap.add_argument("--json", action="store_true", help="machine-readable; what the ops console reads")
    ap.add_argument("--alert", action="store_true",
                    help="on failure, notify the operator through the estate's Telegram path")
    args = ap.parse_args()

    docs = documented_names()
    sections = [
        # Production first, and it is not this Mac. Everything below this line is estate support.
        _section("production (Fly)", grade_fly),
        _section("CI runners", grade_ci_runners),
        _section("deploys", grade_deploys),
        _section("launchd jobs on this Mac", lambda: grade_launchd(docs)),
        _section("GitHub workflows", lambda: grade_workflows(docs)),
        _section("enforcement", grade_enforcement),
        _section("specialist probes", grade_specialists),
        _section("worktree drift", grade_worktree_drift),
        _section("orphaned directories", orphaned_worktrees),
    ]

    if args.json:
        # One shape, so the ops console and the CLI can never disagree about what is failing.
        payload = {
            "generated_at": time.time(),
            "sections": [
                {"title": t, "rows": [{"grade": g, "name": n, "detail": d} for g, n, d in rows]}
                for t, rows in sections
            ],
            "litter": litter(),
            "failing": sum(1 for _, rows in sections for g, _, _ in rows if g == BAD),
            "warnings": sum(1 for _, rows in sections for g, _, _ in rows if g == WARN),
        }
        payload["ok"] = payload["failing"] == 0
        if args.alert and not payload["ok"]:
            payload["alert"] = alert(payload)
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    mark = {OK: "  ok  ", WARN: " warn ", BAD: " FAIL "}
    bad = warn = 0
    for title, rows in sections:
        shown = [r for r in rows if not args.quiet or r[0] != OK]
        print(f"\n=== {title} ({len(rows)}) ===")
        for grade, name, detail in shown:
            bad += grade == BAD
            warn += grade == WARN
            print(f"[{mark[grade]}] {name:<52} {detail}")
        if args.quiet and not shown:
            print("  nothing to report")

    junk = litter()
    if junk:
        print(f"\n=== stale files in ~/Library/LaunchAgents ({len(junk)}) ===")
        print("  " + ", ".join(junk))

    if not INVENTORY.exists():
        print(f"\nFAIL: {INVENTORY} does not exist, so nothing can be documented.")
        bad += 1

    if args.alert and bad:
        payload = {"failing": bad, "sections": [
            {"rows": [{"grade": g, "name": n, "detail": d} for g, n, d in rows]}
            for _t, rows in sections]}
        print(f"\n{alert(payload)}")

    print(f"\n{'FAIL' if bad else 'OK'}: {bad} failing/undocumented, {warn} warnings")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
