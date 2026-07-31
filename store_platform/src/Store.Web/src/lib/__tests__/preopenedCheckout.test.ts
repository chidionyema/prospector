import { describe, it, expect } from 'vitest';
import { preopenedClientSecret, PREOPENED_CHECKOUT_PARAM } from '../preopenedCheckout';

const LIVE = 'cs_live_a1b2c3d4e5f6g7h8_secret_fidkdWxOYHwnPyd1blpxYHZxWjA0S1BS';
const TEST = 'cs_test_a1b2c3d4e5f6g7h8_secret_fidkdWxOYHwnPyd1blpxYHZxWjA0S1BS';

describe('preopenedClientSecret', () => {
  it('opens a live session secret', () => {
    expect(preopenedClientSecret(LIVE)).toBe(LIVE);
  });

  it('opens a test session secret, so the same route works before going live', () => {
    expect(preopenedClientSecret(TEST)).toBe(TEST);
  });

  it('ignores an absent parameter — the ordinary page load', () => {
    expect(preopenedClientSecret(undefined)).toBeNull();
  });

  it('ignores a repeated parameter rather than picking one for the buyer', () => {
    expect(preopenedClientSecret([LIVE, TEST])).toBeNull();
  });

  // A mistyped parameter must fail as an ignored URL, not as an SDK exception thrown on a page a
  // real buyer could be looking at.
  it.each([
    ['empty', ''],
    ['whitespace', '   '],
    ['a session id with no secret half', 'cs_live_a1b2c3d4e5f6g7h8'],
    ['a payment intent secret', 'pi_3abc_secret_xyz'],
    ['an arbitrary string', 'not-a-secret'],
    ['a truncated prefix', 'cs_a1b2_secret_xyz'],
    ['an injected script', '<script>alert(1)</script>'],
  ])('ignores %s', (_label, value) => {
    expect(preopenedClientSecret(value)).toBeNull();
  });

  it('trims surrounding whitespace from a paste', () => {
    expect(preopenedClientSecret(`  ${LIVE}  `)).toBe(LIVE);
  });

  it('exposes a stable parameter name', () => {
    expect(PREOPENED_CHECKOUT_PARAM).toBe('checkout_session');
  });
});
