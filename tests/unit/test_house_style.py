"""The house writing spec, on the pack lane.

Every fixture in this file is either taken verbatim from the corpus measured on 2026-08-15
(2,187 dossiers) or from the live /sample page the founder read. A rule pinned against
invented prose pins the regex, not the defect.

The load-bearing test is `test_a_pack_full_of_violations_still_ships_by_default`: the whole
module is measurement until somebody sets a threshold, and a change that quietly makes it
block would strand the catalogue.
"""
from __future__ import annotations

from prospector.house_style import (
    MIN_QUOTE_WORDS,
    check_house_style,
    extract_quotes,
    house_style_metrics,
)


def _hits(texts, rule):
    return house_style_metrics(texts)["hits"][rule]


class TestR4FourItemLists:
    def test_four_items_are_flagged(self):
        # From the corpus: the fourth item is where the invented vocabulary sits.
        t = {"a": ("The platform handles scheduling, invoicing, compliance reporting, "
                   "and stakeholder alignment.")}
        assert len(_hits(t, "R4")) == 1

    def test_three_items_are_the_spec_ceiling_and_pass(self):
        t = {"a": "The platform handles scheduling, invoicing, and compliance reporting."}
        assert _hits(t, "R4") == []

    def test_a_semicolon_free_two_item_sentence_is_not_a_list(self):
        t = {"a": "Retention is withheld, and subcontractors wait for it."}
        assert _hits(t, "R4") == []


class TestR5FiguresWithoutASource:
    def test_a_percentage_with_no_source_is_flagged(self):
        t = {"a": "Main contractors withhold 5% of each payment until practical completion."}
        assert len(_hits(t, "R5")) == 1

    def test_the_same_figure_with_a_reporting_verb_passes(self):
        t = {"a": ("Build UK reports that main contractors withhold 5% of each payment "
                   "until practical completion.")}
        assert _hits(t, "R5") == []

    def test_a_figure_with_a_link_in_the_sentence_passes(self):
        t = {"a": "Retentions ran to £4.5bn in 2018 ([Build UK](https://builduk.org/x))."}
        assert _hits(t, "R5") == []

    def test_a_financial_model_row_is_arithmetic_not_a_claim(self):
        # Verbatim from the clean pack fixture in test_q2_pack_linter. Wired without the
        # data-line skip, R5 reported four findings against a pack with nothing wrong.
        t = {"financial_model": (
            "- In: £500 - Cost of making and delivering it (12%): £60 - Everything else "
            "it takes to run: £200 - **Left over: £240**")}
        assert _hits(t, "R5") == []

    def test_a_markdown_table_row_is_never_graded(self):
        t = {"a": "| Month 1 | £500 | 12% |"}
        assert _hits(t, "R5") == []

    def test_a_small_bare_integer_is_not_a_figure(self):
        # "the 6 checks" is a heading, not a claim, and firing here made the rule useless.
        t = {"a": "We ran 6 checks against the retrieved passages."}
        assert _hits(t, "R5") == []


class TestR6QuantityWordsWithNoQuantity:
    def test_numerous_alone_is_a_number_the_writer_did_not_have(self):
        t = {"a": "Numerous subcontractors report cash flow problems on large sites."}
        hits = _hits(t, "R6")
        assert len(hits) == 1 and hits[0]["token"] == "numerous"

    def test_the_same_word_beside_a_figure_is_a_style_choice_not_a_defect(self):
        t = {"a": "Numerous subcontractors, 214 of them, reported cash flow problems."}
        assert _hits(t, "R6") == []


class TestR8TheDefectOffTheLiveSamplePage:
    def test_a_sentence_opening_on_that_is_flagged(self):
        t = {"a": "That unpaid subcontractors cause serious cash flow problems."}
        assert len(_hits(t, "R8")) == 1

    def test_that_said_is_ordinary_english_and_is_left_alone(self):
        t = {"a": "That said, the passages do not settle who bears the cost."}
        assert _hits(t, "R8") == []

    def test_that_is_is_ordinary_english_and_is_left_alone(self):
        t = {"a": "That is the whole of the retention mechanism in one sentence."}
        assert _hits(t, "R8") == []


