import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * One way to draw "a source you can open".
 *
 * `SITE_SPEC_PROGRAM.md` §4 calls the source chip a sitewide primitive: "any sourced claim gets
 * one". On 2026-08-07 there were five implementations of it, in two visual languages, differing in
 * colour, padding, glyph and even `rel`. Two omitted `nofollow` on a site that links out to 51
 * sources from a single pack page.
 *
 * The instructive part is not the count, it is that the tree already BELIEVED it had one.
 * `HeroEvidenceStrip.tsx` carried, in prose, above markup that shared nothing with it:
 *
 *     "the -45deg arrow copy `SourceChips` on `/sample` deliberately: this site has one way of
 *      drawing 'a source you can open'"
 *
 * and `EvidenceRecordPanel.tsx` said the same thing about the same non-existent shared markup. Two
 * comments asserting a consistency neither had. A comment cannot fail, so both stayed true-looking
 * for as long as anyone cared to read them. This file is the version that can fail.
 *
 * It matches on BEHAVIOUR, not on class strings: an external anchor whose visible content is a
 * hostname. Pinning the classes would make every legitimate restyle a test failure and this file
 * would be deleted within a month -- the same reasoning as `factOwnership.test.ts`.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

/** The primitive itself, plus the thin named wrappers that delegate to it. */
const ALLOWED = new Set(['components/ui/SourceChip.tsx']);

function sourceFiles(dir: string = SRC, out: { path: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '__tests__' || entry === '__snapshots__') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) sourceFiles(full, out);
    else if (/\.tsx$/.test(entry)) {
      out.push({ path: full.slice(SRC.length).replace(/\\/g, '/'), src: readFileSync(full, 'utf8') });
    }
  }
  return out;
}

/** Comments blanked, newlines kept so line numbers survive. */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/^\s*\/\/.*$/gm, '');
}

/**
 * An `<a>` opening a new tab. `target="_blank"` is the signature of "leaves this site", which is
 * what a source link is and what an internal `<Link>` never is.
 */
const EXTERNAL_ANCHOR = /<a\b[^>]*?target=\{?["']_blank["']\}?[\s\S]*?<\/a>/g;

/** A bare hostname rendered as the anchor's visible text -- `{domain}`, `{host}`, `{s.domain}`. */
const RENDERS_A_HOST = /\{[\w.?\s[\]]*\b(domain|host|hostname)\b[\w.?\s[\]()]*\}/i;

export function handRolledSourceLinks(file: { path: string; src: string }): string[] {
  if (ALLOWED.has(file.path)) return [];
  const stripped = stripComments(file.src);
  return [...stripped.matchAll(EXTERNAL_ANCHOR)]
    .filter((m) => RENDERS_A_HOST.test(m[0]))
    .map((m) => {
      const line = stripped.slice(0, m.index).split('\n').length;
      return `${file.path}:${line}`;
    });
}

describe('§4 source chip -- exactly one implementation', () => {
  const files = sourceFiles();

  it('finds source files to scan', () => {
    // Vacuity guard. A broken walk returns [], and the assertion below then passes by describing
    // nothing -- which is precisely the state this suite exists to make impossible.
    expect(files.length, 'the tsx walk found nothing').toBeGreaterThan(40);
    expect(files.map((f) => f.path)).toContain('components/ui/SourceChip.tsx');
  });

  it('no page or component hand-rolls an external link that renders a hostname', () => {
    const offenders = files.flatMap(handRolledSourceLinks);
    expect(
      offenders,
      `These render a source link without going through <SourceChip>:\n  ${offenders.join('\n  ')}\n` +
        `§4 makes the source chip a sitewide primitive. Five private copies is what the tree had ` +
        `before it was one, and they had drifted apart on colour, padding and rel=nofollow. Use ` +
        `<SourceChip> or <SourceChipRow> from '@/components/ui'.`,
    ).toEqual([]);
  });

  it('every source link is rel=nofollow', () => {
    // Two of the five omitted it. These are cited sources, not endorsements.
    const chip = readFileSync(join(SRC, 'components/ui/SourceChip.tsx'), 'utf8');
    const rels = [...chip.matchAll(/rel:\s*'([^']+)'|rel="([^"]+)"/g)].map((m) => m[1] ?? m[2]);
    expect(rels.length, 'SourceChip declares no rel at all').toBeGreaterThan(0);
    for (const rel of rels) {
      expect(rel, 'a source link must not pass link equity').toContain('nofollow');
      expect(rel, 'target=_blank without noopener is a tabnabbing hole').toContain('noopener');
    }
  });
});

describe('§4 source chip -- the guard itself fires', () => {
  // Three synthetic cases. A guard whose failure path has never run is a guard trusted on its
  // shape, and this whole file exists because prose was trusted on its shape.
  it('catches a hand-rolled anchor rendering a hostname', () => {
    const offenders = handRolledSourceLinks({
      path: 'components/marketing/Invented.tsx',
      src: '<a href={s.url} target="_blank" rel="noopener">{s.domain}</a>',
    });
    expect(offenders).toEqual(['components/marketing/Invented.tsx:1']);
  });

  it('ignores an ordinary external link that is not a source', () => {
    // Without this the rule would ban every outbound link on the site and be reverted on sight.
    const offenders = handRolledSourceLinks({
      path: 'components/marketing/Invented.tsx',
      src: '<a href="https://stripe.com" target="_blank" rel="noopener">Read the terms</a>',
    });
    expect(offenders).toEqual([]);
  });

  it('does not accuse the primitive itself', () => {
    const offenders = handRolledSourceLinks({
      path: 'components/ui/SourceChip.tsx',
      src: '<a href={url} target="_blank" rel="noopener nofollow">{host}</a>',
    });
    expect(offenders).toEqual([]);
  });
});
