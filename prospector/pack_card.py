"""P5: the one page a buyer actually pins up — `First_Fortnight.html`.

THE DEFECT
----------
Founder, verbatim: **"markdown files is not the one."** Eight `.md` files in a zip reads as an
AI output dump, and the buyer is a would-be solo operator with an evening free. Nobody reads
12,000 words before deciding whether to start. The pack has no entry point that fits on a
single sheet of paper.

WHAT THIS IS
------------
One printable page: what you are building, who pays for it, what to do in the first fortnight,
and the two or three things we could NOT prove — so the buyer knows on sheet one where their
own homework starts. It is a summary of the pack, never a replacement: every line here also
appears in a deliverable, and this file is a bonus, so a render failure can never block a
listing.

DETERMINISTIC, WHICH IS WHY IT CAN BE BACKFILLED
------------------------------------------------
Zero model calls. Everything is either a field already on the dossier or a line lifted out of
the pack's own markdown. That is what lets the same renderer put this page into the 62 packs
already sold, and it is the constraint that shaped every extraction below: where the source
text is thin, the card prints less rather than inventing more.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not compute, rephrase or summarise a figure. A money number on a one-page card is the
line a buyer will act on first, so it is copied verbatim out of the financial model or it is
absent — an "about £X" that the model does not literally say would be the pack contradicting
itself on its most-read page.
"""
from __future__ import annotations

import html
import re
from typing import Any, Iterable, List, Tuple

FILENAME = "First_Fortnight.html"

# A numbered or bulleted step at the top level of the checklist. Sub-bullets are deliberately
# NOT collected: this page is one sheet, and a checklist that spills onto a second page is the
# thing it exists to replace.
_STEP_RE = re.compile(r"^\s{0,3}(?:\d{1,2}[.)]|[-*+])\s+(?P<body>\S.*)$")
_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<body>\S.*)$")

# Inline markdown the card strips rather than renders: it prints steps as plain text inside its
# own typography, so `**bold**` and `[a](b)` must not arrive as literal punctuation — the exact
# defect `storefront-renders-no-markdown-2026-07-31` found, one layer in.
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)")


def _plain(text: str) -> str:
    return _EMPHASIS_RE.sub("", _LINK_RE.sub(r"\1", str(text or ""))).strip()


def steps_from_checklist(markdown: str, limit: int = 12) -> List[str]:
    """The checklist's top-level steps, in order, as plain sentences.

    `limit` is a page-fit bound, not a judgement about which steps matter: the caller says how
    many lines fit on one sheet and the renderer prints a pointer to the full document rather
    than pretending the rest do not exist (`render` emits that line whenever it truncates).
    """
    steps: List[str] = []
    for line in str(markdown or "").splitlines():
        m = _STEP_RE.match(line)
        if not m:
            continue
        body = _plain(m.group("body"))
        if body and len(body) > 320:
            # A "step" that runs to a paragraph would push everything below it off the page —
            # but DROPPING it is worse than shortening it: the plan silently renumbers and the
            # buyer follows a sequence with a hole in it. Print its opening sentence, which is
            # where the instruction lives, and leave the full text where it already is.
            body = _first_sentence(body, cap=320)
        if body:
            steps.append(body)
        if len(steps) >= limit:
            break
    return steps


def _first_sentence(text: str, cap: int = 260) -> str:
    """The first sentence of a passage, or "" — never a mid-word cut.

    Truncating mid-word is how `published-onelines-truncated-mid-word` shipped on 34 of 63
    listings. Here the fallback is to drop the value entirely: an absent line on a card is
    invisible, a severed one is a defect the buyer can see.
    """
    body = _plain(text).replace("\n", " ").strip()
    if not body:
        return ""
    m = re.search(r"^(.{20,%d}?[.!?])\s" % cap, body + " ")
    if m:
        return m.group(1).strip()
    return body if len(body) <= cap else ""


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def unproven_labels(checks: Iterable[Any], limit: int = 4) -> List[str]:
    """The checks that came back unproven, in the buyer's words.

    Same label map as every other document in the pack (`dossier.check_label`) — a card that
    calls `payer_solvency` something the QA report does not is a card the buyer cannot
    reconcile with the evidence behind it.
    """
    from .dossier import check_label
    out: List[str] = []
    for chk in checks or []:
        if _verdict(chk) == "unverifiable":
            out.append(check_label(str(getattr(chk, "check_name", "") or "")))
        if len(out) >= limit:
            break
    return out


def _kv(label: str, value: str) -> str:
    return (f'<div class="fact"><dt>{html.escape(label)}</dt>'
            f'<dd>{html.escape(value)}</dd></div>')


