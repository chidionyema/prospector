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
import json
import plistlib
import re
import subprocess
import sys
import time
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

        if failed:
            rows.append((BAD, label, f"FAILING exit {status} -- {detail}"))
        elif label in installed and label not in loaded:
            # The worst state in the estate, and the one that was invisible until 2026-08-19: the
            # plist is tracked in the repo, the plist is on disk, and launchd is simply not running
            # it. Nothing else looks for this. A grader that walks only LOADED jobs cannot see a job
            # that is absent, and a job that never runs never fails, so it appears nowhere at all.
            # Measured that day: com.prospector.scheduler, .consumer, .watchdog and .ops-console
            # were all installed and none was loaded, while the audit reported 15 other problems.
            rows.append((BAD, label, f"NOT LOADED, launchd is not running it -- {detail}"))
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
    """One (grade, filename, detail) row per GitHub workflow."""
    code, out = sh(
        ["gh", "run", "list", "--limit", "200", "--json",
         "workflowName,conclusion,status,createdAt,event"], timeout=90)
    runs: list[dict] = []
    gh_error = None
    if code != 0:
        gh_error = (out.strip().splitlines() or ["gh failed"])[0]
    else:
        try:
            runs = json.loads(out)
        except ValueError as exc:
            gh_error = str(exc)

    newest: dict[str, dict] = {}
    for run in runs:
        name = run.get("workflowName", "")
        if name not in newest or run.get("createdAt", "") > newest[name].get("createdAt", ""):
            newest[name] = run

    rows: list[tuple[str, str, str]] = []
    for f in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^name:\s*(.+)$", text, re.M)
        name = m.group(1).strip().strip("\"'") if m else f.stem
        run = newest.get(name)
        if gh_error:
            rows.append((WARN, f.name, f"could not ask GitHub ({gh_error})"))
            continue
        if run is None:
            # A workflow that never ran leaves no red run anywhere. This is the only place it shows.
            rows.append((BAD, f.name, f"NEVER-RAN -- no run of '{name}' in the last 200"))
            continue
        concl = run.get("conclusion") or run.get("status") or "?"
        detail = f"last {concl} ({run.get('event')}) {run.get('createdAt', '')[:16]}"
        if concl in ("failure", "timed_out", "startup_failure"):
            rows.append((BAD, f.name, f"FAILING -- {detail}"))
        elif f.name not in docs:
            rows.append((BAD, f.name, f"UNDOCUMENTED, absent from {INVENTORY.name} -- {detail}"))
        else:
            rows.append((OK, f.name, detail))
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

    # The doc-lint ratchet only ratchets while its baseline is committed.
    baseline = ROOT / "docs" / "doc_lint_baseline.json"
    rows.append((OK if baseline.exists() else BAD, "doc lint baseline",
                 "present" if baseline.exists() else "MISSING, so the ratchet cannot tighten"))
    return rows



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


def alert(payload: dict) -> str:
    """Send one Telegram line through the estate's existing operator alert path.

    Deliberately not a new channel. `~/.hermes/scripts/estate_alert.py` is already the estate's
    one door -- it holds the credentials, it debounces, and it is written never to raise at the
    caller. A second notifier would mean a second thing to keep working.
    """
    sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))
    try:
        import estate_alert
    except ImportError as exc:
        return f"could not alert: {exc}"
    lines = [f"{n}: {d}" for sec in payload["sections"] for g, n, d in
             ((r["grade"], r["name"], r["detail"]) for r in sec["rows"]) if g == BAD]
    if not lines:
        return "nothing to alert"
    text = (f"process audit: {payload['failing']} failing\n" + "\n".join(lines[:12]))
    sent = estate_alert.send_operator_alert(
        text, debounce_key="process-audit", debounce_s=3600)
    return "alert sent" if sent else "alert suppressed (debounce or no credentials)"


def litter() -> list[str]:
    """Non-plist files loitering in ~/Library/LaunchAgents.

    launchd ignores them, so they are not jobs. They are stale copies that make the directory
    unreadable, and each one is a plist somebody meant to keep "just in case".
    """
    return sorted(
        p.name for p in AGENTS_DIR.glob("*")
        if p.is_file() and p.suffix != ".plist" and not p.name.startswith("."))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true", help="print only problems")
    ap.add_argument("--json", action="store_true", help="machine-readable; what the ops console reads")
    ap.add_argument("--alert", action="store_true",
                    help="on failure, notify the operator through the estate's Telegram path")
    args = ap.parse_args()

    docs = documented_names()
    sections = [
        ("launchd jobs", grade_launchd(docs)),
        ("GitHub workflows", grade_workflows(docs)),
        ("enforcement", grade_enforcement()),
        ("specialist probes", grade_specialists()),
        ("orphaned directories", orphaned_worktrees()),
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
