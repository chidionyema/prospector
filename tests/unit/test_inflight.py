"""The in-flight ledger: work a process is holding, so killing the process cannot lose it.

The defect these pin, measured 2026-08-17 on the live store: 12 candidates had a `candidate_start`
and no `candidate_done` from a process that no longer exists, and 10 of the 12 had NO index row
and NO dossier. `run.drainable()` works from index rows, so the drain could never see them. They
were not backlogged; they were gone.
"""
from __future__ import annotations

import json

import pytest

from prospector import inflight
from prospector.models import Candidate


def _pid(store_root, cand) -> int:
    return json.loads(
        (inflight.directory(store_root) / f"{cand.candidate_id}.json").read_text())["pid"]


def _cand(title: str = "A thing") -> Candidate:
    return Candidate(title=title, one_liner="does a thing", hypothesis="a problem",
                     who_pays="someone", why_now="now")


def test_open_then_close_leaves_nothing_behind(tmp_path):
    cand = _cand()
    assert inflight.open_(tmp_path, cand, run_id="r1", label="lane") is not None
    # `alive` is injected: the real probe reads THIS process's command line, and a test that
    # depends on what pytest happens to be called is a test of the harness, not of the ledger.
    assert inflight.survey(tmp_path, alive={_pid(tmp_path, cand): True})["counts"]["live"] == 1

    assert inflight.close(tmp_path, cand.candidate_id) is True
    assert inflight.survey(tmp_path)["counts"] == {"live": 0, "orphaned": 0, "unreadable": 0}
    # Closing twice is not an error: a recovery pass and the vet itself can both reach it.
    assert inflight.close(tmp_path, cand.candidate_id) is False


def test_a_record_whose_process_is_gone_is_an_orphan(tmp_path):
    """THE WHOLE POINT. A live process holds work; a dead one abandoned it."""
    cand = _cand()
    inflight.open_(tmp_path, cand)
    pid = json.loads((inflight.directory(tmp_path) / f"{cand.candidate_id}.json").read_text())["pid"]

    assert inflight.orphans(tmp_path, alive={pid: True}) == []

    orphaned = inflight.orphans(tmp_path, alive={pid: False})
    assert [r["candidate_id"] for r in orphaned] == [cand.candidate_id]
    assert orphaned[0]["why"] == "the process that held it is gone"


def test_a_live_pid_holding_work_for_days_is_still_reported(tmp_path):
    """macOS reuses pids, so `alive` alone would let a dead run read as busy forever."""
    cand = _cand()
    inflight.open_(tmp_path, cand)
    rec = json.loads((inflight.directory(tmp_path) / f"{cand.candidate_id}.json").read_text())

    later = rec["started_at"] + inflight.STALE_S + 1.0
    orphaned = inflight.orphans(tmp_path, now=later, alive={rec["pid"]: True})
    assert len(orphaned) == 1
    assert "longer than any vet takes" in orphaned[0]["why"]


def test_a_torn_record_is_reported_not_raised(tmp_path):
    """A half-written file is information. Crashing on it would hide every other record."""
    inflight.open_(tmp_path, _cand())
    (inflight.directory(tmp_path) / "junk.json").write_text("{not json")

    view = inflight.survey(tmp_path, alive={})
    assert view["counts"]["unreadable"] == 1
    assert view["counts"]["live"] + view["counts"]["orphaned"] == 1


def test_candidate_of_rebuilds_the_idea_the_dead_process_was_holding(tmp_path):
    """The recovery is worthless if the record cannot produce a vettable Candidate."""
    cand = _cand("Rebuildable")
    inflight.open_(tmp_path, cand)
    rec = json.loads((inflight.directory(tmp_path) / f"{cand.candidate_id}.json").read_text())

    back = inflight.candidate_of(rec)
    assert back is not None
    assert back.title == "Rebuildable"
    assert back.candidate_id == cand.candidate_id


def test_candidate_of_returns_none_rather_than_raising_on_a_ruined_record(tmp_path):
    assert inflight.candidate_of({"candidate_id": "x", "candidate": "not a dict"}) is None


def test_only_one_drain_can_claim_the_same_orphan(tmp_path):
    """Two drains run concurrently in this repo by design, so the claim must be exclusive.

    `Store.claim` cannot do this job — it updates an index row, and the orphans that matter are
    exactly the ones with no index row.
    """
    cand = _cand()
    inflight.open_(tmp_path, cand)

    assert inflight.claim(tmp_path, cand.candidate_id, "drain-a") is True
    assert inflight.claim(tmp_path, cand.candidate_id, "drain-b") is False

    assert inflight.release_claim(tmp_path, cand.candidate_id) is True
    assert inflight.claim(tmp_path, cand.candidate_id, "drain-b") is True


def test_a_claim_from_a_process_that_died_holding_it_expires(tmp_path):
    """Otherwise a recoverer that is itself killed strands the candidate a second time."""
    cand = _cand()
    inflight.open_(tmp_path, cand)
    assert inflight.claim(tmp_path, cand.candidate_id, "dead-drain", now=1000.0) is True

    assert inflight.claim(tmp_path, cand.candidate_id, "next-drain",
                          now=1000.0 + inflight.RECOVER_TTL_S - 1) is False
    assert inflight.claim(tmp_path, cand.candidate_id, "next-drain",
                          now=1000.0 + inflight.RECOVER_TTL_S + 1) is True


def test_a_claim_marker_is_not_mistaken_for_work(tmp_path):
    cand = _cand()
    inflight.open_(tmp_path, cand)
    inflight.claim(tmp_path, cand.candidate_id, "drain-a")

    view = inflight.survey(tmp_path, alive={})
    assert view["counts"]["unreadable"] == 0
    assert view["counts"]["live"] + view["counts"]["orphaned"] == 1


def test_open_never_raises_even_when_the_ledger_cannot_be_written(tmp_path):
    """The cure must not cause the disease: a vet must run even if its recovery note cannot.

    `store/` is a file here, so `mkdir` inside it fails.
    """
    blocked = tmp_path / "store"
    blocked.write_text("not a directory")
    assert inflight.open_(blocked, _cand()) is None


def test_an_unusable_candidate_id_cannot_escape_the_directory(tmp_path):
    with pytest.raises(ValueError):
        inflight._path(tmp_path, "../..")


def test_survey_on_a_store_with_no_ledger_is_empty_not_an_error(tmp_path):
    assert inflight.survey(tmp_path)["counts"] == {"live": 0, "orphaned": 0, "unreadable": 0}


def test_a_probe_that_cannot_answer_leaves_the_work_alone(tmp_path):
    """Unknown must never be recovered. Re-vetting live work pays twice and can race a publish."""
    cand = _cand()
    inflight.open_(tmp_path, cand)

    view = inflight.survey(tmp_path, alive={_pid(tmp_path, cand): None})
    assert view["counts"] == {"live": 1, "orphaned": 0, "unreadable": 0}
    assert "safe direction" in view["live"][0]["note"]
