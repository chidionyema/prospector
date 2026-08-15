"""The typeset edition — `prospector/pack_pdf.py`, the file a buyer prints.

What these pin, and why each one is here rather than being obvious:

* the PDF is BYTE-DETERMINISTIC. `tools/backfill_bundle_html.py` decides whether to rewrite a
  bought bundle by comparing content, so a PDF carrying `datetime.now()` in its trailer would
  rewrite all 62 live bundles on every run and silently retire that check;
* the markdown actually becomes typography — headings, bold, lists, tables — instead of the
  raw `**` and `|` a naive dump would print, which is the whole point of the file;
* nothing is silently DROPPED. fpdf2 discards a character no embedded font covers without
  raising, so "✅ Verified" ships as " Verified" unless something maps it. That failure is
  invisible in a green suite and visible to the buyer, which is exactly the class this file
  exists to catch.
"""
from __future__ import annotations

import re

import pytest

from prospector import pack_pdf
from prospector.pack_html import PackMeta

pypdf = pytest.importorskip("pypdf")


META = PackMeta(
    title="Rota cover alerts for care providers",
    one_liner="A board where care workers hand shifts to a vetted colleague in minutes.",
    verified_at="2026-08-01T09:00:00Z",
    source_count=41,
    pack_id="a1b2c3d4e5f60718",
    claim_count=6,
)

BODY = """# Executive Summary

The buyer is a **registered manager** at a provider running 50-500 care workers.

## What it costs

| Line | Monthly |
|------|--------:|
| Platform | £180 |
| Per swap | £4 |

- First, name the payer.
- Then, price the swap.

> Refusals are the asset: no rota vendor sees them.
"""

SECOND = """# The Financial Model

Break-even lands at 42 swaps a month → £348 of fee income.
"""


def _render(sections=None, meta=META) -> bytes:
    return pack_pdf.render_pack_pdf(sections or [("Executive Summary", BODY),
                                                 ("The Financial Model", SECOND)], meta)


def _text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture(scope="module")
def rendered() -> bytes:
    return _render()


@pytest.fixture(scope="module")
def text(rendered) -> str:
    return _text(rendered)


class TestItIsAPdfAtAll:
    def test_it_starts_with_the_pdf_magic_number(self, rendered):
        assert rendered[:5] == b"%PDF-"

    def test_a_reader_can_open_it_and_finds_more_than_the_cover(self, rendered):
        reader = pypdf.PdfReader(__import__("io").BytesIO(rendered))
        assert len(reader.pages) >= 3  # cover + a page per section

    def test_the_document_title_is_the_pack_title(self, rendered):
        reader = pypdf.PdfReader(__import__("io").BytesIO(rendered))
        assert (reader.metadata or {}).get("/Title") == META.title


class TestByteDeterminism:
    """The property `tools/backfill_bundle_html.py` depends on.

    Its idempotence check is `src.read(FILENAME) == pdf_bytes` (`pdf_ok`). If two renders of
    one pack differ, that comparison is False forever: every backfill run rewrites every
    bought bundle, uploads it again, and the "nothing would change → return None" contract
    that keeps a backfill off 127 sold files becomes decorative.
    """

    def test_two_renders_of_the_same_pack_are_identical(self):
        assert _render() == _render()

    def test_the_creation_date_comes_from_the_pack_not_the_clock(self, rendered):
        # 2026-08-01T09:00:00Z, the dossier's own verified_at, in PDF date syntax.
        assert re.search(rb"/CreationDate\s*\(D:20260801090000", rendered)

    def test_a_pack_with_no_verified_at_still_renders_to_a_fixed_date(self):
        out = _render(meta=PackMeta(title="No stamp", pack_id="f" * 16))
        assert out == _render(meta=PackMeta(title="No stamp", pack_id="f" * 16))
        assert re.search(rb"/CreationDate\s*\(D:20260101", out)

    def test_changing_the_content_changes_the_bytes(self):
        """The other half of determinism: identical output must mean identical input, or the
        backfill would skip a pack whose deliverables actually changed."""
        assert _render() != _render([("Executive Summary", BODY + "\n\nOne more line.\n"),
                                     ("The Financial Model", SECOND)])


