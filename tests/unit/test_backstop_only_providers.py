"""A backstop provider answers an outage, never a low-relevance result.

Founder directive 2026-08-16 — "unacceptable use of claude cli". The relevance escalation in
`FallbackSearchProvider` was reaching `claude_cli` on 141 of 347 searches that morning, because
duckduckgo and exa routinely answer below the 0.35 coverage floor. `claude_cli` is a language
model doing a search: ~196s a call, 76% of all grounding time for 21% of the evidence.

The fence must hold in BOTH directions, which is why the outage case is tested as hard as the
skip case: cutting the backstop out of a real outage would turn a grounded check into a DEFER,
and that is a worse defect than the cost this change exists to remove.
"""
from __future__ import annotations

import pytest

from prospector.models import Source
from prospector.retrieval import FallbackSearchProvider, SearchProvider


class _Answers(SearchProvider):
    """Returns a fixed set. `text` decides its coverage against the query."""

    def __init__(self, text: str = "unrelated filler") -> None:
        self.text = text
        self.calls = 0

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls += 1
        return [Source.make(url="https://example.org/a", text=self.text, query=query)]


class _Raises(SearchProvider):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, k: int = 4, max_chars: int = 1500) -> list[Source]:
        self.calls += 1
        raise RuntimeError("provider down")


class _Health:
    """Health stub. Nothing is dead; marks are recorded, not enforced."""

    def __init__(self) -> None:
        self.marks: list[tuple] = []

    def is_dead(self, name: str) -> bool:
        return False

    def clear(self, name: str) -> None:
        pass

    def mark_exhausted(self, name: str, seconds: float, error: str = "") -> None:
        self.marks.append((name, seconds, error))


QUERY = "georgia film tax credit audit requirement 2026"


def _chain(providers, backstop):
    return FallbackSearchProvider(
        providers, health=_Health(), min_relevance=0.35, backstop_only=backstop)


def test_a_low_relevance_answer_does_not_reach_the_backstop():
    """The whole point. web answered — badly — so the model must not be asked."""
    web = _Answers("unrelated filler about knitting patterns")
    backstop = _Answers("georgia film tax credit audit requirement 2026 rules")
    out = _chain([("ddg", web), ("claude_cli", backstop)], ["claude_cli"]).search(QUERY)

    assert web.calls == 1
    assert backstop.calls == 0, "the backstop was asked about a merely off-topic result"
    # And the off-topic set is still RETURNED — skipping the backstop must not empty the
    # check. An empty `sources` reaches the DEFER gate, which is the failure this guards.
    assert len(out) == 1


def test_the_backstop_still_answers_a_real_outage():
    """Every web provider raised. This is the case the backstop exists for."""
    dead_one, dead_two = _Raises(), _Raises()
    backstop = _Answers("georgia film tax credit audit requirement 2026 rules")
    out = _chain([("ddg", dead_one), ("exa", dead_two), ("claude_cli", backstop)],
                 ["claude_cli"]).search(QUERY)

    assert dead_one.calls == 1 and dead_two.calls == 1
    assert backstop.calls == 1, "an outage was not allowed to reach the backstop"
    assert len(out) == 1


def test_one_survivor_is_enough_to_hold_the_backstop_back():
    """ddg died, exa answered off-topic. Evidence exists, so the model is not needed."""
    dead = _Raises()
    web = _Answers("unrelated filler about knitting patterns")
    backstop = _Answers("georgia film tax credit audit requirement 2026 rules")
    _chain([("ddg", dead), ("exa", web), ("claude_cli", backstop)],
           ["claude_cli"]).search(QUERY)

    assert web.calls == 1
    assert backstop.calls == 0


def test_an_empty_list_restores_the_old_behaviour_exactly():
    """The knob must be a true no-op when off, or it cannot be reverted under fire."""
    web = _Answers("unrelated filler about knitting patterns")
    backstop = _Answers("georgia film tax credit audit requirement 2026 rules")
    _chain([("ddg", web), ("claude_cli", backstop)], []).search(QUERY)

    assert backstop.calls == 1, "with the fence off, low relevance must still escalate"


def test_a_backstop_at_the_head_of_the_chain_is_not_skipped():
    """Nobody answered before it, so it is not being used as a second opinion."""
    backstop = _Answers("georgia film tax credit audit requirement 2026 rules")
    out = _chain([("claude_cli", backstop)], ["claude_cli"]).search(QUERY)

    assert backstop.calls == 1
    assert len(out) == 1


def test_the_live_config_names_claude_cli_as_a_backstop():
    """Config-declared, not just defaulted in the dataclass."""
    import pathlib

    import yaml

    raw = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[2] / "config.yaml").read_text())
    assert "claude_cli" in (raw["retrieval"].get("backstop_only_providers") or [])


def test_make_provider_wires_the_config_through():
    """A knob the builder ignores is a comment. `make_provider` must carry it."""
    from prospector.config import load_config
    from prospector.retrieval import make_provider

    cfg = load_config()
    if isinstance(cfg.retrieval.provider, str) or len(cfg.retrieval.provider) < 2:
        pytest.skip("single-provider config skips FallbackSearchProvider by design")
    chain = make_provider(cfg)
    # Unwrap the enrichment/ranking/cache wrappers to reach the fallback chain.
    seen = 0
    while not isinstance(chain, FallbackSearchProvider) and seen < 10:
        chain = getattr(chain, "inner", None) or getattr(chain, "_inner", None)
        seen += 1
        if chain is None:
            pytest.fail("no FallbackSearchProvider in the built chain")
    assert "claude_cli" in chain.backstop_only
