import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { COMMON_CHECKS } from '../checks';

/**
 * The pack page's "How we tried to kill it" block is STATIC, it is the same six lines on
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

/**
 * The lines the block renders.
 *
 * These used to be a literal array in `pages/pack/[id].tsx` and this guard read it out of the
 * source. They now come from `COMMON_CHECKS` in `lib/checks.ts`, the site-wide vocabulary, so the
 * guard reads the values themselves. That is strictly tighter than the string-matching it
 * replaces: it tests what renders rather than how the file happens to be written, and it now also
 * covers /about and /how-it-works, which render the same objects.
 */
function checkLines(): string[] {
  return COMMON_CHECKS.map((check) => check.refutation);
}

/** The block that renders CHECKS, isolated the same way. */
function checksList(): string {
  const start = PAGE.indexOf('{CHECKS.map(');
  expect(start, 'CHECKS render site not found').toBeGreaterThan(-1);
  // A <div>, not a <ul>: the drawing runs these as `.checkrow` rows inside one `.card incard`
  // (`mockups/pack-detail.html`). The slice is the same span it always was, from the container
  // to the end of the map. Bounding it at `</ul>` after the markup changed made this read the
  // buy rail's own list instead, which legitimately carries a success mark.
  return PAGE.slice(
    PAGE.lastIndexOf('<div className="card incard', start),
    PAGE.indexOf('))}', start),
  );
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
    const rendered = checkLines().join(' | ');
    for (const claim of verdictClaims) {
      expect(
        rendered,
        `"${claim}" asserts a per-pack finding this page has no verdict data for`,
      ).not.toContain(claim);
    }
  });

  it('has exactly six lines, none of them a two-clause assertion', () => {
    const lines = checkLines();
    expect(lines).toHaveLength(6);
    for (const line of lines) {
      // A full stop mid-string is how the "attack. Result." shape returns.
      expect(line, `${line} reads as attack-then-verdict`).not.toMatch(/\.\s+\S/);
    }
  });

  it('still renders those lines from the shared vocabulary, not a local copy', () => {
    // The defect this whole file guards against comes back the moment the page re-declares its
    // own array, because the guard above would then be testing a list nothing renders.
    expect(PAGE, 'the pack page must map the shared checks').toContain(
      'COMMON_CHECKS.map((check) => check.refutation)',
    );
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
    expect(list).toContain("String(i + 1).padStart(2, '0')");
  });

  it('says out loud that finding nothing is not a green light', () => {
    // The block's own prose is what carries the honest reading now that the lines are neutral.
    const heading = PAGE.slice(PAGE.indexOf('How we tried to kill it'));
    expect(heading.slice(0, 900)).toContain('not the same as finding a green light');
  });
});
