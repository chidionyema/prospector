/**
 * Which renderer a document gets, and how a framed one is assembled.
 *
 * Separate from `DocBody.tsx` for one reason: this file imports nothing. The console's test
 * environment is plain node with no DOM (`vitest.config.ts`), so a rule that lives beside
 * `react-markdown` can only be checked by scanning source. A rule that lives here can be called.
 *
 * The suffix set is the browser half of `prospector/ops/docs_view.py::_TEXT_SUFFIXES`. The two
 * can disagree in exactly one safe direction: the python side decides what may be READ, this side
 * decides how what came back is DRAWN. A format python refuses never reaches here, and a format
 * this file has no branch for is drawn as source, which is always truthful and never blank.
 */

export type DocKind = 'html' | 'markdown' | 'source';

/** The suffix, lowercased, or '' — the same plain split the python side uses. */
export function suffixOf(name: string): string {
  const base = name.slice(name.lastIndexOf('/') + 1);
  const dot = base.lastIndexOf('.');
  return dot <= 0 ? '' : base.slice(dot).toLowerCase();
}

export function kindOf(name: string): DocKind {
  switch (suffixOf(name)) {
    case '.html':
    case '.htm':
      return 'html';
    case '.md':
    case '.markdown':
      return 'markdown';
    // A JSON file put through a markdown parser is one long paragraph, which is worse than the
    // file. Everything unrecognised lands here too, on purpose: source is never wrong.
    default:
      return 'source';
  }
}

/**
 * The sandbox every framed document is rendered under, and the reason it is a constant.
 *
 * `allow-same-origin` WITHOUT `allow-scripts`, and the pair is the whole security argument:
 *
 *   - No `allow-scripts` means no script in the document ever runs. `<script>`, `onclick`,
 *     `javascript:` — all inert. That is what makes it safe to draw a file that anyone with
 *     commit access wrote, to a reader who has no session, on `/s/<token>`.
 *   - `allow-same-origin` is what lets the PARENT read `contentDocument.body.scrollHeight` and
 *     size the frame to its content, so a document is one page rather than a page trapped in a
 *     scrolling well. On its own it grants the frame our origin, which would matter if the frame
 *     could run code. It cannot.
 *
 * Adding `allow-scripts` alongside `allow-same-origin` removes the sandbox altogether — the frame
 * could then reach `parent` — and browsers warn about exactly that combination. It is pinned by
 * `tests/doc-render.test.ts` so the pair cannot be widened by someone chasing an auto-height bug.
 */
export const FRAME_SANDBOX = 'allow-same-origin';

/**
 * The three lines put into every framed document.
 *
 * A repo page is written for a browser tab, not for a panel inside a console: it assumes the UA
 * default margin and it assumes nothing else is on screen. `margin:0` hands it the panel's own
 * padding rather than stacking two, and `color-scheme` lets an un-themed document follow the
 * reader's theme instead of being a white slab in a dark console. The charset matters only for
 * the fragments (below), which carry none of their own; a full document declares its own first
 * and that declaration is the one the parser has already acted on.
 *
 * Nothing else is injected, and it is injected FIRST inside the head so that anything the
 * document says about its own margins wins. Showing a document as it was written is the point.
 */
export const FRAME_PREAMBLE =
  '<meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<style>:root{color-scheme:light dark}html,body{margin:0}img,video,table{max-width:100%}</style>';

/** Height used before a frame has been measured, and the floor it never drops below. */
export const MIN_FRAME_PX = 320;

/**
 * A `<head>` start tag. The word boundary is load-bearing: `docs/storefront/look-engine/parts/
 * 02-body.html` opens with `<header class="masthead">`, and a `<head[^>]*>` without `\b` matches
 * it, which would splice our stylesheet into the middle of somebody's page banner.
 */
const HEAD_OPEN = /<head\b[^>]*>/i;

/** A doctype, or an `<html>` start tag, at the very top — optional BOM and comments allowed. */
const DOC_START = /^﻿?\s*(?:<!--[\s\S]*?-->\s*)*(<!doctype\b[^>]*>|<html\b[^>]*>)/i;

/**
 * Does this text open a whole HTML document, or is it a body fragment?
 *
 * Both shapes are tracked in this repo and the difference decides where the preamble may go.
 * Measured 2026-08-21: 14 of the 18 tracked `.html` files are whole documents opening
 * `<!DOCTYPE html>` (the mumchimp mockups); the other 4 are fragments written to be wrapped by
 * something else (`docs/storefront/look-engine/*`), and one of those starts with a comment.
 */
export function isFullDocument(text: string): boolean {
  return DOC_START.test(text.slice(0, 2048));
}

/**
 * The exact string handed to the frame's `srcDoc`.
 *
 * Why this is a function and not `FRAME_PREAMBLE + text`. Prepending to a whole document puts a
 * `<meta>` in front of its `<!DOCTYPE html>`, and a doctype that is not the first thing in the
 * stream is not a doctype — the browser drops the page into QUIRKS MODE, where `box-sizing`,
 * table cell heights and percentage heights all behave differently. Every mockup in
 * `docs/design/mumchimp-build-bundle/` would have rendered subtly wrong and nothing would have
 * said why.
 *
 * So: into the head where there is one, after the doctype where there is not, and only for a
 * fragment is the preamble simply put in front.
 */
export function framedSrcDoc(text: string): string {
  if (isFullDocument(text)) {
    const head = HEAD_OPEN.exec(text);
    // Inside the head, first — the document's own rules come after ours and therefore win.
    if (head) {
      const at = head.index + head[0].length;
      return text.slice(0, at) + FRAME_PREAMBLE + text.slice(at);
    }
    // A document may leave `<head>` implied. Land after the doctype and let the parser hoist.
    const start = DOC_START.exec(text) as RegExpExecArray;
    const at = start.index + start[0].length;
    return text.slice(0, at) + FRAME_PREAMBLE + text.slice(at);
  }
  return FRAME_PREAMBLE + text;
}
