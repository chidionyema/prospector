/**
 * THE HEADING FLOOR MUST STAY INSIDE `@layer base`.
 *
 * `globals.css` imports the shipped drawing stylesheet as
 * `@import "./mumchimp.css" layer(components)`, and unlayered CSS beats EVERY cascade layer
 * regardless of specificity. So an unlayered `h1, h2, h3 { font-weight }` rule in `globals.css`
 * silently overrides the bundle's own heading weights on every page of the site, and nothing
 * reports it: the font SIZES still come from the bundle, so the page looks plausible.
 *
 * That is exactly what happened. Measured 2026-08-18 by `scripts/component_parity.mjs` across all
 * ten pages at 390 and 1280: `h2.sec` computed `font-weight: 560` in the build against `665` in
 * the drawing, and `h3.sub` computed `560` against `655`. Twenty rows out of twenty, on a
 * stylesheet whose whole point is that it ships verbatim.
 *
 * This test walks the real brace structure rather than grepping, so wrapping the rule in some
 * other at-rule, or moving it back out of the layer, both fail.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const GLOBALS = path.join(process.cwd(), 'src/styles/globals.css');

/** Every at-rule and selector block open at the point `needle` first appears, outermost first. */
function enclosingBlocks(css: string, needle: string): string[] {
  const src = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const target = src.indexOf(needle);
  expect(target, `${needle} not found in globals.css`).toBeGreaterThan(-1);

  const stack: string[] = [];
  let preludeStart = 0;
  for (let i = 0; i < target; i += 1) {
    const ch = src[i];
    if (ch === '{') {
      stack.push(src.slice(preludeStart, i).trim().replace(/\s+/g, ' '));
      preludeStart = i + 1;
    } else if (ch === '}') {
      stack.pop();
      preludeStart = i + 1;
    } else if (ch === ';') {
      preludeStart = i + 1;
    }
  }
  return stack;
}

describe('globals.css cascade layers', () => {
  const css = readFileSync(GLOBALS, 'utf8');

  it('imports the shipped bundle into the components layer', () => {
    expect(css).toContain('@import "./mumchimp.css" layer(components);');
  });

  /*
   * SIX LEVELS SINCE 2026-08-30, NOT THREE. The floor used to read `h1, h2, h3` and this test
   * pinned that literal. Leaving h4, h5 and h6 out was a real defect: Tailwind's preflight sets
   * every heading to `font-size:inherit;font-weight:inherit`, and the bundle only draws headings
   * per container (`.htile h3`, `.band h3`, `.checkrow h5`), so a heading level that neither the
   * bundle nor this floor names renders as body text. Measured on the built home page with a
   * computed-style probe, six headings were at 16px / weight 400, including the three tiles at
   * the top of the first shelf a visitor sees. The rendered-DOM guard is the `typography` block
   * in `e2e/storefront.spec.ts`; this one keeps the floor in the right layer.
   */
  it('keeps the element floor for every heading level inside @layer base', () => {
    expect(enclosingBlocks(css, 'h1, h2, h3, h4, h5, h6 {')).toContain('@layer base');
  });

  it('keeps the scale-token overrides unlayered, so a worn token still wins', () => {
    /* These are the finer control the floor defers to. Layering them would put them below the
       bundle and a page wearing `text-display` would lose the step it was tuned at. */
    for (const sel of [':is(h1, h2, h3).text-display {', ':is(h1, h2, h3).text-h1 {', ':is(h1, h2, h3).text-h2 {']) {
      expect(enclosingBlocks(css, sel), sel).toHaveLength(0);
    }
  });
});
