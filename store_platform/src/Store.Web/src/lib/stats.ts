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

/**
 * THE SURVIVOR COUNT IS NOT EXPORTED, AND THAT IS THE POINT.
 *
 * FOUNDER DIRECTIVE, 2026-08-13: "saying 80 when only 50 are listed should never happen regardless
 * of the reasons why survivors are unlisted."
 *
 * 80 ideas cleared the gates; 50 are on the shelf. Every attempt to print the 80 turned into a
 * problem the copy then had to solve: first the site printed both numbers 600px apart and
 * reconciled neither, then it explained the gap in prose ("50 are packaged and listed so far"),
 * then it explained the whole partition. All three were us volunteering our packaging backlog to
 * a buyer who never asked, to defend a figure we chose to print.
 *
 * So the figure is gone. `totals.passed` survives here as an ADDEND for `researched` and nothing
 * else: no export carries it, so no page can print it, and tsc fails on any attempt. What ships is
 * three facts a visitor can check: how many ideas we researched, how many we killed, and how many
 * packs are on the shelf right now (that last one is live, read from /catalog at request time, and
 * has no business being in this module -- see the note below).
 *
 * This is not a presentation trick. A reader who subtracts 1,364 from 1,444 gets 80, and 80 ideas
 * did clear the gates. The difference is that we no longer make a claim we cannot point at.
 */
export const RESEARCH_STATS = {
  /** Ideas the filter rejected, over all time. */
  killed: totals.killed,
  /** Ideas researched. An invariant (killed + cleared), never a typed-in number. */
  researched: researchedTotal,
  /** Kills published on /kill-log. Far smaller than `killed`, and the page must say so. */
  publishedKills: totals.shown,
  /**
   * THE KILL RATE, WITH A DECIMAL, AND IT IS THE ONLY RATE HERE.
   *
   * A whole percent fails the one check a sceptic actually performs, which is to multiply it back.
   * The home page shipped "1,444 ideas researched. 80 survived. That's a 6% pass rate." and 6% of
   * 1,444 is 87, not 80. The rounding was correct (5.54% -> 6%); the printed figure was still one
   * the reader could not reproduce from the two counts beside it, on the page whose entire argument
   * is that our arithmetic checks out. The kill side had it too: 94% of 1,444 is 1,357, not 1,364,
   * a seven-idea gap stated three times across the site.
   *
   * `passRateLabel` went with the survivor count, for the same reason: a pass rate IS the survivor
   * count in another form (5.5% of 1,444 is the 80 we do not claim). One decimal place is what
   * makes this figure reproducible from `killed` and `researched`, and
   * `numbersReconcile.test.ts` pins that PROPERTY -- the rate lands within one idea of the count
   * beside it -- never the digits, so a regeneration cannot silently break it.
   */
  rejectRateLabel: `${((totals.killed / researchedTotal) * 100).toFixed(1)}%`,
  /**
   * THE SAME RATE FROM THE SURVIVOR END, AS A BOUND, NEVER AS A COUNT.
   *
   * The pack page led with "94.5% killed on evidence" and then had to add a sentence turning it
   * round ("This one came through the filter"). The docblock above that plate already argued that
   * only the survivor reading is an argument for buying, and then printed the kill reading anyway.
   * So the page now leads with the survivor reading.
   *
   * IT IS A BOUND, AND THAT IS WHAT KEEPS THE 2026-08-13 DIRECTIVE INTACT. `passRateLabel` was
   * deleted with the survivor count because a pass rate to one decimal IS the survivor count in
   * another form: 5.5% of 1,444 is the 80 we do not claim. Rounding UP to a whole percent breaks
   * that: 6 in 100 of 1,444 is 87, which is not a count of anything and cannot be read as one.
   * The claim stays true in the direction that matters -- the real rate is below the bound, so
   * "fewer than 6 in 100 get through" is honest at any regeneration that does not double the
   * pass rate.
   *
   * Derived from `killed / researched` like every other figure here, so it cannot drift from
   * `rejectRateLabel` sitting two lines above it.
   */
  survivorBoundLabel: `${Math.ceil(100 - (totals.killed / researchedTotal) * 100)} in 100`,
} as const;

/**
 * The kill side of the same partition, in one clause, CARRYING NO COUNTS.
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
 * THE FIX IS SUBTRACTION, NOT A BETTER SENTENCE. The first repair stated every denominator inline
 * ("The remaining 1,364 of 1,444 were killed, and 400 of those kills are published..."), which was
 * arithmetically true and, per the founder on 2026-08-13, three numbers a visitor never asked for
 * on the way to a buy button. A clause with no counts in it cannot contradict the totals above it,
 * cannot mis-bind "the other", and cannot go stale when `make_kill_log.py` runs. The sceptic who
 * wants the partition gets it on /kill-log, which states its own scope in full and is one click
 * away. Callers supply the punctuation: this returns a CLAUSE, not a sentence.
 */
export function killsSummary(): string {
  return 'We publish the ones that didn\'t pass too, with the reason each one failed';
}
