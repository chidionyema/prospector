"""An exemplar may only be built from a grounded, moat-ruled dossier.

`get_exemplars` feeds the top PASSes and most decisive KILLs back into generation as
"this is what a winner looks like". Two classes of index row could reach that slot and
must not:

  1. A row whose dossier JSON is gone. `store.get()` returns None (store.py:215) and the
     builder falls back to the INDEX row's title/one_liner, so the row still produced a
     fully-formed exemplar. On the live store 2026-08-06 that path was reachable by the
     nine PASSes whose files were MOVED to store/dossiers/quarantine_ungrounded/ without
     updating the index — i.e. rulings quarantined precisely for being ungrounded.
  2. A provisional row — ruled by the cheap tail after moat exhaustion, never publishable,
     auto re-vetted. Steering the generator with one launders an unverified verdict into
     every future batch.
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


def _pass(store, cid, composite, *, provisional=False):
    score = ScoreResult(scores={}, justification={}, composite=composite)
    d = Dossier(candidate=Candidate(title=f"title-{cid}", one_liner=f"one-liner-{cid}"),
                decision=Decision.PASS, score=score, model_version="t", created_at="t")
    d.candidate.candidate_id = cid
    d.provisional = provisional
    return store.save(d)


def _kill(store, cid, confidence):
    from prospector.models import AdversarialResult
    d = Dossier(candidate=Candidate(title=f"title-{cid}", one_liner=f"one-liner-{cid}"),
                decision=Decision.KILL, gate_fired="adversarial_decisive",
                adversarial=AdversarialResult(kill_case="k", decisive=True,
                                              confidence=confidence),
                model_version="t", created_at="t")
    d.candidate.candidate_id = cid
    return store.save(d)


def test_pass_with_no_dossier_on_disk_is_not_an_exemplar(tmp_path):
    """The quarantine case: file removed, index row left behind, top composite.

    Without the eligibility filter the builder falls back to the index row and the
    highest-scoring row wins the slot — which is exactly the ungrounded one.
    """
    store = _store(tmp_path)
    _pass(store, "grounded", 2.0)
    orphan_path = _pass(store, "quarantined", 9.9)

    assert "title-quarantined" in get_exemplars(store), (
        "precondition: while the file is on disk the high scorer IS the top exemplar")

    Path(orphan_path).unlink()

    out = get_exemplars(store)
    assert "title-quarantined" not in out
    assert "one-liner-quarantined" not in out, "index-row fallback leaked the orphan"
    assert "title-grounded" in out, "the grounded pass must still be offered"


def test_provisional_pass_is_not_an_exemplar(tmp_path):
    """A provisional ruling never publishes, so it never teaches either."""
    store = _store(tmp_path)
    _pass(store, "grounded", 2.0)
    _pass(store, "cheaptail", 9.9, provisional=True)

    out = get_exemplars(store)
    assert "title-cheaptail" not in out
    assert "title-grounded" in out


def test_kill_exemplars_apply_the_same_bar(tmp_path):
    """The KILL side has the identical index-row fallback and 135 orphaned rows."""
    store = _store(tmp_path)
    _kill(store, "grounded", 0.5)
    orphan_path = _kill(store, "vanished", 1.0)
    Path(orphan_path).unlink()

    out = get_exemplars(store)
    assert "title-vanished" not in out
    assert "title-grounded" in out


def test_no_eligible_rows_yields_no_exemplar_block(tmp_path):
    """Filtering everything out must return "", not a header with an empty list."""
    store = _store(tmp_path)
    orphan_path = _pass(store, "quarantined", 9.9)
    Path(orphan_path).unlink()

    assert get_exemplars(store) == ""
