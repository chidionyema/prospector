import React, { useEffect, useState } from 'react';
import { externalAuthApi } from '@/lib/api/client';
import type { ExternalProvider } from '@/lib/api/types';
import { Button } from '@/components/ui';

/**
 * Social sign-in buttons for the login/register screens (E16). Renders one button per CONFIGURED
 * provider (the API only returns providers it has credentials for, so a half-configured deploy never
 * shows a dead button). Each button is a full-page navigation to the API's challenge endpoint —
 * the OAuth dance can't be a fetch — handing it where to send the one-time code back: this app's
 * /auth/callback.
 *
 * Render is NOT gated on the /providers fetch: the divider + skeleton placeholders paint immediately
 * so the section never pops in late or shifts layout after a round-trip (worse on a cold API). Once
 * the fetch resolves the skeletons swap to live buttons — or the whole section disappears if nothing
 * is configured (rare; both providers are live in prod).
 */
export function SocialSignIn({ label }: { label: string }) {
  const [providers, setProviders] = useState<ExternalProvider[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { providers: list } = await externalAuthApi.providers();
        if (active) setProviders(list);
      } catch {
        // No providers / API down → just don't offer social sign-in (password still works).
        if (active) setProviders([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Settled with nothing configured → offer no social sign-in at all.
  if (!loading && providers.length === 0) return null;

  function start(provider: string) {
    const redirectUrl = `${window.location.origin}/auth/callback`;
    window.location.assign(externalAuthApi.challengeUrl(provider, redirectUrl));
  }

  return (
    <div className="mt-6">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="text-caption text-muted">{label}</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      <div className="mt-4 flex flex-col gap-3">
        {loading
          ? // Skeleton placeholders (expected provider count) so the buttons feel instant.
            [0, 1].map((i) => (
              <div
                key={i}
                aria-hidden
                className="h-11 w-full animate-pulse rounded-md border border-border bg-surface"
              />
            ))
          : providers.map((p) => (
              <Button
                key={p.name}
                variant="secondary"
                fullWidth
                onClick={() => start(p.name)}
              >
                Continue with {p.display_name}
              </Button>
            ))}
      </div>
    </div>
  );
}
