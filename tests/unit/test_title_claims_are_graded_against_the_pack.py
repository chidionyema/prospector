"""The title's claims are graded against the pack, not against the shelf card.

Until 2026-08-17 `lint_pack` passed `check_title_claims` the house fields minus the title —
the card line and the listing texts, about 40 words. The rule's own docstring says the
sources are "the pack's own description and structured fields", and a shelf card is not
that. So a title naming something too specific to fit on a card was reported as a claim the
pack never made, while the pack discussed it at length.

Measured over the 9 stranded PASS packs this blocked: 18 blocking errors, and all 14 distinct
flagged tokens — House, Bill, Department, Information, Resources, ISVs, DevOps, Spine,
Markets, Competition, GA, CTOs, HB and the figure 4 — appear in their own pack's copy. Every
one was false. They could not be switched off separately either, because `check_title` and
`check_title_claims` share the `title_block_on_breach` actuator.

These tests pin both directions: a term the pack uses is not a claim, and a term that appears
nowhere still is. The second half is the whole point of the rule on a source-or-die
storefront, so widening the corpus must not cost it.
"""
from __future__ import annotations

import unittest

from prospector.pack_linter import lint_pack

TITLE = "NHS Spine conformance for UK digital health vendors"
CARD = "Get conformant, with the evidence the assessor asks for."


def _errors(problems, check="title_claim"):
    return [p for p in problems
            if p.get("check") == check and p.get("severity") == "error"]


def _lint(artifacts):
    return lint_pack(
        artifacts=artifacts,
        listing_copy=CARD,
        listing_texts={},
        house_fields={"title": TITLE, "cardLine": CARD},
        market="uk",
        title_block_on_breach=True,
    )["problems"]


class TestATermThePackUsesIsNotAClaim(unittest.TestCase):
    def test_a_prose_artifact_supports_the_title(self):
        body = ("This pack covers NHS Spine conformance end to end. Spine is the national "
                "messaging backbone, and every supplier connecting to it must pass the "
                "same assessment before go-live.")
        self.assertEqual(_errors(_lint({"build_spec.md": body})), [])

    def test_a_structured_artifact_supports_the_title_too(self):
        """`is_prose_artifact` decides what may be graded AS WRITING. Whether a pack
        MENTIONS a term is a different question, and a scorecard row answers it. Restricting
        the corpus to prose left HB, ISVs and DevOps blocked on packs that named them only in
        `scorecard.json` and `scorecard_radar.svg`."""
        self.assertEqual(
            _errors(_lint({"scorecard.json": '{"axis": "Spine conformance", "score": 4}'})),
            [])


class TestATermThatAppearsNowhereIsStillAClaim(unittest.TestCase):
    """Widening the corpus must not switch the rule off. Source-or-die is the storefront."""

    def test_an_unsupported_proper_noun_is_still_reported(self):
        body = ("This pack covers procurement paperwork for health suppliers in general. "
                "It walks through the forms and who signs them.")
        details = [p["detail"] for p in _errors(_lint({"build_spec.md": body}))]
        self.assertTrue(any("Spine" in d for d in details), details)

    def test_an_empty_pack_supports_nothing(self):
        details = [p["detail"] for p in _errors(_lint({}))]
        self.assertTrue(any("Spine" in d for d in details), details)


class TestTheTitleIsNotItsOwnEvidence(unittest.TestCase):
    """13 live headlines are verbatim copies of their title. A title checked against its own
    headline supports itself, which is why the title stays out of its own sources."""

    def test_a_shelf_line_that_repeats_the_title_does_not_clear_it(self):
        problems = lint_pack(
            artifacts={"build_spec.md": "Generic procurement paperwork guidance."},
            listing_copy=TITLE,
            listing_texts={},
            house_fields={"title": TITLE, "cardLine": TITLE},
            market="uk",
            title_block_on_breach=True,
        )["problems"]
        details = [p["detail"] for p in _errors(problems)]
        self.assertTrue(any("Spine" in d for d in details), details)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
