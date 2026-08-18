"""The character count is the machine's job, and the machine must actually send it.

WHAT WENT WRONG. `shelf_copy_repair.USER` asked for "One sentence, under 200 characters", while
`field_write.ONE_LINER_CUT_AT` — the only length the catalogue enforces — is 280. On 2026-08-18
pack `83f2e75faa80bb60` sent a 318-character, fact-dense line into that ask. MiniMax M3 reasoned
to its 65536-token ceiling and returned nothing, three times: 23 minutes, $0.059, no answer.

The obvious fix was to render 280 in the prompt instead of 200. It was measured against the live
provider, same model and same line, and it does not work:

    limit=200   601s   no answer (the streamed response hit the 600s deadline)
    limit=280   254s   a 320-character line — over the gate anyway

A number in the prompt does not control the length of the reply. So the number came out of the
prompt, and three things now carry it instead, each pinned below:

  1. `rewrite_one` measures its own answer and re-asks with the exact overage.
  2. `_propose_one_liner` passes `field_write._reject_feedback` through to the prompt. It used to
     drop it, so the loop computed the count and then discarded it.
  3. The one-liner gets two attempts, so that feedback can actually be sent. At one attempt the
     rejection was assembled on the way out of the loop and never used.
"""
from __future__ import annotations

import re
import unittest
from unittest import mock

from prospector import field_write
from prospector import shelf_copy_repair as scr
from prospector.field_write import ONE_LINER_CUT_AT


class _Op:
    """Records every prompt it is sent and replies from a scripted list."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete_json(self, system, user):
        self.prompts.append(user)
        return {"one_liner": self.replies.pop(0) if self.replies else ""}


class TheAskCarriesNoCharacterBudget(unittest.TestCase):

    def test_the_prompt_states_no_character_count(self):
        """A length in the ask is the defect, whatever its value — 200 and 280 both failed."""
        self.assertEqual([], re.findall(r"under (\d+) characters", scr.USER))
        self.assertNotIn("{limit}", scr.USER)

    def test_it_tells_the_model_the_count_is_not_its_job(self):
        op = _Op("")
        scr.rewrite_one(op, "Licence drafting", "x " * 200)
        self.assertIn("Do not count characters", op.prompts[0])


class TheMachineMeasuresAndSaysByHowMuch(unittest.TestCase):

    def test_an_over_long_answer_is_re_asked_with_the_exact_overage(self):
        """The number in the retry is arithmetic, not a guess."""
        long = "A " + ("word " * 90)          # comfortably over the cut
        self.assertGreater(len(long), ONE_LINER_CUT_AT)
        op = _Op(long, "")
        with mock.patch.object(scr, "voice_breaches", return_value=[]), \
             mock.patch.object(scr, "_new_facts", return_value=[]):
            scr.rewrite_one(op, "T", "the original line")

        self.assertEqual(2, len(op.prompts), "the over-long answer was not re-asked")
        over = len(long.strip()) - ONE_LINER_CUT_AT
        self.assertIn(f"lose {over} characters", op.prompts[1])
        self.assertIn(str(ONE_LINER_CUT_AT), op.prompts[1])

    def test_a_line_inside_the_cut_is_accepted_untouched(self):
        line = ("A service for small hospitality businesses that drafts board-ready alcohol "
                "and pavement licence applications, using a database of past local council "
                "decisions to cite the precedents that apply to the venue.")
        self.assertLessEqual(len(line), ONE_LINER_CUT_AT)
        op = _Op(line)
        with mock.patch.object(scr, "voice_breaches", return_value=[]), \
             mock.patch.object(scr, "_new_facts", return_value=[]):
            self.assertEqual(line, scr.rewrite_one(op, "T", line))
        self.assertEqual(1, len(op.prompts), "a clean answer must not be re-asked")


class TheRejectionReachesThePrompt(unittest.TestCase):

    def test_propose_one_liner_passes_the_feedback_through(self):
        """It used to drop it, so every attempt sent an identical prompt."""
        seen = {}

        def _fake(op, title, current, feedback=""):
            seen["feedback"] = feedback
            return None

        cand = mock.Mock(title="T", one_liner="L")
        with mock.patch.object(scr, "rewrite_one", _fake):
            field_write._propose_one_liner(cand, "L", "REJECTED: 320 chars", 2, object())
        self.assertEqual("REJECTED: 320 chars", seen["feedback"])

    def test_the_feedback_is_appended_to_the_prompt_it_is_given(self):
        op = _Op("")
        scr.rewrite_one(op, "T", "L", feedback="REJECTED: 320 chars — lose 40")
        self.assertIn("REJECTED: 320 chars — lose 40", op.prompts[0])

    def test_the_one_liner_gets_more_than_one_attempt(self):
        """At one attempt the rejection is built on the way out and never sent."""
        self.assertGreaterEqual(field_write.FIELDS["one_liner"].attempts, 2)


if __name__ == "__main__":
    unittest.main()
