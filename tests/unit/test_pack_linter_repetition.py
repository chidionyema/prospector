"""The repetition check, graded on the ASSEMBLED pack rather than on any one document.

`check_repetition` existed, was commented as live in four renderers, and had zero callers
until 2026-08-15. That is the defect these tests pin from the gate's side: `lint_pack` must
actually run it, over a corpus (`pack_sections`) that is different from `artifacts` — the
four model-written documents — because a sentence printed once in each of two sections is
correct in both files and a defect only in the pack a buyer opens.

Everything here pins BEHAVIOUR (reported / not reported, blocks / does not block), never the
wording of a detail string or the shape of the internal grouping: the check is expected to get
better at describing what it found, and a test that pinned the prose would make that a
breakage. The one implementation detail imported on purpose is
`pack_linter._REPETITION_RESTATES_ON_PURPOSE`, because the exemption is an ARGUMENT about a
named section and the test's job is to prove membership still buys exactly the narrow
downgrade the module's comment claims for it.

Companion to test_q2_pack_linter.py, which owns the rest of the report contract.
"""
from __future__ import annotations

import json

from prospector.pack_linter import _REPETITION_RESTATES_ON_PURPOSE, lint_pack

# Twelve words, no markdown, no list marker, not a heading and not a block quote — i.e. above
# `_REPETITION_MIN_WORDS` and through every deliberate exclusion in `_repetition_sentences`.
# A repeated FACT is what this check is for; section furniture ("Read this before you build.")
# recurs by design and is short enough to be skipped, which is what the floor on length buys.
SHARED = "The council publishes its shellfish closure notices every Thursday morning without fail."

# The exemption is keyed on the buyer-visible TITLE, so the fixture has to use the real one.
# Read from the module rather than typed as a literal: if the exempt set is ever re-argued,
# these tests must move with it instead of silently grading a section that is no longer exempt.
RESTATER = sorted(_REPETITION_RESTATES_ON_PURPOSE)[0]


def _section(body: str) -> str:
    """A section as the renderers emit one: a heading (never graded) over prose."""
    return f"## A section\n\n{body}\n"


def _report(pack_sections=None, **kw):
    """`lint_pack` with every other corpus empty, so the only problems are repetition ones.

    Proven clean at the bottom of this file rather than assumed — a baseline that quietly
    started reporting an unrelated error would make every `ok is False` assertion here pass
    for the wrong reason.
    """
    return lint_pack(
        artifacts={},
        listing_copy="",
        listing_texts={},
        market="uk",
        pack_sections=pack_sections,
        **kw,
    )


def _repetition(report):
    return [p for p in report["problems"] if p["check"] == "repetition"]


class TestASentenceInTwoSectionsIsReported:
    """The defect the corpus exists for: two renderers each decided a fact was worth stating
    and neither knew about the other."""

    def test_the_baseline_with_no_repetition_is_silent(self):
        report = _report({"Where this starts": _section(SHARED),
                          "The numbers": _section("A different claim about the margin here.")})
        assert _repetition(report) == []
        assert report["repetition_findings"] == 0
        assert report["ok"] is True

    def test_a_sentence_printed_in_two_sections_is_a_repetition_problem(self):
        report = _report({"Where this starts": _section(SHARED),
                          "The numbers": _section(SHARED)})
        problems = _repetition(report)
        assert problems, "a sentence printed in two sections was not reported at all"
        # Both sections are named, because a finding that cannot be acted on is not a finding.
        where = " ".join(p["where"] for p in problems)
        assert "Where this starts" in where and "The numbers" in where

    def test_the_report_counts_the_finding(self):
        report = _report({"Where this starts": _section(SHARED),
                          "The numbers": _section(SHARED)})
        assert report["repetition_findings"] == len(_repetition(report)) >= 1

    def test_the_report_still_serializes(self):
        """The receipt is written next to the dossier as JSON; a finding must not break that."""
        report = _report({"Where this starts": _section(SHARED),
                          "The numbers": _section(SHARED)})
        json.dumps(report)


