"""A blocking advisory scan must cover the WHOLE dependency tree, exceptions named one by one.

This file replaces `test_a_merge_gate_never_rules_on_code_we_do_not_ship.py`, which pinned the
opposite rule. That rule came from a real incident and drew the wrong conclusion from it. On
2026-08-19 `npm audit --audit-level=high` turned main red with no code change -- 13 high
advisories, all under `@lhci/cli` or `@storybook/nextjs-vite` -- and it blocked every merge in
the repository. The fix that landed added `--omit=dev`, and the test above froze that in place.

Not one dependency changed. The founder's verdict: "that fixed the build, not the issues the
build was complaining about." `--omit=dev` is not a decision about those 13 advisories, it is a
standing instruction to stop looking at half the tree, so every future dev advisory lands silent
too -- including one that matters. A build-time package executes on the CI runner, in this repo,
with whatever the job can reach.

The rule this file pins now:

  1. A blocking advisory step scans the full tree. `--omit=dev` and `--production` are banned on
     any step that can fail a build.
  2. There is at least one such step, so the file cannot pass by finding nothing.
  3. Every advisory the gate tolerates is a written decision: a GHSA id, why it is survivable,
     and a date it gets looked at again.

Rule 3 is checked for SHAPE here, never for freshness. The expiry is enforced by
`store_platform/scripts/audit_gate.mjs` in CI, where a red step names the advisory and the next
action. Enforcing it here as well would put the whole pytest suite -- and therefore the
pre-commit gate -- on a timer, which is a much larger blast radius than the reminder is worth.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ALLOWLISTS = sorted((ROOT / "store_platform" / "src").glob("*/audit-allowlist.json"))

# Anything whose verdict is fetched from an outside advisory feed at gate time, including the
# wrapper. `npm run audit:gate` does not contain the string "npm audit", so matching only the
# raw command would have made this file silently vacuous the day the gate was introduced.
EXTERNAL_VERDICT = ("npm audit", "yarn audit", "pnpm audit", "audit:gate", "audit_gate.mjs")
NARROWING = ("--omit=dev", "--production")


def _steps():
    """(workflow, job, step_name, run_text, blocking) for every `run:` step in every workflow."""
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(wf.read_text()) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                blocking = not (step.get("continue-on-error") is True
                                or job.get("continue-on-error") is True)
                yield wf.name, job_name, step.get("name") or "(unnamed)", run, blocking


def _audit_steps():
    return [s for s in _steps() if any(c in s[3] for c in EXTERNAL_VERDICT)]


def test_there_is_a_blocking_advisory_gate():
    """If the gate ever vanishes or goes report-only, this file must fail rather than pass."""
    blocking = [s for s in _audit_steps() if s[4]]
    assert blocking, (
        "no BLOCKING advisory scan in any workflow. Either the step was deleted or it was "
        "marked continue-on-error, which is the same thing with extra words."
    )


@pytest.mark.parametrize("step", _audit_steps(), ids=lambda s: f"{s[0]}:{s[1]}:{s[2]}")
def test_a_blocking_advisory_scan_is_not_narrowed_to_the_shipped_tree(step):
    wf, job, name, run, blocking = step
    if not blocking:
        return
    used = [flag for flag in NARROWING if flag in run]
    assert not used, (
        f"{wf} job `{job}` step `{name}` gates on {', '.join(used)}, which stops the build "
        f"ever hearing about a dev-tree advisory. Scan the whole tree and record each accepted "
        f"advisory in that project's audit-allowlist.json.\n  run: {run.strip()}"
    )


def test_the_gate_script_is_where_the_workflow_says_it_is():
    assert (ROOT / "store_platform" / "scripts" / "audit_gate.mjs").is_file()


@pytest.mark.parametrize("path", ALLOWLISTS, ids=lambda p: p.parent.name)
def test_every_accepted_advisory_is_a_written_decision(path):
    data = json.loads(path.read_text())
    seen = set()
    for entry in data.get("accepted", []):
        ghsa = entry.get("ghsa", "")
        assert re.fullmatch(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", ghsa), (
            f"{path}: `{ghsa}` is not a GHSA id. The gate matches on the advisory id, so a "
            f"typo here is an entry that never applies to anything."
        )
        assert ghsa not in seen, f"{path}: {ghsa} listed twice"
        seen.add(ghsa)
        assert entry.get("why", "").strip(), f"{path}: {ghsa} has no reason recorded"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.get("review_by", "")), (
            f"{path}: {ghsa} has no `review_by` date in YYYY-MM-DD form. The gate compares it "
            f"as a string against today, so any other format silently never expires."
        )
