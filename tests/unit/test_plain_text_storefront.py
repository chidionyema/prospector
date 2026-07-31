"""The storefront renders catalog metadata WITHOUT a markdown parser.

`store_platform/src/Store.Web/src/pages/pack/[id].tsx:469` prints `{line}` straight into JSX,
and `ProofPoint` is a plain column. Before this suite, `pack_floors.claim_safe_marketing`
handed `proof_point` the raw bullet `- **buyer intent:** ...`, so a buyer read the asterisks.
These tests pin the boundary: nothing that reaches the catalog carries markdown markup.
"""
from __future__ import annotations

import pytest

from prospector.bridge import _sample_excerpts
from prospector.models import Candidate, CheckResult, Verdict
from prospector.pack_floors import claim_safe_marketing
from prospector.plain_text import has_markup, plain_lines, to_plain_text


def _candidate(**kw):
    base = dict(
        candidate_id="a" * 16,
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
    )
    base.update(kw)
    return Candidate(**base)


def _check(name="buyer_intent", rationale="Growers search for closure guidance (SAGB, 2025)."):
    return CheckResult(
        check_name=name, verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale=rationale, citations=[], sources=[], queries=[],
    )


class TestToPlainText:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("**buyer intent:** growers search", "buyer intent: growers search"),
            ("- **bold** item", "bold item"),
            ("## Heading", "Heading"),
            ("> quoted line", "quoted line"),
            ("*italic*", "italic"),
            ("~~struck~~", "struck"),
            ("`code`", "code"),
            ("***all three***", "all three"),
            ("**bold _and_ italic**", "bold and italic"),
            ("1. ordered item", "ordered item"),
            ("[EA report](https://gov.uk/ea)", "EA report"),
            ("![alt text](img.png)", "alt text"),
        ],
    )
    def test_markup_is_stripped(self, raw, expected):
        assert to_plain_text(raw, collapse=True) == expected

    def test_snake_case_survives(self):
        """`_` is markdown italic, but `buyer_intent`/`who_pays` are real words in this
        product's prose. Stripping them would corrupt copy, not clean it."""
        s = "check buyer_intent against who_pays and time_to_first_revenue"
        assert to_plain_text(s, collapse=True) == s

    def test_words_are_preserved_verbatim(self):
        """The sanitizer may only remove markup. If it could drop or reword content it would
        be capable of altering a moat-verified claim."""
        raw = "**1,234** spills logged in 2024 [source: gov.uk]"
        out = to_plain_text(raw, collapse=True)
        for token in ("1,234", "spills", "2024", "gov.uk"):
            assert token in out

    def test_keep_link_urls_preserves_the_evidence(self):
        out = to_plain_text("see [the EA data](https://gov.uk/ea)", collapse=True,
                            keep_link_urls=True)
        assert out == "see the EA data (https://gov.uk/ea)"

    def test_empty_and_none(self):
        assert to_plain_text(None) == ""
        assert to_plain_text("") == ""
        assert plain_lines(None) == []

    def test_plain_lines_drops_blanks(self):
        assert plain_lines(["**a**", "", "  ", "## b"]) == ["a", "b"]

    def test_has_markup_detects_and_clears(self):
        assert has_markup("**buyer intent:** x") is True
        assert has_markup("buyer intent: x") is False


class TestProofPointIsPlain:
    def test_proof_point_has_no_markdown(self):
        """REGRESSION: proof_point was `bullets[0][2:]`, which only trimmed the `- ` list
        marker and left `**buyer intent:**` intact all the way to the storefront."""
        listing = claim_safe_marketing(_candidate(), [_check()])[0]
        pp = listing["proof_point"]
        assert "**" not in pp
        assert not has_markup(pp)
        assert pp.startswith("buyer intent:")
        # the rationale itself must survive intact
        assert "Growers search for closure guidance" in pp

    def test_falls_back_to_one_liner_without_checks(self):
        listing = claim_safe_marketing(_candidate(), [])[0]
        assert listing["proof_point"] == "Scheduling aid for UK oyster farms."

    def test_markdown_in_the_rationale_itself_is_stripped(self):
        listing = claim_safe_marketing(
            _candidate(), [_check(rationale="the **EA** logged 1,234 spills")]
        )[0]
        assert "**" not in listing["proof_point"]
        assert "1,234" in listing["proof_point"]

    def test_pack_markdown_file_keeps_its_formatting(self):
        """The .md deliverable is markdown and must NOT be flattened — only the plain-text
        catalog fields are sanitized."""
        listing = claim_safe_marketing(_candidate(), [_check()])[0]
        assert "**buyer intent:**" in listing["copy"]


class TestSampleExtractIsPlain:
    BUILD_SPEC = (
        "## Scope\n\n"
        "The Environment Agency logged **1,234** storm-overflow spills in 2024 "
        "[source: gov.uk/ea-2024], which is the trigger this pack is built around.\n"
    )

    def test_excerpt_lines_carry_no_markup(self):
        lines = _sample_excerpts(self.BUILD_SPEC, "**buyer intent:** growers are searching now")
        assert lines, "expected at least one excerpt"
        for line in lines:
            assert "**" not in line, line
            assert not has_markup(line), line

    def test_excerpt_keeps_the_numbers_and_citation(self):
        line = _sample_excerpts(self.BUILD_SPEC, "")[0]
        assert "1,234" in line
        assert "gov.uk/ea-2024" in line

    def test_markdown_link_citation_keeps_its_url(self):
        """A citation written as a markdown link must not lose its target — the URL IS the
        evidence, and a sourced excerpt without it proves nothing."""
        spec = ("Sampling failures rose in 2024 according to "
                "[the EA register](https://gov.uk/ea-register), which drives this pack.\n")
        line = _sample_excerpts(spec, "")[0]
        assert "https://gov.uk/ea-register" in line
        assert "[" not in line and "]" not in line

    def test_proof_point_backstop_is_sanitized(self):
        lines = _sample_excerpts("", "**buyer intent:** growers are searching now")
        assert lines == ["buyer intent: growers are searching now"]
