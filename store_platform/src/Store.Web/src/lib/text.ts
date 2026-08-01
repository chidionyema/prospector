/**
 * Site-wide text normalisation, the storefront equivalent of
 * `tools/make_kill_log.py`'s `nodash()`.
 *
 * Em-dashes (`—`) and en-dashes (`–`) are the most universally recognised AI
 * writing signature. The published copy on mumchimp.com used to lean on them
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

export function nodash(s: string | null | undefined): string {
  if (!s) return "";
  let out = s
    .replaceAll(EM_DASH, ", ")
    .replaceAll(EN_DASH, ", ")
    .replace(/\s+-\s+/g, ", ");
  out = out.replace(/\s+/g, " ");
  out = out.replace(/\s+([.,;])/g, "$1");
  return out.trim();
}
