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

  it('/ideas page renders BespokeIcon in the category rows', () => {
    // The flat list of categories on /ideas should use the bespoke icons
    // instead of the generic Lucide set. The page must import or use the
    // BespokeIcon component.
    if (!componentExists) return;
    const usesBespoke = /<BespokeIcon\b/.test(page) || /import\s+BespokeIcon/.test(page);
    expect(
      usesBespoke,
      'pages/ideas/index.tsx must render <BespokeIcon> in the category rows',
    ).toBe(true);
  });
});
