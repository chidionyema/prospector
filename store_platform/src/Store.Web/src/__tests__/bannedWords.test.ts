import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * TWO WORDS THE SITE MAY NOT PRINT.
 *
 * Both bans are the founder's, both on 2026-08-16, and both are about the reader having to
 * translate before they can judge what they are reading.
 *
 * "RECEIPT" IS A MONEY WORD. On a shop it means the thing you get after paying. The site was
 * using it for "our sources" -- a card headed "The receipts" sat on the pack page, above a list
 * of citations, on the same screen as the buy button. A buyer reads that and looks for an order
 * they have not placed. So the word is allowed only where an actual transaction is the subject:
 * the order pages, the account library, and the purchase email.
 *
 * "INCUMBENT" IS A CONSULTANT'S WORD for "the companies already selling this". It was in the
 * name of a check, in its verdict, in an empty-state, and in a landing page. `lib/plainEnglish.ts`
 * is exempt because it is the table that REMOVES the word from model prose: banning it there
 * would ban the fix.
 *
 * Comments are stripped, deliberately. Every one of these edits leaves a comment naming the word
 * it replaced and why, and that prose is how the next reader knows the ban is real rather than a
 * style whim.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

const SKIP_DIRS = new Set(['__tests__', 'node_modules']);

/* Block comments collapse to their own newlines rather than to nothing, so the line number in a
   failure message is the line number in the file. Deleting them outright shifts every report by
   however long the docblocks above it were, which sends the next reader to the wrong line. */
const stripComments = (src: string) =>
  src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ''))
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

/* `incumbency` is also the ENGINE'S KEY for this check -- an object key, a check `id`, a member
   of a list of ids. Those are not copy, they are the wire name, and renaming them would break the
   join to the engine's own output. Only the word as WORDS is banned, so key and quoted-id forms
   are removed before the line is judged. */
const withoutEngineKeys = (line: string) =>
  line.replace(/(['"`])incumbency\1/g, '').replace(/\bincumbency\s*:/g, '');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(entry)) out.push(path);
  }
  return out;
}

function offendersFor(
  word: RegExp,
  allowed: RegExp[],
  sanitize: (line: string) => string = (l) => l,
): string[] {
  const found: string[] = [];
  for (const path of walk(SRC)) {
    const rel = path.slice(SRC.length);
    if (allowed.some((re) => re.test(rel))) continue;
    stripComments(readFileSync(path, 'utf8'))
      .split('\n')
      .forEach((line, i) => {
        if (word.test(sanitize(line))) found.push(`${rel}:${i + 1}  ${line.trim().slice(0, 110)}`);
      });
  }
  return found;
}

describe('banned words', () => {
  it('says "receipt" only where a real transaction is the subject', () => {
    /* The money surfaces. A receipt for an order the buyer has actually paid for is the correct
       word and the reader expects it there. */
    const COMMERCE = [
      /^pages\/orders\//,
      /^pages\/account\//,
      /^components\/account\//,
      /^lib\/email\/receipt\.ts$/,
      /^lib\/api\/types\.ts$/,
    ];
    const offenders = offendersFor(/receipts?\b/i, COMMERCE);
    expect(
      offenders,
      `"receipt" is a money word; outside checkout and the account it sends the reader looking ` +
        `for an order they have not placed:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('never says "incumbent" or "incumbency" in copy', () => {
    /* plainEnglish.ts is the substitution table that removes the word from model prose. */
    const offenders = offendersFor(/incumben/i, [/^lib\/plainEnglish\.ts$/], withoutEngineKeys);
    expect(
      offenders,
      `"incumbent" is jargon for "the companies already selling this"; say that instead:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('exempts the engine key without exempting the sentence it sits in', () => {
    // The key exemption is the one hole in the ban above, so it gets measured rather than
    // trusted. It must clear the four wire-name forms and clear NOTHING a reader would read.
    expect(withoutEngineKeys(`  id: 'incumbency',`)).not.toMatch(/incumben/i);
    expect(withoutEngineKeys(`  incumbency: 'IN',`)).not.toMatch(/incumben/i);
    expect(withoutEngineKeys(`Whether incumbents already own the space`)).toMatch(/incumben/i);
    expect(withoutEngineKeys(`prose: 'incumbency is the gate',`)).toMatch(/incumben/i);
  });

  it('still translates the engine\'s own word, so the ban cannot be met by leaving it untranslated', () => {
    // Vacuity guard. Both assertions above pass trivially if `plainEnglish.ts` ever stops
    // carrying a rule for the gate word -- the site would then print the engine's raw
    // "incumbency" through a path no source scan can see.
    const table = readFileSync(join(SRC, 'lib', 'plainEnglish.ts'), 'utf8');
    expect(table).toMatch(/\\bincumbency\\b/);
    expect(table).toMatch(/\\bincumbents\\b/);
  });
});