class TestTheMarkdownBecameTypography:
    def test_the_cover_carries_title_one_liner_and_pack_id(self, text):
        assert META.title in text
        assert "care workers hand shifts" in text
        assert META.pack_id in text

    def test_the_cover_lists_what_is_inside(self, text):
        assert "What is inside".upper() in text.upper()
        assert "The Financial Model" in text

    def test_provenance_leads_with_claims_not_source_volume(self, text):
        """Same wording rule as the HTML reader's cover: claim count first. Source volume is
        the one number about the evidence a buyer cannot act on."""
        assert "6 claims against 41 sources" in text

    def test_bold_markers_do_not_survive_as_literal_asterisks(self, text):
        assert "registered manager" in text
        assert "**" not in text

    def test_a_pipe_table_is_drawn_rather_than_printed_as_pipes(self, text):
        assert "Platform" in text and "£180" in text
        assert "|------|--------:|" not in text
        assert "| Platform |" not in text

    def test_list_items_keep_their_text(self, text):
        assert "name the payer" in text
        assert "price the swap" in text

    def test_the_sections_are_in_the_order_they_were_given(self, text):
        assert text.index("Executive Summary") < text.index("The Financial Model")

    def test_the_artifacts_own_h1_is_not_printed_twice(self, text):
        """Every engine artifact opens with an H1 repeating its own title, and the section
        opener already sets that line in 16pt. Printing both gives every section a stutter."""
        assert text.count("The Financial Model") == 2  # cover contents + section opener

    def test_a_section_with_no_content_says_so_rather_than_rendering_blank(self):
        text = _text(_render([("The Operations Plan", "")]))
        assert "Not generated for this pack" in text


class TestNothingIsSilentlyDropped:
    """fpdf2 drops an uncoverable character without raising — the defect class that ships a
    green suite and a broken sentence."""

    def test_an_arrow_survives_in_body_text(self, text):
        assert "→" in text

    def test_an_arrow_survives_inside_bold_text(self):
        """REGRESSION, measured 2026-08-14 on publish/bundles/ad26e53cae963bc8: with fpdf2's
        default `exact_match=True` the fallback font had to match the EMPHASIS too, and only
        the regular weight of DejaVu is vendored — so the arrow vanished from bold text while
        surviving in body text ("NotoSerifBold is missing '→'")."""
        assert "→" in _text(_render([("X", "A sentence with **A → B** in bold.\n")]))

    def test_a_status_emoji_becomes_a_glyph_that_exists(self):
        """No font a bundle may legally vendor carries ✅ (Noto Color Emoji is a bitmap font
        fpdf2 cannot embed), so it is substituted rather than dropped: the mark survives."""
        text = _text(_render([("X", "✅ Verified against the source.\n")]))
        assert "Verified against the source" in text
        assert "✓" in text

    def test_the_pound_sign_survives(self, text):
        assert "£180" in text

    def test_substitution_leaves_ordinary_prose_untouched(self):
        assert pack_pdf._substitute("Plain prose, £49.99 — unchanged.") == \
            "Plain prose, £49.99 — unchanged."


