"""The non-critical chain's second tier must be a DIFFERENT model with its OWN dead mark.

`noncritical_operator: [minimax]` was one tier deep, and the log measured what that cost:
231 terminal `Generation chain EXHAUSTED` over 2026-08-06..08-15 against 67 for the two-tier
moat chain. The gap was chain DEPTH, not model behaviour.

Two ways the obvious fix would have been INERT, and both are pinned here:

1. A second tier pinned to the SAME model inherits every stall it exists to survive. So
   `minimax_m27` must resolve to M2.7 and `minimax` to M3 — never both to M3, which is what
   `minimax_fast` already silently did (`config.yaml model_defaults`, `config.py:253`).
2. `FallbackOperator._raw` keys BOTH the in-run breaker and the persisted `dead_until` mark on
   the chain's tier NAME. Reusing the name "minimax" for the second tier would bench it the
   instant M3 was benched — depth on the page, one tier at runtime. Same shape as
   `a-fallback-tier-is-inert-if-a-preflight-filters-it-out`.

Also pinned: `minimax_fast` is a `model_defaults` FIELD, not an operator name. Putting it in a
chain raises at startup rather than building a chain one brain shorter than it reads.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.operator import _build_operator


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """`MiniMaxOperator.__init__` raises `RuntimeError("MINIMAX_API_KEY not set")`
    (`operator.py:665`) before it ever records a model, so these tests cannot construct one
    on a machine without the key — which is every CI runner. The key is never used: nothing
    here makes a call. Same pattern as `test_minimax_stall_retry.py:30`."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")


def test_the_second_tier_is_a_different_model_from_the_first(cfg):
    first = _build_operator("minimax", cfg, fast=False)
    second = _build_operator("minimax_m27", cfg, fast=False)
    assert second.model == "MiniMax-M2.7"
    assert first.model != second.model, (
        "a second tier pinned to the same model is not depth — it inherits the stall")


def test_the_second_tier_is_pinned_even_on_the_cheap_path(cfg):
    """`fast=True` selects the cheap model. For this tier BOTH slots are M2.7, so a
    query-gen or prescreen call cannot silently fall back onto M3 and re-inherit the stall."""
    assert _build_operator("minimax_m27", cfg, fast=True).model == "MiniMax-M2.7"


def test_the_two_tiers_do_not_share_a_dead_mark():
    """The breaker/health key is the CHAIN NAME, so the tiers must be distinct strings."""
    from prospector.operator import FallbackOperator

    chain = FallbackOperator([("minimax", object()), ("minimax_m27", object())])
    assert set(chain._breakers) == {"minimax", "minimax_m27"}, (
        "one shared key would bench the fallback the moment the leader was benched")


def test_minimax_fast_is_not_an_operator_name(cfg):
    with pytest.raises(ValueError, match="unknown operator"):
        _build_operator("minimax_fast", cfg, fast=False)


def test_the_live_config_actually_has_two_noncritical_tiers(cfg):
    from prospector.run import _noncritical_order

    order = _noncritical_order(cfg)
    assert order[0] == "minimax", "M2.7 measured 29.5s against M3's 8.1s — it must not lead"
    assert len(order) >= 2, "the whole point of the change is depth"


def test_the_second_tier_may_never_rule_finally(cfg):
    """It is a non-critical tier. If it ever reached a verdict it must be stamped provisional."""
    from prospector.operator import is_provisional_provider, moat_primary

    assert "minimax_m27" not in moat_primary()
    assert is_provisional_provider("minimax_m27")
