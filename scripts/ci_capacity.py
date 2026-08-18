#!/usr/bin/env python3
"""Check that CI's declared capacity contract still matches the workflows and the runners.

WHY THIS EXISTS. Every previous fix for "CI is unreliable on this box" was a constant tuned to
one observed mix: PYTEST_XDIST_AUTO_NUM_WORKERS=3 chosen for four concurrent python jobs, the
concurrency group, the per-SHA group for pushes to main. Each held until the mix changed, because
nothing compared the constants to each other. Adding a job, or registering a fifth runner, moved
the load and nothing said so.

`ops/config/ci_capacity.yaml` declares the contract. This checks it three ways:

  1. every job in ci.yml is assigned to exactly one pool, and its `runs-on` reads that pool's
     variable — a new job cannot land in the shared pool by default
  2. the widest `heavy.runners` jobs, running at once, fit in cpus - reserved_cpus — and each
     declared width is read back out of ci.yml, so the two cannot drift apart
  3. with --live, the runners actually registered on GitHub carry the pool labels in the
     declared numbers

Exit 0 = the contract holds. Exit 1 = it does not, with the specific line that broke it.

    python3 scripts/ci_capacity.py           # offline; runs in CI's guard lane
    python3 scripts/ci_capacity.py --live    # also checks the registered runners (needs gh)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "ops/config/ci_capacity.yaml"
CI = ROOT / ".github/workflows/ci.yml"

#: `runs-on: ${{ vars.X || vars.CI_RUNS_ON || 'ubuntu-latest' }}` -> X
_RUNS_ON = re.compile(r"runs-on:\s*\$\{\{\s*vars\.([A-Z_]+)")
_JOB = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$")
_WORKERS = re.compile(r'^\s*PYTEST_XDIST_AUTO_NUM_WORKERS:\s*"?(\d+)"?', re.M)


def jobs_and_pools(text: str) -> dict[str, str]:
    """Each job in ci.yml and the variable its `runs-on` reads. Jobs are two-space keys under
    `jobs:`; a job with no `runs-on` of that shape maps to the empty string so it still fails."""
    out: dict[str, str] = {}
    job = None
    for line in text.split("\n"):
        m = _JOB.match(line)
        if m:
            job = m.group(1)
            continue
        if job and "runs-on:" in line:
            hit = _RUNS_ON.search(line)
            out[job] = hit.group(1) if hit else ""
            job = None
    return out


def read_contract(path: Path) -> dict:
    """Read the contract file with the standard library only.

    It runs in CI's `guard` lane, which has no virtualenv on purpose -- the lane exists to be the
    one that always runs, including on a docs-only pull request. Depending on PyYAML there would
    make this check the thing that breaks the build it is meant to protect. The file is nested
    mappings of scalars and inline lists, which is all this reads; anything else raises.
    """
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for n, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        line = raw.split(" #")[0].rstrip() if " #" in raw else raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        if not _:
            raise ValueError(f"{path.name}:{n}: not a `key: value` line: {raw!r}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value = value.strip()
        if not value:
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        elif value.startswith("[") and value.endswith("]"):
            parent[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            parent[key] = int(value) if value.lstrip("-").isdigit() else value
    return root


def _job_block(text: str, job: str) -> str:
    """Everything in ci.yml from `  <job>:` up to the next job header."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln == f"  {job}:"), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if _JOB.match(lines[i])), len(lines))
    return "\n".join(lines[start:end])


def _explicit_n(text: str, job: str) -> int | None:
    """The widest `pytest ... -n N` this job runs on its command line, or None when it leaves the
    width to `-n auto` (which resolves through PYTEST_XDIST_AUTO_NUM_WORKERS)."""
    ns = [int(m) for m in re.findall(r"pytest[^\n]*?-n (\d+)", _job_block(text, job))]
    return max(ns) if ns else None