def render(
    dossier: Any,
    checklist_md: str = "",
    financial_md: str = "",
    pack_id: str = "",
) -> str:
    """The card as one self-contained HTML page, or "" when there is nothing worth printing.

    "" is returned when the pack has no checklist steps AND no buyer named: a card with a title
    and three blanks on it is worse than no card, because it is the first thing the buyer opens.
    """
    cand = getattr(dossier, "candidate", None)
    title = str(getattr(cand, "title", "") or "").strip()
    one_liner = str(getattr(cand, "one_liner", "") or "").strip()
    who = _first_sentence(str(getattr(cand, "who_pays", "") or ""))
    steps = steps_from_checklist(checklist_md)
    if not steps and not who:
        return ""

    checks = list(getattr(dossier, "checks", None) or [])
    facts: List[str] = []
    if who:
        facts.append(_kv("Who pays", who))
    money = _headline_money(financial_md)
    for label, value in money:
        facts.append(_kv(label, value))

    unproven = unproven_labels(checks)
    steps_html = "".join(
        f'<li><span class="tick" aria-hidden="true"></span>{html.escape(s)}</li>'
        for s in steps)
    more = ""
    if len(steps_from_checklist(checklist_md, limit=999)) > len(steps):
        more = ('<p class="more">The rest of the plan is in the first-week checklist inside '
                'this pack.</p>')

    unproven_html = ""
    if unproven:
        items = "".join(f"<li>{html.escape(u)}</li>" for u in unproven)
        unproven_html = (
            '<section class="block warn"><h2>Start your own homework here</h2>'
            "<p>We searched and could not settle these. Treat them as assumptions, not "
            "findings — the evidence document in this pack lists what we looked for.</p>"
            f"<ul class=\"plain\">{items}</ul></section>")

    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title or 'First fortnight')} — first fortnight</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        '<main class="card">\n'
        '<p class="eyebrow">Your first fortnight</p>'
        f"<h1>{html.escape(title) if title else 'Your first fortnight'}</h1>"
        + (f'<p class="lede">{html.escape(one_liner)}</p>' if one_liner else "")
        + (f'<dl class="facts">{"".join(facts)}</dl>' if facts else "")
        + ('<section class="block"><h2>Do these, in this order</h2>'
           f'<ol class="steps">{steps_html}</ol>{more}</section>' if steps else "")
        + unproven_html
        + '<footer class="foot"><p>One page. Everything on it is also in the pack, with its '
          'sources. Print this, keep the rest for when you need it.</p>'
        + (f'<p class="id">Pack ID: {html.escape(pack_id)}</p>' if pack_id else "")
        + "</footer>\n</main>\n</body>\n</html>\n"
    )


_BULLET_RE = re.compile(r"^\s{0,3}[-*+]\s+(?P<body>\S.*)$")
_SUBHEAD_RE = re.compile(r"^#{2,6}\s+(?P<body>\S.*)$")
_BOLD_RUN_RE = re.compile(r"^\s*\*\*(?P<body>[^*]+)\*\*")
# The clause after an em-dash in the financial model is always the model explaining itself
# ("— the model's own figure, not ours"). True, and already in the document it came from; on a
# one-page card it is the sentence that costs the fact below it its place on the sheet.
_ASIDE_RE = re.compile(r"\s+[—–]\s+.*$")

# Which two figures earn a place on the sheet, and what the card calls them. The card's label is
# fixed here rather than copied from the source, because the source's own wording has changed at
# least once ("### Revenue" became "### What it earns") and a buyer comparing two packs bought
# three months apart should not see the same figure under two names.
_WANTED: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("Month 1 revenue", re.compile(r"^month\s*1\b", re.I)),
    ("Payback", re.compile(r"pai?d?\s*back|payback", re.I)),
)

# A headline figure is SHORT. The financial model ends with a "Key Assumptions" list whose
# bullets are paragraphs, and one of them matched "payback" mid-sentence and put 140 words of
# prose in a fact box on a live pack. Length is the honest discriminator here: a figure the
# model states in a line stays in a line, and anything longer is an argument, not a figure.
_FACT_MAX = 90

# The model's own words for "we could not work this out". Copying any of them into a fact box
# puts an apology where the buyer looks for a number, and the model already explains the
# absence, in full, in the document this line was lifted from.
_NOT_STATED_RE = re.compile(
    r"not computed|not specified|not stated|not supplied|unavailable|unknown|n/?a\b", re.I)


def _labelled_bullets(markdown: str) -> List[Tuple[str, str]]:
    """Every bullet in the document as (label, value), reading BOTH shapes the model writes.

    `- **Month 1:** £320 × 2 = **£640**` carries its own label. `### Payback Period` followed by
    `- **1 months**` does not — the label is the heading above it. Older packs on disk use the
    second shape and newer ones the first, so a card that understands only one of them prints
    a blank where the money should be for half the catalogue. That is exactly what the first
    version of this function did, on a live pack, which is why it now reads the structure
    instead of matching one release's wording.
    """
    out: List[Tuple[str, str]] = []
    heading = ""
    for line in str(markdown or "").splitlines():
        h = _SUBHEAD_RE.match(line)
        if h:
            heading = _plain(h.group("body"))
            continue
        b = _BULLET_RE.match(line)
        if not b:
            continue
        raw = b.group("body")
        bold = _BOLD_RUN_RE.match(raw)
        body = _plain(raw)
        head, sep, tail = body.partition(":")
        if sep and tail.strip():
            out.append((head.strip(), tail.strip()))
            continue
        # No colon: the bullet IS the statement, and it may answer to EITHER its own opening
        # bold run (`- **Paid back on the first sale** — ...`) or the heading above it
        # (`### Payback Period` / `- **1 months**`). Offering both is not sloppiness: which one
        # carries the label differs by release, and guessing wrong is how the old shape's
        # payback line went missing. The value is the same either way.
        if bold:
            out.append((_plain(bold.group("body")), body))
        if heading:
            out.append((heading, body))
    return out


