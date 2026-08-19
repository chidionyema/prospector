import { COMMON_CHECKS, idsFor } from '@/lib/checks';

/**
 * Engine vocabulary, translated at the last moment before a buyer reads it.
 *
 * WHY THIS EXISTS
 * ---------------
 * The verdict prose on /kill-log, /how-it-works and /sample is written by the engine, for the
 * engine's own audit trail, and then rendered verbatim to a buyer. Measured 2026-08-15 across
 * `data/kill-log.json`, `data/kill-log-examples.json` and `data/sample-report.json`:
 *
 *   141 of 800 prose strings on /kill-log carry at least one internal term
 *     104  "the candidate" / "the candidate's" / "this candidate"
 *      32  a snake_case gate id (pain_reality, payer_solvency, min_composite, ...)
 *      30  "unverifiable"
 *      14  "source-or-die"
 *      11  "dossier"
 *      10  "verdict-from-retrieval-only"
 *      10  a bare KILL / PASS token
 *       8  "the hypothesis"
 *       5  a backtick code span
 *       1  "hard gate"
 *       1  "refutation threshold"
 *
 * One row printed all of it at once: "Every one of the six gates returned `unverifiable` ...
 * pain_reality: ... incumbency + payer_solvency: ... Publish-on-PASS is impossible; this is a
 * KILL." That is an internal dossier, published as the reason a buyer's idea died.
 *
 * WHY A RENDER-TIME TRANSLATION AND NOT A DATA FIX
 * -----------------------------------------------
 * `tools/make_kill_log.py` regenerates the JSON. Rewriting the 141 strings in place fixes the
 * corpus that exists and none of the corpus that comes next, and the founder's 2026-08-15 copy
 * pass ranks the generator LAST (sixth) precisely so the site can be fixed before the engine is.
 * So the translation lives on the read path, the source data keeps the engine's own words for
 * audit, and the guard runs over the corpus rather than over the pages.
 *
 * WHAT THIS DELIBERATELY DOES NOT TOUCH
 * ------------------------------------
 * Only substitutions that are mechanical AND meaning-preserving are in here. Four classes are
 * left alone on purpose, counted by `internalResidue()` and reported by
 * `plainEnglishCoverage.test.ts`, because paraphrasing them at render time would be authoring
 * evidence prose rather than translating vocabulary:
 *
 *   "unverifiable"                 -- a verdict, and defensible English; the public gloss the
 *                                     site already uses ("the evidence would not settle it") is a
 *                                     clause, not a word, and does not substitute grammatically.
 *   "source-or-die"                -- the name of a policy, load-bearing in the sentences it
 *   "verdict-from-retrieval-only"     appears in; a paraphrase changes what is being asserted.
 *   a bare KILL / PASS token       -- a verdict token whose replacement depends on the sentence
 *                                     around it ("this is a KILL" vs "Publish-on-PASS").
 *
 * Those need a copy decision or the generator, not a regex. The guard pins their counts so they
 * can only go down.
 */

/**
 * The gate-id map is DERIVED from `COMMON_CHECKS`, never typed out here.
 *
 * A second hand-written list of gate ids is exactly how one gate ended up with three different
 * public names (see the note at the top of `pages/how-it-works.tsx`). `idsFor` already returns
 * the id plus its aliases, so `route_to_market` is picked up without this file knowing that it is
 * the same check as `distribution`.
 *
 * ONLY IDS THAT CONTAIN AN UNDERSCORE, AND THE REPLACEMENT IS THE DE-UNDERSCORED WORDS.
 * Two corrections forced by measuring the corpus rather than reasoning about it:
 *
 * 1. Two ids -- `distribution` and `legality` -- are also ordinary English, and in this corpus
 *    they are ONLY ever ordinary English: 38 and 17 occurrences, every one a noun in a sentence
 *    ("bread/bakery distribution dominated by a few large manufacturers", "the legality of
 *    scraping school websites"). Substituting a check name for the word produced "bread/bakery A
 *    route to the buyer dominated by ...". A translation that corrupts the sentence is worse than
 *    the jargon it removes, so those two are left alone; they already read as English. Only the
 *    snake_case form, which cannot be anything but an identifier, is touched.
 *
 *    `incumbency` is NOT one of them, and grouping it with them was an over-generalisation
 *    corrected by the founder on 2026-08-15. Its 24 occurrences were then read one by one: all
 *    but two are the gate word standing in for the check itself -- "Incumbency queries found no
 *    existing competitor", "Incumbency checks failed to find", "(2) INCUMBENCY, Verisk already
 *    ...", "incumbency + payer_solvency:". It is banned outright by the guard and handled in
 *    RULES below, because it is jargon wearing an English suffix, not an English word.
 *
 * 2. The replacement is `payer solvency`, not the check's title-case `name`. The ids appear
 *    mid-clause, not as labels -- "the payer_solvency check returned no supporting evidence",
 *    "payer_solvency and pain_reality returned unverifiable" -- and splicing a name in gives "the
 *    A payer who can pay check returned". The engine already writes the de-underscored form
 *    elsewhere in this same corpus ("value durability, incumbency, payer solvency, distribution,
 *    legality, pain reality"), so this is the corpus's own phrasing, not a coined one. That is
 *    the opposite case to `LiveKillCard`, where de-underscoring was wrong because the slot was a
 *    LABEL and a canonical verdict label already existed for it.
 *
 * Ids with no entry in `COMMON_CHECKS` -- `min_composite`, `moat_ungrounded`,
 * `adversarial_decisive`, `claims_verifiable`, `buyer_intent`, `currency` -- are NOT given a
 * gloss here. Inventing a public name for a check the site does not otherwise name is how a
 * fourth lexicon starts. Any that appear stay in the residue count until someone names them once,
 * in `checks.ts`, where every surface will pick the name up at the same time.
 *
 * Measured after translation, none of those six actually reach a reader today: the 17 snake_case
 * tokens left in the corpus are lane and segment tags the generator drops into prose whole --
 * `commodity_premortem` (5), `proprietary_data` (4), `why_now` (3), `squeezed_middle` (2),
 * `technical_ip`, `who_pays`, `primary_carers`. Same objection, different vocabulary: each needs
 * a name a human chose, so they are counted rather than guessed at.
 */
