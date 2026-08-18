"""The title is repaired before the pack is built, not refused after it is paid for.

Measured 2026-08-17 against the live catalogue: `title` blocked 20 stranded PASS packs and all
20 were created in the previous three days. The rule was never enforced anywhere upstream —
`check_title` was called only by `tools/publish_passes.py` (the gate) and
`tools/retitle_catalogue.py` (a repair tool run by hand on rows that were already stranded).
So a breached title was discovered after a ~7,700-word pack had been generated and vetted, and
nothing downstream could fix it, because the title comes off the Candidate and no marketing
retry touches it.

`run._repair_title` closes that. These tests pin the four properties that make it safe to run
on the money path: it is free when the title is clean, it can only improve, it never loses a
candidate, and it runs before anything is built on the title.
"""
from __future__ import annotations

import unittest
from unittest import mock

from prospector import run as rn
from prospector.models import Candidate
from prospector.pack_linter import TITLE_MAX_CHARS, check_title

# A real breach, not a hand-written assumption: asserted below to be one.
TOO_LONG = ("Automated rota and shift-swap administration for independent NHS locum "
            "agencies in the United Kingdom")
CLEAN = "Rota and shift-swap admin for NHS locum agencies"


def _cand(title: str) -> Candidate:
    return Candidate(title=title, one_liner="Runs the rota so the agency does not.",
                     who_pays="locum agency owners")


def _errors(title: str) -> list[str]:
    return [p["detail"] for p in check_title(title, max_chars=TITLE_MAX_CHARS)
            if p.get("severity") == "error"]


class TestTheFixtures(unittest.TestCase):
    """A repair test whose "broken" input is not broken proves nothing — see the memory
    `a-fixture-with-the-wrong-dash-proved-nothing`."""

    def test_the_broken_title_really_breaches(self):
        self.assertTrue(_errors(TOO_LONG))

    def test_the_clean_title_really_passes(self):
        self.assertEqual(_errors(CLEAN), [])


class TestItCostsNothingWhenTheTitleIsClean(unittest.TestCase):
    def test_no_operator_call_is_made(self):
        op = mock.Mock()
        cand = _cand(CLEAN)
        trail = rn._repair_title(cand, mock.Mock(), op=op)
        self.assertEqual(trail, [])
        op.complete_json.assert_not_called()
        self.assertEqual(cand.title, CLEAN)


class TestItRepairs(unittest.TestCase):
    def test_a_clean_proposal_replaces_the_breached_title(self):
        op = mock.Mock()
        op.complete_json.return_value = {"title": CLEAN}
        cand = _cand(TOO_LONG)
        rn._repair_title(cand, mock.Mock(), op=op)
        self.assertEqual(cand.title, CLEAN)
        self.assertEqual(op.complete_json.call_count, 1)

    def test_the_identity_is_not_rehashed(self):
        """`candidate_id` is the catalogue row and the dossier filename. Recomputing it on a
        retitle would fork the pack in two."""
        op = mock.Mock()
        op.complete_json.return_value = {"title": CLEAN}
        cand = _cand(TOO_LONG)
        before = cand.candidate_id
        rn._repair_title(cand, mock.Mock(), op=op)
        self.assertEqual(cand.candidate_id, before)


class TestItCanOnlyImprove(unittest.TestCase):
    def test_a_proposal_that_still_breaches_is_refused(self):
        op = mock.Mock()
        op.complete_json.return_value = {"title": TOO_LONG + " and also more words"}
        cand = _cand(TOO_LONG)
        rn._repair_title(cand, mock.Mock(), op=op)
        self.assertEqual(cand.title, TOO_LONG)
        self.assertEqual(op.complete_json.call_count, rn._MAX_TITLE_REPAIR_ATTEMPTS)

    def test_a_dead_operator_never_loses_the_candidate(self):
        op = mock.Mock()
        op.complete_json.side_effect = RuntimeError("all operators unavailable")
        cand = _cand(TOO_LONG)
        trail = rn._repair_title(cand, mock.Mock(), op=op)  # must not raise
        self.assertEqual(cand.title, TOO_LONG)
        self.assertTrue(any("call failed" in t for t in trail))

    def test_an_empty_answer_is_retried_then_left_alone(self):
        op = mock.Mock()
        op.complete_json.return_value = {}
        cand = _cand(TOO_LONG)
        rn._repair_title(cand, mock.Mock(), op=op)
        self.assertEqual(cand.title, TOO_LONG)
        self.assertEqual(op.complete_json.call_count, rn._MAX_TITLE_REPAIR_ATTEMPTS)


SECOND_PERSON = ("A tool that keeps your rota full by matching locum shifts to the "
                 "clinicians on your bank.")
CLEAN_LINE = ("A tool for NHS locum agencies that matches open shifts to the clinicians "
              "already on the agency's bank.")
TOO_LONG_LINE = "A rota tool for NHS locum agencies " + ("that fills open shifts " * 14)


class TestTheOneLinerFixtures(unittest.TestCase):
    def test_the_broken_line_really_breaches(self):
        from prospector.shelf_copy_repair import voice_breaches
        self.assertTrue(voice_breaches(SECOND_PERSON))

    def test_the_clean_line_really_passes(self):
        from prospector.shelf_copy_repair import voice_breaches
        self.assertEqual(voice_breaches(CLEAN_LINE), [])
        self.assertLessEqual(len(CLEAN_LINE), rn._ONE_LINER_CUT_AT)

    def test_the_long_line_is_long_enough_to_be_cut(self):
        self.assertGreater(len(TOO_LONG_LINE), rn._ONE_LINER_CUT_AT)


