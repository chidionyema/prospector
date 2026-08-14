"""The register linter must catch the prose the founder rejected and pass the prose he kept.

Both halves are load-bearing. A checker that fires on everything is not a gate, it is a
reason to switch the gate off, so the negative fixtures below are taken from copy that
survived review on 2026-08-13 ("What's genuinely good — don't let a rewrite lose it") and
must stay clean.
"""
import pytest

from prospector.register_lint import (
    BANNED,
    CONSTRUCTIONS,
    check_register,
    cross_document_repeats,
    register_metrics,
    sentences,
)

# Written in the register the founder rejected on 2026-08-14. Every sentence here is
# grammatical, which is why the grammar checker never saw it.
BAD = """
It's not just a book. It's a removed evening.

Ultimately, this business plays a crucial role in the landscape of children's
publishing, leveraging print-on-demand to deliver a seamless experience, ensuring
parents receive a cutting-edge product that empowers them to navigate the complexities
of preparing a child for a new situation.

Whether you're a first-time founder or a seasoned operator, the beauty of this model is
that it delivers actionable, impactful results from day one.
"""

# The copy the founder kept. Plain, short, one idea per sentence.
GOOD = """
Make fifteen books by hand and post them to fifteen real families.

Not a prototype. Fifteen finished books, ordered one at a time from the printer. About
forty minutes each. At five a week that is fine.

Stop if you cannot sell fifteen at full price to people who are not friends.
"""


def test_the_rejected_prose_is_caught():
    m = register_metrics({"01_Blueprint.md": BAD})
    assert m["banned_count"] >= 8, m["banned_hits"]
    assert m["construction_count"] >= 3, m["construction_hits"]
    assert m["register_per_1k"] > 0


def test_the_kept_prose_is_clean():
    m = register_metrics({"01_Blueprint.md": GOOD})
    assert m["banned_count"] == 0, m["banned_hits"]
    assert m["construction_count"] == 0, m["construction_hits"]
    assert m["repeat_count"] == 0


def test_named_constructions_each_fire_on_their_own_shape():
    fixtures = {
        "not_just": "This is not just a book, it is a business.",
        "trailing_participle": "The printer posts it, ensuring the parent does nothing.",
        "adverb_opener": "Ultimately, the margin decides it.",
        "negation_reveal": "It's not the words. It's the object.",
        "not_only_but_also": "It not only prints the book but also posts it.",
        "whether_youre": "Whether you're new to this or not, start here.",
        "rhetorical_answer": "Does it work? Absolutely, on the evidence below.",
        "the_beauty_of": "The beauty of this is that nobody has to check it.",
    }
    assert set(fixtures) == {name for name, _rx, _note in CONSTRUCTIONS}, (
        "every construction needs a fixture, and every fixture a construction")
    for name, rx, _note in CONSTRUCTIONS:
        assert rx.search(fixtures[name]), f"{name} did not match its own fixture"
        others = [t for k, t in fixtures.items() if k != name]
        # A construction that fires on a shape it does not name is a false positive
        # generator, and false positives are what get a gate turned off.
        stray = [t for t in others if rx.search(t)]
        assert not stray, f"{name} also fired on {stray}"


def test_an_individual_hit_never_blocks_but_a_repeat_can():
    problems = check_register({"a.md": BAD}, block=True)
    phrase_hits = [p for p in problems if p["check"] == "register"]
    assert phrase_hits, "expected the phrases to be reported"
    assert all(p["severity"] == "warning" for p in phrase_hits), (
        "one banned word must never be able to unlist a pack")


def test_the_same_sentence_in_two_documents_is_found():
    line = ("Every order goes through the pre-print check by eye, and a faulty "
            "personalised book is a total loss rather than a partial one.")
    texts = {"01_Blueprint.md": f"Some opening text here.\n\n{line}",
             "03_Operations.md": f"{line}\n\nSome closing text here."}
    repeats = cross_document_repeats(texts)
    assert len(repeats) == 1
    _key, first, second, _sentence = repeats[0]
    assert (first, second) == ("01_Blueprint.md", "03_Operations.md")

    blocked = check_register(texts, block=True)
    assert any(p["check"] == "register_repeat" and p["severity"] == "error" for p in blocked)
    advisory = check_register(texts, block=False)
    assert all(p["severity"] == "warning" for p in advisory)


def test_a_repeat_within_one_document_is_not_a_cross_document_repeat():
    line = ("Every order goes through the pre-print check by eye, and a faulty "
            "personalised book is a total loss rather than a partial one.")
    assert cross_document_repeats({"01_Blueprint.md": f"{line}\n\n{line}"}) == []


def test_a_short_shared_line_is_not_a_repeat():
    texts = {"a.md": "This is covered above.", "b.md": "This is covered above."}
    assert cross_document_repeats(texts) == []


@pytest.mark.parametrize("rate_kwarg,value", [
    ("max_per_1k", 1.0),
    ("long_sentence_max_rate", 0.05),
    ("clause_load_max_rate", 0.05),
])
def test_every_rate_errors_only_once_its_own_threshold_is_set(rate_kwarg, value):
    texts = {"01_Blueprint.md": BAD * 6}          # past MIN_WORDS_FOR_RATES
    off = check_register(texts)
    assert not [p for p in off if p["check"] == "register_rate"], (
        "with every threshold at 0.0 the check must measure and never block")
    on = check_register(texts, **{rate_kwarg: value})
    assert [p for p in on if p["check"] == "register_rate" and p["severity"] == "error"]


def test_short_documents_are_never_rate_blocked():
    problems = check_register({"a.md": BAD}, max_per_1k=0.1,
                              long_sentence_max_rate=0.01, clause_load_max_rate=0.01)
    assert not [p for p in problems if p["check"] == "register_rate"]


def test_quoted_and_code_passages_are_never_graded():
    # A cited passage may contain any phrase on the list; correcting it would falsify the
    # citation on a source-or-die storefront.
    text = ("The council's own guidance says:\n\n"
            "> This is a game-changing, seamless, cutting-edge service.\n\n"
            "Here is a code sample:\n\n"
            "```\nleveraging = delve(plethora)\n```\n\n"
            "And an inline `myriad` identifier.\n")
    m = register_metrics({"01_Blueprint.md": text})
    assert m["banned_count"] == 0, m["banned_hits"]


def test_tables_and_urls_are_not_prose():
    text = ("| Metric | Value |\n| --- | --- |\n| Seamless | yes |\n\n"
            "See https://example.com/cutting-edge-delve for the source.\n")
    m = register_metrics({"04_Financial_Model.md": text})
    assert m["banned_count"] == 0, m["banned_hits"]


def test_sentence_splitter_survives_money_and_abbreviations():
    text = ("A book costs £11.50 to print. That leaves £22.18, e.g. after the card fee. "
            "The margin is 63.4%.")
    assert len(sentences(text)) == 3


def test_metrics_are_json_shaped():
    import json
    json.dumps(register_metrics({"a.md": BAD, "b.md": GOOD}))


def test_the_lexicon_has_a_fix_for_every_entry():
    missing = [p for p, fix in BANNED.items() if not fix]
    assert not missing, f"a banned phrase with no replacement is an insult, not a check: {missing}"
