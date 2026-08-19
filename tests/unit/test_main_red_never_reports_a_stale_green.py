"""scripts/main_red.py must never call main green on a run that is not about main's HEAD.

WHY THIS FILE EXISTS. The first version of that script printed `MAIN GREEN: run 31854380817 ...
2026-08-15` while main was red on 2026-08-19 — a four-day-old run reported as today's state. The
tool whose whole job is "prove it before you merge onto a red main" gave the one wrong answer that
would have caused the merge. A green tick is about a SHA, never about a branch name.

These tests drive main() with the network calls replaced, so they run offline and pin the decision
rather than the plumbing.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("main_red", ROOT / "scripts" / "main_red.py")
assert SPEC and SPEC.loader
main_red = importlib.util.module_from_spec(SPEC)
sys.modules["main_red"] = main_red
SPEC.loader.exec_module(main_red)

OLD = "a" * 40
HEAD = "b" * 40
RED_TEST = "tests/unit/test_ci_runner_loops_without_a_reboot.py::test_a_failed_job_does_not_end_the_fleet"
RED_FILE = RED_TEST.split("::")[0]


def _run(monkeypatch, *, sha, conclusion, head, failures=None, since=frozenset(), argv=()):
    monkeypatch.setattr(main_red, "latest_concluded_main_run", lambda: {
        "databaseId": 1, "status": "completed", "conclusion": conclusion,
        "headSha": sha, "createdAt": "2026-08-15T00:41:38Z"})
    monkeypatch.setattr(main_red, "main_head", lambda: head)
    monkeypatch.setattr(main_red, "commits_between", lambda a, b: 2)
    monkeypatch.setattr(main_red, "files_changed_between", lambda a, b: set(since))
    monkeypatch.setattr(main_red, "failures_in",
                        lambda run_id: (["python"], dict(failures or {})))
    monkeypatch.setattr(sys, "argv", ["main_red.py", *argv])
    return main_red.main()


def test_a_green_run_on_an_older_sha_is_never_reported_as_green(monkeypatch, capsys):
    """The exact bug. Commits landed after the green run, so the run says nothing about them."""
    code = _run(monkeypatch, sha=OLD, conclusion="success", head=HEAD)
    out = capsys.readouterr().out
    assert code == 2, "a stale green must be `could not tell`, never a pass"
    assert "MAIN GREEN" not in out
    assert "COULD NOT TELL" in out


def test_a_green_run_on_the_head_sha_is_green(monkeypatch, capsys):
    code = _run(monkeypatch, sha=HEAD, conclusion="success", head=HEAD)
    assert code == 0
    assert "MAIN GREEN" in capsys.readouterr().out


def test_a_red_run_behind_head_still_counts_when_nothing_touched_the_failing_file(
        monkeypatch, capsys):
    """Being behind HEAD is not the same as unknowable. Untested commits can only ADD failures, so
    a failure whose file nobody has touched since is still in the tree — and saying `could not
    tell` here would make the tool useless in the hour it is needed."""
    code = _run(monkeypatch, sha=OLD, conclusion="failure", head=HEAD,
                failures={RED_TEST: "python"}, since={"docs/README.md"})
    out = capsys.readouterr().out
    assert code == 1
    assert "STILL RED" in out
    assert RED_FILE in out


def test_a_red_run_behind_head_is_undecided_once_the_failing_file_changed(monkeypatch, capsys):
    """Somebody may already have fixed it. Reporting red here sends an agent to fix a live bug."""
    code = _run(monkeypatch, sha=OLD, conclusion="failure", head=HEAD,
                failures={RED_TEST: "python"}, since={RED_FILE})
    out = capsys.readouterr().out
    assert code == 2
    assert "CHANGED since that run" in out


def test_a_failing_job_with_no_failed_test_is_not_blamed_on_a_test(monkeypatch, capsys):
    """A job that dies in setup has no FAILED line. Merging a test-only PR cannot fix it, and the
    script has to say so rather than print an empty failure list that reads as green."""
    code = _run(monkeypatch, sha=HEAD, conclusion="failure", head=HEAD, failures={})
    out = capsys.readouterr().out
    assert code == 1
    assert "broken STEP" in out


@pytest.mark.parametrize("head", ["", None])
def test_no_local_main_ref_does_not_fake_a_match(monkeypatch, capsys, head):
    """With no `origin/main` to compare against, the sha check cannot run. It must fall back to
    reporting the run as-is, not silently assume the run is current."""
    code = _run(monkeypatch, sha=OLD, conclusion="failure", head=head or "",
                failures={RED_TEST: "python"})
    out = capsys.readouterr().out
    assert code == 1
    assert "MAIN RED" in out
