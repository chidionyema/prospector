import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { COMMON_CHECKS, checkVerdicts } from '@/lib/checks';

const SRC = fileURLToPath(new URL('..', import.meta.url));

/**
 * The check count is lane-dependent, and the copy is not allowed to forget it.
 *
 * MEASURED 2026-08-06 against the live `/catalog` detail endpoint, all 63 published packs:
 * `qaVerdictSummary` reports "6/6 checks cleared" 40x, "8/8" 15x, "7/8" 4x, "9/9" 3x, "6/8" 1x.
 * So any sentence promising a buyer a fixed six is false for 23 of the 63 packs they can see,
 * on the pages they read before paying. The denominator varies because `config.yaml`'s
 * `lanes.side_hustle` adds buyer_intent, currency and claims_verifiable on top of the common set.
 *
 * WHY THIS FILE EXISTS RATHER THAN ONE MORE ASSERTION IN lTwoAboutPage.test.ts. That test was
 * written the same day for the same defect and reads exactly one file, `pages/about.tsx`. The
 * claim was never confined to one file: it also shipped in `lib/faqContent.ts`, in
 * `lib/copyConfig.ts` (variant b's methodology heading, "The checks every pack faced", sitting
 * above a list of exactly six steps), and in `pages/index.tsx` (six gate names in a row with
 * nothing after them). Two of those four survived the fix and were only found by a second sweep.
 * A guard scoped to the file that happened to be edited proves that file, and licenses the belief
 * that the site is clean. This one reads every rendered copy surface.
 *
 * Comments are stripped before matching, deliberately. Several of these files carry a long note
 * ABOUT the false claim -- including the one three lines above -- and a guard that could not tell
 * an explanation from a promise would force the explanations out, which is how the reasoning gets
 * deleted and the defect returns.
 */

/** Every source that can put words in front of a buyer. */
function copySurfaces(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === '__tests__' || entry.name === 'node_modules') continue;
        walk(path);
      } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
        out.push(path);
      }
    }
  };
  walk(join(SRC, 'pages'));
  walk(join(SRC, 'components'));
  out.push(join(SRC, 'lib', 'copyConfig.ts'), join(SRC, 'lib', 'faqContent.ts'));
  return out;
}

/**
 * Strip block, JSX and line comments. The `(?<!:)` on the line-comment arm matters: without it
 * every `https://…` in a source URL truncates the rest of its line, and a claim sitting after a
 * cited link would go unread by this test -- a guard that quietly stops looking is worse than no
 * guard, because it still reports green.
 */
function stripComments(source: string): string {
  return source
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, ' ')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(?<!:)\/\/[^\n]*/g, ' ');
}

/**
 * The shapes the claim has actually shipped in, plus the ones it would come back as. Each is a
 * promise that the set is closed: an article or quantifier, a number, and the noun.
 *
 * What is deliberately NOT banned: "Six fronts are common to every idea", and about.tsx quoting
 * the real distribution ('40 report "6/6 checks cleared", 15 "8/8"'). Both are true, both are the
 * fix, and a pattern coarse enough to catch them would make the honest sentence unwritable.
 */
const FORBIDDEN: { pattern: RegExp; why: string }[] = [
  {
    pattern: /\b(all|the|these|those|same|every|our)\s+(six|seven|eight|nine|[6-9])\s+(checks|gates|fronts|criteria)\b/i,
    why: 'promises a closed set of checks',
  },
  {
    pattern: /\bsurvived\s+(six|seven|eight|nine|\d+)\s+(checks|gates)\b/i,
    why: 'states a per-pack count the engine varies per lane',
  },
  {
    pattern: /\b(six|seven|eight|nine)\s+(brutal|rigid|rigorous|hard|exhaustive)\s+(checks|gates|criteria)\b/i,
    why: 'dresses a fixed count as rigour',
  },
  {
    pattern: /\bcleared\s+all\s+(six|seven|eight|nine|\d+)\b/i,
    why: 'claims a clean sweep of a fixed denominator',
  },
];

