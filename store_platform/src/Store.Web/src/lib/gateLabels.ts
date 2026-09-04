/**
 * The buyer-facing name of every kill gate, in one place.
 *
 * There were two maps. `killLog.server.ts` carried the full sentences the kill log prints
 * ("Scored below the bar overall"), and `components/marketing/EvidenceBands.tsx` carried a set of
 * one-word shorthands written to fit six of them on one line ("Ungrounded", "Durability",
 * "Affordability"). A reader met both on the same visit and they named the same six causes of
 * death differently, which on a site whose pitch is "every kill is published with its reason" is
 * the reason being published twice, two ways.
 *
 * A check is a question about the IDEA; a stage is something the PROCESS did. Both names below
 * are written so the difference survives the label: `min_composite` says "scored below the bar",
 * which is a fact about our own threshold, not a finding about the market.
 *
 * Fallback is the caller's job: a gate with no entry here is a gate the engine added since, and
 * printing its raw key with underscores is a visible bug rather than a silent one.
 */
export const GATE_LABELS: Record<string, string> = {
  min_composite: 'Did not score high enough to be viable',
  incumbency: 'Too much existing competition',
  moat_ungrounded: 'No proof the business could protect against copycats',
  adversarial_decisive: 'Failed our second round of deep research',
  value_durability: 'The value to the customer would not last',
  payer_solvency: 'The target buyer lacks the budget',
  source_or_die: 'Its own claims could not be sourced',
  legality: 'There is a legal landmine',
  route_to_market: 'There is no route to the buyer',
  pain_reality: 'The pain is not real enough to pay for',
  currency: 'The evidence behind it is out of date',
  distribution: 'There is no route to the buyer',
  buyer_intent: 'No sign anyone is trying to buy it',
};

export function gateLabel(gate: string): string {
  return GATE_LABELS[gate] ?? gate.replace(/_/g, ' ');
}
