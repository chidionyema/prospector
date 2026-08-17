#!/usr/bin/env python3
"""Run a CI job's shell steps locally, in order, with the same environment.

WHY THIS EXISTS (2026-08-16)

On 2026-08-16 a CI failure took three push-and-wait cycles to fix. Each cycle was a
push, a ~10 minute wait, and a log read. The whole diagnosis was reading job logs
after the fact, because there was no way to run a job's steps on this machine.

This script closes that loop for the steps we WROTE. It reads .github/workflows/ci.yml
and executes each `run:` step of a chosen job in order, with the workflow's `env:`, the
job's `defaults.run.working-directory`, each step's own `env:`, and a working
GITHUB_ENV / GITHUB_PATH / RUNNER_TEMP, so a step that exports a variable is seen by the
steps after it exactly as it is on the runner.

WHAT IT DOES NOT DO, and this matters:

`uses:` steps (actions/checkout, setup-uv, setup-node, setup-dotnet, cache) are NOT run.
They are JavaScript actions with their own downloads. The script prints each one it
skipped and what that means for the run. So a failure INSIDE an action — which is
exactly what bit us on 2026-08-16, actions/setup-python writing to a hardcoded
/Users/runner/hostedtoolcache — will not be reproduced here. For those, the job log is
still the evidence. What this catches is every failure in our own shell: a wrong path, a
missing flag, a command that does not exist on macOS, a step ordering mistake.

USAGE

    scripts/ci_local.py --list                 # jobs and their steps
    scripts/ci_local.py python                 # run the python job's shell steps
    scripts/ci_local.py python --dry-run       # print the commands, run nothing
    scripts/ci_local.py dotnet nextjs          # several jobs, in order

EXIT CODES

    0  every shell step in every named job exited 0
    1  a step failed (its exit code and output are printed, and later steps are skipped)
    2  the script could not do its job: bad job name, unreadable workflow, no yaml
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on a machine without pyyaml
    print("ci_local: PyYAML is not installed. `pip install pyyaml`", file=sys.stderr)
    raise SystemExit(2)

WORKFLOW = Path(".github/workflows/ci.yml")

# ${{ env.NAME }} and ${{ vars.NAME }}. Anything else in an expression is left alone and
# reported, because guessing at github.* context is how a local run stops resembling CI.
_EXPR = re.compile(r"\$\{\{\s*([a-zA-Z_][\w.]*)\s*(?:\|\|\s*'([^']*)')?\s*\}\}")


def _runner_os() -> str:
    return {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}.get(
        platform.system(), platform.system()
    )


def _git(*args: str) -> str:
    """Best-effort git read; an empty string is fine as a context default."""
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def substitute(text: str, env: dict[str, str]) -> tuple[str, list[str]]:
    """Expand ${{ env.X }} / ${{ vars.X || 'default' }}; report what was left."""
    unresolved: list[str] = []

    def repl(m: re.Match[str]) -> str:
        ref, default = m.group(1), m.group(2)
        if ref.startswith("env."):
            name = ref[4:]
            if name in env:
                return env[name]
        if ref.startswith("vars.") and default is not None:
            return default
        # github.base_ref -> $GITHUB_BASE_REF, the same name the runner exports. Seeded in
        # run_job below, so `guard` (which diffs against github.base_ref) actually runs.
        if ref.startswith("github."):
            name = "GITHUB_" + ref[7:].replace(".", "_").upper()
            if name in env:
                return env[name]
        unresolved.append(ref)
        return m.group(0)

    return _EXPR.sub(repl, text), unresolved


def step_applies(step: dict, env: dict[str, str]) -> tuple[bool, str]:
    """Evaluate the small subset of `if:` we actually use: runner.os comparisons."""
    cond = step.get("if")
    if cond is None:
        return True, ""
    cond = str(cond).strip()
    m = re.fullmatch(r"runner\.os\s*(==|!=)\s*'([^']+)'", cond)
    if m:
        op, want = m.group(1), m.group(2)
        actual = _runner_os()
        ok = (actual == want) if op == "==" else (actual != want)
        return ok, f"runner.os is {actual}"
    # Anything else is not understood. Run it rather than silently skipping: a step that
    # should not have run failing loudly is better than a step that should have run being
    # dropped without a word.
    return True, f"condition not evaluated locally: {cond!r}"


def apply_github_files(env_file: Path, path_file: Path, env: dict[str, str]) -> None:
    """Fold a step's GITHUB_ENV / GITHUB_PATH writes into the environment, as CI does."""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v
        env_file.write_text("")
    if path_file.exists():
        added = [p for p in path_file.read_text().splitlines() if p.strip()]
        if added:
            env["PATH"] = os.pathsep.join(added + [env.get("PATH", "")])
        path_file.write_text("")


