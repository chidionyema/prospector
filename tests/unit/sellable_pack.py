"""A pack that actually clears every content gate, for tests about what happens AFTER them.

Why this exists. `publish_pass` decides `content_ok` (completeness + bundle audit + Q2 lint)
BEFORE it mints anything, because a pack that cannot list must not leave a Stripe Product
behind. That reorder exposed a latent hole in the money-rail tests: their fixtures were stub
packs — 23-byte artifacts, no financial sections — so they had been asserting on the MINT
path while describing a pack that could never be sold. They passed only because minting used
to happen unconditionally.

So the fixtures need a pack that is genuinely sellable. Everything here is sized against the
real validators rather than guessed:

  * prose artifacts  — >= MIN_PROSE_CHARS (600) and >= MIN_PROSE_BLOCKS (3) blank-line blocks
                       (prospector/pack_validation.py:33-35)
  * financial_model  — carries all four REQUIRED_FIN_SECTIONS (pack_linter.py:208)
  * marketing        — listing_page >= MIN_MARKETING_CHARS, plus enough other copy that
                       Marketing_Assets.md clears _MIN_BUNDLE_ENTRY_BYTES (bridge.py:210)

Two deliberate properties, both load-bearing for keeping these tests fast and offline:

  * NO URLs anywhere. `config.yaml` sets `listing.lint_check_urls: true`, so any URL in this
    text would put a live HTTP probe inside a unit test.
  * NO figures matching the arithmetic regexes (`_MONTH_RE`, `_GM_RE`, `_PAYBACK_CALC_RE`
    and friends, pack_linter.py:135-201). The financial model is deliberately prose: these
    tests are about the money RAIL, not about arithmetic linting, which
    tests/unit/test_q2_pack_linter.py owns and covers directly.
"""
from __future__ import annotations

from typing import Any, Dict, List

from prospector.artifacts import _render_financial_model

_BUILD_SPEC = """## Architecture

The service ingests fuel-card statements, matches each transaction against the vehicle that
drew it, and files a duty reclaim on the operator's behalf. Ingestion, matching and filing are
three separate workers so that a slow filing queue never blocks intake.

## Data model

An operator owns vehicles; a vehicle accumulates transactions; a reclaim batches transactions
into one submission for one period. Reclaims are immutable once submitted, so a correction is
a new reclaim that supersedes its predecessor rather than an edit to a filed record.

## Interfaces

Statement import accepts the three formats the major fuel-card issuers export. The reclaim
submission is a single form, filed on a monthly cadence, with the evidence bundle attached.

## Build order

Import and matching first, because they are what an operator can evaluate without trusting us
with a filing. Submission last, behind a manual review step until the match rate is proven.
"""

_GTM_PLAN = """## Who buys

Fleet operators running between twelve and eighty vehicles. Below twelve the reclaim is not
worth the operator's attention; above eighty they already employ someone whose job this is.

## How they are reached

Fuel-card issuers and fleet-maintenance providers both sit upstream of the buyer and both
already sell adjacent services. A referral arrangement reaches operators at the point where
they are thinking about fuel cost, which is the only moment the pitch lands.

## What convinces them

A reclaim estimate computed from their own statement, produced before any commitment. The
estimate is the sales asset, because it converts an abstract promise into a number the
operator recognises from their own books.

## Pricing posture

A share of the recovered amount reads as free to a sceptical operator and aligns the incentive
with the outcome. A subscription asks for trust the first conversation has not earned yet.
"""

_OPS_PLAN = """## Running the service

Two operational loops. The daily loop reconciles imported statements against vehicles and
escalates anything that failed to match. The monthly loop assembles, reviews and files each
reclaim before its deadline.

## Failure handling

An unmatched transaction is never guessed at. It is held, surfaced to the operator, and either
resolved or excluded from the reclaim. A wrong match becomes a wrong filing, and a wrong filing
costs far more than the transaction it would have recovered.

## Staffing

One reviewer can carry the monthly loop for roughly forty operators at the match rates we
target. Review is the constraint on growth, so match-rate work buys capacity directly.

## Compliance

Filings and their evidence are retained for the statutory period. Every submission records who
reviewed it and when, because a reclaim that cannot be explained cannot be defended.
"""

