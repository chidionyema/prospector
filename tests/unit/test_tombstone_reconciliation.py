"""A row whose dossier is gone is history, not work.

The index and the disk can disagree. On the live store 2026-08-06, 189 of 1594 rows pointed
at a file that was not there (all created 2026-06-13..06-21, a manual event that is over).
Two consequences had to be fixed without deleting the rulings:

  * 45 were DEFERs, and the bounded drain takes oldest-first — so it re-selected and re-skipped
    the same dead rows every tick, and reported a backlog 46 larger than the work that existed.
  * 9 were PASSes whose files had been MOVED to store/dossiers/quarantine_ungrounded/ — voided
    for being ungrounded — with the index still calling them PASS.

`Store.tombstone` records "recorded, not workable". Readers that ACT on rows skip tombstoned
ones; readers that COUNT history still see them.
"""
from __future__ import annotations

from pathlib import Path

from prospector.adaptive import get_exemplars
from prospector.config import load_config
from prospector.models import Candidate, Decision, Dossier, ScoreResult
from prospector.store import Store


def _store(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    return Store(cfg)


def _save(store, cid, decision, *, composite=2.0, provisional=False):
    score = ScoreResult(scores={}, justification={}, composite=composite)
    d = Dossier(candidate=Candidate(title=f"title-{cid}", one_liner=f"one-liner-{cid}"),
                decision=decision, score=score, model_version="t", created_at="t")
    d.candidate.candidate_id = cid
    d.provisional = provisional
    return store.save(d)


def test_tombstone_marks_without_deleting(tmp_path):
    """The ruling stays in the catalogue — history must survive reconciliation."""
    store = _store(tmp_path)
    _save(store, "gone", Decision.DEFER)

    assert store.tombstone("gone", "dossier_missing") is True

    rows = {r["candidate_id"]: r for r in store.all()}
    assert "gone" in rows, "tombstoning must not delete the row"
    assert rows["gone"]["tombstone"] == "dossier_missing"
    assert rows["gone"]["decision"] == "defer", "decision is untouched unless asked"


def test_tombstone_returns_false_for_unknown_row(tmp_path):
    store = _store(tmp_path)
    assert store.tombstone("nope", "dossier_missing") is False


def test_tombstone_can_repoint_and_reclassify(tmp_path):
    """The quarantine case: the file moved, so the row is re-pointed AND voided at once."""
    store = _store(tmp_path)
    original = _save(store, "moved", Decision.PASS, composite=9.9)
    quarantine = tmp_path / "dossiers" / "quarantine_ungrounded"
    quarantine.mkdir(parents=True, exist_ok=True)
    relocated = quarantine / Path(original).name
    Path(original).rename(relocated)

    store.tombstone("moved", "quarantined_ungrounded",
                    path=str(relocated), decision=Decision.KILL.value)

    row = {r["candidate_id"]: r for r in store.all()}["moved"]
    assert row["decision"] == "kill", "an ungrounded PASS must not stay a PASS"
    assert Path(row["path"]).exists(), "the row must point at the file that does exist"
    assert store.get("moved") is not None, "re-pointing makes the dossier readable again"


def test_tombstoned_row_is_not_an_exemplar_even_though_the_file_exists(tmp_path):
    """Readable is not the same as usable — the tombstone is the reason it must not teach.

    This is the case the file-presence check alone cannot catch: after reconciliation the
    quarantined dossier is retrievable again.
    """
    store = _store(tmp_path)
    _save(store, "grounded", Decision.PASS, composite=2.0)
    original = _save(store, "voided", Decision.PASS, composite=9.9)
    quarantine = tmp_path / "dossiers" / "quarantine_ungrounded"
    quarantine.mkdir(parents=True, exist_ok=True)
    relocated = quarantine / Path(original).name
    Path(original).rename(relocated)
    store.tombstone("voided", "quarantined_ungrounded", path=str(relocated))

    assert store.get("voided") is not None, "precondition: the dossier IS readable"
    out = get_exemplars(store)
    assert "title-voided" not in out
    assert "title-grounded" in out


def test_resaving_a_dossier_clears_the_tombstone(tmp_path):
    """Documented consequence of _UPSERT being INSERT OR REPLACE.

    A tombstone is 'there is nothing behind this row', not a permanent ban. If the engine
    writes a real dossier for the candidate again, the row is workable again.
    """
    store = _store(tmp_path)
    _save(store, "back", Decision.DEFER)
    store.tombstone("back", "dossier_missing")
    assert {r["candidate_id"]: r for r in store.all()}["back"]["tombstone"] is not None

    _save(store, "back", Decision.KILL)

    assert {r["candidate_id"]: r for r in store.all()}["back"]["tombstone"] is None
