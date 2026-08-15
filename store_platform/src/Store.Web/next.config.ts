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

// The ONE host this site is allowed to be reachable on. Everything else that resolves here is
// redirected to it — see the redirects() note on why that is a session fence, not an SEO nicety.
// Derived from the same public site URL the canonical <link> uses, so the two can never disagree.
// Undefined (no NEXT_PUBLIC_SITE_URL, e.g. a bare local dev run) simply installs no redirect.
const CANONICAL_HOST = (() => {
  try {
    const raw = process.env.NEXT_PUBLIC_SITE_URL;
    return raw ? new URL(raw).host : undefined;
  } catch {
    return undefined;
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
  // /og/pack/[id] renders its social card with next/og (ImageResponse). Next reaches the renderer
  // through a RUNTIME `import()` inside dist/server/og/image-response.js, which static file tracing
  // cannot see, so the standalone bundle shipped without it and the route threw
  // ERR_MODULE_NOT_FOUND for @vercel/og/index.node.js — a 500 in production while returning 200 in
  // dev and in `next start`, because both of those have the full node_modules on disk. Measured on
  // prospector-store-web 2026-08-01. The glob must stay a directory wildcard: the renderer also
  // loads resvg.wasm, yoga.wasm and Geist-Regular.ttf at runtime, none of which are reachable by
  // tracing either, and naming only index.node.js would move the failure rather than fix it.
  //
  // The key is a GLOB, not a route literal. Next matches it with picomatch
  // (build/collect-build-traces.js), where `[id]` is a character class matching one `i` or `d` — so
  // the obvious key "/og/pack/[id]" matches nothing at all and fails SILENTLY, exactly like having
  // written no include. Any dynamic route has to be reached with a wildcard for this reason.
  outputFileTracingIncludes: {
    "/og/pack/**": ["node_modules/next/dist/compiled/@vercel/og/**"],
  },
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
    return [
      // Everything else the browser fetches, proxied verbatim (no /v1 — these are the store's own
      // unversioned routes: /catalog, /catalog/stats, /catalog/waitlist, /packs/{id}/checkout,
      // /checkout, /events, /api/orders/*). Must come FIRST: rewrites are tried in array order and
      // the /api/:path* rule below would otherwise swallow these and send them to /v1.
      //
      // Why they are proxied at all: a browser fetch to the API's own origin is cross-site on Fly
      // and needs Store__AllowedOrigin to list this exact host. When that list is wrong the failure
      // is SILENT AND PARTIAL — reproduced 2026-08-01 with the storefront on :3001 and the API
      // allowing only :3000: sign-in worked (already proxied) while /events was refused for a
      // missing Access-Control-Allow-Origin. The same mistake on Fly kills the BUY BUTTON, because
      // checkout is a browser POST, while every page still renders. See lib/config.ts API_FETCH_BASE.
      { source: "/api/store/:path*", destination: `${API_ORIGIN}/:path*` },
      { source: "/api/:path*", destination: `${API_ORIGIN}/v1/:path*` },
    ];
  },
  // WR-023 lexicon: the requester's posted ask is a "proposal" (was "/bounties"); an introducer's
  // submission is an "offer" (was the "/proposals" sub-route). Keep the old paths alive permanently —
  // funded links and bookmarks point at them. Order matters: the specific routes must precede the
  // `/bounties/:id` catch-all, or it would swallow "new" and the "…/proposals" leaf.
  async redirects() {
    return [
      // ONE canonical host, and it is the apex. Measured 2026-08-15: BOTH mumchimp.com and
      // www.mumchimp.com answered /account with 200 off the same Fly server, and nothing sent
      // either to the other — two live origins for one site.
      //
      // That is a SESSION bug, not an SEO nicety. The `jwt` cookie is written with no Domain
      // attribute (Store.Api/Identity/JwtTokenService.cs AppendJwtCookie), so it is host-only:
      // a cookie stored for mumchimp.com is never sent to www.mumchimp.com. Meanwhile the social
      // callback returns EVERY user to Email__WebBaseUrl, which is the apex
      // (ExternalAuthEndpoints.cs:58,66). So a visitor who browses www signs in successfully, is
      // handed back to the apex where the cookie lands, and then reads as anonymous the moment
      // anything takes them back to www — with no error anywhere, because nothing failed. The
      // symptom is a paid CTA where the signed-in one should be.
      //
      // The host is spelled out on BOTH sides rather than captured from the request. A named
      // group in `has.host` cannot be interpolated into the destination's HOST position: Next
      // lowercases the key and path-to-regexp then compiles the destination with the group
      // undefined, so every www request 500s with `Expected "apexhost" to be a string` — measured
      // 2026-08-15 against a dev server before this was rewritten. It must be FIRST: redirects
      // are evaluated in order and this one is about the origin, not the path.
      ...(CANONICAL_HOST
        ? [
            {
              source: "/:path*",
              has: [{ type: "host" as const, value: `www.${CANONICAL_HOST}` }],
              destination: `https://${CANONICAL_HOST}/:path*`,
              permanent: true,
            },
          ]
        : []),
      { source: "/bounties/new", destination: "/proposals/new", permanent: true },
      { source: "/bounties/:id/proposals", destination: "/proposals/:id/offers", permanent: true },
      { source: "/bounties/:id", destination: "/proposals/:id", permanent: true },
      // The account surface is ONE route (/account) that renders sign-in, register, verify and
      // reset from its query string. These are the conventional URLs people type or that a
      // password manager has stored, plus the two paths the-introduction-exchange's emails used —
      // any link already in an inbox keeps working. Next.js carries the query string through a
      // redirect, so ?user_id=…&token=… survives; `verify=1` / `reset=1` is what /account
      // dispatches on, so the old paths add it here.
      // THE SHELF GETS A URL. It had none: the catalogue is a section of the home page reachable
      // only as `/#catalog`, so the one thing this site sells could not be linked to, typed, or
      // put in an ad without a fragment nobody guesses. `/catalogue` is the word the nav and the
      // footer both already use for it.
      //
      // A redirect and NOT a second page, deliberately. `Seo` derives the canonical URL from
      // `asPath` with no override (components/Seo.tsx:79), so a route that re-rendered the home
      // page would self-canonicalise and put two URLs serving identical content in the index --
      // which costs more than the missing route does. The honest separate page means lifting
      // `CatalogBrowser` and its ~90-line `getServerSideProps` out of pages/index.tsx, which is a
      // refactor of the highest-traffic page in the week of launch. This gets the linkable URL now
      // and leaves that door open.
      //
      // `permanent: false` (307) for exactly that reason: a 308 is cached by the browser
      // indefinitely, and promoting `/catalogue` to a real page later would then have to fight
      // every visitor's cache.
      { source: "/catalogue", destination: "/#catalog", permanent: false },
      // British spelling is the canonical one (see MARKETING_NAV); the American one is what a US
      // visitor will type.
      { source: "/catalog", destination: "/#catalog", permanent: false },
      { source: "/login", destination: "/account", permanent: false },
      { source: "/register", destination: "/account?mode=register", permanent: false },
      { source: "/forgot-password", destination: "/account", permanent: false },
      { source: "/verify-email", destination: "/account?verify=1", permanent: false },
      { source: "/reset-password", destination: "/account?reset=1", permanent: false },
    ];
  },
};

export default nextConfig;
