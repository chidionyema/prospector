/**
 * The delivery rules the shop screens must not soften.
 *
 * `abandoned` is not a louder `failed`. Failed is still being retried by the drain; abandoned means
 * the drain hit `Delivery:MaxAttempts` and stopped, so a buyer who paid and holds an entitlement
 * will never be sent their link by anything automatic. If the two ever sort or read the same, the
 * screen has lost the only distinction that decides whether a person has to act.
 *
 * The second rule is the id rule. A delivery row's `id` and its `orderId` are different numbers.
 * `deliveries.resend` takes the delivery row; the "Order" link takes the order. Using one where
 * the other belongs opens a different buyer's order, which is why the source is scanned here too.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { DELIVERY_STATES, deliverySeverity, deliveryTone, deliveryWords, isAbandoned, resendWords } from '@/lib/shop';

const SRC = fileURLToPath(new URL('../src', import.meta.url));

describe('abandoned outranks failed', () => {
  it('sorts worse than every other state', () => {
    expect(deliverySeverity('abandoned')).toBeGreaterThan(deliverySeverity('failed'));
    expect(deliverySeverity('failed')).toBeGreaterThan(deliverySeverity('pending'));
    expect(deliverySeverity('pending')).toBeGreaterThan(deliverySeverity('sent'));
  });

  it('says in plain words that nothing will retry it', () => {
    expect(deliveryWords('abandoned')).toMatch(/gave up|never|nothing will try/i);
    // Failed must NOT say that, because failed is still being retried.
    expect(deliveryWords('failed')).toMatch(/still being retried/i);
  });

  it('is coloured as a failure, and is the only state isAbandoned admits', () => {
    expect(deliveryTone('abandoned')).toBe('bad');
    expect(isAbandoned('abandoned')).toBe(true);
    expect(isAbandoned('ABANDONED')).toBe(true);
    expect(isAbandoned('failed')).toBe(false);
    expect(isAbandoned(null)).toBe(false);
  });

  it('offers exactly the states the gateway accepts', () => {
    expect([...DELIVERY_STATES].sort()).toEqual(
      ['abandoned', 'all', 'failed', 'pending', 'sent', 'unsent'].sort(),
    );
  });
});

describe('a resend says whether it destroyed a send time', () => {
  // There is one outcome, `requeued`. The second one this used to have, `duplicated`, cannot
  // happen: PendingDeliveries.EntitlementId is UNIQUE, so no second row for the same entitlement
  // can exist. What splits the cases is previousSentAt.
  it('does not describe the two cases the same way', () => {
    expect(resendWords('requeued', null)).not.toBe(
      resendWords('requeued', '2026-08-18T09:00:00Z'),
    );
  });

  it('a row that never went out is described as harmless', () => {
    expect(resendWords('requeued', null)).toMatch(/never been sent|back to zero/i);
  });

  it('a row that HAD been sent says the buyer gets a second email and the record is gone', () => {
    const words = resendWords('requeued', '2026-08-18T09:00:00Z');
    expect(words).toMatch(/already been sent/i);
    expect(words).toMatch(/second email/i);
    expect(words).toContain('2026-08-18T09:00:00Z');
  });

  it('refuses to claim anything when the store said nothing', () => {
    expect(resendWords(null, null)).toMatch(/did not say/i);
  });
});

describe('resending an already-sent link is not a plain button', () => {
  const panel = readFileSync(`${SRC}/components/ResendDelivery.tsx`, 'utf8');

  it('demands a second acknowledgement before it can be applied', () => {
    expect(panel).toContain('requireAck');
    expect(panel).toMatch(/second email/i);
  });

  it('has no duplicated outcome branch left in it', () => {
    // The schema refuted that outcome. A leftover branch would render a state the store can never
    // return, which reads as a working feature until someone relies on it.
    expect(/outcome === 'duplicated'|p\.will === 'duplicated'/.test(panel)).toBe(false);
  });
});

describe('a delivery row carries the order it belongs to, not just its own id', () => {
  const page = readFileSync(`${SRC}/pages/delivery.tsx`, 'utf8');

  it('links the Order row through orderId', () => {
    expect(page).toMatch(/\/orders\/\$\{encodeURIComponent\(String\(d\.orderId\)\)\}/);
  });

  it('never builds an order link out of the delivery row id', () => {
    expect(page).not.toMatch(/\/orders\/\$\{encodeURIComponent\(String\(d\.id\)\)\}/);
    expect(page).not.toMatch(/\/orders\/\$\{encodeURIComponent\(d\.id\)\}/);
  });

  it('resends the DELIVERY row, not the order', () => {
    expect(page).toContain('<ResendDelivery deliveryId={d.id}');
    expect(page).not.toContain('deliveryId={d.orderId}');
  });
});

describe('the disputes screen states what its figures and dates are not', () => {
  const page = readFileSync(`${SRC}/pages/disputes.tsx`, 'utf8');

  it('renders the gateway date_basis rather than swallowing it', () => {
    // The reversal is not timestamped anywhere, so the dates are SALE dates. An operator who reads
    // them as dispute ages answers the oldest dispute last.
    expect(page).toContain('date_basis');
    expect(page).toContain('dateWord="sold"');
  });

  it('never adds two currencies together', () => {
    // perCurrency is the only reducer allowed on money. addMinorUnits would throw on a second
    // currency, but the point is that this screen never reaches for a single total at all.
    expect(page).toContain('perCurrency');
    expect(page).not.toContain('addMinorUnits');
  });

  it('labels the amount as money at risk, not money returned', () => {
    // by_currency is what the disputed sales were WORTH. What came back is not recorded anywhere,
    // so the tile that carries a money value says "at risk" and the screen says why in words.
    expect(page).toContain('at risk (${t.currency})');
    expect(page).toContain('not what came back');
  });
});
