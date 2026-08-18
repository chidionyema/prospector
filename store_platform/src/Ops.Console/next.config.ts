import type { NextConfig } from 'next';

/**
 * The admin console. Since 2026-08-18 it runs INSIDE the engine container on Fly and answers on
 * the open internet over HTTPS. This comment used to say it ran on the founder's laptop and was
 * "not deployed anywhere". Both halves are now wrong, and leaving them would be exactly the
 * drift this repo keeps paying for.
 *
 * WHY IT SHIPS WITH THE ENGINE AND NOT WITH Store.Web. The console reads store/prospector.db,
 * store/scheduler/*, store/dossiers/* and config.yaml as a DIRECTORY, so it has to sit on the
 * machine that mounts the volume. Store.Web is a separate Fly app whose image carries only
 * `.next/standalone`, `.next/static` and `public/`, and has no filesystem route to any of that.
 * Shipping admin routes inside the money-adjacent public storefront image would be wrong on its
 * own account too.
 *
 * WHAT REPLACED THE NETWORK FENCE. It used to bind a private address and be reached over
 * `fly proxy` from the laptop. Founder, 2026-08-18: "relying on a tunnel on this macbook to run
 * operations is not smart." The door is now TLS, the shared password in lib/auth.ts, the
 * five-strikes-per-address limiter in lib/ratelimit.ts, and the headers below.
 *
 * Detail: docs/ADMIN_CONSOLE_PROGRAM.md §1, deploy/engine/fly.toml.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // No `output: 'standalone'`. The engine image copies `.next` and `node_modules` in and runs
  // `next start`, so the build output is the deployment (deploy/engine/Dockerfile stage 1).
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
          // Added when the console went public, 2026-08-18. Without it the first request of
          // the day can be plain HTTP, and that request carries the session cookie.
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=31536000; includeSubDomains',
          },
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
