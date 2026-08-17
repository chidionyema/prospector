"""A coinage is cryptic because the reader has never seen it. "GitHub" is not that.

`check_title` refuses an intercapped word because the founder called that shape cryptic on
2026-08-13: it is the first thing a scanner reads and it means nothing until you already own
the pack. All-caps initialisms were exempted from the start — "they are words a reader
already knows, which is the whole distinction". Intercapped words the reader already knows
were not, and the rule had no idea of the difference.

Measured on the lint receipts of 2026-08-17. Nineteen findings named a coined name. Three
were real-world vocabulary and all three were ERRORS holding a finished pack off the shelf:

  f2734b0fcec9ca32  "GitHub Advanced Security alert investigation summaries for lean dev teams"
  7be1cb35e01902d7  "Amazon Web Services (AWS) DevOps ops desk for lean agency operators"
  5597002395f8ea60  "Texas HB 4 security questionnaire prep for DIR-contract SaaS vendors"

Each was told to "say the trade instead", and the trade is what each was already saying. The
other sixteen are genuine coinages and still block.

Same founder principle as the shelf-copy demotion of the same day: a rule that stops a sale
has to grade something that is wrong.
"""
from __future__ import annotations

import unittest

from prospector.pack_linter import KNOWN_PRODUCT_NAMES, check_title


def _errors(title):
    return [p for p in check_title(title, block=True) if p["severity"] == "error"]


def _coinage(title):
    return [p for p in check_title(title, block=True) if "coined product name" in p["detail"]]


class TestTheThreeBlockedTitles(unittest.TestCase):
    """Verbatim from the receipts. Each must stop being refused for its product name."""

    def test_github_advanced_security(self):
        self.assertEqual(
            _coinage("GitHub Advanced Security alert summaries for lean dev teams"), [])

    def test_aws_devops(self):
        self.assertEqual(_coinage("AWS DevOps ops desk for lean agency operators"), [])

    def test_saas_vendors(self):
        self.assertEqual(
            _coinage("Texas HB 4 questionnaire prep for DIR-contract SaaS vendors"), [])


class TestAGenuineCoinageStillBlocks(unittest.TestCase):
    """The exemption is a vocabulary list, not an amnesty."""

    def test_the_leading_coinage(self):
        problems = _coinage("LicenceCraft, The Local Council Licensing Application Optimizer")
        self.assertTrue(problems)
        self.assertIn("'LicenceCraft'", problems[0]["detail"])
        self.assertEqual(problems[0]["severity"], "error")

    def test_a_coinage_beside_a_known_name(self):
        """The known word must not shadow the coinage sitting next to it."""
        problems = _coinage("ComputeSheet, where GitHub teams track GPU supply")
        self.assertTrue(problems)
        self.assertIn("'ComputeSheet'", problems[0]["detail"])

    def test_the_exemption_is_the_whole_word(self):
        """`GitHubbery` is a coinage that happens to start with a product name."""
        problems = _coinage("GitHubbery, the alert triage service for lean dev teams")
        self.assertTrue(problems)
        self.assertIn("'GitHubbery'", problems[0]["detail"])


class TestTheFindingSaysWhereTheNameIs(unittest.TestCase):
    """The message said "leads with" on a rule that searches the whole title, so a receipt
    could tell the writer to rewrite an opener that was fine."""

    def test_a_leading_coinage_says_leads_with(self):
        self.assertIn("leads with a coined product name",
                      _coinage("MouldBreak, the home mould survey for renters")[0]["detail"])

    def test_a_coinage_further_in_says_carries(self):
        self.assertIn("carries a coined product name",
                      _coinage("Damp survey letters built on MouldBreak evidence")[0]["detail"])


class TestTheListItself(unittest.TestCase):
    def test_every_entry_would_otherwise_be_caught(self):
        """An entry the regex never matches is dead weight that reads as a live exemption."""
        from prospector.pack_linter import _TITLE_COINAGE
        dead = sorted(n for n in KNOWN_PRODUCT_NAMES if not _TITLE_COINAGE.fullmatch(n))
        self.assertEqual(dead, [], f"these entries exempt nothing: {dead}")


if __name__ == "__main__":
    unittest.main()
