"""Guards for the human verification layer (programme doc §33.8, item 33-G).

Every test here pins one of the four ways this layer could be fake while looking real: verification
by default, a receipt that outlives the prose it reviewed, a queue that silently reads empty, and an
editable audit trail. The happy path is the least interesting thing in this file.
"""
from __future__ import annotations

import json

import pytest

from prospector.human_review import (
    ACTIONS,
    SELLABLE,
    STATUS_CLEAN,
    STATUS_PENDING,
    STATUS_STALE,
    STATUS_UNREVIEWED,
    STATUS_UNTRACED,
    STATUS_VERIFIED,
    Item,
    fingerprint,
    is_sellable,
    is_sellable_checks,
    is_traced,
    load_receipt,
    queue_from_checks,
    queue_items,
    receipt_path,
    record_decision,
    root_for,
    status,
    status_for_checks,
)
from prospector.models import CheckResult, Verdict

PACK = "08b22037fc2afc07"  # a real live pack id from the §33 measurement


def _check(name: str, figs: list[str]) -> CheckResult:
    return CheckResult(check_name=name, verdict=Verdict.SUPPORTED, confidence=0.8,
                       rationale="ok", untraceable_figures=figs)


def _decide(root, items, key, action="repaired", reviewer="founder", note="n"):
    return record_decision(PACK, items, key, action, reviewer, note,
                           now="2026-08-13T12:00:00Z", root=root)


# ---------------------------------------------------------------------------
# The queue: both input shapes, because one silently returning [] reads as `clean`
# ---------------------------------------------------------------------------

def test_queue_is_identical_from_objects_and_from_stored_dossier_json():
    checks = [_check("payer_solvency", ["320", "49"]), _check("legality", ["53601"])]
    from_objs = queue_items(checks)
    from_json = queue_items([json.loads(json.dumps(c.to_dict())) for c in checks])
    assert [i.key for i in from_objs] == ["payer_solvency:320", "payer_solvency:49",
                                         "legality:53601"]
    assert from_json == from_objs, (
        "the dict path is how an out-of-process reviewer builds the queue; if it returns fewer "
        "items the pack reads as `clean`, which is the most dangerous wrong answer here")


def test_queue_dedupes_and_is_empty_for_clean_checks():
    assert queue_items([_check("a", []), _check("b", [])]) == []
    assert len(queue_items([_check("a", ["7000"]), _check("a", ["7000"])])) == 1


# ---------------------------------------------------------------------------
# Property 1: absence of a receipt is never verification
# ---------------------------------------------------------------------------

def test_no_figures_is_clean_and_needs_no_human(tmp_path):
    assert status(PACK, [], traced=True, root=tmp_path) == (STATUS_CLEAN, [])


def test_flagged_and_unreviewed_is_not_verified(tmp_path):
    items = queue_items([_check("payer_solvency", ["320"])])
    assert status(PACK, items, traced=True, root=tmp_path) == (STATUS_UNREVIEWED, ["payer_solvency:320"])
    assert not is_sellable(PACK, items, traced=True, root=tmp_path)


def test_partly_reviewed_is_pending_not_verified(tmp_path):
    items = queue_items([_check("payer_solvency", ["320", "49"])])
    _decide(tmp_path, items, "payer_solvency:320")
    st, outstanding = status(PACK, items, traced=True, root=tmp_path)
    assert (st, outstanding) == (STATUS_PENDING, ["payer_solvency:49"])
    assert not is_sellable(PACK, items, traced=True, root=tmp_path)


def test_all_decided_is_verified_and_sellable(tmp_path):
    items = queue_items([_check("payer_solvency", ["320", "49"])])
    _decide(tmp_path, items, "payer_solvency:320", "repaired")
    _decide(tmp_path, items, "payer_solvency:49", "dropped")
    assert status(PACK, items, traced=True, root=tmp_path) == (STATUS_VERIFIED, [])
    assert is_sellable(PACK, items, traced=True, root=tmp_path)
    assert STATUS_CLEAN in SELLABLE and STATUS_VERIFIED in SELLABLE
    assert STATUS_STALE not in SELLABLE and STATUS_PENDING not in SELLABLE


