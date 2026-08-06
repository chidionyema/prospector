"""The copy backfill must never CLEAR copy it merely failed to regenerate.

PATCH /internal/catalog/{id}/copy distinguishes two intents that look alike from the caller's
side: an omitted field means "leave it alone", and "" means "withdraw this, it was wrong". A
backfill only ever holds the first. Salvage (artifacts._salvage_listing) keeps the fields that
pass claim-check and drops the ones that do not, so a dropped field means "could not rewrite
this" — never "this should not exist".

This is a regression test, not a hypothetical. On the first live pack (6171136b72015134,
2026-08-06) claim-check dropped the headline, catalog_payload rendered it as "", and the PATCH
cleared a headline that had been showing the pack's title. The pack ended up with LESS copy than
the deterministic floor the job existed to improve on.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "backfill_listing_copy.py"
_spec = importlib.util.spec_from_file_location("backfill_listing_copy", _TOOL)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


def test_a_field_salvage_dropped_is_omitted_not_blanked():
    # What _gen_one_content returns after salvage drops the headline: the key is present on the
    # listing dict, with nothing in it.
    listing = {
        "type": "listing_page",
        "card_line": "Guided claim paperwork tool for California family carers",
        "headline": "",
        "subhead": "A verified opportunity with a costed build plan.",
        "what_you_get": ["Blueprint", "Go-to-market plan"],
        "proof_point": "Insurers paid around $12.3 billion in claim benefits in 2021.",
    }

    payload = backfill.prune_empty(backfill.catalog_payload(listing))

    # Omitted entirely — the endpoint leaves the stored headline alone.
    assert "headline" not in payload, (
        "a dropped headline was sent as a value; on PATCH .../copy that CLEARS the stored one"
    )
    # Everything the operator did produce still goes.
    assert payload["cardLine"] == "Guided claim paperwork tool for California family carers"
    assert payload["subhead"] == "A verified opportunity with a costed build plan."
    assert payload["whatYouGet"] == ["Blueprint", "Go-to-market plan"]


def test_no_field_is_ever_sent_as_an_empty_value():
    """The whole listing failing is the extreme case, and it must send nothing at all."""
    payload = backfill.prune_empty(backfill.catalog_payload({"type": "listing_page"}))

    assert payload == {}, f"empty listing produced a clearing payload: {payload}"


@pytest.mark.parametrize("empty", ["", [], None])
def test_prune_removes_every_empty_shape(empty):
    """"", [] and None all reach the endpoint as a clear or a type error. None may pass."""
    assert backfill.prune_empty({"cardLine": "kept", "headline": empty}) == {"cardLine": "kept"}


def test_a_genuinely_zero_like_string_survives():
    """Guard the pruner against over-reach: "0" and "false" are content, not emptiness."""
    payload = backfill.prune_empty({"timeToFirstRevenue": "0", "effortTag": "false"})

    assert payload == {"timeToFirstRevenue": "0", "effortTag": "false"}


DOSSIER = {
    "candidate": {
        "title": "ClaimCare — a guided evidence builder for California family caregivers",
        "one_liner": "Helps family carers get a long-term care insurance claim approved.",
        "why_now": "Claim denials rose after the 2024 rule change.",
        "who_pays": "Adult children caring for an older relative with a policy.",
    },
    "checks": [
        {"verdict": "supported", "check_name": "pain_reality", "rationale": "Carers report denials."},
        {"verdict": "supported", "check_name": "payer_solvency", "rationale": "Policyholders pay premiums."},
        {"verdict": "unverifiable", "check_name": "legality", "rationale": "No passage found."},
    ],
}


def test_a_dropped_field_is_refilled_from_the_deterministic_floor():
    """Persisting a partial listing is what plants the regression; filling it is the fix."""
    salvaged = {"type": "listing_page", "card_line": "Guided claim paperwork tool",
                "headline": "", "copy": ""}

    filled = backfill.fill_from_floor(salvaged, DOSSIER)

    # The operator's own work is never overwritten by the floor.
    assert filled["card_line"] == "Guided claim paperwork tool"
    # `copy` empty is what makes ensure_marketing_floor discard the whole listing on the next
    # publish (pack_floors.py:184-191), so it above all must come back.
    assert filled["copy"].strip(), "empty copy survives; a republish would discard this listing"
    assert filled["headline"] == DOSSIER["candidate"]["title"][:140]


def test_the_filled_listing_satisfies_the_floor_check_that_would_discard_it():
    """The property that matters, asserted against the real predicate rather than restated."""
    from prospector.pack_floors import ensure_marketing_floor

    filled = backfill.fill_from_floor({"type": "listing_page", "card_line": "x"}, DOSSIER)

    candidate = importlib.import_module("types").SimpleNamespace(
        **{k: v for k, v in DOSSIER["candidate"].items()})
    kept = ensure_marketing_floor([filled], candidate, [])

    assert any(m.get("card_line") == "x" for m in kept), (
        "the floor replaced the filled listing, so the backfill's copy would not survive"
    )
