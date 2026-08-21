"""`exec_summary_md` said it could not write a named case. It can quote one.

**Every negative here is ONE property removed from `BASE`, and `BASE` is asserted to pass.**
That is not style. The first draft of this file wrote a plausible-looking rejection fixture per
filter, and a mutation run said 6 of 11 deliberate bugs SURVIVED: each fixture was being
rejected by two or three filters at once, so the filter under test never ran. A fixture that
fails for the right reason by accident grades nothing, which is the same class as the two
defects this module itself shipped -- see the table in `pack_lede`'s docstring.

`_only` is the mechanism: it asserts the base passes and the variant does not, so the variant
can only be failing on the property that was changed.
"""
import pytest

from prospector.pack_floors import exec_summary_md
from prospector.pack_lede import Lede, candidates, select_lede


class _Check:
    def __init__(self, verdict, sources):
        self.verdict = verdict
        self.sources = sources


def _lede(text, topic="", verdict="supported", url="https://ofgem.gov.uk/decisions/bg-2024"):
    return select_lede([{"source_id": "s1", "url": url, "text": text}],
                       [_Check(verdict, ["s1"])], topic)


#: Passes every filter. 132 chars, 22 alphabetic words, 18% of them capitalised, a finite verb,
#: a money stake, a named actor that is neither the opening word nor a place, and four content
#: words shared with TOPIC.
BASE = ("In March the regulator found that British Gas had charged 1,200 customers twice, "
        "and it was fined £24 million for the billing error.")
TOPIC = "energy billing errors British Gas customers charged refund regulator"


def _only(variant, topic=TOPIC):
    """The base passes, the variant does not, so the changed property is what rejected it."""
    assert _lede(BASE, topic) is not None, "the base fixture stopped qualifying"
    assert _lede(variant, topic) is None


def test_the_base_sentence_produces_a_lede():
    lede = _lede(BASE, TOPIC)
    assert lede is not None
    assert lede.text == BASE
    assert lede.url == "https://ofgem.gov.uk/decisions/bg-2024"
    assert lede.actor == "British Gas"


def test_the_lede_is_quoted_verbatim_and_never_paraphrased():
    """A buyer who follows the link must find the words they just read."""
    text = f"Some preamble first. {BASE} And a trailing sentence after it."
    assert _lede(text, TOPIC).text in text


def test_the_attribution_is_the_url_we_fetched():
    block = Lede(text=BASE, url="https://example.gov/x", source_id="s1",
                 actor="British Gas").as_markdown()
    assert "https://example.gov/x" in block
    assert block.startswith("> ")


@pytest.mark.parametrize("verdict", ["unverifiable", "refuted", "insufficient"])
def test_only_a_supported_check_makes_a_passage_evidence(verdict):
    assert _lede(BASE, TOPIC) is not None
    assert _lede(BASE, TOPIC, verdict=verdict) is None


def test_a_passage_no_check_cited_at_all_is_not_evidence():
    assert select_lede([{"source_id": "s1", "url": "https://x/1", "text": BASE}],
                       [], TOPIC) is None


def test_a_passage_with_no_url_is_dropped_rather_than_published_bare():
    assert _lede(BASE, TOPIC) is not None
    assert _lede(BASE, TOPIC, url="") is None


def test_a_blank_line_inside_a_sentence_means_it_is_a_scraped_block():
    """`_sentences` splits on [.!?] + whitespace, so a table whose cells carry no terminator
    arrives as one "sentence". Prose does not contain a blank line mid-sentence."""
    _only(BASE.replace("customers twice,", "customers twice\n\n"))


def test_title_case_is_a_product_name_not_a_situation():
    """This variant has the verb, the money, the actor and the topic overlap. The only thing
    wrong with it is that every word is capitalised, which is a page heading."""
    _only("Energy Bill Refund Claim Form For British Gas Customers Charged Twice In March "
          "Costing £24 Million Each Year")


def test_a_sentence_with_no_finite_verb_is_not_a_situation():
    _only(BASE.replace("found", "noted").replace("charged", "billed").replace("was fined", "saw"))


def test_a_sentence_with_no_stake_is_not_a_lede():
    """No money, no percentage, no duration: the reader has nothing to carry forward."""
    _only(BASE.replace("1,200 customers", "some customers")
              .replace("£24 million", "an undisclosed sum"))


def test_a_sentence_that_names_nobody_is_not_a_lede():
    _only(BASE.replace("British Gas", "the supplier"))


def test_a_bare_place_is_not_an_actor():
    """A country code matches the capitalised-token pattern and names nobody who did
    anything. `_PLACES` is what removes it, and this variant differs from the base only in
    which capitalised token is present."""
    _only(BASE.replace("British Gas", "the USA supplier"))


