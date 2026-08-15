"""The toolkit is the one page a buyer FILLS IN, so its blanks have to be blanks.

`pack_toolkit.render` is deterministic — dossier fields in, markdown out, no model call — so
everything it can get wrong is a template defect, and a template defect ships on every pack at
once. The one pinned here did: the decision memo printed

    BIGGEST RISK:      [from 'What would sink this']

on every pack, unconditionally. Two things are wrong with it and they fail in different ways.

It is a bracket, and every other bracket in this file is a hole the buyer fills from their own
calls. This one held an instruction to go and copy something out of elsewhere in the pack —
template scaffolding that escaped into the deliverable rather than a blank left on purpose.

And what it pointed at is not always there. `pack_bear_case.render` returns "" when nothing was
refuted, nothing was left unverifiable and the financial model named no weakness, and
`bridge._create_bundle` then omits the section entirely (bridge.py:1758-1790). So on an
all-supported dossier the memo sent the buyer to a section that is not in their download.

The fix reads the risk off the dossier instead, and prints no line when the dossier names no
risk. These tests pin both halves and the general rule underneath them: nothing in this
document points at a section the bundle may not contain.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from prospector import pack_toolkit
from prospector.bridge import _SECTION_TITLES

# Every section `bridge` renders conditionally and drops on a falsy body, minus this one. A
# pointer at any of them can dangle in a shipped pack; a pointer at a section that always
# renders (the executive summary, the QA report) cannot, which is why the exec summary is
# allowed to name two of those and this document is allowed to name none of these.
_OMITTABLE_SECTIONS = ("The_Offer.md", "The_Field.md", "What_Would_Sink_This.md",
                       "How_To_Know_In_30_Days.md", "Evidence_and_Constraints.md")

_BRACKETED = re.compile(r"\[([^\[\]]*)\]")


def _check(name: str, verdict: str) -> SimpleNamespace:
    # Verdicts as PLAIN STRINGS, which is the shape `pack_manifest.dossier_from_dict` hands
    # every renderer when a pack is re-rendered from its manifest. A fixture built out of
    # `Verdict` enums only would leave the `getattr(..., "value", ...)` path untested.
    return SimpleNamespace(check_name=name, verdict=verdict, rationale="Because of a passage.")


def _dossier(*checks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        candidate=SimpleNamespace(title="Shellfish Window",
                                  one_liner="Lease closure forecast for growers",
                                  who_pays="Independent shellfish farmers"),
        checks=list(checks),
    )


class TestTheDecisionMemoTakesItsRiskFromTheDossier:
    """The memo's BIGGEST RISK line, which used to be a pointer and is now a reading."""

    def test_the_risk_line_names_the_check_the_pack_could_not_settle(self):
        md = pack_toolkit.render(_dossier(
            _check("pain_reality", "supported"),
            _check("payer_solvency", "unverifiable")))
        assert "BIGGEST RISK:      Can the customer afford it?" in md
        assert "we could not settle this from the desk" in md

    def test_a_refuted_check_outranks_an_unverifiable_one(self):
        """Same ordering rule as `pack_kicker._pick`, for the same reason.

        Evidence that argues AGAINST a check is a live finding the buyer has to overturn; an
        unverifiable one is a gap they have to fill. The first is the bigger risk even when the
        second sits earlier in the kill order, so `distribution` refuted beats `pain_reality`
        unverifiable despite `pain_reality` leading `_ORDER`.
        """
        md = pack_toolkit.render(_dossier(
            _check("pain_reality", "unverifiable"),
            _check("distribution", "refuted")))
        assert "BIGGEST RISK:      Can you actually reach the customer?" in md
        assert "the evidence argued against this" in md
        assert "Is the problem real?" not in md.split("BIGGEST RISK:")[1]

    def test_an_open_check_with_no_interview_question_still_reaches_the_memo(self):
        """`_QUESTIONS` covers seven checks; the engine runs more than seven.

        `hybrid_entity` has no entry there and none in `pack_kicker._TESTS` either, and a risk
        line keyed off those maps would silently print nothing for it — the same class of hole
        that let the kicker claim everything was supported. The memo ranks by `_ORDER` and then
        takes whatever is left, so an unmapped name is demoted, never dropped.
        """
        md = pack_toolkit.render(_dossier(_check("hybrid_entity", "unverifiable")))
        assert "BIGGEST RISK:      Hybrid entity" in md

    def test_the_line_is_absent_rather_than_invented_when_nothing_is_open(self):
        """The all-supported dossier — the exact case the old pointer dangled on.

        Absent, not filled with a plausible risk. This file states no fact about the market
        (module docstring), and "your biggest risk is X" would be the first one it ever
        asserted, in the artefact the buyer is meant to act on.
        """
        md = pack_toolkit.render(_dossier(
            _check("pain_reality", "supported"), _check("legality", "supported")))
        assert "BIGGEST RISK:" not in md
        # An omission, not a collapse: the memo and the lines around it are still there.
        assert "## 3. The one-page decision memo" in md
        assert "KILL LINE:" in md

    def test_the_blanks_the_buyer_fills_are_untouched(self):
        """The brackets that are supposed to be there stay there.

        The fix must not be read as "brackets are bad". A template that filled these in with
        something plausible would be putting words in a buyer's mouth about a business we have
        never seen operate, which is what the module docstring forbids.
        """
        md = pack_toolkit.render(_dossier(_check("pain_reality", "supported")))
        for blank in ("[in their words, from the calls]", "[names, not counts]",
                      "[figure] because [what they compared it to]",
                      "if [specific thing] by [date], I stop."):
            assert blank in md


