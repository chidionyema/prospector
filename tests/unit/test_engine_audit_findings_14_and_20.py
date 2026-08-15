"""Regression cover for the last two open findings in docs/ENGINE_AUDIT_2026-08-10.md.

**#14 — `MOAT_PRIMARY`'s provisional-stamping had a real single-operator gap.**
`make_operator` returns the bare, unwrapped operator when the config resolves to one tier
(there is no chain to fail over to). Only `FallbackOperator` implemented
`served_is_provisional()`, so `verify._served_is_provisional` fell through to its
`lambda: False` default and a config of `operator: minimax` — a form `cfg.operator`
explicitly supports — ruled as though a trusted moat brain had, and could publish on PASS.
The fence is `is_provisional_provider`, and it must not be reachable only via the chain.

The fix keys off the CONFIG TIER name, never `op.name`: instance names carry the model
(`ClaudeOperator.name` is `"claude/claude-opus-4-8"`), while `MOAT_PRIMARY` is a set of
tier names, so keying off `name` would have marked a trusted `operator: claude` config
provisional — the opposite defect. `test_a_single_trusted_tier_is_not_provisional` is the
test that distinguishes the two implementations.

**#20 — `pricing.py`'s no-ladder fallback price was a hardcoded literal**
(`int(listing.get("price_pence", 4999))`) sitting on the publish path, a second source of
truth for a number `config.yaml:1157` already declares. Two hardcoded fallbacks for one
field is finding #17's exact shape, and a price is the field where that drift charges a
buyer. The default now lives once, in `config.LISTING_DEFAULTS`, and config.yaml wins.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

import prospector.pricing as pricing_mod
from prospector.config import LISTING_DEFAULTS, Config, load_config
from prospector.models import Candidate
from prospector.operator import (
    FallbackOperator,
    MockOperator,
    is_provisional_provider,
    make_operator,
    moat_primary,
)
from prospector.pricing import price_for
from prospector.verify import _served_is_provisional

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"


# --------------------------------------------------------------------------
# #14 — single-operator provisional stamping
# --------------------------------------------------------------------------

def test_the_gap_was_real_a_bare_operator_could_not_answer_the_question():
    """The defect, stated as the thing that is now false.

    A directly-constructed operator with no tier stamp still answers False — that is the
    deliberate carve-out for fixtures, and it is why this test asserts the MECHANISM
    (`tier_name` decides) rather than 'every bare operator is provisional'.
    """
    bare = MockOperator()
    assert bare.tier_name == ""
    assert bare.served_is_provisional() is False
    assert _served_is_provisional(bare) is False


def test_make_operator_stamps_the_tier_a_single_operator_config_was_built_from():
    op = make_operator(Config(operator="mock"))
    assert not isinstance(op, FallbackOperator), (
        "a one-tier config must still return the bare operator; wrapping it would rename it")
    assert op.tier_name == "mock"


def test_a_single_untrusted_tier_now_rules_provisional():
    """`operator: mock` resolves to one tier outside MOAT_PRIMARY. Before the fix this
    reached the publish gate as a trusted ruling."""
    op = make_operator(Config(operator="mock"))
    assert is_provisional_provider("mock") is True
    assert op.served_is_provisional() is True
    # The path that actually decides: verify.py reads it, run.py:615 gates publish on it.
    assert _served_is_provisional(op) is True


def test_a_single_trusted_tier_is_not_provisional():
    """The test that distinguishes tier-name keying from `op.name` keying.

    `ClaudeCliOperator.name` carries the model (e.g. `"claude-cli/default"`), which is NOT in
    MOAT_PRIMARY — an implementation that asked the instance name would mark this trusted config
    provisional and stop it publishing. Asserted without credentials by stamping the tier
    directly, exactly as `make_operator` does. (The original example was `ClaudeOperator`, the
    paid API tier, removed 2026-08-15; MOAT_PRIMARY is now the single name `claude_cli`, which
    makes this test's distinction between TIER-keying and NAME-keying more load-bearing, not
    less — there is no second trusted tier to mask a regression.)
    """
    op = MockOperator()
    for trusted in sorted(moat_primary()):
        op.tier_name = trusted
        assert op.served_is_provisional() is False, (
            f"{trusted!r} is in MOAT_PRIMARY and must never be stamped provisional")
        assert _served_is_provisional(op) is False


def test_every_tier_outside_moat_primary_is_provisional_when_it_rules_alone():
    op = MockOperator()
    for untrusted in ("minimax", "deepseek", "ollama", "mock"):
        assert untrusted not in moat_primary()
        op.tier_name = untrusted
        assert op.served_is_provisional() is True, (
            f"{untrusted!r} ruling as a single-tier config must be stamped provisional")


def test_the_chain_path_is_unchanged():
    """`FallbackOperator` still overrides the base and answers from the brain that actually
    served this thread's last call — not from a tier stamped at construction time."""
    chain = FallbackOperator([("claude_cli", MockOperator()), ("minimax", MockOperator())])
    assert chain.last_served() == ""
    assert chain.served_is_provisional() is False, "nothing has served yet"
    chain._served.name = "minimax"
    assert chain.served_is_provisional() is True
    chain._served.name = "claude_cli"
    assert chain.served_is_provisional() is False


