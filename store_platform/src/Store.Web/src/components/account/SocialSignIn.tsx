import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui';
import { social, type Provider } from '@/lib/api/auth';

/**
 * Social sign-in buttons, rendered only for providers the API is actually configured for.
 *
 * The list is fetched rather than hardcoded because /auth/external/providers returns exactly the
 * schemes with credentials present (ExternalAuthEndpoints.cs:90). A hardcoded Google button on a
 * deployment whose secrets are not set is a button that always fails, and it fails on Google's
 * error page rather than ours, so the customer sees a broken product and we see nothing.
 *
 * Renders null while loading, not a skeleton: this sits beside a working email form, and a
 * placeholder that resolves to nothing is a worse flicker than an element appearing.
 */
export function SocialSignIn({ returnTo }: { returnTo: string }) {
  const [providers, setProviders] = useState<Provider[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    social
      .providers()
      .then((r) => {
        if (!cancelled) setProviders(r.providers);
      })
      .catch(() => {
        // Social is an alternative, never the only route in. If the lookup fails the email form
        // beside it still works, so this is silent by design.
        if (!cancelled) setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Distinct from "resolved to zero providers" below: this is the CLS defect (measured 0.184 at
  // 360px, one of two shift entries, ~790ms after navigation, see PageAudit 2026-08-08). The old
  // code returned null for BOTH "still loading" and "loaded, nothing configured", so on every load
  // of a deployment that DOES have a provider configured (this one has Google, see the "Connect
  // Google" fallback AccountPanel offers in its Security tab) the block popped from 0px to its full
  // height ~80ms after the parent's own auth-status shift resolved, and shoved the email/password
  // form down by however tall it turned out to be.
  //
  // Reserve that footprint while we don't yet know the answer, sized for exactly one provider
  // (the only one this codebase names anywhere): Button h-10 (40px) + the space-y-3 gap (12px) +
  // the divider row (pt-1 4px + text-caption line 0.75rem*1.5 = 18px = 22px) = 74px. If a second
  // provider is ever configured, that account gets a residual ~52px (one more button + gap) of
  // shift this reservation does not cover, only the single-provider case is closed.
  if (providers === null) {
    return <div className="min-h-[74px]" aria-hidden="true" />;
  }
  if (providers.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {providers.map((p) => (
        <Button
          key={p.name}
          variant="secondary"
          fullWidth
          onClick={() => social.signIn(p.name, returnTo)}
        >
          Continue with {p.display_name}
        </Button>
      ))}

      <div className="flex items-center gap-3 pt-1">
        <span className="h-px flex-1 bg-border" />
        <span className="text-caption text-muted">or</span>
        <span className="h-px flex-1 bg-border" />
      </div>
    </div>
  );
}
