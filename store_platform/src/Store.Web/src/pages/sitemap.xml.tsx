import type { GetServerSideProps } from 'next';

import { fetchCatalog } from '@/lib/api/client';
import { eligibleLandings, packMatchesLanding } from '@/lib/seo/landings';
import { packOgImagePath } from '@/lib/seo/ogImage';

/**
 * Dynamic /sitemap.xml, the PUBLIC marketing pages, plus one entry per live pack. Authed,
 * transactional, and identity-blind pitch surfaces are deliberately excluded (they're noindex and
 * must not be discoverable). Host is derived from the request so the URLs are correct on every
 * environment without a baked domain.
 */

// Public, indexable routes. Kept as an explicit allow-list, not a directory scan, so a new authed
// page never leaks into the sitemap by accident. `/pack/*` and `/ideas/*` are NOT here, both are
// generated from the live catalogue below, because the set changes on every publish.
//
// `/llms.txt` is deliberately absent: it is a machine-readable index found by convention at a fixed
// path, not a page we want turning up as a search result for a human.
const PUBLIC_PATHS = [
  '/',
  '/how-it-works',
  '/sample',
  '/kill-log',
  '/faq',
  '/ideas',
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

// A pack id is interpolated straight into the XML body below, so it gets the same treatment the
// Host header already gets in `originFromReq`: accept a clean slug or drop the entry. Omitting one
// URL from a crawl hint is a non-event; a corrupted sitemap makes every other URL unreadable too.
const SAFE_PACK_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** `verifiedAt` arrives as an ISO timestamp ("2026-07-31T02:19:33.616927"). Take the date only,
 *  and only when it really is one, a malformed value falls back to the build date rather than
 *  emitting a `<lastmod>` a crawler will reject. */
function packLastmod(verifiedAt: string | undefined, fallback: string): string {
  const date = verifiedAt?.slice(0, 10);
  return date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : fallback;
}

// `image` is the absolute URL of the page's own social card, when it has one. Only the pack pages
// do (see `lib/seo/ogImage.ts`); an image sitemap entry is how that card gets discovered for image
// search, which a crawler will not otherwise do for a URL it has to render to find.
//
// No `<priority>`: Google states it ignores the element, so emitting one is noise that reads like a
// signal. `<changefreq>` stays because it was already here and is equally advisory.
function urlEntry(loc: string, lastmod: string, changefreq: string, image?: string): string {
  const imageTag = image ? `<image:image><image:loc>${image}</image:loc></image:image>` : '';
  return `  <url><loc>${loc}</loc><lastmod>${lastmod}</lastmod><changefreq>${changefreq}</changefreq>${imageTag}</url>`;
}

export const getServerSideProps: GetServerSideProps = async ({ req, res }) => {
  const origin = originFromReq(req.headers as { host?: string; 'x-forwarded-proto'?: string });
  // `lastmod` is the build date (these are static pages rebuilt on deploy). Derived from the build,
  // not request time, so a crawl doesn't see the timestamp churn on every hit.
  const lastmod = (process.env.NEXT_PUBLIC_BUILD_DATE || new Date().toISOString().slice(0, 10)).slice(0, 10);

  // Every live pack already renders a public, indexable page (no `noindex`, canonical emitted by
  // `Seo`, and `/pack` is not in the robots.txt DISALLOW list) and is linked from the shelf on `/`.
  // Listing them here does not change what is exposed, it only stops discovery depending entirely
  // on a crawler walking 42 links off the home page.
  //
  // Best-effort, like `fetchCatalogStats`: a catalogue outage must degrade this to the marketing
  // pages, never 500 the sitemap. A sitemap that fails to load is worse than a short one.
  let packEntries: string[] = [];
  let landingEntries: string[] = [];
  try {
    const packs = await fetchCatalog();
    const safe = packs.filter((pack) => SAFE_PACK_ID.test(pack.id));
    packEntries = safe.map((pack) =>
      urlEntry(
        `${origin}/pack/${pack.id}`,
        packLastmod(pack.verifiedAt, lastmod),
        'monthly',
        `${origin}${packOgImagePath(pack.id)}`,
      ),
    );

    // Only the landings the live catalogue can actually fill, the same eligibility check the pages
    // themselves run, so the sitemap can never advertise a URL that 404s on arrival. A landing's
    // `lastmod` is the newest verification date among its own packs: that is genuinely when the page
    // last changed, and it is what makes a re-crawl worth the crawler's time after a publish.
    landingEntries = eligibleLandings(safe).map(({ landing }) => {
      const dates = safe
        .filter((pack) => packMatchesLanding(pack, landing))
        .map((pack) => packLastmod(pack.verifiedAt, lastmod));
      const newest = dates.length > 0 ? dates.reduce((a, b) => (a > b ? a : b)) : lastmod;
      return urlEntry(`${origin}/ideas/${landing.slug}`, newest, 'weekly');
    });
  } catch (error) {
    console.error('Sitemap: catalog fetch failed, emitting marketing pages only:', error);
  }

  const urls = [
    ...PUBLIC_PATHS.map((p) => urlEntry(`${origin}${p === '/' ? '' : p}`, lastmod, changefreqFor(p))),
    ...landingEntries,
    ...packEntries,
  ].join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n${urls}\n</urlset>\n`;

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
