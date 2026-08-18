"""The rewrite prompt must ask for the length the gate actually enforces.

WHAT WENT WRONG. `shelf_copy_repair.USER` carried its own number, "under 200 characters",
while `field_write.ONE_LINER_CUT_AT` — the only bar the catalogue enforces — is 280. The same
prompt also says "Keep every fact ... Add nothing". On 2026-08-18 pack `83f2e75faa80bb60`
asked MiniMax M3 to cut a 318-character, fact-dense line to under 200 without dropping a
fact. M3 reasoned to its 65536-token ceiling and returned no answer, three times:
`finish_reason=length`, 169,060 characters of reasoning, 23 minutes, $0.059, nothing
produced. A hand-written 262-character line passed the gate immediately — 62 characters
longer than the prompt allowed, and comfortably inside what the catalogue cuts at.

Two numbers for one rule is the defect. The prompt now renders the constant, so the ask and
the grade cannot drift apart again.
"""
from __future__ import annotations

import re
import unittest
from unittest import mock

from prospector import shelf_copy_repair as scr
from prospector.field_write import ONE_LINER_CUT_AT


class RewritePromptCarriesTheGatesLimit(unittest.TestCase):

    def test_the_template_has_no_hardcoded_character_count(self):
        """A literal number here is the bug, whatever its value."""
        literals = re.findall(r"under (\d+) characters", scr.USER)
        self.assertEqual([], literals,
                         f"the prompt hardcodes a length: {literals}. Render "
                         f"ONE_LINER_CUT_AT instead.")
        self.assertIn("{limit}", scr.USER)

    def test_the_rendered_prompt_asks_for_the_gates_number(self):
        """What the brain is actually sent, not what the template looks like."""
        seen = {}

        class _Op:
            def complete_json(self, system, user):
                seen["user"] = user
                return {"one_liner": ""}      # refused; the prompt is what is under test

        scr.rewrite_one(_Op(), "Deposit filing for letting agents", "x " * 200)
        self.assertIn(f"under {ONE_LINER_CUT_AT} characters", seen["user"])
        self.assertNotIn("under 200 characters", seen["user"])

    def test_a_line_inside_the_gate_is_never_asked_to_shrink_further(self):
        """The regression in one sentence: 262 chars passes, so 262 chars is askable.

        `_new_facts` refuses a rewrite that invents, so the fixture reuses the input's own
        words — the point under test is the length ask, not the invention guard.
        """
        line = ("A service for small hospitality businesses that drafts board-ready alcohol "
                "and pavement licence applications, using a database of past local council "
                "decisions to cite the precedents that apply to the venue and write "
                "supporting statements that lift approval odds.")
        self.assertLessEqual(len(line), ONE_LINER_CUT_AT)
        with mock.patch.object(scr, "voice_breaches", return_value=[]), \
             mock.patch.object(scr, "_new_facts", return_value=[]):
            class _Op:
                def complete_json(self, system, user):
                    return {"one_liner": line}

            self.assertEqual(line, scr.rewrite_one(_Op(), "Licence drafting", line))


if __name__ == "__main__":
    unittest.main()
