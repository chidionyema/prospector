"""The engine must run with no Claude Code subscription at all.

Founder directive 2026-08-18: "we cant be depedint on claude code, it has to be a option only".

`claude_cli` is not an API key, it is a BINARY, and its auth lives in `~/.claude`. That does not
travel into a container, so any chain that LEADS with it makes a Claude subscription a hard
requirement for whatever that chain produces — which is what blocked moving the engine to a
server. Every chain now leads with a brain that authenticates by key.

`claude_cli` is still allowed in the chains, second, and it still does real work: the shelf-copy
escalation reaches it (`_escalation_order`). Second is optional. First is a dependency.

The second half of this file pins the escalation, because making Claude optional is what broke
it. Both prose chains now lead with `minimax`, so "escalate to `cfg.artifact_operator`" — the
rule as written until today — would have rewritten refused copy on the brain that had just
written it, logged as an escalation that fired.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.run import _escalation_order

CLAUDE = "claude_cli"

# Every operator chain in config.yaml. `moat_primary` is a trust roster rather than a call
# order, but it is included on purpose: it is read as a chain by `run.py` and an edit that put
# claude_cli at its head would put a subscription binary in front of the verdict path too.
CHAIN_KEYS = (
    "operator",
    "moat_primary",
    "noncritical_operator",
    "artifact_operator",
    "marketing_operator",
)


def _chain(cfg, key):
    value = getattr(cfg, key, None) or []
    return [value] if isinstance(value, str) else list(value)


@pytest.mark.parametrize("key", CHAIN_KEYS)
def test_no_shipped_chain_leads_with_claude_code(key):
    chain = _chain(load_config(), key)
    assert chain, f"{key} must be declared, not left to the default"
    assert chain[0] != CLAUDE, (
        f"config.yaml {key} leads with {CLAUDE}. That makes a Claude Code subscription a "
        f"requirement for everything this chain produces, and the auth for it does not exist "
        f"on a server. Put a key-authenticated brain first and leave {CLAUDE} behind it."
    )


def test_the_pack_prose_chain_still_keeps_claude_as_an_option():
    """Optional means present-and-not-first, not absent.

    Deleting `claude_cli` outright would satisfy the rule above and quietly cost the shelf-copy
    escalation its only different brain, which is the failure this test exists to catch.
    """
    chain = _chain(load_config(), "artifact_operator")
    assert CLAUDE in chain
    assert chain.index(CLAUDE) > 0


class TestTheEscalationGoesToADifferentBrain:
    def test_the_shipped_config_escalates_past_the_brain_that_wrote_the_copy(self):
        cfg = load_config()
        marketing_lead = _chain(cfg, "marketing_operator")[0]
        order = _escalation_order(cfg)
        assert order, (
            "a shelf-copy breach has nowhere to escalate to on the shipped config: every tier "
            "of artifact_operator is the brain that just failed the publish bar"
        )
        assert marketing_lead not in order

    def test_the_failed_brain_is_dropped_even_when_it_is_not_first_in_the_quality_chain(self):
        cfg = load_config()
        cfg.marketing_operator = ["minimax", "claude_cli"]
        cfg.artifact_operator = ["claude_cli", "minimax", "ollama"]
        assert _escalation_order(cfg) == ["claude_cli", "ollama"]

    def test_two_identical_chains_report_no_escalation_rather_than_a_fake_one(self):
        """The regression the whole change turns on.

        Before 2026-08-18 this returned the quality chain unchanged, so the rewrite ran on the
        same lead and the log claimed the guardrail had fired.
        """
        cfg = load_config()
        cfg.marketing_operator = ["minimax", "claude_cli"]
        cfg.artifact_operator = ["minimax", "claude_cli"]
        assert _escalation_order(cfg) == ["claude_cli"]

        cfg.artifact_operator = ["minimax"]
        assert _escalation_order(cfg) == []

    def test_a_config_with_no_marketing_split_reads_its_lead_off_the_quality_chain(self):
        """A pre-split Config has no `marketing_operator` at all, and must not raise here.

        Such a config runs the copy ON the quality chain, so `_generate_pack_content` marks it
        escalated up front and never asks; this only pins that the lookup is total.
        """
        cfg = load_config()
        cfg.marketing_operator = None
        cfg.artifact_operator = ["minimax", "claude_cli"]
        assert _escalation_order(cfg) == ["claude_cli"]
