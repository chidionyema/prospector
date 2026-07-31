"""Markdown -> plain text, for fields the storefront renders WITHOUT a markdown parser.

The pack `.md` files are markdown and must stay markdown. But a subset of the same strings
also travels to the Store Catalog as *metadata* (`proofPoint`, `sampleExtract`, `headline`,
`subhead`, `oneLine`, ...), and the storefront prints those as literal text — e.g.
`store_platform/src/Store.Web/src/pages/pack/[id].tsx:469` renders `{line}` straight into JSX.
So a rationale bullet like `- **buyer intent:** growers search for ...` reaches a buyer with the
asterisks showing.

This module is the boundary converter. It strips markup only; it never rewords, truncates
meaning, or invents text, so it cannot manufacture a claim that the moat did not verify.

`_EMPHASIS` deliberately requires non-word delimiters for `_`/`__` so that snake_case tokens
that legitimately appear in buyer-facing prose (`buyer_intent`, `who_pays`) survive intact.
"""
from __future__ import annotations

import re
from typing import Iterable, List

# Inline constructs, applied in this order. Images before links (an image is a link with a
# leading `!`), links before emphasis (link text may itself be bold).
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")
_CODE_FENCE = re.compile(r"^\s*```.*$", re.MULTILINE)
_CODE_SPAN = re.compile(r"`([^`]+)`")
_EMPHASIS = (
    re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL),
    re.compile(r"\*\*(.+?)\*\*", re.DOTALL),
    re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL),
    re.compile(r"(?<![\w_])___(.+?)___(?![\w_])", re.DOTALL),
    re.compile(r"(?<![\w_])__(.+?)__(?![\w_])", re.DOTALL),
    re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", re.DOTALL),
    re.compile(r"~~(.+?)~~", re.DOTALL),
)
# Leading block markers: heading hashes, blockquote arrows, bullet and ordered-list markers.
_BLOCK_PREFIX = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d{1,3}[.)]\s+)")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$")
_WS = re.compile(r"[ \t]+")


def to_plain_text(
    text: str | None, *, collapse: bool = False, keep_link_urls: bool = False
) -> str:
    """Strip markdown markup, preserving the words verbatim.

    collapse=True folds all whitespace (including newlines) to single spaces — use it for
    single-line catalog fields such as `proofPoint` or `subhead`.

    keep_link_urls=True renders `[text](url)` as `text (url)` instead of dropping the target.
    Use it wherever the URL is the evidence — a sourced excerpt loses its point if the link
    it cites disappears.
    """
    if not text:
        return ""
    s = _CODE_FENCE.sub("", str(text))
    s = _IMAGE.sub(r"\1", s)
    s = _LINK.sub(r"\1 (\2)" if keep_link_urls else r"\1", s)
    s = _CODE_SPAN.sub(r"\1", s)
    for pattern in _EMPHASIS:
        # Repeat until stable: nested emphasis (`**bold _and_ italic**`) needs more than one pass.
        prev = None
        while prev != s:
            prev = s
            s = pattern.sub(r"\1", s)

    lines: List[str] = []
    for line in s.split("\n"):
        if _TABLE_RULE.match(line):
            continue
        line = _BLOCK_PREFIX.sub("", line)
        lines.append(_WS.sub(" ", line).strip())
    s = "\n".join(lines)

    if collapse:
        return " ".join(s.split())
    # Never leave more than one blank line behind after stripping block markers.
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def plain_lines(lines: Iterable[str] | None, *, drop_empty: bool = True) -> List[str]:
    """to_plain_text(collapse=True) over a list of single-line fields (e.g. sampleExtract)."""
    out = [to_plain_text(x, collapse=True) for x in (lines or [])]
    return [x for x in out if x] if drop_empty else out


def has_markup(text: str | None) -> bool:
    """True when `text` still carries markdown that a plain-text renderer would expose.

    Used by the tests and the publish-time assertion — the check that would have caught
    `**buyer intent:**` before it reached a storefront.
    """
    if not text:
        return False
    return to_plain_text(text, collapse=True) != " ".join(str(text).split())
