import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { COMMON_CHECKS, checkForGate, checksSentence, engineGateIds, idsFor } from '../checks';

/**
 * One vocabulary for the checks, across every surface that names them.
 *
 * MEASURED 2026-08-06: the same six gates were written out independently in eight places, in four
 * mutually inconsistent lexicons. `payer_solvency` alone was "Someone will pay" on /about,
 * "Payer can actually pay" on /how-it-works and "Whether anyone will actually pay" on the pack
 * page. A visitor reading two pages met two vocabularies for one mechanism with no way to tell
 * whether they were the same gate or two different ones.
 *
 * This is the guard that stops it fragmenting again. It is deliberately a source scan and not
 * just a unit test of the module: the failure mode is not the module going wrong, it is a page
 * quietly typing its own list beside it, which no test of the module could ever see.
 */

/** `src/`, from `src/lib/__tests__/`. */
const SRC = fileURLToPath(new URL('../..', import.meta.url));

/**
 * Every .ts/.tsx copy surface, minus three deliberate exclusions:
 *
 *   - `lib/checks.ts` itself, which quotes all four retired lexicons in its own docblock as the
 *     record of what it replaced;
 *   - `__tests__`, including this file, for the same reason;
 *   - `lib/copyConfig.ts`. This one is a judgement call and not an oversight. It holds three
 *     marketing voices under a live A/B test (`lib/getCopyVariant.ts`) that differ in EVERY
 *     sentence by design, and variant c describes the filter as "verified market pain,
 *     quantifiable value, fragmented incumbents, a solvent payer base, viable acquisition
 *     channels, and regulatory compliance". Rewriting that to the canonical prose would make it
 *     word-for-word variant a and silently delete the experiment. What actually matters there is
 *     already guarded, and more tightly: `__tests__/fixedCheckCount.test.ts` asserts each of the
 *     three variants hedges the count. Running prose in a voice under test is not a rival
 *     LABEL for a gate, which is the defect this file exists to catch.
 */
const EXCLUDED = [join('lib', 'checks.ts'), join('lib', 'copyConfig.ts')];

function copySurfaces(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) {
        if (entry === '__tests__' || entry === 'node_modules') continue;
        walk(path);
        continue;
      }
      if (!/\.tsx?$/.test(entry)) continue;
      if (EXCLUDED.some((tail) => path.endsWith(tail))) continue;
      out.push(path);
    }
  };
  walk(SRC);
  return out;
}

/**
 * Comments out, before matching. Four of these files carry a note explaining WHICH rival name they
 * used to ship and why it went -- `how-it-works.tsx` names two of them in a docblock. A guard that
 * cannot tell a post-mortem from a live label would force those explanations out of the tree,
 * which is how the reasoning gets deleted and the defect walks back in. Mirrors the same helper in
 * `__tests__/fixedCheckCount.test.ts`, `(?<!:)` and all, so a source URL cannot blind the scan.
 */
function stripComments(source: string): string {
  return source
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, ' ')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(?<!:)\/\/[^\n]*/g, ' ');
}

