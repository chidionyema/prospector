#!/usr/bin/env python3
"""When did each deployable last ship, and is anything stuck on the way out?

    python3 scripts/deploy_status.py            # the table
    python3 scripts/deploy_status.py --json     # what the ops console reads
    python3 scripts/deploy_status.py --fix      # start stopped CI runners when work is queued

WHY THIS EXISTS
---------------
On 2026-08-19 a merge to `main` sat undeployed for twelve hours. Every check a session could
run was green: the PR merged, the local suite passed 97/97, `gh run list` showed the deploy
run existed. The site served the old build the whole time, because the deploy run was QUEUED
behind a runner fleet that had a stopped machine in it. Nothing in the estate compared "what
is on main" with "what the live app is running", so nobody could see it.

That is the blind spot this file closes. It answers one question per deployable:

    the commit that last DEPLOYED, versus the commits on origin/main since it

and it names the state as one of:

    LIVE      everything on main that touches this component has deployed
    SHIPPING  a deploy is running now
    STALLED   commits are waiting and either nothing is running, or a run has been
              queued longer than --stall-after
    FAILED    the newest deploy run for this component failed
    DRIFTED   the component has no deploy workflow, so a human must ship it, and the
              repo has moved since the release that is live
    UNKNOWN   the probe could not measure it

UNKNOWN IS NEVER A PASS. A missing `gh`, an unauthenticated `flyctl`, a workflow whose
trigger paths could not be parsed: each of those returns UNKNOWN and exit 2. The failure
this file exists to catch was a check that had nothing to say and read as silence.

The trigger paths are READ OUT of each workflow file, never retyped here. Adding a path to
`deploy-web.yml` is what makes this probe watch it; there is no second list to forget.

EXIT CODES
    0  every deployable is LIVE or SHIPPING
    1  something is STALLED, FAILED or DRIFTED
    2  something could not be measured
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"

#: The daemons on this box run from their own checkout, pinned to origin/main. `live_checkout.py`
#: owns that path; reading it from there means the two can never point at different directories.
try:  # pragma: no cover - exercised by the CLI, not the unit tests
    sys.path.insert(0, str(ROOT / "scripts"))
    from live_checkout import LIVE as LIVE_CHECKOUT  # type: ignore
except Exception:  # noqa: BLE001 - a probe never dies because an import moved
    LIVE_CHECKOUT = None

#: Everything on the stack that can be deployed, and how each one ships.
#:
#: `workflow` is a filename in .github/workflows, and the trigger paths come out of it. A
#: component with no workflow is deployed by hand: it gets compared by TIME against its Fly
#: release, because there is no run whose head commit could answer it.
DEPLOYABLES: list[dict] = [
    {
        "name": "store-web",
        "what": "the storefront at mumchimp.com",
        "app": "prospector-store-web",
        "workflow": "deploy-web.yml",
        "url": "https://mumchimp.com",
    },
    {
        "name": "store-api",
        "what": "the shop API, checkout and fulfilment",
        "app": "prospector-store-api",
        "workflow": "deploy-api.yml",
    },
    {
        "name": "engine",
        "what": "the vetting engine on Fly",
        "app": "prospector-engine",
        "workflow": "deploy-engine.yml",
    },
    {
        "name": "ci-runner",
        "what": "the CI runner fleet every deploy waits on",
        "app": "prospector-ci",
        "workflow": None,
        "paths": ["deploy/runner/**"],
    },
    {
        "name": "searxng",
        "what": "the self-hosted search endpoint",
        "app": "prospector-searxng",
        "workflow": None,
        "paths": ["deploy/searxng/**"],
    },
    {
        "name": "engine-local",
        "what": "the daemons on this box, from prospector-live",
        "app": None,
        "workflow": None,
        "checkout": True,
        "paths": ["prospector/**", "scripts/**", "config.yaml"],
    },
]

#: The CI app whose machines every deploy queues behind. `--fix` starts these.
CI_APP = "prospector-ci"

RUNNING = ("queued", "in_progress", "waiting", "requested", "pending")


# --------------------------------------------------------------------------- #
# Pure helpers. Everything below the line shells out; everything above is tested.
# --------------------------------------------------------------------------- #
_PATHS_KEY = re.compile(r"^(\s*)paths:\s*$")
_LIST_ITEM = re.compile(r'^\s+-\s+"?([^"#\s]+)"?\s*$')


def workflow_paths(text: str) -> list[str]:
    """The `paths:` filters a workflow triggers on.

    Read rather than retyped on purpose: a path added to the workflow must start being watched
    here without anyone remembering to edit this file. Returns [] when there is no paths block,
    and [] is treated as UNKNOWN by the caller, never as "nothing to watch".
    """
    out: list[str] = []
    grabbing = False
    for line in text.splitlines():
        if _PATHS_KEY.match(line):
            grabbing = True
            continue
        if not grabbing:
            continue
        hit = _LIST_ITEM.match(line)
        if hit:
            out.append(hit.group(1))
            continue
        if line.strip() and not line.lstrip().startswith("#"):
            grabbing = False
    return out


def pathspecs(paths: list[str]) -> list[str]:
    """Workflow path filters as git pathspecs.

    `a/b/**` and `a/b/*` both mean "anything under a/b" to Actions; to `git log` the directory
    itself says the same thing and cannot be read as a literal filename.
    """
    out = []
    for p in paths:
        p = p.rstrip("/")
        while p.endswith("/**") or p.endswith("/*"):
            p = p.rsplit("/", 1)[0]
        if p and p not in out:
            out.append(p)
    return out


def age_s(iso: str | None, now: datetime | None = None) -> float | None:
    """Seconds since an ISO-8601 instant, or None if it cannot be read."""
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - when).total_seconds()


def verdict(f: dict, *, stall_after_s: float) -> tuple[str, str]:
    """The state of one deployable, from facts only. No I/O, so a test can drive every branch.

    Order matters. A component that cannot be measured is never reported as healthy, and a
    failed run outranks a queue: a red deploy with three commits behind it is not "shipping".
    """
    if f.get("unknown_reason"):
        return "UNKNOWN", f["unknown_reason"]
    pending = len(f.get("pending_commits") or [])
    running = f.get("running") or []
    if f.get("last_run_failed"):
        return "FAILED", f"the last deploy run failed ({f.get('last_run_url') or 'no url'})"
    if running:
        # The OLDEST run decides, and its own status is the one quoted. Reading the age off one
        # run and the status off another is how a report says "queued 2 min" about a run that
        # has been queued an hour.
        oldest = max(running, key=lambda r: r.get("age_s") or 0)
        waited = oldest.get("age_s") or 0
        if waited > stall_after_s:
            return "STALLED", (
                f"a deploy has been {oldest.get('status')} for "
                f"{int(waited // 60)} min - check the runners"
            )
        return "SHIPPING", f"a deploy is {oldest.get('status')}"
    if pending == 0:
        return "LIVE", "everything on main that touches it has deployed"
    if not f.get("has_workflow"):
        return "DRIFTED", f"{pending} commit(s) since the live release, and it deploys by hand"
    return "STALLED", f"{pending} commit(s) on main have not deployed and nothing is running"


ATTENTION = ("STALLED", "FAILED", "DRIFTED", "UNKNOWN")


# --------------------------------------------------------------------------- #
# The shell-out layer
# --------------------------------------------------------------------------- #
def sh(*args: str, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    """Run a command, hand back (rc, output). Never raises: a missing tool is a finding, not
    a crash that takes the whole table down with it."""
    try:
        p = subprocess.run(
            list(args), cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"{args[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(args)}: timed out after {timeout}s"


def gh_json(*args: str, timeout: int = 60):
    rc, out = sh("gh", *args, timeout=timeout)
    if rc != 0:
        return None, out.strip()[-300:]
    try:
        return json.loads(out or "null"), None
    except json.JSONDecodeError as exc:
        return None, f"gh returned non-JSON: {exc}"


def fly_releases(app: str, timeout: int = 90):
    rc, out = sh("flyctl", "releases", "-a", app, "--json", timeout=timeout)
    if rc != 0:
        return None, out.strip()[-300:]
    try:
        rows = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        return None, f"flyctl returned non-JSON: {exc}"
    done = [r for r in rows if str(r.get("Status", "")).lower() == "complete"]
    return (done[0] if done else (rows[0] if rows else None)), None


def commits_since(rev: str, specs: list[str], *, since_iso: str | None = None) -> list[dict]:
    """Commits on origin/main after `rev` (or after an instant) that touch these paths."""
    args = ["git", "log", "--no-merges", "--format=%H%x1f%cI%x1f%s"]
    if since_iso:
        args += [f"--since={since_iso}", "origin/main"]
    else:
        args += [f"{rev}..origin/main"]
    if specs:
        args += ["--"] + specs
    rc, out = sh(*args)
    if rc != 0:
        return []
    rows = []
    for line in out.strip().splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            rows.append({"sha": parts[0][:8], "at": parts[1], "subject": parts[2]})
    return rows


def measure(d: dict, *, now: datetime) -> dict:
    """Everything known about one deployable."""
    f: dict = {
        "name": d["name"],
        "what": d["what"],
        "app": d.get("app"),
        "url": d.get("url"),
        "workflow": d.get("workflow"),
        "has_workflow": bool(d.get("workflow")),
        "running": [],
        "pending_commits": [],
        "unknown_reason": None,
    }

    # --- what it triggers on -------------------------------------------------
    if d.get("workflow"):
        wf = WORKFLOWS / d["workflow"]
        if not wf.exists():
            f["unknown_reason"] = (
                f"{wf.relative_to(ROOT)} is gone — this table names a workflow that does not exist"
            )
            return f
        paths = workflow_paths(wf.read_text())
        if not paths:
            f["unknown_reason"] = f"no `paths:` filter parsed out of {d['workflow']}"
            return f
    else:
        paths = list(d.get("paths") or [])
    f["paths"] = paths
    specs = pathspecs(paths)

    # --- the commit that is live --------------------------------------------
    if d.get("checkout"):
        live = LIVE_CHECKOUT
        if live is None or not Path(live).exists():
            f["unknown_reason"] = "the live checkout path could not be read from live_checkout.py"
            return f
        rc, out = sh("git", "-C", str(live), "rev-parse", "HEAD")
        if rc != 0:
            f["unknown_reason"] = f"cannot read HEAD of {live}: {out.strip()[:160]}"
            return f
        f["deployed_sha"] = out.strip()[:8]
        rc, out = sh("git", "-C", str(live), "log", "-1", "--format=%cI", "HEAD")
        f["deployed_at"] = out.strip() if rc == 0 else None
        f["deployed_how"] = "the checkout HEAD the daemons run from"
        f["pending_commits"] = commits_since(f["deployed_sha"], specs)
    elif d.get("workflow"):
        runs, err = gh_json(
            "run",
            "list",
            "--workflow",
            d["workflow"],
            "--branch",
            "main",
            "--limit",
            "25",
            "--json",
            "databaseId,headSha,status,conclusion,createdAt,updatedAt,url",
        )
        if runs is None:
            f["unknown_reason"] = f"gh could not list runs of {d['workflow']}: {err}"
            return f
        f["running"] = [
            {
                "status": r["status"],
                "url": r["url"],
                "sha": r["headSha"][:8],
                "age_s": age_s(r.get("createdAt"), now),
            }
            for r in runs
            if r.get("status") in RUNNING
        ]
        done = [r for r in runs if r.get("status") == "completed"]
        ok = [r for r in done if r.get("conclusion") == "success"]
        if done and not f["running"] and done[0].get("conclusion") not in ("success", "skipped"):
            f["last_run_failed"] = True
            f["last_run_url"] = done[0].get("url")
        if not ok:
            f["unknown_reason"] = f"no successful {d['workflow']} run on main to compare against"
            return f
        f["deployed_sha"] = ok[0]["headSha"][:8]
        f["deployed_at"] = ok[0].get("updatedAt")
        f["deployed_how"] = f"{d['workflow']} run {ok[0]['databaseId']}"
        f["deployed_run_url"] = ok[0].get("url")
        f["pending_commits"] = commits_since(f["deployed_sha"], specs)
    # else: no workflow and not a checkout -> compared by time, below

    # --- what Fly says is actually running -----------------------------------
    if d.get("app"):
        rel, err = fly_releases(d["app"])
        if rel is None:
            f["fly_error"] = err or "no releases"
        else:
            f["fly_version"] = rel.get("Version")
            f["fly_at"] = rel.get("CreatedAt")
            f["fly_status"] = rel.get("Status")
            f["fly_age_s"] = age_s(rel.get("CreatedAt"), now)
        if not d.get("workflow") and not d.get("checkout"):
            if rel is None:
                f["unknown_reason"] = f"flyctl could not read releases for {d['app']}: {err}"
                return f
            f["deployed_at"] = rel.get("CreatedAt")
            f["deployed_how"] = f"Fly release v{rel.get('Version')}, deployed by hand"
            f["pending_commits"] = commits_since("", specs, since_iso=rel.get("CreatedAt"))

    f["deploy_age_s"] = age_s(f.get("deployed_at"), now)
    return f


def runner_fleet(now: datetime) -> dict:
    """The CI machines, and how much work is waiting on them.

    A deploy cannot start without a runner, so a stopped machine is invisible in every
    GitHub-side view: the run just says `queued`. This is the half of the picture that was
    missing on 2026-08-19.
    """
    out: dict = {"app": CI_APP, "machines": [], "queued": [], "error": None}
    rc, raw = sh("flyctl", "machines", "list", "-a", CI_APP, "--json", timeout=90)
    if rc != 0:
        out["error"] = raw.strip()[-300:]
    else:
        try:
            out["machines"] = [
                {"id": m.get("id"), "state": m.get("state"), "region": m.get("region")}
                for m in json.loads(raw or "[]")
            ]
        except json.JSONDecodeError as exc:
            out["error"] = f"flyctl returned non-JSON: {exc}"
    runs, err = gh_json(
        "run", "list", "--limit", "40", "--json", "status,workflowName,createdAt,url"
    )
    if runs is None:
        out["queue_error"] = err
    else:
        out["queued"] = [
            {
                "workflow": r["workflowName"],
                "url": r["url"],
                "age_s": age_s(r.get("createdAt"), now),
            }
            for r in runs
            if r.get("status") in RUNNING
        ]
    out["stopped"] = [m for m in out["machines"] if m["state"] != "started"]
    out["oldest_queued_s"] = max((q["age_s"] or 0) for q in out["queued"]) if out["queued"] else 0
    return out


def start_stopped(fleet: dict) -> list[str]:
    """Start every stopped CI machine. Only called with --fix, and only when work is queued:
    starting idle machines costs money for nothing."""
    done = []
    for m in fleet.get("stopped") or []:
        rc, out = sh("flyctl", "machine", "start", m["id"], "-a", CI_APP, timeout=120)
        done.append(f"{m['id']}: {'started' if rc == 0 else out.strip()[-120:]}")
    return done


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def human(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def render(report: dict) -> str:
    lines = [f"DEPLOY STATUS  {report['at']}", ""]
    lines.append(f"{'component':<14}{'state':<10}{'last deployed':<16}{'commit':<10}why")
    lines.append("-" * 100)
    for r in report["deployables"]:
        lines.append(
            f"{r['name']:<14}{r['state']:<10}{human(r.get('deploy_age_s')):<16}"
            f"{(r.get('deployed_sha') or '-'):<10}{r['why']}"
        )
    fleet = report["runners"]
    lines += [
        "",
        f"CI runners ({fleet['app']}): "
        + (
            ", ".join(f"{m['id'][:8]} {m['state']}" for m in fleet["machines"])
            or fleet.get("error")
            or "none"
        ),
        f"queued now: {len(fleet['queued'])}"
        + (f", oldest {int(fleet['oldest_queued_s'] // 60)}m" if fleet["queued"] else ""),
    ]
    if fleet.get("problem"):
        lines.append(f"PROBLEM: {fleet['problem']}")
    for line in report.get("fixed", []):
        lines.append(f"FIXED: {line}")
    lines += ["", report["headline"]]
    return "\n".join(lines)


def build(*, stall_after_s: float, fix: bool) -> dict:
    now = datetime.now(timezone.utc)
    sh("git", "fetch", "-q", "origin", "main", timeout=120)
    rows = []
    for d in DEPLOYABLES:
        f = measure(d, now=now)
        state, why = verdict(f, stall_after_s=stall_after_s)
        f["state"], f["why"] = state, why
        rows.append(f)
    fleet = runner_fleet(now)
    if fleet["queued"] and fleet["stopped"]:
        fleet["problem"] = (
            f"{len(fleet['queued'])} run(s) queued while "
            f"{len(fleet['stopped'])} CI machine(s) are stopped"
        )
    elif fleet.get("error"):
        fleet["problem"] = f"cannot read the CI machines: {fleet['error']}"
    report = {"at": now.isoformat(timespec="seconds"), "deployables": rows, "runners": fleet}
    if fix and fleet["queued"] and fleet["stopped"]:
        report["fixed"] = start_stopped(fleet)
    bad = [r for r in rows if r["state"] in ("STALLED", "FAILED", "DRIFTED")]
    unknown = [r for r in rows if r["state"] == "UNKNOWN"]
    if bad:
        report["headline"] = "NEEDS ATTENTION: " + "; ".join(
            f"{r['name']} {r['state']} — {r['why']}" for r in bad
        )
        report["exit"] = 1
    elif unknown or fleet.get("problem"):
        report["headline"] = "CANNOT SAY: " + "; ".join(
            [f"{r['name']} — {r['why']}" for r in unknown]
            + ([fleet["problem"]] if fleet.get("problem") else [])
        )
        report["exit"] = 2
    else:
        report["headline"] = "OK: every deployable is running what is on main."
        report["exit"] = 0
    report["needs_attention"] = len(bad) + len(unknown) + (1 if fleet.get("problem") else 0)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    ap.add_argument(
        "--fix",
        action="store_true",
        help="start stopped CI runners when runs are queued behind them",
    )
    ap.add_argument(
        "--stall-after-min",
        type=float,
        default=10.0,
        help="a deploy queued longer than this is STALLED (default 10)",
    )
    args = ap.parse_args()
    report = build(stall_after_s=args.stall_after_min * 60, fix=args.fix)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return int(report["exit"])


if __name__ == "__main__":
    raise SystemExit(main())
