"""The green guard must not revert a commit for a failure it inherited.

Measured 2026-08-20. `main-green-guard.yml` reverted PR #466 -- the central log ingest, both
shippers, the correlation id work and the console auth gate -- because main's CI failed twice.
Of the five failing tests, four had been failing since #460 and #467 merged. The decisive
receipt is the guard's own follow-up run 32317556934 on the revert commit `739b6d42`: it failed
on the same five tests. The revert did not make main green, so #466 was not the cause of four
fifths of the red.

These tests pin the check that would have stopped it, in both directions. Direction matters
more than usual here: a check that always says "already red" would disable the guard entirely
and let a red main sit forever, which is the failure the guard exists to prevent.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "green_guard_cause.py"
WORKFLOW = REPO / ".github" / "workflows" / "main-green-guard.yml"

SHA = "a2e35ae2a62ec2d5d0386c12ea4685a6a258946c"
PARENT = "fe6fcd13ffffffffffffffffffffffffffffffff"


@pytest.fixture(scope="module")
def gg():
    spec = importlib.util.spec_from_file_location("green_guard_cause", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_api(gg, monkeypatch, *, parents=(PARENT,), runs=()):
    """Replace the ONE seam every GitHub read goes through."""
    def _api(path: str):
        if "/actions/workflows/" in path:
            assert PARENT in path, "the runs were fetched for %s, not the parent" % path
            return {"workflow_runs": list(runs)}
        if "/commits/" in path:
            return {"parents": [{"sha": p} for p in parents]}
        raise AssertionError("unexpected call: %s" % path)
    monkeypatch.setattr(gg, "gh_api", _api)


def run(created, updated, conclusion, status="completed", rid=1):
    return {"id": rid, "created_at": created, "updated_at": updated,
            "status": status, "conclusion": conclusion,
            "html_url": "https://example.invalid/%d" % rid}


def test_a_parent_that_was_already_failing_stands_the_guard_down(gg, monkeypatch):
    """The #466 case. Main was broken before the commit arrived, so reverting it fixes nothing."""
    fake_api(gg, monkeypatch,
             runs=[run("2026-08-19T23:48Z", "2026-08-19T23:55Z", "failure")])
    verdict, why = gg.parent_verdict("o/r", SHA)
    assert verdict == gg.ALREADY_RED
    assert PARENT[:8] in why, "the refusal must name the commit that was already red: %r" % why


def test_a_parent_that_was_green_leaves_the_guard_free_to_revert(gg, monkeypatch):
    """The control, and the more important one. Without it the check could pass by always
    standing down, which would disable the recovery this guard exists to provide."""
    fake_api(gg, monkeypatch,
             runs=[run("2026-08-19T23:48Z", "2026-08-19T23:55Z", "success")])
    assert gg.parent_verdict("o/r", SHA)[0] == gg.NEWLY_RED


def test_a_rerun_that_went_green_is_read_as_green(gg, monkeypatch):
    """A re-run keeps the run id and rewrites its conclusion. Reading the first row of the API
    response, or the newest `created_at`, would take a superseded failure as the parent's
    verdict and stand the guard down on a run that has since passed."""
    fake_api(gg, monkeypatch, runs=[
        run("2026-08-19T23:48Z", "2026-08-19T23:52Z", "failure", rid=1),
        run("2026-08-19T23:40Z", "2026-08-19T23:59Z", "success", rid=2),
    ])
    assert gg.parent_verdict("o/r", SHA)[0] == gg.NEWLY_RED


def test_an_unmeasured_parent_does_not_block_the_revert(gg, monkeypatch):
    """No completed run means nothing was measured. Standing down on missing evidence would let
    any change that stops CI running disable the guard."""
    fake_api(gg, monkeypatch, runs=[run("2026-08-19T23:48Z", "2026-08-19T23:48Z",
                                        None, status="in_progress")])
    assert gg.parent_verdict("o/r", SHA)[0] == gg.UNKNOWN


def test_a_first_commit_with_no_parent_is_unknown(gg, monkeypatch):
    fake_api(gg, monkeypatch, parents=())
    assert gg.parent_verdict("o/r", SHA)[0] == gg.UNKNOWN


def test_a_github_outage_does_not_stand_the_guard_down(gg, monkeypatch, tmp_path, capsys):
    """An API failure is unknown evidence, not proof of innocence. If it stood the guard down,
    one GitHub outage would leave main red with nothing to recover it."""
    def _boom(path):
        raise RuntimeError("502 Bad Gateway")
    monkeypatch.setattr(gg, "gh_api", _boom)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert gg.main(["--sha", SHA, "--repo", "o/r"]) == 0
    assert "verdict=%s" % gg.UNKNOWN in out.read_text()
    assert gg.UNKNOWN in capsys.readouterr().out


def test_the_verdict_reaches_the_workflow_as_a_step_output(gg, monkeypatch, tmp_path):
    fake_api(gg, monkeypatch,
             runs=[run("2026-08-19T23:48Z", "2026-08-19T23:55Z", "failure")])
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert gg.main(["--sha", SHA, "--repo", "o/r"]) == 0
    assert "verdict=%s" % gg.ALREADY_RED in out.read_text()


# --- the wiring. A check nothing calls is a check that does not exist. -----------------------

@pytest.fixture(scope="module")
def workflow_source() -> str:
    assert WORKFLOW.exists(), "%s is gone" % WORKFLOW
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_code(workflow_source: str) -> str:
    """The workflow with comment lines removed. Its own comments quote the thing they explain,
    so a search over the raw text would find this check in prose after someone deleted it."""
    return "\n".join(ln for ln in workflow_source.splitlines()
                     if not ln.lstrip().startswith(("#", "//")))


def test_the_workflow_is_valid_yaml(workflow_source: str) -> None:
    assert yaml.safe_load(workflow_source), "main-green-guard.yml does not parse"


def test_the_revert_job_runs_the_check(workflow_code: str) -> None:
    assert "scripts/green_guard_cause.py" in workflow_code, (
        "main-green-guard.yml no longer runs the cause check, so it is back to reverting the "
        "newest commit on faith")


def test_the_revert_is_gated_on_the_verdict(workflow_code: str) -> None:
    """The check exists to CHANGE something. Running it and ignoring the answer is the shape
    this test refuses.

    Bounded to the DECIDE step on purpose. A bare `"already-red" in workflow_code` passed while
    the decide step compared against a value the script never returns, because the string also
    appears in the `if:` of the step that opens the issue. Measured by mutation before this
    file shipped: that version of this test survived the mutation it exists to catch.
    """
    start = workflow_code.index("id: decide")
    block = workflow_code[start:workflow_code.index("Say why nothing was reverted", start)]
    assert "steps.cause.outputs.verdict" in block, (
        "the decide step never reads the cause check's verdict, so the revert is not gated on it")
    assert "'already-red'" in block, (
        "the decide step reads the verdict but compares it against something "
        "green_guard_cause.py never returns, so it can never refuse")
    assert "'already-red')" in block, (
        "the comparison is there but nothing calls refuse(..., 'already-red'), so the issue "
        "step below can never fire and a stand-down stays silent")