describe('the check vocabulary is defined once', () => {
  it('no copy surface re-declares a competing name for a gate', () => {
    // The exact strings that shipped as rival names for gates that already had one. Each was live
    // in the tree on 2026-08-06, on the surface named beside it.
    //
    // NOT listed: "Real demand". It survives in `pack/[id].tsx` as the label for the `pain_acuity`
    // SCORE axis, which is a different engine field from the `pain_reality` gate -- a survivor is
    // ranked on the axes, it is not killed by them. The genuine collision in that map was
    // `distribution`, an id in both sets carrying two names on one page; it now defers to
    // `checkForGate`, and the assertion below is what holds it there.
    const retiredNames = [
      'Someone will pay', //         /about
      'Payer can actually pay', //   /how-it-works
      'durable value', //            faqContent.ts, llms.txt.tsx, ideas/[slug].tsx
      'a solvent payer', //          the same three
      'a distribution route', //     llms.txt.tsx
      'a route to distribution', //  ideas/[slug].tsx
    ];
    const offenders: string[] = [];
    for (const path of copySurfaces()) {
      const text = stripComments(readFileSync(path, 'utf8'));
      for (const name of retiredNames) {
        if (text.includes(name)) offenders.push(`${path.replace(SRC, '')}: "${name}"`);
      }
    }
    expect(
      offenders,
      'these are rival names for gates that already have one in lib/checks.ts',
    ).toEqual([]);
  });

  it('sweeps a real tree, not an empty one', () => {
    // Guards the guard: if the walk resolves nothing, every scan above passes having read no
    // bytes and reports clean.
    const surfaces = copySurfaces();
    expect(surfaces.length, 'the lexicon sweep found no sources to read').toBeGreaterThan(20);
    expect(surfaces.some((f) => f.endsWith(join('pages', 'about.tsx')))).toBe(true);
    expect(surfaces.some((f) => f.endsWith(join('pages', 'how-it-works.tsx')))).toBe(true);
    expect(
      surfaces.some((f) => f.endsWith(join('lib', 'checks.ts'))),
      'the vocabulary module must be excluded, it quotes every retired name',
    ).toBe(false);
  });

  it('every surface that spells the set out derives it, rather than re-typing it', () => {
    // The absence scan above only catches a regression written in the OLD words. A page that
    // hand-types the CURRENT six is just as broken -- it is the next divergence, already written,
    // waiting for one of the six to be reworded. So each surface is pinned to its call site.
    //
    // The rule is "derives OR does not spell it out". A surface whose answer no longer names
    // the set at all (e.g. the FAQ's "grounded" answer was cut to 28 words per the email, no
    // checks in it) is held to the second half by the "names none by hand" assertion in the
    // next test. Pinning a call site the page no longer has would fail forever while proving
    // nothing.
    const derived: [string, string][] = [
      [join('pages', 'llms.txt.tsx'), 'checksSentence()'],
      [join('pages', 'ideas', '[slug].tsx'), 'checksSentence()'],
      // Was `engineGateIds()` until 2026-08-07. The homepage method band no longer lists the
      // checks at all (the email deletes the jargon strip from the homepage entirely), so the
      // pin moves to a negative: the page must not enumerate the set. The pin for /how-it-works
      // and /pack covers the surfaces that DO spell the set out.
      [join('pages', 'how-it-works.tsx'), 'COMMON_CHECKS.map'],
      [join('pages', 'pack', '[id].tsx'), 'COMMON_CHECKS.map'],
    ];
    for (const [file, callSite] of derived) {
      const text = stripComments(readFileSync(join(SRC, file), 'utf8'));
      expect(text, `${file} no longer derives its check names from lib/checks.ts`).toContain(
        callSite,
      );
    }
  });

  /*
   * The other half of the rule, for a surface that stopped deriving the set.
   *
   * "Derives it or does not spell it out" is the actual contract; the list above only pins the
   * first half. /about is the one page that took the second branch, so it is held to it: it must
   * hand-type NONE of the canonical names. That is strictly tighter than the row it replaces,
   * which a page could satisfy by mapping `COMMON_CHECKS` and re-typing three of them beside it.
   */
  it('a surface that no longer derives the set does not re-type it either', () => {
    const text = stripComments(readFileSync(join(SRC, 'pages', 'about.tsx'), 'utf8'));
    const typed = COMMON_CHECKS.filter(
      (c) => text.includes(c.name) || text.includes(c.refutation) || text.includes(c.question),
    ).map((c) => c.id);
    expect(
      typed,
      'pages/about.tsx names checks by hand; derive them from lib/checks.ts or do not list them',
    ).toEqual([]);
  });

  it('every check carries all four registers, none of them empty', () => {
    for (const check of COMMON_CHECKS) {
      expect(check.id, 'gate id must be the engine spelling').toMatch(/^[a-z_]+$/);
      expect(check.name.length, `${check.id} name`).toBeGreaterThan(0);
      expect(check.question.endsWith('?'), `${check.id} question must be a question`).toBe(true);
      expect(check.refutation.length, `${check.id} refutation`).toBeGreaterThan(0);
      expect(check.prose, `${check.id} prose is for use mid-sentence`).toBe(
        check.prose.toLowerCase(),
      );
      expect(check.verdict.length, `${check.id} verdict`).toBeGreaterThan(0);
    }
  });

  /*
   * The verdict register is the one that is not ours to word.
   *
   * The other three are the site's voice. `verdict` is the engine's: /kill-log prints these exact
   * strings as its filter chips and on every row, and the homepage shows them so a reader who
   * follows the link meets the sentence they just read on records they can open. If the two drift,
   * the homepage is describing a receipt that does not exist, which is the same defect class as a
   * pack claiming a source it never fetched.
   *
   * Gates absent from the current log are skipped rather than failed: the log is a rolling window
   * of the newest kills, so "no idea has died on legality lately" is a fact about the engine, not
   * a copy defect.
   */
  it('each verdict is the kill log verbatim', () => {
    const log = JSON.parse(
      readFileSync(join(SRC, 'data', 'kill-log.json'), 'utf8'),
    ) as { entries: { gate: string; gateLabel: string }[] };
    const labelForGate = new Map<string, string>();
    for (const entry of log.entries) labelForGate.set(entry.gate, entry.gateLabel);
    // Guards the guard: an empty or reshaped log would make every assertion below vacuous.
    expect(labelForGate.size, 'kill-log.json carried no gate labels to compare against').toBeGreaterThan(0);

    const drifted: string[] = [];
    let compared = 0;
    for (const check of COMMON_CHECKS) {
      for (const id of idsFor(check)) {
        const label = labelForGate.get(id);
        if (!label) continue;
        compared += 1;
        if (label !== check.verdict) drifted.push(`${id}: log "${label}" vs checks.ts "${check.verdict}"`);
      }
    }
    expect(compared, 'no common gate appears in the kill log; the comparison read nothing').toBeGreaterThan(0);
    expect(drifted, 'the homepage would print a verdict the kill log never uses').toEqual([]);
  });

  it('ids and aliases are unique across the set', () => {
    const all = COMMON_CHECKS.flatMap((c) => idsFor(c));
    expect(new Set(all).size, 'two checks claim the same engine gate id').toBe(all.length);
  });

  it('resolves the distribution gate under both engine spellings', () => {
    // `side_hustle` calls it route_to_market, the other lanes call it distribution. One name.
    expect(checkForGate('distribution')?.name).toBe('A route to the buyer');
    expect(checkForGate('route_to_market')?.name).toBe('A route to the buyer');
    // The catalogue field arrives with the underscores already spaced out.
    expect(checkForGate('route to market')?.name).toBe('A route to the buyer');
    expect(checkForGate('buyer_intent'), 'lane-specific gates are not in the common set').toBeNull();
    expect(checkForGate(null)).toBeNull();
  });

  it('builds the inline sentence and the engine row from the same source', () => {
    const sentence = checksSentence();
    for (const check of COMMON_CHECKS) {
      expect(sentence, `${check.id} missing from the FAQ sentence`).toContain(check.prose);
    }
    expect(sentence, 'Oxford comma, to match the house voice').toContain(', and ');

    const row = engineGateIds();
    for (const check of COMMON_CHECKS) {
      expect(row).toContain(check.id.replace(/_/g, ' '));
    }
    expect(row, 'the row quotes the engine, so it must not contain underscores').not.toContain('_');
  });
});
