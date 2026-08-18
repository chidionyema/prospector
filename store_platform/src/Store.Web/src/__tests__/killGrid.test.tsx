import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { KillGrid } from '@/components/marketing/KillGrid';
import { RESEARCH_STATS } from '@/lib/stats';
import type { Pack } from '@/lib/api/client';

/**
 * THE KILL GRID'S CONTRACT (MASTER-BRIEF §7).
 *
 * The brief states this device as five properties, and four of them are the kind that rot silently:
 * a component keeps rendering, looks roughly right, and has quietly become 1,444 nodes or has
 * stopped linking its survivors. So each one is asserted here against the RENDERED MARKUP rather
 * than against the source, except the one that is genuinely a source property (no client JS).
 *
 *   one `<path>` for every dead cell     -- the payload argument
 *   one `<rect>` per listed pack, in an `<a>` with a `<title>`  -- the interactivity argument
 *   `viewBox` derived from the population -- so a bigger batch cannot overflow the last row
 *   oldest first                          -- the only claim the picture makes about position
 *   zero client JS                        -- it sits on the LCP screen
 *
 * And one property the brief does NOT state, which outranks it: the survivor count is never
 * printed. `mockups/index.html:296` prints it; the founder's directive of 2026-08-13 forbids it and
 * `lib/stats.ts` does not export it. A test is what keeps the mockup from being copied back in.
 */

const SOURCE = readFileSync(
  fileURLToPath(new URL('../components/marketing/KillGrid.tsx', import.meta.url)),
  'utf8',
);

/**
 * The source with its comments removed, and every source assertion below runs against THIS.
 *
 * The first version scanned `SOURCE` and failed on `dangerouslySetInnerHTML` -- a string that
 * appears in the component's docblock, explaining that the component it replaced used one and this
 * one does not. A scanner that cannot tell a MENTION from a USE reports the sentence saying "we do
 * not do this" as evidence that we do it, and the only way to make it pass is to stop writing down
 * why. Strip the comments and the assertion is about the code.
 */
const CODE = SOURCE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

/** The minimum a `Pack` needs to render here. Dates ascend with the index. */
function pack(n: number, verifiedAt?: string): Pack {
  return {
    id: `pack-${n}`,
    title: `Pack number ${n}`,
    oneLine: 'A line.',
    price: '£49',
    paymentProvider: 'stripe',
    providerPriceId: `price_${n}`,
    verifiedAt,
  } as Pack;
}

const SHELF: Pack[] = [
  pack(3, '2026-03-01T00:00:00Z'),
  pack(1, '2026-01-01T00:00:00Z'),
  pack(4, undefined),
  pack(2, '2026-02-01T00:00:00Z'),
];

const html = renderToStaticMarkup(<KillGrid packs={SHELF} />);

describe('the kill grid', () => {
  it('draws every dead cell in exactly one path', () => {
    const paths = html.match(/<path\b/g) ?? [];
    expect(paths, 'one path, or the payload argument is gone').toHaveLength(1);

    // Non-vacuity: the path must actually carry the field. One subpath per dead cell.
    const d = /<path d="([^"]*)"/.exec(html)?.[1] ?? '';
    const subpaths = d.match(/M/g) ?? [];
    expect(subpaths).toHaveLength(RESEARCH_STATS.researched - SHELF.length);
  });

  it('gives every listed pack its own rect, inside a link, with a name', () => {
    const rects = html.match(/<rect\b/g) ?? [];
    expect(rects).toHaveLength(SHELF.length);

    for (const p of SHELF) {
      expect(html, `${p.id} must link to its pack page`).toContain(`href="/pack/${p.id}"`);
      expect(html, `${p.id} must carry its own accessible name`).toContain(
        `<title>${p.title}</title>`,
      );
    }
    // The name must be INSIDE the link, or the link has no accessible name at all.
    expect(html).toMatch(/<a href="\/pack\/pack-1"><title>Pack number 1<\/title><rect\b/);
  });

  it('lands the survivors oldest first, with an undated pack last', () => {
    const order = [...html.matchAll(/href="\/pack\/(pack-\d+)"/g)].map((m) => m[1]);
    // Dates ascend 1 -> 2 -> 3; pack-4 has no `verifiedAt` and must not jump the queue.
    expect(order).toEqual(['pack-1', 'pack-2', 'pack-3', 'pack-4']);
  });

  it('gives no two survivors the same cell', () => {
    const cells = [...html.matchAll(/<rect x="([\d.]+)" y="([\d.]+)"/g)].map(
      (m) => `${m[1]},${m[2]}`,
    );
    expect(new Set(cells).size, 'a collision silently loses a pack from the picture').toBe(
      cells.length,
    );
  });

  it('derives the viewBox from the population rather than typing it', () => {
    const side = Math.ceil(Math.sqrt(RESEARCH_STATS.researched));
    expect(html).toContain(`viewBox="0 0 ${side} ${side}"`);
    // The brief's own number, as a check that the derivation agrees with it at today's totals.
    // If this line fails and the one above passes, the population grew -- that is not a defect.
    expect(side, "MASTER-BRIEF §7 says viewBox='0 0 38 38'").toBe(38);
  });

  it('is a picture, not a picket fence, and its links survive the role', () => {
    // `role="img"` would prune the subtree and hide all four links. See the component's note.
    expect(html).toContain('role="group"');
    expect(html, 'role="img" would hide every survivor link').not.toContain('role="img"');
    expect(html, 'the kill total belongs in the description, not in visible text').toMatch(
      /<desc>[^<]*killed on cited evidence/,
    );
  });

  it('never prints the survivor count', () => {
    // Strip the markup and look at what a reader actually sees. The shelf size must not appear as
    // a figure anywhere in it -- not in the legend, not in the caption.
    const visible = html.replace(/<title>[\s\S]*?<\/title>/g, '')
      .replace(/<desc>[\s\S]*?<\/desc>/g, '')
      .replace(/<[^>]+>/g, ' ');
    expect(visible).not.toMatch(new RegExp(`\\b${SHELF.length}\\b`));
    // ...while the total IS printed, because it is the scale label of the picture.
    expect(visible.replace(/\D/g, '')).toContain(String(RESEARCH_STATS.researched));
  });

  it('renders nothing when the shelf is empty, because that is an outage', () => {
    expect(renderToStaticMarkup(<KillGrid packs={[]} />)).toBe('');
  });

  it('ships zero client JavaScript', () => {
    // It sits on the screen whose LCP budget is defended all over `pages/index.tsx`.
    expect(CODE, "no 'use client'").not.toMatch(/['"]use client['"]/);
    for (const hook of ['useState', 'useEffect', 'useMemo', 'useRef', 'useLayoutEffect']) {
      expect(CODE, `${hook} would make this an interactive component`).not.toContain(hook);
    }
    expect(CODE, 'no innerHTML: the field is real SVG elements').not.toContain(
      'dangerouslySetInnerHTML',
    );
  });
});
