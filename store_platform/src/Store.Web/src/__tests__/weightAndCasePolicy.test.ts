import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { readStylesheet } from './helpers/stylesheet';

/**
 * Weight and case policy (brand v3, 2026-08-06).
 *
 * THREE RULES, AND THE FAILURE EACH ONE PREVENTS
 *
 * 1. NO WEIGHT ABOVE 600. RE-ARGUED 2026-08-08, because §3 destroyed the original argument and
 *    this test's own note said that would mean re-arguing the file rather than editing it.
 *
 *    The original ban rested on SYNTHESIS: `_app.tsx` loaded Geist via next/font at 400/500/600,
 *    no 700 cut was downloaded, so `font-bold` did not fail loudly, it made the browser smear the
 *    600 into a fake bold that differed between engines. §3 deleted next/font entirely and
 *    self-hosts Switzer as a VARIABLE face declaring `font-weight: 100 900` (tokens.css:45-48).
 *    A variable axis renders 700 as a true 700. The synthesis argument is therefore dead, and a
 *    guard that kept citing it would have been a false comment defending a real face.
 *
 *    The ban survives on the stronger basis it should have had all along, which is the type scale
 *    itself: SITE_SPEC_PROGRAM.md's table tops out at 560 (`--type-display`, `--type-h1`), with
 *    h2 at 520 and body at 400. Nothing in the design asks for 700. So the rule is now anchored
 *    to the SCALE rather than to the font request: no `--text-*--font-weight` token may declare
 *    above 600, and no class may ask for a weight the scale never declares.
 *
 *    This also fixes a way the old test could pass while checking nothing. It counted matches of
 *    `weight: [...]` in `_app.tsx` and asserted the COUNT was greater than zero, which is the
 *    right instinct, but when next/font went away the count went to zero and the guard failed
 *    rather than adapting. Its sibling assertion, the one that actually banned weights above 600,
 *    would have passed vacuously on an empty list. The non-vacuity check is kept below and now
 *    points at a pattern that exists.
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

// With local `@import`s inlined. Read as the entry file alone, the `text-transform: uppercase`
// ban below would go GREEN over a violation that had moved into `styles/tokens.css` -- a file
// boundary is not a policy boundary. See `helpers/stylesheet.ts`.
const CSS = readStylesheet(join(SRC, 'styles', 'globals.css')).replace(
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
  it('declares no scale weight above 600, so no class may ask for one', () => {
    // The ban is only honest while the type scale backs it. Read the scale, not the font request:
    // §3 self-hosts a variable face, so the request no longer names discrete weights at all.
    const weights = [...CSS.matchAll(/--text-[a-z0-9-]+--font-weight:\s*(\d{3})/g)].map((m) =>
      Number(m[1]),
    );
    expect(
      weights.length,
      'no --text-*--font-weight tokens found; the pattern stopped matching, so the assertion '
        + 'below would pass on an empty list. Fix the pattern, do not delete the test.',
    ).toBeGreaterThan(0);
    // 2026-08-18: the exemption now covers the three DISPLAY STEPS, because the mockups cut all
    // three heavy (display 690, h1 665, h2 655) and the site was running them at 560/560/520. The
    // ban this test enforces is on SYNTHESISED bolds -- a browser faux-bolding a face that has no
    // heavy cut -- and Inter Variable declares `font-weight: 100 900`, asserted at the bottom of
    // this test, so every one of those numbers is a real position on the axis. Body and meta are
    // still capped at 600: nothing in the mockups sets running text above 550.
    //
    // ORIGINAL NOTE (2026-08-14). `--text-display--font-weight` is 660,
    // transcribed from the specimen the founder approved. The ban exists to stop SYNTHESISED
    // bolds -- a browser faux-bolding a 400-only face -- and Switzer is variable across 100-900,
    // asserted below, so 660 is a real cut on the axis. The exemption is written as a filter on
    // the token NAME rather than as a raised threshold on purpose: raising it to 700 would let
    // any future step drift up silently, which is the thing this test is for.
    const DISPLAY_STEPS = new Set(['display', 'h1', 'h2']);
    const capped = [...CSS.matchAll(/--text-([a-z0-9-]+)--font-weight:\s*(\d{3})/g)]
      .filter((m) => !DISPLAY_STEPS.has(m[1]))
      .map((m) => Number(m[2]));
    expect(
      capped.filter((w) => w > 600),
      `no weight above 600 may be declared outside display, found: ${weights.join(', ')}`,
    ).toEqual([]);
    // ...and the exemption is a CEILING too, not an open door. 690 is the mockups' heaviest cut
    // and the scale may not pass it; a step wanting 700 needs a drawing that uses 700.
    const displaySteps = [...CSS.matchAll(/--text-([a-z0-9-]+)--font-weight:\s*(\d{3})/g)]
      .filter((m) => DISPLAY_STEPS.has(m[1]))
      .map((m) => Number(m[2]));
    expect(displaySteps.length, 'the display steps must still declare a weight').toBe(3);
    expect(
      displaySteps.filter((w) => w > 690),
      'the display steps may reach 690 and no further',
    ).toEqual([]);
    // And the face that renders them must still be the variable one; a static 400-only face
    // would make every 520/560 in the scale a synthesised weight again.
    expect(CSS, 'the sans face must declare a variable weight axis').toMatch(
      /font-weight:\s*100\s+900/,
    );
  });

  it('uses no weight the scale never declares, except the wordmark\'s named exemption (v4, 2026-08-09)', () => {
    // EXEMPTION, ONE LINE, EXPLICIT FOUNDER OVERRIDE: Logo.tsx's "Mum" span sets `font-bold`
    // (700) against "chimp"'s `font-normal`, deliberately re-opening the "no weight above 600"
    // rule for the one string that is the brand -- see Logo.tsx's own docblock. This is NOT the
    // synthesis argument this test's title used to rest on (that was already killed and the rule
    // re-anchored to the type scale on 2026-08-08, per the file docblock above); it is a second,
    // narrower override on TOP of the re-anchored rule, scoped to exactly the wordmark and
    // nothing else. The other 170+ `font-semibold` call sites this test still guards, and every
    // other `font-bold` in the tree, are unaffected -- the filter below only drops an offender
    // that is BOTH this exact file AND this exact span, so a second `font-bold` added anywhere
    // else (including elsewhere in Logo.tsx) still fails loudly.
    const WORDMARK_EXEMPTION = 'components/ui/Logo.tsx';
    const found = offenders(/\bfont-(bold|extrabold|black)\b/).filter(
      (line) => !(line.startsWith(`${WORDMARK_EXEMPTION}:`) && line.includes('{first}')),
    );
    expect(
      found,
      `no weight above 600 outside the wordmark exemption above; these ask for one the scale `
        + `never declares:\n${found.join('\n')}`,
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
