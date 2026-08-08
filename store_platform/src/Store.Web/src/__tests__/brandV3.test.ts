import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { readStylesheet } from './helpers/stylesheet';

function readSource(relativePath: string): string {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  // A stylesheet is read with its local `@import`s inlined, so this file's assertions follow the
  // tokens when they move between files instead of failing as if they had been deleted. See
  // `helpers/stylesheet.ts` for the 21-failure incident that added it.
  return path.endsWith('.css') ? readStylesheet(path) : readFileSync(path, 'utf8');
}

/**
 * Brand v3 — the palette and motion contract.
 *
 * WHY THIS FILE REPLACES `brandV2.test.ts`
 *
 * v2 was rejected outright by the founder ("truly awful look, highly unprofessional"), and the
 * things it pinned are the things that were wrong. This file therefore does not soften v2's
 * assertions, it inverts the four that named a specific choice, and keeps the ones that were
 * about hygiene rather than taste:
 *
 *  1. `--primary: #FF5A1F` (vermillion). v2 asserted it and rejected the old teal. v3 makes the
 *     primary INK (#171717) and asserts vermillion is gone from the palette entirely. A saturated
 *     orange fill was the single loudest element on the page, and it sat under a 3px sticker
 *     shadow on every CTA.
 *  2. Motion `0.3s` / `cubic-bezier(0.32, 0.72, 0, 1)`. v2 called this "confident"; at 300ms every
 *     hover on a card grid visibly lags the cursor. v3 caps duration at 200ms and standardises on
 *     `cubic-bezier(0.2, 0, 0, 1)`.
 *  3. `--surface2` as a "subtle warm tint" (#F7F7F5). The palette is neutral grey now, so the
 *     tint is #FAFAFA. Note v2's own regex `#F[7-9]F[7-9]F[5-9]` could not match #FAFAFA anyway.
 *  4. `--border` as #E5E5E5-ish. Kept in spirit (high-contrast neutral, not warm tan) but written
 *     against the actual token, #E4E4E7.
 *
 * Kept from v2 unchanged, because they were never the problem: the mono font must resolve through
 * the next/font handle with a fallback (a missing fallback is how the webfont silently stops
 * rendering); no `body::before` noise grain; a display step several times body size.
 */
