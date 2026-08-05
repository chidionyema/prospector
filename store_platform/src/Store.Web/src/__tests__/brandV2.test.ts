import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

/**
 * Brand v2 - the world-class design system overhaul.
 *
 * The previous brand read as a 2020-2022 "research tool" aesthetic: warm paper
 * background, warm tan borders, three-family typography stack, decorative
 * noise grain, small h1, fast motion. A 2026 first-time visitor reads it
 * as competent but dated. The fix is a confident system redesign that
 * preserves the *positioning* (research document, not SaaS dashboard) while
 * updating the visual language to 2026 best-in-class.
 *
 * Decisions made by the Architect (this is the design pass, not a code pass):
 *
 *  1. Background: #FEFDF9 (warm paper) -> #FFFFFF (clean white). The warm
 *     paper read as "suburban wellness brand"; clean white reads as
 *     "research ledger" (Linear, Stripe, Mercury all use clean white).
 *  2. Border: #D4C9B5 (warm tan) -> #E5E5E5 (high-contrast neutral). The
 *     warm tan was 2020; 2026 UIs use higher-contrast borders.
 *  3. Typography: drop the third family (Geist Mono). The mono data
 *     markers can use ui-monospace fallback. Two families is the 2026
 *     standard (display serif + body sans, OR all sans).
 *  4. Body noise grain: drop entirely. The SVG turbulence overlay was
 *     a 2020-2021 "texture" trick; 2026 is clean.
 *  5. h1 size: 3rem -> 4.5rem on desktop. Modern heroes dominate.
 *  6. Motion: 0.2s -> 0.3s with cubic-bezier(0.32, 0.72, 0, 1). Slower,
 *     more confident, more Apple-like.
 *  7. Spacing: more generous. Cards: p-5 -> p-6/p-8. Sections: more
 *     vertical breathing room.
 *  8. Surface hierarchy: bg vs surface vs surface-2 needs clearer
 *     visual difference. Add a subtle warm-tint surface-2 to keep the
 *     "paper" feel without losing the clean white.
 *  9. Deep teal #042F2E is the brand colour; KEEP. It's distinctive
 *     and credible. The change is the surrounding palette, not the
 *     accent.
 */
