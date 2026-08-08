"""Two defects the 2026-08-08 republish surfaced on live packs.

1. A pack was unlisted for an em-dash in `headline` that never reached the storefront.
   The catalogue's house-dash rule was applied by `_normalise_catalog_payload` AFTER the
   pack lint ran, so the linter graded a value the buyer never receives. The same string
   passed as `title` (normalised at its call site) and failed as `headline` (not) — one
   string, two verdicts, and two live packs (13d41ccee9e96e2d, 3e72d5a5f1a60068) held off
   the shelf by it.

2. Two packs could never be provisioned at all. The Stripe product idempotency key was the
   pack id alone, and a key replayed inside Stripe's 24h window with different parameters
   is a hard error. `name`/`description` are the pack's copy, so fixing copy inside that
   window made the pack permanently unprovisionable (13795bea31feee47, 2abc23c3c0d05bab).
"""
import sys
import types

import pytest

from prospector.bridge import StripeProvisioner, _card_field
from prospector.pack_linter import check_house_dashes, check_truncation
from prospector.plain_text import nodash

DASHED = "RetainRelease — the subcontractor's automated retention chaser"


# --------------------------------------------------------------------------------------
# 1. The lint must grade the value that ships
# --------------------------------------------------------------------------------------

def test_card_field_applies_the_house_dash_rule():
    """`_card_field` is the catalogue's single boundary for a one-line prose field."""
    out = _card_field(DASHED)
    assert "—" not in out and "–" not in out and "‑" not in out
    assert out == nodash(out), "normalisation must be idempotent"


def test_a_headline_that_ships_clean_no_longer_fails_the_house_dash_check():
    """The exact defect: this text unlisted two live packs on 2026-08-08."""
    assert check_house_dashes({"headline": DASHED}), "control: the raw value does fail"
    assert check_house_dashes({"headline": _card_field(DASHED)}) == []


def test_headline_and_title_now_reach_the_same_verdict():
    """One string graded twice must not pass as `title` and fail as `headline`."""
    title_side = nodash(DASHED)          # bridge.py:832 has always normalised here
    headline_side = _card_field(DASHED)  # this is what the fix aligns
    assert (check_house_dashes({"f": title_side}) == []) is (
        check_house_dashes({"f": headline_side}) == [])


def test_truncation_stays_decidable_when_both_halves_are_normalised():
    """`check_truncation` decides mid-word cuts with `source.startswith(final)`.

    Normalising only the rendered half would not make it wrong — it would make it VACUOUS,
    which is worse, because a genuinely mid-word slice would then pass in silence.
    """
    source = _card_field("Alpha — Bravo " + "x" * 200 + " continuation")
    final = source[:140]
    problems = check_truncation({"headline": (final, source)}, {"headline": 140})
    assert problems and problems[0]["check"] == "truncation", (
        "a hard mid-word slice must still be caught after normalisation")

    # And the half-normalised form is the vacuity this guards against.
    half_normalised = ("Alpha, Bravo " + "x" * 200)[:140]
    raw_source = "Alpha — Bravo " + "x" * 200
    assert check_truncation({"headline": (half_normalised, raw_source)},
                            {"headline": 140}) == [], (
        "control: mismatched spaces silently skip the check — do not ship that shape")


# --------------------------------------------------------------------------------------
# 2. The Stripe product key must change when the request changes
# --------------------------------------------------------------------------------------

class _FakeStripe(types.SimpleNamespace):
    """Minimal stand-in; records the idempotency key each create was issued under."""

    class error:  # noqa: N801 - mirrors the stripe SDK's attribute name
        class StripeError(Exception):
            pass


def _provisioner(monkeypatch):
    keys = []

    fake = _FakeStripe()
    fake.api_key = None

    def _create(**kwargs):
        keys.append(kwargs["idempotency_key"])
        return types.SimpleNamespace(id="prod_fake")

    fake.Product = types.SimpleNamespace(create=_create)
    monkeypatch.setitem(sys.modules, "stripe", fake)
    return StripeProvisioner("sk_test_notreal"), keys


def test_identical_requests_share_one_key(monkeypatch):
    """The property that must survive: a retry of the SAME request never mints twice."""
    prov, keys = _provisioner(monkeypatch)
    meta = {"pack_id": "13795bea31feee47"}
    prov.create_product("Name", "Description", meta)
    prov.create_product("Name", "Description", meta)
    assert keys[0] == keys[1]
    assert keys[0].startswith("prospector-product-13795bea31feee47-")


@pytest.mark.parametrize("field", ["name", "description", "metadata"])
def test_a_copy_change_takes_a_fresh_key(monkeypatch, field):
    """Keying on the pack id alone made a copy fix inside 24h unprovisionable forever."""
    prov, keys = _provisioner(monkeypatch)
    base = dict(name="Name", description="Description",
                metadata={"pack_id": "2abc23c3c0d05bab"})
    changed = dict(base)
    changed[field] = ({"pack_id": "2abc23c3c0d05bab", "extra": "x"}
                      if field == "metadata" else "Different")

    prov.create_product(base["name"], base["description"], base["metadata"])
    prov.create_product(changed["name"], changed["description"], changed["metadata"])
    assert keys[0] != keys[1], f"a changed {field} must not replay the burned key"
    # Still scoped to the pack, so the key remains readable in a Stripe audit.
    assert all(k.startswith("prospector-product-2abc23c3c0d05bab-") for k in keys)