# The Python-rendered head comes from the renderer itself — this fixture asserts that a
# pack the pipeline can actually produce is sellable, so a transcribed head would let the
# claim survive a renderer change. The prose below it is the model-authored tail.
_FIN_INPUTS = {"revenue_model": "subscription", "monthly_price": 40,
               "target_customers_month_1": 12, "target_customers_month_12": 90,
               "estimated_cac_gbp": 90, "estimated_monthly_churn_pct": 4.0,
               "cost_of_goods_pct": 35, "overhead_month_1_gbp": 400}

_FINANCIAL_TAIL = """
### How the revenue works

Revenue is a share of what each operator actually recovers, billed only after the reclaim is
paid out. Recovery scales with fleet size and with the share of transactions matched, so
revenue per operator rises as the matching improves rather than needing a price change.

### What it costs to run

The variable cost is reviewer time in the monthly loop. Infrastructure is immaterial next to
it, so the cost line is effectively a staffing line.

### Why the money comes back

Retention is the lever that matters here. An operator who files once through the service and
sees the money arrive has no reason to return to filing it themselves, so lifetime value is
governed by fleet churn rather than by product churn.
"""


def financial_model(currency: str = "£") -> str:
    """The rendered model in THIS market's symbol.

    It has to be parameterised: `check_currency` refuses a pack whose money symbol
    contradicts its market (a `us` pack quoting £), and every figure above is Python
    formatting `currency` — so a hardcoded £ here made the four `us` money-rail fixtures
    unsellable the moment the renderer started printing real numbers.
    """
    return _render_financial_model(_FIN_INPUTS, [], currency) + _FINANCIAL_TAIL


_LISTING_COPY = """# FuelClaim

Small fleet operators leave fuel duty unclaimed because the filing costs more attention than
the money appears to be worth. FuelClaim imports the fuel-card statement, matches every
transaction to the vehicle that drew it, and files the reclaim on a monthly cadence.

You are billed a share of what is actually recovered, after it arrives.
"""

_EMAIL_COPY = """Subject: the fuel duty your fleet is not reclaiming

Most operators between twelve and eighty vehicles never file, because the paperwork is priced
in attention rather than money and the amount is invisible until someone computes it.

Send one statement and we will compute the estimate from your own numbers, before you commit
to anything at all.
"""

_SOCIAL_COPY = """Fuel duty reclaims are not hard. They are tedious, which is worse, because tedious work loses
to whatever else is on the operator's desk that week.

We import the statement, match the transactions, and file on a monthly cadence. Billing is a
share of what arrives, so an unsuccessful reclaim costs the operator nothing at all.
"""


def sellable_artifacts(currency: str = "£") -> Dict[str, str]:
    """The four required artifacts, each above its real floor."""
    return {
        "build_spec": _BUILD_SPEC,
        "gtm_plan": _GTM_PLAN,
        "ops_plan": _OPS_PLAN,
        "financial_model": financial_model(currency),
    }


def sellable_marketing() -> List[Dict[str, str]]:
    """Marketing copy, including enough non-listing copy for Marketing_Assets.md to clear
    the 120-byte bundle stub floor."""
    return [
        {"type": "listing_page", "copy": _LISTING_COPY},
        {"type": "email", "copy": _EMAIL_COPY},
        {"type": "social", "copy": _SOCIAL_COPY},
    ]


#: Market → money symbol, the same mapping the currency lint holds packs to. A fixture that
#: publishes into a market has to render in that market's symbol or it is not sellable.
_MARKET_SYMBOL = {"us": "$", "eu": "€"}


def symbol_for_market(market: str) -> str:
    return _MARKET_SYMBOL.get(str(market or "").strip().lower(), "£")


def sellable_tags(currency: str = "£", **extra: Any) -> Dict[str, Any]:
    """`candidate.tags` for a pack that clears completeness, the bundle audit and the lint."""
    tags: Dict[str, Any] = {
        "artifacts": sellable_artifacts(currency),
        "marketing": sellable_marketing(),
    }
    tags.update(extra)
    return tags
