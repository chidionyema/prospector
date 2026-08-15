"""An unreadable jobs.json must not be quietly overwritten with an empty history.

`_load_jobs_from` returns `[]` for both "no jobs yet" and "the file is corrupt".  For a
reader that is survivable; for the WRITER it is destructive.  `_save_jobs_to` re-reads the
file to merge concurrent writers' rows before `os.replace`, so a swallowed read error made
the merge see zero rows on disk and replace the file with only what this process held in
memory — the run history deleting itself, and the cockpit then showing "no runs", which is
also exactly what a fresh install shows.

Pinned here: the reader can now tell the two apart (`_read_jobs_file` returns an `ok` flag),
and the writer preserves the bytes it could not parse instead of replacing them.
"""
from __future__ import annotations

import json

from prospector.control_center import runner


def test_read_jobs_file_separates_absent_from_corrupt(tmp_path):
    path = tmp_path / "jobs.json"

    # Absent — an empty history is the honest answer.
    assert runner._read_jobs_file(path) == ([], True)

    # Present and valid.
    path.write_text(json.dumps([{"job_id": "j1"}]), encoding="utf-8")
    jobs, ok = runner._read_jobs_file(path)
    assert ok is True and jobs == [{"job_id": "j1"}]

    # Present and corrupt — same empty list, but no longer indistinguishable.
    path.write_text("[{truncated", encoding="utf-8")
    assert runner._read_jobs_file(path) == ([], False)

    # Present and the wrong shape (a dict where a list belongs) is corruption too.
    path.write_text('{"job_id": "j1"}', encoding="utf-8")
    assert runner._read_jobs_file(path) == ([], False)

    # The old reader keeps its contract for every caller that only wants the rows.
    assert runner._load_jobs_from(path) == []


def test_saving_over_an_unreadable_jobs_file_preserves_it(tmp_path, monkeypatch):
    path = tmp_path / "jobs.json"
    corrupt = '[{"job_id": "history-that-must-not-vanish", '
    path.write_text(corrupt, encoding="utf-8")

    # Take the production merge path (that is where the destructive read lives).
    monkeypatch.setattr(runner, "_production_jobs_file", lambda: path.resolve())
    monkeypatch.setattr(runner, "_looks_like_pytest_path", lambda p: False)

    runner._save_jobs_to(path, [{"job_id": "new", "status": "running"}])

    # The new row landed …
    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"job_id": "new", "status": "running"}
    ]
    # … and the bytes we could not parse are still on disk, not silently discarded.
    preserved = list(tmp_path.glob("jobs.json.corrupt.*"))
    assert len(preserved) == 1, f"expected the unreadable file to be kept, saw {preserved}"
    assert preserved[0].read_text(encoding="utf-8") == corrupt


def test_a_readable_jobs_file_is_still_merged_not_quarantined(tmp_path, monkeypatch):
    """The guard must fire on corruption only — a normal save still merges in place."""
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([{"job_id": "old", "status": "succeeded"}]), encoding="utf-8")

    monkeypatch.setattr(runner, "_production_jobs_file", lambda: path.resolve())
    monkeypatch.setattr(runner, "_looks_like_pytest_path", lambda p: False)

    runner._save_jobs_to(path, [{"job_id": "new", "status": "running"}])

    ids = {j["job_id"] for j in json.loads(path.read_text(encoding="utf-8"))}
    assert ids == {"old", "new"}
    assert list(tmp_path.glob("jobs.json.corrupt.*")) == []
