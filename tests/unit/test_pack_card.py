"""P5: the one page a buyer pins up — `First_Fortnight.html`.

Founder, verbatim: **"markdown files is not the one."** The pack had no entry point that fits on
a sheet of paper, so the first thing a buyer met was eight `.md` files in a zip.

What these tests pin is not "the card renders". It is the three properties that decide whether
the card can be trusted on a pack somebody has ALREADY paid for:

  * it copies money, never computes or paraphrases it — a figure on the most-read page of the
    pack that contradicts the financial model is worse than no figure;
  * it reads every shape the financial model has been written in, not just the current one.
    The renderer's headings changed at least once ("### Revenue" became "### What it earns"),
    and the first version of this card matched the newer wording only — so it printed a blank
    where the money should be, on a live pack, and the smoke test caught it;
  * it never silently drops a step. Dropping renumbers the plan and hands the buyer a sequence
    with a hole in it.
"""
from __future__ import annotations

import html
import re

import pytest

from prospector import pack_card, pack_manifest
from prospector.dossier import check_label
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

# The old shape, as it sits in packs already sold: the figure is a bare bullet and its label is
# the heading above it.
OLD_MODEL_MD = """## Financial Model

### Revenue
- **Month 1:** £320 × 2 customers = **£640**
- **Month 12:** £320 × 16 customers = **£5,120**

### Payback Period
- **1 months**

### Key Assumptions (grounded in verified claims)
- Price is an assumption — unverified. A council's cut takes effect within weeks of the letter,
  which compresses the decision, and nothing retrieved says how long a buyer waits to pay back
  what the pack cost them, so the payback figure above is the model's and not the evidence's.
"""

# The current shape: the bullet carries its own label.
NEW_MODEL_MD = """## Financial Model

### What it earns

- **Month 1:** £320 × 2 sales = **£640**

### What it costs to win a buyer

- **Costs to win one buyer: £150**
- **Paid back in: ~5.2 months** — the model's own figure, not ours
"""

CHECKLIST_MD = """# First week

1. **Call three [councils](https://example.gov.uk) on the list** and ask who signs off care cuts.
2. Draft the letter template.
3. Post it in one carers' group and count the replies.
"""


def _dossier(checks=None) -> Dossier:
    cand = Candidate(
        candidate_id="c" * 16, title="Care Hours Appeal Pack",
        one_liner="Helps a family carer challenge a cut in council-funded care hours.",
        market="uk", who_pays="Unpaid family carers in England. They pay out of pocket.",
        why_now="Council budgets were cut in April.")
    return Dossier(candidate=cand, decision=Decision.PASS,
                   checks=checks if checks is not None else _checks(),
                   created_at="2026-07-31T00:00:00Z", provider_chain="claude-cli/default")


def _checks():
    return [
        CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.8,
                    rationale="Carers already pay solicitors for this fight.",
                    citations=["a" * 16],
                    sources=[Source(source_id="a" * 16, url="https://example.gov.uk/care",
                                    text="A retrieved passage.", query="q",
                                    fetched_at="2026-07-31T00:00:00Z")]),
        CheckResult(check_name="payer_solvency", verdict=Verdict.UNVERIFIABLE, confidence=0.2,
                    rationale="No passage states what a carer can afford.",
                    queries=["unpaid carer household income uk"]),
        CheckResult(check_name="distribution", verdict=Verdict.UNVERIFIABLE, confidence=0.1,
                    rationale="No passage states a reachable channel.", queries=["carer forums"]),
    ]


@pytest.fixture
def card() -> str:
    return pack_card.render(_dossier(), CHECKLIST_MD, NEW_MODEL_MD, "08b22037fc2afc07")


class TestItFitsOnOneSheet:
    def test_the_buyer_meets_the_title_and_who_pays_before_anything_else(self, card):
        assert "Care Hours Appeal Pack" in card
        assert "Who pays" in card
        assert "Unpaid family carers in England." in card

    def test_it_is_a_self_contained_page_a_buyer_can_open_from_their_own_disk(self, card):
        """Same rule as `pack_html`: no script, no external request. This file opens offline,
        from a downloaded zip, on a machine we know nothing about."""
        assert card.startswith("<!doctype html>")
        assert "<script" not in card.lower()
        assert "http://" not in card and "https://" not in card

    def test_the_pack_id_is_on_the_page_so_a_printed_sheet_can_be_traced_back(self, card):
        assert "08b22037fc2afc07" in card


class TestTheSteps:
    def test_they_are_the_checklists_own_steps_in_the_checklists_own_order(self, card):
        first = card.index("Call three councils")
        second = card.index("Draft the letter template")
        assert first < second < card.index("Post it in one carers")

    def test_markdown_never_arrives_as_literal_punctuation(self, card):
        """`storefront-renders-no-markdown-2026-07-31`, one layer in: the card prints steps as
        plain text inside its own typography, so `**bold**` and `[a](b)` must be gone."""
        assert "**" not in card
        assert "](https://example.gov.uk)" not in card
        assert "Call three councils on the list" in card

    def test_a_step_that_runs_to_a_paragraph_is_shortened_never_dropped(self):
        """Dropping renumbers the plan. The buyer then follows a sequence with a hole in it and
        has no way to know a step is missing — the card looks complete either way."""
        long_step = ("Register with the council's adult social care team. " + "x" * 400)
        md = f"1. Do the first thing.\n2. {long_step}\n3. Do the third thing.\n"
        steps = pack_card.steps_from_checklist(md)
        assert len(steps) == 3, "the long step must still be a step"
        assert steps[1].startswith("Register with the council's adult social care team.")
        assert len(steps[1]) <= 320

    def test_truncating_the_list_says_so_rather_than_pretending_that_was_all(self):
        md = "".join(f"{i}. Step number {i}.\n" for i in range(1, 20))
        out = pack_card.render(_dossier(), md, "", "")
        assert "The rest of the plan is in the first-week checklist" in out


