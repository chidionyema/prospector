"""The glossary pass: spell out an initialism from the operator's own words, never a brain's.

`voice_breaches` deliberately refuses to hand an initialism to a rewriting model, because an
expansion is a FACT and a model that invents one ships an unsourced claim on a source-or-die
storefront. That left 31 of the 33 defective live rows on 2026-08-16 with no repair path at
all. The glossary is the safe half of the job: the words come from
`config.yaml listing.initialism_glossary`, and this pass only pastes them in.

Every test here is about what the pass REFUSES to do, because that is where the damage is.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from sweep_shelf_copy import expand_initialisms  # noqa: E402

from prospector.pack_linter import unexplained_initialisms  # noqa: E402

GLOSS = {
    "HSE": "Health and Safety Executive",
    "DVSA": "Driver and Vehicle Standards Agency",
    "IFA": "independent financial adviser",
    "ISV": "independent software vendor",
    "FOI": "Freedom of Information",
    "STRS": "State Teachers' Retirement System",
    "DIR": "Department of Information Resources",
}


def expand(text, gloss=None):
    return expand_initialisms(text, GLOSS if gloss is None else gloss)


def test_a_declared_term_is_spelled_out_and_the_line_now_passes():
    text = "A tool that shows where a DVSA inspector will look first."
    out, unresolved, rejected, embedded = expand(text)
    assert "Driver and Vehicle Standards Agency (DVSA)" in out
    assert (unresolved, rejected, embedded) == ([], [], [])
    assert unexplained_initialisms(out) == []


def test_a_term_nobody_declared_is_reported_not_guessed():
    text = "A compliance pack for METRC reporting."
    out, unresolved, _rejected, _embedded = expand(text)
    assert out == text, "the copy must not change when nobody said what the letters mean"
    assert unresolved == ["METRC"]


def test_a_wrong_expansion_is_dropped_rather_than_published():
    # The initials do not spell the run. A typo in config.yaml must not reach the shelf.
    out, _unresolved, rejected, _embedded = expand(
        "A guide to HSE notices.", {"HSE": "Cloud Hosting Help"})
    assert out == "A guide to HSE notices."
    assert rejected == ["HSE"]


def test_the_article_is_corrected_to_the_words_not_the_letters():
    # The live defect: `an HSE improvement notice` expanded to `an Health and Safety...`.
    # The article sits outside the run, so a plain substitution leaves it agreeing with the
    # letters.
    out, _u, _r, _e = expand("Pays out when a workshop is shut by an HSE notice.")
    assert "by a Health and Safety Executive (HSE) notice" in out
    assert "an Health" not in out


def test_the_article_goes_the_other_way_too():
    out, _u, _r, _e = expand("Sold through a IFA network.")
    assert "through an independent financial adviser (IFA) network" in out


@pytest.mark.parametrize("text,want", [
    # Plural: the term in use, so it is expanded, and the expansion is pluralised too.
    ("Sold to solicitors and IFAs.", "independent financial advisers (IFAs)"),
    ("Binders for UK ISVs.", "independent software vendors (ISVs)"),
    # Compound adjective: still the term.
    ("A FOI-sourced dataset.", "Freedom of Information (FOI)-sourced"),
])
def test_plurals_and_compounds_are_the_term_in_use(text, want):
    out, unresolved, rejected, embedded = expand(text)
    assert want in out
    assert (unresolved, rejected, embedded) == ([], [], [])


def test_a_run_inside_another_word_is_left_alone_and_reported():
    # `CalSTRS` is one word. Pasting an expansion into the middle of it is worse than
    # leaving it, so this needs a human.
    text = "Shows how a leave affects their CalSTRS pension."
    out, _unresolved, _rejected, embedded = expand(text)
    assert out == text
    assert embedded == ["STRS"]


def test_a_plural_this_cannot_form_is_reported_not_invented():
    # `Resources` already ends in s. `Resourcess` is not copy we put on a shelf.
    out, unresolved, _rejected, _embedded = expand("Prep for DIRs across Texas.")
    assert out == "Prep for DIRs across Texas."
    assert unresolved == ["DIR"]


def test_a_lower_case_entry_is_capitalised_when_it_starts_the_sentence():
    out, _u, _r, _e = expand("ISVs need co-sell evidence.")
    assert out.startswith("Independent software vendors (ISVs) need")


def test_a_line_that_already_explains_itself_is_untouched():
    text = "A guide to Health and Safety Executive (HSE) notices."
    out, unresolved, rejected, embedded = expand(text)
    assert out == text
    assert (unresolved, rejected, embedded) == ([], [], [])


def test_an_empty_glossary_changes_nothing():
    text = "A tool for DVSA inspections and HSE notices."
    out, unresolved, _rejected, _embedded = expand(text, {})
    assert out == text
    assert unresolved == ["DVSA", "HSE"]


def test_every_declared_expansion_actually_spells_its_own_run():
    """The live glossary, graded by the gate's own function.

    An entry that does not spell its run is silently dead: `expand_initialisms` rejects it,
    the row stays defective, and nothing says why. This catches it in the suite instead.
    """
    from sweep_shelf_copy import glossary
    live = glossary()
    if not live:
        pytest.skip("no glossary declared in config.yaml")
    bad = []
    for run, words in live.items():
        probe = f"A guide to {words} ({run}) and nothing else."
        if unexplained_initialisms(probe):
            bad.append(f"{run} = {words!r}")
    assert not bad, "glossary entries whose initials do not spell the run: " + "; ".join(bad)
