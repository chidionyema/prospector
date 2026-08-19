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
 * N3 - Bespoke category icons.
 *
 * The audit said: "16 bespoke SVGs in the category system. 4 bespoke
 * archetype icons in the discovery flow."
 *
 * Out of scope (per the spec): full design-led icon work that needs a
 * designer. The pragmatic fix is to consolidate the icon set into a single
 * `BespokeIcon` component, with a unique shape per category, so the site
 * stops depending on the generic Lucide set for category identification.
 * The shapes are minimal geometric primitives; the designer can refine.
 */
describe('N3 - Bespoke category icons', () => {
  const componentExists = existsRelative('../components/marketing/BespokeIcon.tsx');
  const page = readSource('../pages/ideas/index.tsx');

  it('declares a BespokeIcon component', () => {
    expect(
      componentExists,
      'components/marketing/BespokeIcon.tsx must exist',
    ).toBe(true);
  });

  it('BespokeIcon accepts a category kind and renders a unique shape', () => {
    if (!componentExists) return;
    const source = readSource('../components/marketing/BespokeIcon.tsx');
    // The component must accept a `kind` prop and route to multiple category
    // values. The architecture is a lookup map (ICON_MAP[kind] ?? Default) OR
    // a switch; both are valid.
    const acceptsKind = /\bkind\b\s*[:?]/.test(source);
    const routesOverKinds = /switch\s*\(/.test(source) ||
      /ICON_MAP|ICON_SET|categoryIcons|kind\s*===\s*['"]/.test(source) ||
      /kind\s+in\s+\{/.test(source);
    expect(
      acceptsKind && routesOverKinds,
      'BespokeIcon must accept a kind prop and route over multiple category values',
    ).toBe(true);
  });

  it('BespokeIcon renders a unique SVG path per category (no shared shape)', () => {
    if (!componentExists) return;
    const source = readSource('../components/marketing/BespokeIcon.tsx');
    // The component must have at least 4 distinct SVG path/polygon
    // definitions, one per category. The audit asked for 16; the
    // implementation can land at 4+ as the v1 with the rest of the
    // categories added incrementally.
    const pathCount = (source.match(/<path\b|<polygon\b|<rect\b|<circle\b/g) || []).length;
    expect(
      pathCount >= 4,
      `BespokeIcon must render at least 4 distinct shapes; found ${pathCount}`,
    ).toBe(true);
  });

  /*
   * WAS: "/ideas page renders BespokeIcon in the category rows" -- asserting `<BespokeIcon` in
   * `pages/ideas/index.tsx`. That assertion was green for months against a page on which the
   * icons never once drew a category shape, and this is the receipt:
   *
   *   `ICON_MAP` (BespokeIcon.tsx:132) is keyed on short kinds -- `evenings`, `developers`,
   *   `marketplace`, `trades`, `b2b`. `/ideas` passed the LANDING SLUG -- `evening-business-ideas`,
   *   `business-ideas-for-developers`, `marketplace-and-broker-ideas` (landings.ts:67-242). Not one
   *   of the 16 slugs is a key in that map, so every call took `?? DefaultIcon` (BespokeIcon.tsx:166)
   *   and all 14 rendered tiles drew the SAME mark. The test could not see it because it looked for
   *   the tag, and the tag was there.
   *
   * Fixing the keys would not rescue the feature either: the map's 19 kinds resolve to 9 shapes,
   * so `vertical-software` and `developers` are both the triangle, `marketplace` and `operators`
   * both the hexagon, `red_tape` and `part_time` both the cross. A shape shared by two unrelated
   * categories does not identify a category; it decorates one. N3 asked for these icons so the
   * site would stop leaning on a generic set for category identification, and a generic set is
   * what a 9-into-16 mapping is.
   *
   * So the category rows carry no icon, and the honest assertion is the one below: the component
   * and its shapes are intact and still tested (the three cases above), and the page does not claim
   * an identification it cannot make. Flagged to the founder rather than removed quietly, per the
   * no-silent-feature-removal rule -- the shapes are still here the day a designer draws the
   * missing seven and the map is keyed on something `/ideas` actually passes.
   */
  it('/ideas does not decorate its rows with an icon that cannot identify a category', () => {
    if (!componentExists) return;
    const iconSource = readSource('../components/marketing/BespokeIcon.tsx');
    const mapBody = iconSource.slice(iconSource.indexOf('const ICON_MAP'));
    const shapes = new Set(
      Array.from(mapBody.matchAll(/:\s*([A-Z]\w*Icon)\b/g), (m) => m[1]),
    );
    const keys = Array.from(mapBody.matchAll(/^\s*'?([\w-]+)'?:\s*[A-Z]\w*Icon/gm), (m) => m[1]);
    expect(
      shapes.size < keys.length,
      'if every kind ever gets its OWN shape, revisit this: the icons could then identify a row',
    ).toBe(true);

    const landings = readSource('../lib/seo/landings.ts');
    const slugs = Array.from(landings.matchAll(/slug:\s*'([\w-]+)'/g), (m) => m[1]);
    const mapped = slugs.filter((s) => keys.includes(s));
    expect(
      mapped,
      'no landing slug is a key in ICON_MAP -- every one would fall through to DefaultIcon',
    ).toEqual([]);
  });
});
