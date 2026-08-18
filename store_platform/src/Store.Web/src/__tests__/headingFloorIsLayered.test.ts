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

  it('keeps the h1/h2/h3 element floor inside @layer base', () => {
    expect(enclosingBlocks(css, 'h1, h2, h3 {')).toContain('@layer base');
  });

  it('keeps the scale-token overrides unlayered, so a worn token still wins', () => {
    /* These are the finer control the floor defers to. Layering them would put them below the
       bundle and a page wearing `text-display` would lose the step it was tuned at. */
    for (const sel of [':is(h1, h2, h3).text-display {', ':is(h1, h2, h3).text-h1 {', ':is(h1, h2, h3).text-h2 {']) {
      expect(enclosingBlocks(css, sel), sel).toHaveLength(0);
    }
  });
});
