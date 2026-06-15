import { useEffect } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '@/context/AuthContext';

/**
 * Client-side redirect for unauthenticated visitors. This is a UX convenience, NOT the
 * security boundary:
 *
 * - The real boundary is the API — every request is JWT-Bearer-authed and RLS-enforced
 *   server-side, so a guard bypass yields 401/empty data, never someone else's records.
 * - We deliberately keep the access token IN MEMORY ONLY (SECURE-UI §3, never a cookie),
 *   which is why route protection lives here and not in Next middleware/SSR: there is no
 *   auth cookie for the edge to read, and introducing one to enable middleware would
 *   re-open the XSS exfiltration surface this design closes.
 *
 * CONTRACT (prevents a flash of protected content): a caller MUST gate its render on the
 * returned flags — render a neutral skeleton while `loading`, and render nothing protected
 * when `!user` (the redirect is in-flight). Never render data-bearing UI before `user` is set.
 *
 *   const { user, loading } = useProtectedRoute();
 *   if (loading || !user) return <Skeleton />;   // ← required
 */
export function useProtectedRoute() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      void router.push('/login');
    }
  }, [user, loading, router]);

  return { user, loading };
}
