import type { NextConfig } from 'next';

/**
 * The admin console. It runs on the FOUNDER'S LAPTOP and is reached over the tailnet — it is not
 * deployed anywhere.
 *
 * WHY IT IS NOT PART OF Store.Web. Store.Web is a Fly.io deployment (`prospector-store-web`,
 * deploy/fly/web.fly.toml). Its image contains only `.next/standalone`, `.next/static` and
 * `public/`; it has no filesystem access to this machine and no route to it. The console must
 * read store/prospector.db, store/scheduler/*, store/dossiers/* and config.yaml, all of which
 * live here. Serving admin from Fly would mean opening an inbound port on the laptop — the exact
 * thing docs/OPS_CONSOLE_PROGRAM.md §10 forbids. It would also ship admin routes into the
 * money-adjacent public storefront image.
 *
 * Detail: docs/ADMIN_CONSOLE_PROGRAM.md §1.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // No `output: 'standalone'`. Nothing containerises this; `npm run start` on the laptop is the
  // deployment, exactly as Streamlit's launchd agent is today.
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          // Nothing here may be framed, indexed, or leak a referrer to the open web. The console
          // shows queue contents, spend and provider state.
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'X-Robots-Tag', value: 'noindex, nofollow, noarchive' },
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              // Next's dev overlay and its hydration bootstrap are inline.
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              "font-src 'self' data:",
              // The console talks to its own API routes and nothing else. No CDN, no analytics.
              "connect-src 'self'",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join('; '),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
