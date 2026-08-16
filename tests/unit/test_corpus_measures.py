"""The corpus tools measure. These tests pin WHAT they measure, on inputs with known answers.

A keyness table is only worth acting on if the statistic behind it is right, and a
log-likelihood computed with the sign inverted would confidently tell us to delete the words
we under-use. Every number here is hand-checkable.

The rule these tools exist to replace: `prompts/style/voice.md` sets a 25-word sentence
ceiling and a two-comma clause limit, and `register_lint.py:353-355` gates on them. Nobody
measured those. See docs/PROSE_CORPUS_PROGRAM.md.
"""
from __future__ import annotations

import math
import random

import pytest

from tools.corpus.build_ours import document
from tools.corpus.load import load_corpus
from tools.corpus.text import (
    MATTR_WINDOW,
    classify_item,
    log_likelihood,
    log_ratio,
    mattr,
    ngrams,
    paragraphs,
    profile,
    sentences,
    tokens,
)

# ---------------------------------------------------------------- the statistic

def test_the_sign_says_which_corpus_over_uses_it():
    """Positive means over-used in A. Get this backwards and every rule inverts."""
    assert log_likelihood(100, 10, 10_000, 10_000) > 0
    assert log_likelihood(10, 100, 10_000, 10_000) < 0


def test_identical_rates_score_zero():
    assert log_likelihood(50, 100, 10_000, 20_000) == pytest.approx(0.0, abs=1e-9)


def test_g2_matches_the_textbook_value():
    """a=100 b=10 in two 10k corpora. G2 = 2*(100*ln(100/55) + 10*ln(10/55))."""
    expected = 2 * (100 * math.log(100 / 55) + 10 * math.log(10 / 55))
    assert log_likelihood(100, 10, 10_000, 10_000) == pytest.approx(expected)


def test_log_ratio_reads_as_times_more_often():
    assert log_ratio(200, 100, 10_000, 10_000) == pytest.approx(1.0)   # twice as often
    assert log_ratio(400, 100, 10_000, 10_000) == pytest.approx(2.0)   # four times


def test_an_item_absent_from_the_human_corpus_still_scores():
    """Zero frequency must not divide by zero or vanish — those are the interesting rows."""
    assert log_ratio(50, 0, 10_000, 10_000) > 0
    assert log_likelihood(50, 0, 10_000, 10_000) > 0


# ---------------------------------------------------------------- tokenising

def test_numbers_are_not_tokens():
    """A keyness table full of 2024 and 1299 measures subject matter, not voice."""
    assert tokens("In 2024 we paid £1,299 monthly") == ["in", "we", "paid", "monthly"]


def test_apostrophes_and_hyphens_stay_inside_a_word():
    assert tokens("the buyer's well-founded doubt") == ["the", "buyer's", "well-founded", "doubt"]


def test_an_abbreviation_does_not_end_a_sentence():
    got = sentences("The firm, e.g. a broker, agreed. The complaint succeeds.")
    assert len(got) == 2
    assert got[0].startswith("The firm, e.g. a broker")


def test_paragraph_breaks_survive_and_single_newlines_do_not():
    assert len(paragraphs("one\ntwo\n\nthree")) == 2


def test_ngrams_are_contiguous_and_counted_right():
    assert ngrams(["a", "b", "c"], 2) == [("a", "b"), ("b", "c")]


# ---------------------------------------------------------------- the profile

def test_sentence_length_mean_is_the_hand_count():
    p = profile(["One two three four five. Six seven eight nine ten eleven twelve."])
    assert p.sentence_count == 2
    assert p.sent_len_mean == pytest.approx(6.0)   # (5 + 7) / 2


def test_the_long_sentence_rate_counts_sentences_over_twenty_five_words():
    short = "Short one here."
    long_ = "Word " + " ".join(["word"] * 29) + "."
    assert profile([f"{short} {long_}"]).long_sentence_rate == pytest.approx(0.5)


