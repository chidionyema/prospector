"""A repeated line is worth less than a fresh one. It is not a reason to refuse to sell.

Founder decision 2026-08-17, on reading why finished packs were being held off the shelf:
"the linter is wrong clearly".

The other shelf-copy rules grade a line that is WRONG — cut off mid-clause, addressed to the
wrong reader, carrying an initialism the buyer has never seen. Rule 7 grades a line that is
merely redundant, and it was doing two kinds of damage with that.

It withheld sound packs. Measured on the lint receipts of 2026-08-17: of the 32 finished
packs blocked from listing, 7 carried a duplicate-line error and 2 carried nothing else.

And it made us pay for the duplicate twice. `pack_floors.py:258` fills a missing listing with
`headline = title` and `subhead = one_liner`, so a marketing generation failure produced copy
this gate then refused. `run._shelf_copy_breaches` counts an error as a failed attempt, so
each such pack burned MAX_GEN_ATTEMPTS of generation plus an escalation to the expensive
chain, and landed UNLISTED regardless — the floor is deterministic, so the retry could never
converge.

The finding is still REPORTED, at warning, because `tools/sweep_shelf_copy.py` uses it to
find copy worth rewriting. Reporting and acting are different decisions.
"""
from __future__ import annotations

import unittest

from prospector.pack_linter import check_shelf_copy

TITLE = "Abandoned-vendor alerts for UK software operations managers"


def _sev(problems, check, where):
    return [p["severity"] for p in problems
            if p.get("check") == check and p.get("where") == where]


class TestTheDuplicateRuleNeverBlocks(unittest.TestCase):
    def test_a_headline_repeating_the_title_is_a_warning_even_with_block_on(self):
        """The exact shape `pack_floors` writes, and the exact receipt that blocked
        0bf4d472ef2b90ad."""
        problems = check_shelf_copy({"title": TITLE, "headline": TITLE}, block=True)
        self.assertEqual(_sev(problems, "shelf_copy", "headline"), ["warning"],
                         "a duplicate headline must never set ok=False")

    def test_the_finding_is_still_reported_so_the_copy_sweep_can_see_it(self):
        problems = check_shelf_copy({"title": TITLE, "headline": TITLE}, block=True)
        details = [p["detail"] for p in problems if p.get("where") == "headline"]
        self.assertTrue(any("repeats `title` verbatim" in d for d in details), details)

    def test_a_pack_whose_only_defect_is_a_duplicate_line_has_no_errors_at_all(self):
        """This is the whole point: those two packs list now."""
        problems = check_shelf_copy(
            {"title": TITLE, "headline": TITLE,
             "subhead": "A weekly feed showing which third-party licences lapsed last week.",
             "oneLine": "A weekly feed showing which third-party licences lapsed last week."},
            block=True)
        self.assertEqual([p for p in problems if p["severity"] == "error"], [],
                         "duplicate lines are the only defect here and must not block")

    def test_a_line_that_is_actually_wrong_still_blocks(self):
        """The demotion is one rule wide. An unexplained initialism is still an error, so
        this cannot be read as turning the shelf-copy gate off."""
        problems = check_shelf_copy(
            {"title": TITLE,
             "subhead": "Pulls order, IP and fulfilment evidence from Shopify every week."},
            block=True)
        self.assertIn("error", _sev(problems, "shelf_copy", "subhead"))

    def test_block_off_is_unchanged(self):
        problems = check_shelf_copy({"title": TITLE, "headline": TITLE}, block=False)
        self.assertEqual({p["severity"] for p in problems}, {"warning"})


if __name__ == "__main__":
    unittest.main()
