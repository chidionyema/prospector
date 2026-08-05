import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Geist Mono is the data voice, and only that.
 *
 * THE DECISION
 *
 * The site downloads three families (Hanken Grotesk, Newsreader, Geist Mono, see `_app.tsx`) and
 * the third one had no job. Counted on 2026-08-05 before this pass: 70 `font-mono` utilities
 * across 25 `.tsx` files, of which the overwhelming majority were section eyebrows, footer
 * headings, nav links and one full-width button -- human language, set in a typeface designed to
 * make `l` distinguishable from `1`.
 *
 * Founder decision, 2026-08-05: keep the family, restrict it to the evidence voice. Mono is for
 * things the reader might copy, compare or transcribe -- amounts, IDs and refs, filenames, scores,
 * source hostnames, keyboard keys, and the kill-gate / verdict tags. Everything decorative moves
 * to the sans.
 *
 * WHAT THIS TEST GUARDS
 *
 * The failure mode is drift back: the eyebrow pattern
 * (`font-mono text-[10px] font-bold uppercase tracking-widest text-muted`) appeared 40+ times
 * because it was copy-pasted, and it will be copy-pasted again from any surviving instance.
 * So the test pins a budget and pins the two coupling bugs the CSS rule used to have.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

function walk(dir: string, ext: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, ext, out);
    else if (entry.endsWith(ext)) out.push(path);
  }
  return out;
}

const TSX = walk(SRC, '.tsx')
  .filter((p) => !p.endsWith('_app.tsx')) // declares the next/font `variable`, not a class
  .map((path) => ({ path: path.slice(SRC.length), src: readFileSync(path, 'utf8') }));

// Comments stripped: this file's own prose names the classes under test, and a doc comment
// explaining that `.text-caption` must NOT set a family would otherwise match as if it did.
const CSS = readFileSync(join(SRC, 'styles', 'globals.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

describe('mono is the data voice', () => {
  it('is still in use, so this suite cannot pass by the family being deleted', () => {
    const total = TSX.reduce((n, f) => n + (f.src.match(/\bfont-mono\b/g)?.length ?? 0), 0);
    expect(total, 'no font-mono anywhere means the decision became "drop it"').toBeGreaterThan(10);
  });

  it('stays inside the data budget', () => {
    // 70 before this pass, 21 after: amounts, refs, filenames, scores, hostnames, <kbd>, and the
    // kill-gate tags. Raising this number means claiming a new kind of DATA exists.
    const total = TSX.reduce((n, f) => n + (f.src.match(/\bfont-mono\b/g)?.length ?? 0), 0);
    expect(total, `font-mono usages: ${total}`).toBeLessThanOrEqual(26);
  });

  it('the caption size utility is not secretly a typeface', () => {
    /*
     * `.text-caption` is a SIZE (`--text-caption: 0.75rem`). It used to share a declaration with
     * `.font-mono`, so every caption -- including `role="alert"` validation errors in ui/Field,
     * ui/Checkbox and ui/RadioGroup -- rendered monospaced and uppercased. Those are sentences.
     */
    const rule = /\.text-caption[^{]*\{[^}]*\}/g;
    for (const match of CSS.match(rule) ?? []) {
      expect(match, 'a size utility must not set a family').not.toMatch(/font-family/);
      expect(match, 'a size utility must not uppercase its content').not.toMatch(/text-transform/);
    }
  });

  it('the mono class sets a family and nothing else', () => {
    /*
     * `.font-mono` used to carry `text-transform: uppercase`, which reached the two values on the
     * site a reader is most likely to transcribe: `pack.dossierRef` and the order access token on
     * /orders/success. `text-transform` leaves the DOM alone, so copy-paste was always correct --
     * but anyone reading one off the screen read capitals that are not in the value.
     */
    const match = /\.font-mono\s*\{([^}]*)\}/.exec(CSS);
    expect(match, '.font-mono rule must exist in globals.css').not.toBeNull();
    const body = match![1];
    expect(body).toMatch(/font-family:\s*var\(--font-mono\)/);
    expect(body, 'must not uppercase the data it exists to render').not.toMatch(/text-transform/);
    expect(body, 'must not track out the data it exists to render').not.toMatch(/letter-spacing/);
  });

  it('no eyebrow is set in mono any more', () => {
    // The copy-pasted signature. The kill-gate and verdict tags are the deliberate exception:
    // they ARE the data (which gate, what verdict), and they are uppercase because that is the
    // ledger voice, so they are matched out by their semantic colour.
    const offenders: string[] = [];
    for (const { path, src } of TSX) {
      const lines = src.split('\n');
      lines.forEach((line, i) => {
        // A ±2 line window, because the tag's colour usually sits on the next line of a `cx()`
        // ternary rather than beside the classes (DossierPreview's SURVIVED / PUSHED BACK).
        const window = lines.slice(Math.max(0, i - 2), i + 3).join(' ');
        const isGateTag = /text-(?:warning|success|danger)\b/.test(window) || /Badge\.tsx$/.test(path);
        if (!isGateTag && /\bfont-mono\b/.test(line) && /\buppercase\b/.test(line)) {
          offenders.push(`${path}:${i + 1}  ${line.trim().slice(0, 100)}`);
        }
      });
    }
    expect(offenders, `an eyebrow is language, not data:\n${offenders.join('\n')}`).toEqual([]);
  });
});
