"""The currency backfill must fix rendered rows and never touch a cited figure.

The whole risk of this repair is that both defects LOOK identical — a `$` in a `uk` pack —
while one is Python stamping the wrong symbol on its own arithmetic and the other is the
model quoting a US source at its real US price. Rewriting the second falsifies a citation
on a storefront whose first rule is source-or-die, and nothing downstream would catch it:
the pack would lint clean and sell, carrying a number no source supports.

So these tests deliberately put the SAME symbol on both sides of the renderer's free-text
boundary in one artifact, and pin that only the rendered side moves.
"""
from tools.backfill_pack_currency import _foreign_elsewhere, _repair_rendered

# A `uk` pack whose rendered rows are correct (£) but whose Key Assumptions quote a US
# comparable at its real US price — exactly the shape of the four packs this tool must
# leave alone (13795bea, 736fe5af, 904b6a0b, 9e662c07).
UK_PACK_WITH_A_CITED_US_PRICE = """## Financial Model

### Customer Lifetime Value (CLV)
- **£295**

### Month 1 P&L
- Overhead: £30,000 _(revenue not specified)_

### Key Assumptions (grounded in verified claims)
- The nearest incumbent, getowed.us, charges $0.75 per invoice (source: getowed.us/pricing).
- PACER charges $0.10 per page (source: https://pacer.uscourts.gov/).

### Model Weaknesses
- ⚠️  A $47,000 annual loss was self-reported in a single LinkedIn post.
"""

# A `us` pack rendered before 091e806: Python stamped £ on figures the model supplied in
# USD, and says so itself two sections down.
US_PACK_RENDERED_IN_STERLING = """## Financial Model

### Customer Lifetime Value (CLV)
- **£295**

### Month 1 P&L
- Overhead: £30,000 _(revenue not specified)_

### Key Assumptions (grounded in verified claims)
- Customer lifetime value equals the single $295 fee, as there is no recurring revenue.
- Overhead for month 1 is estimated at $30,000 per month, covering a team of three.
"""


def test_a_cited_foreign_price_below_the_boundary_is_never_rewritten():
    out, changed = _repair_rendered(UK_PACK_WITH_A_CITED_US_PRICE, "£")

    assert changed == [], "rendered rows were already correct; nothing should be touched"
    assert out == UK_PACK_WITH_A_CITED_US_PRICE
    # The citations still say what their sources say.
    assert "$0.75 per invoice" in out
    assert "$0.10 per page" in out
    assert "$47,000" in out
    assert "£0.75" not in out and "£0.10" not in out and "£47,000" not in out


def test_the_quoted_figures_are_reported_so_a_human_can_judge_them():
    quoted = _foreign_elsewhere(UK_PACK_WITH_A_CITED_US_PRICE, "£")

    # Reported, not silently ignored: "no price page in your currency" is a fact about the
    # world, and the operator decides whether to add a home-currency figure alongside.
    assert any("$0.75" in q for q in quoted)
    assert any("$0.10" in q for q in quoted)
    assert any("$47,000" in q for q in quoted)


def test_a_rendered_row_in_the_wrong_symbol_is_repaired_without_moving_a_digit():
    out, changed = _repair_rendered(US_PACK_RENDERED_IN_STERLING, "$")

    assert "- **$295**" in out
    assert "- Overhead: $30,000 _(revenue not specified)_" in out
    assert "£" not in out
    assert len(changed) == 2

    # The repair is a symbol swap and nothing else. Every number survives intact — a
    # backfill that "corrects" 295 into a converted 231 would be inventing a figure.
    for amount in ("295", "30,000"):
        assert out.count(amount) == US_PACK_RENDERED_IN_STERLING.count(amount)


def test_the_models_own_prose_is_untouched_even_when_it_agrees_with_the_repair():
    out, _ = _repair_rendered(US_PACK_RENDERED_IN_STERLING, "$")

    # These lines already said $ and sit below the boundary; the tool must not have been
    # what put them right, or the boundary is not being honoured.
    assert "- Customer lifetime value equals the single $295 fee" in out
    assert "- Overhead for month 1 is estimated at $30,000 per month" in out


def test_an_artifact_with_no_free_text_headers_is_still_fully_repaired():
    # Missing lists are legal output (`if assumptions_list:`), so the boundary search has
    # to fall back to "all of it is rendered" rather than to "none of it is".
    bare = "## Financial Model\n\n### Payback Period\n- CAC: £120 _(not specified)_\n"
    out, changed = _repair_rendered(bare, "$")

    assert "- CAC: $120 _(not specified)_" in out
    assert len(changed) == 1


def test_a_bare_symbol_not_bound_to_a_digit_is_left_alone():
    # "priced in $ per seat" is prose, not an amount. Guessing at it is how a backfill
    # starts editing sentences.
    text = "## Financial Model\n\n### Revenue\n- Sold in £ per seat, £40 per month\n"
    out, _ = _repair_rendered(text, "$")

    assert "Sold in £ per seat" in out
    assert "$40 per month" in out
