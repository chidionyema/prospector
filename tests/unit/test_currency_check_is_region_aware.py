"""`check_currency` must stay strict on rendered rows and tolerant of cited comparables.

Both halves are load-bearing and they pull in opposite directions, so each is pinned here.

The strict half exists because `_render_financial_model` hardcoded `£` until 091e806: a `us`
pack shipped `- **£295**` as its headline while its own justification two sections down said
`$295`. Python stamping the wrong symbol on its own arithmetic is never acceptable.

The tolerant half exists because the strict rule was applied to the whole artifact, including
the two model-authored lists the renderer appends. In a `uk` pack, "PACER charges $0.10 per
page (source: pacer.uscourts.gov)" is foreign because the SOURCE is foreign. The only edit
that satisfied a whole-artifact rule was rewriting the figure — which fabricates a number no
source supports, on a storefront whose first rule is source-or-die.
"""
from prospector.artifacts import _render_financial_model
from prospector.pack_linter import (
    FINANCIAL_MODEL_FREE_TEXT_HEADERS,
    FINANCIAL_MODEL_FREE_TEXT_HEADERS_CURRENT,
    FINANCIAL_MODEL_FREE_TEXT_HEADERS_LEGACY,
    check_currency,
    split_rendered_free_text,
)

RENDERED_IN_STERLING = """## Financial Model

### Customer Lifetime Value (CLV)
- **£295**

### Key Assumptions (grounded in verified claims)
- Customer lifetime value equals the single $295 fee.
"""

CITED_COMPARABLE = """## Financial Model

### Customer Lifetime Value (CLV)
- **£9**

### Key Assumptions (grounded in verified claims)
- PACER charges $0.10 per page (source: https://pacer.uscourts.gov/).
"""

FOREIGN_ONLY = """## Financial Model

### Customer Lifetime Value (CLV)
- _(not specified)_

### Key Assumptions (grounded in verified claims)
- The only buyer-facing price found is a €7.55/month subscription.
"""


def _errors(problems):
    return [p for p in problems if p["severity"] == "error"]


def _warnings(problems):
    return [p for p in problems if p["severity"] == "warning"]


def test_a_wrong_symbol_on_a_rendered_row_is_still_an_error():
    # The regression guard. If this ever softens, the defect the check was written for
    # walks straight back onto the shelf.
    problems = check_currency(RENDERED_IN_STERLING, "", "us")
    errs = _errors(problems)

    assert errs, "a £ headline in a us pack must block the sale"
    assert errs[0]["where"] == "financial_model"
    assert "1 '£' amount(s) in a 'us' pack" in errs[0]["detail"]


def test_a_cited_foreign_price_in_the_notes_is_a_warning_not_a_blocker():
    problems = check_currency(CITED_COMPARABLE, "", "uk")

    assert _errors(problems) == [], "a quoted US source price must not hold a uk pack back"
    warns = _warnings(problems)
    assert len(warns) == 1
    assert warns[0]["where"] == "financial_model_notes"


def test_foreign_only_notes_are_still_an_error():
    # The buyer never sees their own currency anywhere in the artifact. That is the case
    # the tolerant branch must NOT wave through.
    errs = _errors(check_currency(FOREIGN_ONLY, "", "uk"))

    assert len(errs) == 1
    assert errs[0]["where"] == "financial_model_notes"
    assert "only '€' amounts in a 'uk' pack" in errs[0]["detail"]


def test_the_home_currency_may_come_from_the_rendered_rows_above():
    # `- **£9**` sits above the boundary and the `$` below it. The buyer reads one document,
    # so co-occurrence is judged across the whole artifact, not within the notes alone.
    _, notes = split_rendered_free_text(CITED_COMPARABLE)

    assert "£" not in notes, "fixture must isolate the home symbol to the rendered region"
    assert _errors(check_currency(CITED_COMPARABLE, "", "uk")) == []


def test_an_artifact_with_no_notes_is_graded_entirely_as_rendered():
    # Both lists are conditional in the renderer, so "no headers" must fall back to
    # all-rendered. Falling back the other way would silently disable the strict half.
    bare = "## Financial Model\n\n### Payback Period\n- CAC: £120\n"
    rendered, notes = split_rendered_free_text(bare)

    assert rendered == bare and notes == ""
    assert _errors(check_currency(bare, "", "us"))


def test_the_boundary_headers_match_what_the_renderer_actually_emits():
    """The fix is inert if these strings drift from the renderer.

    Without this, renaming a header in artifacts.py would send every artifact down the
    all-rendered fallback, and cited comparables would start blocking packs again with no
    test going red — the failure mode is silent re-tightening, not a crash.
    """
    out = _render_financial_model(
        {
            "monthly_price": 10,
            "target_customers_month_1": 5,
            "assumptions": ["A US comparable charges $0.10 per page."],
            "weaknesses": ["The €7.55 anchor is a different product."],
        },
        claims=[],
        currency="£",
    )

    for header in FINANCIAL_MODEL_FREE_TEXT_HEADERS_CURRENT:
        assert header in out, f"renderer no longer emits {header!r}"
    # The legacy spellings are NOT asserted against the renderer — nothing emits them since
    # 2026-08-14 — but the boundary has to keep recognising them for the packs on disk.
    for header in FINANCIAL_MODEL_FREE_TEXT_HEADERS_LEGACY:
        assert header in FINANCIAL_MODEL_FREE_TEXT_HEADERS

    rendered, notes = split_rendered_free_text(out)
    assert "$0.10 per page" in notes and "€7.55" in notes
    assert "$" not in rendered and "€" not in rendered
    # And the whole point: this pack is sellable.
    assert _errors(check_currency(out, "", "uk")) == []
