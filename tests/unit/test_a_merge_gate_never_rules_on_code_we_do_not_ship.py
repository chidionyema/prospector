"""A blocking CI step must not take its verdict from an outside advisory feed.

`npm audit` asks a remote advisory database a question whose answer changes without anybody
touching this repository. Wired in as a merge gate over the WHOLE dependency tree, it turned
main red on 2026-08-19 with no code change: 10 high advisories, every one of them under
`@lhci/cli` or `@storybook/nextjs-vite` -- build tooling that no request ever reaches. The
production tree had zero. It blocked every merge in the repository, including PR #425, which
was the fix for main's other red, so one external feed update stalled 14 pull requests.

The rule this pins: a step that can BLOCK a merge may only rule on code we ship
(`--omit=dev`), and a scan of the full tree is welcome as long as it cannot fail the build
(`continue-on-error: true`). Report all you like; gate only on what reaches a user.
"""
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# Commands whose verdict is fetched from outside this repository at gate time.
EXTERNAL_VERDICT = ("npm audit", "yarn audit", "pnpm audit")


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


def _external_gates():
    return [s for s in _steps()
            if any(c in s[3] for c in EXTERNAL_VERDICT) and s[4]]


def test_there_is_something_to_check():
    """If the audit steps ever vanish, this file must fail rather than pass vacuously."""
    found = [s for s in _steps() if any(c in s[3] for c in EXTERNAL_VERDICT)]
    assert found, "no advisory scan found in any workflow -- did the step get deleted?"


@pytest.mark.parametrize("gate", _external_gates(),
                         ids=lambda g: f"{g[0]}:{g[1]}:{g[2]}")
def test_a_blocking_advisory_scan_covers_only_shipped_code(gate):
    wf, job, name, run, _ = gate
    assert "--omit=dev" in run or "--production" in run, (
        f"{wf} job `{job}` step `{name}` can block a merge on an advisory in a dev-only "
        f"dependency. Either add --omit=dev so it rules on code we ship, or mark the step "
        f"continue-on-error: true so it reports instead of gating.\n  run: {run.strip()}"
    )


def test_a_full_tree_scan_is_allowed_only_when_it_cannot_fail_the_build():
    offenders = [
        f"{wf}:{job}:{name}"
        for wf, job, name, run, blocking in _steps()
        if any(c in run for c in EXTERNAL_VERDICT)
        and "--omit=dev" not in run and "--production" not in run
        and blocking
    ]
    assert not offenders, (
        "these steps scan the full dependency tree AND can fail the build: "
        + ", ".join(offenders)
    )
