import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

/**
 * RED MEANS KILLED, AND ONLY KILLED (MASTER-BRIEF §2 and §6).
 *
 * §6 states the rule as a property of one component: `VerdictChip` is "the only place `--kill` may
 * appear". This test is what makes that true of the codebase rather than true of a sentence in a
 * brief.
 *
 * IT EXISTS BECAUSE HAND-FIXING DID NOT HOLD. Measured on this tree on 2026-08-17, before the
 * component was written, three sites drew a PUSHED-BACK check in the kill red:
 *
 *   CheckSequence.tsx:101  the numeral badge   `border-kill bg-kill-bg text-kill-strong`
 *   CheckSequence.tsx:139  the verdict word    `text-kill`
 *   CheckSequence.tsx:178  the summary count   `text-kill`
 *
 * while `HeroEvidenceStrip.tsx` drew the identical three states in amber, on the same page. Each
 * had been corrected by hand at least once before (see the colour-audit notes still in both
 * files), and each came back, because the next component to draw a verdict starts from a blank
 * className and picks a colour from memory.
 *
 * WHAT IT COSTS TO ADD A SITE. The allowlist below is the whole escape hatch, and each entry
 * carries the reason it is not a verdict on an idea. A new file that reaches for a kill utility
 * fails here and has two honest ways out: compose `VerdictChip`, or add itself to the list with a
 * sentence. That is the point -- not to make the colour unreachable, but to make reaching for it a
 * decision someone wrote down.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

/** Any Tailwind utility built on the kill colour: text, bg, border, ring, in any variant. */
const KILL_UTILITY = /(?:^|[\s'"`:[])(?:[a-z-]+:)*(?:text|bg|border|ring|from|to|via|fill|stroke|decoration|outline)-kill(?:-bg|-strong)?\b/;

/**
 * Files allowed to name the kill colour directly, each with the reason it is not a verdict chip.
 * Paths are relative to `src/`.
 */
const ALLOWED: Record<string, string> = {
  'components/ui/VerdictChip.tsx':
    'The component the rule is about. This is where the colour is decided.',
  'components/marketing/MarketingLayout.tsx':
    'The footer stat label "killed", above the count of killed ideas. It labels a population, ' +
    'not one ruling, so it is a stat label rather than a chip -- and the population really is ' +
    'the killed one.',
  'components/marketing/DocRail.tsx':
    'The pack reader rail marks the "what would sink this" section in the kill tone. It names ' +
    'the section that argues the idea should die; there is no verdict being rendered.',
  'pages/kill-log.tsx':
    'The page the colour exists for. Its table cells and chart bars are kills by definition. ' +
    'The header stat composes VerdictChip; the row-level uses are the corpus itself.',
};

/** Every `.ts`/`.tsx` under `src/`, tests and styles excluded, as `{ rel, src }`. */
function walk(dir: string = SRC, out: { rel: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules' || entry === 'data') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (/\.tsx?$/.test(entry)) {
      out.push({ rel: full.slice(SRC.length), src: readFileSync(full, 'utf8') });
    }
  }
  return out;
}

/** Comment lines are argument, not paint. A note explaining the rule must not trip the rule. */
function codeOnly(src: string): string[] {
  return src
    .split('\n')
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line));
}

describe('red is reserved for a kill', () => {
  const files = walk();

  it('reads a non-trivial tree, so a broken walk cannot pass vacuously', () => {
    expect(files.length).toBeGreaterThan(100);
  });

  it('names the kill colour only in VerdictChip and the four documented exceptions', () => {
    const offenders = files
      .filter(({ rel }) => !(rel in ALLOWED))
      .filter(({ src }) => codeOnly(src).some((line) => KILL_UTILITY.test(line)))
      .map(({ rel }) => rel);

    expect(
      offenders,
      `These files paint with the kill colour without being VerdictChip or an allowed exception. ` +
        `Compose <VerdictChip kind="killed" />, or add the file to ALLOWED with the reason it is ` +
        `not a verdict.`,
    ).toEqual([]);
  });

  it('keeps the allowlist honest: every entry still names the colour', () => {
    // An entry that no longer applies is a licence nobody is using and everybody inherits.
    const stale = Object.keys(ALLOWED).filter((rel) => {
      const file = files.find((f) => f.rel === rel);
      return !file || !codeOnly(file.src).some((line) => KILL_UTILITY.test(line));
    });
    expect(stale, 'Remove these from ALLOWED -- they no longer use the kill colour.').toEqual([]);
  });

  it('gives every allowed file a written reason', () => {
    for (const [rel, reason] of Object.entries(ALLOWED)) {
      expect(reason.length, `${rel} needs a real reason, not a placeholder`).toBeGreaterThan(40);
    }
  });
});
