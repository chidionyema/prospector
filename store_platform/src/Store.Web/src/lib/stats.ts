import killTotals from '@/data/kill-log-totals.json';

/**
 * The research counters, derived once, so the site cannot contradict itself about its own numbers.
 *
 * WHY THIS EXISTS
 * ---------------
 * Seven files imported `kill-log-totals.json` directly and each re-derived what the numbers
 * MEANT. They disagreed. Measured against the live site on 2026-08-06:
 *
 *   /kill-log meta:  "We researched 1168 business ideas and rejected 89%"
 *   /how-it-works:   "Of 1,313 ideas researched, 145 survived"
 *
 * Both read the same JSON. 1,168 is the KILL count; researched is killed + passed = 1,313. The
 * rejection rate was right (1168/1313 = 89%) while the noun in front of it was wrong, so the one
 * page whose entire job is to prove we do not invent numbers was inventing one.
 *
 * On a storefront selling epistemic rigour an internal contradiction costs more than it would
 * anywhere else: a sceptic who finds two of our numbers disagreeing has no reason to trust the
 * forty-three inside the pack. So `researched` is an INVARIANT here (killed + survived), never a
 * literal, and every page reads these names rather than doing its own arithmetic on the JSON.
 *
 * WHAT IS AND IS NOT IN HERE
 * --------------------------
 * These three are historical totals over every dossier the engine ever wrote, so a build-time
 * snapshot is the right shape. `published` is NOT in here and must never be added: the number of
 * packs on the shelf changes when a pack is listed, with no redeploy, so it is only ever correct
 * when read from the live `/catalog` at request time. That exact drift already shipped once,
 * "61 live now" and "60 live now" on a single scroll (see TrustGuaranteesRow.tsx).
 *
 * Regenerate the underlying JSON with `python tools/make_kill_log.py`.
 */
const totals = killTotals as { killed: number; passed: number; shown: number };

const researchedTotal = totals.killed + totals.passed;

export const RESEARCH_STATS = {
  /** Ideas the filter rejected, over all time. */
  killed: totals.killed,
  /** Ideas that cleared every hard gate. NOT the same as the number on sale, see `published`. */
  survived: totals.passed,
  /** Ideas researched. An invariant, never a typed-in number. */
  researched: researchedTotal,
  /** Kills published on /kill-log. Far smaller than `killed`, and the page must say so. */
  publishedKills: totals.shown,
  /**
   * THE RATES CARRY A DECIMAL, AND THAT IS THE WHOLE POINT OF THESE TWO FIELDS.
   *
   * A whole percent fails the one check a sceptic actually performs, which is to multiply it back.
   * The home page shipped "1,444 ideas researched. 80 survived. That's a 6% pass rate." and 6% of
   * 1,444 is 87, not 80. The rounding was correct (5.54% -> 6%); the printed figure was still one
   * the reader could not reproduce from the two counts sitting beside it, on the page whose entire
   * argument is that our arithmetic checks out. The kill side had it too: 94% of 1,444 is 1,357,
   * not 1,364, a seven-idea gap stated three times across the site.
   *
   * Both survive as their own derivation rather than one being `100 - other`: they sum to 100 here,
   * but subtracting a rounded number is how a page ends up a point out the first time the totals
   * move. `numbersReconcile.test.ts` pins the PROPERTY (the rate must reproduce the count beside it
   * to within one idea), never the digits, so a regeneration cannot silently break it.
   *
   * These are pre-formatted strings, and the whole-percent numbers they replaced are deliberately
   * GONE rather than kept alongside: a page reaching for the unreproducible figure was not a
   * hypothetical, it was five call sites.
   */
  passRateLabel: `${((totals.passed / researchedTotal) * 100).toFixed(1)}%`,
  rejectRateLabel: `${((totals.killed / researchedTotal) * 100).toFixed(1)}%`,
} as const;

/**
 * How many survivors are actually buyable, phrased so the gap is stated rather than hidden.
 *
 * 83 ideas survived; 63 are listed. Every page that said "browse the survivors" landed the reader
 * on a smaller grid and left them to notice the shortfall themselves. Naming the gap is both
 * truer and more on-brand than quietly printing the smaller number.
 *
 * The wording says what each number MEANS, not just that they differ: one is a verdict ("survived
 * the checks"), the other is a state of packaging ("packaged and listed so far"). The site printed
 * both figures on the same scroll and never once reconciled them, which reads to a sceptic as an
 * arithmetic error on the one site claiming it checks its arithmetic.
 *
 * Do not write either figure into copy. Both move: re-vetting the backlog on 2026-08-06 turned 62
 * former passes into kills, taking survivors 145 -> 83 in one regeneration, while `listed` changes
 * with no redeploy at all.
 *
 * `listed` comes from the live catalogue. Callers that have no catalogue to hand pass nothing and
 * get the survivor count alone, which is stale-proof because it is a historical total.
 */
export function survivorsSummary(listed?: number): string {
  const { survived } = RESEARCH_STATS;
  if (typeof listed !== 'number' || listed <= 0 || listed >= survived) {
    return `${survived.toLocaleString('en-GB')} survived the checks`;
  }
  return `${survived.toLocaleString('en-GB')} survived the checks; ${listed.toLocaleString('en-GB')} are packaged and listed so far`;
}

/**
 * The kill side of the same partition, in one clause, because the home page got it wrong twice at
 * once and the founder had to be the one to notice.
 *
 * WHAT SHIPPED, live on 2026-08-13, one paragraph under "1,444 ideas researched. 80 survived.":
 *
 *   "80 survived the checks; 50 are packaged and listed so far.
 *    The other 1,364 are published, each with the evidence that killed it."
 *
 * Two falsehoods in fourteen words:
 *
 * 1. "The other" attaches to the nearest number, which is 50. So the sentence asserts a partition
 *    of 50 + 1,364 = 1,414 against a total of 1,444 printed one line above it, quietly losing the
 *    30 survivors that are not packaged yet. The antecedent it needed was 80, four words further
 *    back, and English will not reach that far.
 *
 * 2. 1,364 kills are NOT published. 400 are. That is `totals.shown`, it is what /kill-log itself
 *    says one click away ("This page publishes 400 of those kills, not all 1,364"), and it is what
 *    the field comment on `publishedKills` above has warned about since the day it was written.
 *    The home page contradicted the kill log about a number both read from the same JSON.
 *
 * So this clause states its own denominator instead of trusting "other" to point somewhere, and the
 * only count it will ever place next to the word "published" is `publishedKills`. Callers supply
 * the punctuation, as with `survivorsSummary`.
 */
export function killsSummary(): string {
  const { killed, researched, publishedKills } = RESEARCH_STATS;
  return (
    `The remaining ${killed.toLocaleString('en-GB')} of ${researched.toLocaleString('en-GB')} ` +
    `were killed, and ${publishedKills.toLocaleString('en-GB')} of those kills are published ` +
    `with the evidence that killed them`
  );
}
