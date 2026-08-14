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
     * louder about it. So this asserts the PROBLEM stays solved rather than pinning any one
     * drawing of it.
     *
     * REVISED 2026-08-06 (brand v3). The carrier it used to pin -- a 44px identity row of
     * `cat.dot` + sector label + market + `pack.id.slice(0, 6).toUpperCase()` -- is gone, and two
     * of its four elements went for reasons this suite should not be re-litigating:
     *
     *   - the short id (`№ FCF4A5`) is debug output. A truncated hash of a database key, printed
     *     on a product, is a fact about our storage that no buyer can use;
     *   - the market read as a bare `US` beside it, and rendered on all 63 cards including the
     *     63 that matched the reader's own market, where it distinguishes nothing.
     *
     * What replaces it is a drawn cover (`PackCoverArt`) rather than a text row, so the
     * assertions follow the identity to it: the sector's colour and icon, a per-pack variation
     * that is deterministic in the pack id, and the market stated in words but only when it is
     * not the reader's own.
     */
    expect(page, 'the card must derive its identity from the pack category').toMatch(
      /const cat = categoryFor\(pack\)/,
    );
    expect(page, 'the card must open on the generated cover').toMatch(
      /<PackCoverArt\b[\s\S]{0,120}category=\{cat\}/,
    );
    /*
     * THE TINT AND THE ICON: WITHDRAWN 2026-08-14, and this is the second withdrawal on this
     * cover, so the reasoning is kept rather than the assertion. Two assertions stood here:
     *
     *   toMatch(/category\.tint/)              // the cover ground is the sector's pastel
     *   toMatch(/name=\{category\.icon\}/)     // the mark is the sector's glyph at 72px
     *
     * They were the surviving half of "identity comes from the category", and they were right
     * that the cover must be deterministic and not decorative-random. What they pinned was a
     * sector drawn TWICE -- once as a hue, once as a pictogram -- on a card whose only
     * pack-specific fact (the source count) was pushed into the body. A pastel rectangle with a
     * 14%-opacity briefcase in it is stock furniture, and this shop sells audited evidence.
     *
     * The cover is now the pack's evidence run on the instrument plate. The determinism rule is
     * not withdrawn and is asserted below in its stronger form: the cover renders `sourceCount`,
     * a fact of the pack, and nothing derived from a hash, a random, or the render order.
     */
    expect(page, 'the cover must draw the pack\'s own evidence run').toMatch(
      /<EvidenceBar\b[^>]*count=\{pack\.sourceCount\}[^>]*tone="instrument"/,
    );
    expect(page, 'the cover must sit on the instrument ground, not a per-sector tint').toMatch(
      /border-ins-line bg-ins-bg/,
    );
    expect(page, 'the sector stays on the cover, as a fact rather than a picture').toMatch(
      /category\.tagged \? category\.label : null/,
    );
    /*
     * PER-PACK JITTER: WITHDRAWN, NOT RELAXED (2026-08-06, internal design review).
     *
     * Two assertions used to live here and are deleted on purpose, with the reasoning kept in
     * place so nobody re-derives the idea from scratch:
     *
     *   toMatch(/Array\.from\(pack\.id\)\.reduce/)                  // seed the offset from the id
     *   toMatch(/COVER_OFFSETS = \[[\s\S]{0,200}'left-\[\d+%\]'/)   // 5 literal offset classes
     *
     * They encoded a real constraint -- a cover that moves on reload is worse than no cover,
     * because a returning reader cannot find the card they were looking at -- and the fix was
     * sound in isolation: hash the id, index a fixed table of `left-[n%]` literals.
     *
     * It was rejected on what it rendered. The glyph was pushed to a per-pack horizontal offset
     * inside a 96px-tall band, so on the seeds that landed right the mark was CLIPPED by the
     * card edge, and down a three-up grid the eye read the row as five different components
     * rather than five instances of one. Variation was bought at the cost of the thing a shelf
     * needs most, which is that its cards look like a set.
     *
     * The replacement gets non-uniformity from something that is already true of each pack
     * rather than from its id: the category tint and the category glyph, on a fixed four-corner
     * layout, over one shared `COVER_WEAVE` texture. Two packs in the same sector do look alike
     * -- that is now the intent, because they ARE alike, and the chip and title separate them.
     *
     * The determinism requirement is not withdrawn; it is satisfied more strongly than before,
     * since nothing about the cover is derived from anything but the pack's own category. The
     * `Math.random` ban below is the part of the old rule that still has teeth, so it stays.
     */
    // Comments stripped first: the component's own header names `Math.random()` while explaining
    // why it is banned there, and a doc comment is not a call.
    const withoutComments = page.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    expect(withoutComments, 'the cover must not be random').not.toMatch(/Math\.random\(/);
    // Tailwind scans source text, so an interpolated `bg-[image:...${n}...]` compiles to nothing.
    // The cover's one arbitrary-value class must therefore be a full literal, not built at
    // runtime. It used to be `COVER_WEAVE`, a repeating-linear-gradient; it is now the plate's
    // radial lift. The RULE is what this pins, not the gradient.
    expect(page, 'the cover texture must be a full literal class string').toMatch(
      /'bg-\[image:radial-gradient\([^']*\)\]'/,
    );
    expect(page, 'the cover must state the listing market in words').toMatch(
      /For \{marketLabel\(pack\.market\)\} rules/,
    );
    expect(page, 'the market chip must render only when it differs from the reader\'s').toMatch(
      /pack\.market !== viewerMarket/,
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
