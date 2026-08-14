"""A pinned subdivision must reach the MODEL, not just the dossier stamp.

THE DEFECT THIS CLOSES

`market_rotation` could already name a subdivision — the config prose has said
`"uk,us-ca"` since rotation shipped — and `config.market_config("us-ca")` resolved it
correctly, inheriting the parent `us` block. But a subdivision inherits the parent's
`label` too, and `label` was the ONLY thing prompt framing was built from. So
`market_kwargs("us-tx")` and `market_kwargs("us-ca")` came out byte-identical on every
key. The state reached `Candidate.market`, the dossier row, the dedup scope and the
retrieval namespace, and never once reached the prompt.

Rotating over states was therefore COSMETIC: ten ticks over ten states asked the model
the same question ten times, and the model supplied a state from its own prior. It
supplied one state. Measured over the 146 `us` dossiers in `store/prospector.db` on
2026-08-14: 92 (63%) named no state at all, and of the 54 that did, California took 40
against Texas 10, New York 3, Illinois 2, Florida 1 — while the only worked examples in
`prompts/markets/us/query_gen_exemplars.md` are Texas. The config pointed one way and
the output went the other, which is the signature of framing that never arrived.

WHAT IS PINNED, AND WHY EACH ONE

1. Two subdivisions of one parent must not render the same prompt. This is the defect
   itself; everything else here is a guard around it.
2. The state name reaches the moat via `market_scope`. A verdict that cannot tell which
   state it is ruling on cannot judge a California passage irrelevant to a Texas
   candidate. Admissible because `market_scope` is built from NAMES alone — never a
   fact — so this cannot become a prior-knowledge leak.
3. The moat's key set stays exactly `MOAT_MARKET_KEYS`. Widening framing is precisely
   how the rich generation variables would leak into the verdict.
4. A market with no subdivisions is untouched, byte for byte — `uk` is the calibration
   anchor every threshold was measured against, and a steering change that moves it
   invalidates the bars.
5. A bare parent with `require_subdivision` keeps its original reminder. The pinned
   directive REPLACES that reminder only when a name is actually available.
6. Every subdivision code in the LIVE rotation has a name in `subdivisions`. This is the
   guard that matters long-term: adding `us-nv` to the rotation without adding it to
   `subdivisions` silently restores the cosmetic-rotation bug, and nothing else in the
   system would report it — the tick runs, the dossier is stamped `us-nv`, and only the
   prompt is wrong.
"""
from __future__ import annotations

import textwrap

import pytest

from prospector import prompts
from prospector.config import load_config
from prospector.prompts import MOAT_MARKET_KEYS
from prospector.scheduler.run_scheduled import _market_rotation

_BASE = """\
operator: mock
hard_gates:
  - legality: [refuted]
weights: {pain_acuity: 0.5, defensibility: 0.5}
thresholds: {min_composite_to_pass: 2.5}
"""

_MARKETS = """\
active_market: ""
markets:
  default: uk
  uk:
    label: "United Kingdom"
    status: open
    currency_hint: "GBP"
    market_context: "Jurisdiction: the United Kingdom."
  us:
    label: "United States"
    status: open
    currency_hint: "USD"
    require_subdivision: true
    market_context: "Jurisdiction: the United States."
    subdivisions:
      us-tx: "Texas"
      us-ca: "California"
"""


@pytest.fixture()
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_BASE + textwrap.dedent(_MARKETS), encoding="utf-8")
    return load_config(str(p))


# 1 — the defect itself ------------------------------------------------------------------

def test_two_subdivisions_of_one_parent_do_not_render_the_same_prompt(cfg):
    tx = prompts.market_kwargs(cfg.for_market("us-tx"))
    ca = prompts.market_kwargs(cfg.for_market("us-ca"))
    assert tx != ca, (
        "us-tx and us-ca rendered identical framing — the subdivision reached the dossier "
        "stamp but not the model, which is the cosmetic-rotation defect this file exists for"
    )
    assert "Texas" in tx["market_context"] and "Texas" in tx["market_scope"]
    assert "California" in ca["market_context"] and "California" in ca["market_scope"]
    assert "California" not in tx["market_context"], "Texas framing must not name another state"
    assert "Texas" not in ca["market_context"], "California framing must not name another state"


def test_the_pinned_state_is_named_as_a_directive_not_a_hint(cfg):
    ctx = prompts.market_kwargs(cfg.for_market("us-tx"))["market_context"]
    assert "SUBDIVISION PINNED" in ctx
    assert "Do NOT substitute another sub-jurisdiction" in ctx
    # The parent framing survives — the directive is appended, never a replacement.
    assert "Jurisdiction: the United States." in ctx


