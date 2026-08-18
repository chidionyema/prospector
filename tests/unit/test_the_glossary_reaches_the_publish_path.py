"""The operator's glossary now runs where packs are MADE, not only where they are cured.

Measured 2026-08-18 across the 123 lint receipts in the canonical store: 65 packs could not
list, and `shelf_copy` held 41 of them. Twenty of those were held by an unexplained initialism
alone, and fifteen of the terms already had a declared expansion sitting in
`config.yaml listing.initialism_glossary`. Nothing on the publish path ever ran the expander --
`rg -l initialism_glossary` returned the sweep, the linter and config, and the sweep is
hand-run. So packs stayed off the shelf for want of words that were already on disk.

The rule these tests defend: a declared expansion is pasted in for free, and an UNdeclared one
is never handed to a brain. An expansion is a fact, and this is a source-or-die storefront.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prospector import field_write, shelf_copy_repair  # noqa: E402

GLOSS = {"HSE": "Health and Safety Executive", "IFA": "independent financial adviser"}


class Cand:
    def __init__(self, title: str = "", one_liner: str = ""):
        self.candidate_id = "c1"
        self.title = title
        self.one_liner = one_liner


class ExplodingOperator:
    """Any call is a test failure. The whole point is that these repairs cost nothing."""

    def complete_json(self, *a, **k):  # pragma: no cover - only reached on a regression
        raise AssertionError("a model was called for a repair the glossary could do")


@pytest.fixture()
def gloss(monkeypatch):
    monkeypatch.setattr(shelf_copy_repair, "glossary", lambda: dict(GLOSS))
    return GLOSS


def test_an_unexplained_initialism_is_now_a_breach_the_writer_can_see():
    # It always blocked publication. It just never reached the grader the writer runs, so the
    # first anyone heard of it was the publish gate refusing a pack that had already been paid
    # for.
    why = field_write.grade_one_liner("A compliance service for HSE inspections.", Cand())
    assert any(b.startswith(field_write.INITIALISM_BREACH) for b in why), why


def test_a_term_the_title_spells_out_is_not_a_breach_on_the_line():
    # The buyer reads the page, not the field. The publish gate grades it this way too
    # (`pack_linter.py:1376` builds its context from every graded field), and a grader that
    # disagreed with the gate would send the writer chasing a breach the gate does not raise.
    cand = Cand(title="Health and Safety Executive (HSE) notice service")
    why = field_write.grade_one_liner("A compliance service for HSE inspections.", cand)
    assert not [b for b in why if b.startswith(field_write.INITIALISM_BREACH)], why


def test_a_declared_expansion_is_pasted_in_with_no_model_call(gloss):
    cand = Cand(title="Notice response service",
                one_liner="A compliance service for HSE inspections.")
    outcome = field_write.repair(cand, "one_liner", op=ExplodingOperator())

    assert outcome.repaired is True
    # Zero attempts: the deterministic pass sits OUTSIDE the attempt budget, so it cannot eat
    # the tries the model needs for the breaches only a rewrite can fix.
    assert outcome.attempts_used == 0
    assert "Health and Safety Executive (HSE)" in cand.one_liner
    assert field_write.grade_one_liner(cand.one_liner, cand) == []


def test_an_undeclared_term_is_never_handed_to_a_brain(gloss):
    # METRC is a product name, not an initialism anyone can expand. Asking a model to spell it
    # out is asking it to invent a fact. The honest answer is that the pack stays off the shelf
    # until the operator declares the words or rewords the copy.
    original = "A compliance service for METRC reconciliation."
    cand = Cand(title="Reconciliation service", one_liner=original)
    outcome = field_write.repair(cand, "one_liner", op=ExplodingOperator())

    assert outcome.repaired is False
    assert cand.one_liner == original
    assert all(b.startswith(field_write.INITIALISM_BREACH) for b in outcome.after), outcome.after


def test_a_model_still_runs_when_something_other_than_an_initialism_is_wrong(gloss):
    # Second person is a voice defect, which is exactly what a rewrite is for. The model must
    # be handed the line the glossary already improved, not the raw one -- otherwise the free
    # repair is thrown away and the model is asked to do both jobs.
    seen: list[str] = []

    def fake_rewrite(op, title, line, feedback=""):
        seen.append(line)
        return "A compliance service run by Health and Safety Executive (HSE) inspectors."

    import prospector.shelf_copy_repair as scr
    original_rewrite = scr.rewrite_one
    scr.rewrite_one = fake_rewrite
    try:
        cand = Cand(title="Notice response service",
                    one_liner="Your compliance service for HSE inspections.")
        outcome = field_write.repair(cand, "one_liner", op=ExplodingOperator())
    finally:
        scr.rewrite_one = original_rewrite

    assert seen, "the model was never asked to fix the voice breach"
    assert "Health and Safety Executive (HSE)" in seen[0], seen[0]
    assert outcome.repaired is True


def test_an_expansion_that_pushes_the_line_over_the_cut_is_discarded(gloss):
    # An expansion makes a line longer and the catalogue's cut is a breach too. A pass that
    # trades an unexplained initialism for a line that trails off on the shelf has helped
    # nobody, so the pass is kept only when the breach count strictly goes down.
    filler = "a" * (field_write.ONE_LINER_CUT_AT - 40)
    line = f"A service for HSE inspections {filler}."
    assert len(line) <= field_write.ONE_LINER_CUT_AT
    expanded = field_write._expand_one_liner(line, Cand())
    assert expanded is not None and len(expanded) > field_write.ONE_LINER_CUT_AT

    cand = Cand(title="Notice response service", one_liner=line)
    outcome = field_write.repair(cand, "one_liner", op=ExplodingOperator())

    assert cand.one_liner == line
    assert any("discarded" in t for t in outcome.trail), outcome.trail


def test_the_expander_lives_in_the_package_so_the_engine_can_import_it():
    # It lived in `tools/sweep_shelf_copy.py`, which the package cannot import. That is the
    # whole reason the publish path never ran it. One definition, two callers.
    sys.path.insert(0, str(ROOT / "tools"))
    import sweep_shelf_copy  # noqa: PLC0415

    assert sweep_shelf_copy.expand_initialisms is shelf_copy_repair.expand_initialisms
