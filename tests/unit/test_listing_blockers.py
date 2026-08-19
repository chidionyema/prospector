"""Backlog B1: the shelf decision must name the fence that refused, not just return False.

`bridge.listing_gate` composed six independent fences into one boolean. Nothing counted any of
them, so 108 registered packs sat off the shelf and finding out why was 108 hand investigations.
These tests pin the three ways that regresses: a fence that is not named, a report that disagrees
with the gate, and a ledger written beside the code instead of into the store.
"""
from __future__ import annotations

import inspect
import itertools
import json
from pathlib import Path

import pytest

from prospector import listing_ledger
from prospector.bridge import LISTING_FENCES, listing_blockers, listing_gate

PASSING = dict(uploaded=True, pack_complete=True, priced=True, bundle_complete=True,
               lint_ok=True, figures_verified=True)


def test_a_passing_pack_has_no_blockers():
    assert listing_blockers(**PASSING) == ()
    assert listing_gate(**PASSING) is True


@pytest.mark.parametrize("fence", LISTING_FENCES)
def test_each_fence_names_itself_when_it_refuses(fence):
    blockers = listing_blockers(**{**PASSING, fence: False})
    assert blockers == (fence,), f"{fence} refused and the decision did not say so"


def test_every_failing_fence_is_reported_not_just_the_first():
    """Kill-fast is right for the moat, where each check costs spend. Here they are all already
    computed, and stopping at the first name hides a pack that needs two fixes behind one."""
    blockers = listing_blockers(**{**PASSING, "uploaded": False, "lint_ok": False})
    assert blockers == ("uploaded", "lint_ok")


def test_blockers_come_back_in_declared_order():
    assert listing_blockers(uploaded=False, pack_complete=False, priced=False,
                            bundle_complete=False, lint_ok=False,
                            figures_verified=False) == LISTING_FENCES


@pytest.mark.parametrize("combo", list(itertools.product([True, False], repeat=6)))
def test_the_gate_and_the_report_can_never_disagree(combo):
    """All 64 states. Two expressions of one rule drift, and the drift is a pack that lists while
    a report calls it blocked, or the reverse."""
    kwargs = dict(zip(LISTING_FENCES, combo))
    assert listing_gate(**kwargs) is (listing_blockers(**kwargs) == ())


def test_every_gate_operand_is_a_named_fence():
    """A seventh fence added to the signature but not to LISTING_FENCES is invisible in every
    report — it would silently block packs for a reason no query can return."""
    params = [p for p in inspect.signature(listing_gate).parameters if p != "self"]
    assert set(params) == set(LISTING_FENCES)
    assert set(inspect.signature(listing_blockers).parameters) == set(LISTING_FENCES)


# ---- the ledger ------------------------------------------------------------------------

def test_the_trail_is_written_into_the_store_not_beside_the_code(tmp_path, monkeypatch):
    """On the engine the code is at /app and the store is a volume at /data/store. A `__file__`
    path writes the trail where the console never reads and every deploy erases it."""
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "volume" / "store"))
    path = listing_ledger.ledger_path()
    assert path == tmp_path / "volume" / "store" / "ops" / "listing_decisions.jsonl"
    assert Path(__file__).resolve().parents[2] not in path.parents


def test_a_decision_lands_as_one_row_with_its_reasons(tmp_path):
    assert listing_ledger.record("abc123", listed=False, blockers=("lint_ok", "uploaded"),
                                 store=tmp_path) is True
    rows = [json.loads(line) for line in
            listing_ledger.ledger_path(tmp_path).read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "abc123"
    assert rows[0]["listed"] is False
    assert rows[0]["blockers"] == ["lint_ok", "uploaded"]   # sorted, so a diff of the trail means something


def test_recording_can_never_break_a_publish(tmp_path, monkeypatch):
    """This runs on the publish path. A ledger that raises turns observability into an outage."""
    def explode(*a, **k):
        raise OSError("the volume is full")

    monkeypatch.setattr(listing_ledger, "append_jsonl", explode)

    assert listing_ledger.record("abc123", listed=True, blockers=(), store=tmp_path) is False


def test_the_report_counts_the_latest_decision_per_pack(tmp_path):
    """A pack republished after a fix has two rows saying opposite things. Only the last one
    answers "what is blocked NOW"."""
    listing_ledger.record("p1", listed=False, blockers=("lint_ok",), store=tmp_path)
    listing_ledger.record("p2", listed=False, blockers=("lint_ok", "priced"), store=tmp_path)
    listing_ledger.record("p1", listed=True, blockers=(), store=tmp_path)   # fixed and republished

    report = listing_ledger.counts_by_blocker(tmp_path)

    assert report["decisions"] == 2
    assert report["listed"] == 1
    assert report["unlisted"] == 1
    assert report["by_blocker"] == {"lint_ok": 1, "priced": 1}


def test_an_unlisted_pack_with_no_named_blocker_is_surfaced(tmp_path):
    """That is the B1 defect surviving: the decision was recorded, the reason was not. It must be
    visible rather than averaged into a clean-looking report."""
    listing_ledger.record("mystery", listed=False, blockers=(), store=tmp_path)

    assert listing_ledger.counts_by_blocker(tmp_path)["unlisted_with_no_named_blocker"] == 1


def test_the_report_is_empty_not_broken_before_the_first_publish(tmp_path):
    report = listing_ledger.counts_by_blocker(tmp_path)
    assert report["decisions"] == 0 and report["by_blocker"] == {}
