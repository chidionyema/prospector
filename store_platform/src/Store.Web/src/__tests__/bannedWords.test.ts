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
    /* lib/gateLabels.ts is the SECOND hole, opened 2026-08-18 by the founder's live-defect fix
       prompt (D7), which writes the six kill-cause labels out in full and names this one
       "Incumbents already own the space". The prompt's governing rule is that the copy is given,
       never composed here: "If you find yourself composing a sentence, you have already made a
       mistake." So the word is allowed in exactly one file, the one that holds the given
       sentences, and nowhere a sentence gets written. The ban still covers every other file,
       including the components that render these labels. */
    const offenders = offendersFor(
      /incumben/i,
      [/^lib\/plainEnglish\.ts$/, /^lib\/gateLabels\.ts$/],
      withoutEngineKeys,
    );
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

/**
 * THE PLAIN ENGLISH SWEEP, AS A TEST (founder spec, 2026-08-18).
 *
 * The rule the founder set: "Site chrome and marketing copy: only words a reader would use with a
 * friend in a pub." The test is never "is this the correct term", it is "does the person this page
 * is for already say this word?"
 *
 * Step 4 of the sweep as specified is this file: "re-run the grep as a CI check, a banned word
 * fails the build". A sweep done once by hand comes back. The words came back into a paragraph a
 * fortnight after they were taken out of it, because nothing was watching.
 *
 * THREE KINDS OF ENTRY, AND THE DIFFERENCE MATTERS.
 *  - `say` is the replacement the founder wrote. It is printed in the failure message so the next
 *    person does not have to find this table's source to know what to write instead.
 *  - `allow` exempts a FILE. Used only where the word is not copy: a statutory phrase, an icon
 *    name, a browser API.
 *  - `sanitize` exempts a FORM of the word on any line: a URL path, a wire key, an analytics
 *    source. Those are names the code joins on, not sentences a buyer reads.
 *
 * WHAT IS NOT HERE. The founder's grammar bans (no sentence starting with "Not", one em dash per
 * paragraph, no Title Case headings, no exclamation marks) are not greppable without a sentence
 * parser, and a bad grep on those would fire on aria-labels and regexes. They are stated in
 * docs/SITE_SPEC_PROGRAM.md and reviewed by eye. The em-dash ban has its own file already
 * (`dashFree.test.ts`).
 */

/** URL paths, wire keys and analytics sources are names the code joins on, never copy. */
const withoutNames = (line: string) =>
  line
    .replace(/\/ideas\b/g, '')
    .replace(/business-ideas-for-operators|marketplace-and-broker-ideas|productised-service-ideas|vertical-software-ideas/g, '')
    .replace(/shelf-end/g, '');

type Ban = { word: RegExp; say: string; allow?: RegExp[] };

/* Words the founder introduced and then banned: "my fault, ban them". */
const OURS: Ban[] = [
  { word: /\bshelf\b/i, say: 'available now, for sale, or in the catalogue' },
  { word: /\bcollections?\b/i, say: 'types, what it suits, or just name it' },
  { word: /\bartefacts?\b|\bartifacts?\b/i, say: 'file, document', allow: [/^lib\/plainEnglish\.ts$/] },
];

