"""Contract for C3 — the `price_comparables` check (prospector/price_comparables.py).

This check is the first thing in the engine that reads a number off a web page and lets it
reach the money path, so the tests are organised by what each rail stops:

1. **It can never kill.** Whatever config says, `price_comparables` cannot fire a hard gate
   and never joins the kill-fast run order. "No price page exists for this" is a fact about
   the open web, not evidence that an idea is dead.
2. **A number must literally be in the passage it cites.** This is the rail an LLM cannot
   argue past, and the one that separates a transcription from an assertion. Near-misses
   (49 inside 149, 49.99, or 4,900) must be rejected — a fuzzy match would launder a
   fabricated price into a "cited" one, which is worse than having no anchor.
3. **FX is declared, never guessed.** An anchor in an undeclared currency stays visible as
   evidence and stays out of every pricing decision.
4. **Landing this check moves no price.** `rung_adjust_enabled` defaults to false, so the
   golden matrix in test_pricing.py holds unchanged with anchors present.
5. **When adjustment IS enabled, it moves at most one rung, only on a classified pack, and
   only when the evidence clears an adjacent rung outright.**
"""
from __future__ import annotations

import copy

import pytest

from prospector.config import Config
from prospector.kill_filter import is_hard_fail
from prospector.models import (
    CHECKS,
    PRICING_CHECK,
    Candidate,
    CheckResult,
    PriceAnchor,
    ScoreResult,
    Source,
    Verdict,
)
from prospector.price_comparables import (
    _appears_in,
    anchor_evidence,
    comparables_config,
    comparables_queries,
    eligible_anchors,
    extract_anchors,
    to_pence_gbp,
)
from prospector.pricing import price_for

# --- helpers ---------------------------------------------------------------

def _candidate(tier: str = "smb", market: str = "") -> Candidate:
    return Candidate(title="Rota compliance checker for care homes",
                     one_liner="Flags rota gaps that breach staffing minimums",
                     ambition_tier=tier, market=market)


def _score() -> ScoreResult:
    return ScoreResult(scores={}, justification={}, composite=3.5)


def _source(url: str, text: str) -> Source:
    return Source.make(url=url, text=text)


def _anchor(pence: int, cadence: str = "one_off", url: str = "https://a.example/pricing",
            currency: str = "GBP") -> PriceAnchor:
    return PriceAnchor(amount=pence / 100, currency=currency, cadence=cadence,
                       what="a comparable thing", source_id="sid", url=url,
                       amount_pence_gbp=pence)


