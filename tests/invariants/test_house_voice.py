"""House-voice invariants: the dossier must read like plain English, and saying so
must not cost the engine any of its evidence discipline.

Four failure modes, all silent if unguarded:
  1. A `{style_guide}`/`{rationale_style}` placeholder ships to the model verbatim
     because a render site forgot it.
  2. The voice file goes missing or empty and every prompt quietly loses its tone.
  3. The moat gets the buyer-facing voice ("warm, like a knowledgeable friend"),
     which is the wrong instruction for a verdict and could soften the ruling.
  4. The rationale style stops fencing itself off from the ruling, so a WORDING
     instruction starts influencing WHAT gets decided.
"""
from __future__ import annotations

import re
from pathlib import Path

from prospector import prompts
from prospector.config import load_config

PROMPTS_DIR = Path(prompts.PROMPTS_DIR)
STYLE_PLACEHOLDER = re.compile(r"\{(style_guide|rationale_style)\}")

# The prompts that write prose a human reads in a dossier or a listing.
PROSE_PROMPTS = {"generate_system", "refine_system", "verdict", "adversarial",
                 "artifacts", "content_gen", "score"}

# Ruled by the moat: these get the fenced rationale style, never the buyer voice.
MOAT_PROMPTS = {"verdict", "adversarial"}


def _prompt_files() -> list[Path]:
    return sorted(PROMPTS_DIR.glob("*.md"))


# ---------------------------------------------------------------------------
# 1 & 2. The voice exists and is wired
# ---------------------------------------------------------------------------

def test_the_voice_files_exist_and_say_something():
    kw = prompts.style_kwargs()
    assert set(kw) == set(prompts.STYLE_KEYS)
    for key, text in kw.items():
        assert len(text) > 200, f"{key} is empty or a stub — every prompt loses its tone"


def test_every_prose_prompt_asks_for_the_voice():
    """A prompt that writes prose a human reads must import the house voice rather
    than restate a tone of its own, or the two drift apart."""
    for name in sorted(PROSE_PROMPTS):
        text = (PROMPTS_DIR / f"{name}.md").read_text()
        assert STYLE_PLACEHOLDER.search(text), (
            f"{name}.md produces reader-facing prose but never asks for the house "
            f"voice. Add {{style_guide}} (or {{rationale_style}} inside the moat).")


def test_the_voice_is_substituted_without_the_caller_lifting_a_finger():
    """Auto-injection is the whole point: a call site cannot forget what it never
    has to pass."""
    for name in sorted(PROSE_PROMPTS):
        system, user = prompts.render(name)
        assert not STYLE_PLACEHOLDER.search(system + user), (
            f"{name}.md rendered with a literal style placeholder still in it")


def test_an_explicit_caller_value_still_wins():
    system, user = prompts.render("verdict", rationale_style="OVERRIDDEN")
    assert "OVERRIDDEN" in system + user


# ---------------------------------------------------------------------------
# 3 & 4. The moat keeps its distance
# ---------------------------------------------------------------------------

def test_the_moat_never_gets_the_buyer_voice():
    """The buyer voice is written to sell; a verdict is written to be right. Handing
    'warm, like a knowledgeable friend' to the ruling prompt is a category error."""
    for name in sorted(MOAT_PROMPTS):
        text = (PROMPTS_DIR / f"{name}.md").read_text()
        assert "{style_guide}" not in text, (
            f"{name}.md rules a verdict and must use {{rationale_style}}, which is "
            f"fenced to wording only")


def test_the_rationale_style_fences_itself_off_from_the_ruling():
    """The one sentence that makes this change safe. If it is ever edited away, a
    style note becomes an instruction that can move verdicts."""
    text = prompts.style_kwargs()["rationale_style"].lower()
    assert "does not touch your ruling" in text
    assert "citation" in text  # clarity must never cost a source


def test_the_voice_forbids_our_internal_vocabulary():
    """The actual cause of cryptic dossiers was our own filing system leaking into
    prose ('Lens: cross_sector', 'the 80%+ single-controller condition')."""
    voice = prompts.style_kwargs()["style_guide"].lower()
    rationale = prompts.style_kwargs()["rationale_style"].lower()
    assert "internal vocabulary" in voice
    assert "durable_wedge_type" in voice  # names the taxonomy tokens explicitly
    assert "internal machinery" in rationale


def test_evidence_rules_survive_the_restyle():
    """A tone change must not have quietly displaced the rules that make a verdict
    worth anything."""
    verdict = (PROMPTS_DIR / "verdict.md").read_text()
    assert "No prior knowledge." in verdict
    assert '"unverifiable"' in verdict
    assert "Cite the source_ids you relied on." in verdict

    content = (PROMPTS_DIR / "content_gen.md").read_text()
    assert "HARD RULE" in content
    assert "claim-check" in content


# ---------------------------------------------------------------------------
# 5. Kill reasons read as plain English
# ---------------------------------------------------------------------------

def test_kill_reasons_no_longer_start_with_gate_jargon():
    """The stored kill reason used to open with Gate 'legality' fired — … which
    leaked filing-system vocabulary into every dossier and adaptive feed."""
    from prospector.dossier import _CHECK_LABEL, build_dossier
    from prospector.models import (
        AdversarialResult,
        Candidate,
        CheckResult,
        Decision,
        Verdict,
    )

    cfg = load_config()
    cand = Candidate(title="Jargon leak probe")
    checks = [CheckResult(
        check_name="legality", verdict=Verdict.REFUTED, confidence=0.9,
        rationale="Cited statute forbids it.",
    )]
    d = build_dossier(cand, checks, None, "legality", None, cfg, "test")
    assert d.decision == Decision.KILL
    assert not d.reason.startswith("Gate '"), d.reason
    assert d.reason.startswith("It failed on:"), d.reason
    assert "`legality`" in d.reason
    assert _CHECK_LABEL["legality"] in d.reason
    assert "Cited statute forbids it." in d.reason
    # adaptive.py still peels substance after the first colon
    substance = d.reason.split(":", 1)[1].strip()
    assert "Cited statute forbids it." in substance

    adv = AdversarialResult(kill_case="A dominant free alternative already exists.",
                            decisive=True, citations=["s1"])
    d2 = build_dossier(cand, [], adv, "adversarial_decisive", None, cfg, "test")
    assert not d2.reason.startswith("Gate '"), d2.reason
    assert "`adversarial_decisive`" in d2.reason
    assert _CHECK_LABEL["adversarial_decisive"] in d2.reason
