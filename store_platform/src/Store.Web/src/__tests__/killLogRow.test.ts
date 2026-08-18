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

  it('never cuts at all when there is no sentence to cut on', () => {
    // WAS "never cuts mid-word", and it cut on a word with a trailing ellipsis. The character
    // budget is gone (2026-08-18, D3a), so a reason with no sentence end in it comes back whole.
    // The ellipsis is what the founder reported as a live defect, and 364 of the 400 rows in
    // `src/data/kill-log.json` took that branch, so it is not an edge case being tidied away.
    const long = `${'evidence '.repeat(40)}end`;
    expect(excerptOf(long)).toBe(long.replace(/\s+/g, ' ').trim());
    expect(excerptOf(long)).not.toContain('…');
  });

  it('cuts on a sentence end wherever it falls, not inside a window', () => {
    // The old rule looked for a sentence end in the first 150 characters and gave up past that.
    // A median kill argument's first sentence is 270 characters long, so the old rule gave up on
    // most of them.
    const text = `${'a'.repeat(260)} runs out here. And a second sentence follows.`;
    const cut = excerptOf(text);
    expect(cut.endsWith('here.')).toBe(true);
    expect(cut).not.toContain('…');
  });

  it('leaves no ellipsis anywhere in the shipped log', () => {
    // The check that speaks directly to the defect: not "the function can avoid an ellipsis" but
    // "no row on the live page has one".
    // AT THE END, and only at the end. Nine of the 400 reasons quote a passage that contains its
    // own ellipsis ("no breed-based pricing... a calendar event doesn't know"). That is the
    // source's punctuation inside a quotation, not our cut, and banning it everywhere would ban
    // quoting evidence accurately -- on the page whose whole claim is that we quote accurately.
    const marked = index.summaries.filter((s) => /(…|\.\.\.)$/.test(s.excerpt)).map((s) => s.slug);
    expect(marked, 'a kill-log row still ships a truncation mark').toEqual([]);
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
      // No `.replace('…', '')` any more: the excerpt carries no truncation mark to strip, and
      // stripping one would corrupt the nine excerpts that quote an ellipsis of their own.
      .filter((s) => !details[s.slug].reason.replace(/\s+/g, ' ').trim().startsWith(s.excerpt))
      .map((s) => s.slug)
      .slice(0, 3);
    expect(wrong).toEqual([]);
  });

  it('stays inside one sentence, which is the width it is cut to now', () => {
    // The per-row ratchet, which is the one that matters: the payload ceiling in
    // killLogPayload.test.ts is a total, and a total hides one row that grew by 4,000 characters.
    //
    // The number moved from 170 to 700 on 2026-08-18 with the character budget (D3a). It is no
    // longer the width the row is cut TO -- the row is cut to a sentence -- it is a backstop
    // against a reason whose first sentence is a runaway. Measured over the 400 entries the day
    // it changed: 39 / 270 / 402 / 511 characters (min / median / p90 / max).
    const over = index.summaries.filter((s) => s.excerpt.length > 700).map((s) => s.slug);
    expect(over).toEqual([]);

    // And the rule the length backstop cannot state: every row ends on a sentence, or is the
    // whole reason. Neither ends mid-word, which is what the founder reported.
    const details = buildKillDetails();
    const midThought = index.summaries
      .filter((s) => {
        const full = details[s.slug].reason.replace(/\s+/g, ' ').trim();
        return s.excerpt !== full && !/[.!?]$/.test(s.excerpt);
      })
      .map((s) => s.slug)
      .slice(0, 3);
    expect(midThought, 'a row is cut somewhere other than the end of a sentence').toEqual([]);
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
