"""A tool installer must never need a directory the runner will not give it.

On 2026-08-19 `deploy-api.yml` could not run at all. Its only job died in
`actions/setup-dotnet@v4` with `mkdir: cannot create directory '/usr/share/dotnet': Permission
denied` (run 32223984416), because setup-dotnet installs there on Linux and our Linux runners are
containers with a non-root user.

`ci.yml` had already been fixed for exactly this on 2026-08-18 (ci.yml:613-615). `deploy-api.yml`
was not, and nothing noticed for a day, because a workflow gated on `on.push.paths` does not run
until something touches its paths — so a broken workflow and a workflow with nothing to do look
identical from the outside.

The fix is one line per job. This file is the thing that makes it one line per job FOREVER: add a
setup-dotnet step anywhere without it and this test fails, in the same CI run that added it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: The action under test, and the environment variable that decides where it writes.
ACTION = "actions/setup-dotnet"
VAR = "DOTNET_INSTALL_DIR"

#: Roots a self-hosted runner is guaranteed to be able to write to. `$HOME` persists between jobs
#: on our own runners, so the SDK is downloaded once; `github.workspace` does not, but it is
#: always writable. Anything else — `/usr/share`, `/opt`, `/usr/local` — is a root-owned system
#: directory on at least one runner in the pool and is what this test exists to refuse.
WRITABLE = ("$HOME", "${HOME}", "~/", "github.workspace", "RUNNER_TEMP", "runner.temp")


def _jobs() -> list[tuple[str, str, dict]]:
    """(workflow filename, job id, job body) for every job in every workflow."""
    out = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            if isinstance(job, dict):
                out.append((path.name, job_id, job))
    return out


def _dotnet_jobs() -> list[tuple[str, str, dict]]:
    return [
        (f, j, body)
        for f, j, body in _jobs()
        if any(
            ACTION in str(s.get("uses", ""))
            for s in (body.get("steps") or [])
            if isinstance(s, dict)
        )
    ]


def test_there_is_a_dotnet_job_to_grade():
    """Anti-vacuity. If .NET ever leaves this repo, delete this file deliberately rather than
    letting it pass by having nothing to check."""
    found = _dotnet_jobs()
    # deploy-api.yml went with the Fly pipeline on 2026-08-26 (crew#203); ci.yml's job stays.
    assert len(found) >= 1, f"expected at least the ci.yml dotnet job, found {found}"


@pytest.mark.parametrize("workflow,job_id", [(f, j) for f, j, _ in _dotnet_jobs()])
def test_every_dotnet_job_installs_somewhere_it_can_write(workflow: str, job_id: str):
    body = next(b for f, j, b in _dotnet_jobs() if (f, j) == (workflow, job_id))
    steps = body.get("steps") or []

    setup_at = next(
        i for i, s in enumerate(steps) if isinstance(s, dict) and ACTION in str(s.get("uses", ""))
    )

    # The variable may be set three ways: exported into GITHUB_ENV by an earlier step, on the
    # job's own `env:`, or on the workflow's. Only the first two are visible from here per job;
    # the workflow-level one is checked separately below.
    declared = ""
    for step in steps[:setup_at]:
        if not isinstance(step, dict):
            continue
        run = str(step.get("run", ""))
        if VAR in run and "GITHUB_ENV" in run:
            declared = run
        declared = declared or str((step.get("env") or {}).get(VAR, ""))
    declared = declared or str((body.get("env") or {}).get(VAR, ""))
    if not declared:
        doc = yaml.safe_load((WORKFLOWS / workflow).read_text()) or {}
        declared = str((doc.get("env") or {}).get(VAR, ""))

    assert declared, (
        f"{workflow}:{job_id} runs {ACTION} without setting {VAR} BEFORE it. On a Linux runner "
        f"that installs to /usr/share/dotnet, which our container runners cannot create. Copy the "
        f"three lines from ci.yml's dotnet job."
    )

    assert any(w in declared for w in WRITABLE), (
        f"{workflow}:{job_id} points {VAR} at {declared!r}. That is not one of the roots a "
        f"self-hosted runner is guaranteed to be able to write to ({', '.join(WRITABLE)})."
    )


def test_the_variable_is_set_before_the_action_not_after():
    """Ordering is the whole mechanism. setup-dotnet reads the variable when it runs, so a step
    that exports it afterwards reads as present to a naive grep and does nothing at all."""
    for workflow, job_id, body in _dotnet_jobs():
        steps = [s for s in (body.get("steps") or []) if isinstance(s, dict)]
        setup_at = next(i for i, s in enumerate(steps) if ACTION in str(s.get("uses", "")))
        after = [
            s
            for s in steps[setup_at + 1 :]
            if VAR in str(s.get("run", "")) and "GITHUB_ENV" in str(s.get("run", ""))
        ]
        before = [
            s
            for s in steps[:setup_at]
            if VAR in str(s.get("run", "")) and "GITHUB_ENV" in str(s.get("run", ""))
        ]
        assert not (after and not before), (
            f"{workflow}:{job_id} sets {VAR} AFTER {ACTION}, which has no effect on it"
        )


def test_the_failure_that_produced_this_file_is_named_in_the_workflow():
    """The comment is the only place a reader learns WHY the line is there, and a line whose
    reason is unrecorded is a line the next tidy-up deletes."""
    text = (WORKFLOWS / "ci.yml").read_text()
    assert re.search(r"/usr/share/dotnet", text), (
        "ci.yml no longer records why DOTNET_INSTALL_DIR is set"
    )
