import type { CopySlots, CopyVariant, VariantKey } from './copyConfig';

export type { VariantKey };

/**
 * The buyer's copy variant, resolved from query param → cookie → default.
 *
 * Resolution order:
 *  1. `?variant=a|b|c` query param, sets cookie, returns that variant (preview mode)
 *  2. `mumchimp.copy.variant` cookie, persists across visits
 *  3. Default: `'a'` (current live copy, zero change for existing visitors)
 *
 * Googlebot / crawler always gets variant 'a' to keep SEO stable.
 */
export function resolveVariant(
  queryParam: string | string[] | undefined,
  cookieValue: string | undefined,
  userAgent: string | undefined,
): VariantKey {
  // Crawlers always get the canonical variant so search indices are stable.
  if (userAgent && /\b(Googlebot|Bingbot|Slurp|DuckDuckBot|Baiduspider|YandexBot|facebookexternalhit|Twitterbot|LinkedInBot)\b/i.test(userAgent)) {
    return 'a';
  }
  // Query param overrides everything and sets the cookie for persistence.
  const fromQuery = typeof queryParam === 'string' ? queryParam.trim().toLowerCase() : undefined;
  if (fromQuery === 'a' || fromQuery === 'b' || fromQuery === 'c') return fromQuery;
  // Cookie carries the returning visitor's variant.
  if (cookieValue === 'b') return 'b';
  if (cookieValue === 'c') return 'c';
  return 'a';
}

export const VARIANT_COOKIE = 'mumchimp.copy.variant';

export function variantSetCookie(key: VariantKey): string {
  return `${VARIANT_COOKIE}=${key}; Path=/; Max-Age=31536000; SameSite=Lax`;
}

/** Append a Set-Cookie without wiping one already queued on this response. */
export function appendSetCookie(
  res: {
    getHeader(name: string): number | string | string[] | undefined;
    setHeader(name: string, value: string | number | readonly string[]): void;
  },
  cookie: string,
): void {
  const prev = res.getHeader('Set-Cookie');
  if (prev === undefined) {
    res.setHeader('Set-Cookie', cookie);
    return;
  }
  const list = Array.isArray(prev) ? prev.map(String) : [String(prev)];
  res.setHeader('Set-Cookie', [...list, cookie]);
}

/**
 * First-visit assignment for the homepage headline test (founder 2026-09-03).
 * Crawlers stay on a. A query or cookie wins. Otherwise a or b at 50/50; c is preview only.
 * `roll` is passed in so tests do not depend on Math.random.
 */
export function pickVisitorVariant(
  queryParam: string | string[] | undefined,
  cookieValue: string | undefined,
  userAgent: string | undefined,
  roll: number,
): { key: VariantKey; persist: boolean } {
  if (
    userAgent &&
    /\b(Googlebot|Bingbot|Slurp|DuckDuckBot|Baiduspider|YandexBot|facebookexternalhit|Twitterbot|LinkedInBot)\b/i.test(
      userAgent,
    )
  ) {
    return { key: 'a', persist: false };
  }
  const fromQuery = typeof queryParam === 'string' ? queryParam.trim().toLowerCase() : undefined;
  if (fromQuery === 'a' || fromQuery === 'b' || fromQuery === 'c') {
    return { key: fromQuery, persist: true };
  }
  if (cookieValue === 'a' || cookieValue === 'b' || cookieValue === 'c') {
    return { key: cookieValue, persist: false };
  }
  return { key: roll < 0.5 ? 'a' : 'b', persist: true };
}

/** Look up ONE copy slot from the variant dictionary. */
export function copyForSlot(variant: CopyVariant, slot: keyof CopySlots): string {
  return variant[slot] as string;
}

export const VARIANT_KEYS: VariantKey[] = ['a', 'b', 'c'];
