import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { buildKillDetails, buildKillIndex, excerptOf } from '@/lib/killLog.server';

/**
 * THE ARGUMENT IS THE ROW (MASTER-BRIEF §7 `/kill-log`).
 *
 * The brief's finding: "the live page hides the reasoning until a row is selected, in a 400-row
 * table that is unusable on a phone". A row that carries only a title and a cause label is an
 * ASSERTION -- the reader is told an idea failed on incumbency and is shown no evidence that any
 * work was done, so the only way to find out whether the page is real is to open a row and hope.
 * Two lines of the actual finding on every row turns the table into something a reader can scan.
 *
 * These tests hold three things: the excerpt is really in the props (not fetched), it is really
 * the argument (not a restated title), and it is CUT CAREFULLY -- on this page above all, a
 * sentence chopped mid-word makes the evidence look as carelessly handled as the sentence.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const PAGE = readFileSync(`${SRC}/pages/kill-log.tsx`, 'utf8');
const index = buildKillIndex();

describe('excerptOf cuts an argument to a row', () => {
  it('returns a short reason whole, with no ellipsis', () => {
    // An ellipsis on a complete sentence promises more behind the row than is there. A reader who
    // opens it and finds the same words learns the other rows are not worth opening either.
    expect(excerptOf('The incumbent bundles this free.')).toBe('The incumbent bundles this free.');
    expect(excerptOf('The incumbent bundles this free.')).not.toContain('…');
  });

  it('never cuts mid-word', () => {
    const long = `${'evidence '.repeat(40)}end`;
    const cut = excerptOf(long);
    expect(cut.endsWith('…')).toBe(true);
    expect(cut.replace('…', '').endsWith(' ')).toBe(false);
    // Everything before the ellipsis is whole words of the original.
    expect(long.startsWith(cut.replace('…', ''))).toBe(true);
  });

  it('prefers a sentence boundary when there is one in range', () => {
    const text = `${'a'.repeat(70)} runs out here. And then a second sentence continues well past the limit for a while.`;
    const cut = excerptOf(text);
    expect(cut.endsWith('here.')).toBe(true);
    expect(cut).not.toContain('…');
  });

  it('does not mistake a decimal or an abbreviation for a sentence end', () => {
    // "Composite 3.2 below threshold" is the engine's own phrasing, and a naive `.` search cuts it
    // to "Composite 3." -- a number turned into a different, wrong number.
    const text = `Composite 3.2 fell below the threshold of 4.0 for this candidate, ${'x'.repeat(200)}`;
    const cut = excerptOf(text);
    expect(cut).not.toMatch(/\d\.$/);
    expect(cut).toContain('3.2');
  });

  it('collapses whitespace, because a row is one line of flow', () => {
    expect(excerptOf('  two\n\nlines  here ')).toBe('two lines here');
  });
});

describe('every row carries its own argument', () => {
  it('puts an excerpt on every kill', () => {
    const empty = index.summaries.filter((s) => !s.excerpt.trim()).map((s) => s.slug);
    expect(empty).toEqual([]);
  });

  it('is the start of the real reason, not a restated title', () => {
    // The failure this catches is an excerpt built from the wrong field. It would look right in a
    // screenshot and would tell the reader nothing they did not already have in the row above it.
    const details = buildKillDetails();
    const wrong = index.summaries
      .filter((s) => !details[s.slug].reason.replace(/\s+/g, ' ').trim().startsWith(s.excerpt.replace('…', '')))
      .map((s) => s.slug)
      .slice(0, 3);
    expect(wrong).toEqual([]);
  });

  it('stays inside the width it was cut for', () => {
    // The per-row ratchet, which is the one that matters: the payload ceiling in
    // killLogPayload.test.ts is a total, and a total hides one row that grew by 4,000 characters.
    const over = index.summaries.filter((s) => s.excerpt.length > 170).map((s) => s.slug);
    expect(over).toEqual([]);
  });

  it('renders in the page HTML, not behind the fetch', () => {
    // The whole point. `detail.reason` still arrives from /api/kill-log-detail; the excerpt must
    // be in the props, or a reader on a phone is back to tapping blind.
    expect(PAGE).toContain('entry.excerpt');
    expect(PAGE).not.toContain('detail.excerpt');
  });

  it('hides the excerpt on the open row, where the full reason repeats it', () => {
    expect(PAGE).toContain('{!isOpen && entry.excerpt');
  });
});

describe('the cause grid is the signature, and the bars are the second form', () => {
  it('renders the grid', () => {
    expect(PAGE).toContain('<CauseGrid distribution={distribution}');
  });

  it('puts the grid above the bars, same data twice, on purpose', () => {
    // §7: "Distribution bars below the grid, same data, second form." The grid carries SCALE --
    // one cell per idea, so the size of the claim is the size of the picture. The bars carry the
    // ranking and the counts, which a grid cannot. Neither replaces the other.
    const grid = PAGE.indexOf('<CauseGrid');
    const bars = PAGE.indexOf('{distribution.map(');
    expect(grid).toBeGreaterThan(-1);
    expect(bars).toBeGreaterThan(-1);
    expect(grid).toBeLessThan(bars);
  });

  it('keeps the cause filter and the sort, which the grid does not replace', () => {
    // The brief keeps both explicitly. A picture of how ideas die does not let a reader pull out
    // the eleven that died on payer solvency and read them.
    expect(PAGE).toContain('setActive(label === active ? null : label)');
    expect(PAGE).toContain('setSort(s.key)');
  });
});
