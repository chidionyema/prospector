"""A pull request that changes code must run the lane that grades that code.

`ci.yml`'s `changes` job decides which lanes run. Until 2026-08-19 it had an early `exit 0` for
any diff touching `.github/`, and on a MIXED diff that branch decided dotnet, web and console from
the TEXT of the workflow diff and threw the file list away. Run 32226199534 is the receipt: the
pull request changed `store_platform/src/Ops.Console/src/pages/queue.tsx` and two api route files
alongside `.github/workflows/deploy-api.yml`, the `ops-console` job reported `skipped`, nothing
typechecked the console, and the run was green.

A skipped lane is not a failing lane. It leaves a tick, not a cross, so nothing downstream can
tell "graded and passed" from "never looked at".

This file runs the filter's real shell, lifted out of ci.yml, against made-up file lists. Editing
the regexes is fine; making the filter blind to a file is not.
"""
from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _filter_script() -> str:
    """The decision half of the filter step: everything from the `match` helper onwards."""
    doc = yaml.safe_load(CI.read_text())
    steps = doc["jobs"]["changes"]["steps"]
    step = next(s for s in steps if s.get("id") == "filter")
    body = step["run"]
    start = body.index("match() {")
    return body[start:]


def _run(files: list[str], workflow_diff: str = "") -> dict[str, str]:
    """Execute the filter with `files` as the diff and `workflow_diff` as the .github patch text.

    `git` is shadowed by a shell function, so the script's own `git diff ... -- .github/` returns
    whatever this test wants without a repository being involved.
    """
    script = textwrap.dedent(f"""
        set -u
        files={_q(chr(10).join(files))}
        base=main
        git() {{ printf '%s\\n' {_q(workflow_diff)}; }}
        """) + _filter_script()

    out = Path(_tmp()) / "gh_output"
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                          capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(out)})
    assert proc.returncode == 0, f"the filter exited {proc.returncode}: {proc.stderr}"
    parsed = {}
    for line in out.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            parsed[k] = v
    return parsed


_TMP: list[str] = []


def _tmp() -> str:
    import tempfile
    if not _TMP:
        _TMP.append(tempfile.mkdtemp())
    return _TMP[0]


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def test_the_filter_is_still_a_shell_block_this_test_can_run():
    """Anti-vacuity. If the step is rewritten as an action, every case below would pass by
    grading nothing. Fail loudly instead."""
    script = _filter_script()
    assert "GITHUB_OUTPUT" in script and "match()" in script


@pytest.mark.parametrize("lane,path", [
    ("python", "prospector/run.py"),
    ("dotnet", "store_platform/src/Store.Api/Program.cs"),
    ("web", "store_platform/src/Store.Web/app/page.tsx"),
    ("console", "store_platform/src/Ops.Console/src/pages/queue.tsx"),
])
def test_a_change_to_one_area_runs_that_areas_lane(lane: str, path: str):
    assert _run([path])[lane] == "true", f"{path} did not turn on the {lane} lane"


@pytest.mark.parametrize("lane,path", [
    ("python", "prospector/run.py"),
    ("dotnet", "store_platform/src/Store.Api/Program.cs"),
    ("web", "store_platform/src/Store.Web/app/page.tsx"),
    ("console", "store_platform/src/Ops.Console/src/pages/queue.tsx"),
])
def test_a_workflow_edit_alongside_code_still_grades_the_code(lane: str, path: str):
    """THE REGRESSION. A diff containing a workflow file must not stop the file list being read.

    The workflow patch here deliberately names nothing, so the only route to a `true` is the file
    list itself.
    """
    got = _run([".github/workflows/deploy-api.yml", path],
               workflow_diff="+          run: echo hello")
    assert got[lane] == "true", (
        f"{path} changed alongside a workflow file and the {lane} lane was switched off. That is "
        f"the 2026-08-19 defect: the .github branch discarded the file list.")


def test_a_workflow_only_change_still_runs_python():
    """`guard` and `ci-ok` are python-lane jobs, so any workflow edit can move them."""
    got = _run([".github/workflows/ci.yml"], workflow_diff="+ timeout-minutes: 45")
    assert got["python"] == "true"


def test_a_workflow_only_change_does_not_run_every_heavy_lane():
    """The cost control this branch exists for. A workflow patch naming nothing must not queue
    the dotnet, web and console lanes for work that does not exist."""
    got = _run([".github/workflows/ci.yml"], workflow_diff="+ timeout-minutes: 45")
    assert (got["dotnet"], got["web"], got["console"]) == ("false", "false", "false"), got


@pytest.mark.parametrize("lane,mention", [
    ("dotnet", "-        dotnet-version: 8.0.x"),
    ("web", "+  nextjs:"),
    ("console", "+  ops-console:"),
])
def test_a_workflow_edit_that_names_a_lane_runs_it_with_no_files_of_its_own(lane, mention):
    got = _run([".github/workflows/ci.yml"], workflow_diff=mention)
    assert got[lane] == "true", f"a workflow diff naming {lane} did not turn its lane on"


def test_a_docs_only_change_runs_nothing_heavy():
    got = _run(["docs/DEPLOY_PIPELINE.md"])
    assert got == {"python": "false", "dotnet": "false", "web": "false", "console": "false"}, got


def test_every_lane_output_is_always_written():
    """A job's `if:` compares against an output that may not exist. An unwritten output is the
    empty string, which is not 'true', so the lane silently skips. Write all four, always."""
    for files in (["README.md"], ["prospector/run.py"], [".github/workflows/ci.yml"]):
        got = _run(files, workflow_diff="+x")
        assert set(got) == {"python", "dotnet", "web", "console"}, (files, got)


def test_the_jobs_gate_on_the_outputs_this_filter_writes():
    """The filter and the jobs must name the same four lanes, or a lane is decided by an output
    nothing sets."""
    doc = yaml.safe_load(CI.read_text())
    declared = set(doc["jobs"]["changes"]["outputs"])
    assert declared == {"python", "dotnet", "web", "console"}, declared
    referenced = set(re.findall(r"needs\.changes\.outputs\.(\w+)", CI.read_text()))
    assert referenced <= declared, f"{sorted(referenced - declared)} is gated on nothing"
