import type { GetServerSideProps } from 'next';

/**
 * Dynamic /sitemap.xml — the PUBLIC marketing pages only. Authed, transactional, and identity-blind
 * pitch surfaces are deliberately excluded (they're noindex and must not be discoverable). Host is
 * derived from the request so the URLs are correct on every environment without a baked domain.
 */

// Public, indexable routes. Kept as an explicit allow-list, not a directory scan, so a new authed
// page never leaks into the sitemap by accident.
const PUBLIC_PATHS = [
  '/',
  '/how-it-works',
  '/faq',
  '/terms',
  '/privacy',
  '/refund',
];

function originFromReq(headers: { host?: string; 'x-forwarded-proto'?: string }): string {
  const rawHost = headers.host ?? 'localhost:3000';
  const proto = headers['x-forwarded-proto'] ?? (rawHost.startsWith('localhost') ? 'http' : 'https');
  // The Host header is attacker-controllable and is interpolated into the XML body below, so
  // only accept a clean hostname[:port]. Anything with markup chars (`<`, `>`, `&`, spaces)
  // falls back to the configured site URL rather than corrupting the sitemap.
  if (!/^[a-zA-Z0-9.-]+(:\d+)?$/.test(rawHost)) {
    return (process.env.NEXT_PUBLIC_SITE_URL || 'https://localhost:3000').replace(/\/$/, '');
  }
  return `${proto}://${rawHost}`;
}

// Marketing copy changes occasionally; the home page is the most-updated. These are crawl-budget
// hints only (search engines treat them as advisory), so a coarse static value is honest and enough.
function changefreqFor(path: string): string {
  return path === '/' ? 'weekly' : 'monthly';
}

export const getServerSideProps: GetServerSideProps = async ({ req, res }) => {
  const origin = originFromReq(req.headers as { host?: string; 'x-forwarded-proto'?: string });
  // `lastmod` is the build date (these are static pages rebuilt on deploy). Derived from the build,
  // not request time, so a crawl doesn't see the timestamp churn on every hit.
  const lastmod = (process.env.NEXT_PUBLIC_BUILD_DATE || new Date().toISOString().slice(0, 10)).slice(0, 10);
  const urls = PUBLIC_PATHS.map(
    (p) =>
      `  <url><loc>${origin}${p === '/' ? '' : p}</loc><lastmod>${lastmod}</lastmod><changefreq>${changefreqFor(p)}</changefreq></url>`,
  ).join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;

  res.setHeader('Content-Type', 'application/xml; charset=utf-8');
  res.setHeader('Cache-Control', 'public, max-age=86400');
  res.write(body);
  res.end();
  return { props: {} };
};

// Route only exists to serve the body above; nothing renders.
export default function Sitemap() {
  return null;
}