# 2 & 3 — what the moat may see ----------------------------------------------------------

def test_the_moat_learns_which_state_it_is_ruling_on(cfg):
    moat = prompts.market_kwargs(cfg.for_market("us-tx"), for_moat=True)
    assert moat["market_scope"] == "Jurisdiction under evaluation: Texas, United States."


def test_the_moat_key_set_does_not_widen(cfg):
    for code in ("uk", "us", "us-tx", "us-ca"):
        moat = prompts.market_kwargs(cfg.for_market(code), for_moat=True)
        assert set(moat) == set(MOAT_MARKET_KEYS), (
            f"{code} leaked generation variables into the verdict prompt"
        )


def test_market_scope_carries_names_only(cfg):
    """The moat's market variable may name a jurisdiction; it may never assert about it."""
    scope = prompts.market_kwargs(cfg.for_market("us-tx"), for_moat=True)["market_scope"]
    assert scope.startswith("Jurisdiction under evaluation: ")
    assert scope.endswith(".")
    # Nothing from the rich parent context may ride along.
    assert "SUBDIVISION PINNED" not in scope
    assert "USD" not in scope and "$" not in scope


# 4 & 5 — no collateral movement ---------------------------------------------------------

def test_a_market_without_subdivisions_is_untouched(cfg):
    uk = prompts.market_kwargs(cfg.for_market("uk"))
    assert uk["market_scope"] == "Jurisdiction under evaluation: United Kingdom."
    assert uk["market_label"] == "United Kingdom"
    assert "SUBDIVISION" not in uk["market_context"]


def test_a_bare_parent_keeps_its_original_reminder(cfg):
    ctx = prompts.market_kwargs(cfg.for_market("us"))["market_context"]
    assert "SUBDIVISION REQUIRED" in ctx, (
        "the pinned directive must REPLACE the generic reminder only when a name exists"
    )
    assert "SUBDIVISION PINNED" not in ctx


def test_an_unnamed_subdivision_falls_back_rather_than_inventing_a_name(cfg):
    """`us-nv` is resolvable but absent from `subdivisions` — it must not fabricate one."""
    ctx = prompts.market_kwargs(cfg.for_market("us-nv"))["market_context"]
    assert "SUBDIVISION PINNED" not in ctx
    assert "Nevada" not in ctx


# 6 — the live config, which is the thing that actually runs -----------------------------

def test_every_subdivision_in_the_live_rotation_has_a_name():
    live = load_config("config.yaml")
    codes = _market_rotation(live)
    assert codes, "the live rotation is empty — generation would run one market forever"
    unnamed = []
    for code in codes:
        if "-" not in code:
            continue
        block = live.market_config(code)
        if not (block.get("subdivisions") or {}).get(code):
            unnamed.append(code)
    assert not unnamed, (
        f"rotation codes with no name in `subdivisions`: {unnamed}. Each would render the "
        f"parent's framing verbatim, so its ticks ask the same question as every other "
        f"unnamed sibling and the model picks the state itself."
    )


def test_the_live_rotation_is_us_dominant_and_spread_across_states():
    """The founder's directive of 2026-08-14, pinned as a property of the config."""
    live = load_config("config.yaml")
    codes = _market_rotation(live)
    us = [c for c in codes if c == "us" or c.startswith("us-")]
    assert len(us) > len(codes) - len(us), (
        f"US must be the dominant market: {len(us)} of {len(codes)} ticks is not a majority"
    )
    states = {c for c in us if "-" in c}
    assert len(states) >= 4, (
        f"US is pinned to too few states ({sorted(states)}) — 'not just california' is the "
        f"other half of the directive"
    )
    assert len(states) == len(us), "a state repeats within one rotation cycle"


def test_the_uk_anchor_is_not_retired():
    """UK is the market every threshold was calibrated against (its readiness_ref is empty)."""
    live = load_config("config.yaml")
    assert "uk" in _market_rotation(live)


def test_the_us_exemplars_do_not_lead_with_one_state():
    """The exemplar header named cslb.ca.gov ahead of every worked example."""
    for name in ("query_gen_exemplars", "query_gen_batched_exemplars"):
        text = (
            __import__("pathlib").Path(f"prompts/markets/us/{name}.md").read_text(encoding="utf-8")
        )
        head = text.split("- Product", 1)[0]
        assert "PINNED STATE" in head, f"{name}: header must defer to the pinned state"
        assert "that is the format, not the state" in head.lower(), (
            f"{name}: the Texas worked examples must be labelled as format, or they read as "
            f"an instruction to answer for Texas whatever state is pinned"
        )