def test_a_corrupt_receipt_reads_as_unreviewed(tmp_path):
    items = queue_items([_check("payer_solvency", ["320"])])
    p = receipt_path(PACK, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert load_receipt(PACK, tmp_path) is None
    assert status(PACK, items, traced=True, root=tmp_path)[0] == STATUS_UNREVIEWED


def test_a_half_written_history_entry_certifies_nothing(tmp_path):
    items = queue_items([_check("payer_solvency", ["320"])])
    p = receipt_path(PACK, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pack_id": PACK, "fingerprint": fingerprint(items),
                             "history": [{"key": "payer_solvency:320"}]}), encoding="utf-8")
    assert status(PACK, items, traced=True, root=tmp_path)[0] == STATUS_PENDING


# ---------------------------------------------------------------------------
# Property 2: a re-vet invalidates its receipt
# ---------------------------------------------------------------------------

def test_a_revet_that_flags_a_different_figure_makes_the_receipt_stale(tmp_path):
    """The whole point of the fingerprint. A receipt must not certify prose written after it."""
    items = queue_items([_check("payer_solvency", ["320"])])
    _decide(tmp_path, items, "payer_solvency:320")
    assert status(PACK, items, traced=True, root=tmp_path)[0] == STATUS_VERIFIED

    revetted = queue_items([_check("payer_solvency", ["1200"])])  # engine ran again, new prose
    st, outstanding = status(PACK, revetted, traced=True, root=tmp_path)
    assert st == STATUS_STALE and outstanding == ["payer_solvency:1200"]
    assert not is_sellable(PACK, revetted, traced=True, root=tmp_path)


def test_a_revet_that_traces_everything_returns_to_clean_despite_the_old_receipt(tmp_path):
    """`clean` is decided before the receipt is read, so a fixed pack is not held hostage."""
    items = queue_items([_check("payer_solvency", ["320"])])
    _decide(tmp_path, items, "payer_solvency:320")
    assert status(PACK, [], traced=True, root=tmp_path) == (STATUS_CLEAN, [])


def test_fingerprint_ignores_order_but_not_content():
    a = [Item("x", "1000"), Item("y", "2000")]
    assert fingerprint(a) == fingerprint(list(reversed(a)))
    assert fingerprint(a) != fingerprint([Item("x", "1000")])


# ---------------------------------------------------------------------------
# Properties 3 and 4: `accepted` is first-class but must justify itself; history appends
# ---------------------------------------------------------------------------

def test_accepted_is_a_real_action_because_the_matcher_is_lenient_by_design(tmp_path):
    """`figure_check` over-flags on purpose, so the reviewer needs a way to say "not a claim".

    Without it, every false positive forces a lie (`repaired`) or a stall — and the queue would
    stop draining, which is how this layer dies.
    """
    assert "accepted" in ACTIONS
    items = queue_items([_check("legality", ["53601"])])
    _decide(tmp_path, items, "legality:53601", "accepted", note="a regulation number, not a claim")
    assert status(PACK, items, traced=True, root=tmp_path) == (STATUS_VERIFIED, [])


def test_accepted_without_a_note_is_refused(tmp_path):
    items = queue_items([_check("legality", ["53601"])])
    with pytest.raises(ValueError, match="requires a note"):
        record_decision(PACK, items, "legality:53601", "accepted", "founder", "",
                        now="2026-08-13T12:00:00Z", root=tmp_path)
    assert load_receipt(PACK, tmp_path) is None, "a refused decision must not create a receipt"


@pytest.mark.parametrize("kwargs,match", [
    ({"action": "looks_fine"}, "unknown action"),
    ({"reviewer": "  "}, "named reviewer"),
    ({"key": "payer_solvency:999"}, "not in the current queue"),
])
def test_a_decision_that_cannot_be_attributed_or_matched_is_refused(tmp_path, kwargs, match):
    items = queue_items([_check("payer_solvency", ["320"])])
    call = {"key": "payer_solvency:320", "action": "repaired", "reviewer": "founder", "note": "n"}
    call.update(kwargs)
    with pytest.raises(ValueError, match=match):
        record_decision(PACK, items, call["key"], call["action"], call["reviewer"], call["note"],
                        now="2026-08-13T12:00:00Z", root=tmp_path)


