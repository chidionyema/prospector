"""One unverifiable field must not discard the whole listing_page.

Measured 2026-08-06 on the live corpus: of 258 non-KILL dossiers on disk, the four
marketing pieces survived at teaser_social 40, launch_email 41, seo_preview 36 — and
listing_page only 18 (7%), despite listing_page being the ONLY piece that reaches the
storefront and the only one granted a third repair attempt (``artifacts.py`` attempts=3).

The cause is granularity, not standard. ``_listing_check_text`` concatenated card_line,
headline, subhead, every what_you_get bullet and proof_point into ONE blob, took ONE
claim-check verdict over it, and returned None for the entire piece on a single violation.
Eight independent strings each 90% clean clear together only ~43% of the time; at six
fields the arithmetic alone explains the observed collapse.

Consequence on the storefront (live /catalog, n=61): cardLine populated on 6 packs, and
headline byte-identical to the raw candidate title on 34 — publish falling back to engine
internals because the copy that should have filled those fields was thrown away whole.

These tests pin the repaired contract: check each field on its own, drop only the fields
that actually violate, keep the rest. The truth bar is unchanged — nothing unverified
ships — so the fix may never let a violating string through (test_violating_field_never_survives).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from prospector.artifacts import _gen_one_content


# The one unverifiable sentence. It appears in proof_point only.
POISON = "Guaranteed £5,000 in your first month."

CLEAN_LISTING: Dict[str, Any] = {
    "card_line": "Challenge your business rates valuation",
    "headline": "Build a ready-to-submit business rates appeal in an afternoon",
    "subhead": "A guided evidence builder that assembles the comparables and the notice.",
    "what_you_get": [
        "A completed challenge pack",
        "The comparable-evidence table",
        "A submission checklist",
    ],
    "proof_point": POISON,
    "who_pays": "Small shop owners",
}


class FakeGen:
    """Drafting model. Returns the same listing every attempt, so the test measures the
    claim-check granularity and never the model's willingness to self-correct."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def complete_json(self, system: str, user: str, temperature: float = 0.0) -> Dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


class FakeChecker:
    """Claim-check gate. Fails exactly the texts containing POISON, passes everything else.

    This is the whole point of the fixture: every other field in CLEAN_LISTING is verifiable,
    so any field that goes missing was discarded by the gate's granularity, not by its bar.
    """

    def __init__(self) -> None:
        self.seen: List[str] = []

    def complete_json(self, system: str, user: str, temperature: float = 0.0) -> Dict[str, Any]:
        self.seen.append(user)
        if POISON in user:
            return {"pass": False,
                    "violations": [{"claim": POISON, "reason": "no supporting claim"}]}
        return {"pass": True, "violations": []}


@pytest.fixture
def piece():
    gen, checker = FakeGen(CLEAN_LISTING), FakeChecker()
    return _gen_one_content(gen, checker, "{}", "[]", [], "listing_page")


def test_one_bad_field_does_not_discard_the_piece(piece):
    """RED before the fix: a single violating proof_point returned None for all six fields."""
    assert piece is not None, "whole listing_page discarded over one unverifiable field"


def test_clean_fields_survive_alongside_a_violating_one(piece):
    """The five verifiable fields must reach the storefront unchanged."""
    assert piece["card_line"] == CLEAN_LISTING["card_line"]
    assert piece["headline"] == CLEAN_LISTING["headline"]
    assert piece["subhead"] == CLEAN_LISTING["subhead"]
    assert piece["what_you_get"] == CLEAN_LISTING["what_you_get"]


def test_violating_field_never_survives(piece):
    """The truth bar is unchanged: the unverifiable sentence ships nowhere, including in
    the derived ``copy`` blob that the storefront renders as prose."""
    assert piece["proof_point"] == ""
    assert POISON not in piece["copy"]
    for value in piece.values():
        assert POISON not in str(value)


def test_copy_is_rederived_from_surviving_fields_only(piece):
    """``copy`` is assembled from the other fields when the operator omits it. Dropping a
    field must re-derive it, or the discarded claim reappears in the prose body."""
    assert piece["headline"] in piece["copy"]
    assert piece["subhead"] in piece["copy"]
    assert piece["copy"].strip() != ""


def test_a_single_violating_bullet_keeps_its_siblings():
    """Bullets are checked individually — one bad deliverable must not cost the other two."""
    payload = dict(CLEAN_LISTING)
    payload["proof_point"] = "VOA figures show 57% of challenges secure a reduction."
    payload["what_you_get"] = ["A completed challenge pack", POISON, "A submission checklist"]

    piece = _gen_one_content(FakeGen(payload), FakeChecker(), "{}", "[]", [], "listing_page")

    assert piece is not None
    assert piece["what_you_get"] == ["A completed challenge pack", "A submission checklist"]
    assert piece["proof_point"] == payload["proof_point"]


def test_all_fields_violating_still_yields_nothing():
    """Salvage is per-field, not a weakening: when nothing is verifiable there is no piece.

    Without this, the repair would publish an empty shell that reads as 'copy exists' to
    every downstream check while carrying no buyer-facing text at all.
    """
    poisoned = {k: (POISON if isinstance(v, str) else [POISON])
                for k, v in CLEAN_LISTING.items()}

    assert _gen_one_content(FakeGen(poisoned), FakeChecker(), "{}", "[]", [], "listing_page") is None


def test_clean_listing_costs_one_check_call():
    """Cost fence. A fully verifiable piece must still take exactly ONE claim-check call.

    The gate runs on the moat, so per-field checking every piece unconditionally would
    multiply the most expensive operator in the pipeline by six. Per-field checks are a
    salvage path, entered only after the cheap whole-piece check has already failed.
    """
    clean = dict(CLEAN_LISTING)
    clean["proof_point"] = "VOA figures show 57% of challenges secure a reduction."
    checker = FakeChecker()

    piece = _gen_one_content(FakeGen(clean), checker, "{}", "[]", [], "listing_page")

    assert piece is not None
    assert len(checker.seen) == 1, f"expected 1 check call on clean copy, made {len(checker.seen)}"
