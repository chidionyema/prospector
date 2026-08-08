"""The publish pass: the one gate every engine-authored string crosses before a buyer reads it.

Five defect classes were measured on the live kill log (400 published entries, 2026-08-07) and
every one of them reached either a public web page or a pack `.md` opened offline from a zip:

    1. bare passage ids   34 entries
    2. empty citations     6 entries
    3. truncation         54 entries
    4. confidence floats  14 entries
    5. register            2 entries

Each class gets a test here, and so does the thing that matters more than any of them: the
NON-firing cases. This repo has been burned twice by unanchored matching — a bare HTTP-code
substring benched a live provider, and an unanchored `/ape/` matched "shape" — so the
word-boundary claims made in `prospector/plain_text.py` are pinned below, not just asserted.

Pure string tests: nothing here touches `store/`, the catalogue, or the real kill-log.json.
"""
from __future__ import annotations

import pytest

from prospector.plain_text import (
    CONFIDENCE_SCALE_NOTE,
    clean_reason,
    publish_pass,
    publish_pass_document,
)

# Two real ids from the live corpus, and a third for list forms.
ID1 = "9fa810377aee4d8f"
ID2 = "10481947a354f7f9"
ID3 = "659308d43632c84b"


# ───────────────────────────── 1. bare passage ids ───────────────────────────

class TestPassageIds:
    def test_noun_phrase_is_repaired_not_gutted(self):
        out = publish_pass(f"Passages {ID1} and {ID2} directly show UK carers are squeezed.")
        assert ID1 not in out and ID2 not in out
        assert out == "The passages directly show UK carers are squeezed."

    def test_oxford_comma_list_keeps_its_spacing(self):
        """The separator has to leave WITH the ids: `The passagesand show` was a real bug."""
        out = publish_pass(f"Passages {ID1}, {ID2}, and {ID3} show NAVA is established.")
        assert out == "The passages show NAVA is established."

    def test_singular_noun_mid_sentence_keeps_its_case(self):
        out = publish_pass(f"The evidence in passage {ID1} shows a free incumbent.")
        assert out == "The evidence in passage shows a free incumbent."

    def test_bracketed_reference_group_goes_whole(self):
        out = publish_pass(f"Client communication is already covered [{ID1}, {ID2}].")
        assert out == "Client communication is already covered."

    def test_bracket_survives_when_it_names_something_real(self):
        out = publish_pass(f"A free tool (FairPay, source {ID1}) already aggregates shifts.")
        assert out == "A free tool (FairPay) already aggregates shifts."

    def test_labelled_citation_span_is_dropped(self):
        out = publish_pass(f"The market is unproven (citation: {ID1}). It may still exist.")
        assert out == "The market is unproven. It may still exist."

    def test_id_as_clause_subject_becomes_a_noun(self):
        """Deleting the subject would leave a verb with nothing in front of it."""
        out = publish_pass(f"Councils run brokerage; {ID1} confirms local FIS operations.")
        assert out == "Councils run brokerage; the passage confirms local FIS operations."

    def test_preposition_leaves_with_the_id(self):
        out = publish_pass(f"The guidance at {ID1} is freely public.")
        assert out == "The guidance is freely public."

    def test_never_leaves_the_sentence_holding_a_gap(self):
        """The failure mode this class exists to prevent: `Passages  and  directly show`."""
        out = publish_pass(f"Passages {ID1} and {ID2} directly show it.")
        assert "  " not in out
        assert " and directly" not in out


# ─────────────────────────── 2. empty citation markers ───────────────────────

class TestEmptyCitationMarkers:
    @pytest.mark.parametrize("marker", ["(,)", "(,,)", "(,,,,)", "()", "[,,]"])
    def test_marker_and_its_orphan_space_are_removed(self, marker):
        out = publish_pass(f"Budget insoles are on eBay from £2.99 {marker}, and so are others.")
        assert out == "Budget insoles are on eBay from £2.99, and so are others."

    def test_marker_before_a_full_stop(self):
        out = publish_pass("Prosecutions are routine (,,,,). Nothing here is novel.")
        assert out == "Prosecutions are routine. Nothing here is novel."


# ──────────────────────────────── 3. truncation ──────────────────────────────

