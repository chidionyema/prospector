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
  '/for-buyers',
  '/for-connectors',
  '/pricing',
  '/faq',
  '/guides',
  '/guides/how-to-get-a-warm-introduction',
  '/guides/warm-intro-vs-cold-outreach',
  '/guides/introduction-email-templates',
  '/guides/what-to-pay-for-an-introduction',
  '/terms',
  '/privacy',
  '/remove-me',
  '/register',
  '/login',
];

function originFromReq(headers: { host?: string; 'x-forwarded-proto'?: string }): string {
  const host = headers.host ?? 'localhost:3000';
  const proto = headers['x-forwarded-proto'] ?? (host.startsWith('localhost') ? 'http' : 'https');
  return `${proto}://${host}`;
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
