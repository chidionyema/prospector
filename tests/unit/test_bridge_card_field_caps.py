"""A capped catalogue field must not be cut in the middle of a word.

On 2026-08-08 pack `8ce5270ade208070` published UNLISTED with, among its errors:

    truncation | subhead | hard-sliced mid-word at [:280]: …'to a true hourly wag'

`catalog_meta["subhead"]` was a bare `subhead[:280]`. `pack_linter.check_truncation` is
built to detect exactly that shape, so the hard slice was not a cosmetic defect: it was a
guaranteed unlist. These tests pin the fix at BOTH ends — the string the buyer sees, and
the linter's verdict on it — because a truncation fix that only satisfies the assertion
about length would leave the linter still failing the pack.
"""
from prospector.bridge import _cap_words
from prospector.pack_linter import check_truncation


def _mid_word_at(cap: int) -> str:
    """A source string whose character at index `cap` is mid-word, like the real defect."""
    src = ("The gap between an advertised day rate and a true hourly wage is invisible to "
           "most contractors, which is why the calculator below converts every quoted figure "
           "back into the only unit that can be compared across jobs, sites and seasons, "
           "namely what one worked hour actually pays after unpaid travel and waiting time.")
    assert len(src) > cap and src[cap].isalnum() and src[cap - 1].isalnum(), (
        "fixture must reproduce the mid-word cut, else this test proves nothing")
    return src


def test_cap_words_retreats_to_a_word_boundary():
    src = _mid_word_at(280)
    out = _cap_words(src, 280)
    assert len(out) <= 280
    assert src.startswith(out.rstrip(" ,;:")) or src.startswith(out)
    # The point of the fix: the last word is whole.
    assert not out.endswith(" ")
    tail = out.rsplit(" ", 1)[-1]
    assert src.split()[len(out.split()) - 1] == tail, "final word was cut in half"


def test_linter_no_longer_flags_the_capped_subhead():
    """The assertion that actually decides whether the pack lists."""
    src = _mid_word_at(280)
    hard = src[:280]
    # Control: the OLD behaviour must still be caught, else this test is vacuous.
    assert check_truncation({"subhead": (hard, src)}, {"subhead": 280}), (
        "linter no longer flags a hard mid-word slice; this test would prove nothing")
    fixed = _cap_words(src, 280)
    assert check_truncation({"subhead": (fixed, src)}, {"subhead": 280}) == []


def test_headline_cap_is_the_same_rule():
    src = _mid_word_at(140)
    fixed = _cap_words(src, 140)
    assert len(fixed) <= 140
    assert check_truncation({"headline": (fixed, src)}, {"headline": 140}) == []


def test_short_text_is_returned_untouched():
    assert _cap_words("A short subhead.", 280) == "A short subhead."
    assert _cap_words("  padded  ", 280) == "padded"
    assert _cap_words("", 280) == ""


def test_a_single_token_longer_than_the_cap_keeps_the_hard_slice():
    """Documented, deliberate: there is no word boundary to retreat to. It stays visible to
    the linter rather than being disguised as a clean cut."""
    src = "x" * 400
    out = _cap_words(src, 280)
    assert out == "x" * 280
    assert check_truncation({"subhead": (out, src)}, {"subhead": 280}) != []
