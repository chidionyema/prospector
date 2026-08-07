"""Market config resolution (Epic D, spec D1).

Covers the four things the market dimension rests on: the default resolves to today's
behaviour, subdivisions inherit their parent, an unknown market fails closed, and a
market can never move the bar.
"""
from __future__ import annotations

import textwrap

import pytest

from prospector.config import (
    MarketConfigError,
    UnknownMarketError,
    load_config,
)

_BASE_CFG = """\
operator: mock
hard_gates:
  - value_durability: [refuted]
  - legality: [refuted]
weights: {pain_acuity: 0.5, defensibility: 0.5}
thresholds: {min_composite_to_pass: 2.5}
"""


def _write_cfg(tmp_path, markets_block: str, extra: str = "") -> str:
    """Compose a config file from dedented fragments.

    Each fragment is dedented independently — embedding an indented block inside an
    outer dedent yields YAML that only *looks* right.
    """
    p = tmp_path / "config.yaml"
    parts = [_BASE_CFG,
             textwrap.dedent(markets_block).strip("\n"),
             textwrap.dedent(extra).strip("\n")]
    p.write_text("\n".join(part for part in parts if part) + "\n")
    return str(p)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_real_config_defaults_to_uk_and_changes_nothing():
    """active_market is unset in the shipped config => the default market, and the
    operative gate/threshold/weight fields are untouched by the market machinery."""
    cfg = load_config()
    assert cfg.active_market == ""
    assert cfg.resolve_market(None) == "uk"
    resolved = cfg.for_market(None)
    assert resolved.hard_gates == cfg.hard_gates
    assert resolved.thresholds == cfg.thresholds
    assert resolved.weights == cfg.weights


def test_subdivision_inherits_parent(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, """
        markets:
          default: uk
          uk: {label: UK}
          us:
            label: US
            currency_hint: USD
            search_region: us-en
          us-tx:
            label: "US - Texas"
            search_region: us-tx
    """))
    tx = cfg.market_config("us-tx")
    assert tx["currency_hint"] == "USD"      # inherited from us
    assert tx["search_region"] == "us-tx"    # own value wins
    assert tx["label"] == "US - Texas"
    assert tx["code"] == "us-tx"


def test_undefined_subdivision_still_resolves_through_parent(tmp_path):
    """Opening us-ca must not require a config entry for every state."""
    cfg = load_config(_write_cfg(tmp_path, """
        markets:
          default: us
          us: {label: US, currency_hint: USD}
    """))
    assert cfg.resolve_market("us-ca") == "us-ca"
    assert cfg.market_config("us-ca")["currency_hint"] == "USD"


def test_unknown_market_raises(tmp_path):
    """Unlike an unknown LANE (which no-ops), an unknown market fails closed: running
    'atlantis' as the default would stamp a dossier with provenance that never ran."""
    cfg = load_config(_write_cfg(tmp_path, """
        markets:
          default: uk
          uk: {label: UK}
    """))
    with pytest.raises(UnknownMarketError):
        cfg.resolve_market("atlantis")
    with pytest.raises(UnknownMarketError):
        cfg.for_market("atlantis")


def test_no_markets_block_is_a_no_op(tmp_path):
    """A config predating Epic D keeps working, unchanged."""
    cfg = load_config(_write_cfg(tmp_path, ""))
    assert cfg.markets == {}
    assert cfg.market_config() == {}
    assert cfg.market_status() == "open"
    assert cfg.for_market("anything") is cfg


# ---------------------------------------------------------------------------
# The bar is untouchable (spec DD2) — the structural refusal of bar-lowering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("forbidden", [
    "hard_gates: [{legality: [refuted]}]",
    "thresholds: {min_composite_to_pass: 0.1}",
    "weights: {pain_acuity: 1.0}",
])
def test_market_may_not_move_the_bar(tmp_path, forbidden):
    with pytest.raises(MarketConfigError) as exc:
        load_config(_write_cfg(tmp_path, f"""
            markets:
              default: uk
              uk: {{label: UK}}
              ng:
                label: Nigeria
                {forbidden}
        """))
    assert "ng" in str(exc.value)


