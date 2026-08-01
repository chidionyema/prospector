/**
 * The proof tier of a listing: the one sourced sentence behind it, cleaned for a renderer that
 * has no markdown parser.
 *
 * `proofPoint` was declared on the Pack type (`lib/api/client.ts`) and read by nothing. Measured
 * against the live catalogue on 2026-08-01: present on 51 of 51 packs, 51 distinct values,
 * rendered on 0 surfaces. The strongest evidence we hold per pack was reaching no buyer.
 *
 * It needs cleaning before it can, because it begins life as a markdown rationale bullet —
 * `- **value durability:** Passages show direct-payment recipients still face ...` — and
 * `prospector/plain_text.py` strips the markup without rewording. That is the correct engine
 * behaviour (a filter that rewrites its own evidence has stopped being a filter), but it leaves
 * two residues in the catalogue field, both measured on the same 51 packs:
 *
 *   - 20 carry the check name as a leading label: `value durability: Passages show ...`
 *   - 8 still carry raw `**`, from a publish path that never ran the converter at all
 *
 * Both are removed here rather than at the source, because the `.md` deliverables a buyer
 * downloads must keep their markdown — the conversion belongs at the display boundary.
 *
 * What this file does NOT do is as important: it strips markup and a known label, and it never
 * rewords, truncates meaning, or supplies a sentence where there was none. It cannot manufacture
 * a claim the moat did not verify. A proofPoint that cleans to nothing returns `null`, and the
 * caller renders no proof line at all — absent stays absent, the same rule the facets follow.
 */

/**
 * The verification checks, mirrored from `prospector/dossier.py`'s `_CHECK_LABEL`.
 *
 * This is a closed vocabulary on purpose. The tempting implementation is `/^[a-z ]+:\s/`, which
 * also eats the opening of a legitimately sourced sentence — `Ofgem: the price cap fell ...`
 * loses its attribution, which is precisely the word a buyer needs in order to check us. Only a
 * name that is actually one of our internal checks may be stripped.
 *
 * `proof.test.ts` reads dossier.py off disk and fails if this list drifts from it, the same way
 * `facets.test.ts` holds the facet vocabulary to the C#.
 */
export const CHECK_NAMES: readonly string[] = [
  'pain_reality',
  'value_durability',
  'incumbency',
  'payer_solvency',
  'distribution',
  'legality',
  'buyer_intent',
  'route_to_market',
  'currency',
  'claims_verifiable',
  'adversarial_decisive',
  'min_composite',
  'moat_ungrounded',
  'source_or_die',
];

// A check name reaches the catalogue field with its underscores already spaced out, so both
// spellings have to match. Longest first, so `payer_solvency` is never partly eaten by a
// shorter entry that happens to prefix it.
const LABEL_PREFIX = new RegExp(
  `^(?:${[...CHECK_NAMES]
    .sort((a, b) => b.length - a.length)
    .map((name) => name.replace(/_/g, '[_ ]'))
    .join('|')}):\\s*`,
  'i',
);

// Mirrors the inline constructs `plain_text.py` handles, in the same order: images before links
// (an image is a link with a leading `!`), links before emphasis (link text may itself be bold).
const INLINE: readonly [RegExp, string][] = [
  [/!\[([^\]]*)\]\([^)]*\)/g, '$1'],
  [/\[([^\]]+)\]\(([^)]*)\)/g, '$1'],
  [/`([^`]+)`/g, '$1'],
  [/\*\*\*([\s\S]+?)\*\*\*/g, '$1'],
  [/\*\*([\s\S]+?)\*\*/g, '$1'],
  [/(?<![\w*])\*(?!\s)([\s\S]+?)(?<!\s)\*(?![\w*])/g, '$1'],
  [/~~([\s\S]+?)~~/g, '$1'],
];

// Leading block markers: bullet, ordered-list and heading/quote marks.
const BLOCK_PREFIX = /^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d{1,3}[.)]\s+)/;

/**
 * Strip markup and a leading internal check name; return null when nothing usable is left.
 *
 * The null return is the point of the signature. `cleanProofPoint('') === null` rather than
 * `''`, so a caller cannot render an empty proof row by forgetting to check truthiness — the
 * failure mode would be a card that looks like it is citing something and is citing nothing.
 */
export function cleanProofPoint(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let text = String(raw);
  for (const [pattern, replacement] of INLINE) {
    // Repeat until stable: nested emphasis needs more than one pass.
    let previous: string | null = null;
    while (previous !== text) {
      previous = text;
      text = text.replace(pattern, replacement);
    }
  }
  text = text.replace(BLOCK_PREFIX, '');
  text = text.replace(LABEL_PREFIX, '');
  text = text.replace(/\s+/g, ' ').trim();
  // A label and nothing else ("value durability:") is not evidence.
  return text.length > 0 ? text : null;
}
