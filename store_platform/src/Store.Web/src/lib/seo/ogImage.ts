/**
 * Where a pack's link-preview image lives.
 *
 * NOT UNDER `/api`. `next.config.ts` rewrites `/api/:path*` to the backend API origin, so the
 * conventional `/api/og/...` route used by most Next examples would be proxied straight past this
 * app and 404 from the API. The route is a normal page path for that reason alone, if the proxy
 * rule is ever removed, this is still correct, so there is no reason to move it back.
 *
 * `/og` is also NOT in the robots.txt disallow list (unlike `/api`), which matters: Google and
 * every social scraper must be able to fetch the image the page nominates. A blocked og:image is
 * the same as no og:image.
 *
 * One module so the route, the `og:image` meta, the Product schema, and the image sitemap can
 * never disagree about the URL, four call sites is exactly the number at which a hardcoded
 * string starts drifting.
 */

/**
 * Site-root-relative path of a pack's 1200x630 preview card.
 *
 * No `.png` extension: in the Pages Router a file named `[id].png.tsx` does not produce a dynamic
 * segment with a literal suffix, and every scraper that matters (Facebook, X, LinkedIn, Slack,
 * Discord, Google) reads the `Content-Type` response header rather than the URL. The route sets
 * `image/png` explicitly, so the extension would be decoration.
 */
export function packOgImagePath(packId: string): string {
  return `/og/pack/${encodeURIComponent(packId)}`;
}

/**
 * Site-root-relative path of the DEFAULT card, used by every page that does not render its own
 * (i.e. everything except pack pages). Lives here for the same reason `packOgImagePath` does: it
 * had drifted into two hardcoded `/og.png` strings, in `Seo.tsx` and in `schema.ts`'s Product
 * `image`, and this module exists precisely so the meta tag and the schema cannot disagree.
 *
 * THE `?v=` IS LOAD-BEARING, not decoration. Until 2026-08-14 `public/og.png` was the link-preview
 * card of a different product entirely ("The Intro Exchange"), shipped in `5f95ca7` and never
 * regenerated; it is now the Mumchimp card (`scripts/gen-brand-assets.mjs`). Every social scraper
 * caches a preview against the image URL and re-fetches on a timescale of weeks, not minutes --
 * Slack, X, LinkedIn, iMessage and Facebook all do, and Facebook's cache is only clearable by
 * hand through its Sharing Debugger. Replacing the BYTES at an unchanged URL therefore leaves the
 * wrong brand on every link already scraped, and on every new share that hits a warm cache. A new
 * URL is the one thing every scraper treats as a new image.
 *
 * Bump this date whenever `public/og.png` is regenerated with different content. It is a date
 * rather than an incrementing integer so the value says WHEN the card changed, which is the
 * question anyone reading a stale preview is actually asking.
 */
export const DEFAULT_OG_IMAGE_PATH = '/og.png?v=2026-08-14';