def test_for_market_merges_retrieval_and_generation_only(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, """
        markets:
          default: uk
          uk: {label: UK}
          us:
            label: US
            retrieval: {results_per_query: 9}
            generation: {candidates_per_signal: 3}
    """))
    us = cfg.for_market("us")
    assert us.retrieval.results_per_query == 9
    assert us.generation["candidates_per_signal"] == 3
    assert us.hard_gates == cfg.hard_gates
    assert us.thresholds == cfg.thresholds
    assert us.weights == cfg.weights


# ---------------------------------------------------------------------------
# Validation + composition
# ---------------------------------------------------------------------------

def test_default_must_name_a_defined_market(tmp_path):
    with pytest.raises(MarketConfigError):
        load_config(_write_cfg(tmp_path, """
            markets:
              default: ie
              uk: {label: UK}
        """))


def test_missing_default_rejected(tmp_path):
    with pytest.raises(MarketConfigError):
        load_config(_write_cfg(tmp_path, """
            markets:
              uk: {label: UK}
        """))


def test_bad_status_rejected(tmp_path):
    with pytest.raises(MarketConfigError):
        load_config(_write_cfg(tmp_path, """
            markets:
              default: uk
              uk: {label: UK, status: kinda-open}
        """))


def test_missing_label_rejected(tmp_path):
    with pytest.raises(MarketConfigError):
        load_config(_write_cfg(tmp_path, """
            markets:
              default: uk
              uk: {status: open}
        """))


def test_market_survives_lane_profile_and_persona_composition(tmp_path):
    """for_lane/for_profile/for_persona use dataclasses.replace, so active_market must
    pass through untouched. Asserted rather than assumed."""
    cfg = load_config(_write_cfg(tmp_path, """
        markets:
          default: uk
          uk: {label: UK}
          us: {label: US}
    """, extra=textwrap.dedent("""
        lanes:
          smb:
            thresholds: {min_composite_to_pass: 2.6}
        profiles:
          tight:
            generation: {focus: narrow}
        personas:
          skeptic:
            verdict_bias: "be strict"
    """)))
    us = cfg.for_market("us")
    assert us.for_lane("smb").active_market == "us"
    assert us.for_profile("tight").active_market == "us"
    assert us.for_persona("skeptic").active_market == "us"


def test_active_market_in_config_is_applied_at_load(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, """
        markets:
          default: uk
          uk: {label: UK}
          us:
            label: US
            generation: {candidates_per_signal: 7}
    """, extra="active_market: us"))
    assert cfg.active_market == "us"
    assert cfg.generation["candidates_per_signal"] == 7


def test_status_reads_open_for_uk_and_us_in_shipped_config():
    """UK baseline + US after readiness probe + markets open (2026-07-30)."""
    cfg = load_config()
    assert cfg.market_status("uk") == "open"
    assert cfg.market_status("us") == "open"


# MVP fields every closed stub must carry so `markets probe` is a config+calibration
# exercise, not a scramble to invent authority domains after the fact.
_STUB_REQUIRED = (
    "label", "status", "readiness_ref", "search_region", "currency_hint",
    "cache_salt", "authority_domains", "market_context",
)
_CLOSED_STUBS = ("africa", "nigeria", "europe", "asia")


def test_closed_market_stubs_have_mvp_evidence_terrain():
    """Closed markets are openable later only if the evidence terrain is defined now."""
    cfg = load_config()
    for code in _CLOSED_STUBS:
        block = cfg.market_config(code)
        assert cfg.market_status(code) == "closed", code
        for key in _STUB_REQUIRED:
            assert block.get(key) not in (None, "", []), f"{code} missing/empty {key}"
        assert str(block["cache_salt"]).strip(), f"{code} cache_salt must be non-empty"
        assert isinstance(block["authority_domains"], list) and block["authority_domains"]
        assert len(str(block["market_context"]).strip()) >= 40
        # Exemplars may live in config or prompts/markets/<code>/ — at least one path.
        exemplars = block.get("exemplars") or {}
        qg = exemplars.get("query_gen") if isinstance(exemplars, dict) else None
        from pathlib import Path
        frag = Path("prompts/markets") / code / "query_gen_exemplars.md"
        assert (qg and len(qg) >= 1) or frag.exists(), (
            f"{code} needs query_gen exemplars in config or {frag}")


def test_uk_baseline_keeps_empty_cache_salt():
    """UK salt '' preserves the pre-market store/_cache; must not be 'fixed' away."""
    cfg = load_config()
    assert cfg.market_config("uk").get("cache_salt", None) == ""
