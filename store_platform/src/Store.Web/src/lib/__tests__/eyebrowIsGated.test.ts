import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

/**
 * EVERY SECTOR RENDER SITE IS GATED ON `tagged`, proved over the whole source tree.
 *
 * `lib/category.ts` states the rule: an untagged pack renders NOTHING -- no label, no marker --
 * because "Not yet tagged" is a status message about our own pipeline, and a buyer reads it as an
 * unfinished listing. `categoryScale.test.ts` asserts that rule on the shared `PackCardHeader`
 * path, which is one render site out of several, so a NEW site could ignore `tagged` and no test
 * would notice.
 *
 * One did. `PackRow.tsx`'s three-up tile (`.htile`, the "Newest survivors" row) shipped
 * `<span className="eyebrow">{cat.label}</span>` with no guard, and mumchimp.com printed
 * "Not yet tagged" on the first card above the fold. Confirmed on the live HTML 2026-08-30:
 *
 *   $ curl -s https://mumchimp.com/ | grep -c "Not yet tagged"
 *   1
 *
 * This test closes the class rather than that one instance: it reads the source and fails on any
 * JSX that puts a category label inside an eyebrow without `tagged` on the same line. A new tile
 * added next month cannot reintroduce the defect without turning this red.
 */

const SRC = join(__dirname, '..', '..');

function tsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '__tests__') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...tsxFiles(full));
    else if (name.endsWith('.tsx')) out.push(full);
  }
  return out;
}

/** A JSX line that renders a category label inside the eyebrow span. */
const RENDERS_SECTOR = /className="eyebrow"[^]*?\{\s*cat\.label/;
/** The guard, on the same line: `cat.tagged && <span className="eyebrow">…`. */
const IS_GATED = /cat\.tagged\s*(\?|&&)/;

describe('no ungated sector eyebrow anywhere in the source', () => {
  it('every line that renders cat.label in an eyebrow also tests cat.tagged', () => {
    const offenders: string[] = [];
    for (const file of tsxFiles(SRC)) {
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (RENDERS_SECTOR.test(line) && !IS_GATED.test(line)) {
          offenders.push(`${file.replace(SRC, 'src')}:${i + 1}  ${line.trim()}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });

  it('the test can actually fail — an ungated line is detected', () => {
    const ungated = '        <span className="eyebrow">{cat.label}</span>';
    expect(RENDERS_SECTOR.test(ungated)).toBe(true);
    expect(IS_GATED.test(ungated)).toBe(false);

    const gated = '        {cat.tagged && <span className="eyebrow">{cat.label.toUpperCase()}</span>}';
    expect(RENDERS_SECTOR.test(gated)).toBe(true);
    expect(IS_GATED.test(gated)).toBe(true);
  });
});
