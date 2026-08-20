#!/usr/bin/env python3
"""Ship one service, from the ops console, without a terminal.

WHY THIS EXISTS. `scripts/deploy_status.py` answers "is the live stack running what is on main?".
When the answer was no, there was nothing to click: the /deploys page showed the gap and offered
no way to close it. Shipping meant `gh workflow run` or `flyctl deploy` typed by whoever had a
shell, which is the same single-human dependency deploy-engine.yml was written to remove.

WHAT IT SHIPS. The list of deployables is imported from `scripts/deploy_status.py`, never retyped,
so a component added there cannot be missing here without a test failing. Each one ships one of
four ways, and every deployable must be named by exactly one route or
`tests/unit/test_every_service_can_be_deployed_from_the_console.py` fails:

  workflow  dispatch its GitHub workflow on main. One commit, gated, rollbackable.
  script    run its deploy script on this host. Only for components with no workflow.
  button    already a console button somewhere else; this names which one.
  manual    deliberately not a button, with the reason. Today: the CI fleet, because
            `deploy/runners.sh up N` creates machines and spends money.

WHAT A DISPATCH ACTUALLY DEPLOYS. `--ref main`, so it ships whatever is on main at that moment,
including work merged by other people since the operator looked at the page. That is the same
thing the push trigger does; it is stated here because the button hides it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from deploy_status import DEPLOYABLES  # noqa: E402

#: How each component that has no workflow ships. Every DEPLOYABLE not covered by a workflow must
#: appear here, and the guard test fails when one does not.
ROUTES: dict[str, dict] = {
    "searxng": {
        "kind": "script",
        "cmd": ["bash", "deploy/searxng/deploy.sh"],
        # A local flyctl deploy builds the WORKING TREE, not a commit. On this host that tree is
        # a shared checkout several sessions write to, so shipping it unchecked would put another
        # session's half-finished edit into production. The preflight below refuses that.
        "clean_paths": ["deploy/searxng", "searxng"],
        "note": "builds from this checkout, so the shipping paths must be clean and on main",
    },
    "ci-runner": {
        "kind": "manual",
        "why": "ships with `deploy/runners.sh up <n>`, which CREATES Fly machines and spends "
               "money per machine. A button that provisions infrastructure on one click is a "
               "different decision from a button that redeploys code. The console can already "
               "START stopped runners (deploy_status.py --fix) and can see the fleet "
               "(ci_fleet_probe.py); standing new ones up stays a typed command",
    },
    "engine-standby": {
        "kind": "button",
        "where": "/tools -> \"Roll production forward to origin/main\" "
                 "(scripts/live_checkout.py --update)",
    },
}

#: Inputs we always force rather than inherit. `deploy now` means deploy; a workflow whose
#: dry_run default is later flipped to true would otherwise turn every button into a no-op that
#: reports success.
FORCED_INPUTS = {"dry_run": "false"}

_RUNNING = ("queued", "in_progress", "waiting", "requested", "pending")


# --------------------------------------------------------------------------- #
# Pure helpers - everything here is tested; everything below the next line shells out.
# --------------------------------------------------------------------------- #
def routes() -> dict[str, dict]:
    """Every deployable and the single route that ships it."""
    out: dict[str, dict] = {}
    for d in DEPLOYABLES:
        name = d["name"]
        if d.get("workflow"):
            out[name] = {"kind": "workflow", "workflow": d["workflow"], "what": d.get("what", "")}
        elif name in ROUTES:
            out[name] = dict(ROUTES[name], what=d.get("what", ""))
        else:
            out[name] = {"kind": "unrouted", "what": d.get("what", "")}
    return out


def dispatch_inputs(workflow_text: str) -> dict[str, str]:
    """The inputs to pass to `gh workflow run`, read from the workflow itself.

    Read rather than retyped for the same reason `deploy_status.workflow_paths` is read: an input
    added to the workflow must be answered here without anyone remembering to edit this file.

    Raises ValueError on an input with no default that we have no answer for, because guessing a
    deploy input is how a storefront gets shipped at the wrong target.
    """
    import yaml  # local: keeps `--list` working on a host with no pyyaml

    data = yaml.safe_load(workflow_text) or {}
    # PyYAML is YAML 1.1, where the bare key `on:` parses as the boolean True.
    trigger = data.get("on", data.get(True)) or {}
    if not isinstance(trigger, dict):
        return {}
    spec = (trigger.get("workflow_dispatch") or {}).get("inputs") or {}

    out: dict[str, str] = {}
    for name, meta in spec.items():
        meta = meta or {}
        if name in FORCED_INPUTS:
            out[name] = FORCED_INPUTS[name]
            continue
        if "default" in meta:
            out[name] = str(meta["default"])
            continue
        if meta.get("required"):
            raise ValueError(
                f"workflow input {name!r} is required and has no default; refusing to guess it"
            )
    return out


def dispatch_command(gh: str, workflow: str, inputs: dict[str, str], ref: str = "main") -> list[str]:
    cmd = [gh, "workflow", "run", workflow, "--ref", ref]
    for key, value in sorted(inputs.items()):
        cmd += ["-f", f"{key}={value}"]
    return cmd


def find_gh() -> str | None:
    """`gh` on PATH, or where Homebrew puts it.

    The console runs under launchd, whose PATH does not include /usr/local/bin, so a bare
    shutil.which finds nothing there and the button would fail with "gh: not found".
    """
    found = shutil.which("gh")
    if found:
        return found
    for candidate in ("/usr/local/bin/gh", "/opt/homebrew/bin/gh"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


# --------------------------------------------------------------------------- #
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=120, **kw)


def _in_flight(gh: str, workflow: str) -> list[dict]:
    p = _run([gh, "run", "list", "--workflow", workflow, "--limit", "5",
              "--json", "status,url,headBranch,createdAt"])
    if p.returncode != 0:
        return []
    try:
        runs = json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [r for r in runs if r.get("status") in _RUNNING]


def _newest_run_url(gh: str, workflow: str) -> str | None:
    p = _run([gh, "run", "list", "--workflow", workflow, "--limit", "1", "--json", "url"])
    if p.returncode != 0:
        return None
    try:
        runs = json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return runs[0]["url"] if runs else None


def _dirty(paths: list[str]) -> list[str]:
    p = _run(["git", "status", "--porcelain", "--"] + paths)
    if p.returncode != 0:
        return [f"git status failed: {p.stderr.strip()}"]
    return [line for line in p.stdout.splitlines() if line.strip()]


def print_routes() -> int:
    print("component        route     how it ships")
    print("-" * 78)
    bad = 0
    for name, r in routes().items():
        kind = r["kind"]
        if kind == "workflow":
            how = f"gh workflow run {r['workflow']} --ref main"
        elif kind == "script":
            how = " ".join(r["cmd"]) + f"   ({r['note']})"
        elif kind == "button":
            how = "already a button: " + r["where"]
        elif kind == "manual":
            how = "not a button - " + r["why"]
        else:
            how = "NO ROUTE - this service cannot be shipped from the console"
            bad += 1
        print(f"{name:<16} {kind:<9} {how}")
    return 2 if bad else 0


def deploy(name: str, check_only: bool) -> int:
    r = routes().get(name)
    if r is None:
        print(f"unknown component {name!r}. Known: {', '.join(routes())}", file=sys.stderr)
        return 2

    kind = r["kind"]
    if kind == "button":
        print(f"{name} is already deployable from the console: {r['where']}")
        return 2
    if kind == "manual":
        print(f"{name} is deliberately not a one-click deploy.\n  {r['why']}")
        return 2
    if kind == "unrouted":
        print(f"{name} has no route. Add one to ROUTES in {__file__}.", file=sys.stderr)
        return 2

    if kind == "script":
        dirty = _dirty(r["clean_paths"])
        if dirty:
            print(f"REFUSED: {name} builds from this checkout and these shipping paths are "
                  f"modified:\n  " + "\n  ".join(dirty) +
                  "\n\nA local build ships the working tree, so this would put uncommitted work "
                  "into production. Commit or stash first.", file=sys.stderr)
            return 2
        cmd = r["cmd"]
        print(f"$ {' '.join(cmd)}")
        if check_only:
            print("--check: nothing was deployed. Shipping paths are clean.")
            return 0
        p = subprocess.run(cmd, cwd=str(ROOT), timeout=1500)
        return p.returncode

    gh = find_gh()
    if gh is None:
        print(
            "REFUSED: no `gh` CLI on PATH, and none at /usr/local/bin/gh or /opt/homebrew/bin/gh.\n"
            "Measured 2026-08-19: the ops console that runs INSIDE the engine image has neither "
            "`gh` nor a GitHub token (deploy/engine/Dockerfile installs flyctl only, and "
            "`fly secrets list -a prospector-engine` names no GitHub credential), so a dispatch "
            "cannot come from there. Deploy from the laptop console, whose launchd job puts "
            "/usr/local/bin on PATH and whose gh is already authenticated. Closing that gap needs "
            "a GitHub token minted by the founder, which no agent may do.",
            file=sys.stderr)
        return 2

    auth = _run([gh, "auth", "status"])
    if auth.returncode != 0:
        print("REFUSED: `gh auth status` failed on this host, so a dispatch would be rejected.\n"
              "  " + (auth.stderr or auth.stdout).strip().splitlines()[0], file=sys.stderr)
        return 2

    workflow = r["workflow"]
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    try:
        inputs = dispatch_inputs(text)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    live = _in_flight(gh, workflow)
    if live:
        first = live[0]
        print(f"REFUSED: {workflow} already has a run {first['status']} on "
              f"{first.get('headBranch')}: {first.get('url')}\n"
              "Wait for it, or watch it on /deploys. Dispatching a second one now would queue "
              "behind it and deploy the same commit twice.", file=sys.stderr)
        return 2

    cmd = dispatch_command(gh, workflow, inputs)
    print(f"$ {' '.join(cmd)}")
    if check_only:
        print("--check: nothing was dispatched. gh is authenticated, no run is in flight, "
              f"inputs resolve to {inputs or '{}'}.")
        return 0

    before = _newest_run_url(gh, workflow)
    p = _run(cmd)
    if p.returncode != 0:
        print((p.stderr or p.stdout).strip(), file=sys.stderr)
        return p.returncode

    # `gh workflow run` prints no run id, so find the run it started. Bounded: a dispatch that
    # succeeded has already deployed whether or not we manage to name its URL.
    for _ in range(10):
        time.sleep(2)
        url = _newest_run_url(gh, workflow)
        if url and url != before:
            print(f"dispatched {workflow} on main -> {url}")
            return 0
    print(f"dispatched {workflow} on main. The run has not appeared in the API yet; "
          f"/deploys will show it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("component", nargs="?", help="what to deploy; omit to list every route")
    ap.add_argument("--list", action="store_true", help="show every service and how it ships")
    ap.add_argument("--check", action="store_true",
                    help="run every preflight and print the command, deploy nothing")
    args = ap.parse_args(argv)

    if args.list or not args.component:
        return print_routes()
    return deploy(args.component, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
