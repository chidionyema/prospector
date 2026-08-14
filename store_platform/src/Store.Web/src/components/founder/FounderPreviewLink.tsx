import { useEffect, useState } from 'react';

import { founder } from '@/lib/api/auth';
import { useAuth } from '@/lib/auth/AuthContext';

/**
 * "Open the pack" : reading a pack's contents without buying it, for the founder only.
 *
 * Renders nothing for everybody else, and renders nothing while the answer is unknown. Both are
 * deliberate: a control that flickers into view and then disappears is worse than one that
 * arrives late, and a disabled-looking control would tell every visitor that a privileged route
 * exists.
 *
 * This is presentation only. The fence is the API's allowlist, re-checked on the download itself,
 * so forcing this component to render buys a 404 and nothing more.
 */
export function FounderPreviewLink({ packId, className = '' }: { packId: string; className?: string }) {
  const { status } = useAuth();
  const [allowed, setAllowed] = useState(false);

  // Every setState lives in an async continuation. The signed-out case is handled by the render
  // guard below rather than by resetting state here: react-hooks/set-state-in-effect rejects a
  // synchronous setState in an effect body, and gating the render is the honest fix anyway: a
  // stale `allowed` cannot show through a status check it has to pass first.
  useEffect(() => {
    if (status !== 'authenticated') {
      return;
    }

    let cancelled = false;
    founder
      .me()
      .then((answer) => {
        if (!cancelled) setAllowed(answer.founder);
      })
      .catch(() => {
        // A 401/404/outage all mean the same thing here: do not offer the control.
        if (!cancelled) setAllowed(false);
      });

    return () => {
      cancelled = true;
    };
  }, [status]);

  if (status !== 'authenticated' || !allowed) {
    return null;
  }

  return (
    <div className={className}>
      <a
        href={founder.downloadHref(packId)}
        // A plain navigation, not a fetch: see founder.downloadHref. No `download` attribute:
        // the redirect target names the file, and forcing a filename here would rename it.
        className="text-caption font-medium underline underline-offset-2"
      >
        Open the pack (founder preview)
      </a>
      <p className="mt-1 text-caption leading-relaxed text-subtle">
        The current build of this pack, no purchase recorded. Only your account can see this link.
      </p>
    </div>
  );
}
