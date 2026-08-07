"""§25.6 item 3 — `payer_solvency` must argue against the REAL rung, not an invented price.

The check used to be handed no price at all, so it made one up, sometimes off the ladder
entirely; those invented figures are ~2/3 of the corpus's untraceable-number count. The fix
is `verify._check_question`, and the two properties worth pinning are:

  * the price it states is the one `pricing.price_for` resolves from `config.yaml`, and
  * NO other check's question moves by a single byte, so the golden set cannot shift
    underneath a change that was only ever about one check.

The blast-radius test is the important one. A prompt edit that quietly reworded all seven
questions would still pass a test that only asserted "£49 appears somewhere".
"""
from __future__ import annotations

import pytest

from prospector.models import CHECKS, DEFAULT_CHECKS, Candidate
from prospector.prompts import render
from prospector.verify import _check_question


def _cand(**kw) -> Candidate:
    return Candidate(title="A pack about something", **kw)


# --- the blast radius: six checks must not move ------------------------------------------

def test_every_other_check_renders_byte_identically(cfg):
    """Only payer_solvency may change. Six checks, compared exactly, not by substring."""
    others = [c for c in DEFAULT_CHECKS if c != "payer_solvency"]
    assert len(others) == 5, f"DEFAULT_CHECKS shape changed: {DEFAULT_CHECKS}"
    for name in others:
        assert _check_question(name, _cand(), cfg) == CHECKS[name], name


def test_a_non_default_check_is_also_untouched(cfg):
    """The pack-intent lane checks share the same renderer and must be unaffected too."""
    assert _check_question("buyer_intent", _cand(), cfg) == CHECKS["buyer_intent"]


# --- the fix: the stated price is the resolved rung ---------------------------------------

def test_unclassified_pack_is_asked_about_the_default_rung(cfg):
    """`default_rung_index: 2` over `rungs: [1900, 2900, 4900, ...]` => £49."""
    q = _check_question("payer_solvency", _cand(), cfg)
    assert "£49" in q
    assert q.startswith(CHECKS["payer_solvency"]), "the original question must survive intact"
    assert "do not substitute a different figure" in q


@pytest.mark.parametrize("tier,market,expected", [
    ("side_hustle", "uk", "£29"),   # index 1, no offset
    ("smb", "uk", "£49"),           # index 2, no offset
    ("growth", "uk", "£79"),        # index 3, no offset
    ("venture", "uk", "£149"),      # index 5, no offset
    ("venture", "us", "£199"),      # index 5 + 1 us offset = 6
    ("smb", "us", "£79"),           # index 2 + 1 = 3
])
def test_the_question_follows_the_ladder(cfg, tier, market, expected):
    """The number in the prompt is the ladder's, so a config rung edit moves the prompt."""
    q = _check_question("payer_solvency", _cand(ambition_tier=tier, market=market), cfg)
    assert expected in q, q


def test_the_price_actually_reaches_the_rendered_prompt(cfg):
    """The seam, not just the helper: prove the figure survives into the verdict text."""
    q = _check_question("payer_solvency", _cand(), cfg)
    _system, user = render("verdict", candidate_json="{}", check_name="payer_solvency",
                           check_question=q, verdict_bias="",
                           market_scope="", market_verdict_exemplars="",
                           rationale_style="")
    assert "£49" in user


# --- degradation: a pricing problem must never take the moat down -------------------------

def test_no_cfg_degrades_to_the_bare_question():
    assert _check_question("payer_solvency", _cand(), None) == CHECKS["payer_solvency"]


def test_a_broken_config_degrades_instead_of_raising():
    """`price_for` reads `cfg.listing`; an object without one must not fail a check."""
    q = _check_question("payer_solvency", _cand(), object())  # type: ignore[arg-type]
    assert q == CHECKS["payer_solvency"]


def test_a_ladderless_config_holds_at_the_flat_price(cfg):
    """No usable ladder => price_for holds at listing.price_pence, and we still state it."""
    class _Ladderless:
        listing = {"price_pence": 4900}
    q = _check_question("payer_solvency", _cand(), _Ladderless())  # type: ignore[arg-type]
    assert "£49" in q
