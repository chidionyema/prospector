import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { auth, AuthError, type Account } from '@/lib/api/auth';

/**
 * Session state for the storefront.
 *
 * The session itself lives in an HttpOnly cookie the browser holds and this code cannot read
 * (see lib/api/auth.ts). So "am I signed in?" is not a value we keep — it is a question only the
 * API can answer, and the answer is GET /auth/me: 200 means yes, 401 means no. That single fact
 * shapes everything below.
 *
 * `status` is a three-state, not a boolean, because a boolean cannot distinguish "not signed in"
 * from "we have not asked yet". With a boolean, the first paint of every account view is the
 * signed-out view, and a returning customer watches a sign-in form flash before their account
 * appears. Worse, a route guard written against it redirects them to sign in while their perfectly
 * good session is still being confirmed.
 */
export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextValue {
  status: AuthStatus;
  account: Account | null;
  /** Re-ask the API. Call after anything that changes the session or the profile. */
  refresh: () => Promise<Account | null>;
  signIn: (username: string, password: string) => Promise<Account>;
  signOut: () => Promise<void>;
  /** Adopt an account we already hold — used by the OAuth callback after it exchanges its code. */
  adopt: (account: Account) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * A 401 is the ordinary answer for a visitor with no cookie — not an error worth surfacing.
 * Anything else (the API is down, a proxy misconfigured) is also treated as anonymous by the
 * callers below, because the alternative is holding the whole storefront in 'loading' forever.
 * The pages that need to say something about it read the failure from their own call.
 */
function warnUnlessSignedOut(err: unknown) {
  if (!(err instanceof AuthError) || err.status !== 401) {
    console.warn('Could not confirm session:', err);
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [account, setAccount] = useState<Account | null>(null);

  const apply = useCallback((me: Account | null) => {
    setAccount(me);
    setStatus(me ? 'authenticated' : 'anonymous');
  }, []);

  const refresh = useCallback(async () => {
    try {
      const me = await auth.me();
      apply(me);
      return me;
    } catch (err) {
      warnUnlessSignedOut(err);
      apply(null);
      return null;
    }
  }, [apply]);

  // The one session probe on mount. Written as an explicit promise chain rather than `void
  // refresh()` for two reasons: the cancelled flag stops a late answer writing to an unmounted
  // provider, and react-hooks/set-state-in-effect rejects an effect body that calls into a
  // setState path directly — the state changes have to happen in the async continuation, which is
  // where they genuinely belong.
  useEffect(() => {
    let cancelled = false;
    auth
      .me()
      .then((me) => {
        if (!cancelled) apply(me);
      })
      .catch((err: unknown) => {
        warnUnlessSignedOut(err);
        if (!cancelled) apply(null);
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const signIn = useCallback(async (username: string, password: string) => {
    // The response body carries a token we deliberately ignore; the cookie the same response set
    // is the session. Re-reading /auth/me is what gives us the full account + profile, and it also
    // proves the cookie round-tripped rather than assuming it did.
    await auth.login(username, password);
    const me = await auth.me();
    apply(me);
    return me;
  }, [apply]);

  const signOut = useCallback(async () => {
    try {
      // Server-side first: logout revokes the token's JTI and clears the cookie. Clearing local
      // state without it would show a signed-out storefront while the session stayed valid for
      // anyone holding the cookie — the appearance of logging out, which is worse than none.
      await auth.logout();
    } finally {
      apply(null);
    }
  }, [apply]);

  const adopt = useCallback((next: Account) => apply(next), [apply]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, account, refresh, signIn, signOut, adopt }),
    [status, account, refresh, signIn, signOut, adopt],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an <AuthProvider>');
  }
  return ctx;
}