class TestNothingHerePointsAtASectionTheBundleMayNotContain:
    """The general rule the memo defect was one instance of.

    A cross-reference in a paid document is a promise that the thing referred to is in the
    download. Five of the pack's sections render conditionally, so naming one of those is a
    promise this module cannot keep — and it costs the buyer the two minutes of looking for it
    before they conclude the pack is short, in the first five minutes, which is when a refund
    gets decided.
    """

    def test_no_bracket_holds_a_pointer_out_of_this_document(self):
        for dossier in (_dossier(_check("pain_reality", "supported")),
                        _dossier(_check("payer_solvency", "refuted")),
                        _dossier()):
            md = pack_toolkit.render(dossier)
            for inner in _BRACKETED.findall(md):
                for filename in _OMITTABLE_SECTIONS:
                    assert _SECTION_TITLES[filename].lower() not in inner.lower(), (
                        f"bracketed pointer at a section bridge may omit: [{inner}]")

    def test_no_prose_names_an_omittable_section_either(self):
        """Brackets were how it shipped; they are not what makes it wrong.

        The same sentence without the brackets is the same broken promise, so the assertion is
        made over the whole document rather than over its punctuation.
        """
        for dossier in (_dossier(_check("pain_reality", "supported")),
                        _dossier(_check("legality", "unverifiable")),
                        _dossier()):
            md = pack_toolkit.render(dossier)
            for filename in _OMITTABLE_SECTIONS:
                assert _SECTION_TITLES[filename].lower() not in md.lower(), (
                    f"named {_SECTION_TITLES[filename]!r}, which bridge drops on a falsy body")

    def test_a_dossier_with_no_checks_does_not_promise_a_list_of_sources(self):
        """`pack_reference.render` returns "" without checks, so that section goes too.

        And there would be nothing in it: no checks means no cited sources. A closing section
        telling the reader to go and re-run the links is pointing at both a missing page and
        missing links.
        """
        md = pack_toolkit.render(_dossier())
        assert "The sources are listed with their links" not in md
        assert "## 4. When to re-check us" in md

    def test_the_pointer_is_there_when_the_evidence_it_points_at_is(self):
        # The negative above is only worth anything if the positive still holds — otherwise
        # deleting the sentence outright would pass every assertion in this class.
        md = pack_toolkit.render(_dossier(_check("pain_reality", "supported")))
        assert "The sources are listed with their links" in md


def test_it_renders_nothing_at_all_without_a_candidate():
    assert pack_toolkit.render(SimpleNamespace(candidate=None, checks=[])) == ""