describe('Brand v3 — palette, motion, surfaces', () => {
  const css = readSource('../styles/globals.css');
  // Strip comments for a clean search: this file's rationale names the banned colours in prose.
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');

  describe('palette: neutral greys, ink primary, one accent', () => {
    it('declares --bg as clean white', () => {
      expect(stripped, '--bg must be clean white').toMatch(/--bg\s*:\s*#FFFFFF/i);
    });

    it('declares --border as a high-contrast neutral, not a warm tan', () => {
      expect(stripped, '--border must be the neutral hairline #E4E4E7').toMatch(
        /--border\s*:\s*#E4E4E7/i,
      );
      expect(stripped, '--border must NOT be the old warm tan #D4C9B5').not.toMatch(
        /--border\s*:\s*#D4C9B5/i,
      );
    });

    it('makes the primary action ink, not a saturated fill', () => {
      expect(stripped, '--primary must be ink #171717').toMatch(/--primary\s*:\s*#171717/i);
      expect(stripped, '--primary must NOT be the rejected deep teal').not.toMatch(
        /--primary\s*:\s*#(042F2E|022C22)/i,
      );
    });

    it('has removed vermillion from the stylesheet entirely, not merely stopped using it', () => {
      // Left declared it is a standing invitation: the next component reaches for it, it
      // resolves, and the rebrand is undone one commit at a time with no test firing.
      expect(stripped, '#FF5A1F must not appear anywhere in globals.css').not.toMatch(/#FF5A1F/i);
    });

    it('declares NO chromatic accent: links are ink plus a hairline underline', () => {
      // SUPERSEDED, not deleted. This required `--accent: #2563EB`. Spec §3 (docs/
      // SITE_SPEC_PROGRAM.md:223-224) replaced the blue with ink and made an inline link's whole
      // affordance a hairline underline, and the §3 row records the browser-computed proof:
      // `--accent` = #171717 on all five sampled pages, `2563EB` x0 in the built sheet.
      //
      // The assertion is INVERTED rather than dropped, because "no chromatic accent" is the rule
      // that is easy to undo one component at a time. Asserting the blue is absent is what stops
      // the next `text-accent` from quietly reintroducing a hue.
      expect(stripped, '--accent must resolve to ink, via the text token').toMatch(
        /--accent\s*:\s*var\(\s*--text\s*\)/i,
      );
      expect(stripped, 'the v2 link blue must not be declared anywhere').not.toMatch(/#2563EB/i);
    });
  });

  describe('typography: one family, dominant display step', () => {
    it('resolves the mono stack through --font-mono-pref with a fallback', () => {
      // Kept verbatim from v2. The indirection is load-bearing: a missing fallback here is how
      // the webfont silently stops rendering, which has happened on this codebase before.
      expect(stripped, 'mono must resolve via the next/font handle').toMatch(
        /--font-mono\s*:\s*var\(\s*--font-mono-pref/,
      );
      expect(stripped, 'mono must declare a fallback family').toMatch(
        /--font-mono\s*:\s*var\([^)]*\)\s*,\s*var\(--font-fallback-mono\)/,
      );
    });

    it('declares a heading step that dominates body copy', () => {
      // The top two steps are `clamp(min, preferred, max)` now (spec §3.2 gives display and h1
      // their own mobile sizes), so a bare `([\d.]+)rem` matched nothing and this read as "the
      // token is not declared". The ratio this test is about is the DESKTOP one, which is the
      // clamp's maximum: the last rem value in the declaration.
      const largestRem = (declaration: string | undefined): number | null => {
        if (declaration === undefined) return null;
        const rems = [...declaration.matchAll(/([\d.]+)rem/g)].map((m) => Number(m[1]));
        return rems.length > 0 ? Math.max(...rems) : null;
      };
      const display = /--text-display\s*:\s*([^;]+);/i.exec(stripped);
      const body = /--text-body\s*:\s*([^;]+);/i.exec(stripped);
      expect(display, 'globals.css must declare --text-display').not.toBeNull();
      expect(body, 'globals.css must declare --text-body').not.toBeNull();
      expect(
        largestRem(display?.[1])! / largestRem(body?.[1])!,
        'the largest heading step must be at least 2.5x body',
      ).toBeGreaterThanOrEqual(2.5);
    });
  });

  describe('motion: fast enough to feel attached to the cursor', () => {
    it('caps every declared transition at 200ms', () => {
      const durations = [...stripped.matchAll(/--transition-[a-z]+\s*:[^;]*?([\d.]+)s/g)].map((m) =>
        Number(m[1]),
      );
      expect(durations.length, 'no --transition-* tokens found; the pattern stopped matching')
        .toBeGreaterThan(0);
      expect(
        durations.filter((d) => d > 0.2),
        `every transition token must be <= 0.2s, found: ${durations.join(', ')}`,
      ).toEqual([]);
    });

    it('standardises on one easing curve', () => {
      expect(stripped, 'transitions must use cubic-bezier(0.2, 0, 0, 1)').toMatch(
        /cubic-bezier\(0\.2\s*,\s*0\s*,\s*0\s*,\s*1\)/,
      );
      expect(stripped, "v2's 300ms Apple ease must be gone").not.toMatch(
        /cubic-bezier\(0\.32\s*,\s*0\.72/,
      );
    });
  });

  describe('visual hygiene', () => {
    it('does not render a body::before noise grain', () => {
      const hasBodyBefore =
        /body::before\s*\{/.test(stripped) && /feTurbulence|fractalNoise/i.test(stripped);
      expect(!hasBodyBefore, 'globals.css must not render a body::before noise grain').toBe(true);
    });
  });

  describe('surface hierarchy', () => {
    it('separates the page canvas from the sunken panel tint', () => {
      expect(stripped, '--surface2 must be the neutral tint #FAFAFA').toMatch(
        /--surface2\s*:\s*#FAFAFA/i,
      );
      // The card surface is the same white as the canvas ON PURPOSE: the edge is drawn by a
      // border. Asserted so a future "let's tint the cards" change has to argue with this line.
      expect(stripped, '--surface must be white; the border draws the edge').toMatch(
        /--surface\s*:\s*#FFFFFF/i,
      );
    });
  });
});
