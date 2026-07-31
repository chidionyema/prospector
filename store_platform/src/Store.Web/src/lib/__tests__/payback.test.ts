import { describe, expect, it } from 'vitest';
import { parseAmount, paybackEquation } from '@/lib/payback';

describe('parseAmount', () => {
  it('reads a plain currency figure', () => {
    expect(parseAmount('£2,400')).toBe(2400);
  });

  it('scales a k/m suffix', () => {
    expect(parseAmount('£2.4k')).toBe(2400);
    expect(parseAmount('$1.2m')).toBe(1_200_000);
  });

  it('refuses a range rather than half-reading it', () => {
    // "£500 to £2,000" has no single honest answer. Picking either end would put a number on
    // the buy button that the engine never modelled.
    expect(parseAmount('£500 to £2,000')).toBeNull();
  });

  it('returns null for absent, empty, non-numeric and non-positive input', () => {
    expect(parseAmount(undefined)).toBeNull();
    expect(parseAmount('   ')).toBeNull();
    expect(parseAmount('not modelled')).toBeNull();
    expect(parseAmount('£0')).toBeNull();
  });
});

describe('paybackEquation', () => {
  it('computes the multiple from the price and the modelled month 1 revenue', () => {
    const result = paybackEquation('£49.00', { month1Revenue: '£2,400' });
    expect(result).not.toBeNull();
    expect(result!.multiple).toBe(48); // floor(2400 / 49)
    expect(result!.priceLabel).toBe('£49');
    expect(result!.revenueLabel).toBe('£2,400');
    expect(result!.paybackMonths).toBeNull();
  });

  it('carries the engine-stated payback period and never derives one', () => {
    const withPeriod = paybackEquation('£49.00', { month1Revenue: '£2,400', paybackMonths: '3 months' });
    expect(withPeriod!.paybackMonths).toBe('3 months');

    // No paybackMonths in the snapshot -> null, even though revenue and price are both known
    // and a period could trivially be invented from them.
    const withoutPeriod = paybackEquation('£49.00', { month1Revenue: '£2,400' });
    expect(withoutPeriod!.paybackMonths).toBeNull();
  });

  it('renders nothing when the modelled revenue does not clear the price', () => {
    // The load-bearing test: this must not be a widget that only appears when it flatters the
    // sale. A pack modelling £30 of month-1 revenue against a £49 price shows no equation at
    // all, rather than "0x" or a reframing that hides the shortfall.
    expect(paybackEquation('£49.00', { month1Revenue: '£30' })).toBeNull();
  });

  it('renders nothing without a snapshot, without month 1 revenue, or on an unreadable figure', () => {
    expect(paybackEquation('£49.00', undefined)).toBeNull();
    expect(paybackEquation('£49.00', { ltvCac: '3.4x' })).toBeNull();
    expect(paybackEquation('£49.00', { month1Revenue: 'to be modelled' })).toBeNull();
  });

  it('renders nothing when the price itself is unreadable', () => {
    expect(paybackEquation('', { month1Revenue: '£2,400' })).toBeNull();
    expect(paybackEquation('free', { month1Revenue: '£2,400' })).toBeNull();
  });
});