class TestTruncation:
    def test_trailing_ellipsis_trims_to_the_last_whole_sentence(self):
        out = publish_pass(
            "The joined series is not proprietary. It also names planting dates and……",
            sentences=True,
        )
        assert out == "The joined series is not proprietary."

    def test_mid_word_end_is_trimmed_in_sentence_mode(self):
        out = publish_pass(
            "Councils already do this free. So they do not offset the sol",
            sentences=True,
        )
        assert out == "Councils already do this free."

    def test_never_ends_on_an_ellipsis(self):
        out = publish_pass("A whole first sentence. A second one truncat...", sentences=True)
        assert not out.endswith("…") and not out.endswith("...")
        assert out == "A whole first sentence."

    def test_ellipsis_wearing_a_closing_quote_is_still_truncation(self):
        out = publish_pass(
            "Rigs are sold seasonally. The advert reads 'if you haven't already scheduled...'",
            sentences=True,
        )
        assert out == "Rigs are sold seasonally."

    def test_no_complete_sentence_survives_returns_empty(self):
        """A signal, not a value: the caller omits the field rather than render a fragment."""
        assert publish_pass("planting dates and the weather series……", sentences=True) == ""

    def test_headline_ending_on_a_noun_is_left_alone(self):
        """`sentences=False` is why the whole catalogue is not emptied by this rule."""
        line = "A monthly noise test that keeps a small venue's licence safe"
        assert publish_pass(line) == line

    def test_truncated_headline_with_no_sentence_is_omitted(self):
        assert publish_pass("A monthly noise test that keeps a small ven…") == ""

    def test_decimal_point_is_not_a_sentence_boundary(self):
        out = publish_pass("Margins run at 2.5% and the rest is unclear", sentences=True)
        assert out == ""


# ───────────────────────── 4. raw confidence floats ──────────────────────────

class TestConfidenceFigures:
    @pytest.mark.parametrize("raw,expected", [
        ("The three gates are all UNVERIFIABLE at confidence 0.0, so nothing is proven.",
         "The three gates are all UNVERIFIABLE, so nothing is proven."),
        ("payer_solvency is unverifiable at confidence 0.0, there is zero evidence.",
         "payer_solvency is unverifiable, there is zero evidence."),
        ("The check returned unverifiable at 0.0 confidence, not one passage shows a channel.",
         "The check returned unverifiable, not one passage shows a channel."),
        ("There is no route (distribution conf 0.0). Legality is ungrounded.",
         "There is no route (distribution). Legality is ungrounded."),
        ("Every gate returned unverifiable (pain_reality 0.43, legality 0.0). Nothing cleared.",
         "Every gate returned unverifiable (pain_reality, legality). Nothing cleared."),
    ])
    def test_float_is_omitted_and_the_clause_still_reads(self, raw, expected):
        assert publish_pass(raw, sentences=True) == expected

    @pytest.mark.parametrize("innocent", [
        "IPSE runs the Freelancer Confidence Index with Upwork.",
        "The claim path is treated in confidence, with no bureaucratic maze.",
        "Confidence is tempered because the rival is pre-launch.",
        "The tool confirms 3 of the 6 checks.",
    ])
    def test_confidence_without_a_figure_is_untouched(self, innocent):
        """Every pattern demands the word AND an adjacent number, or it does not fire."""
        assert publish_pass(innocent, sentences=True) == innocent

    def test_qa_report_may_keep_the_figure_but_must_explain_the_scale(self):
        doc = "# QA Report\n\n**unverifiable.** Confidence 0.40. No passage settled it.\n"
        out = publish_pass_document(doc, keep_confidence_figures=True)
        assert "Confidence 0.40" in out
        assert CONFIDENCE_SCALE_NOTE in out
        assert out.splitlines()[0] == "# QA Report"

    def test_scale_note_is_added_once(self):
        doc = "# QA Report\n\n**unverifiable.** Confidence 0.40.\n"
        once = publish_pass_document(doc, keep_confidence_figures=True)
        twice = publish_pass_document(once, keep_confidence_figures=True)
        assert twice.count(CONFIDENCE_SCALE_NOTE) == 1
        assert twice == once

    def test_scale_note_is_absent_when_there_is_no_figure(self):
        doc = "# QA Report\n\nEvery check was grounded.\n"
        assert CONFIDENCE_SCALE_NOTE not in publish_pass_document(
            doc, keep_confidence_figures=True)

    def test_marketing_surface_omits_by_default(self):
        doc = "# Listing\n\nThe check was unverifiable at confidence 0.0, so we killed it.\n"
        out = publish_pass_document(doc)
        assert "0.0" not in out and CONFIDENCE_SCALE_NOTE not in out


