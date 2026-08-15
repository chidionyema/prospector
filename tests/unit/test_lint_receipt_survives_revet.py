"""The stale-decision sweep must remove ONLY decision files.

`Store.save` deletes the previous decision's JSON so a re-vet cannot leave two verdicts on
disk for one candidate. It globbed `{cid}.*.json`, which also matched the publish receipt
`{cid}.lint.json` (`bridge.py:1102`) — so every re-vet after a publish destroyed the record
of WHY a pack was held off the shelf, and `tools/verify_pass_shelf_coverage.py` then reported
that pack as "never published".

Measured 2026-08-15: 3 of 11 stranded passes were mislabelled this way. Each had a listing
receipt written minutes BEFORE the dossier that its re-vet rewrote, e.g.

    f99dc175e10adc78.pass.json   15 Aug 15:32   <- re-vet rewrote the dossier
    f99dc175e10adc78.json        15 Aug 15:25   <- listing receipt (publish had succeeded)
       (no .lint.json)

while the log proved the lint had run and blocked it:

    14:25:55Z ERROR EngineBridge: f99dc175e10adc78 FAILED the pack lint (['leads with a
    coined product name 'PlatformAlpha'...', 'names no buyer...']); publishing UNLISTED

This pins BOTH directions: the receipt survives, and the stale verdict is still swept. A fix
that simply stopped deleting would trade a lost receipt for a double-counted dossier.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.models import Candidate, Decision, Dossier
from prospector.store import Store


def _store(tmp_path) -> Store:
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    return Store(cfg)


def test_revet_sweeps_the_stale_decision_but_keeps_the_lint_receipt(tmp_path):
    store = _store(tmp_path)
    cand = Candidate(title="T", one_liner="x")
    cid = cand.candidate_id
    dossiers = tmp_path / "dossiers"

    # First vet PASSes; publish then writes its lint receipt beside the dossier.
    store.save(Dossier(candidate=cand, decision=Decision.PASS))
    receipt = dossiers / f"{cid}.lint.json"
    receipt.write_text('{"errors": ["shelf_copy"]}', encoding="utf-8")

    # A re-vet flips the decision, which is what runs the sweep.
    store.save(Dossier(candidate=cand, decision=Decision.KILL))

    assert receipt.exists(), (
        "publish receipt was destroyed by the stale-decision sweep; the pack will report "
        "as 'never published' when it was in fact published UNLISTED"
    )
    assert not (dossiers / f"{cid}.pass.json").exists(), "stale decision file was not swept"
    assert (dossiers / f"{cid}.kill.json").exists()


@pytest.mark.parametrize("decision", list(Decision))
def test_sweep_covers_every_decision_value(tmp_path, decision):
    """The suffix set is derived from the Decision enum, so adding a decision cannot
    silently reintroduce either failure — a wide sweep that eats receipts, or a narrow
    one that leaks a stale verdict."""
    store = _store(tmp_path)
    cand = Candidate(title="T", one_liner="x")
    cid = cand.candidate_id
    dossiers = tmp_path / "dossiers"

    store.save(Dossier(candidate=cand, decision=decision))
    written = dossiers / f"{cid}.{decision.value}.json"
    assert written.exists()

    # Any OTHER decision, saved second, must displace the first.
    other = next(d for d in Decision if d is not decision)
    store.save(Dossier(candidate=cand, decision=other))
    assert not written.exists(), f"stale {decision.value} survived a re-vet to {other.value}"
    assert (dossiers / f"{cid}.{other.value}.json").exists()


def test_sweep_does_not_touch_another_candidates_files(tmp_path):
    store = _store(tmp_path)
    mine = Candidate(title="A", one_liner="x")
    theirs = Candidate(title="B", one_liner="y")
    dossiers = tmp_path / "dossiers"

    store.save(Dossier(candidate=theirs, decision=Decision.PASS))
    store.save(Dossier(candidate=mine, decision=Decision.PASS))
    store.save(Dossier(candidate=mine, decision=Decision.KILL))

    assert (dossiers / f"{theirs.candidate_id}.pass.json").exists()
