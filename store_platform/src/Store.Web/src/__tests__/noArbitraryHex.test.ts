import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * No colour outside the token scale.
 *
 * `src/lib/category.ts` carried nine hardcoded hexes -- an eight-hue category rainbow plus a zinc
 * for untagged -- straight through the brand v3 sweep, which converted everything else to tokens.
 * They survived because nothing looked for them: they are correct TypeScript, they render, and
 * the file had a docblock defending them written under the previous brand. The only thing that
 * found them was inspecting a rendered page and asking why the money screen had exactly one red
 * element on it (`rgb(225,29,72)`, the rose category dot, on a site where red means KILLED).
 *
 * A palette does not drift back all at once. It drifts one `bg-[#...]` at a time, each one locally
 * reasonable, and the tokens quietly stop being the source of truth. This is the check that makes
 * that fail loudly, and it is deliberately a whole-tree scan rather than a rule about one file --
 * the next hex will not be in `category.ts`.
 *
 * Legitimate escape hatch: none is needed today, and adding one should be a decision, not a
 * convenience. If a genuine one-off arises (an external brand's colour in an embed, say), add it
 * to ALLOWED with the reason, so the exception is reviewable instead of invisible.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

/** Arbitrary-value Tailwind colour utilities: `bg-[#fff]`, `text-[#171717]`, `border-[#E4E4E7]`. */
const ARBITRARY_HEX = /\b(?:bg|text|border|ring|outline|fill|stroke|shadow|from|via|to|decoration|accent|caret|divide)-\[#[0-9A-Fa-f]{3,8}\]/g;

/** Paths that may carry a raw hex, with the reason. Keep this empty unless there is one. */
const ALLOWED: string[] = [];

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === 'node_modules' || entry === '__snapshots__') continue;
      out.push(...sourceFiles(full));
    } else if (/\.(tsx?|css)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

describe('colour comes from the token scale, never a literal', () => {
  const files = sourceFiles(SRC).filter((f) => !f.endsWith('noArbitraryHex.test.ts'));

  it('finds source files to scan', () => {
    // Vacuity guard. A broken walk returns [], and every it.each below then passes by describing
    // nothing at all -- the exact failure mode this suite exists to prevent elsewhere.
    expect(files.length).toBeGreaterThan(50);
  });

  it.each(files.map((f) => [f.slice(SRC.length), f] as const))(
    '%s uses no arbitrary hex colour',
    (relative, full) => {
      if (ALLOWED.includes(relative)) return;
      // `globals.css` is where the tokens are DEFINED, so hexes there are the point. It is
      // matched by path rather than listed in ALLOWED because it is not an exception to the
      // rule, it is the rule's source.
      if (relative.replace(/\\/g, '/').endsWith('styles/globals.css')) return;
      const offenders = [...readFileSync(full, 'utf8').matchAll(ARBITRARY_HEX)].map((m) => m[0]);
      expect(offenders, `${relative} hardcodes a colour; use a token from styles/globals.css`).toEqual([]);
    },
  );
});