# ───────────────────────────── 5. register denylist ──────────────────────────

class TestRegisterDenylist:
    def test_the_measured_phrase_is_replaced(self):
        out = publish_pass("This shows the target buyer profile is a broke body, and no more.")
        assert "broke body" not in out
        assert out == (
            "This shows the target buyer profile is a buyer group under severe "
            "financial strain, and no more."
        )

    def test_scare_quotes_are_absorbed(self):
        out = publish_pass("which is precisely the 'broke body' condition here.")
        assert "'" not in out
        assert out == (
            "which is precisely the buyer group under severe financial strain condition here."
        )

    def test_plural_form(self):
        assert "broke bodies" not in publish_pass("These are broke bodies with no budget.")


# ─────────────── the correctness constraint: word boundaries only ────────────

class TestWordBoundaries:
    """The single most important property. Anchored patterns, never bare substrings."""

    @pytest.mark.parametrize("sentence", [
        "The shape of the market is unchanged.",
        "Councils reshape their brokerage every year.",
        "Their responsibilities are already funded by the council.",
        "A landscape of free alternatives already exists.",
    ])
    def test_innocent_words_are_never_touched(self, sentence):
        assert publish_pass(sentence, sentences=True) == sentence

    def test_a_sixteen_character_english_word_survives(self):
        word = "responsibilities"
        assert len(word) == 16
        assert publish_pass(f"The {word} sit with the council.") == (
            f"The {word} sit with the council."
        )

    def test_a_longer_hex_run_is_not_eaten_sixteen_at_a_time(self):
        """A 20-char hex token is not an id, and must not lose a 16-char bite of itself."""
        token = "0123456789abcdef0123"
        assert token in publish_pass(f"The build hash {token} is recorded.")

    def test_uppercase_hex_is_not_an_id(self):
        """The engine mints lowercase ids; an uppercase token is somebody's data, not ours."""
        token = "9FA810377AEE4D8F"
        assert token in publish_pass(f"The reference {token} appears in the contract.")

    def test_all_letter_hex_word_survives(self):
        """The digit requirement is the fence that keeps a-f words out of the id pattern."""
        assert "deadbeefdeadbeef" in publish_pass("The token deadbeefdeadbeef is a joke.")

    def test_denylist_does_not_fire_inside_a_longer_word(self):
        for sentence in ("The brokeback ridge is a landmark.", "They broke bodywork rules."):
            assert publish_pass(sentence) == sentence

    def test_single_comma_after_a_noun_is_ordinary_english(self):
        """Only a DOUBLED separator is upstream damage; one comma is prose."""
        sentence = "The sources, and the evidence, show the same thing."
        assert publish_pass(sentence, sentences=True) == sentence


# ───────────────────────────────── idempotence ───────────────────────────────

class TestIdempotence:
    RAW = [
        f"Passages {ID1}, {ID2}, and {ID3} show it at confidence 0.0 (,,) already……",
        f"A free tool (FairPay, source {ID1}) serves a broke body. It is already free.",
        "Every gate returned unverifiable (pain_reality 0.43, legality 0.0). Nothing cleared.",
        "A complete sentence that needs no repair at all.",
        "",
    ]

    @pytest.mark.parametrize("raw", RAW)
    @pytest.mark.parametrize("sentences", [True, False])
    def test_running_twice_equals_running_once(self, raw, sentences):
        once = publish_pass(raw, sentences=sentences)
        assert publish_pass(once, sentences=sentences) == once

    @pytest.mark.parametrize("raw", RAW)
    def test_document_form_is_idempotent(self, raw):
        once = publish_pass_document(f"# Title\n\n{raw}\n\n- a bullet {ID1}\n")
        assert publish_pass_document(once) == once


# ──────────────────────── the document (pack .md) form ───────────────────────

