"""scripts/workflow_health.py must call a jobless workflow DEAD, and an outage "could not tell".

WHY THIS FILE EXISTS. On 2026-08-19 `.github/workflows/ci-autoscale.yml` had 30 runs, 30
failures and zero jobs on every one — `workflow_job` is a webhook event, not a workflow
trigger, so GitHub could not start it. There was no log, no annotation and no red check
anywhere, so the CI runner pool went unscaled for the workflow's entire life and nobody saw
it. The tell is arithmetic, not a log line: a run that CONCLUDED and produced zero jobs did
no work.

These tests replace the network calls, so they run offline and pin the DECISION rather than
the plumbing. The second failure mode they guard is the worse one: an API error or a missing
`gh` must exit 2, never 0. A health check that reports green when it could not measure is
more dangerous than no health check at all.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "workflow_health", ROOT / "scripts" / "workflow_health.py"
)
assert SPEC and SPEC.loader
wfh = importlib.util.module_from_spec(SPEC)
sys.modules["workflow_health"] = wfh
SPEC.loader.exec_module(wfh)


def _fake_gh(workflows, runs_by_wf, jobs_by_run):
    """Stand in for `gh api`, dispatching on the path the script asks for."""

    def gh(args):
        path = args[0]
        if path.endswith("/actions/workflows"):
            return workflows
        if "/actions/workflows/" in path and "/runs" in path:
            wid = int(path.split("/actions/workflows/")[1].split("/runs")[0])
            return runs_by_wf.get(wid, [])
        if "/actions/runs/" in path and path.endswith("/jobs"):
            rid = int(path.split("/actions/runs/")[1].split("/jobs")[0])
            return jobs_by_run.get(rid, 0)
        raise AssertionError(f"unexpected gh api path: {path}")

    return gh


def _wf(wid, path, state="active"):
    return {"id": wid, "name": path.split("/")[-1], "path": path, "state": state}


def _run(rid, conclusion="failure", status="completed"):
    return {"id": rid, "conclusion": conclusion, "status": status}


def test_a_workflow_whose_every_run_produced_zero_jobs_is_dead(monkeypatch):
    monkeypatch.setattr(
        wfh,
        "_gh",
        _fake_gh(
            [_wf(1, ".github/workflows/ci-autoscale.yml")],
            {1: [_run(10), _run(11), _run(12)]},
            {10: 0, 11: 0, 12: 0},
        ),
    )
    report = wfh.grade("o/r", 3)
    assert report["dead"] == [".github/workflows/ci-autoscale.yml"]
    assert report["healthy"] is False


def test_a_workflow_that_fails_but_does_real_work_is_red_not_dead(monkeypatch):
    monkeypatch.setattr(
        wfh,
        "_gh",
        _fake_gh(
            [_wf(2, ".github/workflows/e2e-live-smoke.yml")],
            {2: [_run(20), _run(21)]},
            {20: 4, 21: 4},
        ),
    )
    report = wfh.grade("o/r", 2)
    assert report["dead"] == []
    assert report["red"] == [".github/workflows/e2e-live-smoke.yml"]
    assert report["healthy"] is False


def test_a_healthy_workflow_is_healthy(monkeypatch):
    monkeypatch.setattr(
        wfh,
        "_gh",
        _fake_gh(
            [_wf(3, ".github/workflows/ci.yml")],
            {3: [_run(30, "success"), _run(31, "success")]},
            {30: 6, 31: 6},
        ),
    )
    report = wfh.grade("o/r", 2)
    assert report["healthy"] is True


def test_an_unconcluded_run_is_not_evidence_either_way(monkeypatch):
    """A queued run has no jobs yet. Counting it would call every busy repo dead."""
    monkeypatch.setattr(
        wfh,
        "_gh",
        _fake_gh(
            [_wf(4, ".github/workflows/ci.yml")],
            {4: [_run(40, None, "queued"), _run(41, "success")]},
            {40: 0, 41: 3},
        ),
    )
    report = wfh.grade("o/r", 2)
    assert report["workflows"][0]["runs_graded"] == 1
    assert report["healthy"] is True


def test_a_disabled_workflow_is_not_graded(monkeypatch):
    monkeypatch.setattr(
        wfh,
        "_gh",
        _fake_gh([_wf(5, ".github/workflows/old.yml", state="disabled_manually")], {}, {}),
    )
    assert wfh.grade("o/r", 3)["workflows"] == []


def test_an_api_error_exits_could_not_tell_never_green(monkeypatch, capsys):
    """The failure mode that matters most: an outage must never read as health."""
    monkeypatch.setattr(wfh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(wfh, "_repo", lambda _e: "o/r")

    def boom(_args):
        raise RuntimeError("HTTP 401: Bad credentials")

    monkeypatch.setattr(wfh, "_gh", boom)
    assert wfh.main([]) == 2
    assert "Bad credentials" in capsys.readouterr().err


def test_a_missing_gh_exits_could_not_tell(monkeypatch):
    monkeypatch.setattr(wfh.shutil, "which", lambda _n: None)
    assert wfh.main([]) == 2


@pytest.mark.parametrize("jobs,expected", [(0, 1), (5, 0)])
def test_main_exit_code_follows_the_verdict(monkeypatch, jobs, expected):
    monkeypatch.setattr(wfh.shutil, "which", lambda _n: "/usr/bin/gh")
    monkeypatch.setattr(wfh, "_repo", lambda _e: "o/r")
    monkeypatch.setattr(
        wfh,
        "_gh",
        _fake_gh([_wf(6, ".github/workflows/ci.yml")], {6: [_run(60, "success")]}, {60: jobs}),
    )
    assert wfh.main(["--json"]) == expected
