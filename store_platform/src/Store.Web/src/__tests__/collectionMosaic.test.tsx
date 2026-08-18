import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { CollectionMosaic, bandFor, type MosaicTile } from '@/components/marketing/CollectionMosaic';

/**
 * THE MOSAIC (MASTER-BRIEF §7 `/collections`).
 *
 * Three properties, and each one is a defect the brief names: tiles sized by pack count, the SHORT
 * display name rendered rather than the SEO h1 the live page truncated to "Busin…", and every tile
 * pointing at a pre-filtered catalogue URL rather than a page of its own.
 */

const tiles: MosaicTile[] = [
  { slug: 'big', name: 'Evenings', longName: 'Business ideas you can start in the evenings', count: 40 },
  { slug: 'mid', name: 'Vertical software', longName: 'Vertical software ideas', count: 18 },
  { slug: 'small', name: 'Care and benefits', longName: 'Business ideas in care and benefits', count: 5 },
];

const html = renderToStaticMarkup(<CollectionMosaic tiles={tiles} />);

describe('bandFor sizes a tile against the shelf, not against a typed number', () => {
  it('gives the largest collection the largest band', () => {
    expect(bandFor(40, 40)).toBe(2);
  });

  it('scales with the shelf rather than a hardcoded threshold', () => {
    // The same count is a big tile on a small shelf and a small one on a large shelf. A typed
    // "40 is big" would make every tile large the month the catalogue doubles.
    expect(bandFor(20, 20)).toBe(2);
    expect(bandFor(20, 200)).toBe(0);
  });

  it('never divides by an empty shelf', () => {
    expect(bandFor(0, 0)).toBe(0);
  });
});

describe('the mosaic', () => {
  it('renders one tile per collection, biggest first', () => {
    expect(html.split('<li').length - 1).toBe(3);
    expect(html.indexOf('Evenings')).toBeLessThan(html.indexOf('Vertical software'));
    expect(html.indexOf('Vertical software')).toBeLessThan(html.indexOf('Care and benefits'));
  });

  it('sizes the tiles differently, which is the whole point of a mosaic', () => {
    // A grid of equal tiles says every collection is the same size. They are not.
    const spans = new Set(
      [...html.matchAll(/sm:col-span-(\d)/g)].map((m) => m[1]),
    );
    expect(spans.size).toBeGreaterThan(1);
  });

  it('renders the short name, never the SEO h1, and never truncates', () => {
    // §9: "Never truncate text by character budget." The live page CSS-clipped the long name to
    // "Busin…". The fix is a shorter source string, which is what `name` is.
    expect(html).toContain('Evenings');
    expect(html).not.toContain('…');
    // The long form is still available -- to a screen reader and in the title attribute -- so
    // nothing is lost, it is just not what gets drawn in a 7rem tile.
    expect(html).toContain('Business ideas you can start in the evenings');
  });

  it('links every tile to a pre-filtered catalogue URL', () => {
    expect(html).toContain('href="/collections/big"');
    expect(html).not.toContain('/ideas/');
  });

  it('states the count on every tile, and gets the singular right', () => {
    const one = renderToStaticMarkup(
      <CollectionMosaic tiles={[{ slug: 'x', name: 'X', longName: 'X ideas', count: 1 }]} />,
    );
    expect(one).toContain('1 pack');
    expect(one).not.toContain('1 packs');
    expect(html).toContain('40 packs');
  });

  it('drops empty collections rather than drawing a tile onto nothing', () => {
    const withEmpty = renderToStaticMarkup(
      <CollectionMosaic tiles={[...tiles, { slug: 'none', name: 'None', longName: 'None', count: 0 }]} />,
    );
    expect(withEmpty.split('<li').length - 1).toBe(3);
  });

  it('renders nothing at all when the shelf is empty', () => {
    expect(renderToStaticMarkup(<CollectionMosaic tiles={[]} />)).toBe('');
  });

  it('carries a focus ring, because this is sixteen links in a grid', () => {
    // Section 9 accessibility: focus-visible ring on every interactive element. A mosaic is exactly
    // the layout where a keyboard user loses their place without one.
    //
    // THIS ASSERTION USED TO PIN THE BROKEN VERSION. It required `focus-visible:ring-2`, which the
    // tiles carried along with `focus-visible:ring-link` and `focus-visible:outline-none`. There is
    // no `--color-link`, so Tailwind emitted no colour for the ring, and `outline-none` had already
    // removed the global one: these tiles had no focus indicator at all and this test was green.
    // A class name is not a rendered ring, and the only way to tell the difference is to name the
    // colour and check it resolves.
    expect(html).toContain('focus-visible:outline-2');
    expect(html).toContain('focus-visible:outline-offset-2');
    expect(html).toContain('focus-visible:outline-focus');
    expect(html).not.toContain('focus-visible:outline-none');
    expect(html).not.toContain('ring-link');
  });
});
