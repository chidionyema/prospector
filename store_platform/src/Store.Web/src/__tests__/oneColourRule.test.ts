import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * One colour rule: vermillion means "you can act on this", and nothing else.
 *
 * THE DEFECT
 *
 * `--primary` (#FF5A1F) is declared in globals.css as "the visual signal that Mumchimp is not a
 * blue SaaS brand". It was doing that job and about six others. Counted across `src/**\/*.tsx` at
 * commit c4bc460, before this pass: 165 accent utilities in 36 files, of which it was
 * simultaneously carrying every section eyebrow, the verified tick, decorative icon tiles, the category pill,
 * the score bars, the numbered step badges, the search-match highlight, the source chips, a
 * 16:9 placeholder panel on the order-success page, AND every button and link.
 *
 * The consequence is not that it looked busy. It is that the colour stopped carrying
 * information: on the pack page a visitor saw the same orange on the buy button, on a label that
 * does nothing, on a bar that does nothing, and on a tick that means "verified". A colour used
 * for seven meanings has one meaning, which is decoration.
 *
 * THE RULE
 *
 * Vermillion is allowed on: a button, a link, a focus ring, a checked/active/selected state, a
 * hover affordance on something clickable, and the logo mark. Everything else uses ink
 * (`text`/`muted`/`surface2`) or its own semantic token (`success` for verified, `warning` for
 * a failing score).
 *
 * WHY THIS TEST IS SHAPED THE WAY IT IS
 *
 * "Is this element actionable?" is not decidable by grep, so the test does not try. It pins the
 * two things that ARE decidable and that regressed in practice:
 *
 *   1. the specific decorative SIGNATURES that were wrong (an eyebrow, a verified tick), which
 *      are recognisable from the utility classes sitting beside the colour; and
 *   2. a total budget, so a broad reintroduction fails loudly even in a shape not listed below.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

function tsxFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) tsxFiles(path, out);
    else if (entry.endsWith('.tsx')) out.push(path);
  }
  return out;
}

const FILES = tsxFiles(SRC).map((path) => ({
  path: path.slice(SRC.length),
  src: readFileSync(path, 'utf8'),
}));

/** Any utility that paints with the accent. `on-primary`/`primary-hover` are its companions. */
const ACCENT =
  /\b(?:text|bg|border|fill|stroke|from|to|via|ring|decoration|shadow)-(?:primary|accent)(?:\/\[?[\d.]+\]?)?\b/g;

describe('the one colour rule', () => {
  it('finds the accent at all, so a rename cannot make this suite vacuous', () => {
    const total = FILES.reduce((n, f) => n + (f.src.match(ACCENT)?.length ?? 0), 0);
    expect(total, 'zero matches means the token was renamed and these tests stopped testing').toBeGreaterThan(20);
  });

  it('no section eyebrow wears the action colour', () => {
    // The eyebrow signature: small uppercase tracked-out label text. There were 12.
    const offenders: string[] = [];
    for (const { path, src } of FILES) {
      src.split('\n').forEach((line, i) => {
        // `href`/`hover:` excludes the real links that happen to be set as uppercase tracked
        // labels -- LegalDoc's "back to home" is one, and it is allowed to be the action colour
        // precisely because it IS an action.
        const isLink = /href|hover:|<Link|role="button"/.test(line);
        if (
          !isLink &&
          /tracking-wide(?:st)?/.test(line) &&
          /uppercase/.test(line) &&
          /\btext-(?:primary|accent)\b/.test(line)
        ) {
          offenders.push(`${path}:${i + 1}  ${line.trim().slice(0, 100)}`);
        }
      });
    }
    expect(offenders, `an eyebrow is a label, not a control:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('the verified mark keeps its own semantic colour', () => {
    // "verified" and "buy" rendering in the same colour is the collision that made the tick
    // read as an advert rather than as a result.
    const offenders: string[] = [];
    for (const { path, src } of FILES) {
      src.split('\n').forEach((line, i) => {
        if (/name="verified"/.test(line) && /\btext-(?:primary|accent)\b/.test(line)) {
          offenders.push(`${path}:${i + 1}`);
        }
      });
    }
    expect(offenders, `verified is --success, not --primary:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('stays inside its budget', () => {
    /*
     * 165 before this pass, 119 after. The budget is deliberately just above the current count
     * rather than at it: a genuinely new BUTTON should not have to edit this file, but adding
     * ten of anything should have to justify itself.
     *
     * Recount after an intentional change with:
     *   grep -rEn "(text|bg|border|...)-(primary|accent)" src --include="*.tsx" | grep -vc __tests__
     */
    const total = FILES.reduce((n, f) => n + (f.src.match(ACCENT)?.length ?? 0), 0);
    expect(total, `accent usages: ${total}`).toBeLessThanOrEqual(128);
  });
});
