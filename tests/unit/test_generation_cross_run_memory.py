"""Cross-run anti-duplication memory (regression for live near-duplicate probate packs).

The blue-sky daemon re-runs generation every cycle. Before this fix the `avoid` list was rebuilt
from ONLY the current run's candidates, so each wave re-explored the same idea space blind to every
prior run and to the catalogue — the engine kept minting near-duplicate "probate clear-out" packs.
generate() now accepts `prior_titles` (the engine's already-explored ideas, PASS and KILL alike) and
folds them into the avoid list fed to the model on every call.
"""
from __future__ import annotations

from prospector.config import load_config
from prospector.generate import generate


class _CapturingOp:
    """Records the user prompt of every call so we can assert what the model was told to avoid."""

    model_version = "stub"

    def __init__(self):
        self.calls = 0
        self.prompts: list[str] = []

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        self.prompts.append(user)
        return [{"title": f"Fresh idea {self.calls}-{i}", "one_liner": "x",
                 "why_now": "y", "tags": {"sector": "s"}} for i in range(6)]


def test_prior_titles_reach_the_avoid_list():
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    op = _CapturingOp()
    prior = ["The Probate Locker Clear-Out Agent", "Estate Cleanout Concierge"]
    generate(op, cfg, signal_text="", k=6, prior_titles=prior)
    blob = "\n".join(op.prompts)
    assert "Probate Locker Clear-Out Agent" in blob
    assert "Estate Cleanout Concierge" in blob


def test_no_prior_titles_is_safe_default():
    """Omitting prior_titles (or passing None) must not crash and must still generate."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    out = generate(_CapturingOp(), cfg, signal_text="", k=6)  # no prior_titles
    assert len(out) == 6


def test_prior_titles_deduplicated_and_capped():
    """A huge, dupe-laden prior list must not bloat the prompt unboundedly."""
    cfg = load_config()
    cfg.generation["refinement_enabled"] = False
    op = _CapturingOp()
    prior = ["Same Idea"] * 50 + [f"Idea {i}" for i in range(500)]
    generate(op, cfg, signal_text="", k=6, prior_titles=prior)
    first_prompt = op.prompts[0]
    # "Same Idea" collapses to a single mention in the avoid block (dedup), not 50.
    assert first_prompt.count("Same Idea") == 1
