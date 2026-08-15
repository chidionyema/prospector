import type { Pack } from '@/lib/api/client';
import { paybackEquation } from '@/lib/payback';

/**
 * THE ONE NUMBER A PACK CARD LEADS WITH.
 *
 * WHY THIS EXISTS. The shelf's cards read as empty. The site's rule is "every visual is earned"
 * (docs/SITE_SPEC_PROGRAM.md:28), and the answer built for it was a mark computed by hashing the
 * pack id -- a drawing that encodes nothing about the pack. The rule was obeyed and the meaning
 * was lost; the 112px plate carrying that mark was removed on 2026-08-14 and the cards were left
 * honest and visually dead. The replacement is not a picture: it is the pack's own strongest
 * number, set as type. A figure large enough to be the card's visual is a genuine visual, and a
 * figure the engine already computed is unarguably earned.
 *
 * THE PRIORITY ORDER, and why each rung is where it is. Exactly one rung renders per pack; a rung
 * that cannot be stated honestly falls through to the next one.
 *
 *  1. THE MODELLED PRICE MULTIPLE -- `paybackEquation(pack.price, pack.financialSnapshot)`.
 *     Month-1 revenue divided by the price on the same card, from the engine's own financial
 *     model. Measured over the live catalogue on 2026-08-15 (all 59 listed packs): 55 carry a
 *     `financialSnapshot`, 37 of those carry a readable `month1Revenue`, and 36 of those clear
 *     their own price. Of that 36 the multiples were
 *       2 2 3 3 4 5 6 6 6 6 7 7 7 8 8 9 9 9 9 10 12 12 13 13 14 16 17 17 | 21 22 25 30 45 76 89 123
 *     -- median 9x, p75 17x. The bar marks `CREDIBLE_MULTIPLE_CEILING` (lib/payback.ts:80, where
 *     the reasoning for 20 lives): 28 render here, and the 8 above it fall through to rung 2
 *     rather than printing a clamped "20x+", which would make the same claim less precisely and
 *     invite the reader to wonder what was capped. Nothing is hidden by that -- `pack/[id].tsx`
 *     is governed by the SAME bound, and the "Modelled economics" box on that page still carries
 *     the underlying revenue figure, in context and at reading size.
 *
 *     IT IS THE RATIO AND NOT THE MONEY, DELIBERATELY, AND THIS IS A FOUNDER DECISION ALREADY ON
 *     RECORD. The obvious lead is the raw figure -- "£1,300 in month one" -- and that exact
 *     rendering was DELETED from the buy box on 2026-08-13: "a modelled LTV:CAC of 30.7x and a
 *     Month 1 revenue of £1,152 contradict the homepage's 'no invented revenue' promise, and read
 *     as fantasy to anyone who has operated" (pages/pack/[id].tsx:440-447). These figures are
 *     modelled, not sourced -- `_render_financial_model` receives the claims list and never reads
 *     it, so no input behind them carries a citation (lib/payback.ts:9-11). Printing the money
 *     figure at display size on 62 cards would reverse that decision at six times the type size,
 *     on the shelf rather than in a rail. The ratio is the one form that survived every objection
 *     the deletion raised: it is a comparison to the price on the same card rather than a revenue
 *     promise, it is currency-invariant, it invents nothing but the division, and
 *     `paybackEquation` returns null rather than a multiple below 1, so it cannot become a widget
 *     that appears only when the numbers flatter. The word "modelled" travels with it in the
 *     label, which is the same attribution the pack page makes in prose ("The pack's own model
 *     puts month one at 24x what the pack costs").
 *
 *  2. THE CITED SOURCE COUNT -- `pack.sourceCount`, the floor. Populated on 62 of 62 live packs
 *     (range 17-51, measured 2026-08-14), and the only number on the shelf payload that is a
 *     fact about the research rather than a model of the business. So it is the rung that can
 *     never leave a card blank, and it is also the number this shop's whole pitch rests on.
 *
 * WHAT IS DELIBERATELY NOT IN THE LADDER:
 *
 *  - `ltvCac` ("30.7x"). Named in the 2026-08-13 deletion as the specific figure that reads as
 *    fantasy, and it is a ratio of two modelled quantities with no reference point on the card.
 *  - `paybackMonths` ("1 months", verbatim from the engine on 10 of the first 20 packs sampled).
 *    It is the same model as rung 1 and would contradict it in exactly the case rung 1 refuses:
 *    a pack whose modelled month one does not cover its own price cannot honestly lead with a
 *    one-month payback.
 *  - `price`. Already set large on every card. A card cannot lead with the number it also closes
 *    with, and doing so would print one fact twice and no second fact at all.
 *
 * The result is a function of the pack and nothing else -- no hash of the id, no `Math.random`,
 * no dependence on what else is on the shelf -- so a buyer returning to the shelf finds the same
 * card showing the same number. That is the determinism rule the deleted cover carried, kept.
 */

export type PackStatKind = 'price_multiple' | 'sources';

export interface PackLeadStat {
  /** Which rung of the ladder produced this. The card uses it to avoid stating the same fact
   *  twice (the evidence bar drops its numeral when the lead figure IS the source count). */
  kind: PackStatKind;
  /** The figure itself, ready to set as type. Short by construction: "24x", "34". */
  figure: string;
  /** What the figure IS, in the buyer's words rather than the engine's. Never a field name. */
  label: string;
}

export function packLeadStat(pack: Pack): PackLeadStat | null {
  // Rung 1. `pack.price` and not the FX-converted display price: both operands are the pack's
  // own GBP, and a ratio taken across two currencies would be a different number every time the
  // rate moved. The ratio is currency-invariant, which is why it is safe on a shelf that renders
  // prices in the reader's money.
  //
  // No ceiling check here on purpose: `paybackEquation` refuses a multiple above
  // `CREDIBLE_MULTIPLE_CEILING` at the source, so the shelf and the pack page cannot disagree
  // about which claims this shop will make. A rung that re-checked it here would be a second
  // ceiling to keep in step with the first.
  const payback = paybackEquation(pack.price, pack.financialSnapshot);
  if (payback) {
    return {
      kind: 'price_multiple',
      figure: `${payback.multiple}×`,
      label: 'the price back in month one, modelled',
    };
  }

  // Rung 2, the floor.
  const sources = pack.sourceCount;
  if (typeof sources === 'number' && sources > 0) {
    return {
      kind: 'sources',
      figure: String(sources),
      label: sources === 1 ? 'cited source behind it' : 'cited sources behind it',
    };
  }

  // A pack carrying no number at all renders NO figure -- not a zero, not an em dash. The same
  // rule `EvidenceBar` states: an empty evidence figure on a product whose pitch is evidence
  // says "we checked and found none", when the truth is "this field is absent". No live pack is
  // in this state (62/62 carry a source count); the branch exists so that one never can be.
  return null;
}
