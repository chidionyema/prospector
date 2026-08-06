"""The rationale cap must never cut a word in half, and must admit when it cut at all.

Regression cover for the defect measured on 2026-08-06: three call sites capped model prose with
a bare `[:600]` slice, putting 726 of 7,265 stored rationales on disk ending mid-word.
"""

import re

from prospector.trimming import RATIONALE_MAX, clip_to_sentence


def test_short_text_is_returned_untouched():
    text = "The incumbent already owns this channel."
    assert clip_to_sentence(text, 600) == text


def test_empty_and_blank_are_safe():
    assert clip_to_sentence("") == ""
    assert clip_to_sentence("   ", 600) == ""


def test_text_exactly_at_the_limit_is_not_marked_as_cut():
    """The off-by-one that would put an ellipsis on a complete rationale."""
    text = "a" * RATIONALE_MAX
    assert clip_to_sentence(text, RATIONALE_MAX) == text
    assert not clip_to_sentence(text, RATIONALE_MAX).endswith("…")


def test_prefers_the_last_whole_sentence_inside_the_budget():
    body = "First claim here. " * 40  # ~720 chars, sentence ends throughout
    out = clip_to_sentence(body, 600)
    assert len(out) <= 600
    assert out.endswith(".")
    assert "…" not in out


def test_a_citation_bracket_is_not_orphaned():
    """`... (Ofgem, 2024).` must cut after the period, keeping the attribution whole."""
    sentence = "The cap fell in April (Ofgem, 2024). "
    out = clip_to_sentence(sentence * 30, 600)
    assert out.endswith("(Ofgem, 2024).")
    assert out.count("(") == out.count(")")


def test_one_long_sentence_falls_back_to_a_whole_word_and_is_marked():
    """No sentence boundary in the budget at all -- the hardest case, and the one `[:600]` botched."""
    text = "word " * 300  # 1500 chars, zero terminal punctuation
    out = clip_to_sentence(text, 600)
    assert out.endswith("…")
    assert len(out) <= 601
    # The body before the ellipsis must be whole words only.
    assert out[:-1].strip().split()[-1] == "word"


def test_an_early_full_stop_does_not_throw_away_the_budget():
    """"No. <600 more chars>" must not be clipped to "No." -- the keep-ratio guard."""
    text = "No. " + ("the incumbent holds every distribution channel and " * 20)
    out = clip_to_sentence(text, 600)
    assert out != "No."
    assert len(out) > 300


def test_never_emits_a_mid_word_cut_across_the_real_corpus_shapes():
    """The property that the bare slice violated 726 times."""
    fragments = [
        "Regulation 4 of the 2019 Order requires registration before any fee is charged, ",
        "and the operator would need a licence. ",
        "Comparable services (Checkatrade, MyBuilder) already occupy this niche; ",
        "no evidence of unmet demand was retrieved. ",
    ]
    for repeat in range(1, 12):
        text = "".join(fragments * repeat)
        out = clip_to_sentence(text, 600)
        assert len(out) <= 601
        if out.endswith("…"):
            # A marked cut still ends on a word boundary, never inside one.
            assert re.search(r"[\w\)\]\.]…$", out)
        else:
            assert out.rstrip().endswith((".", "!", "?", ")", '"'))
        # Whatever we returned is a genuine prefix of the source text, modulo the marker.
        assert text.startswith(out.rstrip("…").rstrip())
