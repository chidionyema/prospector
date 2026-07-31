"""Market prompt injection invariants (spec D3 / DD6).

Three failure modes are guarded here, all silent if unguarded:
  1. A `{market_*}` placeholder whose call site forgot the kwarg ships VERBATIM to the
     model — a quality regression that raises no error.
  2. The moat (verdict / adversarial) receiving rich market prose, which invites ruling
     from prior knowledge instead of from retrieved passages.
  3. De-hardcoding the UK examples losing what those examples taught.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from prospector import prompts
from prospector.config import load_config

PROMPTS_DIR = Path(prompts.PROMPTS_DIR)
MARKET_PLACEHOLDER = re.compile(r"\{(market_[a-z_]+|currency_hint)\}")

# Prompts that are ruled by the moat. These may reference only MOAT_MARKET_KEYS.
MOAT_PROMPTS = {"verdict", "adversarial"}


def _prompt_files() -> list[Path]:
    return sorted(p for p in PROMPTS_DIR.glob("*.md"))


def _placeholders(text: str) -> set[str]:
    return set(MARKET_PLACEHOLDER.findall(text))


# ---------------------------------------------------------------------------
# 1. Every placeholder is wired
# ---------------------------------------------------------------------------

def test_every_market_placeholder_is_produced_by_market_kwargs():
    cfg = load_config()
    known = set(prompts.market_kwargs(cfg))
    for path in _prompt_files():
        for name in _placeholders(path.read_text()):
            assert name in known, (
                f"{path.name} uses {{{name}}} but market_kwargs() never produces it — "
                f"the literal token would be sent to the model")


def test_no_market_placeholder_survives_rendering():
    """Render every prompt with its market kwargs and assert nothing leaks."""
    cfg = load_config()
    for path in _prompt_files():
        name = path.stem
        if name.endswith("_system"):
            continue  # rendered as part of its parent prompt
        kwargs = prompts.market_kwargs(cfg, for_moat=name in MOAT_PROMPTS)
        system, user = prompts.render(name, **kwargs)
        assert "{market_" not in system, f"{name} system leaked a market placeholder"
        assert "{market_" not in user, f"{name} user leaked a market placeholder"
        assert "{currency_hint}" not in system + user, f"{name} leaked currency_hint"


# ---------------------------------------------------------------------------
# 2. The moat restriction (DD6)
# ---------------------------------------------------------------------------

def test_moat_prompts_reference_only_the_restricted_key_set():
    for name in MOAT_PROMPTS:
        text = (PROMPTS_DIR / f"{name}.md").read_text()
        used = _placeholders(text)
        illegal = used - set(prompts.MOAT_MARKET_KEYS)
        assert not illegal, (
            f"{name}.md references {illegal}, which is outside MOAT_MARKET_KEYS. The "
            f"verdict brain must not receive market prose — it rules from passages only.")


def test_market_kwargs_for_moat_excludes_the_rich_context():
    cfg = load_config()
    moat = prompts.market_kwargs(cfg, for_moat=True)
    assert set(moat) == set(prompts.MOAT_MARKET_KEYS)
    assert "market_context" not in moat


def test_market_scope_is_derived_from_the_label_alone():
    """Structural guarantee: the moat's market variable is a NAME, never a fact, so it
    cannot smuggle claims about the market into the verdict prompt."""
    cfg = load_config().for_market("us")
    scope = prompts.market_kwargs(cfg, for_moat=True)["market_scope"]
    label = cfg.market_config()["label"]
    assert scope == f"Jurisdiction under evaluation: {label}."
    # The rich prose exists but must not appear anywhere in the moat's variable.
    context = cfg.market_config()["market_context"]
    assert context.strip() not in scope


def test_verdict_prompt_keeps_its_retrieval_only_instruction():
    text = (PROMPTS_DIR / "verdict.md").read_text()
    assert "Rule ONLY from the passages" in text
    assert "No prior knowledge." in text
    # And the market line explicitly disclaims being evidence.
    assert "is not admissible" in text


# ---------------------------------------------------------------------------
# 3. De-hardcoding is lossless
# ---------------------------------------------------------------------------

def test_uk_fragments_carry_the_previously_inline_examples():
    """The UK exemplars moved from the prompt body into prompts/markets/uk/. The content
    must survive the move — that is what makes the de-hardcoding lossless."""
    cfg = load_config()
    kw = prompts.market_kwargs(cfg)

    assert "NHS nurse pension additional voluntary contributions take-up UK" in kw["market_exemplars"]
    assert "Sensitech Berlinger pharma cold chain monitoring incumbents" in kw["market_exemplars"]
    assert "NHS nurse pension additional voluntary contributions take-up UK" in kw["market_batched_exemplars"]

    verdict_ex = prompts.market_kwargs(cfg, for_moat=True)["market_verdict_exemplars"]
    assert "[PRECEDENT 2 — UNVERIFIABLE VIA IRRELEVANCE]" in verdict_ex
    assert "[PRECEDENT 3 — REFUTED VIA CONTRADICTION]" in verdict_ex
    assert "Probate clearance services in the UK." in verdict_ex


def test_rendered_uk_verdict_prompt_still_contains_all_three_precedents():
    cfg = load_config()
    system, _ = prompts.render("verdict", verdict_bias="",
                               **prompts.market_kwargs(cfg, for_moat=True))
    for n in ("PRECEDENT 1", "PRECEDENT 2", "PRECEDENT 3"):
        assert n in system


def test_us_market_swaps_the_exemplars_and_context():
    cfg = load_config().for_market("us")
    kw = prompts.market_kwargs(cfg)
    assert "CMS DMEPOS supplier standards" in kw["market_exemplars"]
    assert "tdlr.texas.gov" in kw["market_exemplars"]
    assert "NHS nurse" not in kw["market_exemplars"]
    assert kw["currency_hint"] == "USD"
    assert "United States" in kw["market_context"]
    # require_subdivision on bare "us" injects the naming reminder into framing only.
    assert "SUBDIVISION REQUIRED" in kw["market_context"]
    # Moat never sees the reminder (or any market_context).
    moat = prompts.market_kwargs(cfg, for_moat=True)
    assert "SUBDIVISION REQUIRED" not in moat.get("market_scope", "")
    assert "market_context" not in moat


def test_subdivision_code_skips_bare_parent_reminder():
    """us-tx already names the state — no SUBDIVISION REQUIRED nag."""
    kw = prompts.market_kwargs(load_config().for_market("us-tx"))
    assert "SUBDIVISION REQUIRED" not in kw["market_context"]
    assert "United States" in kw["market_context"]


def test_us_inherits_uk_verdict_precedents_when_it_defines_none():
    """The precedents teach RELEVANCE JUDGEMENT, not market facts, so inheritance is
    correct. Documented fallback (spec D3.3)."""
    us = prompts.market_kwargs(load_config().for_market("us"),
                               for_moat=True)["market_verdict_exemplars"]
    uk = prompts.market_kwargs(load_config().for_market("uk"),
                               for_moat=True)["market_verdict_exemplars"]
    assert us == uk
    assert us != ""


def test_subdivision_inherits_parent_fragments():
    tx = prompts.market_kwargs(load_config().for_market("us-tx"))
    assert "CMS DMEPOS supplier standards" in tx["market_exemplars"]
    assert "tdlr.texas.gov" in tx["market_exemplars"]


def test_config_without_markets_falls_back_to_the_baseline_prompts(tmp_path):
    """A pre-Epic-D config must still render the prompts it always rendered."""
    p = tmp_path / "config.yaml"
    p.write_text("operator: mock\n")
    cfg = load_config(p)
    kw = prompts.market_kwargs(cfg)
    assert "NHS nurse pension" in kw["market_exemplars"]
    assert kw["market_context"] == ""
    assert kw["market_scope"] == ""
