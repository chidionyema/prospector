import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The pack page's "Six ways we tried to kill it" block is STATIC — it is the same six lines on
 * every pack, because `PackDetails` (lib/api/client.ts) carries no per-check verdicts. A static
 * list may therefore only state what is true of every listed pack.
 *
 * It once did not. Six lines each asserted a positive per-pack finding beside a green success
 * tick ("We tried to show the value would not last. **It held.**"), and measurement over the
 * dossiers said that was unsupportable twice over:
 *
 *   - silence is the common case, not the exception. Of 111 passing dossiers, `incumbency` has
 *     no positive finding for 71 (59 `unverifiable` + 12 never run) and `legality` for 52;
 *   - and the smb and side_hustle lanes never run `value_durability` or `incumbency` at all
 *     (per-lane `hard_gates` / `score_checks`, config.yaml), so even "we tried" was false there.
 *
 * These tests pin the fix at the two places it can rot back: the claim in the strings, and the
 * green tick that makes a static line read as a verdict. Source-reading, like the other web tests
 * in this directory (no jsdom/RTL is configured in this repo).
 */
const PAGE = readFileSync(
  join(__dirname, '..', '..', 'pages', 'pack', '[id].tsx'),
  'utf8',
);

/** The CHECKS array literal, isolated so a match elsewhere on the page cannot mask a regression. */
function checksArray(): string {
  const start = PAGE.indexOf('const CHECKS = [');
  expect(start, 'CHECKS array not found — rename it and update this guard').toBeGreaterThan(-1);
  const end = PAGE.indexOf('];', start);
  return PAGE.slice(start, end);
}

/** The <ul> that renders CHECKS, isolated the same way. */
function checksList(): string {
  const start = PAGE.indexOf('{CHECKS.map(');
  expect(start, 'CHECKS render site not found').toBeGreaterThan(-1);
  return PAGE.slice(PAGE.lastIndexOf('<ul', start), PAGE.indexOf('</ul>', start));
}

describe('the six-checks block claims no per-pack finding', () => {
  it('names the front attacked, never the result of attacking it', () => {
    // The exact second clauses that shipped, plus the shapes they would come back as.
    const verdictClaims = [
      'It was real',
      'It held',
      'There was room',
      'A payer was there',
      'A route existed',
      'came back clean',
    ];
    for (const claim of verdictClaims) {
      expect(
        checksArray(),
        `"${claim}" asserts a per-pack finding this page has no verdict data for`,
      ).not.toContain(claim);
    }
  });

  it('has exactly six lines, none of them a two-clause assertion', () => {
    const lines = checksArray().match(/'[^']+'/g) ?? [];
    expect(lines).toHaveLength(6);
    for (const line of lines) {
      // A full stop mid-string is how the "attack. Result." shape returns.
      expect(line.replace(/'/g, ''), `${line} reads as attack-then-verdict`).not.toMatch(/\.\s+\S/);
    }
  });

  it('marks each line with a neutral numeral, not a success tick', () => {
    const list = checksList();
    // A success-coloured marker on a static line is the visual half of the same false claim: it
    // reads as this pack's verdict on that check. Matched as class tokens rather than as the bare
    // word, so prose about the rule does not trip the rule.
    expect(list, 'a success-coloured marker reads as a per-pack verdict').not.toMatch(
      /\b(bg|text|border|ring)-success\b/,
    );
    expect(list).not.toContain('Icon name="check"');
    expect(list).toContain('{i + 1}');
  });

  it('says out loud that finding nothing is not a green light', () => {
    // The block's own prose is what carries the honest reading now that the lines are neutral.
    const heading = PAGE.slice(PAGE.indexOf('Six ways we tried to kill it'));
    expect(heading.slice(0, 900)).toContain('not the same as finding a green light');
  });
});
