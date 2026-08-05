import React from 'react';
import { useRouter } from 'next/router';
import { resolveVariant, type VariantKey } from './getCopyVariant';
import { VARIANTS, type CopyVariant } from './copyConfig';
import { track } from './analytics';

const COOKIE_NAME = 'mumchimp.copy.variant';

function readVariantCookie(): string | undefined {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${COOKIE_NAME}=`))
    ?.split('=')[1];
}

/**
 * The cookie and the user-agent are read once per snapshot and never change during a session, so
 * there is nothing to subscribe to. A no-op subscribe is the documented shape for reading a
 * client-only value through useSyncExternalStore. It is module-level because a new function
 * identity on every render would make React tear down and re-establish the subscription.
 */
const NO_SUBSCRIPTION = () => () => {};

/** The server has no cookie and no user-agent, so it always renders the control variant. */
const getServerSnapshot = (): VariantKey => 'a';

/**
 * Client-side copy-variant hook.
 *
 * Reads the variant from the URL query param or the cookie, persists via cookie, and returns the
 * full copy dictionary for the resolved variant. Fires a `copy_variant` analytics event on first
 * resolution so the founder can measure which variant converts better.
 *
 * This previously ran as `useState(null)` plus an effect that called `setResolved(variant)` in its
 * body while also listing `resolved` in its own dependency array, so every resolution scheduled a
 * second render which re-ran the effect (caught by react-hooks/set-state-in-effect). The variant
 * is not React state, it is a value derived from three client-only inputs, so it is read through
 * useSyncExternalStore instead: `getServerSnapshot` keeps SSR and hydration on the control variant,
 * and the client snapshot takes over immediately after, with no cascading render.
 */
export function useCopyVariant(): { variant: CopyVariant; key: VariantKey } {
  const router = useRouter();
  const queryParam = router.query.variant;

  const getSnapshot = React.useCallback(
    (): VariantKey => resolveVariant(queryParam, readVariantCookie(), window.navigator.userAgent),
    [queryParam],
  );

  const key = React.useSyncExternalStore(NO_SUBSCRIPTION, getSnapshot, getServerSnapshot);

  // Writes to external systems (document.cookie, analytics) stay in an effect, which is what
  // effects are for. Neither writes React state, so neither triggers a re-render.
  const tracked = React.useRef(false);
  React.useEffect(() => {
    if (readVariantCookie() !== key) {
      document.cookie = `${COOKIE_NAME}=${key}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    }
    // Once per mount, matching the previous `resolved === null` guard.
    if (!tracked.current) {
      tracked.current = true;
      track('copy_variant', key);
    }
  }, [key]);

  return { variant: VARIANTS[key], key };
}
