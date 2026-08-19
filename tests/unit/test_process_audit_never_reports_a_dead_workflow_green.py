"""`process_audit.grade_workflows` must never grade a DEAD workflow as ok.

A workflow GitHub cannot START fails with zero jobs, no log, no annotation and no red check.
`scripts/ci-autoscale.yml` was in that state for 30 consecutive runs and the dashboard read it
as ordinary red, so nobody looked. These tests pin the mapping from `workflow_health.grade()`'s
verdicts onto the three grades the ops dashboard renders, and pin the two ways this function
used to lie: a workflow GitHub knows nothing about, and an unreachable GitHub.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "process_audit_under_test", ROOT / "scripts" / "process_audit.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(*rows):
    return {"workflows": list(rows)}


def _row(name, verdict, runs_graded=5):
    return {
        "path": f".github/workflows/{name}",
        "name": name,
        "verdict": verdict,
        "runs_graded": runs_graded,
    }


def _grade(monkeypatch, pa, report, files=("ci.yml",)):
    """Run grade_workflows against a fixed workflow-health report and a fixed file list."""

    class _Dir:
        def glob(self, _pattern):
            return [pathlib.Path(f".github/workflows/{n}") for n in files]

    monkeypatch.setattr(pa, "WORKFLOW_DIR", _Dir())

    fake = type(
        "wfh",
        (),
        {
            "grade": staticmethod(lambda *a, **k: report),
            "_repo": staticmethod(lambda *a, **k: "o/r"),
        },
    )

    def _fake_loader(_name, _path):
        class _Spec:
            loader = type(
                "L", (), {"exec_module": staticmethod(lambda _m: None)}
            )()

        return _Spec()

    monkeypatch.setattr(
        pa.importlib.util, "spec_from_file_location", lambda *a, **k: _fake_loader(*a[:2])
    )
    monkeypatch.setattr(pa.importlib.util, "module_from_spec", lambda _s: fake)
    return pa.grade_workflows(set(files))


def test_a_dead_workflow_is_bad_and_says_so(monkeypatch):
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("ci.yml", "DEAD — every run produced zero jobs")))
    grade, name, detail = rows[0]
    assert grade == pa.BAD, rows
    assert name == "ci.yml"
    assert "DEAD" in detail and "ZERO jobs" in detail
    assert "actionlint" in detail, "the row must name the command that diagnoses it"


def test_failing_every_run_is_bad_but_not_dead(monkeypatch):
    """A workflow that ran and failed did real work. Calling it DEAD sends the reader to
    actionlint, which will find nothing, and the real failure stays unread."""
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("ci.yml", "failing every run")))
    grade, _, detail = rows[0]
    assert grade == pa.BAD
    assert "FAILING" in detail
    assert "DEAD" not in detail


def test_one_failing_run_reads_as_run_not_runs(monkeypatch):
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("ci.yml", "failing every run", runs_graded=1)))
    assert "the last 1 run all failed" in rows[0][2]


def test_partially_jobless_is_degraded(monkeypatch):
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("ci.yml", "3/5 runs produced zero jobs")))
    grade, _, detail = rows[0]
    assert grade == pa.BAD
    assert "DEGRADED" in detail


def test_a_healthy_documented_workflow_is_ok(monkeypatch):
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("ci.yml", "ok")))
    assert rows[0][0] == pa.OK
    assert "ok" in rows[0][2]


def test_a_file_github_has_no_workflow_for_is_warn_never_ok(monkeypatch):
    """A workflow file GitHub has never registered is unproven, not proven good."""
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("other.yml", "ok")))
    grade, name, detail = rows[0]
    assert (grade, name) == (pa.WARN, "ci.yml")
    assert "no workflow for this file" in detail


def test_github_unreachable_is_warn_on_every_file_never_green(monkeypatch):
    """`could not ask GitHub` must never be silently green. An outage that reads as healthy is
    the same defect this whole file exists to stop, one level up."""
    pa = _load()

    class _Dir:
        def glob(self, _pattern):
            return [pathlib.Path(".github/workflows/ci.yml")]

    monkeypatch.setattr(pa, "WORKFLOW_DIR", _Dir())
    boom = type(
        "wfh",
        (),
        {
            "grade": staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gh: 401"))),
            "_repo": staticmethod(lambda *a, **k: "o/r"),
        },
    )
    monkeypatch.setattr(
        pa.importlib.util,
        "spec_from_file_location",
        lambda *a, **k: type(
            "S", (), {"loader": type("L", (), {"exec_module": staticmethod(lambda _m: None)})()}
        )(),
    )
    monkeypatch.setattr(pa.importlib.util, "module_from_spec", lambda _s: boom)

    rows = pa.grade_workflows({"ci.yml"})
    assert rows and all(g == pa.WARN for g, _, _ in rows), rows
    assert "could not ask GitHub" in rows[0][2]
    assert "gh: 401" in rows[0][2]


@pytest.mark.parametrize(
    "verdict,expected_substring",
    [
        ("DEAD — every run produced zero jobs", "DEAD"),
        ("failing every run", "FAILING"),
        ("2/5 runs produced zero jobs", "DEGRADED"),
        ("no recent runs", "no runs at all"),
    ],
)
def test_every_unhealthy_verdict_reaches_the_dashboard_intact(
    monkeypatch, verdict, expected_substring
):
    pa = _load()
    rows = _grade(monkeypatch, pa, _report(_row("ci.yml", verdict)))
    assert expected_substring in rows[0][2], rows
    assert rows[0][0] != pa.OK, "an unhealthy verdict must never render as ok"