const GATE_WORDS: ReadonlyArray<readonly [string, string]> = COMMON_CHECKS.flatMap((check) =>
  idsFor(check)
    .filter((id) => id.includes('_'))
    .map((id) => [id, id.replace(/_/g, ' ')] as const),
);

type Rule = { readonly pattern: RegExp; readonly replace: string; readonly why: string };

/**
 * Order is load-bearing: the longest form of a phrase has to match before its prefix does, or
 * "the candidate's" is rewritten to "the idea's" only after "the candidate" has already eaten the
 * first three words and left a stray apostrophe-s behind.
 */
const RULES: readonly Rule[] = [
  {
    pattern: /\bthe candidate's\b/g,
    replace: "the idea's",
    why: '"candidate" is what the engine calls the thing under review; a buyer calls it the idea',
  },
  { pattern: /\bThe candidate's\b/g, replace: "The idea's", why: 'sentence-initial form' },
  { pattern: /\bthis candidate\b/g, replace: 'this idea', why: 'as above' },
  { pattern: /\bThis candidate\b/g, replace: 'This idea', why: 'sentence-initial form' },
  { pattern: /\bthe candidate\b/g, replace: 'the idea', why: 'as above' },
  { pattern: /\bThe candidate\b/g, replace: 'The idea', why: 'sentence-initial form' },

  {
    pattern: /\bthe hypothesis\b/g,
    replace: 'the idea',
    why: 'the engine calls the unproven claim a hypothesis; the site calls it the idea throughout',
  },
  { pattern: /\bThe hypothesis\b/g, replace: 'The idea', why: 'sentence-initial form' },

  {
    pattern: /\bdossiers\b/g,
    replace: 'evidence records',
    why: '"evidence record" is the name /how-it-works and /sample already use for the same document',
  },
  { pattern: /\bdossier\b/g, replace: 'evidence record', why: 'as above' },
  { pattern: /\bDossiers\b/g, replace: 'Evidence records', why: 'sentence-initial form' },
  { pattern: /\bDossier\b/g, replace: 'Evidence record', why: 'sentence-initial form' },

  /**
   * UPDATED 2026-08-16: the replacement itself is now banned. "Incumbent" is a consultant's word
   * for "the companies already selling this", and the founder banned it in reader-facing copy, so
   * a substitution that produced "incumbent competition" was translating one piece of jargon into
   * another. `incumbency` now becomes `existing competition`, which fills the same noun slot.
   *
   * The plural noun is substituted too, because model prose writes it directly and no guard over
   * our own source can reach that. The BARE SINGULAR is deliberately mapped to a noun phrase and
   * not to an adjective: "incumbent" appears in both slots and one replacement cannot serve both.
   * The one adjectival use on the site ("the incumbent tooling is old") was hand-written copy in
   * `lib/seo/landings.ts` and was edited directly rather than left to this table.
   *
   * The historical note below is kept because it records what was measured against the corpus.
   *
   * `incumbency` -> `incumbent competition`. Three cased forms rather than an `i` flag, because
   * the corpus writes all three ("Incumbency queries", "(2) INCUMBENCY,") and a case-insensitive
   * replace would print lowercase mid-heading.
   *
   * WHY THIS WORDING AND NOT THE CHECK'S OWN NAME. Both candidates were rendered against all 24
   * occurrences before choosing. The check is called "Room past the incumbents", which is phrased
   * as the thing that must be TRUE, and that phrasing does not survive substitution into a noun
   * slot: "that is dominant, well-resourced room past the incumbents over the ... segment",
   * "the standard for refuting room past the incumbents", "Room past the incumbents queries found
   * no existing competitor". Six of 24 came out ungrammatical. "incumbent competition" is a noun
   * where the original is a noun, so it reads in 23 of 24; the exception is "not open for a new
   * entrant to claim incumbency", which is opaque in the source too.
   *
   * `incumbencies` is deliberately NOT handled. It does not occur today, and the guard bans both
   * forms, so a regeneration that introduces the plural fails the build naming it rather than
   * being silently half-translated.
   */
  { pattern: /\bincumbency\b/g, replace: 'existing competition', why: 'the gate word, not English' },
  { pattern: /\bIncumbency\b/g, replace: 'Existing competition', why: 'sentence-initial form' },
  { pattern: /\bINCUMBENCY\b/g, replace: 'EXISTING COMPETITION', why: 'the corpus shouts headings' },
  { pattern: /\bincumbents\b/g, replace: 'established competitors', why: 'banned word, plural noun' },
  { pattern: /\bIncumbents\b/g, replace: 'Established competitors', why: 'sentence-initial form' },
  { pattern: /\bincumbent\b/g, replace: 'established competitor', why: 'banned word, singular noun' },
  { pattern: /\bIncumbent\b/g, replace: 'Established competitor', why: 'sentence-initial form' },

  {
    pattern: /\bhard gates?\b/gi,
    replace: 'check that can kill on its own',
    why: '"hard gate" names the kill-fast property; the property is the readable part, not the noun',
  },
  {
    pattern: /\brefutation threshold\b/gi,
    replace: 'bar for calling it refuted',
    why: 'a scoring term; the bar is what the sentence is actually about',
  },

  {
    // Backticks are markdown the renderer never interprets: `unverifiable` reaches the page with
    // its quotes still on, reading as a typo rather than as emphasis. The site renders NO markdown
    // (see storefrontRendersNoMarkdown), so stripping is the only correct handling.
    pattern: /`/g,
    replace: '',
    why: 'the site renders no markdown, so a code span ships its own backticks as literal text',
  },
];

/** The classes deliberately left in place. Counted, never rewritten -- see the docblock. */
const RESIDUE: ReadonlyArray<readonly [string, RegExp]> = [
  ['unverifiable', /\bunverifiable\b/gi],
  ['source-or-die', /\bsource-or-die\b/gi],
  ['verdict-from-retrieval-only', /\bverdict-from-retrieval-only\b/gi],
  ['bare KILL/PASS token', /\b(?:KILL|PASS)\b/g],
  // Named for what it MATCHES, not for what it was expected to catch. It was called "unnamed gate
  // id" until the count was actually run: every gate id in the corpus is translated by GATE_NAMES
  // above, and what survives is a different class entirely -- lane and segment tags. A residue
  // label that describes the wrong thing sends the next reader looking for a defect that is not
  // there, and hides the one that is.
  ['snake_case identifier', /\b[a-z]+(?:_[a-z]+)+\b/g],
];

/**
 * Translate one string of engine prose into the site's own vocabulary.
 *
 * Idempotent by construction: every replacement's output is outside its own pattern, so running
 * it twice is the same as running it once. That matters because the same `reason` is rendered by
 * `/kill-log` and again, truncated, by `/how-it-works` through `firstSentences`.
 */
export function plainEnglish(text: string): string {
  if (!text) return text;
  let out = text;
  for (const [id, words] of GATE_WORDS) {
    // Word-boundaried so a URL path segment or a longer identifier that merely contains the id is
    // left intact.
    out = out.replace(new RegExp(`\\b${id}\\b`, 'g'), words);
  }
  for (const { pattern, replace } of RULES) {
    out = out.replace(pattern, replace);
  }
  return out;
}

/** What `plainEnglish` knowingly leaves behind, as `{term: count}`. Used by the guard. */
export function internalResidue(text: string): Record<string, number> {
  const found: Record<string, number> = {};
  for (const [label, pattern] of RESIDUE) {
    const n = (text.match(pattern) ?? []).length;
    if (n) found[label] = n;
  }
  return found;
}
