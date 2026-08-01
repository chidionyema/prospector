"""
prospector/pack_html.py — renders a pack's markdown deliverables into ONE self-contained
`index.html` reading experience for the zip bundle.

WHY: today a buyer who downloads the £49 zip gets eight raw `.md` files. Anyone without a
markdown viewer sees literal `**bold**` and `##` — the exact defect
`storefront-renders-no-markdown-2026-07-31` found on the storefront side, except here it is
the buyer's own file browser doing the rendering, and there is no boundary to fix it at except
this one. The `.md` files themselves are NOT touched — they remain the markdown source of
truth (buyer-facing deliverables keep their markdown per repo rule) — this module only adds
one extra, already-rendered view alongside them.

Self-contained by construction: every rule is inlined into a single `<style>` block, there is
no `<script>`, and no tag references an external host — the page must open from a buyer's
local disk with zero network activity.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import mistune

# `table` covers the GFM tables the QA report actually ships (the six-check scorecard).
# `strikethrough` is a zero-cost addition common in LLM-authored markdown. `escape=True`
# (mistune's default, stated explicitly here so it survives a mistune upgrade) renders any
# raw HTML inside the source markdown as text rather than executing it — the markdown bodies
# are LLM-generated and buyer-facing, so treat them as untrusted input.
_MD = mistune.create_markdown(plugins=["table", "strikethrough"], escape=True)


def _slugify(text: str, fallback: str) -> str:
    """A short, readable anchor id for a TOC entry.

    Section titles come from a fixed, small, known list (the bundle's own file titles), not
    free-form user input, so a simple collapse-non-alnum-to-hyphen slug is enough; no
    de-duplication beyond the caller-supplied fallback index is needed in practice.
    """
    slug = "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or fallback


@dataclass
class PackMeta:
    """Cover-header fields. Everything but `title` is optional — a dossier assembled with
    partial data (no source count, no verified_at) must still render a complete page rather
    than raise, since this runs inline in the bundle writer on every publish."""

    title: str
    one_liner: str = ""
    verified_at: str = ""
    source_count: Optional[int] = None
    pack_id: str = ""


def _cover_html(meta: PackMeta) -> str:
    """The header block: title, one-liner, and whatever provenance fields are available.
    Each stat is only emitted when present — an absent source count must not print '0
    sources' (that reads as a claim we didn't check), it must simply not appear."""
    stats: List[str] = []
    if meta.verified_at:
        stats.append(
            f'<span class="stat"><span class="stat-label">Verified</span> '
            f'<span class="stat-value">{html.escape(meta.verified_at)}</span></span>'
        )
    if meta.source_count is not None:
        noun = "source" if meta.source_count == 1 else "sources"
        stats.append(
            f'<span class="stat"><span class="stat-label">Grounded in</span> '
            f'<span class="stat-value">{meta.source_count} {noun}</span></span>'
        )
    stats_html = f'<div class="cover-stats">{"".join(stats)}</div>' if stats else ""
    one_liner_html = (
        f'<p class="cover-one-liner">{html.escape(meta.one_liner)}</p>' if meta.one_liner else ""
    )
    return (
        '<header class="cover">'
        f'<h1 class="cover-title">{html.escape(meta.title)}</h1>'
        f"{one_liner_html}"
        f"{stats_html}"
        "</header>"
    )


def _toc_html(entries: Sequence[Tuple[str, str]]) -> str:
    """entries: (slug, title) pairs, in section order."""
    items = "".join(
        f'<li><a href="#{slug}">{html.escape(title)}</a></li>' for slug, title in entries
    )
    return f'<nav class="toc" aria-label="Table of contents"><h2>Contents</h2><ol>{items}</ol></nav>'


def _footer_html(meta: PackMeta) -> str:
    pack_id_html = f'<p class="footer-id">Pack ID: {html.escape(meta.pack_id)}</p>' if meta.pack_id else ""
    return (
        '<footer class="pack-footer">'
        "<p>Every factual claim in this pack cites a retrievable source.</p>"
        f"{pack_id_html}"
        "</footer>"
    )


def render_pack_html(sections: List[Tuple[str, str]], meta: PackMeta) -> str:
    """Render the whole pack to one self-contained HTML document.

    Args:
        sections: ordered ``(display_title, markdown_text)`` pairs, given in READING order —
            this renders them in the order received and never re-sorts.

            Reading order is the ``BUNDLE_FILES`` contract (bridge.py), NOT the order the
            files happen to be written to the zip. The two differ: the bundle is written
            01, 02, 03, 04, QA, Marketing, 00, 05. This docstring used to say "the same order
            the corresponding files are written to the zip", and a caller that followed it
            (tools/backfill_bundle_html.py) shipped a reader opening on the build spec with
            the executive summary seventh and the first-week checklist last.
        meta: cover-header fields.

    Returns:
        A complete ``<!doctype html>`` document string: inline CSS only, no ``<script>``, no
        external ``http(s)://`` asset reference of any kind.
    """
    slugged: List[Tuple[str, str, str]] = []  # (slug, title, markdown)
    seen_slugs: set[str] = set()
    for i, (title, body) in enumerate(sections):
        slug = _slugify(title, f"section-{i}")
        if slug in seen_slugs:
            slug = f"{slug}-{i}"
        seen_slugs.add(slug)
        slugged.append((slug, title, body))

    toc = _toc_html([(slug, title) for slug, title, _ in slugged])

    section_blocks: List[str] = []
    for slug, title, body in slugged:
        rendered = _MD(body or "") if body else "<p><em>Not generated for this pack.</em></p>"
        section_blocks.append(
            f'<section id="{slug}" class="pack-section">'
            f'<h2 class="section-title">{html.escape(title)}</h2>'
            f'<div class="section-body">{rendered}</div>'
            "</section>"
        )

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(meta.title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="page">\n'
        f"{_cover_html(meta)}\n"
        f"{toc}\n"
        '<main class="pack-main">\n'
        f"{''.join(section_blocks)}\n"
        "</main>\n"
        f"{_footer_html(meta)}\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


# ---------------------------------------------------------------------------
# Inline stylesheet. System font stack only (no @font-face / no remote font — a remote font
# is exactly the kind of external request this page must never make). ~70ch measure for
# comfortable reading; light/dark via prefers-color-scheme; a print stylesheet that starts
# each deliverable on its own page so "print to PDF" already looks like a finished document.
# ---------------------------------------------------------------------------
_CSS = """
:root {
  --bg: #ffffff;
  --fg: #1a1a1a;
  --muted: #5b5b5b;
  --accent: #0a5f38;
  --border: #dcdcdc;
  --code-bg: #f4f4f4;
  --quote-bg: #f8f8f6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a;
    --fg: #e8e8e6;
    --muted: #a6a6a6;
    --accent: #4fd1a5;
    --border: #33363c;
    --code-bg: #1e2126;
    --quote-bg: #1a1d22;
  }
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial,
    sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
  line-height: 1.6;
  font-size: 17px;
}
.page { max-width: 70ch; margin: 0 auto; padding: 3rem 1.25rem 5rem; }
.cover { border-bottom: 2px solid var(--border); padding-bottom: 1.75rem; margin-bottom: 2rem; }
.cover-title { font-size: 1.9rem; line-height: 1.25; margin: 0 0 0.5rem; }
.cover-one-liner { font-size: 1.1rem; color: var(--muted); margin: 0 0 1rem; }
.cover-stats { display: flex; flex-wrap: wrap; gap: 1.5rem; }
.stat { font-size: 0.92rem; color: var(--muted); }
.stat-label { text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.72rem; margin-right: 0.35rem; }
.stat-value { color: var(--fg); font-weight: 600; }
.toc { border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 2.5rem; }
.toc h2 { margin-top: 0; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.toc ol { margin: 0; padding-left: 1.25rem; }
.toc a { color: var(--accent); text-decoration: none; }
.toc a:hover { text-decoration: underline; }
.pack-section { margin-bottom: 3.5rem; }
.section-title {
  font-size: 1.5rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem;
  margin-bottom: 1.25rem;
  scroll-margin-top: 1rem;
}
.section-body h1 { font-size: 1.4rem; }
.section-body h2 { font-size: 1.2rem; margin-top: 2rem; }
.section-body h3 { font-size: 1.05rem; margin-top: 1.5rem; }
.section-body h1, .section-body h2, .section-body h3, .section-body h4 {
  line-height: 1.3;
}
.section-body p, .section-body ul, .section-body ol { margin: 0.9rem 0; }
.section-body a { color: var(--accent); }
.section-body table {
  border-collapse: collapse;
  width: 100%;
  margin: 1.25rem 0;
  font-size: 0.92rem;
}
.section-body th, .section-body td {
  border: 1px solid var(--border);
  padding: 0.5rem 0.65rem;
  text-align: left;
  vertical-align: top;
}
.section-body th { background: var(--code-bg); font-weight: 600; }
.section-body blockquote {
  margin: 1.25rem 0;
  padding: 0.75rem 1.1rem;
  border-left: 3px solid var(--accent);
  background: var(--quote-bg);
  color: var(--muted);
}
.section-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--code-bg);
  padding: 0.15em 0.4em;
  border-radius: 4px;
  font-size: 0.9em;
}
.section-body pre {
  background: var(--code-bg);
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
}
.section-body pre code { background: none; padding: 0; }
.section-body hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
.pack-footer {
  border-top: 2px solid var(--border);
  margin-top: 3rem;
  padding-top: 1.5rem;
  color: var(--muted);
  font-size: 0.9rem;
}
.footer-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

@media print {
  body { font-size: 12pt; }
  .page { max-width: none; padding: 0; }
  .toc { border: none; padding: 0; }
  .toc a { color: var(--fg); }
  .pack-section {
    break-before: page;
    page-break-before: always;
  }
  .pack-section:first-of-type {
    break-before: auto;
    page-break-before: avoid;
  }
  a { color: var(--fg) !important; text-decoration: none; }
}
"""
