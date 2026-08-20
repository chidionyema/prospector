#!/usr/bin/env python3
"""Can CI actually run? Grade every self-hosted runner fleet against its repository.

WHY THIS EXISTS. On 2026-08-19, standing up the hermes-ci fleet, `deploy/runners.sh up 1`
reported success, `fly status` showed a machine, and GitHub showed ZERO runners. `fly scale
count` leaves the machines it keeps in whatever state they were in, and the machine `fly
deploy` had just made was stopped. Every job on that repository would have queued forever.
Seeing it took two commands in two different tools, run by hand, and comparing them by eye.
`deploy/runners.sh:180` now starts stopped machines after a scale, but nothing WATCHES the
pair, so the next way they drift apart is again invisible.

That is the shape of every failure this grades: the fleet and the repository each look fine on
their own screen, and only the pair tells the truth.

  MACHINES vs RUNNERS   a stopped or crashed machine is missing from GitHub's runner list, and
                        the Fly screen still says the fleet is the size you asked for
  CREDENTIAL MODE       a PAT expires and CI goes dark quietly. A registration token expires in
                        ONE HOUR: fine for a fixed fleet, fatal for `runners.sh autoscale`,
                        because a machine started later has nothing to register with
  QUEUE DEPTH           runners online and jobs queueing is capacity, not a fault, and the two
                        need different actions, so the report separates them

NO SECRET VALUE IS READ OR PRINTED. `fly secrets list` returns names and digests only, which is
all this needs: the question is "is a credential present, and which kind", never "what is it".

    .venv/bin/python scripts/ci_fleet_probe.py            # human report; exit 1 if degraded
    .venv/bin/python scripts/ci_fleet_probe.py --json     # for the ops console
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER_DIR = ROOT / "deploy" / "runner"
CAPACITY = ROOT / "ops" / "config" / "ci_capacity.yaml"


def capacity() -> tuple[int, int]:
    """The autoscale band, read from the file `deploy/runners.sh` reads.

    A second copy of these two numbers here would grade the fleet against a bound the scaler
    does not use, which is a probe that disagrees with production and is right about nothing.
    Same one-key shape as `_cfg_num` in that script, so the two cannot read the file
    differently.
    """
    lo, hi = 1, 3
    try:
        for line in CAPACITY.read_text().splitlines():
            key, _, val = line.partition(":")
            val = val.strip()
            if not val.isdigit():
                continue
            if key.strip() == "autoscale_min":
                lo = int(val)
            elif key.strip() == "autoscale_max":
                hi = int(val)
    except OSError:
        pass
    return lo, hi


def _cli(name: str) -> str | None:
    """Find a CLI that launchd cannot see.

    launchd hands a job PATH=/usr/bin:/bin:/usr/sbin:/sbin, so `fly` and `gh` — both in
    /opt/homebrew/bin, /usr/local/bin or ~/.fly/bin — are simply absent. A probe that reports
    "fly is not installed" on a box where fly works is worse than no probe: it turns a green
    fleet into a page at 3am. Memory: launchd-path-hides-local-bin-clis.
    """
    found = shutil.which(name)
    if found:
        return found
    for extra in ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".fly" / "bin")):
        candidate = Path(extra) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _run(cmd: list[str], timeout: int = 45) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


def _json_out(cmd: list[str], timeout: int = 45):
    """Run a command and parse its JSON, returning (value, error_message)."""
    rc, out = _run(cmd, timeout)
    if rc != 0:
        last = out.strip().splitlines()
        return None, (last[-1] if last else f"exit {rc}")
    # flyctl prints update notices ABOVE its JSON, so parse from the first bracket rather than
    # from byte zero. Without this every fly call fails on the day a new flyctl is released.
    starts = [i for i in (out.find("["), out.find("{")) if i >= 0]
    if not starts:
        return None, "no JSON in the output"
    try:
        return json.loads(out[min(starts) :]), None
    except json.JSONDecodeError as exc:
        return None, f"unparseable JSON: {exc}"


def discover_fleets() -> list[dict]:
    """Read the fleets out of deploy/runner/fly*.toml, never from a list in this file.

    A fleet added by writing a config and forgetting to edit a probe is a fleet nothing
    watches, which is exactly the blind spot this file exists to close. hermes-ci was added
    that way — one new config file, no other change (`deploy/runners.sh:169`).
    """
    fleets: dict[str, dict] = {}
    for cfg in sorted(RUNNER_DIR.glob("fly*.toml")):
        text = cfg.read_text()
        app = re.search(r'(?m)^\s*app\s*=\s*"([^"]+)"', text)
        repo = re.search(r'(?m)^\s*GITHUB_REPO\s*=\s*"([^"]+)"', text)
        if app and app.group(1) not in fleets:
            fleets[app.group(1)] = {
                "app": app.group(1),
                "repo": repo.group(1) if repo else None,
                "config": str(cfg.relative_to(ROOT)),
            }
    return list(fleets.values())


# The image stamp. `deploy/runners.sh up` passes RUNNER_IMAGE_SHA into every machine it
# creates, set to the commit that last touched deploy/runner/. Nothing else can answer "is the
# fleet running the image this repository describes?": Fly reports a deployment id and a layer
# digest, neither of which maps back to a commit, and the tools inside the image are only
# visible by opening an SSH session to a machine.
#
# THE FAILURE THIS GRADES. On 2026-08-19 the hermes-config gate died at exit 127 with no
# output, because the image had no openssh-client. The package was added to the Dockerfile the
# same hour. The fleet went on running the old image for as long as nobody thought to redeploy
# it, and every screen — Fly, GitHub, the machine list — said the fleet was healthy, because it
# was: it was healthily running the wrong image.
STAMP = "RUNNER_IMAGE_SHA"


def expected_image_sha() -> str | None:
    """The commit ``origin/main`` last changed the runner image at.

    Graded against ORIGIN/MAIN, never the local HEAD: this probe runs from a developer
    checkout that is routinely dozens of commits behind, and "the fleet matches my working
    tree" is not the question. It does not fetch — a probe that reaches the network to decide
    what to compare has two ways to be wrong instead of one.
    """
    code, out = _run(
        ["git", "-C", str(ROOT), "log", "-1", "--format=%H", "origin/main", "--", "deploy/runner"]
    )
    sha = out.strip()
    return sha if code == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def image_staleness(machines: list[dict], expected: str | None) -> str | None:
    """One problem line, or None when every machine carries the expected stamp.

    Unstamped machines are reported as stale rather than skipped. A machine with no stamp was
    built before `runners.sh` learned to write one, which means it is at least that old — the
    exact condition this exists to catch. Passing an unknown is how a staleness check quietly
    stops checking.
    """
    if expected is None or not machines:
        return None
    seen: dict[str, int] = {}
    for m in machines:
        env = (m.get("config") or {}).get("env") or {}
        seen[env.get(STAMP) or "unstamped"] = seen.get(env.get(STAMP) or "unstamped", 0) + 1
    wrong = {k: v for k, v in seen.items() if k != expected}
    if not wrong:
        return None
    detail = ", ".join(
        f"{n} machine(s) at {k[:12] if k != 'unstamped' else k}" for k, n in sorted(wrong.items())
    )
    return (
        f"the fleet is not running the image this repository describes: {detail}, but "
        f"deploy/runner/ on origin/main is at {expected[:12]}. A workflow step can then "
        f"fail as a bare exit 127 with no output. Rebuild: deploy/runners.sh up "
        f"(check `gh run list --status in_progress` first — that deploy kills in-flight "
        f"jobs)"
    )


def grade(fleet: dict, fly: str | None, gh: str | None, image_only: bool = False) -> dict:
    app, repo = fleet["app"], fleet["repo"]
    lo, hi = capacity()
    # A fleet is autoscaled only if it holds a PAT: `deploy/runners.sh autoscale` starts
    # machines minutes or hours after the credential was written, and a registration token is
    # dead in an hour. Everything graded against the autoscale band is gated on this.
    autoscaled = False
    out = dict(
        fleet,
        machines=[],
        started=0,
        stopped=0,
        floor=lo,
        ceiling=hi,
        runners_online=0,
        runners_offline=0,
        runners_busy=0,
        queued=0,
        credential=None,
        problems=[],
        notes=[],
    )

    if fly is None:
        out["problems"].append("flyctl is not on PATH, so the machines cannot be graded")
    else:
        machines, err = _json_out([fly, "machine", "list", "-a", app, "--json"])
        if machines is None:
            out["problems"].append(f"fly machine list failed: {err}")
        else:
            out["machines"] = [
                {"id": m.get("id"), "state": m.get("state"), "region": m.get("region")}
                for m in machines
            ]
            out["started"] = sum(1 for m in machines if m.get("state") == "started")
            out["stopped"] = len(machines) - out["started"]
            # A STOPPED MACHINE IS NOT A FAULT. `deploy/runners.sh autoscale` stops idle
            # machines on purpose: a stopped Fly machine bills no CPU and no RAM, and that is
            # the entire saving. The first version of this file graded each one as a problem
            # and reported eight faults for a fleet doing exactly what it was built to do.
            # The real fault is capacity sitting stopped WHILE work queues, which needs the
            # queue depth and so is graded further down.
            # ...and only on a fleet an autoscaler actually manages. hermes-ci is a
            # deliberate one-machine, token-only fleet with no scaler; grading it against
            # prospector-ci's band reported a fault for a fleet built that way on purpose.
            # `autoscaled` is decided below, from the credential, because a registration
            # token expires in an hour and so cannot serve a machine started later.
            if machines and autoscaled and out["started"] < lo:
                out["problems"].append(
                    f"{out['started']} machine(s) started, below the floor of {lo} in "
                    f"ops/config/ci_capacity.yaml. A cold pool makes the next job wait for a "
                    f"boot. PROSPECTOR_RUNNER_APP={app} deploy/runners.sh autoscale"
                )
            if not machines:
                out["problems"].append(
                    f"no machines at all — nothing can run a {repo or app} job. "
                    f"PROSPECTOR_RUNNER_APP={app} deploy/runners.sh up 1"
                )
            # AN UNKNOWN EXPECTATION IS A PROBLEM, NOT A PASS. image_staleness() returns
            # None both when every machine is current and when there is nothing to compare
            # against, and those two must not look the same to an operator. `origin/main`
            # fails to resolve on a shallow clone — which is the default `actions/checkout`
            # gives you — so a scheduled run would have graded nothing and gone green. The
            # same reasoning as unstamped machines, one level up.
            expected = expected_image_sha()
            if expected is None:
                out["problems"].append(
                    "cannot tell whether the fleet is current: `git log origin/main -- "
                    "deploy/runner` resolved nothing, so there is no image commit to compare "
                    "against. In CI that means a shallow checkout — use fetch-depth: 0 and "
                    "fetch origin main. This is reported rather than skipped because a "
                    "staleness check that accepts an unknown has stopped checking."
                )
            else:
                stale = image_staleness(machines, expected)
                if stale:
                    out["problems"].append(stale)

        # NAMES AND DIGESTS ONLY. There is no code path in this file that can read a value.
        secrets, err = _json_out([fly, "secrets", "list", "-a", app, "--json"])
        if secrets is None:
            out["notes"].append(f"could not list secret NAMES: {err}")
        else:
            names = {s.get("Name") or s.get("name") for s in secrets}
            if "GITHUB_RUNNER_PAT" in names:
                out["credential"] = "pat"
                autoscaled = True
            elif "RUNNER_TOKEN" in names:
                out["credential"] = "registration-token"
                out["notes"].append(
                    "token-only fleet. It holds nothing that can add or remove a runner, which "
                    "is the narrower and safer mode — but a registration token expires in an "
                    "HOUR, so a machine started later cannot register. Do not point "
                    "`runners.sh autoscale` at this fleet without moving it to a PAT."
                )
            elif names:
                out["problems"].append(
                    "no runner credential on the app, so a machine can never register. "
                    f"PROSPECTOR_RUNNER_APP={app} deploy/runners.sh up 1 mints one."
                )

    # THE HALF THAT NEEDS NO GITHUB CREDENTIAL.
    # Reading a repository's self-hosted runners needs the `administration` permission, which
    # GITHUB_TOKEN cannot be granted at all — only a personal access token can. So a scheduled
    # job that asks the whole question is red every day for a credential reason, and a check
    # that cries wolf daily is a check the operator stops reading. `--image-only` grades what
    # FLY_API_TOKEN alone can answer: is the fleet running the image this repository describes.
    # The rest stays a console button until a scoped PAT exists as a repository secret.
    if image_only:
        return out

    if gh is None:
        out["problems"].append("gh is not on PATH, so the repository's runners cannot be read")
        return out
    if repo is None:
        out["problems"].append(
            f"{fleet['config']} names no GITHUB_REPO, so this fleet registers with nothing"
        )
        return out

    runners, err = _json_out([gh, "api", f"repos/{repo}/actions/runners", "--jq", ".runners"])
    if runners is None:
        out["problems"].append(f"could not read {repo}'s runners: {err}")
    else:
        runners = runners or []
        online = [r for r in runners if r.get("status") == "online"]
        out["runners_online"] = len(online)
        out["runners_offline"] = len(runners) - len(online)
        # BUSY ONLY AMONG THE ONLINE. An offline runner keeps whatever `busy` it carried when
        # it went away, so counting across the whole list read 6 busy against 4 online, and
        # the "every runner is busy" branch below then fired on arithmetic that cannot be
        # true.
        out["runners_busy"] = sum(1 for r in online if r.get("busy"))
        if out["started"] and out["runners_online"] < out["started"]:
            out["problems"].append(
                f"{out['started']} machine(s) started but {out['runners_online']} runner(s) "
                f"online at {repo}. Registration failed — usually an expired credential. "
                f"fly logs -a {app} says which."
            )

    counted, err = _json_out(
        [
            gh,
            "api",
            f"repos/{repo}/actions/runs?status=queued&per_page=1",
            "--jq",
            "{n: .total_count}",
        ]
    )
    if counted is not None:
        out["queued"] = counted.get("n", 0)
        if (
            out["queued"]
            and out["runners_online"]
            and not out["stopped"]
            and out["runners_busy"] >= out["runners_online"]
        ):
            # Only when there is nothing left to start. While stopped machines remain, the
            # answer is to start them, and saying "buy more" alongside that is advice that
            # contradicts the fault printed two lines above it.
            out["notes"].append(
                f"{out['queued']} run(s) queued, every runner busy and every machine already "
                f"started. That is capacity, not a fault. "
                f"PROSPECTOR_RUNNER_APP={app} deploy/runners.sh up {out['started'] + 1}"
            )
        elif out["queued"] and not out["runners_online"]:
            out["problems"].append(
                f"{out['queued']} run(s) queued and NO runner online at {repo} — CI is stopped, "
                f"not slow."
            )
        # THE AUTOSCALE FAULT, stated as the pair rather than as either half. Stopped machines
        # are fine. Stopped machines while work waits, with the ceiling not reached, means the
        # scaler did not react. Measured 2026-08-19: 5 queued, 4 started, 8 stopped, ceiling
        # 12 — and every run of ci-autoscale.yml had failed since the day it shipped.
        if autoscaled and out["queued"] and out["stopped"] and out["started"] < hi:
            out["problems"].append(
                f"{out['queued']} run(s) queued with {out['stopped']} machine(s) stopped and "
                f"the ceiling at {hi} — the scaler did not react. "
                f"gh run list -R {repo} --workflow ci-autoscale.yml -L 3"
            )

    # THE SCALER'S OWN HEALTH. This is the check that was missing on 2026-08-19, when the
    # autoscale workflow failed five times out of five and nothing said so. A workflow GitHub
    # rejects at parse time starts no job, so it writes no log and annotates no check suite:
    # the conclusion of its newest run is the only evidence that exists.
    scaler, _err = (
        (None, None)
        if not autoscaled
        else _json_out(
            [
                gh,
                "api",
                f"repos/{repo}/actions/workflows/ci-autoscale.yml/runs?per_page=1",
                "--jq",
                "{c: .workflow_runs[0].conclusion, n: .workflow_runs[0].run_number}",
            ]
        )
    )
    if scaler and scaler.get("c") not in (None, "success", "cancelled", "skipped"):
        out["problems"].append(
            f"the CI autoscale workflow's newest run (#{scaler.get('n')}) is {scaler['c']}, so "
            f"nothing is sizing this pool. "
            f"gh run list -R {repo} --workflow ci-autoscale.yml -L 5"
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Grade the self-hosted CI runner fleets.")
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    ap.add_argument(
        "--image-only",
        action="store_true",
        help="grade only whether each fleet runs the image this repository describes; "
        "needs flyctl and no GitHub credential, so a scheduled job can ask it",
    )
    args = ap.parse_args()

    fly, gh = (_cli("fly") or _cli("flyctl")), _cli("gh")
    fleets = discover_fleets()
    graded = [grade(f, fly, gh, image_only=args.image_only) for f in fleets]
    degraded = [g for g in graded if g["problems"]]

    if args.json:
        print(json.dumps({"ok": not degraded and bool(graded), "fleets": graded}, indent=2))
        return 1 if degraded or not graded else 0

    if not fleets:
        print(
            f"FAIL  no runner fleets found in {RUNNER_DIR.relative_to(ROOT)}/ — either the "
            f"fleet configs moved or this checkout is stale"
        )
        return 1

    for g in graded:
        print(
            f"{'FAIL' if g['problems'] else 'PASS'}  {g['app']:<14} "
            f"{g['repo'] or '(no repo)':<26} "
            f"machines {g['started']}/{len(g['machines'])} started · "
            f"runners {g['runners_online']} online ({g['runners_busy']} busy) · "
            f"queued {g['queued']} · credential {g['credential'] or 'none'}"
        )
        for p in g["problems"]:
            print(f"        x {p}")
        for n in g["notes"]:
            print(f"        · {n}")
    print()
    print(
        f"CI FLEET: {'DEGRADED' if degraded else 'OPERATIONAL'} "
        f"({len(graded) - len(degraded)}/{len(graded)} fleets healthy)"
    )
    return 1 if degraded else 0


if __name__ == "__main__":
    sys.exit(main())
