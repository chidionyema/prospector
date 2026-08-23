"""The generator's shelf-copy guardrail must apply the publish gate's bar, not a nearby one.

`run._shelf_copy_breaches` exists to stop the cheap chain shipping copy `bridge.py` would
refuse. It only does that while the two ask the same question. Two shelf rules read the whole
page rather than one field at a time — an initialism the title spells out is introduced by
the time the card line uses it, and a line that repeats the title is the repeat — so a
guardrail handed the card line alone grades against a HARDER bar than publish does.

The cost of that divergence is not a wrong verdict at publish. It is three wasted generation
attempts plus a permanent escalation to the deliverable chain (`run.py:772`), all to arrive
at the same pack, because no rewrite of the card line can satisfy a rule about the title.

What must not change with it: the title is context, never graded. It comes off the Candidate,
so no marketing rewrite can move it, and `_MARKETING_SHELF_FIELDS` is the list of fields a
rewrite can actually fix.
"""
from __future__ import annotations

import unittest

from prospector import run as run_mod


class _Cfg:
    listing = {"shelf_copy_block_on_breach": True}


class _Cand:
    candidate_id = "d" * 16

    def __init__(self, title):
        self.title = title


def _listing(**kw):
    return [{"type": "listing_page", **kw}]


class TestTheTitleIsContext(unittest.TestCase):
    TITLE = "Cybersecurity Maturity Model Certification (CMMC) evidence packs"

    def test_a_term_the_title_expands_does_not_fail_an_attempt(self):
        """Verbatim shape of `38029727242c23c9`, the pack this cost."""
        breaches = run_mod._shelf_copy_breaches(
            _Cand(self.TITLE),
            _listing(card_line="CMMC Level 2 evidence binders for defense software firms"),
            _Cfg())
        self.assertEqual(breaches, [], breaches)

    def test_a_term_nothing_expands_still_fails_the_attempt(self):
        breaches = run_mod._shelf_copy_breaches(
            _Cand("Evidence binders for defense software firms"),
            _listing(card_line="CMMC Level 2 evidence binders for defense software firms"),
            _Cfg())
        self.assertTrue(any("CMMC" in b for b in breaches), breaches)


class TestTheTitleIsNeverGraded(unittest.TestCase):
    def test_a_breaching_title_alone_costs_no_attempt(self):
        """A 104-character title is a real defect and a rewrite cannot fix it here."""
        breaches = run_mod._shelf_copy_breaches(
            _Cand("QQQQ " * 40),
            _listing(card_line="Evidence binders for defense software firms"),
            _Cfg())
        self.assertEqual(breaches, [], breaches)

    def test_only_the_marketing_fields_are_reported(self):
        breaches = run_mod._shelf_copy_breaches(
            _Cand("Evidence binders for defense software firms"),
            _listing(card_line="CMMC Level 2 evidence binders for defense software firms",
                     headline="DVSA renewal packs for coach operators"),
            _Cfg())
        self.assertTrue(breaches)
        self.assertTrue(all("title" not in b.split("repeats")[0][:20] for b in breaches))


class TestTheActuatorIsUnchanged(unittest.TestCase):
    def test_the_switch_off_costs_nothing(self):
        class _Off:
            listing = {"shelf_copy_block_on_breach": False}

        self.assertEqual(
            run_mod._shelf_copy_breaches(
                _Cand("x"), _listing(card_line="CMMC binders"), _Off()),
            [])


if __name__ == "__main__":
    unittest.main()
