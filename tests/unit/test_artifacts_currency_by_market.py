"""Generation must read the market from the PACK, not from the config's active market.

On 2026-08-08 three packs published UNLISTED on a currency error:

    7a6c07535fd8a998  currency | financial_model | 2 '£' amount(s) in a 'us' pack (expected '$')
    8d5e24fbe6c1f5d3  currency | financial_model | 1 '£' amount(s) in a 'us' pack (expected '$')
    8ce5270ade208070  currency | listing_page    | only '€' amounts in a 'uk' pack (expected '£')

`market_kwargs(cfg)` resolved `cfg.market_config()` — the ACTIVE market of the run, one
global value — while `lint_pack` grades against `candidate.market`, per pack
(bridge.py:842). With the daemon pointed at `uk`, every US pack was told
`currency_hint = GBP`; `artifacts.py:378` then rendered its financial model with `£`, and
the linter refused to list it. Generator and grader now read the same field.
"""
from types import SimpleNamespace

import pytest

from prospector.artifacts import _currency_rule
from prospector.config import load_config
from prospector.pack_linter import check_currency, expected_currency, symbol_for_currency
from prospector.prompts import market_kwargs


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_active_market_is_uk_so_this_test_can_discriminate(cfg):
    """Vacuity guard. If the active market were already 'us', every assertion below would
    pass without the fix and prove nothing."""
    assert market_kwargs(cfg).get("currency_hint") == "GBP"


def test_override_selects_the_packs_own_currency(cfg):
    assert market_kwargs(cfg, market="us").get("currency_hint") == "USD"
    assert market_kwargs(cfg, market="uk").get("currency_hint") == "GBP"


def test_rendered_financial_model_symbol_follows_the_pack(cfg):
    """artifacts.py:378 feeds this exact value into `_render_financial_model`."""
    us = symbol_for_currency(market_kwargs(cfg, market="us").get("currency_hint"))
    uk = symbol_for_currency(market_kwargs(cfg, market="uk").get("currency_hint"))
    assert us == expected_currency("us") == "$"
    assert uk == expected_currency("uk") == "£"
    # The defect, stated as an assertion: no override meant a US pack rendered in £.
    assert symbol_for_currency(market_kwargs(cfg).get("currency_hint")) == "£"


def test_currency_rule_names_the_packs_symbol(cfg):
    rule = _currency_rule(cfg, SimpleNamespace(market="us"))
    assert "$" in rule and "£" not in rule


def test_currency_rule_is_empty_when_no_market_is_declared(cfg):
    """An unmapped or absent market lints currency-free (pack_linter.py:44), so instructing
    the model in a currency nobody declared would be inventing one."""
    assert _currency_rule(cfg, SimpleNamespace(market="")) == ""
    assert _currency_rule(cfg, SimpleNamespace(market="atlantis")) == ""
    assert _currency_rule(None, SimpleNamespace(market="us")) == ""


def test_the_rule_does_not_forbid_what_the_grader_allows(cfg):
    """The instruction must not be stricter than `check_currency`. A foreign comparable
    quoted ALONGSIDE the market's own currency is a warning, not an error, and
    content_gen.md rule (b) requires figures verbatim from a claim, so a rule saying
    'never use another currency' would push the model into inventing an FX conversion."""
    both = "Comparable services in Ireland charge €50 per month; here that is £42."
    problems = check_currency("", both, "uk")
    assert problems and all(p["severity"] == "warning" for p in problems)

    foreign_only = "Comparable services charge €50 per month."
    assert any(p["severity"] == "error" for p in check_currency("", foreign_only, "uk"))

    rule = _currency_rule(cfg, SimpleNamespace(market="uk"))
    assert "verbatim" in rule and "Never convert" in rule
