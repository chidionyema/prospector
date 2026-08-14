"""pack_html.py — the pure renderer behind the bundle's self-contained index.html.

Covers: headings/tables render, a TOC anchor exists per section, the document never
references an external http(s) asset (self-contained is the whole point — a buyer opens this
from disk, offline), and the dark-mode block is present.
"""
from __future__ import annotations

import re

from prospector.pack_html import PackMeta, render_pack_html

_TABLE_MD = (
    "# Scorecard\n\n"
    "| What we rated | Score |\n"
    "|---|---:|\n"
    "| pain_acuity | 4/5 |\n"
    "| distribution | 3/5 |\n"
)

_QUOTE_MD = "> A cited passage, quoted verbatim.\n\nSome *emphasis* and a [link](https://example.com/source).\n"


def _meta(**overrides) -> PackMeta:
    base = dict(
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        verified_at="2026-07-31T00:00:00Z",
        source_count=12,
        pack_id="b" * 16,
    )
    base.update(overrides)
    return PackMeta(**base)


class TestHeadingsAndStructure:
    def test_renders_markdown_headings_as_html(self):
        html = render_pack_html([("Executive Summary", "# Title\n\nBody text.\n")], _meta())
        assert "<h1>Title</h1>" in html
        assert "Body text." in html

    def test_section_titles_become_h2_headers(self):
        html = render_pack_html(
            [("The Blueprint (Build Spec)", "# Anything\n")], _meta()
        )
        assert "The Blueprint (Build Spec)" in html

    def test_cover_shows_title_and_one_liner(self):
        html = render_pack_html([("A", "x\n")], _meta())
        assert "Shellfish Classification Aid" in html
        assert "Scheduling aid for UK oyster farms." in html

    def test_missing_optional_meta_does_not_crash_or_print_zero(self):
        """An absent source count must not render '0 sources' — that reads as a checked
        claim, not an absent one."""
        html = render_pack_html([("A", "x\n")], PackMeta(title="Only a title"))
        assert "0 source" not in html.lower()


class TestTables:
    def test_pipe_table_renders_as_an_html_table(self):
        html = render_pack_html([("QA Report", _TABLE_MD)], _meta())
        assert "<table>" in html
        assert "<th>" in html
        assert "pain_acuity" in html
        assert "4/5" in html


class TestBlockquotesAndLinks:
    def test_blockquote_renders(self):
        html = render_pack_html([("A", _QUOTE_MD)], _meta())
        assert "<blockquote>" in html
        assert "cited passage" in html

    def test_cited_link_is_preserved_as_a_hyperlink(self):
        """A citation URL in the deliverable's own prose is legitimate content — the
        self-contained requirement is about ASSETS (css/js/img/font), not buyer-facing links."""
        html = render_pack_html([("A", _QUOTE_MD)], _meta())
        assert 'href="https://example.com/source"' in html


class TestTableOfContents:
    def test_toc_contains_an_anchor_per_section(self):
        sections = [
            ("Executive Summary", "# a\n"),
            ("The Blueprint (Build Spec)", "# b\n"),
            ("The QA Report, with the receipts", "# c\n"),
        ]
        html = render_pack_html(sections, _meta())
        # Every section gets an id, and the TOC links to it with a matching #fragment.
        section_ids = re.findall(r'<section id="([^"]+)"', html)
        assert len(section_ids) == len(sections)
        for sid in section_ids:
            assert f'href="#{sid}"' in html

    def test_section_order_matches_input_order(self):
        sections = [("First", "# 1\n"), ("Second", "# 2\n"), ("Third", "# 3\n")]
        html = render_pack_html(sections, _meta())
        assert html.index("First") < html.index("Second") < html.index("Third")

    def test_duplicate_titles_get_distinct_anchors(self):
        sections = [("Same Title", "# a\n"), ("Same Title", "# b\n")]
        html = render_pack_html(sections, _meta())
        section_ids = re.findall(r'<section id="([^"]+)"', html)
        assert len(set(section_ids)) == len(section_ids)


class TestSelfContained:
    """No external network request may ever be issued opening this file offline."""

    def test_no_external_stylesheet_or_script_tag(self):
        html = render_pack_html([("A", "# a\n")], _meta())
        assert "<link" not in html.lower()
        assert "<script" not in html.lower()

    def test_no_remote_asset_url_in_markup_scaffolding(self):
        html = render_pack_html([("A", "# a\n")], _meta())
        assert "@import" not in html
        assert "src=\"http" not in html.lower()
        assert "url(http" not in html.lower()

    def test_document_is_a_single_self_contained_file(self):
        html = render_pack_html([("A", "# a\n")], _meta())
        assert html.strip().startswith("<!doctype html>")
        assert "<style>" in html  # CSS is inlined, not linked


class TestDarkMode:
    def test_prefers_color_scheme_dark_block_present(self):
        html = render_pack_html([("A", "# a\n")], _meta())
        assert "@media (prefers-color-scheme: dark)" in html


class TestPrintStylesheet:
    def test_print_media_block_present_with_page_breaks(self):
        html = render_pack_html([("A", "# a\n")], _meta())
        assert "@media print" in html
        assert "page-break-before" in html or "break-before" in html


class TestFooter:
    def test_footer_states_the_sourcing_claim_and_pack_id(self):
        html = render_pack_html([("A", "# a\n")], _meta(pack_id="deadbeef" * 2))
        assert "Every claim we could check links to the page it came from." in html
        assert "deadbeef" * 2 in html

    def test_the_footer_does_not_promise_a_source_for_every_claim(self):
        """A pack ships `unverifiable` checks — claims we could NOT source. The old footer
        said every factual claim cites a retrievable source, which those checks falsify, and
        an overstated sourcing promise is the first thing a sceptical buyer tests."""
        html = render_pack_html([("A", "# a\n")], _meta())
        assert "Every factual claim in this pack cites a retrievable source" not in html


class TestCoverStat:
    def test_the_cover_leads_with_claims_not_source_volume(self):
        html = render_pack_html([("A", "# a\n")], _meta(claim_count=6))
        assert "6 claims against 12 sources" in html
        assert "Grounded in" not in html

    def test_one_claim_and_one_source_are_singular(self):
        html = render_pack_html([("A", "# a\n")], _meta(claim_count=1, source_count=1))
        assert "1 claim against 1 source" in html

    def test_a_pack_with_no_claim_count_keeps_the_old_source_line(self):
        """Bundles rendered before claim counts existed still carry a source count; a
        backfill of one must not lose the stat entirely."""
        html = render_pack_html([("A", "# a\n")], _meta())
        assert "12 sources" in html

    def test_a_claim_count_with_no_source_count_still_renders(self):
        html = render_pack_html([("A", "# a\n")], _meta(claim_count=4, source_count=None))
        assert "4 claims" in html
        assert "against" not in html.split("cover-stats")[1][:200]


class TestEscaping:
    def test_html_special_characters_in_title_are_escaped(self):
        html = render_pack_html([("A", "# a\n")], _meta(title="<script>alert(1)</script>"))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_raw_html_inside_markdown_body_is_not_executed(self):
        html = render_pack_html([("A", "<script>alert(1)</script>\n\nReal text.\n")], _meta())
        assert "<script>alert(1)</script>" not in html