class _StubOp:
    """A moat operator that returns exactly what a test hands it."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0, retries=2):
        self.calls += 1
        return self.payload

    def last_served(self):
        return "stub/test"

    def served_is_provisional(self):
        return False


def _with_comparables(cfg: Config, **overrides) -> Config:
    """A deep copy of cfg with the comparables block overridden.

    Deep-copied because `cfg` is a session-scoped fixture reading the real config.yaml —
    mutating it in place would leak a pricing setting into every later test.
    """
    c = copy.deepcopy(cfg)
    block = dict((c.listing["pricing"].get("comparables") or {}))
    block.update(overrides)
    c.listing["pricing"]["comparables"] = block
    return c


# --- 1. It can never kill --------------------------------------------------

def test_pricing_check_is_in_the_vocabulary():
    """It must be a real check with a real question — not a magic string."""
    assert PRICING_CHECK in CHECKS
    assert CHECKS[PRICING_CHECK].strip()


def test_pricing_check_can_never_hard_fail_even_when_config_gates_it(cfg: Config):
    """The guard is structural. Adding it to hard_gates is a DATA edit that passes through
    neither code review nor this suite, so config must not be the thing standing between a
    missing price page and a killed candidate."""
    c = copy.deepcopy(cfg)
    c.hard_gates = [{PRICING_CHECK: ["refuted", "unverifiable", "supported"]}] + list(
        c.hard_gates)
    c.thresholds.confidence_floor = 0.0
    for verdict in (Verdict.REFUTED, Verdict.UNVERIFIABLE, Verdict.SUPPORTED):
        res = CheckResult(check_name=PRICING_CHECK, verdict=verdict, confidence=1.0,
                          rationale="whatever")
        assert is_hard_fail(PRICING_CHECK, res, c) is False, verdict


def test_pricing_check_never_joins_the_kill_fast_run_order(cfg: Config, monkeypatch):
    """Even gated in config it must not be run as a generic verdict check: the verdict
    prompt would emit a meaningless supported/refuted for a question that has no such
    answer, and that value would then be visible to anything reading `checks`."""
    from prospector import verify as verify_mod

    c = copy.deepcopy(cfg)
    c.hard_gates = [{PRICING_CHECK: ["refuted"]}] + list(c.hard_gates)
    ran: list[str] = []

    def _fake_run_check(op, search, cfg_, cand, check_name, **kw):
        ran.append(check_name)
        return CheckResult(check_name=check_name, verdict=Verdict.SUPPORTED,
                           confidence=0.9, rationale="ok")

    monkeypatch.setattr(verify_mod, "run_check", _fake_run_check)
    verify_mod.verify(_StubOp({}), None, c, _candidate(), skip_adversarial=True)
    assert PRICING_CHECK not in ran
    assert ran, "sanity: the other checks still ran"


# --- 2. The number must be in the passage ----------------------------------

@pytest.mark.parametrize("amount,text,expected", [
    (49, "Plans start at £49 per user", True),
    (49.0, "It costs 49.00 GBP", True),
    (49.99, "Yours for £49.99", True),
    (1299, "Enterprise is £1,299 a year", True),      # thousands separator normalised
    (49, "The pro tier is £149", False),              # 49 inside 149
    (49, "Only £49.99 today", False),                 # 49 inside 49.99
    (49, "A £4,900 annual contract", False),          # 49 inside 4900
    (49, "Priced competitively for teams", False),    # no number at all
    (0, "Free forever", False),                       # zero is not a price anchor
])
def test_appears_in_rejects_near_misses(amount, text, expected):
    assert _appears_in(amount, text) is expected


def test_anchor_whose_number_is_absent_from_its_passage_is_rejected(cfg: Config):
    """The fabrication rail. The model cites a real passage and attaches a plausible price
    the passage never states — the single most likely way a hallucinated number reaches a
    live storefront wearing a citation."""
    src = _source("https://vendor.example/pricing", "Our starter plan is £29 per month.")
    op = _StubOp({"anchors": [
        {"amount": 29, "currency": "GBP", "cadence": "monthly",
         "what": "starter plan", "source_id": src.source_id},
        {"amount": 99, "currency": "GBP", "cadence": "monthly",
         "what": "invented pro plan", "source_id": src.source_id},
    ], "rationale": "two plans"})

    res = extract_anchors(op, _candidate(), [src], cfg)

    assert [a.amount for a in res.anchors] == [29]
    assert len(res.rejected) == 1
    assert "does not appear in the cited passage" in res.rejected[0]["reason"]


def test_anchor_citing_an_unknown_source_is_rejected(cfg: Config):
    src = _source("https://vendor.example/pricing", "Our starter plan is £29 per month.")
    op = _StubOp({"anchors": [
        {"amount": 29, "currency": "GBP", "cadence": "monthly", "what": "x",
         "source_id": "not-a-real-source-id"},
    ]})
    res = extract_anchors(op, _candidate(), [src], cfg)
    assert res.anchors == []
    assert "source_id does not match" in res.rejected[0]["reason"]


def test_market_size_is_rejected_by_the_bounds_rail(cfg: Config):
    """A number that IS in the passage but is not a price. The prompt tells the model not
    to do this; the bounds rail is what happens when it does anyway."""
    src = _source("https://analyst.example/report",
                  "The care compliance software market reached 4200000 in 2025.")
    op = _StubOp({"anchors": [
        {"amount": 4200000, "currency": "GBP", "cadence": "one_off",
         "what": "market", "source_id": src.source_id},
    ]})
    res = extract_anchors(op, _candidate(), [src], cfg)
    assert res.anchors == []
    assert "outside the sane price band" in res.rejected[0]["reason"]


def test_synthesized_sources_are_stripped_before_the_model_sees_them(cfg: Config):
    """P1-5 defence-in-depth, same rule as verdict_for: a price 'found' in a cheap model's
    self-synthesis is not retrieval, and must not be citable."""
    synth = _source("synthesized://llm", "Typical packs sell for £79.")
    op = _StubOp({"anchors": [{"amount": 79, "currency": "GBP", "cadence": "one_off",
                               "what": "pack", "source_id": synth.source_id}]})
    res = extract_anchors(op, _candidate(), [synth], cfg)
    assert res.anchors == []
    assert res.degraded is True
    assert op.calls == 0, "no LLM call should fire with nothing citable"


def test_extraction_failure_degrades_and_never_raises(cfg: Config):
    class _Boom(_StubOp):
        def complete_json(self, *a, **kw):
            raise RuntimeError("brain down")

    res = extract_anchors(_Boom({}), _candidate(),
                          [_source("https://a.example", "£49 a pop")], cfg)
    assert res.anchors == []
    assert res.degraded is True


# --- 3. FX is declared, never guessed --------------------------------------

def test_undeclared_currency_carries_no_pence_and_is_never_eligible(cfg: Config):
    """The rule is UNDECLARED -> no pence. It is not "GBP is the only declared rate".

    This test used to assert `to_pence_gbp(49, "USD", fx) is None`, i.e. it pinned the
    contents of config.yaml rather than the rule the contents were an instance of. On
    2026-08-13 a sourced USD/EUR rate was added — `fx_source: "US Federal Reserve H.10,
    release 2026-08-12"`, `fx_asof: "2026-08-07"` — which is precisely the "explicit,
    sourced config act" the old assertion's own message demanded, and the test failed
    anyway, blocking every commit in the repo. A test that fails when the thing it asks
    for is delivered is testing the wrong noun.

    So: pick a currency that is genuinely absent from the config, and separately require
    that any rate which IS declared came with its provenance.
    """
    conf = comparables_config(cfg)
    fx = conf["fx_to_gbp"]
    assert to_pence_gbp(49, "GBP", fx) == 4900

    absent = next(c for c in ("JPY", "CHF", "AUD", "SEK") if c not in fx)
    assert to_pence_gbp(49, absent, fx) is None, (
        f"{absent} is not declared in config.yaml; an undeclared rate must never be guessed")

    anchor = PriceAnchor(amount=49, currency=absent, cadence="one_off", what="x",
                         source_id="s", url="https://a.example", amount_pence_gbp=None)
    assert eligible_anchors([anchor], cfg) == []


def test_every_declared_non_gbp_rate_carries_its_source(cfg: Config):
    """An FX rate is evidence about the world, so source-or-die applies to it too.

    This is the half of the old assertion that was worth keeping: a non-GBP rate may exist,
    but only as a dated, attributed act. Without this, dropping the previous assertion would
    have left the config free to grow unsourced rates silently.
    """
    conf = comparables_config(cfg)
    non_gbp = {k for k in conf["fx_to_gbp"] if k != "GBP"}
    if not non_gbp:
        return  # GBP-only is always fine; there is nothing to source.

    assert conf.get("fx_source"), (
        f"config declares FX rates {sorted(non_gbp)} with no `fx_source` — an unsourced "
        f"rate is a guess with a decimal point on it")
    assert conf.get("fx_asof"), (
        f"config declares FX rates {sorted(non_gbp)} with no `fx_asof` — a rate with no date "
        f"cannot be told from a stale one")


def test_a_declared_rate_converts(cfg: Config):
    c = _with_comparables(cfg, fx_to_gbp={"GBP": 1.0, "USD": 0.8})
    assert to_pence_gbp(50, "USD", comparables_config(c)["fx_to_gbp"]) == 4000


def test_ineligible_cadence_is_kept_as_evidence_but_cannot_price(cfg: Config):
    monthly = _anchor(2900, cadence="monthly")
    assert eligible_anchors([monthly], cfg) == []
    assert anchor_evidence([monthly] * 5, cfg) is None


# --- 4. Evidence thresholds ------------------------------------------------

def test_too_few_anchors_is_not_evidence(cfg: Config):
    anchors = [_anchor(7900, url="https://a.example/p"),
               _anchor(8900, url="https://b.example/p")]
    assert comparables_config(cfg)["min_anchors"] == 3
    assert anchor_evidence(anchors, cfg) is None


def test_one_domain_is_one_data_point_however_many_prices_it_lists(cfg: Config):
    anchors = [_anchor(7900, url="https://same.example/pricing") for _ in range(6)]
    assert anchor_evidence(anchors, cfg) is None


def test_evidence_uses_the_median_not_the_mean(cfg: Config):
    """One outlier that survived the bounds rail must not drag the decision across a rung."""
    anchors = [_anchor(4900, url="https://a.example/p"),
               _anchor(4900, url="https://b.example/p"),
               _anchor(49000, url="https://c.example/p")]
    ev = anchor_evidence(anchors, cfg)
    assert ev is not None
    assert ev["median_pence"] == 4900
    assert ev["n"] == 3
    assert len(ev["domains"]) == 3


# --- 5. Landing this check moves no price ----------------------------------

def test_rung_adjust_is_off_by_default(cfg: Config):
    assert comparables_config(cfg)["rung_adjust_enabled"] is False


def test_anchors_do_not_move_a_price_while_adjustment_is_disabled(cfg: Config):
    """The golden matrix in test_pricing.py must hold unchanged in the presence of strong
    contrary evidence. Retrieving evidence and acting on it are two separate decisions."""
    loud = [_anchor(19900, url=f"https://{d}.example/p") for d in ("a", "b", "c", "d")]
    baseline = price_for(_candidate("smb"), _score(), cfg)
    with_anchors = price_for(_candidate("smb"), _score(), cfg, anchors=loud)
    assert with_anchors.price_pence == baseline.price_pence == 4999
    assert with_anchors.evidence is None


def test_enabled_adjustment_moves_at_most_one_rung_up(cfg: Config):
    c = _with_comparables(cfg, rung_adjust_enabled=True)
    rungs = list(c.listing["pricing"]["rungs"])          # [1999, 2999, 4999, 7999, ...]
    # smb sits at index 2 (4999). Comparables far above the TOP rung must still move one.
    loud = [_anchor(19900, url=f"https://{d}.example/p") for d in ("a", "b", "c", "d")]
    d = price_for(_candidate("smb"), _score(), c, anchors=loud)
    assert d.price_pence == rungs[3] == 7999
    assert d.evidence is not None
    assert d.evidence["median_pence"] == 19900
    assert "Adjusted one rung up" in d.rationale


def test_enabled_adjustment_moves_one_rung_down(cfg: Config):
    c = _with_comparables(cfg, rung_adjust_enabled=True)
    cheap = [_anchor(1900, url=f"https://{d}.example/p") for d in ("a", "b", "c")]
    d = price_for(_candidate("smb"), _score(), c, anchors=cheap)
    assert d.price_pence == 2999
    assert "Adjusted one rung down" in d.rationale


def test_evidence_that_does_not_clear_an_adjacent_rung_leaves_the_ladder_alone(cfg: Config):
    """A median that merely leans upward is not evidence the ladder is wrong. Rungs exist so
    that crossing one is a decision."""
    c = _with_comparables(cfg, rung_adjust_enabled=True)
    leaning = [_anchor(5900, url=f"https://{d}.example/p") for d in ("a", "b", "c")]
    d = price_for(_candidate("smb"), _score(), c, anchors=leaning)
    assert d.price_pence == 4999
    assert d.evidence is None
    assert "did not clear an adjacent rung" in d.rationale


def test_an_unclassified_pack_is_never_repriced_by_comparables(cfg: Config):
    """Holding the back catalogue at 4999 is the ladder's central safety property.
    Comparables must not be the side door that re-prices it."""
    c = _with_comparables(cfg, rung_adjust_enabled=True)
    loud = [_anchor(19900, url=f"https://{d}.example/p") for d in ("a", "b", "c", "d")]
    d = price_for(_candidate(tier=""), _score(), c, anchors=loud)
    assert d.price_pence == 4999
    assert d.evidence is None


def test_adjustment_cannot_walk_off_either_end_of_the_ladder(cfg: Config):
    c = _with_comparables(cfg, rung_adjust_enabled=True)
    rungs = list(c.listing["pricing"]["rungs"])
    # venture sits at index 5; us adds one, landing on the top rung (index 6).
    top = [_anchor(rungs[-1] * 10, url=f"https://{d}.example/p") for d in ("a", "b", "c")]
    d = price_for(_candidate("venture", "us"), _score(), c, anchors=top)
    assert d.price_pence == rungs[-1]

    # ...and the bottom: a tier pinned to rung 0 with anchors below every rung stays put.
    floor_cfg = copy.deepcopy(c)
    floor_cfg.listing["pricing"]["tier_rung_index"] = dict(
        floor_cfg.listing["pricing"]["tier_rung_index"], side_hustle=0)
    cheap = [_anchor(100, url=f"https://{d}.example/p") for d in ("a", "b", "c")]
    d2 = price_for(_candidate("side_hustle"), _score(), floor_cfg, anchors=cheap)
    assert d2.price_pence == rungs[0]


# --- queries ---------------------------------------------------------------

def test_queries_target_price_pages_and_are_deterministic(cfg: Config):
    cand = _candidate()
    first = comparables_queries(cand, cfg)
    assert first == comparables_queries(cand, cfg)
    assert any("pricing" in q or "price" in q for q in first)
    assert all("{q}" not in q for q in first)


def test_config_defaults_survive_a_missing_comparables_block(cfg: Config):
    """A config written before C3 existed must still load and behave — with the check off."""
    c = copy.deepcopy(cfg)
    c.listing["pricing"].pop("comparables", None)
    conf = comparables_config(c)
    assert conf["enabled"] is False
    assert conf["rung_adjust_enabled"] is False
    assert conf["fx_to_gbp"] == {"GBP": 1.0}