def test_a_sentence_must_start_with_a_capital_to_be_split_off():
    """A property of the splitter, pinned so nobody 'fixes' it into a defect. Requiring a
    capital is what stops '£1,299. 00' and 'v. 2' being read as two sentences. The cost is
    that a lowercase opener joins the sentence before it, which prose in this genre does
    not do."""
    assert len(sentences("First one here. second one lowercase.")) == 1
    assert len(sentences("First one here. Second one capital.")) == 2


def test_hedges_are_a_rate_not_a_count():
    """Per 1,000 words, so a long corpus and a short one compare directly."""
    p = profile(["It may be that this could possibly work. " + " ".join(["word"] * 992) + "."])
    assert p.words == 1000
    assert p.hedges_per_1k == pytest.approx(3.0)   # may, could, possibly


def test_a_hyphen_inside_a_word_is_not_a_dash():
    """Counted together, our compound-heavy titles read as a dash habit and we would go and
    fix punctuation that is not there. Measured 2026-08-16: merged, our 'dash' rate came out
    7x the human corpus; split, dashes sat INSIDE the human range and hyphens were 12x."""
    p = profile(["A well-founded, re-sited front-door claim."])
    assert p.punct_per_1k["hyphen"] > 0
    assert p.punct_per_1k["dash"] == 0


def test_an_em_dash_and_a_spaced_hyphen_both_count_as_dashes():
    p = profile(["The firm agreed — eventually. The buyer - who waited - did not."])
    assert p.punct_per_1k["dash"] > 0
    assert p.punct_per_1k["hyphen"] == 0


def test_opener_diversity_falls_when_every_sentence_opens_the_same_way():
    same = profile(["The firm did this. The firm did that. The firm did the other."])
    varied = profile(["The firm did this. Buyers did that. Regulators did the other."])
    assert same.opener_diversity < varied.opener_diversity


def test_a_measure_of_a_corpus_is_not_the_average_of_per_document_measures():
    """A one-line document must not weigh as much as a long decision."""
    long_doc = " ".join(["word"] * 100) + "."
    together = profile(["Tiny.", long_doc])
    assert together.words == 101


# ---------------------------------------------------------------- boilerplate

def test_a_line_in_most_documents_is_dropped_from_all_of_them(tmp_path):
    """Every FOS decision closes with the same statutory paragraph. Left in, it dominates
    the 4-gram table and we 'discover' that our generator over-uses a legal requirement."""
    common = "Under the rules of the Financial Ombudsman Service I am required to ask."
    for i in range(10):
        (tmp_path / f"d{i}.txt").write_text(f"Unique sentence {i} here.\n{common}\n")
    docs, dropped = load_corpus(tmp_path)
    assert common in dropped
    assert all(common not in d for d in docs)
    assert any("Unique sentence 3" in d for d in docs)


def test_a_rare_line_survives(tmp_path):
    for i in range(10):
        (tmp_path / f"d{i}.txt").write_text(f"Body text number {i} runs on.\n")
    (tmp_path / "d0.txt").write_text("Body text number 0 runs on.\nA line only one doc has.\n")
    docs, dropped = load_corpus(tmp_path)
    assert dropped == []
    assert any("only one doc has" in d for d in docs)


def test_boilerplate_stripping_is_skipped_on_a_corpus_too_small_to_measure_it(tmp_path):
    """With three documents, 'appears in more than 30%' means 'appears twice'. That is not
    evidence of a template, so the filter must not run at all."""
    for i in range(3):
        (tmp_path / f"d{i}.txt").write_text("A shared sentence appears here.\n")
    docs, dropped = load_corpus(tmp_path)
    assert dropped == []
    assert len(docs) == 3


# ---------------------------------------------------------------- what counts as ours

def test_our_corpus_takes_our_prose_and_leaves_the_webs():
    """`sources[].text` is a journalist's writing. Measuring it would tell us how the web
    writes, which is not the question we are asking."""
    d = {"candidate": {"title": "A title", "one_liner": "A one liner",
                       "hypothesis": "A hypothesis", "who_pays": "Buyers",
                       "why_now": "A trigger"},
         "checks": [{"rationale": "The passages support the claim.",
                     "citations": ["S1"], "queries": ["q"],
                     "sources": [{"text": "WEB PASSAGE TEXT", "url": "https://x"}]}],
         "adversarial": {"kill_case": "The case against.",
                         "objections": [{"objection": "One vendor holds the channel.",
                                         "what_would_have_to_be_true": "A second route."}]}}
    text = document(d)
    for kept in ("A title", "A one liner", "A hypothesis", "Buyers", "A trigger",
                 "The passages support the claim.", "The case against.",
                 "One vendor holds the channel.", "A second route."):
        assert kept in text
    for excluded in ("WEB PASSAGE TEXT", "https://x", "S1"):
        assert excluded not in text