def test_the_shipped_verdict_chain_is_multi_tier_so_production_is_unaffected():
    """Recorded so the change's blast radius is a fact, not a claim: the finding was
    structural, not live — config.yaml declares more than one tier, which took the chain path.
    (Three tiers until 2026-08-15, two since standardcompute was removed.)"""
    ops = load_config(str(REPO_CONFIG)).operator
    assert isinstance(ops, list) and len(ops) > 1
    assert ops[0] in moat_primary(), "the chain must stay LED by a trusted brain"


# --------------------------------------------------------------------------
# #20 — the flat catalogue price is declared once
# --------------------------------------------------------------------------

def _load_listing(tmp_path: Path, mutate) -> dict:
    raw = yaml.safe_load(REPO_CONFIG.read_text(encoding="utf-8"))
    mutate(raw)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_config(str(p)).listing


def test_config_yaml_wins_over_the_default(tmp_path):
    """The direction that matters: a default that could override the operator's declared
    price would be a code change silently re-pricing the catalogue."""
    listing = _load_listing(tmp_path, lambda r: r["listing"].update(price_pence=1234))
    assert listing["price_pence"] == 1234


def test_omitting_the_key_falls_back_to_the_one_declared_default(tmp_path):
    listing = _load_listing(tmp_path, lambda r: r["listing"].pop("price_pence", None))
    assert listing["price_pence"] == LISTING_DEFAULTS["price_pence"]


def test_the_shipped_config_still_declares_the_flat_price():
    """If this ever fails, production is running on the fallback rather than on config."""
    declared = load_config(str(REPO_CONFIG)).listing.get("price_pence")
    assert isinstance(declared, int) and declared > 0


def test_the_no_ladder_degrade_reads_the_declared_default_not_a_literal():
    """The money-path branch the finding cites: a cfg with no ladder AND no price must
    still return a price (it is on the publish path) and it must be THE declared one."""
    cfg = Config(listing={})
    decision = price_for(Candidate(title="A test opportunity"), None, cfg)
    assert decision.price_pence == LISTING_DEFAULTS["price_pence"]
    assert decision.rung == "flat (no ladder declared)"


def test_pricing_module_carries_no_second_price_literal():
    """Drift guard. The defect was not the number; it was that there were two of them."""
    src = Path(pricing_mod.__file__).read_text(encoding="utf-8")
    assert 'price_pence", 4999' not in src
    assert "LISTING_DEFAULTS" in src


def test_a_cfg_object_without_a_listing_attribute_still_prices():
    """`tests/unit/test_payer_solvency_price.py` pins that `price_for` tolerates a cfg
    built by hand. The fallback change must not have taken that away."""
    cfg = replace(Config(), listing={})
    assert price_for(Candidate(title="A test opportunity"), None, cfg).price_pence > 0