def test_a_supported_citation_that_is_off_subject_is_not_a_lede():
    """The base sentence is unchanged here -- only the TOPIC moves. A supported check can cite
    a passage that is off-subject, and in the first live run one did: French metal-detecting
    law opened an AI training-data provenance pack."""
    assert _lede(BASE, TOPIC) is not None
    assert _lede(BASE, "metal detecting heritage code france archaeology permits") is None


def test_a_sentence_too_short_to_be_a_situation_is_dropped():
    short = "It says John Smith paid 5% in 30 days for all of it now."
    longer = "It says John Smith paid 5% in 30 days for all of the money owed now."
    assert len(short) < 60 <= len(longer)
    assert _lede(longer) is not None
    assert _lede(short) is None


def test_a_run_on_sentence_is_dropped():
    """One sentence, no internal full stop, over MAX_CHARS. A quotation this long stops being
    a lede and becomes the passage itself."""
    run_on = BASE.rstrip(".") + (
        ", and the same regulator also said the same thing about several other suppliers in "
        "the same month, and it then repeated the whole of that finding again at length in a "
        "second notice issued the following week.")
    assert len(run_on) > 300
    _only(run_on)


def test_money_outranks_a_percentage_outranks_a_duration():
    """Three sentences of the same shape, differing only in which kind of stake they carry.
    All three qualify on their own, so the ordering is the only thing under test."""
    stem = ("In March the regulator found that British Gas had charged its customers twice, "
            "and ")
    money = f"{stem}it was fined £24 million over the billing error."
    pct = f"{stem}38% of them were refunded over the billing error."
    dur = f"{stem}it was given 90 days to refund the billing error."
    for one in (money, pct, dur):
        assert _lede(one, TOPIC) is not None
    sources = [{"source_id": f"s{i}", "url": f"https://x/{i}", "text": t}
               for i, t in enumerate((dur, pct, money))]
    checks = [_Check("supported", ["s0", "s1", "s2"])]
    assert select_lede(sources, checks, TOPIC).text == money
    assert select_lede(sources[:2], checks, TOPIC).text == pct


def test_the_opening_document_prints_the_lede_under_the_standfirst():
    class Cand:
        title = "Energy billing error refund evidence for British Gas customers"
        one_liner = "Cited evidence that the regulator already ruled on the billing error."
        who_pays = "Customers charged twice by British Gas."
        why_now = ""

    md = exec_summary_md(Cand(), [_Check("supported", ["s1"])],
                         [{"source_id": "s1", "url": "https://ofgem.gov.uk/x", "text": BASE}])
    assert BASE in md
    assert md.index(Cand.one_liner) < md.index(BASE)
    assert "https://ofgem.gov.uk/x" in md


def test_the_opening_document_is_unchanged_when_no_lede_exists():
    """89 of 108 live pass dossiers hold no qualifying line. None of them may gain a generic
    opening in place of one."""
    class Cand:
        title = "Pack"
        one_liner = "One line."
        who_pays = "SMEs."
        why_now = ""

    assert exec_summary_md(Cand(), [], []) == exec_summary_md(Cand(), [])


@pytest.mark.parametrize("bad", ["", "   ", "Too short."])
def test_a_fragment_is_never_a_lede(bad):
    assert _lede(bad, TOPIC) is None


def test_candidates_returns_every_survivor_not_only_the_winner():
    """`select_lede` ranks; `candidates` is the population an ops panel would count."""
    found = candidates([{"source_id": "s1", "url": "https://x/1", "text": BASE}],
                       [_Check("supported", ["s1"])], TOPIC)
    assert [c.text for c in found] == [BASE]


# --- Regression fixtures: the exact strings this module shipped before the filters existed. ---
# These are over-determined on purpose -- several filters reject each one now. They are here so
# that a future loosening of ANY filter is caught by the real output that motivated it, not to
# prove which filter is doing the work.

def test_regression_the_scraped_shipping_table():
    assert _lede("EVER MACH Oakland\n\nElevated\n\nERD drift expectation +1 to +7 days CY Cut "
                 "behavior repeated movement Volatility elevated Recommended buffer +2 days",
                 "Savannah port container dwell forecasts for 3PLs drift buffer") is None


def test_regression_the_temperature_log_book_product_listing():
    assert _lede("Temperature Log Book 6 Month Food Hygiene Record Chart Fridge Freezer "
                 "Checklist Pad 30 days Catering Supplies UK",
                 "Fridge hygiene loggers cafes takeaways temperature record") is None


def test_regression_french_metal_detecting_law_in_an_ai_provenance_pack():
    assert _lede("542-1 of the Heritage Code; significant finds must be reported to the "
                 "Ministry of Culture; penalties run to €1,500 for unauthorized detection and "
                 "€7,500 if digging occurs on a protected site.",
                 "Training data provenance audit for AI startup sales") is None
