/**
 * Site-wide text normalisation, the storefront equivalent of
 * `tools/make_kill_log.py`'s `nodash()`.
 *
 * Em-dashes and en-dashes (U+2014 and U+2013) are the most universally recognised
 * AI writing signature. The published copy on mumchimp.com used to lean on them
 * because the marketing prose was written to a model that defaults to them.
 * Run user-visible text through `nodash()` at the render boundary to drop the
 * tell. Compound words like "out-of-hours" and "slip-resistance" are preserved
 * because the regex only matches dashes surrounded by whitespace.
 *
 * Kept in lock-step with the Python `nodash()` in `tools/make_kill_log.py`:
 * the substitution rules are byte-for-byte identical.
 */

const EM_DASH = "\u2014";
const EN_DASH = "\u2013";

/**
 * A dash between two digits is a RANGE, and a comma changes what it means.
 *
 * The blanket rule was safe while this only ran over marketing prose written in-house. Pointing it
 * at the live catalogue found 13 fields where it is not: `Mothers 25-45 who have a child with
 * autism`, `Gen Z gig workers (18-27)`, `for 2025-2026`. Turning those into "Mothers 25, 45" and
 * "2025, 2026" states something the source did not say, on a storefront whose rule is
 * source-or-die. Measured 2026-08-06:
 *
 *   curl -s https://api.mumchimp.com/catalog | python3 -c "import sys,json,re;\
 *   d=json.load(sys.stdin);p=re.compile(r'\\d[--]\\d');\
 *   print(sum(1 for i in d for v in i.values() if isinstance(v,str) and p.search(v)))"
 *
 * A hyphen keeps the range and drops the tell, which is the whole point of the function.
 */
const NUMERIC_RANGE = new RegExp(`(\\d)\\s*[${EM_DASH}${EN_DASH}]\\s*(\\d)`, "g");

export function nodash(s: string | null | undefined): string {
  if (!s) return "";
  let out = s
    // U+2011 NON-BREAKING HYPHEN joins compound words ("O‑licence", "zero‑hour"), so it
    // becomes a plain hyphen and NOT ", " -- a comma would split the word itself. It renders
    // as a dash the buyer sees while surviving every check written against U+002D, which is
    // how 3 of them reached live titles undetected before 2026-08-08. Kept in lock-step with
    // the Python `nodash()` in `prospector/plain_text.py:507`.
    .replaceAll("‑", "-")
    .replace(NUMERIC_RANGE, "$1-$2")
    .replaceAll(EM_DASH, ", ")
    .replaceAll(EN_DASH, ", ")
    .replace(/\s+-\s+/g, ", ");
  out = out.replace(/\s+/g, " ");
  out = out.replace(/\s+([.,;])/g, "$1");
  return out.trim();
}