describe('no rendered copy promises a fixed number of checks', () => {
  const surfaces = copySurfaces();

  it('sweeps every page, component and copy library, not just the file last edited', () => {
    // Guards the guard. If the walk silently resolves nothing -- a moved directory, a renamed
    // `pages/` -- every assertion below passes vacuously and the sweep reports clean having read
    // no bytes at all.
    expect(surfaces.length, 'the copy sweep found no sources to read').toBeGreaterThan(20);
    expect(surfaces.some((f) => f.endsWith('index.tsx'))).toBe(true);
    expect(surfaces.some((f) => f.endsWith('copyConfig.ts'))).toBe(true);
    expect(surfaces.some((f) => f.endsWith('about.tsx'))).toBe(true);
  });

  it('carries no fixed-count claim in any of them', () => {
    const violations: string[] = [];
    for (const file of surfaces) {
      const body = stripComments(readFileSync(file, 'utf8'));
      for (const { pattern, why } of FORBIDDEN) {
        const hit = body.match(pattern);
        if (hit) {
          const line = body.slice(0, hit.index).split('\n').length;
          violations.push(`${file.slice(SRC.length)}:${line} "${hit[0]}" -- ${why}`);
        }
      }
    }
    // Reported as the offending file, line and phrase, never a count: a failure has to be fixable
    // from the message without re-running the sweep by hand.
    expect(violations).toEqual([]);
  });
});

describe('the methodology surfaces hedge the count where they enumerate it', () => {
  /*
   * Both of these render a list of exactly six things. A list of six with no qualifier beside it
   * IS the claim, whatever the heading says -- which is why banning the phrase alone is not
   * enough, and why these two are asserted positively rather than by absence.
   */
  // `depends?` and the `which …` alternatives are not padding of a lax rule: variant c hedges as
  // "The criteria applied DEPEND on the model under review … each dossier records WHICH WERE RUN",
  // and the first cut of this regex spelled only `depends`, failing correct copy. A guard that
  // fails the fix teaches the next reader to delete the guard.
  const HEDGE = /\bcommon\b|\bdepends?\b|\bsome\s+(ideas|face)\b|\bwhich\s+(checks|ones|were)\b|\bfaced\b/i;

  it('every copy variant intros the /how-it-works timeline with a hedge', () => {
    const config = readFileSync(join(SRC, 'lib', 'copyConfig.ts'), 'utf8');
    const descriptions = [...config.matchAll(/sixChecksDescription:\s*\n?\s*'((?:[^'\\]|\\.)*)'/g)].map(
      (m) => m[1],
    );
    // Three variants ship (a/b/c, `getCopyVariant.ts`); a missing one means the regex drifted off
    // the field rather than that the copy is fine.
    expect(descriptions.length, 'expected one sixChecksDescription per copy variant').toBe(3);
    const unhedged = descriptions.filter((d) => !HEDGE.test(d));
    expect(unhedged, 'each variant sits above six timeline steps and must qualify the set').toEqual(
      [],
    );
  });

  it('the homepage method band qualifies its list of check verdicts', () => {
    const page = stripComments(readFileSync(join(SRC, 'pages', 'index.tsx'), 'utf8'));
    // The list is DERIVED from `COMMON_CHECKS` (lib/checks.ts) rather than typed out, which is
    // itself the fix for how this row was missed last time: the earlier sweep updated about.tsx
    // and faqContent.ts and left this literal behind. So the guard anchors on the call site, and
    // separately asserts what the call actually produces.
    //
    // The band listed `engineGateIds()` until 2026-08-07 ("pain reality · value durability · ..."),
    // six machine identifiers naming the subject of each check and never its conclusion. It lists
    // `checkVerdicts()` now, which is the kill log's own wording. The count claim this test exists
    // to police is unchanged: six items, and a hedge beside them.
    expect(checkVerdicts(), 'the derived list no longer carries the kill log verdicts').toContain(
      'The pain was not real',
    );
    expect(checkVerdicts().length, 'the list must be the full common set').toBe(COMMON_CHECKS.length);
    const enumeration = page.indexOf('checkVerdicts()');
    expect(enumeration, 'the verdict list is gone or renamed').toBeGreaterThan(-1);
    // Adjacent to the row, not merely somewhere on a 1,700-line page. The window is the
    // enumeration plus the element that follows it, and it is deliberately narrow: the first cut
    // required the hedge in the SAME <p>, which was the wrong shape -- the mono row is set in the
    // engine's own gate identifiers, so the site's own sentence has to be a separate element or it
    // reads as a seventh gate. 320 characters is the qualifying paragraph and nothing beyond it.
    const window = page.slice(enumeration, enumeration + 320);
    expect(
      HEDGE.test(window),
      'the six gate names must be qualified immediately beside where they are listed',
    ).toBe(true);
  });
});