class TestTheOneLinerIsRepairedToo(unittest.TestCase):
    """`bridge.py:843` takes the shelf's one-liner off the Candidate, so no marketing retry
    reaches it. Measured 2026-08-17: `oneLine` blocked 21 stranded passes."""

    def _run(self, line: str, proposal):
        cand = _cand(CLEAN)
        cand.one_liner = line
        with mock.patch("prospector.shelf_copy_repair.rewrite_one",
                        return_value=proposal) as rw:
            trail = rn._repair_one_liner(cand, mock.Mock(), op=mock.Mock())
        return cand, rw, trail

    def test_a_clean_line_costs_nothing(self):
        cand, rw, trail = self._run(CLEAN_LINE, "anything")
        rw.assert_not_called()
        self.assertEqual(trail, [])
        self.assertEqual(cand.one_liner, CLEAN_LINE)

    def test_second_person_is_rewritten(self):
        cand, rw, _ = self._run(SECOND_PERSON, CLEAN_LINE)
        rw.assert_called_once()
        self.assertEqual(cand.one_liner, CLEAN_LINE)

    def test_a_line_the_catalogue_would_cut_is_shortened(self):
        """The cut adds `…` and `check_shelf_copy` then refuses the line for trailing off —
        the engine manufacturing the defect it rejects. 9 of the 21 fail exactly this way."""
        cand, rw, _ = self._run(TOO_LONG_LINE, CLEAN_LINE)
        rw.assert_called_once()
        self.assertEqual(cand.one_liner, CLEAN_LINE)

    def test_a_rewrite_that_is_still_too_long_is_refused(self):
        cand, _, trail = self._run(TOO_LONG_LINE, TOO_LONG_LINE + " more")
        self.assertEqual(cand.one_liner, TOO_LONG_LINE)
        self.assertTrue(any("rejected" in t for t in trail))

    def test_a_refused_rewrite_keeps_the_candidate_s_line(self):
        cand, _, trail = self._run(SECOND_PERSON, None)
        self.assertEqual(cand.one_liner, SECOND_PERSON)
        self.assertTrue(any("rejected" in t for t in trail))

    def test_a_dead_operator_never_loses_the_candidate(self):
        cand = _cand(CLEAN)
        cand.one_liner = SECOND_PERSON
        with mock.patch("prospector.shelf_copy_repair.rewrite_one",
                        side_effect=RuntimeError("all operators unavailable")):
            trail = rn._repair_one_liner(cand, mock.Mock(), op=mock.Mock())  # must not raise
        self.assertEqual(cand.one_liner, SECOND_PERSON)
        self.assertTrue(any("call failed" in t for t in trail))


class TestOneDefinitionTwoCallers(unittest.TestCase):
    """The engine and the live-shelf sweep must never disagree about what a clean line is."""

    def test_the_sweep_uses_the_same_objects(self):
        import prospector.shelf_copy_repair as repair
        import tools.sweep_shelf_copy as sweep
        self.assertIs(sweep.breaches, repair.breaches)
        self.assertIs(sweep.voice_breaches, repair.voice_breaches)
        self.assertIs(sweep.rewrite_one, repair.rewrite_one)


class TestItRunsBeforeThePackIsBuilt(unittest.TestCase):
    """The whole point is the ORDER. Repairing the title after the artifacts are written
    would leave every document inside the pack talking about the old one."""

    def test_the_title_is_repaired_before_generate_artifacts_reads_it(self):
        seen: list[str] = []
        cand = _cand(TOO_LONG)

        def _fake_repair(c, cfg, *, op):
            c.title = CLEAN
            seen.append(f"repair:{c.title}")
            return []

        def _fake_artifacts(op, c, checks, **kw):
            seen.append(f"artifacts:{c.title}")
            return {"build_spec": "x"}

        # `_generate_pack_content` imports these INSIDE the function, so they are patched on
        # the modules they come from, not on `run`.
        with mock.patch.object(rn, "_repair_title", _fake_repair), \
             mock.patch("prospector.artifacts.generate_artifacts", _fake_artifacts), \
             mock.patch("prospector.artifacts.generate_marketing_content", return_value=[]), \
             mock.patch("prospector.pack_validation.validate_pack", return_value=(True, [])), \
             mock.patch.object(rn, "_shelf_copy_breaches", return_value=[]):
            # The escalation chain is read off cfg (`_escalation_order`, run.py:1103) and
            # `list()`ed. A bare Mock answers that attribute with another Mock, which is
            # truthy and not iterable, so this raised TypeError before it reached the thing
            # the test is about. Empty chains: this test is about ORDER, not escalation.
            rn._generate_pack_content(mock.Mock(), cand, [], query_op=mock.Mock(),
                                      quality_op=mock.Mock(),
                                      cfg=mock.Mock(artifact_operator=[], marketing_operator=[]),
                                      score=None)

        self.assertEqual(seen, [f"repair:{CLEAN}", f"artifacts:{CLEAN}"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
