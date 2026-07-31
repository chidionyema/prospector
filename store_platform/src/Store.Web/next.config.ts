import type { NextConfig } from "next";

/**
 * Security headers (docs/ux/SECURE-UI.md).
 * CSP is allow-listed for Stripe.js/Elements ONLY — card data never touches our JS or
 * servers, it loads from js.stripe.com and posts into a Stripe iframe. Everything else
 * is locked to 'self'. No object/embed, framing denied, MIME-sniffing off.
 */

// API origin the browser is allowed to call (connect-src). Derived from the public API URL.
const API_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/v1").origin;
  } catch {
    return "http://localhost:8080";
  }
})();

const csp = [
  "default-src 'self'",
  // Next's runtime needs inline bootstrap; Stripe.js loads from its own origin.
  "script-src 'self' 'unsafe-inline' https://js.stripe.com",
  // Tailwind injects styles; allow inline styles.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN} https://api.stripe.com`,
  // Stripe Elements renders card fields inside these frames.
  "frame-src https://js.stripe.com https://hooks.stripe.com",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(self \"https://js.stripe.com\")" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
];

// The guest pitch link carries a 256-bit CSPRNG magic token in its PATH (hashed at rest server-side;
// see ProposalEndpoints.cs). It is unguessable, but the URL itself is a bearer secret, so this single
// surface is locked down harder than the rest of the app: send NO referrer (so the token can't leak to
// any destination, even same-origin) and keep these private links out of search indexes.
const pitchHeaders = [
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Emit `.next/standalone` (minimal server.js + traced node_modules) for a small
  // production Docker image. The Dockerfile copies standalone + .next/static + public.
  output: "standalone",
  // Pin file-tracing to THIS app dir. Without it a stray lockfile higher up the tree makes Next
  // infer the wrong monorepo root and nest the output (.next/standalone/<long/path>/server.js),
  // which breaks the Docker COPY and the dev server's dynamic routes. Pinning keeps server.js
  // flat at .next/standalone/server.js and silences the workspace-root warning.
  outputFileTracingRoot: import.meta.dirname,
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Listed AFTER the catch-all so the duplicate Referrer-Policy key wins for pitch URLs.
      { source: "/pitch/:path*", headers: pitchHeaders },
    ];
  },
  // D-63 same-origin API proxy: the browser's XHR hits `/api/*` (first-party to the web origin), and
  // Next.js forwards it to the real API. This makes the API's httpOnly `jwt` session cookie first-party
  // to the web origin, so a SameSite=Strict cookie survives a page reload — on *.fly.dev web and API are
  // cross-site (fly.dev is a public suffix), so a cookie the API set directly would never be re-sent.
  // Full-page OAuth/OIDC navigations deliberately bypass this and go straight to the API (client.ts
  // API_DIRECT_BASE) because the provider correlation cookie must be set and read on the API origin.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/v1/:path*` }];
  },
  // WR-023 lexicon: the requester's posted ask is a "proposal" (was "/bounties"); an introducer's
  // submission is an "offer" (was the "/proposals" sub-route). Keep the old paths alive permanently —
  // funded links and bookmarks point at them. Order matters: the specific routes must precede the
  // `/bounties/:id` catch-all, or it would swallow "new" and the "…/proposals" leaf.
  async redirects() {
    return [
      { source: "/bounties/new", destination: "/proposals/new", permanent: true },
      { source: "/bounties/:id/proposals", destination: "/proposals/:id/offers", permanent: true },
      { source: "/bounties/:id", destination: "/proposals/:id", permanent: true },
    ];
  },
};

export default nextConfig;
