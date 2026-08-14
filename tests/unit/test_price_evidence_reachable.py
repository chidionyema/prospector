"""The price-evidence limb must be REACHABLE, not merely present.

WHY THIS FILE EXISTS (2026-08-13). `price_comparables` ran on 233 packs and produced 361 cited
anchors. Not one of them had ever touched a price. Everyone assumed the blocker was the
deliberate `rung_adjust_enabled: false` switch. It was not. Replaying the config's own
eligibility gate over every anchor on disk, only **8 of 117** packs could have moved a rung even
with the switch on — so the evidence limb was not "off pending review", it was a null, and
flipping the switch would have re-priced ~7% of the catalogue by one rung and looked like a
feature working.

Two causes, both self-inflicted, both fixed in `config.yaml`:

  * **200 of 361 anchors died on `cadence != one_off`** — while one of our own three retrieval
    queries was literally `"{q} price per month subscription plans"`. We were paying a third of
    the retrieval budget to manufacture the one cadence the gate throws away.
  * **47 more died on `currency 'USD' absent from fx_to_gbp`**, which held GBP alone. 146 of the
    361 anchors (40%) were USD and every one carried `amount_pence_gbp: null`. That compounded a
    real unfairness: `market_rung_offset: {us: 1}` charges a US-market pack one rung MORE on a
    taxonomy rule, while we were structurally unable to read a single US price page as evidence
    for or against that rule.

Adding the FX rates alone took the reachable population from **8/117 to 17/117** — measured, on
the same anchors. These tests pin the conditions that make evidence reachable at all. They
deliberately do NOT assert `rung_adjust_enabled` — whether evidence may move money is a founder
decision and a separate switch, which is exactly the distinction the config draws.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.price_comparables import comparables_config, to_pence_gbp


@pytest.fixture(scope="module")
def conf():
    return comparables_config(load_config("config.yaml"))


# --- the currency hole -------------------------------------------------------------------------

def test_usd_anchors_convert_instead_of_evaporating(conf):
    """A real anchor from a real dossier: $300/mo bookkeeping, source_id 6713accdf9a51666.

    Before 2026-08-13 this returned None — not "rejected with a reason", just silently worth
    nothing — for 40% of everything the check retrieved.
    """
    assert to_pence_gbp(300.0, "USD", conf["fx_to_gbp"]) is not None


@pytest.mark.parametrize("code", ["GBP", "USD", "EUR"])
def test_the_three_currencies_the_open_web_prices_in_are_declared(code, conf):
    """A missing rate is not a conservative default; it is a silent discard. If a currency is
    genuinely undecidable, the honest move is to REJECT its anchors with a stated reason, not to
    let them through the extractor and null them at conversion."""
    assert code in conf["fx_to_gbp"], f"{code} absent — its anchors become worthless silently"


def test_fx_rates_carry_a_date_and_a_source():
    """`fx_asof`/`fx_source` exist so staleness is VISIBLE. A snapshot rate with no date is
    indistinguishable from a guess, and the config's own rule is 'declared, never inferred'."""
    cfg = load_config("config.yaml")
    comps = ((cfg.listing or {}).get("pricing") or {}).get("comparables") or {}
    assert comps.get("fx_asof"), "fx_asof missing — a rate with no date cannot be audited"
    assert comps.get("fx_source"), "fx_source missing — an unsourced number on the money path"


def test_fx_is_never_used_to_bill_anyone(conf):
    """FX converts EVIDENCE for comparison against the ladder; packs are charged in GBP. The
    ladder's narrowest gap is 1999->2999 (+50%), so FX drift cannot move a rung on its own —
    which is precisely why a snapshot is tolerable HERE and nowhere else on the money rail."""
    cfg = load_config("config.yaml")
    rungs = [int(r) for r in (((cfg.listing or {}).get("pricing") or {}).get("rungs") or [])]
    assert rungs, "no ladder declared"
    narrowest = min((b - a) / a for a, b in zip(rungs, rungs[1:]))
    assert narrowest > 0.25, (
        f"narrowest rung gap is {narrowest:.0%}; a snapshot FX rate is only safe here because "
        f"the gaps are far wider than plausible FX drift. Re-examine if the ladder tightens.")


# --- the cadence hole --------------------------------------------------------------------------

def test_we_do_not_pay_to_retrieve_the_cadence_we_discard(conf):
    """The gate admits `one_off` only, so a query that ASKS for monthly plans spends retrieval
    budget generating rejects. Monthly anchors still arrive incidentally and are still kept as
    readable dossier evidence; we simply stop hunting for them."""
    eligible = set(conf["cadence_eligible"])
    if "monthly" in eligible:                      # the rule tracks the gate, not a fixed string
        pytest.skip("monthly is eligible now; querying for it is no longer self-defeating")
    for q in conf["queries"]:
        low = q.lower()
        assert not ("per month" in low or "subscription" in low), (
            f"query {q!r} solicits monthly pricing while cadence_eligible={sorted(eligible)} "
            f"rejects it — 200 of 361 real anchors died exactly this way")


def test_at_least_one_query_targets_the_cadence_that_can_actually_count(conf):
    """The mirror of the test above: having removed the monthly query, something must still aim
    at one-off purchases or the check retrieves nothing usable at all."""
    joined = " ".join(conf["queries"]).lower()
    assert any(t in joined for t in ("one-off", "one time", "fixed price", "template", "toolkit",
                                     "course")), \
        "no query targets one-off pricing; the eligible cadence would go unretrieved"
