"""`scripts/process_audit.py` is what tells this estate its docs have drifted. It must not die.

Measured 2026-08-20: it did. `_grade_doc_lint_baseline` called `min()` on an empty
`docs/doc_lint_baseline.json` and raised `ValueError: min() iterable argument is empty`. That
file is `{}` on origin/main, so it raised on every run -- including the daily
`com.prospector.process-audit` launchd job, which had been printing a traceback instead of a
grade for as long as the baseline has been empty.

Two separate defects, so two separate sets of tests:

  1. The empty case was unhandled, and it is the BEST state the ratchet can be in -- zero
     suppressions left to expire. The audit crashed on success.

  2. The nine graders were called while the section list was being BUILT, so the first one to
     raise took the other eight with it. That is what turned a one-line bug into total silence.

The second is the one that matters. An audit that crashes reports nothing, and reporting
nothing looks exactly like reporting no problems -- both exit non-zero, so not even the exit
status separated them. These tests pin the isolation, not the arithmetic.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "process_audit_isolation_under_test", ROOT / "scripts" / "process_audit.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit():
    return _load()


# --- defect 1: the empty case ------------------------------------------------------------


def test_an_empty_baseline_grades_ok_instead_of_raising(audit, tmp_path, monkeypatch):
    """Zero suppressions is the goal state, not an error."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "doc_lint_baseline.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    grade, name, detail = audit._grade_doc_lint_baseline()

    assert grade == audit.OK, f"an empty baseline graded {grade!r}: {detail}"
    assert "0 doc" in detail


def test_the_real_baseline_in_this_repo_does_not_raise(audit):
    """The regression as it actually shipped, against the file on disk rather than a fixture.

    `docs/doc_lint_baseline.json` is `{}` today. If a fixture-only test had existed it would
    have passed while the estate's own file killed every run, so this one reads the real file.
    """
    grade, _name, detail = audit._grade_doc_lint_baseline()
    assert grade in (audit.OK, audit.WARN, audit.BAD), detail


def test_a_populated_baseline_still_reports_the_soonest_burn_down(audit, tmp_path, monkeypatch):
    """The empty-case fix must not have flattened the case that was already working."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "doc_lint_baseline.json").write_text(
        json.dumps({"docs/a.md": {"expires": "2099-12-31"},
                    "docs/b.md": {"expires": "2099-06-30"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    grade, _name, detail = audit._grade_doc_lint_baseline()

    assert grade == audit.OK, detail
    assert "2099-06-30" in detail, f"reported the wrong soonest date: {detail}"


# --- defect 2: one crashing grader must not silence the other eight -----------------------


def test_a_crashing_grader_becomes_a_fail_row(audit):
    def boom():
        raise ValueError("min() iterable argument is empty")

    title, rows = audit._section("enforcement", boom)

    assert title == "enforcement"
    assert len(rows) == 1
    grade, name, detail = rows[0]
    assert grade == audit.BAD, "a grader that crashed was not graded BAD"
    assert "ValueError" in detail, "the exception type is not in the row, so nobody can debug it"
    assert "graded NOTHING" in detail, (
        "the row does not say the section is UNKNOWN rather than clean, which is the whole "
        "distinction this fix exists to make"
    )


def test_a_working_grader_is_passed_through_untouched(audit):
    rows = [(audit.OK, "a", "fine"), (audit.WARN, "b", "hmm")]
    assert audit._section("t", lambda: rows) == ("t", rows)


def test_one_dead_grader_does_not_stop_the_others(audit):
    """The actual failure mode, reproduced: nine graders, one raises, eight must still report."""
    graders = [(f"s{i}", (lambda: [(audit.OK, "row", "fine")])) for i in range(9)]
    graders[5] = ("s5", lambda: (_ for _ in ()).throw(RuntimeError("dead")))

    sections = [audit._section(t, g) for t, g in graders]

    assert len(sections) == 9, "a raising grader truncated the section list"
    bad = [t for t, rows in sections if any(g == audit.BAD for g, _, _ in rows)]
    assert bad == ["s5"], f"expected only s5 to be BAD, got {bad}"
    ok = [t for t, rows in sections if all(g == audit.OK for g, _, _ in rows)]
    assert len(ok) == 8, "the eight healthy graders did not all report"