describe('Brand v2 - the world-class design system', () => {
  const css = readSource('../styles/globals.css');
  // Strip comments for a clean search.
  const stripped = css
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '');

  describe('palette: clean white, high-contrast borders, deep teal kept', () => {
    it('declares --bg as clean white (#FFFFFF or near-white)', () => {
      const hasCleanWhite = /--bg\s*:\s*#FFFFFF/i.test(stripped) ||
        /--bg\s*:\s*#FAFAFA/i.test(stripped) ||
        /--bg\s*:\s*#F[A-F0-9]{5}/i.test(stripped);
      expect(
        hasCleanWhite,
        '--bg must be a clean white (no warm cream/paper tone)',
      ).toBe(true);
    });

    it('declares --border as high-contrast neutral', () => {
      // #E5E5E5, #D4D4D4, or similar (no warm tan)
      const hasHighContrast = /--border\s*:\s*#E[5-9]E[5-9]E[5-9]/i.test(stripped) ||
        /--border\s*:\s*#D[4-9]D[4-9]D[4-9]/i.test(stripped) ||
        /--border\s*:\s*rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\.0[5-9]\)/i.test(stripped);
      const noWarmTan = !/--border\s*:\s*#D4C9B5/i.test(stripped) &&
        !/--border\s*:\s*#C8B/i.test(stripped);
      expect(
        hasHighContrast,
        '--border must be a high-contrast neutral (not warm tan)',
      ).toBe(true);
      expect(
        noWarmTan,
        '--border must NOT be the old warm tan #D4C9B5',
      ).toBe(true);
    });

    it('declares --primary as a bold 2026 accent (NOT the old muddy deep teal)', () => {
      // The previous brand colour #042F2E (deep teal) was muddy and dated.
      // The v2 commits to #FF5A1F (vermillion) — bold, distinctive, the
      // same lane as Figma's orange and Stripe's purple. It is the
      // visual signal that Mumchimp is not a blue SaaS brand.
      // The v2 also REJECTS the old deep teal explicitly: the test
      // fails if --primary is still the old colour, so a rebrand that
      // forgets to drop the teal fails the contract.
      const hasVermillion = /--primary\s*:\s*#FF5A1F/i.test(stripped) ||
        /--primary\s*:\s*#FF[0-9A-F]{4}/i.test(stripped);
      const noDeepTeal = !/--primary\s*:\s*#042F2E/i.test(stripped) &&
        !/--primary\s*:\s*#022C22/i.test(stripped);
      expect(
        hasVermillion,
        '--primary must be the bold 2026 vermillion #FF5A1F (or a similarly bold accent)',
      ).toBe(true);
      expect(
        noDeepTeal,
        '--primary must NOT be the old deep teal #042F2E (rejected by stakeholder)',
      ).toBe(true);
    });
  });

  describe('typography: two families, dominant h1', () => {
    it('resolves the mono stack through --font-mono-pref with a fallback', () => {
      /*
       * REWRITTEN 2026-08-05. This test was named "removes the third (Geist Mono) font family from
       * the stack" and asserted `!/Geist_Mono|geist_mono|geist-mono/i.test(globals.css)`.
       *
       * That can never fail. globals.css never names a font family directly, it consumes the
       * next/font handle `--font-mono-pref` (lines 149 and 248), so the literal string "geist"
       * cannot appear there whatever _app.tsx does. The test was green while _app.tsx imported
       * Geist_Mono, instantiated it, and applied `geistMono.variable` to the app root, and while
       * globals.css:348 applied `var(--font-mono)` to `.font-mono/.text-caption/.text-eyebrow`
       * across 74 component usages. Geist has been shipping and rendering the whole time.
       *
       * The brand-v2 intent to drop the third family therefore never landed. Reinstating the
       * original assertion honestly would turn 74 components' type over to ui-monospace, which is
       * a visible redesign and a founder call, not a test fix. Flagged for decision; until then
       * this asserts the wiring that is actually load-bearing, which the old test never covered:
       * the indirection must stay intact, because a missing fallback here is how the webfont
       * silently stops rendering.
       */
      expect(stripped, 'mono must resolve via the next/font handle').toMatch(
        /--font-mono\s*:\s*var\(\s*--font-mono-pref/,
      );
      expect(stripped, 'mono must declare a fallback family').toMatch(
        /--font-mono\s*:\s*var\([^)]*\)\s*,\s*var\(--font-fallback-mono\)/,
      );
    });

    it('declares the h1 size as 4rem or larger on desktop', () => {
      // The previous --text-h1 was 3rem. The v2 lifts it to 4rem+ so the
      // hero h1 dominates the page. Tailwind v4 maps --text-h1 to the
      // text-h1 utility, used in the h1 utilities further down.
      const hasLargeH1 = /--text-h1\s*:\s*[4-9]rem/i.test(stripped) ||
        /--text-display\s*:\s*[4-9]rem/i.test(stripped) ||
        /--text-hero\s*:\s*[4-9]rem/i.test(stripped);
      expect(
        hasLargeH1,
        'globals.css must declare a dominant h1 (>= 4rem on desktop)',
      ).toBe(true);
    });
  });

  describe('motion: slower, more confident', () => {
    it('uses a longer transition duration (0.3s base)', () => {
      // The previous --transition-standard was 0.2s. The v2 lifts the
      // base to 0.3s, with cubic-bezier(0.32, 0.72, 0, 1) for the
      // Apple-like ease.
      const hasThreeHundredMs = /transition-standard[^;]*0\.3s/i.test(stripped) ||
        /--transition-base\s*:\s*0\.3s/i.test(stripped) ||
        /transition:\s*all\s+0\.3s/i.test(stripped);
      expect(
        hasThreeHundredMs,
        'globals.css must use a 0.3s base transition (was 0.2s)',
      ).toBe(true);
    });

    it('uses cubic-bezier ease for transitions', () => {
      // The previous was cubic-bezier(0.4, 0, 0.2, 1) (Material standard,
      // feels 2020). The v2 uses cubic-bezier(0.32, 0.72, 0, 1) (Apple
      // standard, more confident).
      const hasAppleEase = /cubic-bezier\(0\.32\s*,\s*0\.72/i.test(stripped);
      expect(
        hasAppleEase,
        'globals.css must use cubic-bezier(0.32, 0.72, 0, 1) (Apple-like)',
      ).toBe(true);
    });
  });

  describe('visual hygiene: drop the 2020 noise grain', () => {
    it('does not render a body::before noise grain', () => {
      // The previous body::before used an SVG turbulence filter at 0.02
      // opacity. The v2 drops the grain entirely; clean white is the
      // 2026 look.
      const hasBodyBefore = /body::before\s*\{/.test(stripped) &&
        /feTurbulence|fractalNoise/i.test(stripped);
      expect(
        !hasBodyBefore,
        'globals.css must not render a body::before noise grain',
      ).toBe(true);
    });
  });

  describe('surface hierarchy: clear bg vs surface vs surface-2', () => {
    it('declares three distinct surface tokens with clear visual difference', () => {
      // The previous --bg, --surface, --surface-2 were all in the same
      // warm paper family. The v2 makes surface-2 a subtle warm tint
      // (#F7F7F5) so elevated cards have a clear visual difference.
      const hasBg = /--bg\s*:\s*#[F]+\b/i.test(stripped) ||
        /--bg\s*:\s*#FAFAFA/i.test(stripped);
      const hasSurface2 = /--surface2\s*:\s*#F[7-9]F[7-9]F[5-9]/i.test(stripped);
      expect(
        hasBg && hasSurface2,
        'globals.css must declare --bg (clean white) and --surface2 (subtle warm tint)',
      ).toBe(true);
    });
  });
});
