import type { GetServerSideProps } from 'next';

/**
 * Dynamic /robots.txt. Allows crawling of the public marketing pages and explicitly disallows the
 * authed app + transactional surfaces (a crawler can't reach them, but stating it keeps private
 * paths out of any accidental index and points crawlers at the sitemap). Host is derived from the
 * request so it is correct on every environment without a baked URL.
 */

// Authed/transactional/dev paths that must never be advertised to crawlers (matches the noindex
// surfaces and the identity-blind pitch links). Kept in lockstep with SENSITIVE_PREFIXES in
// scripts/check-conformance.mjs (E30-001), which fails the build if any of these is dropped.
const DISALLOW = [
  '/board',
  '/dashboard',
  '/roster',
  '/settings',
  '/admin',
  '/proposals',
  '/bounties',
  '/auth',
  '/api',
  '/dev',
  '/pitch',
];

function originFromReq(headers: { host?: string; 'x-forwarded-proto'?: string }): string {
  const rawHost = headers.host ?? 'localhost:3000';
  const proto = headers['x-forwarded-proto'] ?? (rawHost.startsWith('localhost') ? 'http' : 'https');
  // The Host header is attacker-controllable and is interpolated into the response body, so
  // only accept a clean hostname[:port]; otherwise fall back to the configured site URL.
  if (!/^[a-zA-Z0-9.-]+(:\d+)?$/.test(rawHost)) {
    return (process.env.NEXT_PUBLIC_SITE_URL || 'https://localhost:3000').replace(/\/$/, '');
  }
  return `${proto}://${rawHost}`;
}

export const getServerSideProps: GetServerSideProps = async ({ req, res }) => {
  const origin = originFromReq(req.headers as { host?: string; 'x-forwarded-proto'?: string });
  const body = [
    'User-agent: *',
    ...DISALLOW.map((p) => `Disallow: ${p}`),
    '',
    `Sitemap: ${origin}/sitemap.xml`,
    '',
  ].join('\n');

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=86400');
  res.write(body);
  res.end();
  return { props: {} };
};

// Route only exists to serve the body above; nothing renders.
export default function Robots() {
  return null;
}