def test_our_documents_keep_paragraph_breaks():
    """profile() measures paragraph length. Joined with single newlines it would report one
    paragraph per document and that measure would be a constant, not a measurement."""
    d = {"candidate": {"title": "T", "one_liner": "O"},
         "checks": [{"rationale": "R."}], "adversarial": {}}
    assert len(paragraphs(document(d))) == 3


# --------------------------------------------- form is a target, subject matter is not

def test_the_sectors_we_write_about_can_never_become_a_voice_rule():
    """THE CARVE-OUT. We are not adjudicating complaints, so the human corpus's subject
    matter is not a target. These four are the top content rows in the keyness table; a rule
    cut from them would ban what this engine exists to write about."""
    for topic in ("uk", "nhs", "ai", "data", "tool", "solo", "buyer", "pricing"):
        assert classify_item(topic) == "content"


def test_our_own_machinery_is_actionable_not_subject_matter():
    """`passages` is our largest keyness row at 1,872x the human rate. It is not a topic —
    it is us describing our retrieval to a reader who wants to know what is true."""
    for item in ("passages", "the passages", "none of the passages", "no passage",
                 "passages show", "cited in"):
        assert classify_item(item) == "meta"


def test_function_word_patterns_are_form():
    """Closed-class items are how we build sentences, which is the pattern to adopt."""
    for item in ("none of", "but none", "is a", "and a", "every", "who"):
        assert classify_item(item) == "form"


def test_one_content_word_makes_the_whole_item_content():
    """A phrase is only form if EVERY token is closed-class. Otherwise the topic rides in
    on the back of the function words around it."""
    assert classify_item("none of the nhs trusts") == "content"
    assert classify_item("") == "content"


# ------------------------------------------------- vocabulary, with length controlled

def _same_writing_at_two_lengths() -> tuple[list[str], list[str]]:
    """One writer, one vocabulary, two document lengths. Any measure that separates these
    two is measuring length."""
    rng = random.Random(7)
    vocab = [f"w{i}" for i in range(300)]
    toks = [rng.choice(vocab) for _ in range(4000)]
    return toks[:600], toks


def test_type_token_ratio_falls_with_length_on_identical_writing():
    """The reason `type_token_ratio` was retired from the scored set. Our documents average
    654 words and the human decisions 1,923, so this drop alone put us 3.5 sd 'above' the
    human corpus on vocabulary."""
    short, long_ = _same_writing_at_two_lengths()
    ttr = lambda t: len(set(t)) / len(t)  # noqa: E731
    assert ttr(short) - ttr(long_) > 0.15


def test_mattr_holds_when_the_same_writing_gets_longer():
    """Same two texts, same writer, fixed 100-word window: the measure does not move."""
    short, long_ = _same_writing_at_two_lengths()
    assert mattr(short) == pytest.approx(mattr(long_), abs=0.02)


def test_mattr_is_nan_below_one_window_and_never_zero():
    """A short document is UNMEASURED, not word-poor. Zero would be averaged into the target
    as 'no vocabulary variety' and drag it down with documents nobody measured."""
    assert math.isnan(mattr(["a"] * (MATTR_WINDOW - 1)))
    row = profile(["one two three."]).as_row()
    assert "mattr" not in row


def test_mattr_separates_a_repetitive_writer_from_a_varied_one():
    """Direction check: the measure must be able to move at all."""
    repetitive = ["the", "claim", "is", "supported"] * 200
    varied = [f"w{i}" for i in range(800)]
    assert mattr(repetitive) < 0.1
    assert mattr(varied) > 0.9
