import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { authApi, ApiError, setAccessToken, setOnUnauthorized } from '@/lib/api/client';
import type { UserAndProfile } from '@/lib/api/types';

interface AuthContextType {
  user: UserAndProfile | null;
  loading: boolean;
  /** Re-fetch the signed-in user (call after a successful login). */
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  refresh: async () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserAndProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const resetAuth = useCallback(() => {
    setAccessToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setOnUnauthorized(resetAuth);
    return () => setOnUnauthorized(() => {});
  }, [resetAuth]);

  const refresh = useCallback(async () => {
    try {
      const me = await authApi.me();
      setUser(me);
    } catch (err) {
      // Best-effort refresh: a failed session reload (401 cold load, transient 5xx, unreachable
      // backend) means "treat as logged out", not an app error. Warn, never console.error — see the
      // mount-effect note below for why escalating to the dev overlay here is wrong.
      if (!(err instanceof ApiError) || err.status !== 401) {
        console.warn('Session probe failed; treating as logged out', err);
      }
      resetAuth();
    } finally {
      setLoading(false);
    }
  }, [resetAuth]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const me = await authApi.me();
        if (active) setUser(me);
      } catch (err) {
        // The mount-time session probe is best-effort: every public page (the auth-blind marketing
        // site included) renders fine logged-out, so ANY failure here — a 401 cold load, a transient
        // 5xx, or an unreachable backend — just means "treat as logged out". We log it as a warning,
        // never console.error: in dev that would escalate to the Next error overlay and blank a page
        // that is otherwise perfectly viewable; in prod it would be noise a logged-out visitor can't act on.
        if (!(err instanceof ApiError) || err.status !== 401) {
          console.warn('Session probe failed; treating as logged out', err);
        }
        if (active) resetAuth();
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [resetAuth]);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      resetAuth();
    }
  }, [resetAuth]);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