def run_job(name: str, job: dict, workflow_env: dict[str, str], root: Path,
            dry_run: bool, allow_system: bool) -> bool:
    print(f"\n\033[1m=== job: {name}\033[0m")
    default_wd = (job.get("defaults", {}).get("run", {}) or {}).get("working-directory", ".")

    scratch = Path(tempfile.mkdtemp(prefix=f"ci-local-{name}-"))
    env_file, path_file = scratch / "github_env", scratch / "github_path"
    env_file.write_text("")
    path_file.write_text("")

    env = dict(os.environ)
    env.update(workflow_env)
    env.update({
        "CI": "true",
        "RUNNER_OS": _runner_os(),
        "RUNNER_TEMP": str(scratch / "temp"),
        "GITHUB_ENV": str(env_file),
        "GITHUB_PATH": str(path_file),
    })
    # The github.* context a PR job gets. Defaults describe a pull request into main, which
    # is what every job here runs on; override any of them from your shell to change it.
    env.setdefault("GITHUB_BASE_REF", "main")
    env.setdefault("GITHUB_EVENT_NAME", "pull_request")
    env.setdefault("GITHUB_REF_NAME", _git("rev-parse", "--abbrev-ref", "HEAD"))
    env.setdefault("GITHUB_SHA", _git("rev-parse", "HEAD"))
    Path(env["RUNNER_TEMP"]).mkdir(parents=True, exist_ok=True)

    ok = True
    for i, step in enumerate(job.get("steps", []), start=1):
        label = step.get("name") or step.get("uses") or f"step {i}"

        if "uses" in step:
            print(f"  \033[2m—  skipped (action): {label}\033[0m")
            continue

        applies, why = step_applies(step, env)
        if not applies:
            print(f"  \033[2m—  skipped (if): {label}  [{why}]\033[0m")
            continue
        if why:
            print(f"  \033[33m?  {why}\033[0m")

        cmd, unresolved = substitute(str(step["run"]), env)
        wd = root / step.get("working-directory", default_wd)
        step_env = dict(env)
        for k, v in (step.get("env") or {}).items():
            expanded, more = substitute(str(v), env)
            unresolved += more
            step_env[k] = expanded

        if unresolved:
            print(f"  \033[33m?  unresolved expression(s): {', '.join(sorted(set(unresolved)))}\033[0m")

        if dry_run:
            print(f"  \033[36m$  {label}\033[0m")
            for line in cmd.rstrip().splitlines():
                print(f"       {line}")
            continue

        # A runner is disposable; this machine is not. `--system` installs into whatever
        # interpreter is on PATH, which here is the developer's own python. Refuse it
        # rather than rewrite it, because a silently rewritten command stops being a
        # reproduction of the job.
        if "--system" in cmd and not allow_system:
            print(f"  \033[33m—  skipped (would install into this machine's python): "
                  f"{label}\033[0m")
            print("  \033[33m   re-run with --allow-system if that is what you want\033[0m")
            continue

        print(f"  \033[36m>  {label}\033[0m")
        started = time.time()
        proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", cmd],
                              cwd=wd, env=step_env)
        apply_github_files(env_file, path_file, env)
        secs = time.time() - started

        if proc.returncode == 0:
            print(f"  \033[32m✓  {label}  ({secs:.0f}s)\033[0m")
        else:
            print(f"  \033[31m✗  {label}  exit {proc.returncode} after {secs:.0f}s\033[0m")
            print(f"  \033[31m   later steps in `{name}` were not run\033[0m")
            ok = False
            break

    shutil.rmtree(scratch, ignore_errors=True)
    return ok


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("jobs", nargs="*", help="job names from ci.yml; default: python")
    ap.add_argument("--list", action="store_true", help="list jobs and steps, run nothing")
    ap.add_argument("--dry-run", action="store_true", help="print commands, run nothing")
    ap.add_argument("--allow-system", action="store_true",
                    help="permit steps that install into this machine's python")
    args = ap.parse_args(argv[1:])

    try:
        root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                            text=True).strip())
    except subprocess.CalledProcessError:
        print("ci_local: not inside a git repository", file=sys.stderr)
        return 2

    wf_path = root / WORKFLOW
    if not wf_path.exists():
        print(f"ci_local: {wf_path} not found", file=sys.stderr)
        return 2
    workflow = yaml.safe_load(wf_path.read_text())
    jobs = workflow.get("jobs", {})
    workflow_env = {k: str(v) for k, v in (workflow.get("env") or {}).items()}

    if args.list:
        for name, job in jobs.items():
            steps = job.get("steps", [])
            shell = sum(1 for s in steps if "run" in s)
            print(f"{name:10s} {len(steps)} steps, {shell} of them shell")
            for s in steps:
                kind = "run " if "run" in s else "uses"
                print(f"   {kind}  {s.get('name') or s.get('uses')}")
        return 0

    wanted = args.jobs or ["python"]
    unknown = [j for j in wanted if j not in jobs]
    if unknown:
        print(f"ci_local: unknown job(s): {', '.join(unknown)}. "
              f"Known: {', '.join(jobs)}", file=sys.stderr)
        return 2

    print(f"\033[2mrunner.os={_runner_os()}  actions are skipped; their tools must already "
          f"be on PATH\033[0m")
    failed = [j for j in wanted
              if not run_job(j, jobs[j], workflow_env, root, args.dry_run,
                                 args.allow_system)]

    print()
    if failed:
        print(f"\033[31mFAILED: {', '.join(failed)}\033[0m")
        return 1
    print(f"\033[32mOK: {', '.join(wanted)} (shell steps only)\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
