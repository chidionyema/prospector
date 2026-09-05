import { OG } from '@/lib/design/ogPalette';
import { ImageResponse } from 'next/og';
import type { GetServerSideProps } from 'next';

import { ApiError, fetchPackDetails } from '@/lib/api/client';
import { evidenceRun } from '@/lib/evidenceTicks';

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

/*
 * Brand v3 (2026-08-06). The card is ink on near-white with one hairline rule, matching the
 * storefront. The colours come from `lib/design/ogPalette.ts`, which is checked against
 * `tokens.css` by a test -- Satori resolves no CSS custom properties, so the card must carry
 * literal hexes, and every one of the four this comment used to list had drifted from its token.
 *
 * The vermillion is gone with the rest of brand v2. The card keeps a near-white rather than pure
 * white ground for a reason that is specific to this surface: a social card renders against an
 * arbitrary background, and a pure-white card with no border disappears into a light timeline.
 * `BORDER` is drawn as a full 2px frame for the same reason -- the storefront can rely on the
 * viewport edge, a 1200x630 image cannot.
 */
const { ink: INK, cream: CREAM, border: BORDER, subtle: MUTED, survive: SURVIVE, onInk: ON_INK } = OG;


/**
 * THE CITED-SOURCE RUN, drawn on the share card.
 *
 * WHY IT IS HERE. This card was all type: a headline, a title, a price pill, and one grey line
 * reading "34 sources cited". The count -- the single fact this shop sells, and the only number on
 * the card that differs meaningfully between two packs -- was set at 24px in the muted grey used
 * for timestamps, below the brand name, in a card whose largest element was the title. A link
 * preview is read at thumbnail size in a timeline; nothing at 24px survives that.
 *
 * WHY THIS DRAWING AND NOT AN ILLUSTRATION. `docs/SITE_SPEC_PROGRAM.md:28` permits exactly one kind
 * of visual -- "every visual is generated from real engine data (verdicts, source counts, kill
 * ratios)" -- and forbids the alternatives by name. A run of ticks counted off the pack's own
 * `sourceCount` is that, with nothing to amend and no model to run. It is also the drawing already
 * on the shelf card, which is the point: the two surfaces now show one pack one way.
 *
 * The digits stay in `proofLine` beneath it. A chart without its figure is decoration.
 *
 * SATORI. `display: flex` is set explicitly on every container: satori throws on a div with
 * multiple children and no display, and it does not inherit the browser's default. Widths are px
 * literals for the same reason the radius below is -- no CSS variables, no Tailwind.
 */
const OG_TICK_TRACK = 76;
const OG_TICK_WIDTH = 7;
const OG_TICK_GAP = 5;

export function EvidenceRunOg({ count }: { count: number | undefined }) {
  const { ticks, over, shown } = evidenceRun(count, { track: OG_TICK_TRACK });
  // No count, no element -- not an empty track. Same rule as the shelf bar: an empty evidence
  // drawing on a card selling evidence says "we checked and found none", when the truth is "this
  // field is absent". The card then falls back to type alone, exactly as it rendered before.
  if (shown === 0) return null;

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', height: OG_TICK_TRACK }}>
      {ticks.map((t, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            width: OG_TICK_WIDTH,
            height: t.height,
            marginRight: OG_TICK_GAP,
            backgroundColor: SURVIVE,
            opacity: t.opacity,
          }}
        />
      ))}
      {over && (
        <div
          style={{
            display: 'flex',
            width: OG_TICK_WIDTH,
            height: OG_TICK_TRACK,
            marginLeft: OG_TICK_GAP,
            backgroundColor: SURVIVE,
            opacity: 0.4,
          }}
        />
      )}
    </div>
  );
}

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

/**
 * THE CARD, as a tree, separated from the route that fetches for it.
 *
 * It is here rather than inline in `getServerSideProps` so the drawing can be rendered without a
 * running Next server -- satori accepts only a subset of CSS and fails at REQUEST time on a tree
 * that is perfectly valid React, on a route whose output social platforms then cache for days. A
 * card that can only be rendered by starting a dev server, fetching a live pack and looking at a
 * PNG is a card nobody checks. This split is what lets a test render the real thing.
 */
export function PackOgCard({
  title,
  proof,
  price,
  sourceCount,
}: {
  title: string;
  proof: string;
  price?: string;
  sourceCount?: number;
}) {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        backgroundColor: CREAM,
        padding: '72px 80px',
        // A hairline frame plus an ink rule down the left edge, so the card is recognisable as
        // this site at thumbnail size before any of the text is legible.
        border: `2px solid ${BORDER}`,
        borderLeft: `16px solid ${INK}`,
        fontFamily: 'sans-serif',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', fontSize: 26, color: MUTED, fontWeight: 500 }}>
          Researched. Priced. Ready to build.
        </div>
        <div
          style={{
            display: 'flex',
            marginTop: 28,
            fontSize: title.length > 60 ? 58 : 70,
            lineHeight: 1.12,
            fontWeight: 600,
            color: INK,
            letterSpacing: -1.5,
          }}
        >
          {title}
        </div>
      </div>

      {/* The run sits between the title and the footer rather than beside the proof line, so it
          is a band the eye lands on at thumbnail size rather than an ornament on a caption. */}
      <EvidenceRunOg count={sourceCount} />

      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', fontSize: 34, fontWeight: 600, color: INK, letterSpacing: -0.7 }}>
            Mumchimp
          </div>
          {proof ? (
            <div style={{ display: 'flex', marginTop: 8, fontSize: 24, color: MUTED }}>{proof}</div>
          ) : null}
        </div>
        <div
          style={{
            display: 'flex',
            backgroundColor: INK,
            color: ON_INK,
            // The storefront's whole radius scale is 2px (`--radius-sm`/`--radius-md`,
            // tokens.css:544-545). An 8px pill here made the social card the only surface
            // in the system with a soft corner. Raw number because Satori cannot read CSS vars.
            borderRadius: 2,
            padding: '16px 36px',
            fontSize: 32,
            fontWeight: 600,
          }}
        >
          {/* No `|| '£49'`: a pack whose price did not load renders no price. The OG card is
               cached by every social platform that scrapes it, so a guessed number here
               outlives any fix. */}
          {price || ''}
        </div>
      </div>
    </div>
  );
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
    <PackOgCard title={title} proof={proof} price={pack.price} sourceCount={pack.sourceCount} />,
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
