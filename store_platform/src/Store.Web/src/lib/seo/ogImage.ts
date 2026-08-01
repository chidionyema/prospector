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
