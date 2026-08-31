import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

/**
 * A LINK INSIDE A SENTENCE THAT NOBODY CAN SEE IS A BROKEN LINK.
 *
 * axe measured this on the live site on 2026-08-30, run 33339472255, `link-in-text-block`,
 * severity serious, at 390 and at 1280, and both offending nodes were the two kill-gate captions
 * on the home page (`components/marketing/EvidenceBands.tsx`):
 *
 *   The link has insufficient color contrast of 2.31:1 with the surrounding text.
 *   (Minimum contrast is 3:1, link text: #2447c9, surrounding text: #8b9096)
 *   The link has no styling (such as underline) to distinguish it from the surrounding text
 *
 * WCAG 1.4.1 allows colour to be the only cue at 3:1 against the text around it. This pair is
 * 2.31:1. So on the band whose whole argument is that every rejection is published with its
 * reason, the link to that evidence was, for anyone who cannot separate those two greys, not
 * there.
 *
 * WHY NOTHING CAUGHT IT, WHICH IS THE PART WORTH KEEPING.
 *
 * Two rules already existed for exactly this, both in `storefrontDesignContract.test.ts`: "never
 * hides a link behind :hover alone" and "uses ONE inline-link treatment across the site". Neither
 * could fire, for two independent reasons, and both had to be fixed for this to be a guard:
 *
 *   1. They are BLOCKLISTS. Each names className patterns that are known to be wrong. The markup
 *      that shipped was `<Link href="/kill-log">read the kill log</Link>` with NO className at
 *      all, so it matched no pattern and inherited `mumchimp.css`'s `.src a{color:var(--link)}` --
 *      a colour and nothing else. A blocklist cannot see an omission.
 *   2. That file is on `SUSPENDED_UNTIL_UI_STABLE` in `vitest.config.ts` (founder, 2026-08-18:
 *      "ui is always changing", "why waste time and resources"), so it is excluded from the suite
 *      and every rule in it has been dead since. The suspension is correct and stays: it covers
 *      APPEARANCE -- hexes, radii, letter case. This rule is not appearance. The same block draws
 *      the line itself, and puts "a broken link" on the live side of it.
 *
 * So the rule is written here, in a file the suite runs, and as an allowlist: a link that shares
 * its paragraph with prose carries the house treatment, or it is named here with a reason.
 *
 * It fires only on a link that shares its paragraph with prose, which is the same shape axe
 * judges. A paragraph whose entire content is one link is a standalone control, not a link in a
 * text block -- `GuideLayout.tsx` draws its "Guides" back-link that way on purpose, and refusing
 * it would be a guard refusing correct work.
 */
const SRC = join(__dirname, '..');

/** The treatments that draw a cue other than colour. `textLinkClass` is the one for prose. */
const TREATED = /textLinkClass|\btlink\b|buttonClasses|chipClasses/;

function walkTsx(dir: string = SRC, out: { path: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) walkTsx(p, out);
    else if (entry.endsWith('.tsx')) out.push({ path: p.slice(SRC.length), src: readFileSync(p, 'utf8') });
  }
  return out;
}

/**
 * Every link that shares a `<p>` with prose, as `path:line  <tag>`.
 *
 * Comments are stripped first: `blocks.tsx` keeps the breadcrumb markup it deleted quoted in a
 * comment, and a quotation is not a call site.
 */
function proseLinks(source: string, relPath: string) {
  const found: { where: string; tag: string }[] = [];
  // Blanked rather than deleted, character for character, so the reported line number is the
  // line in the file the reader has to open.
  const blank = (m: string) => m.replace(/[^\n]/g, ' ');
  const src = source.replace(/\{\/\*[\s\S]*?\*\/\}/g, blank).replace(/\/\*[\s\S]*?\*\//g, blank);
  for (const open of src.matchAll(/<p(\s[^>]*)?>/g)) {
    const close = src.indexOf('</p>', open.index!);
    if (close === -1) continue;
    const body = src.slice(open.index!, close);
    // What is left once every link and its own text is removed. Tags and `{...}` expressions are
    // markup, so a letter surviving both means the link sits in a sentence rather than alone.
    const around = body
      .replace(/<(a|Link)\b[\s\S]*?<\/\1>/g, '')
      .replace(/<[^>]*>/g, '')
      .replace(/\{[^{}]*\}/g, '');
    if (!/[A-Za-z]/.test(around)) continue;
    // No `s` flag: `[^>]` already crosses newlines, and `s` needs an es2018 target this
    // tsconfig does not set -- `npx tsc --noEmit` fails on it with TS1501 while vitest,
    // which transpiles with esbuild, runs it green. Two instruments, one of them silent.
    for (const link of body.matchAll(/<(a|Link)\s[^>]*?>/g)) {
      const line = src.slice(0, open.index! + link.index!).split('\n').length;
      found.push({ where: `${relPath}:${line}`, tag: link[0].replace(/\s+/g, ' ') });
    }
  }
  return found;
}

describe('a link inside a sentence is findable without colour vision', () => {
  it('finds the shape that shipped, so this rule is proved on the defect it missed', () => {
    // The exact markup axe reported, byte for byte, from `EvidenceBands.tsx` before the fix.
    const shipped = `
      <p className="src num">
        Every kill published with its reason · <Link href="/kill-log" prefetch={false}>read the kill log</Link>
      </p>`;
    const found = proseLinks(shipped, 'fixture.tsx');
    expect(found).toHaveLength(1);
    expect(TREATED.test(found[0].tag)).toBe(false);
  });

  it('leaves a paragraph that is nothing but a link alone', () => {
    // `GuideLayout.tsx`'s back-link. A standalone control is not a link in a text block, and axe
    // does not judge it as one.
    const standalone = `
      <p className="mb-6 text-body">
        <Link href="/guides" className="inline-block py-3 text-muted hover:text-text">
          Guides
        </Link>
      </p>`;
    expect(proseLinks(standalone, 'fixture.tsx')).toEqual([]);
  });

  it('gives every link inside a sentence a cue that is not colour', () => {
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      // `components/ui` is where the treatments themselves are defined.
      if (/components\/ui\//.test(file.path)) continue;
      for (const link of proseLinks(file.src, file.path)) {
        if (TREATED.test(link.tag)) continue;
        offenders.push(`${link.where}  ${link.tag.slice(0, 100)}`);
      }
    }
    expect(
      offenders,
      `a link sharing a paragraph with prose needs textLinkClass() -- colour alone measured 2.31:1 against the text around it:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });
});