class TestTheMoneyIsCopiedNeverComputed:
    @pytest.mark.parametrize("model_md,expected", [
        (NEW_MODEL_MD, "£320 × 2 sales = £640"),
        (OLD_MODEL_MD, "£320 × 2 customers = £640"),
    ])
    def test_month_one_revenue_is_read_out_of_both_document_shapes(self, model_md, expected):
        """The live defect: the first version matched only the newer wording, so every pack
        written before the financial model was re-headed showed no money at all."""
        assert ("Month 1 revenue", expected) in pack_card._headline_money(model_md)

    @pytest.mark.parametrize("model_md,expected", [
        (NEW_MODEL_MD, "~5.2 months"),
        (OLD_MODEL_MD, "1 months"),
    ])
    def test_payback_is_read_from_the_bullets_label_or_from_the_heading_above_it(
            self, model_md, expected):
        assert ("Payback", expected) in pack_card._headline_money(model_md)

    def test_a_figure_is_reproduced_exactly_as_the_model_printed_it(self, card):
        """Including "1 months" and "£2 × 500 customers = £995", which are the model's own
        rounding and its own grammar. Correcting them here would make the card disagree with
        the document it summarises, and the document is the one with the arithmetic in it."""
        assert "£320 × 2 sales = £640" in card

    def test_a_paragraph_that_merely_mentions_payback_is_not_put_in_a_fact_box(self):
        """Measured on live pack `08b22037fc2afc07`: the assumptions list at the foot of the
        financial model matched on the word, and 140 words of prose landed where the buyer
        looks for a number."""
        facts = dict(pack_card._headline_money(OLD_MODEL_MD))
        assert facts["Payback"] == "1 months"
        assert "compresses the decision" not in facts["Payback"]

    def test_the_models_own_words_for_i_could_not_work_this_out_are_not_printed_as_a_figure(self):
        md = ("### Revenue\n- **Month 1:** (price or customer target not specified)\n"
              "### Payback Period\n- **(not specified)**\n")
        assert pack_card._headline_money(md) == []

    def test_the_models_aside_about_itself_is_left_in_the_document_it_belongs_to(self):
        """"— the model's own figure, not ours" is true, and already stated where it matters.
        On a one-page card it costs the fact below it its place on the sheet."""
        assert ("Payback", "~5.2 months") in pack_card._headline_money(NEW_MODEL_MD)


class TestWhereTheBuyersOwnHomeworkStarts:
    def test_the_unproven_checks_are_named_in_the_same_words_as_the_rest_of_the_pack(self, card):
        assert "Start your own homework here" in card
        assert html.escape(check_label("payer_solvency")) in card
        assert html.escape(check_label("distribution")) in card

    def test_a_proven_check_is_not_listed_as_homework(self, card):
        block = card.split("Start your own homework here")[1]
        assert check_label("pain_reality") not in block

    def test_a_pack_with_nothing_unproven_does_not_print_an_empty_warning(self):
        proven = [c for c in _checks() if c.verdict == Verdict.SUPPORTED]
        out = pack_card.render(_dossier(proven), CHECKLIST_MD, NEW_MODEL_MD, "")
        assert "Start your own homework here" not in out


class TestItRefusesToPrintABlankPage:
    def test_no_steps_and_no_buyer_named_means_no_card_at_all(self):
        """A card with a title and three blanks on it is worse than no card: it is the first
        file the buyer opens, and it is a bonus file, so its absence blocks nothing."""
        cand = Candidate(candidate_id="c" * 16, title="Thin", one_liner="", market="uk",
                         who_pays="", why_now="")
        thin = Dossier(candidate=cand, decision=Decision.PASS, checks=[],
                       created_at="2026-07-31T00:00:00Z", provider_chain="x")
        assert pack_card.render(thin, "", "", "") == ""

    def test_a_buyer_named_but_no_checklist_still_earns_a_card(self):
        out = pack_card.render(_dossier(), "", NEW_MODEL_MD, "")
        assert "Who pays" in out and "Do these, in this order" not in out


class TestItReadsBothRecordShapes:
    def test_a_replayed_dossier_renders_the_identical_page(self):
        """The backfill holds a `SimpleNamespace` tree rebuilt from `store/dossiers/<id>.json`,
        whose verdicts are plain strings, not enums. Every read here is duck-typed for that
        reason; this test is what stops a `.value` creeping back in."""
        live = _dossier()
        replayed = pack_manifest.dossier_from_dict(live.to_dict())
        assert pack_card.render(replayed, CHECKLIST_MD, NEW_MODEL_MD, "x" * 16) == \
            pack_card.render(live, CHECKLIST_MD, NEW_MODEL_MD, "x" * 16)


class TestItEscapesWhatItPrints:
    def test_a_title_with_an_ampersand_cannot_break_the_page(self):
        cand = Candidate(candidate_id="c" * 16, title="R&D <Claims> Pack", one_liner="",
                         market="uk", who_pays="Founders & their accountants pay for this.",
                         why_now="")
        out = pack_card.render(
            Dossier(candidate=cand, decision=Decision.PASS, checks=[],
                    created_at="2026-07-31T00:00:00Z", provider_chain="x"), "", "", "")
        assert "R&amp;D &lt;Claims&gt; Pack" in out
        assert not re.search(r"<Claims>", out)