class TestR10PredictionsAssertedAsFact:
    def test_the_corpus_example_is_caught(self):
        # Verbatim from the corpus, 2026-08-15.
        t = {"a": "Late copiers cannot catch up because the data compounds with every "
                  "contract."}
        assert len(_hits(t, "R10")) == 1

    def test_a_competitor_claim_is_caught(self):
        t = {"a": "The point competitors cannot match is the installer referral loop."}
        assert len(_hits(t, "R10")) == 1

    def test_a_sourced_prediction_is_what_the_spec_asks_for_and_passes(self):
        t = {"a": ("Gartner reports that competitors cannot match the installer referral "
                   "loop before 2027.")}
        assert _hits(t, "R10") == []


class TestQuoteExtraction:
    def test_a_blockquote_is_a_quote(self):
        got = extract_quotes("> Main contractors withhold a percentage of each payment.")
        assert got == ["Main contractors withhold a percentage of each payment."]

    def test_an_apostrophe_never_opens_a_quote(self):
        # "subcontractors' money" would open a single quote that never closes.
        assert extract_quotes("It withholds subcontractors' money until milestones.") == []

    def test_a_short_double_quoted_word_is_emphasis_not_a_citation(self):
        assert extract_quotes('The pack is "free" to read.') == []


class TestQ1Q2Q3:
    def test_a_quote_under_eight_words_is_flagged(self):
        t = {"a": "> cash flow problems on site"}
        hits = _hits(t, "quotes")
        assert len(hits) == 1 and f"at least {MIN_QUOTE_WORDS}" in hits[0]["reason"]

    def test_a_quote_opening_mid_clause_is_flagged(self):
        t = {"a": "> and that unpaid retentions were left behind by the 2018 collapse"}
        hits = _hits(t, "quotes")
        assert len(hits) == 1 and hits[0]["reason"].startswith("Q1")

    def test_the_glued_title_that_shipped_on_the_sample_page_is_a_splice(self):
        t = {"a": ("> Payapps Reviews, Pros & Cons.Payapps is a cloud application for "
                   "construction payments")}
        hits = _hits(t, "quotes")
        # Furniture is checked first because it is the more actionable reason.
        assert len(hits) == 1 and hits[0]["reason"].startswith("Q3")

    def test_an_ellipsis_inside_a_quote_is_two_passages_joined(self):
        t = {"a": "> Main contractors withhold retention ... until practical completion"}
        hits = _hits(t, "quotes")
        assert len(hits) == 1 and hits[0]["reason"].startswith("Q2")

    def test_page_furniture_is_flagged_however_long_it_is(self):
        t = {"a": "> Skip to main content Sign in Subscribe to our newsletter for updates"}
        hits = _hits(t, "quotes")
        assert len(hits) == 1 and hits[0]["reason"].startswith("Q3")

    def test_a_clean_quote_passes_every_rule(self):
        t = {"a": ("> Main contractors routinely withhold five per cent of each payment "
                   "until practical completion.")}
        assert _hits(t, "quotes") == []


class TestTheActuatorsAreOffUntilSomebodySetsThem:
    VIOLATING = {
        "Section": (
            "Numerous subcontractors report problems. "
            "That unpaid retentions are withheld is not settled. "
            "Late copiers cannot catch up because the data compounds. "
            "The platform handles scheduling, invoicing, reporting, and alignment. "
            "Main contractors withhold 5% of each payment.\n"
            "> too short a quote"
        )
    }

    def test_every_rule_fires(self):
        m = house_style_metrics(self.VIOLATING)
        assert m["four_item_lists"] >= 1
        assert m["unsourced_figures"] >= 1
        assert m["vague_quantities"] >= 1
        assert m["orphan_openers"] >= 1
        assert m["flat_predictions"] >= 1
        assert m["bad_quotes"] >= 1

    def test_a_pack_full_of_violations_still_ships_by_default(self):
        # THE contract of this module. `lint_pack` fails a pack iff a problem carries
        # severity "error"; with no threshold set, nothing here may.
        problems = check_house_style(self.VIOLATING)
        assert problems, "the defects must still be REPORTED"
        assert [p for p in problems if p["severity"] == "error"] == []

    def test_the_two_decidable_actuators_block_when_switched_on(self):
        problems = check_house_style(
            self.VIOLATING, block_predictions=True, block_quotes=True)
        errors = {p["check"] for p in problems if p["severity"] == "error"}
        assert errors == {"house_style", "house_quote"}

    def test_a_rate_threshold_needs_forty_sentences_before_it_rules(self):
        # A four-sentence section is not a sample. Firing on one would make every short
        # pack section fail on a rate computed from a denominator of three.
        problems = check_house_style(self.VIOLATING, max_four_item_list_rate=0.01)
        assert [p for p in problems if p["check"] == "house_rate"] == []

    def test_over_a_real_sample_the_rate_threshold_rules(self):
        text = " ".join(
            ["The platform handles scheduling, invoicing, reporting, and alignment."] * 50)
        problems = check_house_style({"s": text}, max_four_item_list_rate=0.10)
        rate = [p for p in problems if p["check"] == "house_rate"]
        assert len(rate) == 1 and "R4" in rate[0]["detail"]

    def test_metrics_are_reused_when_passed_so_a_pack_is_scanned_once(self):
        m = house_style_metrics(self.VIOLATING)
        assert check_house_style(self.VIOLATING, metrics=m) == check_house_style(
            self.VIOLATING)


