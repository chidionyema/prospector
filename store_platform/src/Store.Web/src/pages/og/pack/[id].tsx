import { ImageResponse } from 'next/og';
import type { GetServerSideProps } from 'next';

import { ApiError, fetchPackDetails } from '@/lib/api/client';

/**
 * Per-pack 1200x630 link-preview card.
 *
 * WHY. Every pack page previously nominated the same generic `/og.png`, so 49 different products
 * shared one image on X, LinkedIn, Slack, iMessage, and in the citation cards AI assistants now
 * render. The preview image is the largest element of a shared link and the only part that is
 * pack-specific here, a card naming the actual idea is the difference between a share that reads
 * as "someone linked a shop" and one that reads as "someone linked *this* business idea".
 *
 * WHERE. Not under `/api`: `next.config.ts` rewrites `/api/:path*` to the backend, and an array
 * rewrite is evaluated after static pages but BEFORE dynamic routes, so a dynamic
 * `/api/og/pack/[id]` route would lose to the proxy and 404 from the API. See `lib/seo/ogImage.ts`.
 *
 * RUNTIME. Rendered with `next/og` (satori + resvg, both bundled with Next, no new dependency)
 * from `getServerSideProps` on the Node runtime, then written to the response as raw PNG bytes.
 * The Pages Router's documented path for `ImageResponse` is an edge API route, which is unavailable
 * to us for the routing reason above; `ImageResponse` is a plain `Response`, so consuming its body
 * here is well-defined rather than a trick.
 *
 * FONT. Deliberately the container's default sans rather than a fetched webfont. Fetching Hanken
 * Grotesk per request would add a network hop to every scrape and a second failure mode, for a
 * difference no one comparing two link previews will ever see.
 */

export const OG_WIDTH = 1200;
export const OG_HEIGHT = 630;

/** Brand v2 (2026-08-05): vermillion is the new primary; the OG image must
 *  match the live site. Cream is gone (clean white is the canvas); the
 *  OG image still uses a subtle off-white because the social card
 *  renders against any background and a white-on-white card disappears. */
const VERMILLION = '#FF5A1F';
const CREAM = '#FAFAF8';
const MUTED = '#6B6B6B';

/** Long titles must not overflow the card. Cut on a word boundary and ellipsize, so the card
 *  degrades to a readable truncation rather than clipped glyphs at the frame edge. */
export function fitTitle(title: string, max = 95): string {
  if (title.length <= max) return title;
  const cut = title.slice(0, max);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 40 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

/** The trust line under the title, built only from facts the pack page itself displays. Returns
 *  an empty string for a pack carrying neither, so the card shows no line rather than "0 sources". */
export function proofLine(sourceCount: number | undefined, verifiedAt: string | undefined): string {
  const parts: string[] = [];
  if (typeof sourceCount === 'number' && sourceCount > 0) {
    parts.push(`${sourceCount} sources cited`);
  }
  const date = verifiedAt?.slice(0, 10);
  if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) parts.push(`verified ${date}`);
  return parts.join('  ·  ');
}

export const getServerSideProps: GetServerSideProps = async ({ params, res }) => {
  const id = typeof params?.id === 'string' ? params.id : '';
  if (!id) return { notFound: true };

  let pack: Awaited<ReturnType<typeof fetchPackDetails>>;
  try {
    pack = await fetchPackDetails(id);
  } catch (error) {
    // Never a blank card. A scraper that receives an error falls back to the page's other
    // signals; one that receives a valid-looking empty image caches it, and social platforms
    // cache preview images for days.
    //
    // Which error matters, for the same caching reason: an unknown id is genuinely gone (404),
    // but an unreachable API is temporary and must not be recorded as gone, hence the status on
    // ApiError. `notFound` cannot express the second case at all: Next overrides `res.statusCode`
    // when `notFound` is returned, so a 503 set alongside it is served as 404 (measured on
    // /ideas/[slug], 2026-08-01).
    const status = error instanceof ApiError ? error.status : 503;
    if (status === 404 || status === 410) return { notFound: true };
    res.statusCode = 503;
    res.setHeader('Retry-After', '120');
    res.end();
    return { props: {} };
  }

  const title = fitTitle(pack.title ?? '');
  const proof = proofLine(pack.sourceCount, pack.verifiedAt);

  const image = new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          backgroundColor: CREAM,
          padding: '72px 80px',
          // The brand's teal edge, so the card is recognisable as this site at thumbnail size
          // before any of the text is legible.
          borderLeft: `24px solid ${VERMILLION}`,
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              display: 'flex',
              fontSize: 26,
              letterSpacing: 2,
              textTransform: 'uppercase',
              color: MUTED,
              fontWeight: 700,
            }}
          >
            Survived six brutal checks
          </div>
          <div
            style={{
              display: 'flex',
              marginTop: 28,
              fontSize: title.length > 60 ? 58 : 70,
              lineHeight: 1.12,
              fontWeight: 800,
              color: VERMILLION,
              letterSpacing: -1.5,
            }}
          >
            {title}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', fontSize: 34, fontWeight: 800, color: VERMILLION }}>
              Mumchimp
            </div>
            {proof ? (
              <div style={{ display: 'flex', marginTop: 8, fontSize: 24, color: MUTED }}>{proof}</div>
            ) : null}
          </div>
          <div
            style={{
              display: 'flex',
              backgroundColor: VERMILLION,
              color: CREAM,
              borderRadius: 999,
              padding: '16px 36px',
              fontSize: 32,
              fontWeight: 800,
            }}
          >
            {/* No `|| '£49'`: a pack whose price did not load renders no price. The OG card is
                 cached by every social platform that scrapes it, so a guessed number here
                 outlives any fix. */}
            {pack.price || ''}
          </div>
        </div>
      </div>
    ),
    { width: OG_WIDTH, height: OG_HEIGHT },
  );

  const body = Buffer.from(await image.arrayBuffer());
  res.setHeader('Content-Type', 'image/png');
  // Long cache: the card only changes when the pack's title or price does, and social platforms
  // re-scrape on their own schedule anyway. `stale-while-revalidate` keeps a slow render off the
  // critical path of a scrape once the entry ages out.
  res.setHeader('Cache-Control', 'public, max-age=86400, stale-while-revalidate=604800');
  res.setHeader('Content-Length', String(body.length));
  res.end(body);

  return { props: {} };
};

// Route only exists to serve the bytes above; nothing renders.
export default function PackOgImage() {
  return null;
}
