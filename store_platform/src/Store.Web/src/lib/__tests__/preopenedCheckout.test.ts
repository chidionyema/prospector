import { describe, it, expect } from 'vitest';
import {
  preopenedClientSecret,
  preopenedCheckoutUrl,
  PREOPENED_CHECKOUT_PARAM,
} from '../preopenedCheckout';

const LIVE = 'cs_live_a1b2c3d4e5f6g7h8_secret_fidkdWxOYHwnPyd1blpxYHZxWjA0S1BS';
const TEST = 'cs_test_a1b2c3d4e5f6g7h8_secret_fidkdWxOYHwnPyd1blpxYHZxWjA0S1BS';

/**
 * A REAL live secret returned by the deployed API, shortened but with its exact charset kept.
 * The `%` sequences are the point: a plausible `[A-Za-z0-9_-]` charset rejects every genuine
 * secret, which shows up as an overlay that silently never opens rather than as any error.
 */
const REAL_LIVE =
  'cs_live_a1LEgibSYVdkNxEb3J0GkGOTuJHy3oQa1EDZdDD7eGAs1gHy0GVcQMccST_secret_'
  + 'fidnandhYHdWcXxpYCc%2FJ2FgY2RwaXEnKSdkdWxOYHwnPyd1blppbHNgWjA0UW9%2FXE1V';

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

  // The regression that nearly shipped: a charset of [A-Za-z0-9_-] looks right and rejects every
  // real secret, so the overlay silently never opens and the smoke test proves nothing.
  it('accepts a REAL live secret, whose blob contains percent sequences', () => {
    expect(preopenedClientSecret(REAL_LIVE)).toBe(REAL_LIVE);
  });
});

describe('preopenedCheckoutUrl', () => {
  /**
   * The other half of the same bug. The secret contains literal `%2F`; pasted raw into a query
   * string the browser decodes it to `/`, so Stripe receives a different string than it issued
   * and the session fails in a way that looks like a broken overlay.
   */
  it('escapes the percent sequences so the secret survives a round trip', () => {
    const url = preopenedCheckoutUrl('https://mumchimp.com', 'pack-1', REAL_LIVE);

    expect(url).toContain('%252F');
    expect(url).not.toContain('%2F&');

    const roundTripped = new URL(url).searchParams.get(PREOPENED_CHECKOUT_PARAM);
    expect(roundTripped).toBe(REAL_LIVE);
    expect(preopenedClientSecret(roundTripped ?? undefined)).toBe(REAL_LIVE);
  });

  it('does not double up a slash when the origin has a trailing one', () => {
    const url = preopenedCheckoutUrl('https://mumchimp.com/', 'pack-1', LIVE);
    expect(url.startsWith('https://mumchimp.com/pack/pack-1?')).toBe(true);
  });
});