class TestTheActuatorIsOffByDefault:
    """`repetition_block` is deliberately off while a baseline accrues on live packs — the
    same way `check_grammar` and `check_shelf_copy` earn their thresholds. The count is
    recorded pass or fail, so the number the switch is eventually turned on with is one that
    was measured rather than guessed."""

    SECTIONS = {"Where this starts": _section(SHARED), "The numbers": _section(SHARED)}

    def test_the_default_is_a_warning_and_the_pack_still_lists(self):
        report = _report(self.SECTIONS)   # repetition_block not passed at all
        assert all(p["severity"] == "warning" for p in _repetition(report))
        assert report["ok"] is True

    def test_passing_false_explicitly_is_the_same(self):
        report = _report(self.SECTIONS, repetition_block=False)
        assert all(p["severity"] == "warning" for p in _repetition(report))
        assert report["ok"] is True

    def test_the_finding_is_still_counted_while_the_actuator_is_off(self):
        """The whole point of grading without blocking: the receipt accrues anyway."""
        assert _report(self.SECTIONS, repetition_block=False)["repetition_findings"] >= 1

    def test_with_the_switch_on_the_same_input_blocks(self):
        report = _report(self.SECTIONS, repetition_block=True)
        assert any(p["severity"] == "error" for p in _repetition(report))
        assert report["ok"] is False


class TestTheOldCallShapeStillWorks:
    """`pack_sections` arrived in 2026-08-15 as a keyword with a None default. Every caller
    that predates it — the backfill tools, the tests, anything grading the four artifacts
    alone — must keep working and must not be told a pack is clean on a corpus it never
    supplied."""

    def test_no_sections_grades_nothing(self):
        report = _report(None)
        assert report["sections_graded"] == 0
        assert report["repetition_findings"] == 0
        assert _repetition(report) == []

    def test_the_parameter_can_be_omitted_entirely(self):
        report = lint_pack(artifacts={}, listing_copy="", listing_texts={}, market="uk")
        assert report["sections_graded"] == 0
        assert report["ok"] is True

    def test_sections_graded_counts_what_was_handed_over(self):
        """The receipt's own answer to "was the whole pack graded, or nine of fourteen?" —
        which is the question the Q2 gate could not answer before this wiring existed."""
        report = _report({"Where this starts": _section("One."),
                          "The numbers": _section("Two."),
                          "What you build": _section("Three.")})
        assert report["sections_graded"] == 3

    def test_an_empty_mapping_grades_nothing_and_does_not_crash(self):
        report = _report({})
        assert report["sections_graded"] == 0
        assert report["ok"] is True


class TestTheSectionThatRestatesOnPurpose:
    """"Copy you can paste" hands the buyer a headline, a one-line description and a proof
    point to lift into a landing page. Every one of those is BY DEFINITION a line printed
    elsewhere in the pack, so blocking it would mean the only way to ship is to make the
    paste-ready copy differ from the pack it came out of — a worse pack and a false claim.

    Membership buys a downgrade, not a waiver, and only while exactly one other section is
    involved. Both halves are pinned: a section that starts absorbing whole sections still
    blocks.
    """

    def test_the_exempt_set_is_the_one_named_section(self):
        assert RESTATER == "Copy you can paste"

    def test_sharing_with_exactly_one_other_section_does_not_block(self):
        report = _report({RESTATER: _section(SHARED),
                          "The numbers": _section(SHARED)},
                         repetition_block=True)
        assert report["ok"] is True, "the restating section blocked a pack it is exempt from"
        assert all(p["severity"] == "warning" for p in _repetition(report))

    def test_the_downgraded_finding_is_still_reported(self):
        """Downgraded, never waived — a renderer that starts copying into it stays visible."""
        report = _report({RESTATER: _section(SHARED),
                          "The numbers": _section(SHARED)},
                         repetition_block=True)
        assert report["repetition_findings"] >= 1

    def test_sharing_with_two_other_sections_still_blocks(self):
        report = _report({RESTATER: _section(SHARED),
                          "The numbers": _section(SHARED),
                          "What you build": _section(SHARED)},
                         repetition_block=True)
        assert report["ok"] is False
        assert any(p["severity"] == "error" for p in _repetition(report))

    def test_two_unexempt_sections_block_even_next_to_the_exempt_one(self):
        """The exemption is not ambient: a pack that HAPPENS to contain the restating section
        does not thereby get its other duplication forgiven."""
        report = _report({RESTATER: _section("A paste-ready headline that shares nothing here."),
                          "The numbers": _section(SHARED),
                          "What you build": _section(SHARED)},
                         repetition_block=True)
        assert report["ok"] is False
