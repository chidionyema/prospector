import { describe, expect, it } from 'vitest';

import type { Pack } from '../api/client';
import { packLeadStat } from '../packStat';

/**
 * The ceiling on the lead multiple.
 *
 * Founder, 2026-08-15, looking at the live shelf: "123x is the number that makes a buyer distrust
 * the other 58 cards. exactly." The defect was never the arithmetic -- month-1 revenue over price
 * is an exact division of two numbers the engine already published -- it was that an implausible
 * figure set at display size does not fail alone. It reprices every credible 6x beside it as
 * marketing, on the one shop whose entire pitch is that claims are checked.
 *
 * These cases pin the behaviour rather than the constant: a card at or under the ceiling still
 * leads with its multiple, a card above it falls THROUGH to the cited-source count instead of
 * rendering a clamped "20x+" (which would make the same claim less precisely), and the fallback
 * is a real number rather than an empty card.
 */
function packWith(pricePounds: number, month1Revenue: string | undefined, sourceCount: number): Pack {
  return {
    price: pricePounds.toFixed(2),
    sourceCount,
    financialSnapshot: month1Revenue === undefined ? undefined : { month1Revenue },
  } as unknown as Pack;
}

describe('the lead multiple has a ceiling', () => {
  it('leads with the multiple at the ceiling exactly', () => {
    // 49.99 x 20 = 999.80. The boundary is inclusive, and a strict `<` here would quietly
    // exempt the exact case the constant names.
    const stat = packLeadStat(packWith(49.99, '£999.80', 31));
    expect(stat).toEqual({
      kind: 'price_multiple',
      figure: '20× first-year return',
      label: '',
    });
  });

  it('falls through to cited sources one step above the ceiling', () => {
    const stat = packLeadStat(packWith(49.99, '£1,050', 31));
    expect(stat?.kind).toBe('sources');
    expect(stat?.figure).toBe('31');
  });

  it('does not print a clamped multiple for the loudest pack on the shelf', () => {
    // The live 123x: "Disability Living Allowance claim packs", measured 2026-08-15.
    const stat = packLeadStat(packWith(49.99, '£6,150', 44));
    expect(stat?.kind).toBe('sources');
    expect(stat?.figure).not.toContain('×');
    expect(stat?.figure).not.toContain('+');
  });

  it('still refuses a multiple below 1, which the ceiling must not have displaced', () => {
    const stat = packLeadStat(packWith(49.99, '£30', 22));
    expect(stat?.kind).toBe('sources');
  });

  it('leads with the multiple across the ordinary body of the catalogue', () => {
    // The median live pack is 9x; the bulk runs 2x-17x. None of it may be affected.
    for (const multiple of [2, 6, 9, 13, 17]) {
      const stat = packLeadStat(packWith(49.99, `£${(49.99 * multiple).toFixed(2)}`, 31));
      expect(stat?.kind, `multiple ${multiple}`).toBe('price_multiple');
      expect(stat?.figure, `multiple ${multiple}`).toBe(`${multiple}× first-year return`);
    }
  });
});
