import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

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

  it('every PackCard still carries a per-pack identity, drawn from the category', () => {
    /*
     * US-2's actual problem was that 45 cards were indistinguishable without reading the title.
     * The 1:1 coloured tile was one answer to it; it is not the only one, and it was not a good
     * one -- sixty-one gradient tiles are as uniform as sixty-one white rectangles, they are just
     * louder about it. So this asserts the PROBLEM stays solved rather than pinning the tile:
     * the card opens on an identity row carrying the sector (a category-derived dot and label)
     * and the listing's own market and short ID, all of which differ pack to pack.
     */
    expect(page, 'the card must derive its identity from the pack category').toMatch(
      /const cat = categoryFor\(pack\)/,
    );
    expect(page, 'the sector dot must be category-derived, not a fixed hue').toMatch(
      /'h-2 w-2 flex-none rounded-full', cat\.dot/,
    );
    expect(page, 'the identity row must carry the listing market').toMatch(
      /marketLabel\(pack\.market\)/,
    );
    expect(page, 'the identity row must carry the short dossier id').toMatch(
      /pack\.id\.slice\(0, 6\)\.toUpperCase\(\)/,
    );
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
      /<DossierExcerptPlate\s+pack=\{pack\}/.test(packPage),
      'pack/[id].tsx must open on <DossierExcerptPlate pack={pack} />',
    ).toBe(true);

    const plate = readSource('../components/marketing/DossierExcerptPlate.tsx');
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
