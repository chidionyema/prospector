import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
const page = read('../pages/index.tsx');

/* Comments stripped where the assertion is "this construct is gone": every one of these changes
   leaves behind a comment naming what it replaced, which is the point of the comment and would
   otherwise read as the construct still being there. */
const stripComments = (src: string) =>
  src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

/**
 * The shelf has a shape (design critique 2026-08-05, section 7).
 *
 * MEASURED BEFORE
 *
 * `/` was 21,717px tall on desktop (24 screens) and 49,558px on mobile (59 screens). 73% of that
 * was the catalogue: 61 cards in one flat grid, no pagination, no lazy loading, no hierarchy
 * between pack #1 and pack #61. A shelf is supposed to dominate a storefront, so height alone was
 * never the defect -- the defect was that a buyer had no way to form a shortlist.
 *
 * WHAT IS PINNED HERE, AND WHY EACH ONE
 *
 * 1. The tail is capped but not unmounted. The obvious implementation of "paginate" is
 *    `tail.slice(0, 24).map(...)`, which silently removes 37 internal links from the server HTML
 *    and would also make the existing e2e ("a filtered URL comes back filtered") compare two
 *    different truncations. Hiding is the version that costs nothing but scroll.
 * 2. The editorial rows only exist on the default view. Once someone sorts by price, a row headed
 *    "Newest survivors" above their sorted results is the page arguing with them.
 * 3. No row heading may assert something we do not measure. This is why "Trending picks" is gone.
 */
describe('the shelf has editorial shape', () => {
  it('caps the tail with a browse-all control instead of an endless grid', () => {
    expect(page, 'a page size must be declared, not implied').toMatch(/SHELF_PAGE\s*=\s*\d+/);
    expect(page, 'the cap must be releasable by the buyer').toMatch(/setShowAll\(true\)/);
    expect(page, 'the control must say how many it opens').toMatch(/Browse all \{/);
  });

  it('hides the capped cards rather than dropping them from the DOM', () => {
    // The failure this catches is a "tidy-up" refactor to `.slice(0, shown).map(...)`: green on
    // every unit test, and it quietly strips the catalogue's internal links out of the HTML.
    expect(page).toMatch(/i >= shown && 'hidden'/);
    expect(
      /tailPacks\.slice\(\s*0\s*,\s*shown/.test(page),
      'the tail must be rendered in full and hidden, never sliced away',
    ).toBe(false);
  });

  it('gates the editorial rows on the visitor not having stated an order', () => {
    expect(page).toMatch(/const editorial = !filtered && sort === 'newest'/);
    expect(page, 'the newest row must come from the editorial gate').toMatch(
      /const newestRow = editorial \?/,
    );
  });

  it('no shelf row claims something the site does not measure', () => {
    // "Trending" is a traffic claim, and nothing here counts traffic. The row was always ordered
    // by `sourceCount`; the heading now says that, and every card under it prints the number, so
    // the claim is checkable against the thing directly below it.
    expect(page, 'an unmeasured popularity claim must not return').not.toMatch(/Trending picks/);
    expect(page).toMatch(/>Most sources</);
  });
});

/**
 * The pack page proves rather than decorates (design critique 2026-08-05, section 6).
 *
 * The title was in the DOM 7 times, three of them inside the fold (breadcrumb, cover caption,
 * 60px h1), and a ~550px empty plate held the prime visual slot. See the header comment on
 * `DossierExcerptPlate` for why a cover cannot carry this page's claim.
 */
describe('the pack page opens on evidence', () => {
  const packPage = read('../pages/pack/[id].tsx');

  it('renders the title once inside the fold', () => {
    // Scoped to the rendered trail. `breadcrumbNode(...)` still carries the full title, and must:
    // that is JSON-LD for a search result, where the title IS the label, and it costs no pixels.
    const trail = /<Breadcrumbs[\s\S]*?\/>/.exec(stripComments(packPage));
    expect(trail, 'pack/[id].tsx must render <Breadcrumbs />').not.toBeNull();
    expect(trail![0], 'the visible trail must not repeat the h1').not.toMatch(/pack\.title/);
    expect((packPage.match(/<h1\b/g) ?? []).length, 'exactly one h1').toBe(1);
  });

  it('does not size the h1 up to the display step', () => {
    // Titles here average ~90 characters. At --text-display (48px) the h1 alone ran ~400px and
    // was still unfinished at the fold boundary, which is what pushed the product off screen.
    const h1 = /<h1 className="([^"]*)"/.exec(packPage);
    expect(h1, 'pack/[id].tsx must have an h1').not.toBeNull();
    expect(h1![1], 'one type step, no md: bump').not.toMatch(/text-display/);
    expect(h1![1]).toMatch(/\btext-h1\b/);
  });

  it('moves share below the article', () => {
    // Share sat at y~247, above the product, before the visitor knew what it was.
    const share = packPage.indexOf('<ShareRow');
    const similar = packPage.indexOf('<SimilarPacks');
    expect(share, 'ShareRow must still be rendered').toBeGreaterThan(0);
    expect(share, 'share belongs after the article, not above it').toBeGreaterThan(similar);
  });
});
