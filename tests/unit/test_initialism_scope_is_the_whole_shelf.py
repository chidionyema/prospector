"""A term the title spells out is introduced by the time the card line uses it.

The buyer reads the title, the headline, the subhead and the card line at once. Grading each
field on its own refused copy that had done exactly what the rule asked for, in the field
with the most room to do it.

The measured case, from the lint receipt of 2026-08-17. Pack `38029727242c23c9` titled itself
"Cybersecurity Maturity Model Certification (CMMC) Level 2 evidence packs for GA defense
software vendors" and was blocked because its card line said "CMMC Level 2 evidence binders
for defense software firms". The only copy that satisfied the per-field rule would have spelt
a 46-character term out four times on one page, and the title cap is 60 characters.

Same principle as the duplicate-line demotion (`test_duplicate_shelf_lines_never_block.py`):
a rule that stops a sale has to grade something that is wrong, and this line was not wrong.

What does NOT change: the terms REPORTED are still only the ones the graded line uses. The
context widens where an expansion counts, never what is graded.
"""
from __future__ import annotations

import unittest

from prospector.pack_linter import check_shelf_copy, unexplained_initialisms

TITLE = "Cybersecurity Maturity Model Certification (CMMC) Level 2 evidence packs"
CARD = "CMMC Level 2 evidence binders for defense software firms"


def _errors(problems, where=None):
    return [p for p in problems
            if p["severity"] == "error" and (where is None or p.get("where") == where)]


class TestTheHelperTakesAContext(unittest.TestCase):
    def test_without_a_context_the_line_is_its_own_context(self):
        """The sweep calls it this way and must keep the behaviour it had."""
        self.assertEqual(unexplained_initialisms(CARD), ["CMMC"])
        self.assertEqual(unexplained_initialisms(TITLE), [])

    def test_an_expansion_in_the_context_introduces_the_term(self):
        self.assertEqual(unexplained_initialisms(CARD, context=TITLE + " " + CARD), [])

    def test_a_context_that_never_expands_it_still_reports_it(self):
        self.assertEqual(
            unexplained_initialisms(CARD, context="Evidence binders for defense firms " + CARD),
            ["CMMC"])

    def test_the_context_widens_where_not_what(self):
        """A term used only in the CONTEXT is not reported against this line."""
        self.assertEqual(unexplained_initialisms("Evidence binders for defense firms",
                                                 context="DFARS 252.227 evidence binders"),
                         [])


class TestTheShelfIsGradedAsOnePage(unittest.TestCase):
    def test_the_measured_pack_is_no_longer_blocked(self):
        problems = check_shelf_copy({"title": TITLE, "cardLine": CARD}, block=True)
        self.assertEqual(_errors(problems, "cardLine"), [],
                         "the title spells CMMC out; the card line must not be refused for it")

    def test_a_term_nothing_on_the_shelf_expands_still_blocks(self):
        """The widening is scope, not amnesty."""
        problems = check_shelf_copy(
            {"title": "Evidence binders for defense software firms", "cardLine": CARD},
            block=True)
        details = [p["detail"] for p in _errors(problems, "cardLine")]
        self.assertTrue(any("CMMC" in d for d in details), details)


class TestTheTermReportedIsTheTermInTheCopy(unittest.TestCase):
    """The receipt on `19aaf66a4e9f7778` told the operator to spell out "PL" in the line
    "Savannah port container dwell forecasts for 3PLs". No "PL" appears in it.

    Trade terms carry their digit — 3PL, 2FA, 4PL — and an instruction naming a string the
    writer cannot find is not actionable. `listing.initialism_glossary` is keyed on the
    reported term too, so the operator's own expansion could never have matched it."""

    def test_a_digit_prefixed_trade_term_is_reported_whole(self):
        self.assertEqual(
            unexplained_initialisms("Savannah port container dwell forecasts for 3PLs"),
            ["3PL"])

    def test_a_plain_initialism_is_unchanged(self):
        self.assertEqual(unexplained_initialisms("Filed with the FSA and the DVSA"),
                         ["DVSA", "FSA"])

    def test_a_run_hiding_in_a_mixed_case_token_is_unchanged(self):
        """`CalSTRS` -> `STRS`. The documented second shape must survive the digit change."""
        self.assertEqual(unexplained_initialisms("A CalSTRS reporting tool"), ["STRS"])


if __name__ == "__main__":
    unittest.main()
