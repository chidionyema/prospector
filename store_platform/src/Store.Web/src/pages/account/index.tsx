import React, { useMemo } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHeader } from '@/components/ui';
import { AuthPanel } from '@/components/account/AuthPanel';
import { AccountPanel } from '@/components/account/AccountPanel';
import { useAuth } from '@/lib/auth/AuthContext';

/**
 * The whole customer-account surface: one route.
 *
 * Signed out it is sign-in / register / forgot-password, and — via the query string the
 * transactional emails carry — verify-address and reset-password. Signed in it is orders, details
 * and security. The-introduction-exchange spread the same functionality over nine pages; the
 * storefront has one kind of user and one thing they come here to do, which is get at what they
 * bought.
 *
 * noindex, and not because the content is secret — a signed-out crawler only ever sees a sign-in
 * form. It is that a sign-in form indexed against the store's name outranks the catalogue for
 * people searching the brand.
 */
export default function AccountPage() {
  const router = useRouter();
  const { status } = useAuth();

  const initial = useMemo(() => {
    const q = router.query;
    const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

    if (one(q.verify) === '1') {
      return {
        mode: 'verifying' as const,
        userId: one(q.user_id),
        token: one(q.token),
        error: one(q.error),
      };
    }
    if (one(q.reset) === '1') {
      return {
        mode: 'reset' as const,
        email: one(q.email),
        token: one(q.token),
        error: one(q.error),
      };
    }
    return {
      mode: (one(q.mode) === 'register' ? 'register' : 'signin') as 'register' | 'signin',
      error: one(q.error),
    };
  }, [router.query]);

  // Absolute, because it leaves our origin: the API's open-redirect guard compares it against the
  // configured web base and falls back to /auth/callback if it does not match
  // (ExternalAuthEndpoints.cs:188). Computed in the browser so a preview deployment returns to
  // itself rather than to whatever host was baked in at build time.
  const returnTo = typeof window === 'undefined' ? '' : `${window.location.origin}/auth/callback`;

  return (
    <MarketingLayout>
      <Head>
        <meta name="robots" content="noindex, nofollow" />
      </Head>
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8">
        <PageHeader
          title={status === 'authenticated' ? 'Your account' : 'Sign in'}
          description={
            status === 'authenticated'
              ? undefined
              : 'Your purchases are tied to the email address you bought with — sign in with it to see them.'
          }
        />

        <div className="mt-8">
          {/* Nothing renders until the session question is answered. The alternative shows every
              returning customer a sign-in form for one frame before their account replaces it. */}
          {status === 'loading' && (
            <p className="text-body text-muted">Checking your session…</p>
          )}
          {status === 'anonymous' && <AuthPanel initial={initial} returnTo={returnTo} />}
          {status === 'authenticated' && <AccountPanel />}
        </div>
      </div>
    </MarketingLayout>
  );
}