def test_history_appends_and_the_latest_decision_wins(tmp_path):
    items = queue_items([_check("payer_solvency", ["320"])])
    _decide(tmp_path, items, "payer_solvency:320", "accepted", note="thought it was fine")
    _decide(tmp_path, items, "payer_solvency:320", "dropped", reviewer="founder", note="on review, no")
    rec = load_receipt(PACK, tmp_path)
    assert len(rec.history) == 2, "an overwritten decision is not an audit trail"
    assert rec.current()["payer_solvency:320"].action == "dropped"
    assert rec.history[0].note == "thought it was fine"


def test_the_receipt_names_who_and_when(tmp_path):
    items = queue_items([_check("payer_solvency", ["320"])])
    _decide(tmp_path, items, "payer_solvency:320", reviewer="chidi")
    d = load_receipt(PACK, tmp_path).current()["payer_solvency:320"]
    assert (d.reviewer, d.decided_at) == ("chidi", "2026-08-13T12:00:00Z")


# ---------------------------------------------------------------------------
# Property 5: a pack the trace never ran on is NOT clean
# ---------------------------------------------------------------------------

def test_a_pre_trace_dossier_is_untraced_not_clean(tmp_path):
    """The near-miss that made `is_traced` necessary.

    All 2,011 dossiers on disk were written before `CheckResult.untraceable_figures` existed, so
    their checks carry no such key and the queue builds EMPTY. Treating that as `clean` would have
    certified as figure-traceable the very 15 packs §33 measured as dirty — the §33.1 failure
    (a promise nothing enforces) reproduced by the mechanism built to end it.
    """
    old = [{"check_name": "payer_solvency", "verdict": "supported", "rationale": "£320 a year"}]
    assert is_traced(old) is False
    items, traced = queue_from_checks(old)
    assert items == [] and traced is False
    assert status_for_checks(PACK, old, root=tmp_path) == (STATUS_UNTRACED, [])
    assert not is_sellable_checks(PACK, old, root=tmp_path)
    assert STATUS_UNTRACED not in SELLABLE


def test_a_traced_check_with_no_flags_is_clean(tmp_path):
    new = [_check("payer_solvency", []).to_dict()]
    assert is_traced(new) is True
    assert status_for_checks(PACK, new, root=tmp_path) == (STATUS_CLEAN, [])
    assert is_sellable_checks(PACK, new, root=tmp_path)


def test_zero_checks_cannot_prove_a_trace_ran(tmp_path):
    assert is_traced([]) is False
    assert status_for_checks(PACK, [], root=tmp_path) == (STATUS_UNTRACED, [])


def test_status_fails_closed_when_traced_is_forgotten(tmp_path):
    """The default is the safe answer, not the convenient one."""
    items = queue_items([_check("payer_solvency", ["320"])])
    assert status(PACK, items, root=tmp_path)[0] == STATUS_UNTRACED


def test_receipts_live_under_the_configured_store_root_not_a_hardcoded_one(tmp_path):
    class _Cfg:
        store_dir = tmp_path / "some_store"
    assert root_for(_Cfg()) == tmp_path / "some_store" / "human_review"
    assert root_for(None).as_posix().endswith("store/human_review")


# ---------------------------------------------------------------------------
# The fence: `bridge.listing_gate` is where this layer either acts or does not
# ---------------------------------------------------------------------------

def test_listing_gate_default_leaves_the_figure_fence_OFF():
    """Default True = off, deliberately: switching it on delists ~30% of the shelf.

    That is the founder's revenue decision, so the engine ships the switch, not the delisting.
    """
    from prospector.bridge import listing_gate
    passing = dict(uploaded=True, pack_complete=True, priced=True,
                   bundle_complete=True, lint_ok=True)
    assert listing_gate(**passing) is True
    assert listing_gate(**passing, figures_verified=False) is False


def test_the_figure_fence_cannot_rescue_a_pack_the_other_five_gates_reject():
    from prospector.bridge import listing_gate
    assert listing_gate(uploaded=False, pack_complete=True, priced=True, bundle_complete=True,
                        lint_ok=True, figures_verified=True) is False


def test_require_figure_verification_defaults_off_in_config():
    from prospector.config import LISTING_DEFAULTS
    assert LISTING_DEFAULTS["require_figure_verification"] is False
