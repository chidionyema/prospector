/**
 * Pull the citations out of a sourced prose line, at the render boundary.
 *
 * WHY THIS EXISTS
 *
 * The storefront's entire proposition, stated verbatim on the pack page, is "every check it
 * faced, each verdict, and a clickable source behind every claim". Measured against the served
 * production build on 2026-08-05, `GET /pack/8d5e24fbe6c1f5d3` rendered **zero** source
 * anchors. The URLs were all there -- they were just printed as text:
 *
 *   "...printable PDFs (source: https://socialstorytemplates.com/)."
 *
 * `/sample` renders 8 real `<a href>` source links, so the capability existed; the money page
 * simply never used it. The single most valuable thing the brand owns was the one thing the
 * design did least with.
 *
 * WHY THE PARSE LIVES HERE AND NOT IN THE ENGINE
 *
 * Same rule as `prospector/plain_text.py`: the engine writes prose, the storefront converts at
 * the boundary. `sampleExtract` is a `string[]` of human-readable lines whose readability does
 * not depend on a renderer -- they are correct as plain text in an email, a PDF or a terminal.
 * Teaching the engine to emit structured citations would fix one consumer and change the
 * contract for all of them. Parsing here fixes the consumer that is wrong.
 *
 * WHAT THE REAL DATA LOOKS LIKE
 *
 * Sampled across 12 live packs (34 `sampleExtract` lines) on 2026-08-05:
 *
 *   packs with >= 1 sourced line   12 / 12
 *   lines with a parseable source  30 / 34
 *   label forms                    "source" x32, bare URL x3
 *
 * Four shapes occur in production and all four are covered by the tests:
 *
 *   1. `(source: URL)`                       -- the common case
 *   2. `(source: URL - "a quoted passage")`  -- URL plus the passage it is grounded in
 *   3. `(source: URL; source: URL)`          -- two sources in one paren group
 *   4. `(prose...; ..., source: URL)`        -- a source folded into a larger aside
 *
 * The parser therefore removes the citation *scaffolding* rather than assuming a fixed shape,
 * and returns whatever prose is left. A line with no URL comes back unchanged with an empty
 * citation list, so the caller renders it exactly as before.
 */

export interface Citation {
  /** The absolute URL, exactly as it appeared in the prose. */
  url: string;
  /** Hostname without `www.`, e.g. "socialstorytemplates.com". The chip's visible label. */
  host: string;
  /** The passage the claim is grounded in, when the line quoted one. Shown as a title. */
  quote?: string;
}

export interface SourcedText {
  /** The prose with the citation scaffolding removed. Never empty unless the input was. */
  text: string;
  /** Every citation found, in the order they appeared. De-duplicated by URL. */
  citations: Citation[];
}

/**
 * A URL run. Stops at whitespace and at the characters that in practice terminate a URL inside
 * this prose: `)` closes the aside, `;` separates two sources in one group, `"` starts a quote.
 * Deliberately NOT a general URL grammar -- it only has to be right for the corpus above.
 */
const URL_RE = /https?:\/\/[^\s)<>"';]+/g;

/**
 * A full citation fragment: an optional leading separator, the `source:` label, the URL, and an
 * optional dash-quoted passage. This is the thing that gets deleted from the prose.
 *
 * The leading `[;,]?` is what makes shape 3 collapse cleanly: the first `source: URL` is removed
 * without its separator, then the second matches WITH the `; ` in front of it, leaving `()`.
 */
// The dashes below are DATA, not copy: the engine writes `URL - "quote"` with a real em-dash, so
// the pattern has to contain one in order to strip it. Same opt-out `lib/discovery.ts` uses.
const CITATION_RE =
  /[;,]?\s*sources?\s*:\s*https?:\/\/[^\s)<>"';]+(?:\s*[—–-]\s*"[^"]*")?/gi; // dash-free-ignore

/** A bare URL with an optional leading separator, for lines that omitted the `source:` label. */
const BARE_URL_RE = /[;,]?\s*https?:\/\/[^\s)<>"';]+/g;

/** Trailing punctuation that belongs to the sentence, not to the URL. */
const TRAILING_PUNCT_RE = /[.,;:]+$/;

/**
 * Split a sourced prose line into its text and its citations.
 *
 * Pure and total: any string in, a `SourcedText` out. Never throws, never returns `undefined`.
 */
export function parseCitations(line: string): SourcedText {
  if (!line || line.indexOf('http') === -1) {
    return { text: line ?? '', citations: [] };
  }

  const citations: Citation[] = [];
  const seen = new Set<string>();

  for (const match of line.matchAll(URL_RE)) {
    const url = match[0].replace(TRAILING_PUNCT_RE, '');
    if (!url || seen.has(url)) continue;
    seen.add(url);
    citations.push({
      url,
      host: hostLabel(url),
      quote: quoteAfter(line, (match.index ?? 0) + match[0].length),
    });
  }

  return { text: stripCitations(line), citations };
}

/**
 * Remove every citation fragment from a line and repair the punctuation the removal breaks.
 *
 * The repair order matters. Deleting `source: URL` from `"...safe (source: URL)."` leaves
 * `"...safe ()."`; only after the empty parens collapse does the space-before-period become
 * visible, so parens are collapsed BEFORE whitespace is tightened.
 */
function stripCitations(line: string): string {
  let out = line.replace(CITATION_RE, '').replace(BARE_URL_RE, '');

  // An aside that held nothing but citations is now empty -- drop it whole. Runs to a fixed
  // point so `( )` left inside `(( ))` also goes.
  let previous: string;
  do {
    previous = out;
    out = out.replace(/\(\s*[;,]?\s*\)/g, '');
  } while (out !== previous);

  return out
    .replace(/\(\s*[;,]\s*/g, '(') // "(; solvency..." -> "(solvency..."
    .replace(/\s+([.,;:!?)])/g, '$1') // "safe ." -> "safe."
    .replace(/\(\s+/g, '(')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * The passage quoted immediately after a URL, if any: `URL - "the law says you must..."`.
 * Matched only at the position right after the URL so a quote elsewhere in the line is not
 * mis-attributed to it.
 */
function quoteAfter(line: string, from: number): string | undefined {
  const rest = line.slice(from);
  const m = /^\s*[—–-]\s*"([^"]+)"/.exec(rest); // dash-free-ignore: matching, not rendering
  const quote = m?.[1]?.trim();
  return quote ? quote : undefined;
}

/**
 * The chip's visible label. Hostname, `www.` stripped.
 *
 * Falls back to the raw URL rather than throwing: a malformed URL still deserves to render as
 * *something* the visitor can see and copy, and `new URL()` throws on input this parser will
 * happily hand it (the regex above matches `http://` with nothing after it).
 */
export function hostLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url.replace(/^https?:\/\//, '').split('/')[0] || url;
  }
}

/**
 * Does this line carry at least one citation? Cheap pre-check for callers that want a different
 * container for sourced vs unsourced lines without paying for the full parse.
 *
 * Deliberately NOT `URL_RE.test(line)`: `URL_RE` carries the `g` flag, and `test` on a global
 * regex advances `lastIndex` between calls, so the same input alternates true/false. That class
 * of bug survives a unit test that only ever calls it once.
 */
export function hasCitation(line: string): boolean {
  return typeof line === 'string' && /https?:\/\/[^\s)<>"';]+/.test(line);
}
