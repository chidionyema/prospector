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

  it('PackCover accepts a pack and a variant (square or hero)', () => {
    if (!coverExists) return;
    const source = readSource('../components/marketing/PackCover.tsx');
    const acceptsPack = /pack\s*:\s*Pack\b/.test(source);
    expect(
      acceptsPack,
      'PackCover must accept a pack prop typed Pack',
    ).toBe(true);
    const acceptsVariant = /variant\s*:/.test(source);
    expect(
      acceptsVariant,
      'PackCover must accept a variant prop (square | hero)',
    ).toBe(true);
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

  it('home page renders a 1:1 (square) cover on the PackCard', () => {
    // The PackCard is the primary surface. The 1:1 cover sits at the top of the card.
    const hasSquareCover = /<PackCover\s+[^>]*variant=["']square["']/.test(page) ||
      /<PackCover\s+[^>]*pack=\{pack\}/.test(page);
    expect(
      hasSquareCover,
      'index.tsx must render <PackCover variant="square" pack={pack} /> somewhere in the PackCard',
    ).toBe(true);
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