def registered_runners() -> list[dict]:
    raw = subprocess.run(
        ["gh", "api", "repos/chidionyema/prospector/actions/runners", "--paginate"],
        capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(raw)["runners"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="also check the runners registered on GitHub")
    args = ap.parse_args()

    contract = read_contract(CONTRACT)
    box, pools = contract["box"], contract["pools"]
    text = CI.read_text(encoding="utf-8")
    bad: list[str] = []

    # 1. Every job is in exactly one pool, and reads that pool's variable.
    declared = {j: name for name, p in pools.items() for j in p["jobs"]}
    for job, var in sorted(jobs_and_pools(text).items()):
        pool = declared.get(job)
        if pool is None:
            bad.append(f"ci.yml job {job!r} is in no pool — add it to {CONTRACT.name} "
                       f"under pools.<heavy|light>.jobs")
            continue
        want = pools[pool]["variable"]
        if var != want:
            bad.append(f"ci.yml job {job!r} is declared {pool} but its runs-on reads "
                       f"{var or '(no vars. expression)'}, not {want}")
    for job, pool in sorted(declared.items()):
        if job not in jobs_and_pools(text):
            bad.append(f"{CONTRACT.name} declares job {job!r} in the {pool} pool, "
                       f"but ci.yml has no such job")

    # 2. The arithmetic. At most `heavy.runners` heavy jobs run at once, so the worst case is the
    #    widest that many. The widths are read back out of ci.yml so the yaml cannot drift.
    hit = _WORKERS.search(text)
    if not hit:
        bad.append("ci.yml no longer sets PYTEST_XDIST_AUTO_NUM_WORKERS, so how wide a heavy job "
                   "runs is undeclared and this contract cannot be checked")
    else:
        auto = int(hit.group(1))
        widths = contract["job_cpus"]
        for job, n in sorted(widths.items()):
            explicit = _explicit_n(text, job)
            want = explicit if explicit is not None else auto if n > 1 else n
            if n != want:
                bad.append(f"{CONTRACT.name} says {job!r} runs {n} process(es), but ci.yml runs "
                           f"{want} — change one to match the other")
        heavy = pools["heavy"]["runners"]
        budget = box["cpus"] - box["reserved_cpus"]
        worst = sorted(widths.values(), reverse=True)[:heavy]
        used = sum(worst)
        print(f"worst case: {heavy} heavy jobs at once = {'+'.join(map(str, worst))} = {used} "
              f"CPUs; budget {budget} of {box['cpus']} ({box['reserved_cpus']} reserved)")
        if used > budget:
            bad.append(f"CI would take {used} CPUs of a {budget}-CPU budget: lower "
                       f"pools.heavy.runners, narrow a job in ci.yml, or raise box.cpus if the "
                       f"machine actually changed")

    # 3. The runners that exist, when asked for.
    if args.live:
        try:
            runners = registered_runners()
        except Exception as exc:                                   # noqa: BLE001
            bad.append(f"could not read the registered runners: {type(exc).__name__}: {exc}")
            runners = []
        for name, p in sorted(pools.items()):
            labels = [r["name"] for r in runners if p["label"] in
                      {lbl["name"] for lbl in r.get("labels", [])}]
            print(f"{name:5} pool: {len(labels)} registered {sorted(labels)}")
            if len(labels) != p["runners"]:
                bad.append(f"the {name} pool declares {p['runners']} runner(s) but "
                           f"{len(labels)} carry the {p['label']!r} label: {sorted(labels)}")
        unlabelled = [r["name"] for r in runners
                      if not ({lbl["name"] for lbl in r.get("labels", [])}
                              & {p["label"] for p in pools.values()})]
        if unlabelled:
            bad.append(f"runner(s) in no pool: {sorted(unlabelled)} — they will take work from "
                       f"any job whose runs-on falls back to CI_RUNS_ON")

    for line in bad:
        print(f"FAIL {line}", file=sys.stderr)
    print("ci capacity contract: " + ("BROKEN" if bad else "holds"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
