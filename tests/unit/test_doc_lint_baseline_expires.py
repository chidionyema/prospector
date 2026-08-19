"""A suppression may not outlive the deadline written beside it.

INC-2026-08-18-doc-rot-ratchet: on 2026-08-18 `docs/doc_lint_baseline.json` held all 45 live
findings, so `doc_lint.py --check` was green while every single finding was real. The gate was
installed with the existing rot grandfathered in, nothing was scheduled to burn the baseline
down, and grandfathered became permanent. The class is a ratchet with no burn-down schedule,
which is a warning fence, and a warning fence is not a fence.

The mechanism is a per-file deadline in the baseline itself. These tests pin the two halves that
make it bite: an expired suppression fails `--check`, and `--write-baseline` cannot move a
deadline out unless the count came DOWN. Without the second half the first is a snooze button.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "scripts"))

import doc_lint  # noqa: E402


def _findings(rel: str, n: int) -> list[dict]:
    return [{"file": rel, "line": i, "kind": "missing_path", "detail": "x", "why": "y"}
            for i in range(n)]


def test_an_expired_suppression_fails_the_ratchet(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    baseline.write_text('{"docs/A.md": {"count": 3, "expires": "%s"}}' % yesterday)
    monkeypatch.setattr(doc_lint, "BASELINE_PATH", baseline)

    ok, messages = doc_lint.check_ratchet(_findings("docs/A.md", 3))

    assert not ok, "a suppression past its burn-down date must fail, not pass on the count"
    assert any(yesterday in m for m in messages), messages


def test_an_expired_suppression_fails_even_outside_the_scope(tmp_path, monkeypatch):
    """`scope` spares a doc this branch did not touch. A deadline is not spared.

    A deadline is neither new nor a surprise: it was written into the baseline weeks earlier and
    the file names the day. If it were reported and not fatal, a doc nobody happens to edit would
    rot forever, which is the failure the deadline exists to end.
    """
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"docs/A.md": {"count": 3, "expires": "2020-01-01"}}')
    monkeypatch.setattr(doc_lint, "BASELINE_PATH", baseline)

    ok, _ = doc_lint.check_ratchet(_findings("docs/A.md", 3), scope={"docs/B.md"})

    assert not ok


def test_a_live_deadline_still_passes(tmp_path, monkeypatch):
    """The guard above must not have turned the ratchet into one that always fires."""
    baseline = tmp_path / "baseline.json"
    later = (date.today() + timedelta(days=30)).isoformat()
    baseline.write_text('{"docs/A.md": {"count": 3, "expires": "%s"}}' % later)
    monkeypatch.setattr(doc_lint, "BASELINE_PATH", baseline)

    ok, _ = doc_lint.check_ratchet(_findings("docs/A.md", 3))

    assert ok


def test_an_undated_entry_is_refused(tmp_path, monkeypatch):
    """The old shape is readable, so nothing crashes, and it is not acceptable.

    A hand-edited entry with the date stripped out is the obvious dodge, and it would otherwise
    restore exactly the pre-incident behaviour.
    """
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"docs/A.md": 3}')
    monkeypatch.setattr(doc_lint, "BASELINE_PATH", baseline)

    ok, messages = doc_lint.check_ratchet(_findings("docs/A.md", 3))

    assert not ok
    assert any("no burn-down date" in m for m in messages), messages


def test_re_baselining_cannot_push_a_deadline_out_without_an_improvement():
    """This is the half that makes the deadline mean anything.

    Re-running `--write-baseline` on the deadline must not buy another month. It only buys one by
    getting the count down, which is what "burn-down" means.
    """
    today = date(2026, 8, 19)
    previous = {"docs/A.md": (3, "2026-09-01"), "docs/B.md": (3, "2026-09-01")}

    due = doc_lint.due_dates({"docs/A.md": 3, "docs/B.md": 2}, previous, today)

    assert due["docs/A.md"] == "2026-09-01", "no improvement, so no new deadline"
    assert due["docs/B.md"] > "2026-09-01", "the count came down, so the doc earned a fresh one"


def test_a_worse_count_does_not_earn_a_fresh_deadline():
    """Going backwards is not an improvement, and must not reset the clock either."""
    due = doc_lint.due_dates({"docs/A.md": 9}, {"docs/A.md": (3, "2026-09-01")}, date(2026, 8, 19))

    assert due["docs/A.md"] == "2026-09-01"


def test_deadlines_are_staggered_so_they_do_not_all_land_on_one_day():
    counts = {"docs/A.md": 1, "docs/B.md": 2, "docs/C.md": 3}

    due = doc_lint.due_dates(counts, {}, date(2026, 8, 19))

    assert len(set(due.values())) == 3, due
    # Cheapest first: the doc with the fewest findings is the one that comes due soonest.
    assert due["docs/A.md"] < due["docs/B.md"] < due["docs/C.md"]


def test_the_committed_baseline_has_a_deadline_on_every_entry():
    """The real file, not a fixture. An entry with no date is the gate turned off for that doc."""
    raw = doc_lint.json.loads(doc_lint.BASELINE_PATH.read_text())

    undated = sorted(rel for rel, v in raw.items()
                     if not isinstance(v, dict) or not v.get("expires"))

    assert not undated, (
        f"{len(undated)} baselined doc(s) have no burn-down date: {undated}. "
        "Run `python3 scripts/doc_lint.py --write-baseline`.")
