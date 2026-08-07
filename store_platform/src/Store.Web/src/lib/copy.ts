/**
 * Repairing copy the catalogue was already published with.
 *
 * THE DEFECT, measured against the live API on 2026-08-06:
 *
 *   curl -s https://api.mumchimp.com/catalog
 *     oneLine present   63
 *     oneLine truncated 34   <- every one of them EXACTLY 153 characters
 *     clean lengths     111..362
 *
 * 153 is not a coincidence and it is not the writer running out of things to say. It is
 * `prospector/bridge.py:394`:
 *
 *     if len(one_liner) > 150:
 *         one_liner = one_liner[:150] + "..."
 *
 * A hard slice at a character index, with no regard for where a word ends, applied on the
 * publish path. So 54% of the shelf shipped with its description cut, and some of them cut
 * mid-word: `for a flat fee per applicat...`, `keeps you on ...`. On a storefront whose entire
 * pitch is "we check our numbers and cite our sources", a product description that stops in the
 * middle of a word is the loudest possible contradiction of the brand, and it is on the money
 * page, in the lead paragraph, above the buy button.
 *
 * `bridge.py` is fixed too, so nothing published from here on is cut this way. That does NOT fix
 * the 34 rows already in the production database -- those are only repaired by re-publishing the
 * catalogue, which is a money-rail operation with its own hazards (an upsert ignores `PricePence`
 * on update and can charge a buyer a price the fulfilment fence then refuses; bundle keys are
 * content-addressed). So the storefront repairs what it is handed, and keeps doing so
 * indefinitely: a reader must never see the cut, whatever is in the row.
 *
 * The engine's `to_plain_text` has the equivalent job on the markdown side. This is the same idea
 * one boundary later.
 */

/** What `bridge.py` appends, plus the typographic form in case anything upstream is fixed. */
const TRUNCATION_MARKS = ['...', '…'] as const;

/**
 * True when this string was cut by a length cap rather than finished by its author.
 *
 * Deliberately conservative: it tests only for a trailing truncation mark. A sentence that
 * genuinely ends in an ellipsis is rare in this catalogue's register (these are product
 * descriptions, not fiction), and treating one as truncated costs nothing -- the repair leaves
 * a legible sentence either way.
 */
export function isTruncated(text?: string | null): boolean {
  if (!text) return false;
  const trimmed = text.trimEnd();
  return TRUNCATION_MARKS.some((mark) => trimmed.endsWith(mark));
}

/**
 * Make a cut string read as a deliberate abbreviation instead of a broken one.
 *
 * The last whitespace-delimited token is dropped, then a single `…` is appended. Dropping the
 * token is the whole point and it is why this cannot be done with a regex on the ellipsis alone:
 * the cut is at character 150 of the original, so the final token is a coin-flip between a whole
 * word (`...own rules...`) and a fragment (`...per applicat...`), and NOTHING in the string that
 * survives tells you which one you have. Given that, the only choice available is which failure
 * to take, and they are not equally bad. Losing one real word costs a reader nothing they cannot
 * infer; printing half a word tells them the site is broken.
 *
 * `…` rather than `...`: one character instead of three, so it never wraps to its own line, and
 * screen readers announce it once rather than as three full stops.
 *
 * Returns the input untouched when it was not truncated, so this is safe to wrap around every
 * description on the site rather than only the ones we have checked.
 */
export function repairTruncation(text: string): string;
export function repairTruncation(text: null | undefined): null;
export function repairTruncation(text?: string | null): string | null;
export function repairTruncation(text?: string | null): string | null {
  if (!text) return text ?? null;
  if (!isTruncated(text)) return text;

  let body = text.trimEnd();
  for (const mark of TRUNCATION_MARKS) {
    if (body.endsWith(mark)) {
      body = body.slice(0, -mark.length);
      break;
    }
  }

  // Drop the final token. `trimEnd` first so `keeps you on ` -- a cut that landed on a space --
  // loses `on` rather than losing nothing and re-appending the ellipsis it just removed.
  body = body.trimEnd();
  const lastSpace = body.lastIndexOf(' ');
  // No space at all means the cap fell inside the first word. There is nothing to trim back to,
  // and returning an empty string would blank the card, so the fragment is kept.
  if (lastSpace > 0) body = body.slice(0, lastSpace);

  // A trailing comma or dash before an ellipsis reads as a typo.
  // \u2014 and \u2013 are the em- and en-dash, written as escapes because
  // `dashFree.test.ts` bans the literal characters from every TS/TSX source file here.
  body = body.replace(/[\s,;:\u2014\u2013-]+$/u, '');

  return body ? `${body}…` : text;
}