class TestDocumentForm:
    def test_markdown_structure_survives(self):
        doc = (
            "# Blueprint\n\n"
            "## Step one\n\n"
            f"Passages {ID1} and {ID2} show the pain is real.\n\n"
            "- first item\n"
            "  - nested item\n"
        )
        out = publish_pass_document(doc)
        assert out.startswith("# Blueprint")
        assert "## Step one" in out
        assert "- first item" in out
        assert "  - nested item" in out
        assert ID1 not in out
        assert "The passages show the pain is real." in out

    def test_fenced_code_is_untouched(self):
        doc = f"# Spec\n\n```\nhash = {ID1}\n```\n\nProse citing {ID1} goes clean.\n"
        out = publish_pass_document(doc)
        assert f"hash = {ID1}" in out          # inside the fence, left alone
        assert "Prose citing goes clean." in out

    def test_a_document_is_not_trimmed_to_its_last_full_stop(self):
        """The whole-string rule would cut a ten-page build spec back to one paragraph."""
        doc = "# Ops plan\n\nA sentence.\n\n## A heading with no full stop\n\nMore prose.\n"
        out = publish_pass_document(doc)
        assert "## A heading with no full stop" in out
        assert "More prose." in out


# ─────────────────────── the shared kill-log entry point ─────────────────────

class TestCleanReason:
    def test_engine_prefix_is_stripped(self):
        out = clean_reason("Gate 'incumbency' fired — The passages show things.")
        assert out == "The passages show things."

    def test_it_failed_on_prefix_is_stripped(self):
        out = clean_reason(
            "It failed on: Do incumbents already own this? (`incumbency`) — "
            "Free rivals exist."
        )
        assert out == "Free rivals exist."

    def test_dashes_ids_and_truncation_in_one_pass(self):
        out = clean_reason(
            f"Passages {ID1} and {ID2} show free rivals — at confidence 0.0. "
            "The rest was cut mid-sen"
        )
        assert "—" not in out
        assert ID1 not in out
        assert out == "The passages show free rivals."

    def test_fragment_only_reason_returns_empty_so_the_entry_is_dropped(self):
        assert clean_reason("so they do not offset the sol") == ""


class TestParenthesisedConfidenceFloat:
    """The escape the first pass missed.

    Every original confidence rule demanded the digits sit ADJACENT to the word, so a single
    `(` between them slipped past all five. `kill-log.json` row 392 published
    "..., with a low confidence (0.43)." on 2026-08-07 with the pass already live and the
    suite green: the defect class was closed, one spelling of it was not. Measured, not
    recalled -- the scan that found it reads all 400 published entries.
    """

    def test_parenthesised_float_with_qualifier_is_removed_whole(self):
        out = publish_pass(
            "However, the 'pain_reality' check indicates that this premise is unverifiable, "
            "with a low confidence (0.43). The provided source describes a retiree."
        )
        assert "0.43" not in out
        # The qualifier goes with it: leaving "with a low ." would be a new defect, not a fix.
        assert "with a low" not in out
        assert out == (
            "However, the 'pain_reality' check indicates that this premise is unverifiable. "
            "The provided source describes a retiree."
        )

    def test_bare_parenthesised_float_keeps_the_word_drops_the_number(self):
        out = publish_pass("Scored confidence (0.7) by the adversarial pass.")
        assert out == "Scored confidence by the adversarial pass."

    @pytest.mark.parametrize(
        "safe",
        [
            # A number in parentheses near no confidence word at all.
            "Revenue grew (0.43) percentage points.",
            # The word as part of a proper noun, followed by a parenthesised YEAR.
            "The Freelancer Confidence Index (2024) rose.",
            # The word with no figure anywhere.
            "Confidence is tempered because the source is thin.",
            # "in confidence" is register, not a score, and 3 is a real count.
            "Spoken to in confidence by 3 of the 5 operators.",
        ],
    )
    def test_does_not_fire_without_an_adjacent_confidence_figure(self, safe: str):
        assert publish_pass(safe) == safe

    def test_qa_report_path_still_keeps_the_parenthesised_figure(self):
        kept = publish_pass(
            "Scored confidence (0.7) by the adversarial pass.",
            keep_confidence_figures=True,
        )
        assert "0.7" in kept
