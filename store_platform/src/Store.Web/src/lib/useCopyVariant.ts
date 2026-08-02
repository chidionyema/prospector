import React from 'react';
import { useRouter } from 'next/router';
import { resolveVariant } from './getCopyVariant';
import { VARIANTS, type CopyVariant, type VariantKey } from './copyConfig';
import { track } from './analytics';

const COOKIE_NAME = 'mumchimp.copy.variant';

/**
 * Client-side copy-variant hook.
 *
 * Reads the variant from the URL query param or the cookie, persists via cookie,
 * and returns the full copy dictionary for the resolved variant. Fires a
 * `copy_variant` analytics event on first resolution so the founder can measure
 * which variant converts better.
 */
export function useCopyVariant(): { variant: CopyVariant; key: VariantKey } {
  const router = useRouter();
  const [resolved, setResolved] = React.useState<VariantKey | null>(null);

  React.useEffect(() => {
    if (typeof window === 'undefined') return;

    const queryParam = router.query.variant;
    const cookie = document.cookie
      .split('; ')
      .find((row) => row.startsWith(`${COOKIE_NAME}=`))
      ?.split('=')[1];
    const variant = resolveVariant(
      queryParam,
      cookie,
      window.navigator.userAgent,
    );

    // Persist the resolved variant in a cookie if it differs from what's stored.
    if (variant !== cookie) {
      document.cookie = `${COOKIE_NAME}=${variant}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    }
    // Track once per resolution.
    if (resolved === null) {
      track('copy_variant', variant);
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResolved(variant);
  }, [router.query.variant, resolved]);

  const key = resolved ?? 'a';
  return { variant: VARIANTS[key], key };
}
