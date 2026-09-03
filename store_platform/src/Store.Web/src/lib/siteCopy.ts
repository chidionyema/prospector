/**
 * ONE COPY SOURCE. Founder's spec, 2026-08-18, PART 2 step 5: "every string that appears on more
 * than one page comes from a constants file, not from the template."
 *
 * WHY A FILE AND NOT A GREP. One CTA was live on five pages in three different wordings at once,
 * and the divergence was invisible from any one of them: the hero link ended in "no email
 * needed", the pack rail ended in "first", and /faq and /ideas ended after "free", one of
 * them with a trailing arrow. Nobody chose that. It is what happens when a CTA is typed at the
 * call site.
 *
 * WHY THE SAMPLE LINK IS THREE SLOTS AND NOT ONE STRING. The mockups deliberately say different
 * things in different places -- `mockups/index.html` ends the hero link with "no email needed",
 * `mockups/pack-detail.html:529` ends the rail link with "first" -- and the governing rule is
 * that the mockup's sentence wins ("if you find yourself composing a sentence, you have already
 * made a mistake"). So each slot names its drawing. What this file removes is a FOURTH wording
 * appearing because someone typed it, not the three the drawings actually specify.
 *
 * WHAT IS DELIBERATELY NOT HERE.
 *   - The six check names live in `lib/checks.ts` (`COMMON_CHECKS`), which is already the single
 *     source and is consumed by /how-it-works, /kill-log, the specimen and the lexicon test.
 *     Copying them here would create the second source this file exists to prevent.
 *   - The proof-line format lives in `components/ui/ProofLine.tsx`, which is a component rather
 *     than a string: D4 asks for one component sitewide, and it renders `41 sources` or
 *     `17x payback · 28 sources` from data.
 *   - Variant-keyed marketing copy lives in `lib/copyConfig.ts`, keyed a/b/c. Nothing here is
 *     variant-keyed: these are the strings that are the same for every reader, by specification.
 */

export const SITE_COPY = {
  /**
   * D2, a BLOCKER in the founder's fix prompt: the home page H1 is this sentence exactly, with
   * the full stop. `mockups/index.html`. `.verify.mjs` asserts the rendered page equals it.
   */
  heroH1: 'Business ideas with the research already done.',

  /* WHAT THESE THREE MAY CLAIM, AND WHY.
     Every one of them read "a full pack free" until 2026-08-21. /sample stopped being a full
     pack on 2026-08-15, when the founder settled it as a true excerpt: `data/sample-report.json`
     ships `sectionsShown: 3` against `sectionsTotal: 14`, and names the other eleven in
     `withheld`. `pages/sample.tsx` was rewritten that day and its own headline says so -- "The
     opening of a real pack, in full." The three links INTO the page were not rewritten, so
     every route to the sample promised fourteen sections and delivered three, and the break
     landed on the first click a stranger makes.
     `__tests__/sampleOfferIsTrue.test.ts` reads the fixture and fails if any string here claims
     a whole pack while the fixture withholds one. Widen the sample and the test lets the claim
     back in by itself. */
  /**
   * D6: an em dash, no trailing full stop, and the arrow removed so the line cannot wrap onto a
   * glyph of its own at 390px. `mockups/index.html`.
   * The `dash-free-ignore` pragma must sit on the same line as the character it exempts
   * (`src/__tests__/dashFree.test.ts:68` tests `line.includes(IGNORE)`).
   */
  /* dash-free-ignore */ sampleLinkHero: 'Read a pack free',

  /** `mockups/pack-detail.html:529`, the buy rail's link under the button. */
  sampleLinkPanel: 'Read the opening of a real pack free first',

  /** Every other entry point: /faq, /ideas, the pack page's mobile bar. */
  sampleLink: 'Read the opening of a real pack, free',
} as const;
