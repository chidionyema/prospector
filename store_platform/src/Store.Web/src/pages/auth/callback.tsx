import React, { useEffect, useRef } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { auth, social } from '@/lib/api/auth';
import { useAuth } from '@/lib/auth/AuthContext';

/**
 * Where a social provider's sign-in lands.
 *
 * The API never puts a JWT in this URL. It mints a one-time opaque code with a 60-second life
 * (ExternalAuthCodeStore) and redirects here with only that; this page POSTs the code back and the
 * API answers by setting the session cookie. A token in the query string would be written into
 * browser history, the Referer header of the next request, and any access log between here and
 * the server, none of which expire in 60 seconds.
 *
 * The exchange is guarded by a ref rather than left to the effect's dependencies: React 19 in
 * development mounts effects twice, the code is single-use, and the second call would consume
 * nothing and report a failed sign-in on a sign-in that had just succeeded.
 */
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default function AuthCallbackPage() {
  const router = useRouter();
  const { adopt } = useAuth();
  const exchanged = useRef(false);

  // Every other outcome leaves this page by redirecting, so the only thing to render is "a link
  // with no code at all". Derived rather than held in state: it is a pure function of the URL, and
  // an effect that set it would be a cascading render the lint rule rightly rejects.
  const incomplete =
    router.isReady && !one(router.query.code) && !one(router.query.error) && one(router.query.linked) !== '1';

  useEffect(() => {
    if (!router.isReady || exchanged.current) return;

    const code = one(router.query.code);
    const failure = one(router.query.error);
    const linked = one(router.query.linked);

    // Returning from connecting a provider to an account that is already signed in, no code to
    // exchange, the link happened server-side.
    if (linked === '1') {
      void router.replace('/account');
      return;
    }

    if (failure) {
      void router.replace(`/account?error=${encodeURIComponent(failure)}`);
      return;
    }

    if (!code) return; // rendered by `incomplete` above

    exchanged.current = true;
    social
      .exchange(code)
      .then(() => auth.me())
      .then((account) => {
        adopt(account);
        void router.replace('/account');
      })
      .catch(() => {
        // Deliberately vague and always recoverable: an expired or replayed code is the common
        // case, and the only useful next step is the same one either way.
        void router.replace('/account?error=Auth.InvalidExchangeCode');
      });
  }, [router, adopt]);

  return (
    // The trail is not decoration on this route. The happy path redirects immediately, but the
    // `incomplete` branch below is a terminal state -- it says "please start again" and offers
    // nothing to start again WITH. The crumb is the only way out of it.
    // Width '3xl' matches the max-w-3xl the panel below already uses, so the two line up.
    <MarketingLayout
      breadcrumbs={[{ href: '/', label: 'Catalogue' }, { href: '#', label: 'Signing in' }]}
      breadcrumbsWidth="6xl"
    >
      <Head>
        <meta name="robots" content="noindex, nofollow" />
      </Head>
      <div className="mx-auto max-w-[1080px] px-5 py-24 text-center">
        {/* Visually hidden, because this page is a redirect step and shows no chrome. It still
            needs a heading: with none, the route has no h1 and a screen reader has nothing to
            navigate to. */}
        <h1 className="sr-only">Signing in</h1>
        <p className="text-body text-muted">
          {incomplete ? 'That sign-in link is incomplete. Please start again.' : 'Signing you in…'}
        </p>
      </div>
    </MarketingLayout>
  );
}
