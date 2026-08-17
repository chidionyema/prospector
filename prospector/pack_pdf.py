"""The pack as one typeset PDF — the file a buyer prints, reads on a train, or forwards.

Why this exists (P5, "markdown files is not the one"). A £49.99 pack shipped as eight `.md`
files asks the buyer to own a markdown reader before they can read what they bought.
`pack_html.py` answered that for the screen; this answers it for paper and for every reader
that opens a PDF and nothing else. Same eight sections, same reading order, same bytes of
source text — a second rendering, never a second version.

Two constraints shape every decision in here:

* **Zero model calls.** 127 packs are already sold. A fix that needs a model call cannot be
  replayed into a bought zip, so this renders from the markdown already on disk and from
  nothing else. `tools/backfill_bundle_html.py` can therefore add it to a pack generated
  months ago and get the identical document a fresh publish would write.
* **Byte-deterministic.** The backfill decides whether to rewrite a zip by comparing content
  (`rebuild_zip_with_index` returns None when nothing would change). A PDF that stamps
  `time.now()` into its trailer would rewrite all 62 bundles on every run and make that
  check meaningless, so the creation date is pinned to the pack's own `verified_at` and the
  file id is derived from the content rather than the clock (`_pin_determinism`).

Typography. Noto Serif for reading, Noto Sans for the furniture (cover, headings, tables,
running feet), DejaVu Sans behind both as the glyph fallback — all three OFL, vendored under
`assets/fonts/` because the CSP-equivalent rule for a bundle is stricter than a web page's:
the file has to render on a laptop with no network and no fonts installed. Measured
2026-08-14: Noto Serif has no glyph for `≥` or `→`, both of which appear in engine prose, and
that is exactly what the fallback is for.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import mistune

from .pack_html import PackMeta  # one cover contract, shared with the HTML reader

_log = logging.getLogger(__name__)

__all__ = ["FILENAME", "PackMeta", "render_pack_pdf"]

#: The bundle entry name. A literal, because `bridge.BUNDLE_BONUS_FILES` is compared as a set
#: against what a written zip actually contains (`bridge.undeclared_entries`).
FILENAME = "Complete_Pack.pdf"

_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

# Page geometry, millimetres. A4 with a 165mm text column, which sets the measure at roughly
# 72 characters at the body size below — the same target the HTML reader's max-width serves.
_PAGE = "A4"
_MARGIN_X = 22.0
_MARGIN_TOP = 20.0
_MARGIN_BOTTOM = 18.0

# Type scale, points. Deliberately shallow: this is a document to read, not a brochure.
_SZ_COVER_TITLE = 25
_SZ_COVER_LINE = 12.5
_SZ_LABEL = 7.5
_SZ_SECTION = 16
_SZ_H2 = 12
_SZ_H3 = 10.5
_SZ_BODY = 10.0
_SZ_SMALL = 8.5
_SZ_TABLE = 8.5

_LEAD = 5.0          # body leading, mm
_PARA_GAP = 2.6      # space between paragraphs, mm

_INK = (26, 26, 26)
_MUTED = (91, 91, 91)
_RULE = (214, 214, 214)
_ACCENT = (11, 83, 148)
_QUOTE_BAR = (176, 176, 176)

_MD_AST = mistune.create_markdown(renderer=None, plugins=["table", "strikethrough"])

# A markdown heading that merely repeats the section title the renderer has already set in
# 16pt. Every engine artifact opens with one ("# Blueprint / build spec"), and printing both
# gives every section a stutter at the top of its page.
_PUNCT = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return _PUNCT.sub(" ", text.lower()).strip()


# Emoji carry no glyph in any font a bundle may legally vendor — Noto Color Emoji is a
# bitmap font fpdf2 cannot embed, and the three OFL faces here have no coverage. fpdf2 drops
# an uncoverable character SILENTLY, so "✅ Verified" would ship as " Verified" with the
# meaning gone. Engine prose uses a small, fixed set of them as status marks; each is mapped
# to a typographic equivalent DejaVu does carry, so the mark survives the rendering.
_GLYPH_SUBSTITUTES = {
    "✅": "✓",   # ✅ → ✓
    "❌": "✗",   # ❌ → ✗
    "✔": "✓",
    "✘": "✗",
    "⚠": "⚠",   # ⚠ is in DejaVu; kept explicit so the variation selector below is
    "️": "",         #   what gets stripped, not the sign itself
    "🔴": "●",
    "•️": "•",
}
_SUBSTITUTE_RE = re.compile("|".join(re.escape(k) for k in _GLYPH_SUBSTITUTES if k))

#: What is left after the map above: the DECORATIVE emoji engine prose uses as section
#: markers. An enumerated blocklist cannot cover these — the first backfill over the live
#: shelf turned up 🏗 🔥 📈 🤝 💬 🎥 🎤 in one pass, and the next pack will use seven others.
#: So coverage is asked of the fonts themselves and anything they cannot draw is removed
#: rather than left to fpdf2's silent drop, which leaves the space it was standing in.
_UNCOVERED = "\x00"  # placeholder, so the space cleanup below can see where the hole was
_HOLE_RE = re.compile(_UNCOVERED + r"+ ?")
_TRAILING_WS_RE = re.compile(r"[ \t]+(?=\n|$)")


@lru_cache(maxsize=1)
def _covered_codepoints() -> frozenset:
    """Every codepoint the vendored faces can actually draw, read from their own cmaps.

    Derived, never declared: a hand-written list of "safe" characters is a claim about six
    binary files that nothing checks, and it is wrong the day a face is swapped. fontTools
    is already a hard dependency of fpdf2, so this costs an import that is loaded anyway.
    """
    from fontTools.ttLib import TTFont

    cps: set = set()
    for name in sorted(set(_FONT_FILES.values())):
        path = _FONT_DIR / name
        if not path.is_file():
            continue
        tt = TTFont(str(path), fontNumber=0, lazy=True)
        try:
            for table in tt["cmap"].tables:
                cps.update(table.cmap.keys())
        finally:
            tt.close()
    return frozenset(cps)


def _substitute(text: str) -> str:
    """Map the status marks, then drop what no vendored face can draw.

    The order matters: ✅ is uncoverable too, so a coverage sweep that ran first would delete
    the tick instead of translating it.
    """
    if not text:
        return text
    out = _SUBSTITUTE_RE.sub(lambda m: _GLYPH_SUBSTITUTES[m.group(0)], text)
    covered = _covered_codepoints()
    if all(ord(c) in covered or c in "\n\r\t" for c in out):
        return out  # the common case: ordinary prose, no scan, no rebuild
    # Removing the character ourselves means it never reaches fpdf2, which is the only thing
    # that was reporting it ("Font ... is missing the following glyphs"). Silence here would
    # be strictly worse than the defect: the first live backfill found not only decorative
    # emoji but KOREAN (독서교육) in a pack's prose, and a dropped word is not a dropped
    # ornament. No OFL face small enough to vendor covers CJK, so the drop stands — but it is
    # logged, so the report says which packs lost something and what.
    dropped = sorted({c for c in out if ord(c) not in covered and c not in "\n\r\t"})
    if dropped:
        _log.warning("pack_pdf: %d uncoverable character(s) removed: %s",
                     len(dropped), " ".join(f"{c!r}(U+{ord(c):04X})" for c in dropped))
    out = "".join(c if (ord(c) in covered or c in "\n\r\t") else _UNCOVERED for c in out)
    # A decorative marker is almost always followed by a space ("🔥 Growth"), and removing
    # the character alone leaves that space to open the line. Take the hole and one space
    # with it; a marker mid-sentence still keeps the space in front of it.
    out = _HOLE_RE.sub("", out)
    return _TRAILING_WS_RE.sub("", out)


def _font(name: str) -> str:
    return str(_FONT_DIR / name)


def _pdf_class(fpdf_mod: Any, meta: PackMeta):
    """Build the FPDF subclass carrying this pack's running foot.

    fpdf is imported inside `render_pack_pdf` rather than at module import: `pack_pdf` is
    imported by `bridge` on every publish, and a missing optional dependency must degrade to
    "no PDF in this bundle" (the caller guards it, exactly like index.html) rather than break
    the money rail's bundle writer.
    """
    FPDF = fpdf_mod.FPDF

    class _PackPDF(FPDF):
        cover_pages = 1  # pages carrying no running foot

        def footer(self) -> None:  # noqa: D102 — fpdf2 hook
            if self.page_no() <= self.cover_pages:
                return
            self.set_y(-14)
            self.set_font("sans", "", _SZ_LABEL)
            self.set_text_color(*_MUTED)
            left = meta.title if len(meta.title) <= 64 else meta.title[:61] + "…"
            self.cell(0, 4, left, align="L")
            self.set_x(-_MARGIN_X - 30)
            self.cell(30, 4, str(self.page_no() - self.cover_pages), align="R")

    return _PackPDF


#: Every (family, style) the renderer may ask for. All FOUR styles of both families are
#: vendored, because the combinations are not hypothetical: `_heading` merges "B" into
#: whatever the markup already carried, so an italic inside an H2 asks sans for "BI", and
#: `***text***` asks serif for it directly. Measured 2026-08-14 on the first live backfill:
#: pack 13d41ccee9e96e2d died with "Undefined font: serifBI" and shipped with no PDF at all —
#: a whole missing deliverable caused by one triple-asterisk in one sentence.
_FONT_FILES = {
    ("serif", ""): "NotoSerif-Regular.ttf",
    ("serif", "B"): "NotoSerif-Bold.ttf",
    ("serif", "I"): "NotoSerif-Italic.ttf",
    ("serif", "BI"): "NotoSerif-BoldItalic.ttf",
    ("sans", ""): "NotoSans-Regular.ttf",
    ("sans", "B"): "NotoSans-Bold.ttf",
    ("sans", "I"): "NotoSans-Italic.ttf",
    ("sans", "BI"): "NotoSans-BoldItalic.ttf",
    ("fallback", ""): "DejaVuSans.ttf",
}


def _register_fonts(pdf: Any) -> None:
    for (family, style), filename in _FONT_FILES.items():
        pdf.add_font(family, style, _font(filename))
    # Covers the glyphs Noto Serif does not carry (≥, →, some dingbats in engine prose).
    # Without this fpdf2 drops the character silently and the sentence loses its operator.
    #
    # `exact_match=False` is load-bearing, not a loosening. fpdf2 defaults to matching the
    # fallback's EMPHASIS as well as its glyph coverage, and only the regular weight of
    # DejaVu is vendored — so with the default, `**A → B**` lost its arrow while the same
    # arrow in body text kept it. Measured 2026-08-14 on
    # publish/bundles/ad26e53cae963bc8: "NotoSerifBold is missing '→'" with the default,
    # silent with this. A bold arrow drawn in regular weight is the right trade against a
    # sentence that loses its operator.
    pdf.set_fallback_fonts(["fallback"], exact_match=False)


# ---------------------------------------------------------------------------
# Inline runs
# ---------------------------------------------------------------------------

def _inline_runs(children: Sequence[Dict[str, Any]],
                 style: str = "") -> List[Tuple[str, str, Optional[str]]]:
    """Flatten a mistune inline tree to ``(text, style, link)`` runs.

    Style is fpdf's own vocabulary ("", "B", "I", "BI") so the caller can hand it straight to
    `set_font`. Strikethrough has no font style in a PDF and no honest substitute, so its text
    is kept and its emphasis dropped rather than the text disappearing.
    """
    runs: List[Tuple[str, str, Optional[str]]] = []
    for node in children or []:
        kind = node.get("type")
        if kind == "text":
            runs.append((_substitute(node.get("raw", "")), style, None))
        elif kind == "strong":
            runs.extend(_inline_runs(node.get("children"), _merge(style, "B")))
        elif kind == "emphasis":
            runs.extend(_inline_runs(node.get("children"), _merge(style, "I")))
        elif kind == "codespan":
            runs.append((_substitute(node.get("raw", "")), style, None))
        elif kind == "link":
            url = (node.get("attrs") or {}).get("url") or None
            # An anchor-only link points inside the page it was written for. fpdf2 reads a
            # leading "#" as a NAMED DESTINATION and raises at output time if nothing ever
            # called set_link(name=...) — "Named destination 'main-content' was referenced but
            # never set". That killed Complete_Pack.pdf for pack 83f2e75faa80bb60 on
            # 2026-08-16, which failed the structural audit and left the pack unlisted. The
            # anchor is model-written copy, so we cannot stop it appearing; a standalone PDF
            # has no such destination to point at either way. Keep the words, drop the link —
            # the same trade the font rail below makes, and for the same reason: fpdf raises
            # during the write, so one dead anchor otherwise costs the whole document.
            if url and url.startswith("#"):
                url = None
            for text, st, _ in _inline_runs(node.get("children"), style):
                runs.append((text, st, url))
        elif kind in ("linebreak", "softbreak"):
            runs.append((" " if kind == "softbreak" else "\n", style, None))
        elif kind == "strikethrough":
            runs.extend(_inline_runs(node.get("children"), style))
        elif node.get("children"):
            runs.extend(_inline_runs(node.get("children"), style))
        elif node.get("raw"):
            runs.append((_substitute(node["raw"]), style, None))
    return runs


def _merge(style: str, add: str) -> str:
    return style if add in style else "".join(sorted(set(style + add)))


def _runs_text(runs: Sequence[Tuple[str, str, Optional[str]]]) -> str:
    return "".join(text for text, _, _ in runs)


def _write_runs(pdf: Any, runs: Sequence[Tuple[str, str, Optional[str]]], *,
                family: str = "serif", size: float = _SZ_BODY,
                lead: float = _LEAD) -> None:
    """Flow styled runs across lines, switching font mid-line where the markup does.

    `write` is used rather than `multi_cell` precisely because a paragraph's bold span must
    not force a new line: fpdf's `write` continues at the current x, which is what makes
    "**Cost:** £4,200 a month" read as one sentence instead of three stacked fragments.
    """
    for text, style, link in runs:
        if not text:
            continue
        # The rail behind the font table: an unregistered style raises, and fpdf raises DURING
        # the page write, so the failure costs the whole PDF rather than one word's emphasis.
        # Degrading to the nearest registered style is always the right trade here.
        while style and (family, style) not in _FONT_FILES:
            style = style[:-1]
        pdf.set_font(family, style, size)
        if link:
            pdf.set_text_color(*_ACCENT)
            pdf.write(lead, text, link)
            pdf.set_text_color(*_INK)
        else:
            pdf.write(lead, text)
    pdf.ln(lead)


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------

def _heading(pdf: Any, runs, level: int) -> None:
    size = {2: _SZ_H2, 3: _SZ_H3}.get(level, _SZ_H3)
    pdf.ln(3.2 if level == 2 else 2.4)
    # Keep a heading with at least two lines of its own text rather than orphaning it at the
    # foot of a page — the one page-break rule worth hand-coding in a document like this.
    if pdf.get_y() > pdf.h - _MARGIN_BOTTOM - 22:
        pdf.add_page()
    pdf.set_text_color(*_INK)
    _write_runs(pdf, [(t, _merge(s, "B"), lk) for t, s, lk in runs],
                family="sans", size=size, lead=size * 0.52)
    pdf.ln(0.8)


def _paragraph(pdf: Any, runs) -> None:
    pdf.set_text_color(*_INK)
    _write_runs(pdf, runs)
    pdf.ln(_PARA_GAP)


def _list(pdf: Any, node: Dict[str, Any], depth: int = 0) -> None:
    ordered = (node.get("attrs") or {}).get("ordered", False)
    indent = 5.0 + depth * 5.0
    number = int((node.get("attrs") or {}).get("start") or 1)
    for item in node.get("children") or []:
        if item.get("type") != "list_item":
            continue
        marker = f"{number}." if ordered else "•"
        number += 1
        blocks = item.get("children") or []
        first_text = next((b for b in blocks if b.get("type") in ("block_text", "paragraph")), None)
        start_y = pdf.get_y()
        if first_text is not None:
            pdf.set_left_margin(_MARGIN_X + indent + 4.5)
            pdf.set_xy(_MARGIN_X + indent + 4.5, start_y)
            _write_runs(pdf, _inline_runs(first_text.get("children")))
            end_y = pdf.get_y()
            # The marker is drawn after the text so a wrapped item cannot push it onto the
            # wrong page: if the item broke, start_y belongs to the previous page and the
            # bullet is placed on the line the text actually starts on.
            marker_y = start_y if end_y >= start_y else _MARGIN_TOP
            pdf.set_font("sans", "", _SZ_BODY - 0.5)
            pdf.set_text_color(*_MUTED)
            pdf.set_xy(_MARGIN_X + indent, marker_y)
            pdf.cell(4.5, _LEAD, marker)
            pdf.set_text_color(*_INK)
            pdf.set_xy(_MARGIN_X, end_y)
            pdf.set_left_margin(_MARGIN_X)
        for block in blocks:
            if block is first_text:
                continue
            if block.get("type") == "list":
                _list(pdf, block, depth + 1)
            elif block.get("type") in ("paragraph", "block_text"):
                pdf.set_left_margin(_MARGIN_X + indent + 4.5)
                pdf.set_x(_MARGIN_X + indent + 4.5)
                _write_runs(pdf, _inline_runs(block.get("children")))
                pdf.set_left_margin(_MARGIN_X)
                pdf.set_x(_MARGIN_X)
    if depth == 0:
        pdf.ln(_PARA_GAP)


def _block_quote(pdf: Any, node: Dict[str, Any]) -> None:
    top = pdf.get_y()
    pdf.set_left_margin(_MARGIN_X + 6)
    pdf.set_x(_MARGIN_X + 6)
    for child in node.get("children") or []:
        if child.get("type") in ("paragraph", "block_text"):
            _write_runs(pdf, [(t, _merge(s, "I"), lk)
                              for t, s, lk in _inline_runs(child.get("children"))])
            pdf.ln(1.4)
    bottom = pdf.get_y()
    pdf.set_left_margin(_MARGIN_X)
    pdf.set_x(_MARGIN_X)
    if bottom > top:  # a quote that broke across a page gets its rule on the last page only
        pdf.set_draw_color(*_QUOTE_BAR)
        pdf.set_line_width(0.5)
        pdf.line(_MARGIN_X + 2, top + 1, _MARGIN_X + 2, bottom - 1)
    pdf.ln(_PARA_GAP - 1)


def _code_block(pdf: Any, node: Dict[str, Any]) -> None:
    text = _substitute((node.get("raw") or "").rstrip("\n"))
    if not text:
        return
    pdf.ln(1.0)
    pdf.set_font("fallback", "", _SZ_SMALL)
    pdf.set_text_color(*_INK)
    pdf.set_fill_color(246, 246, 244)
    pdf.multi_cell(0, 4.4, text, fill=True, padding=(2, 3, 2, 3))
    pdf.ln(_PARA_GAP)


def _table(pdf: Any, node: Dict[str, Any]) -> None:
    """Markdown pipe tables — the financial model is mostly these, and a table flattened to
    prose is the single most-cited reason a markdown pack read as unfinished."""
    head: List[str] = []
    rows: List[List[str]] = []
    for part in node.get("children") or []:
        if part.get("type") == "table_head":
            head = [_runs_text(_inline_runs(c.get("children")))
                    for c in part.get("children") or []]
        elif part.get("type") == "table_body":
            for row in part.get("children") or []:
                rows.append([_runs_text(_inline_runs(c.get("children")))
                             for c in row.get("children") or []])
    if not head and not rows:
        return
    pdf.ln(1.4)
    pdf.set_font("sans", "", _SZ_TABLE)
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.2)
    with pdf.table(line_height=4.6, text_align="LEFT", padding=(1.6, 2.0),
                   headings_style=_headings_style(pdf)) as table:
        if head:
            hr = table.row()
            for cell in head:
                hr.cell(cell)
        for row in rows:
            tr = table.row()
            for cell in row:
                tr.cell(cell)
    pdf.set_text_color(*_INK)
    pdf.ln(_PARA_GAP)


def _headings_style(pdf: Any):
    from fpdf.fonts import FontFace

    return FontFace(family="sans", emphasis="BOLD", color=_INK, fill_color=(242, 242, 240))


def _rule(pdf: Any) -> None:
    pdf.ln(1.6)
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.3)
    y = pdf.get_y()
    pdf.line(_MARGIN_X, y, pdf.w - _MARGIN_X, y)
    pdf.ln(_PARA_GAP + 1)


def _render_markdown(pdf: Any, markdown: str, section_title: str) -> None:
    tokens = _MD_AST(markdown or "")
    if isinstance(tokens, tuple):  # mistune returns (tokens, state) in some configurations
        tokens = tokens[0]
    dropped_title = False
    for node in tokens or []:
        kind = node.get("type")
        if kind == "blank_line":
            continue
        if kind == "heading":
            level = (node.get("attrs") or {}).get("level", 2)
            runs = _inline_runs(node.get("children"))
            if not dropped_title and level == 1:
                dropped_title = True
                # The section already carries this line at 16pt; printing the artifact's own
                # H1 underneath it gives every section a stutter. Dropped only for the FIRST
                # H1 and only when it says the same thing.
                if _norm(_runs_text(runs)) in (_norm(section_title), ""):
                    continue
            _heading(pdf, runs, level)
        elif kind in ("paragraph", "block_text"):
            _paragraph(pdf, _inline_runs(node.get("children")))
        elif kind == "list":
            _list(pdf, node)
        elif kind == "block_quote":
            _block_quote(pdf, node)
        elif kind in ("block_code", "code"):
            _code_block(pdf, node)
        elif kind == "table":
            _table(pdf, node)
        elif kind == "thematic_break":
            _rule(pdf)
        elif node.get("children"):
            _paragraph(pdf, _inline_runs(node.get("children")))


# ---------------------------------------------------------------------------
# Cover, contents, closing note
# ---------------------------------------------------------------------------

def _label(pdf: Any, text: str) -> None:
    pdf.set_font("sans", "B", _SZ_LABEL)
    pdf.set_text_color(*_MUTED)
    pdf.set_char_spacing(0.9)
    pdf.cell(0, 4, text.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_char_spacing(0)
    pdf.set_text_color(*_INK)


def _cover(pdf: Any, meta: PackMeta, sections: Sequence[Tuple[str, str]]) -> None:
    pdf.add_page()
    pdf.ln(26)
    _label(pdf, "Business pack")
    pdf.ln(3)
    pdf.set_font("sans", "B", _SZ_COVER_TITLE)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(0, _SZ_COVER_TITLE * 0.46, _substitute(meta.title),
                   new_x="LMARGIN", new_y="NEXT")
    if meta.one_liner:
        pdf.ln(3.5)
        pdf.set_font("serif", "", _SZ_COVER_LINE)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 6.2, _substitute(meta.one_liner), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(7)
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(_MARGIN_X, y, _MARGIN_X + 46, y)
    pdf.ln(7)

    # Provenance, worded as pack_html words it: claims first, sources second. Volume of
    # sources is the one number about the evidence a buyer cannot act on.
    stats: List[Tuple[str, str]] = []
    if meta.verified_at:
        stats.append(("Verified", meta.verified_at))
    if meta.claim_count is not None:
        value = f"{meta.claim_count} claim{'' if meta.claim_count == 1 else 's'}"
        if meta.source_count is not None:
            value += f" against {meta.source_count} source{'' if meta.source_count == 1 else 's'}"
        stats.append(("Checked", value))
    elif meta.source_count is not None:
        stats.append(("Grounded in",
                      f"{meta.source_count} source{'' if meta.source_count == 1 else 's'}"))
    for label, value in stats:
        pdf.set_font("sans", "B", _SZ_LABEL)
        pdf.set_text_color(*_MUTED)
        pdf.set_char_spacing(0.9)
        pdf.cell(30, 5, label.upper())
        pdf.set_char_spacing(0)
        pdf.set_font("serif", "", _SZ_SMALL + 0.5)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5, value, new_x="LMARGIN", new_y="NEXT")

    # Contents on the cover rather than a page of its own: eight lines do not earn a page,
    # and a buyer opening the file sees immediately what they bought.
    pdf.ln(9)
    _label(pdf, "What is inside")
    pdf.ln(1.5)
    for i, (title, _) in enumerate(sections, start=1):
        pdf.set_font("sans", "", _SZ_LABEL + 0.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(7, 5.4, f"{i:02d}")
        pdf.set_font("serif", "", _SZ_BODY)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 5.4, title, new_x="LMARGIN", new_y="NEXT")

    if meta.pack_id:
        pdf.set_y(-24)
        pdf.set_font("sans", "", _SZ_LABEL)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 4, f"Pack ID {meta.pack_id}")
    pdf.set_text_color(*_INK)


def _section_opener(pdf: Any, index: int, title: str) -> None:
    pdf.add_page()
    pdf.set_font("sans", "B", _SZ_LABEL)
    pdf.set_text_color(*_MUTED)
    pdf.set_char_spacing(0.9)
    pdf.cell(0, 4, f"SECTION {index:02d}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_char_spacing(0)
    pdf.ln(1.2)
    pdf.set_font("sans", "B", _SZ_SECTION)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(0, _SZ_SECTION * 0.5, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.6)
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(_MARGIN_X, y, pdf.w - _MARGIN_X, y)
    pdf.ln(5)


def _closing(pdf: Any, meta: PackMeta) -> None:
    pdf.ln(6)
    if pdf.get_y() > pdf.h - _MARGIN_BOTTOM - 30:
        pdf.add_page()
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.3)
    y = pdf.get_y()
    pdf.line(_MARGIN_X, y, pdf.w - _MARGIN_X, y)
    pdf.ln(4)
    pdf.set_font("serif", "I", _SZ_SMALL)
    pdf.set_text_color(*_MUTED)
    # Same promise as the HTML reader's footer, and same reason for its wording: a sourcing
    # claim that overstates itself is the first sentence a sceptical buyer tests.
    pdf.multi_cell(
        0, 4.6,
        "Every claim we could check links to the page it came from. Where the evidence was "
        "thin, this pack says so instead of filling the gap.",
        new_x="LMARGIN", new_y="NEXT")
    if meta.pack_id:
        pdf.ln(1.5)
        pdf.set_font("sans", "", _SZ_LABEL)
        pdf.cell(0, 4, f"Pack ID {meta.pack_id}")
    pdf.set_text_color(*_INK)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

_EPOCH = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)


def _pin_determinism(pdf: Any, meta: PackMeta, sections: Sequence[Tuple[str, str]]) -> None:
    """Make two renders of the same pack byte-identical.

    A PDF carries a creation date and a file id. Left to fpdf2 both come from the clock,
    which would make `rebuild_zip_with_index`'s content comparison always report a change and
    rewrite all 62 live bundles on every backfill run — the check that stops a backfill
    churning bought files would quietly become a no-op.
    """
    stamp = _EPOCH
    if meta.verified_at:
        try:
            stamp = _dt.datetime.fromisoformat(
                meta.verified_at.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            stamp = _EPOCH
    pdf.creation_date = stamp
    digest = hashlib.sha256(
        ("\x00".join([meta.title, meta.one_liner, meta.pack_id, meta.verified_at]
                     + [t for t, _ in sections]
                     + [b or "" for _, b in sections])).encode("utf-8")
    ).hexdigest()[:32]
    pdf.set_producer("Prospector")
    pdf.set_creator("Prospector")
    try:
        pdf._security_handler = None  # noqa: SLF001 — no encryption, so no random id salt
    except Exception:
        pass
    pdf._file_id = f"<{digest.upper()}><{digest.upper()}>"  # noqa: SLF001


def render_pack_pdf(sections: List[Tuple[str, str]], meta: PackMeta) -> bytes:
    """Render the whole pack to one typeset PDF.

    Args:
        sections: ordered ``(display_title, markdown_text)`` pairs in READING order — the
            `BUNDLE_FILES` order, exactly as `pack_html.render_pack_html` takes them. This
            renders what it is given and never re-sorts (the defect that shipped a reader
            opening on the build spec is one caller away from repeating here).
        meta: the same cover fields the HTML reader uses.

    Returns:
        PDF bytes. Deterministic: identical inputs give identical bytes.

    Raises:
        ImportError: if fpdf2 is not installed. Callers treat the PDF as a bonus file and
            guard the call, exactly as they guard index.html.
    """
    import fpdf as fpdf_mod

    pdf = _pdf_class(fpdf_mod, meta)(orientation="P", unit="mm", format=_PAGE)
    pdf.set_margins(_MARGIN_X, _MARGIN_TOP, _MARGIN_X)
    pdf.set_auto_page_break(True, margin=_MARGIN_BOTTOM)
    pdf.set_title(meta.title)
    pdf.set_lang("en")
    _register_fonts(pdf)
    _pin_determinism(pdf, meta, sections)

    _cover(pdf, meta, sections)
    for i, (title, body) in enumerate(sections, start=1):
        _section_opener(pdf, i, title)
        pdf.set_font("serif", "", _SZ_BODY)
        if body and body.strip():
            _render_markdown(pdf, body, title)
        else:
            pdf.set_font("serif", "I", _SZ_BODY)
            pdf.set_text_color(*_MUTED)
            pdf.multi_cell(0, _LEAD, "Not generated for this pack.",
                           new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*_INK)
    _closing(pdf, meta)

    out = pdf.output()
    return bytes(out)
