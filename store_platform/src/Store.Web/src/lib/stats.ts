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

export const RESEARCH_STATS = {
  /** Ideas the filter rejected, over all time. */
  killed: totals.killed,
  /** Ideas that cleared every hard gate. NOT the same as the number on sale, see `published`. */
  survived: totals.passed,
  /** Ideas researched. An invariant, never a typed-in number. */
  researched: totals.killed + totals.passed,
  /** Kills published on /kill-log. Far smaller than `killed`, and the page must say so. */
  publishedKills: totals.shown,
  /** Whole percent, rounded once, here. Pages that re-rounded this drifted by a point. */
  rejectRate: Math.round((totals.killed / (totals.killed + totals.passed)) * 100),
  /**
   * The share that CLEARED every gate, as a whole percent, rounded once for the same reason.
   *
   * It exists because there was no survival figure to read, so pages filling a sentence about
   * survival reached for `rejectRate` and printed its inverse. On 2026-08-08 `how-it-works.tsx`
   * rendered "94% survive" two lines under "1,444 ideas in. 80 out.", and the home page rendered
   * "80 survived. That's 94%.", which attaches the kill rate to the survivor count. Both read as
   * the filter passing almost everything, when it kills almost everything.
   *
   * Kept as its own rounded figure rather than `100 - rejectRate`: the two are derived from the
   * same totals, so they sum to 100 here, but subtracting a rounded number is how a page ends up
   * a point out the first time the totals move.
   */
  passRate: Math.round((totals.passed / (totals.killed + totals.passed)) * 100),
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
