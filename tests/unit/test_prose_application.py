"""The measured human target, APPLIED and CORRECTED, not merely reported.

`test_prose_target.py` pins the measurement and the grading. This file pins the two things
that act on it, which is the gap the founder named on 2026-08-16: "prevention is one thing
but application and correction are also critical."

  APPLY   — the armed measures reach the model BEFORE it writes, through the house voice
            guide every prose template already carries.
  CORRECT — a finished draft outside the human range earns one rewrite turn, and never
            blocks the sale.

The fence that matters most here is the last one. `violations` is wired to a listing gate
(`listing.claim_check_block`), the register interval is the human 5th-95th percentile, and
one human document in ten falls outside it on any single measure. A register finding that
reached `violations` would unlist packs a human author would also have failed.
"""

from __future__ import annotations

import pytest

from prospector import artifacts, prompts, prose_target
from prospector.prompts import ALL_MARKET_KEYS

# A draft that stacks hyphenated compounds the way the engine actually does. The test
# asserts this is genuinely outside the range before relying on it, rather than trusting
# the fixture to be what it claims.
_OFFENDING_DRAFT = (
    "Front-Door Key-Safe Re-Siting is a multi-council, cross-tenure, high-volume "
    "service-delivery workstream; it is a end-to-end, fully-managed, single-point-of-contact "
    "operating-model change; the in-house, business-as-usual, day-to-day team cannot "
    "absorb the additional first-line, second-line and third-line demand. "
) * 6


class _RecordingOperator:
    """Returns a canned draft per call and keeps every prompt it was shown."""

    def __init__(self, drafts):
        self.drafts = list(drafts)
        self.calls = []

    def complete_json(self, system, user, temperature=0.3, validate=None, coerce=None):
        self.calls.append({"system": system, "user": user})
        draft = self.drafts[min(len(self.calls) - 1, len(self.drafts) - 1)]
        return {"content": draft}


def _market_vars():
    return {k: "" for k in ALL_MARKET_KEYS}


# ---------------------------------------------------------------------------
# APPLY
# ---------------------------------------------------------------------------

def test_every_armed_measure_carries_an_instruction_for_the_writer():
    """The linter's advice and the writer's instruction cover the same measures.

    An armed measure that reached the grader but not the generator is exactly the defect
    memory `the-generator-was-never-shown-the-scorers-rubric.md` records.
    """
    armed = set(prose_target.armed_measures())
    assert set(prose_target.PROMPT_RULE) == armed
    assert set(prose_target.ADVICE) == set(prose_target.PROMPT_RULE)
    for measure, sides in prose_target.PROMPT_RULE.items():
        assert set(sides) == {"above", "below"}, measure
        for side, text in sides.items():
            assert text.strip(), f"{measure}/{side} is empty"


def test_the_prompt_block_names_the_measures_we_actually_fall_off():
    block = prose_target.prompt_block()
    assert block, "the shipped target must produce a block"
    armed = prose_target.armed_measures()
    for measure, spec in armed.items():
        rule = prose_target.PROMPT_RULE[measure][spec["side"]]
        # The first clause of each rule is enough to prove the right SIDE was rendered.
        assert rule.split(".")[0] in block, f"{measure} missing from the prompt block"


def test_the_prompt_block_obeys_the_house_voice_it_is_appended_to():
    """No dashes, per `prompts/style/voice.md`. A style block that breaks the style rules
    teaches the model the rule is optional."""
    block = prose_target.prompt_block()
    assert "—" not in block, "em dash in the style block"
    assert "–" not in block, "en dash in the style block"
    assert " - " not in block.replace("\n  - ", "\n"), "spaced hyphen standing in for a dash"


def test_the_writer_is_shown_the_target_through_the_house_voice_guide():
    """The seam. `style_guide` reaches generate, refine, revise, content_gen, artifacts and
    retitle, so proving it here proves it for all six."""
    guide = prompts.style_kwargs()["style_guide"]
    assert "HOW HUMANS ACTUALLY WRITE" in guide
    assert prose_target.prompt_block() in guide
    # The voice guide itself must survive; this appends, never replaces.
    assert "ONE IDEA PER SENTENCE" in guide


def test_an_unreadable_target_leaves_generation_exactly_as_it_was(monkeypatch):
    """A missing target must not stop a pack being WRITTEN. The linter is where that outage
    is said out loud, because there it can stop a pack listing and be seen."""
    def _boom(*a, **k):
        raise prose_target.TargetUnreadable("gone")

    monkeypatch.setattr(prose_target, "armed_measures", _boom)
    assert prose_target.prompt_block() == ""