/* Words that were already live on the site when the founder read it. */
const LIVE: Ban[] = [
  { word: /\bbeachhead\b/i, say: 'the first group to sell to' },
  { word: /non-goals?\b/i, say: 'what to leave out at first' },
  { word: /on what stack\b/i, say: 'what to build it with' },
  { word: /machine-readable/i, say: 'a version other software can read', allow: [/^pages\/privacy\.tsx$/] },
  { word: /claim-checked/i, say: 'checked against the sources' },
  { word: /drip[- ]feed/i, say: 'you get everything at once' },
  { word: /\bdossiers?\b/i, say: 'pack, file' },
  { word: /\bGTM\b/, say: 'how you get your first customers' },
  { word: /unit economics/i, say: 'the numbers' },
  { word: /LTV\s*[:/]?\s*CAC/, say: 'you earn back N times what a customer costs to win' },
  { word: /adversarial pass/i, say: 'a second round of checks' },
  { word: /productised service/i, say: 'fixed-price service' },
  { word: /vertical software/i, say: 'software for one trade' },
  { word: /\bmarketplace\b|\bbrokers?\b/i, say: 'connecting two sides of a deal', allow: [/^components\/marketing\/BespokeIcon\.tsx$/] },
  { word: /\boperators\b/i, say: 'people who run things well', allow: [/^components\/marketing\/BespokeIcon\.tsx$/] },
  { word: /micro-hedge/i, say: 'small cover that pays out if prices jump' },
  { word: /parametric bond/i, say: 'pays out automatically when it happens' },
  { word: /documentary research/i, say: 'desk research', allow: [/^lib\/sources\.ts$/] },
  { word: /cold[- ]start/i, say: 'getting the first people on both sides' },
];

/* Generic startup fog. Banned outright, no replacement offered, because the sentence that needed
   one of these usually did not need saying. */
const FOG: Ban[] = [
  { word: /\bleverage[ds]?\b/i, say: 'use' },
  { word: /\bseamless(ly)?\b/i, say: 'nothing' },
  { word: /\brobust\b/i, say: 'nothing' },
  { word: /\bsolutions?\b/i, say: 'name the thing' },
  { word: /\bplatforms?\b/i, say: 'the site, or name the thing', allow: [/^components\/discovery\/CommandPalette\.tsx$/] },
  { word: /\bonboarding\b/i, say: 'getting started' },
  { word: /\butilis[ez]/i, say: 'use' },
  { word: /\bempower(s|ed|ing)?\b/i, say: 'lets you' },
  { word: /\bunlocks?\b/i, say: 'nothing' },
  { word: /\bsupercharge/i, say: 'nothing' },
  { word: /game[- ]changing/i, say: 'nothing' },
  { word: /best[- ]in[- ]class/i, say: 'nothing' },
  { word: /frictionless/i, say: 'nothing' },
  { word: /\bscalable\b/i, say: 'nothing' },
  { word: /\bbespoke\b/i, say: 'made to order' },
  { word: /\bcurated\b/i, say: 'chosen' },
  { word: /\bjourney\b/i, say: 'name the steps' },
  { word: /\becosystems?\b/i, say: 'name the thing' },
  { word: /\blearnings\b/i, say: 'what we learned' },
  { word: /\bdeliverables?\b/i, say: 'what you get' },
  { word: /\btouchpoints?\b/i, say: 'name the step' },
  { word: /\bat scale\b/i, say: 'nothing' },
  { word: /deep dive/i, say: 'nothing' },
  { word: /circle back/i, say: 'nothing' },
];

describe.each([
  ['words we introduced', OURS],
  ['words already live on the site', LIVE],
  ['generic startup fog', FOG],
])('plain English: %s', (_group, bans) => {
  it.each(bans.map((b) => [b.word.source, b] as const))('never prints %s', (_src, ban) => {
    const offenders = offendersFor(ban.word, ban.allow ?? [], withoutNames);
    expect(
      offenders,
      `banned by the founder's plain English sweep, 2026-08-18. Say instead: ${ban.say}.\n` +
        offenders.join('\n'),
    ).toEqual([]);
  });
});

describe('the sweep cannot pass vacuously', () => {
  it('scans a real tree', () => {
    expect(walk(SRC).length).toBeGreaterThan(100);
  });

  it('exempts names without exempting sentences', () => {
    expect(withoutNames(`<Link href="/ideas">`)).not.toMatch(/collection/i);
    expect(withoutNames(`source="homepage-shelf-end"`)).not.toMatch(/\bshelf\b/i);
    expect(withoutNames(`The shape of the collection`)).toMatch(/collection/i);
    expect(withoutNames(`packs on the shelf`)).toMatch(/\bshelf\b/i);
  });
});
