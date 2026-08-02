import type { CopySlots, CopyVariant, VariantKey } from './copyConfig';

/**
 * The buyer's copy variant, resolved from query param → cookie → default.
 *
 * Resolution order:
 *  1. `?variant=a|b|c` query param — sets cookie, returns that variant (preview mode)
 *  2. `mumchimp.copy.variant` cookie — persists across visits
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

/**
 * Look up ONE copy string for a given slot and variant.
 *
 * Every copy slot returns a plain string. The caller renders it into JSX;
 * this module owns only the text, never the markup.
 */
export function copyForSlot(
  variant: CopyVariant,
  slot: keyof CopyVariant,
): CopyVariant[typeof slot] {
  return variant[slot];
}

/** All valid variant keys. */
export const VARIANT_KEYS: VariantKey[] = ['a', 'b', 'c'];
