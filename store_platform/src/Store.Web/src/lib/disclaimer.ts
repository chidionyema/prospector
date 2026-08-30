/**
 * The honesty note, written once.
 *
 * WHY THIS EXISTS
 * ---------------
 * The same promise was typed out at four render sites in three different wordings, measured
 * 2026-08-15:
 *
 *   pages/how-it-works.tsx:385  "not a guarantee"
 *   components/checkout/BuyDrawer.tsx:184  "not a promise of business success"
 *   pages/pack/[id].tsx:523  "not a promise of business success"
 *   pages/pricing.tsx:156  "not a promise of outcome"
 *
 * This is the one sentence on the storefront that limits what is being sold, and it appears
 * immediately before the buy button on two of those four surfaces. A limitation stated in three
 * wordings is three limitations, and under the CPUTR/DMCCA reading the site already applies to
 * its own copy, the WEAKEST wording is the one a reader can hold us to. It also cannot be
 * amended safely: whoever edits it next will find three of the four and leave the fourth.
 *
 * So the sentence lives here and the surfaces import it. `PACK_DISCLAIMER` is the whole promise;
 * pages that need more (what IS done, what is not) compose from it rather than restating it.
 */

/**
 * The limit, in the wording that is hardest to read as a promise.
 *
 * "business success" over "outcome" and over the bare "guarantee": "outcome" is vague enough that
 * a reader can decide the outcome they had in mind is covered, and "not a guarantee" denies the
 * strength of the claim without denying its subject.
 */
/* voice.md bans the antithesis as a RHYTHM, and allows the negative where clearing a
   misconception is the point. Here the misconception is the whole job of the sentence, and the
   docblock above is why this exact wording and no shorter one. Hence the opt-out below. */
export const PACK_DISCLAIMER =
  'A pack is evidence-backed research, not a promise of business success.'; // tone-ok: the misconception IS the point

/** What the pack DOES do, for surfaces with room for the second half of the sentence. */
export const PACK_SCOPE = 'The finding, vetting and sourcing is done. The execution is yours.';
