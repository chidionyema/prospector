"""The scorer was the only reader of the six axes that had never been told what they mean.

`prompts/score.md` listed six bare axis names and left every definition to the model. The
generator (since `e0b270f`) and the critic (`critique._axes_brief`) both receive definitions
rendered from `cfg.weights`; the scorer received none — so the axis that decides most kills was
defined by whatever the model assumed.

MEASURED 2026-08-15, 161 `money_provability` scores <=1 since 2026-08-01: what the model
assumed was a PRODUCT-level, price-page-dependent reading. It rejected money it had found for
being the wrong artifact —

  "The only price anyone is shown paying is a solicitor's fixed probate fee of £825 plus £165
   VAT ... same buyer, different service."
  "the closest products are quote-on-request only ... with no figure."

Both are facts about what the open web publishes. `price_comparables` is already built on the
opposite principle and may NEVER kill, because "no price page on the open web" is a fact about
the web, not the idea. The scorer was applying the inverse rule with full kill authority
through `min_composite`.

This is a correction to a MIS-MEASUREMENT, not a loosened gate: nothing here changes a
threshold, and every claim the scorer credits still has to have come from a retrieved passage.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from prospector.config import load_config
from prospector.prompts import PROMPTS_DIR, render


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_the_score_prompt_actually_receives_the_definitions(cfg):
    from prospector.critique import _axes_brief

    _system, user = render("score", candidate_json="{}", claims_json="[]",
                           score_axes=_axes_brief(cfg))
    assert "money_provability (weight" in user, "the axis brief never reached the prompt"
    assert "defensibility (weight" in user


def test_the_placeholder_cannot_ship_unsubstituted(cfg):
    """`render()` does not raise on an unsubstituted token — it ships `{score_axes}` to the
    model verbatim. That is only safe because `score.py` is the SOLE caller. If a second
    caller appears without the kwarg, this test is the thing that should have caught it."""
    import re

    from prospector import score as score_mod

    src = (PROMPTS_DIR.parent / "prospector" / "score.py").read_text()
    assert "score_axes=_axes_brief(cfg)" in src
    callers = [p for p in (PROMPTS_DIR.parent / "prospector").rglob("*.py")
               if re.search(r'render\(\s*"score"', p.read_text())]
    assert [p.name for p in callers] == ["score.py"], (
        f"a new caller of render('score') must pass score_axes: {callers}")
    assert score_mod.SCORE_AXES


def test_no_public_price_is_not_scored_as_no_money():
    """The founder's case: money changes hands in the sector, but not for this exact idea."""
    text = (PROMPTS_DIR / "score.md").read_text()
    assert "ABSENCE OF A PUBLISHED PRICE IS NOT EVIDENCE OF ABSENCE OF MONEY" in text
    assert "Quote-on-request" in text
    # And the floor must stay real, or the axis measures nothing at all.
    assert "nobody spends anything to get this job done" in text


def test_the_definition_is_job_level_at_the_single_source():
    """One string feeds generator, critic and scorer. Widening it product-ward again would
    silently restore the bias in all three at once — which is exactly why it lives in one place."""
    from prospector.critique import _AXIS_HINTS

    hint = _AXIS_HINTS["money_provability"]
    assert "OUTCOME" in hint
    assert "No public price page" in hint
    assert "quote-on-request" in hint.lower()


def test_a_weightless_config_still_renders_the_prompt(cfg):
    """`_axes_brief` returns "" with no weights; the score prompt must still be renderable."""
    from prospector.critique import _axes_brief

    _system, user = render("score", candidate_json="{}", claims_json="[]",
                           score_axes=_axes_brief(SimpleNamespace(weights={})))
    assert "{score_axes}" not in user