class TestTheBundleContract:
    def test_the_filename_is_a_promised_deliverable(self):
        """Renamed and inverted 2026-08-15 (was `test_the_filename_is_declared_as_a_bonus_file`).

        The old reasoning, kept because it was right for its moment: BUNDLE_FILES is the
        drift-tested sellability contract with the storefront's PackContents.tsx, and while the
        PDF renderer was new a missing PDF must never be able to block the listing of a pack
        whose eight markdown deliverables had all arrived. The regression two tests below
        (pack 13d41ccee9e96e2d, "Undefined font: serifBI", shipped with NO PDF) is exactly the
        failure that tolerance was designed to absorb.

        It is not absorbed any more, deliberately. All 59 live packs carry a PDF (measured
        against the objects R2 serves), the markdown is gone from the archive, and the typeset
        edition is now one of only five things a buyer receives. So a PDF that fails to render
        makes the pack SHORT: `audit_bundle` reports it missing and the pack is held UNLISTED
        rather than sold incomplete.
        """
        from prospector.bridge import BUNDLE_BONUS_FILES, BUNDLE_FILES

        assert pack_pdf.FILENAME in BUNDLE_FILES
        assert pack_pdf.FILENAME not in BUNDLE_BONUS_FILES

    def test_the_vendored_fonts_are_present(self):
        """The bundle has to render on a laptop with no network and no fonts installed, so the
        faces travel with the repo. A missing file here is an ImportError-shaped outage that
        would show up only as bundles quietly shipping without the PDF."""
        for (family, style), name in pack_pdf._FONT_FILES.items():
            assert (pack_pdf._FONT_DIR / name).is_file(), f"{family}{style}: {name}"

    def test_bold_italic_is_registered_for_both_families(self):
        """REGRESSION, measured 2026-08-14 on the first live backfill: pack 13d41ccee9e96e2d
        raised "Undefined font: serifBI" and shipped with NO PDF. `_heading` merges "B" into
        whatever the markup carried, so one italic inside one H2 asks for a face that was not
        vendored, and fpdf raises during the page write — losing the whole deliverable."""
        for family in ("serif", "sans"):
            assert (family, "BI") in pack_pdf._FONT_FILES

    def test_triple_emphasis_renders_rather_than_killing_the_document(self):
        text = _text(_render([("X", "A ***bold italic*** phrase.\n\n## An *italic* heading\n")]))
        assert "bold italic" in text
        assert "italic" in text


class TestDecorativeEmojiLeaveNoHole:
    """The second half of "nothing is silently dropped", found by the first live backfill.

    Engine prose uses emoji as section markers (🏗 🔥 📈 🤝 💬 🎥 🎤 turned up in ONE pass over
    the shelf), and no vendored face can draw any of them. fpdf2 removes them without raising
    and leaves the space they stood in, so the heading opens with a gap. Coverage is read from
    the fonts' own cmaps rather than enumerated, because the next pack uses seven others.
    """

    def test_an_uncoverable_marker_takes_its_space_with_it(self):
        assert pack_pdf._substitute("🔥 Growth levers") == "Growth levers"
        assert pack_pdf._substitute("Costs 📈 rose") == "Costs rose"

    def test_every_emoji_the_live_shelf_used_is_removed_cleanly(self):
        for ch in "🏗🔥📈🤝💬🎥🎤🚀🧭📊":
            out = pack_pdf._substitute(f"{ch} Section")
            assert out == "Section", (ch, out)

    def test_the_status_marks_are_translated_not_deleted(self):
        """Order matters: ✅ is uncoverable too, so a coverage sweep running first would
        delete the tick rather than translate it."""
        assert pack_pdf._substitute("✅ done") == "✓ done"
        assert pack_pdf._substitute("❌ not done") == "✗ not done"

    def test_coverage_is_read_from_the_vendored_faces(self):
        covered = pack_pdf._covered_codepoints()
        for ch in "A£—→✓✗•":
            assert ord(ch) in covered, ch
        for ch in "🔥📈":
            assert ord(ch) not in covered, ch

    def test_ordinary_prose_is_returned_untouched_without_a_rebuild(self):
        s = "Plain prose, £49.99 — unchanged, with a → arrow and a ✓ tick."
        assert pack_pdf._substitute(s) == s

    def test_a_marker_in_a_heading_does_not_survive_into_the_pdf(self):
        text = _text(_render([("X", "## 🔥 Growth levers\n\nBody text here.\n")]))
        assert "Growth levers" in text
        assert "🔥" not in text


def test_removing_an_uncoverable_letter_leaves_a_trace(caplog):
    """Not the same case as an emoji. The first live backfill found KOREAN (독서교육) in a
    pack's prose, and no OFL face small enough to vendor covers CJK. The drop stands — but
    doing it ourselves means fpdf2 never sees the character and never prints its own
    "missing the following glyphs" line, so silence here would be worse than the defect."""
    with caplog.at_level("WARNING", logger="prospector.pack_pdf"):
        assert pack_pdf._substitute("독서교육 market") == "market"
    said = [r.getMessage() for r in caplog.records]
    assert any("uncoverable" in m and "U+B3C5" in m for m in said), said
