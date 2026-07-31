/**
 * Can this browser reach Stripe's API at all?
 *
 * Why this exists: `resolveStripeCheckout` only falls back to hosted checkout when the SESSION
 * REQUEST fails. A session that is issued fine but cannot RENDER gets no fallback — Stripe's
 * iframe shows its own "the payment provider cannot be reached" copy and the buyer has nowhere
 * to go. That is not hypothetical: on 2026-07-31 a Chrome process rejected the certificate
 * chain for api.stripe.com (`net::ERR_CERT_AUTHORITY_INVALID`) while every other host, including
 * our own API, resolved normally. See `LIVE_RAIL_SMOKE_TEST.md`.
 *
 * The probe is a same-origin `no-cors` fetch, which is the only check proven to discriminate:
 * a reachable host yields an opaque response even for Stripe's 401, and an unreachable one
 * throws. Two probes that look equivalent and are NOT (both produced false positives while this
 * was being diagnosed):
 *   - fetching js.stripe.com — always throws, because our CSP `connect-src` does not list it;
 *   - navigating to api.stripe.com — always shows a Chrome error page, because Stripe answers
 *     401 with a Basic-auth challenge.
 *
 * Deliberately fails SAFE: any ambiguity (no fetch available, abort, timeout) reports reachable,
 * because a false "unreachable" would bounce a buyer out of a working overlay.
 */

/** Cheapest authenticated endpoint; we only care that the connection is made, not the answer. */
export const STRIPE_PROBE_URL = 'https://api.stripe.com/v1/charges';

export interface StripeReachabilityOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export async function isStripeApiReachable(
  { fetchImpl, timeoutMs = 6000 }: StripeReachabilityOptions = {},
): Promise<boolean> {
  const doFetch = fetchImpl ?? (typeof fetch === 'function' ? fetch : undefined);
  if (!doFetch) return true; // No fetch to probe with: assume fine rather than block a sale.

  const controller = typeof AbortController === 'function' ? new AbortController() : undefined;
  const timer = setTimeout(() => controller?.abort(), timeoutMs);
  try {
    await doFetch(STRIPE_PROBE_URL, { mode: 'no-cors', signal: controller?.signal });
    return true;
  } catch {
    // A timeout lands here too. Treat it as unreachable: the buyer has already been staring at
    // an unpainted overlay for `timeoutMs`, so offering them a working surface beats waiting.
    return false;
  } finally {
    clearTimeout(timer);
  }
}
