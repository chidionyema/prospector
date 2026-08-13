"""Claude may never do ancillary work.

Founder directive 2026-08-14: "we are over using claude cli and we have Minimax, claude should
never be used for non-critical". Demoting claude_cli to failover (2026-08-08) was not enough —
a failover still RUNS. Measured on the 2026-08-08 republish of 34 packs: 36 claude_cli calls,
3227s of CLI wall-clock, ~90s each, at full moat price, for work that never rules a verdict.

The fence is enforced where the chain is BUILT (`_noncritical_order` strips it), not only where
it is declared, because config.yaml is editable from a phone and this rule must survive that.

Scope is deliberately narrow: the moat (`cfg.operator`) and the pack prose
(`cfg.artifact_operator`) are UNTOUCHED. The £49 deliverable is not ancillary work.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.run import _NONCRITICAL_FORBIDDEN, _NONCRITICAL_ORDER, _noncritical_order


def test_the_shipped_config_has_no_claude_on_the_noncritical_chain():
    cfg = load_config()
    chain = getattr(cfg, "noncritical_operator", None) or []
    chain = [chain] if isinstance(chain, str) else list(chain)
    assert chain, "noncritical_operator must be declared, not left to the default"
    for banned in _NONCRITICAL_FORBIDDEN:
        assert banned not in chain, f"config.yaml puts {banned} on the non-critical chain"


def test_the_hardcoded_default_has_no_claude_either():
    """The default is what runs when the config key is missing or empty."""
    for banned in _NONCRITICAL_FORBIDDEN:
        assert banned not in _NONCRITICAL_ORDER


@pytest.mark.parametrize("banned", sorted(_NONCRITICAL_FORBIDDEN))
def test_a_config_that_names_claude_is_stripped_not_obeyed(banned):
    """Editing the config back must not reinstate it."""
    cfg = load_config()
    cfg.noncritical_operator = [banned, "minimax", "standardcompute"]
    assert _noncritical_order(cfg) == ("minimax", "standardcompute")


def test_a_chain_of_only_claude_falls_back_rather_than_running_claude():
    """Stripping must never leave an empty chain that silently re-admits the banned name."""
    cfg = load_config()
    cfg.noncritical_operator = ["claude_cli"]
    order = _noncritical_order(cfg)
    assert order == _NONCRITICAL_ORDER
    for banned in _NONCRITICAL_FORBIDDEN:
        assert banned not in order


def test_the_strip_is_logged_not_silent(caplog):
    """A silently dropped provider is how a chain degrades unnoticed."""
    cfg = load_config()
    cfg.noncritical_operator = ["claude_cli", "minimax"]
    with caplog.at_level("WARNING"):
        assert _noncritical_order(cfg) == ("minimax",)
    assert any("claude_cli" in r.getMessage() for r in caplog.records), \
        "dropping a configured provider must produce a WARNING"


def test_a_clean_chain_is_passed_through_untouched():
    cfg = load_config()
    cfg.noncritical_operator = ["minimax", "standardcompute"]
    assert _noncritical_order(cfg) == ("minimax", "standardcompute")


def test_the_moat_chain_is_NOT_stripped():
    """The verdict chain still leads with claude_cli — this directive was about ancillary work.

    `is_provisional_provider` (operator.py:1071) is what fences the moat's tail; removing
    claude_cli from `cfg.operator` would leave nothing that can finalise a ruling, so a PASS
    could never publish.
    """
    cfg = load_config()
    chain = cfg.operator
    chain = [chain] if isinstance(chain, str) else list(chain)
    assert "claude_cli" in chain, "the moat must stay led by a trusted brain"