# ---------------------------------------------------------------------------
# CORRECT
# ---------------------------------------------------------------------------

def test_the_offending_draft_is_genuinely_outside_the_human_range():
    """Prove the probe fires on the before-state, or the repair test proves nothing."""
    findings = prose_target.grade_text(_OFFENDING_DRAFT)
    assert findings, "fixture is not actually outside the human range"


def test_repair_feedback_is_empty_when_nothing_is_wrong():
    assert prose_target.repair_feedback([]) == ""


def test_a_draft_outside_the_human_range_earns_a_rewrite_turn():
    op = _RecordingOperator([_OFFENDING_DRAFT, "A short clean second draft."])
    t, content, raw, violations = artifacts._gen_one_artifact(
        op, "{}", "[]", "build_spec", _market_vars(), "", None, [], True)

    assert len(op.calls) == 2, "the draft was never corrected"
    assert "outside the range of human writing" in op.calls[1]["user"]
    assert content == "A short clean second draft."
    assert raw is None


def test_the_rewrite_turn_is_shown_the_measures_and_the_numbers():
    op = _RecordingOperator([_OFFENDING_DRAFT, "A short clean second draft."])
    artifacts._gen_one_artifact(
        op, "{}", "[]", "build_spec", _market_vars(), "", None, [], True)

    repair = op.calls[1]["user"]
    findings = prose_target.grade_text(_OFFENDING_DRAFT)
    rule = prose_target.PROMPT_RULE[findings[0]["measure"]][findings[0]["side"]]
    assert rule.split(".")[0] in repair
    assert "this draft:" in repair
    # It must not tell the model to change the evidence to fix its sentences.
    assert "Do not change any figure" in repair


def test_a_register_finding_never_blocks_the_sale():
    """The fence. `violations` drives `listing.claim_check_block`; register findings must
    not ride it, however badly the final draft reads."""
    op = _RecordingOperator([_OFFENDING_DRAFT, _OFFENDING_DRAFT])
    _, content, _, violations = artifacts._gen_one_artifact(
        op, "{}", "[]", "build_spec", _market_vars(), "", None, [], True)

    assert len(op.calls) == 2, "both attempts should have run"
    assert violations == [], "a style measure reached the listing gate"
    assert content, "the document is kept even when it never came into range"


def test_the_repair_turn_can_be_switched_off():
    op = _RecordingOperator([_OFFENDING_DRAFT])
    artifacts._gen_one_artifact(
        op, "{}", "[]", "build_spec", _market_vars(), "", None, [], False)
    assert len(op.calls) == 1


def test_a_clean_draft_costs_no_second_call(monkeypatch):
    """The trigger is the finding, not the flag."""
    monkeypatch.setattr(prose_target, "grade_text", lambda *a, **k: [])
    op = _RecordingOperator(["A perfectly ordinary paragraph."])
    artifacts._gen_one_artifact(
        op, "{}", "[]", "build_spec", _market_vars(), "", None, [], True)
    assert len(op.calls) == 1


def test_a_non_prose_artifact_is_never_graded_on_register(monkeypatch):
    """financial_model is a JSON fill rendered by a Python template. Its shape is a property
    of the template, not of the model's restraint."""
    called = []
    monkeypatch.setattr(artifacts, "_prose_findings",
                        lambda c: called.append(c) or [])
    op = _RecordingOperator([_OFFENDING_DRAFT])
    artifacts._gen_one_artifact(
        op, "{}", "[]", "marketing_email", _market_vars(), "", None, [], True)
    assert called == []


def test_a_broken_measurement_never_breaks_generation(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("measurement exploded")

    monkeypatch.setattr(prose_target, "grade_text", _boom)
    op = _RecordingOperator(["A paragraph."])
    _, content, _, violations = artifacts._gen_one_artifact(
        op, "{}", "[]", "build_spec", _market_vars(), "", None, [], True)
    assert content == "A paragraph."
    assert violations == []


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,expected", [
    (None, True),
    ({"listing": {}}, True),
    ({"listing": {"human_register_repair": False}}, False),
    ({"listing": {"human_register_repair": True}}, True),
])
def test_the_repair_switch_is_config_declared(cfg, expected):
    assert artifacts.prose_repair_enabled(cfg) is expected


def test_repair_and_block_are_separate_switches():
    """Turning the blocker off must not turn the rewrite off. They are different acts: one
    refuses to sell a finished pack, the other spends a model call on a draft."""
    cfg = {"listing": {"human_register_block": False}}
    assert artifacts.prose_repair_enabled(cfg) is True