class TestWiredIntoTheGateThatDecidesWhatShips:
    """`register_lint` shipped fully tested with zero callers. These pin the wiring itself.

    `lint_pack`'s report is what `bridge.py:1094` ANDs into `is_listed`, so "the check runs"
    and "the check runs ON THE PUBLISH PATH" are two different claims and only the second
    one matters.
    """

    SECTIONS = {
        "What we found": (
            "Late copiers cannot catch up by leveraging the same contract data.\n"
            "> Pros & Cons.Payapps is a cloud application"
        ),
    }

    @staticmethod
    def _lint(**kw):
        from prospector.pack_linter import lint_pack
        return lint_pack(artifacts={}, listing_copy="", listing_texts={}, market="UK",
                         pack_sections=TestWiredIntoTheGateThatDecidesWhatShips.SECTIONS,
                         **kw)

    def test_the_baseline_is_recorded_on_every_pack(self):
        spec = self._lint()["house_spec"]
        assert spec["R10_flat_predictions"] == 1
        assert spec["Q_bad_quotes"] == 1
        assert spec["sentences"] >= 1

    def test_with_no_thresholds_set_the_pack_still_lists(self):
        report = self._lint()
        assert report["ok"] is True
        assert any(p["check"] in {"house_style", "house_quote"}
                   for p in report["problems"]), "the defects must still be reported"

    def test_the_prediction_actuator_unlists_the_pack_when_switched_on(self):
        report = self._lint(house_block_predictions=True)
        assert report["ok"] is False

    def test_the_quote_actuator_unlists_the_pack_when_switched_on(self):
        report = self._lint(house_block_quotes=True)
        assert report["ok"] is False

    def test_register_is_graded_on_the_assembled_read_not_only_on_artifacts(self):
        # "leveraging" is in register_lint's banned list AND it sits in a SECTION, not in an
        # artifact. Before 2026-08-15 `check_register` had no caller at all, so nothing in
        # this repo had ever graded register on anything, let alone on the assembled read.
        #
        # It is "leveraging" rather than the founder's own R9 example "moat" on purpose:
        # `register_lint.py:65-67` deliberately keeps `foster`, `leverage`, `bespoke` and
        # `ecosystem` OUT of the banned list, because foster care and financial leverage are
        # real subjects a pack may be about on a storefront that sells every sector. The
        # spec's R9 list and this one disagree, that disagreement is recorded in the ledger
        # in docs/HOUSE_WRITING_SPEC.md, and it is the founder's to settle — not a test's.
        assert self._lint()["house_spec"]["R9_register_per_1k"] > 0


class TestEmptyAndMalformedInput:
    def test_no_text_is_not_a_defect(self):
        m = house_style_metrics({})
        assert m["sentences"] == 0 and m["over_28_rate"] == 0.0
        assert check_house_style({}) == []

    def test_a_non_string_section_is_skipped_not_crashed_on(self):
        m = house_style_metrics({"a": None, "b": 7, "c": "A clean sentence."})
        assert m["sentences"] == 1
