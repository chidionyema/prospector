import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

/**
 * ONE BREADCRUMB TRAIL PER PAGE.
 *
 * `PageHero` drew its own `<p className="crumb">Catalogue / {eyebrow}</p>` while `MarketingLayout`
 * drew `<Breadcrumbs>` -- the same `.crumb` line from the same drawing -- immediately above it, so
 * all five pages that render a hero rendered the trail twice. Measured on the live site
 * (`curl -s https://mumchimp.com/packs`, 2026-08-30), the page opened:
 *
 *     Catalogue / Every pack
 *     Catalogue / 77 packs
 *     77 packs
 *     Every pack
 *
 * Neither trail knew about the other, which is the whole defect: a second component quietly
 * claiming to be the breadcrumb is invisible in a diff and only shows up on the rendered page.
 * This is also an accessibility fault, not only a visual one -- two things speak as the trail and
 * only one of them is a `nav`/`ol` with `aria-current`.
 *
 * So the class is closed at the source: `.crumb` is emitted by exactly ONE component. A new
 * component hand-rolling a breadcrumb line fails here rather than on a screenshot.
 */
const WEB = path.resolve(__dirname, '../../..');
const OWNER = 'src/components/ui/Breadcrumbs.tsx';
const EMITS_CRUMB = /className=(?:"crumb"|\{[^}]*['"`]crumb['"`])/;

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === '__tests__' || e.name === '.next') continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) sourceFiles(full, out);
    else if (e.name.endsWith('.tsx')) out.push(full);
  }
  return out;
}

describe('the breadcrumb trail is drawn once', () => {
  it('only Breadcrumbs.tsx emits the .crumb line', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(path.join(WEB, 'src'))) {
      const rel = path.relative(WEB, file);
      if (rel === OWNER) continue;
      /* Comments are blanked, not skipped by line. This file's own explanation of the defect
         quotes the deleted JSX, and the first run of this test flagged that comment -- which is
         the scan working, and the reason the stripping happens before the match rather than as a
         per-line heuristic. Line numbers survive because each stripped line keeps its newline. */
      const code = fs
        .readFileSync(file, 'utf8')
        .replace(/\/\*[^]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
        .replace(/(^|[^:])\/\/.*$/gm, (m, lead) => lead + ' '.repeat(m.length - lead.length));
      code.split('\n').forEach((line, i) => {
        if (EMITS_CRUMB.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it('the scan can actually fail', () => {
    expect(EMITS_CRUMB.test('        <p className="crumb">')).toBe(true);
    expect(EMITS_CRUMB.test('    <nav className={cx("crumb", extra)}>')).toBe(true);
    expect(EMITS_CRUMB.test('        <p className="lede">')).toBe(false);
    expect(EMITS_CRUMB.test('  /* the drawing calls this the crumb */')).toBe(false);
  });
});
