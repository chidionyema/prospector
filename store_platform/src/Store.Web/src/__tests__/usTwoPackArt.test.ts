import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import type { Pack } from '@/lib/api/client';
import { packLeadStat } from '@/lib/packStat';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function existsRelative(relativePath: string): boolean {
  return existsSync(fileURLToPath(new URL(relativePath, import.meta.url)));
}

/**
 * US-2 — Pack cards with pack art.
 *
 * The audit (§4.2) found 45 identical left-rule documents on the catalogue — no
 * imagery, no per-pack visual identity, no way to tell a "story book for autistic
 * kids" from a "shower drain unblocker" without reading the title. The fix is a
 * cover plate on every pack card (1:1) and every pack detail page (16:9 hero).
 *
 * Out of scope (per the spec): generating 60 unique covers. The implementation
 * derives the cover from the pack's category — the same category colour and
 * icon the rest of the site already uses — so every pack has a *distinct*
 * identity without needing bespoke art.
 */
describe('US-2 — Pack cards with pack art', () => {
  const coverExists = existsRelative('../components/marketing/PackCover.tsx');
  const page = readSource('../pages/index.tsx');
  const packPage = readSource('../pages/pack/[id].tsx');

  it('declares a PackCover component', () => {
    expect(coverExists, 'components/marketing/PackCover.tsx must exist').toBe(true);
  });

  it('PackCover takes a pack, and no longer takes a variant', () => {
    /*
     * The `variant` half of this assertion is INVERTED, not relaxed.
     *
     * `square | hero` existed because one component drew two coloured plates: a 1:1 tile on the
     * shelf and a 16:9 hero on the detail page. Both are gone (see the component's header comment
     * and the pack-page test below); what survives is a single 44px identity row, and the shelf
     * card composes that row itself rather than importing a component to draw it. A `variant`
     * prop with one variant is an invitation to add the second one back.
     */
    if (!coverExists) return;
    const source = readSource('../components/marketing/PackCover.tsx');
    expect(
      /pack\s*:\s*Pack\b/.test(source),
      'PackCover must accept a pack prop typed Pack',
    ).toBe(true);
    expect(
      /variant\s*[:?]/.test(source),
      'PackCover must not carry a variant prop: there is only one form now',
    ).toBe(false);
  });

  it('PackCover renders a category-coloured cover with an icon', () => {
    // The cover is the existing category gradient + category icon. This is the same
    // visual identity the rest of the site uses; the cover just makes it visible
    // on every pack card and every pack detail page.
    if (!coverExists) return;
    const source = readSource('../components/marketing/PackCover.tsx');
    const usesCategory =
      /categoryFor|coverFor|category\.cover|cat\.icon|cat\.chip/.test(source);
    expect(
      usesCategory,
      'PackCover must derive its visual from the pack\'s category',
    ).toBe(true);
  });

  it('every PackCard still carries a per-pack identity, and it is now a number', () => {
    /*
     * US-2's actual problem was that 45 cards were indistinguishable without reading the title.
     * This test has always asserted that the PROBLEM stays solved rather than pinning any one
     * drawing of it, and the drawing has now been withdrawn twice:
     *
     *   1. the 1:1 category tile (withdrawn 2026-08-06) -- sixty-one gradient tiles are as
     *      uniform as sixty-one white rectangles, they are just louder about it;
     *   2. `PackCoverArt`, the 112px instrument plate carrying `PackMark` (withdrawn 2026-08-14)
     *      -- at 112px it took roughly 60% of a card and read as the placeholder where a product
     *      image failed to load, and the mark inside it was computed by hashing `pack.id`, so it
     *      encoded nothing about the pack it identified.
     *
     * The assertions that pinned #2 by name (`<PackCoverArt ... category={cat}`, the plate's
     * `bg-ins-bg`, its literal radial-gradient class, `For {marketLabel(pack.market)} rules`) are
     * REPLACED rather than deleted, because the rule they served is unchanged and is the reason
     * this file exists: a card must carry something that is true of THIS pack and of no other.
     *
     * That something is now the pack's own strongest figure, set as type (`lib/packStat.ts`,
     * `PackFigure` in index.tsx). It is a stronger satisfaction of the rule than either cover:
     * a tile encoded the sector, which 51 other packs share; a hashed mark encoded nothing at
     * all; a number is a fact about this pack that the buyer can act on and that differs card to
     * card. Measured on the live catalogue 2026-08-14: 39 of 62 packs lead with the modelled
     * price multiple (1x to 123x) and the remaining 23 with their cited source count (17 to 51).
     */
    expect(page, 'the card must still read the pack category for its sector label').toMatch(
      /const cat = categoryFor\(pack\)/,
    );
    expect(page, 'the card must compute one lead figure per pack').toMatch(
      /const stat = packLeadStat\(pack\)/,
    );

    /*
     * ALL THREE VARIANTS, ONE DEVICE. The row, the lead poster and the shelf card each render the
     * SAME component at a different size. Pinning "three mounts, one per weight" is what stops
     * the treatment drifting into three treatments, which is how the shelf got flat the first
     * time: the row list and the grid stopped stating the same fact the same way.
     */
    // TWO variants, was three (2026-08-15, the founder's mobile brief). `mid` is deleted and
    // `row` moved to `components/discovery/PackRow.tsx`, so the two mounts are in two files. What
    // this pins is unchanged: EVERY format the shelf can render carries the lead figure, because
    // one format quietly dropping it is how the shelf went flat the first time.
    const cardStart = page.indexOf('function PackSpotlight(');
    expect(cardStart, 'function PackSpotlight must be locatable').toBeGreaterThan(-1);
    const cardEnd = page.indexOf('\nfunction ', cardStart + 1);
    const cardBody =
      page.slice(cardStart, cardEnd === -1 ? undefined : cardEnd)
      + readSource('../components/discovery/PackRow.tsx');
    const figures = cardBody.match(/<PackFigure\b[^/]*\/>/g) ?? [];
    /* ONE MOUNT, NOT THREE (2026-08-18, the founder's live-defect fix prompt, D4).
       The rule this pins did not soften, it moved: every card variant must state the pack's
       own evidence, and the SHAPE of that statement is now fixed by the drawing rather than
       by this test. `mockups/index.html`'s rows and tiles print one mono proof line --
       `<b>41</b> sources`, or `<b>17x</b> payback . <b>28</b> sources` -- and only the
       featured card carries the big `.stat` figure the `PackFigure` component draws. Three
       different sentences for the same fact were live on the shelf the day this changed
       (`38 sources`, `16 cited sources behind it`, `2x the price back in month one,
       modelled`), which is exactly the drift the "one device" note above is about.
       So: the spotlight keeps `PackFigure`; the row and the tile carry `CardProof`. */
    expect(figures.length, 'only the spotlight carries the big lead figure').toBe(1);
    expect(
      figures.some((f) => f.includes('weight="spotlight"')),
      'the spotlight variant must carry the lead figure',
    ).toBe(true);
    const proofMounts = cardBody.match(/<CardProof\b/g) ?? [];
    expect(
      proofMounts.length,
      'the row and the tile must each state the pack evidence through the one proof component',
    ).toBe(2);

    /*
     * NOT A SECOND PRICE. The figure is one step of the six-step scale above the price it shares
     * a card with, which is what makes it the lead. If it ever renders at the price's size the
     * card has two numbers of equal weight and no visual at all, which is the state this whole
     * change was made to leave.
     */
    const packRow = readSource('../components/discovery/PackRow.tsx');
    const figureComponent = packRow.slice(packRow.indexOf('export function PackFigure('));
    /* THE SIZE IS THE DRAWING'S NOW, NOT A TAILWIND STEP. The spotlight figure renders as the
       drawing's `.stat > .big` (mumchimp.css: 44px, weight 685) against `.price-lg` at 26px, so the
       rule this pins -- the figure outweighs the price it shares a card with -- is carried by the
       copied stylesheet instead of by a utility class. Matching `text-display` here would fail on
       a card that is drawn exactly like the drawing, which is what it did on 2026-08-18. */
    expect(figureComponent, 'the lead poster sets its figure at the drawing\'s stat size').toMatch(
      /className="big num"/,
    );
    // The Row's figure is `text-body font-semibold`, not `text-h1` (2026-08-15). `text-h1` was
    // the deleted `mid` card's size; a row is one line tall, so a figure two steps above the line
    // it sits on cannot fit in it. What this pins is unchanged -- the figure outweighs the label
    // beside it -- and on the row that is carried by weight and by the mono face.
    expect(figureComponent, 'the row sets its figure above the label beside it').toMatch(
      /text-body font-semibold/,
    );

    /*
     * THE DETERMINISM RULE, KEPT AND STRENGTHENED. It was written for the cover -- "a cover that
     * changes on reload is worse than no cover, because a buyer returning to the shelf cannot
     * find the card they were looking at" -- and it now binds the figure. The hash it used to
     * permit (the id-seeded offset table, then `PackMark`) is banned outright: a number derived
     * from a database key is not a fact about the business, which is precisely why the mark was
     * removed. The figure may be derived from the pack's DATA and from nothing else.
     */
    const withoutComments = page.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    expect(withoutComments, 'the card must not be random').not.toMatch(/Math\.random\(/);
    const statSource = readSource('../lib/packStat.ts').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(statSource, 'the lead figure must not be random').not.toMatch(/Math\.random\(/);
    expect(statSource, 'the lead figure must not be hashed out of the id').not.toMatch(
      /charCodeAt|pack\.id/,
    );

    // The flag renders on the Row, which moved to `components/discovery/PackRow.tsx` on
    // 2026-08-15. The rule this pins is "in WORDS, never a flag emoji or a bare country code",
    // and that is unchanged. The noun is not the rule: the founder changed it from "rules" to
    // "market" the same day, because the subtitle beside it already argues that the buyers and
    // the numbers travel with the country too, not only its statute book.
    // THE NOUN IS GONE (2026-08-18, D7: "`US . CA market` -> `US . CA`"). The rule this pins is
    // still "in WORDS, never a flag emoji or a bare country code", and `marketLabel` is what
    // carries it. `mockups/index.html:163` draws `.market` as a bordered mono chip, and a chip
    // that reads "US . CA market" states its own column heading inside itself.
    expect(readSource('../components/discovery/PackRow.tsx'), 'the market chip must still be stated in words').toMatch(
      /\{marketLabel\(pack\.market\)\}/,
    );
    expect(page, 'the market chip must render only when it differs from the reader\'s').toMatch(
      /pack\.market !== viewerMarket/,
    );
  });

  /*
   * THE LADDER ITSELF, exercised rather than read. The assertions above prove the card renders a
   * figure; these prove the figure is always there to render. A source-text test cannot tell the
   * difference between "renders the pack's number" and "renders an empty span", and an empty span
   * is exactly the failure the removed cover produced.
   */
  describe('the lead figure is never blank, and never invented', () => {
    const base: Pack = {
      id: 'aaaa1111bbbb2222',
      title: 'Material price cover for UK self-employed builders',
      oneLine: 'Weekly quotes cover for builders.',
      price: '£49.99',
      pricePence: 4999,
      paymentProvider: 'stripe',
      providerPriceId: 'price_test',
      sourceCount: 34,
    };

    it('leads with the modelled multiple when the pack models one that clears its own price', () => {
      const stat = packLeadStat({ ...base, financialSnapshot: { month1Revenue: '£870' } });
      // 870 / 49.99 floored. The figure is the RATIO, not the money: the raw modelled revenue was
      // deleted from the buy box on 2026-08-13 as an invented-revenue claim, and a shelf card is
      // not the place to reinstate it at display size. See lib/packStat.ts.
      expect(stat).toEqual({
        kind: 'price_multiple',
        // Brief 2026-09-02 §4.2: the card states the return in words, so the label is empty.
        figure: '17× first-year return',
        label: '',
      });
    });

    it('falls to the cited source count when there is no model, and says so in words', () => {
      expect(packLeadStat(base)).toEqual({
        kind: 'sources',
        figure: '34',
        label: 'sources',
      });
    });

    it('falls through a model that does not clear the price, rather than flattering it', () => {
      // £30 modelled against a £49.99 price is a multiple below 1. `paybackEquation` refuses it,
      // so the card states the fact it can stand behind instead of the one that reads better.
      const stat = packLeadStat({ ...base, financialSnapshot: { month1Revenue: '£30' } });
      expect(stat?.kind).toBe('sources');
    });

    it('renders nothing at all rather than a zero when the pack carries no number', () => {
      expect(packLeadStat({ ...base, sourceCount: undefined })).toBeNull();
      expect(packLeadStat({ ...base, sourceCount: 0 })).toBeNull();
    });

    it('is a pure function of the pack, so a returning buyer sees the same card', () => {
      const pack = { ...base, financialSnapshot: { month1Revenue: '£1,300' } };
      expect(packLeadStat(pack)).toEqual(packLeadStat({ ...pack }));
    });
  });

  it('pack detail page opens on a sourced dossier excerpt, not a cover', () => {
    /*
     * SUPERSEDED, deliberately. This used to require `<PackCover variant="hero" />` on the pack
     * page. US-2's problem was 45 identical left-rule documents, and a cover did solve that on
     * the SHELF, where the job is to tell packs apart at a glance -- the square variant is still
     * asserted above and still ships.
     *
     * On the detail page it did not: measured 2026-08-05 the 16:9 plate held the whole fold
     * above the h1 and carried the pack ID, a market tag, a monogram and the title again, all of
     * which the visitor already had. Worse, it renders identically for a pack with nothing
     * behind it, so the prime slot on the money page was occupied by the one element that
     * cannot be evidence.
     *
     * The replacement can only render when the claim is true: a line from this pack's own
     * `sampleExtract` with its source resolved to a live anchor, and nothing at all when there
     * is no such line.
     */
    expect(
      /<PackCover\s+[^>]*variant=["']hero["']/.test(packPage),
      'the empty hero cover must not come back to the pack page',
    ).toBe(false);
    expect(
      /<EvidenceExcerptPlate\s+pack=\{pack\}/.test(packPage),
      'pack/[id].tsx must open on <EvidenceExcerptPlate pack={pack} />',
    ).toBe(true);

    const plate = readSource('../components/marketing/EvidenceExcerptPlate.tsx');
    expect(plate, 'the plate must read the pack\'s own extract').toMatch(/sampleExtract/);
    expect(plate, 'the plate must resolve sources to anchors').toMatch(/parseCitations/);
    expect(
      /if\s*\(!first\)\s*return null/.test(plate),
      'no sourced extract must render nothing, never an empty plate',
    ).toBe(true);
  });

  it('PackCover has a fallback when the pack has no category', () => {
    // The audit says: "the cover renders a fallback (current gradient + icon) when the
    // image is missing." A pack with no category (untagged) must still render a cover.
    if (!coverExists) return;
    const source = readSource('../components/marketing/PackCover.tsx');
    const hasFallback = /fallback|cat\.tagged|untagged|no category|missing/i.test(source);
    expect(
      hasFallback,
      'PackCover must handle a pack with no category (fallback gradient + icon)',
    ).toBe(true);
  });
});
