"""`3PLs` is one word. The claim checker read it as the figure 3 and the proper noun "PLs".

`_TOKEN_RE` (`prospector/pack_linter.py:1479`) splits on the alpha/digit boundary, which is
right for counting words and wrong for deciding what the copy claims. `check_claims` asked
two questions of the halves:

  * "states a figure the pack's own copy does not: '3'"
  * "introduces the proper noun 'PLs', which appears nowhere in the pack's own copy"

Both were reported as ERRORS on pack `19aaf66a4e9f7778`, whose title is "Savannah port
container dwell forecasts for 3PLs". Nobody claimed the number three, and "PLs" appears
nowhere in the title either, so the operator was handed a receipt naming a string they could
not find in their own copy. Trade terms are built this way — 3PL, 4PL, 2FA, K8s.

Same defect and the same day as `_CAPS_RUN_RE` keeping its leading digits
(`test_initialism_scope_is_the_whole_shelf.py`), in the other rule that reads tokens.
"""
from __future__ import annotations

import unittest

from prospector.pack_linter import check_claims

SOURCES = ["Weekly container dwell time forecasts for logistics operators at the port."]


def _details(text, sources=SOURCES):
    return [p["detail"] for p in check_claims(text, sources, block=True)]


class TestTheMeasuredTitle(unittest.TestCase):
    TITLE = "Savannah port container dwell forecasts for 3PLs"

    def test_the_digit_in_a_trade_term_is_not_a_figure(self):
        self.assertEqual([d for d in _details(self.TITLE) if "states a figure" in d], [])

    def test_the_tail_of_a_trade_term_is_not_a_proper_noun(self):
        self.assertEqual([d for d in _details(self.TITLE) if "proper noun" in d], [])


class TestARealClaimStillBlocks(unittest.TestCase):
    """The guards are about word boundaries, not about letting figures through."""

    def test_a_standalone_figure_is_still_reported(self):
        self.assertTrue([d for d in _details("Cuts dwell time by 40% at the port")
                         if "states a figure" in d and "40" in d])

    def test_a_standalone_proper_noun_is_still_reported(self):
        self.assertTrue([d for d in _details("Container dwell forecasts for Maersk operators")
                         if "proper noun" in d and "Maersk" in d])

    def test_a_figure_the_copy_supports_is_not_reported(self):
        self.assertEqual(
            [d for d in _details("Cuts dwell time by 40% at the port",
                                 SOURCES + ["Measured at 40% on the 2026 sample."])
             if "states a figure" in d],
            [])


if __name__ == "__main__":
    unittest.main()
