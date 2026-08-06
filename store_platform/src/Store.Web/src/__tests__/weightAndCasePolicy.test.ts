import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Weight and case policy (brand v3, 2026-08-06).
 *
 * THREE RULES, AND THE FAILURE EACH ONE PREVENTS
 *
 * 1. NO WEIGHT ABOVE 600. `_app.tsx` loads Geist at 400/500/600 and Geist Mono at 400/500 — no
 *    700 cut is downloaded. A `font-bold` class does not therefore fail loudly; the browser
 *    SYNTHESISES the weight by smearing the 600, which renders heavier and wider than a real cut
 *    and differs between engines. That is invisible in a diff, invisible in a unit test, and
 *    visible on the page. So the class is banned rather than the weight being added: 600 is the
 *    heaviest anything on this site gets, and if that ever changes the font request has to change
 *    with it, in the same commit.
 *
 * 2. NO `uppercase` OUTSIDE MONO. All-caps set in a proportional face is a shouting device, and
 *    it is the one this redesign was called in to remove — the rejected v2 had the signature
 *    `font-mono text-[10px] font-bold uppercase tracking-widest` eyebrow copy-pasted 40+ times.
 *    Case is also data: `text-transform` leaves the DOM alone, so an uppercased pack ID or order
 *    token copy-pastes correctly but is read off the screen wrong. Where all-caps IS the right
 *    voice — a kill-gate tag, a market code — the value is uppercased in the DOM
 *    (`.toUpperCase()`), which this test permits, because then the screen and the clipboard agree.
 *
 * 3. NO WIDE TRACKING. `tracking-widest` / `tracking-[0.2em]` letterspaced small caps is the
 *    single most dated device the audit found, and on this site it had been applied to the price.
 *
 * All three are at ZERO in the working tree as of 2026-08-06; every surviving textual match is
 * inside a rationale comment, which is why this file strips comments before searching. Reproduce:
 *   grep -rn 'font-bold\|font-extrabold\|font-black' src --include='*.tsx' | grep -v __tests__
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (entry.endsWith('.tsx') || entry.endsWith('.ts')) out.push(path);
  }
  return out;
}

/**
 * Comments stripped, because this codebase documents WHY each banned class went, naming it. A
 * test that cannot tell `font-bold` in a class list from `font-bold` in the sentence explaining
 * its removal makes the rationale unwritable, and the rationale is the thing that stops the
 * class coming back.
 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '');
}

const FILES = walk(SRC).map((path) => ({
  path: path.slice(SRC.length),
  src: stripComments(readFileSync(path, 'utf8')),
}));

const CSS = readFileSync(join(SRC, 'styles', 'globals.css'), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
);

function offenders(pattern: RegExp): string[] {
  const found: string[] = [];
  for (const { path, src } of FILES) {
    src.split('\n').forEach((line, i) => {
      if (pattern.test(line)) found.push(`${path}:${i + 1}  ${line.trim().slice(0, 110)}`);
    });
  }
  return found;
}

describe('weight and case policy', () => {
  it('loads no weight above 600, so no class may ask for one', () => {
    const app = readFileSync(join(SRC, 'pages', '_app.tsx'), 'utf8');
    // The ban is only honest while the font request backs it. If a 700 is ever loaded, the
    // synthesis argument evaporates and this whole file needs re-arguing rather than editing.
    const weights = [...app.matchAll(/weight:\s*\[([^\]]*)\]/g)].flatMap((m) =>
      m[1].split(',').map((w) => Number(w.replace(/["'\s]/g, ''))),
    );
    expect(weights.length, 'no next/font weight arrays found; the pattern stopped matching')
      .toBeGreaterThan(0);
    expect(
      weights.filter((w) => w > 600),
      `no weight above 600 may be requested, found: ${weights.join(', ')}`,
    ).toEqual([]);
  });

  it('uses no synthesised bold weight', () => {
    const found = offenders(/\bfont-(bold|extrabold|black)\b/);
    expect(
      found,
      `600 is the heaviest weight loaded; these synthesise:\n${found.join('\n')}`,
    ).toEqual([]);
  });

  it('sets nothing in all-caps via CSS', () => {
    const found = offenders(/\buppercase\b/);
    expect(
      found,
      `uppercase the VALUE (.toUpperCase()) if caps are the voice:\n${found.join('\n')}`,
    ).toEqual([]);
    expect(CSS, 'no utility in globals.css may uppercase its content').not.toMatch(
      /text-transform:\s*uppercase/,
    );
  });

  it('letterspaces nothing out into small caps', () => {
    const found = offenders(/\btracking-(widest|wider)\b|\btracking-\[0\.[12]\d*em\]/);
    expect(found, `letterspaced small caps is the dated device:\n${found.join('\n')}`).toEqual([]);
  });

  it('still uses 600 somewhere, so this suite cannot pass by all emphasis being deleted', () => {
    const semibold = FILES.reduce(
      (n, f) => n + (f.src.match(/\bfont-semibold\b/g)?.length ?? 0),
      0,
    );
    expect(semibold, 'headings must still carry weight; 600 is the tool for it').toBeGreaterThan(
      20,
    );
  });
});