def _headline_money(financial_md: str) -> List[Tuple[str, str]]:
    """Headline figures COPIED, never derived, out of the rendered financial model.

    `04_Financial_Model.md` is the one document in the pack whose arithmetic is done in Python
    (`artifacts._render_financial_model`), so its figures are exact — which is precisely why
    this function must not compute anything of its own. It finds a line and copies what is
    already printed; a figure the model does not state does not appear here.
    """
    out: List[Tuple[str, str]] = []
    bullets = _labelled_bullets(financial_md)
    for label, pattern in _WANTED:
        for src_label, src_value in bullets:
            if not pattern.search(src_label):
                continue
            value = _ASIDE_RE.sub("", src_value).strip(" .|")
            if not value or len(value) > _FACT_MAX or _NOT_STATED_RE.search(value):
                continue  # keep looking: a later bullet may state it properly
            out.append((label, value))
            break
    return out


# ---------------------------------------------------------------------------------------------
# One sheet of A4. System fonts only, no <script>, no external request — same rules as
# pack_html.py, for the same reason: this page opens from a buyer's own disk.
# ---------------------------------------------------------------------------------------------
_CSS = """
@page { size: A4; margin: 14mm; }
:root {
  --bg: #ffffff; --fg: #16181c; --muted: #5b6068; --accent: #0a5f38;
  --border: #d9dde1; --warn-bg: #fdf7ec; --warn-border: #e6cf9d;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --fg: #e8e8e6; --muted: #a6a6a6; --accent: #4fd1a5;
    --border: #33363c; --warn-bg: #221d13; --warn-border: #5a4a25;
  }
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.45; font-size: 15px;
}
.card { max-width: 46rem; margin: 0 auto; padding: 2.5rem 1.5rem 3rem; }
.eyebrow {
  text-transform: uppercase; letter-spacing: 0.09em; font-size: 0.68rem;
  color: var(--accent); font-weight: 700; margin: 0 0 0.35rem;
}
h1 { font-size: 1.5rem; line-height: 1.2; margin: 0 0 0.4rem; }
.lede { color: var(--muted); margin: 0 0 1.25rem; font-size: 1rem; }
.facts {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
  gap: 0.75rem 1.5rem; margin: 0 0 1.5rem; padding: 0.9rem 0;
  border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
}
.fact { margin: 0; }
.fact dt {
  text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.66rem;
  color: var(--muted); font-weight: 700; margin-bottom: 0.15rem;
}
.fact dd { margin: 0; font-size: 0.95rem; }
.block { margin: 0 0 1.4rem; }
.block h2 { font-size: 0.95rem; margin: 0 0 0.6rem; letter-spacing: 0.01em; }
.block p { margin: 0 0 0.6rem; color: var(--muted); font-size: 0.9rem; }
.steps { list-style: none; counter-reset: step; margin: 0; padding: 0; }
.steps li {
  counter-increment: step; position: relative;
  padding: 0.4rem 0 0.4rem 2.4rem; border-bottom: 1px dotted var(--border);
  break-inside: avoid; page-break-inside: avoid;
}
.steps li:last-child { border-bottom: none; }
.steps .tick {
  position: absolute; left: 0.9rem; top: 0.62rem;
  width: 0.85rem; height: 0.85rem; border: 1.5px solid var(--muted); border-radius: 3px;
}
.steps li::before {
  content: counter(step); position: absolute; left: 0; top: 0.4rem;
  font-size: 0.7rem; font-weight: 700; color: var(--muted);
}
.warn {
  background: var(--warn-bg); border: 1px solid var(--warn-border);
  border-radius: 8px; padding: 0.9rem 1.1rem;
}
.warn h2 { margin-top: 0; }
ul.plain { margin: 0; padding-left: 1.1rem; font-size: 0.9rem; }
.more { font-size: 0.82rem; margin-top: 0.6rem; }
.foot {
  border-top: 1px solid var(--border); margin-top: 1.5rem; padding-top: 0.8rem;
  color: var(--muted); font-size: 0.8rem;
}
.foot p { margin: 0 0 0.25rem; }
.id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
@media print {
  body { font-size: 10.5pt; background: #fff; color: #000; }
  .card { padding: 0; max-width: none; }
  .warn { background: #fff; }
}
"""
