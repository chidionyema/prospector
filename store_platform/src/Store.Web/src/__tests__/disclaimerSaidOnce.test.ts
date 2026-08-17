import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { PACK_DISCLAIMER } from '@/lib/disclaimer';

const SRC = fileURLToPath(new URL('..', import.meta.url));

/**
 * The limit on what is being sold is written in ONE place.
 *
 * Before `lib/disclaimer.ts` this sentence existed four times in three wordings -- "not a
 * guarantee", "not a promise of business success", "not a promise of outcome" -- two of them
 * sitting directly above a buy button. Three wordings is three different limits, and a reader
 * holds us to the weakest one. The failure mode is not that someone writes it badly; it is that
 * someone amends three of the four and never learns about the fourth.
 */
function sourceFiles(): string[] {
  // A filesystem walk, NOT `git ls-files`. The first version shelled out to git and passed when
  // run by hand, then failed inside the POPDD gate with ENOENT on `//pi-governance/src/index.ts`:
  // the gate runs the suite against the STAGED tree, where a cwd-relative pathspec resolves to
  // files outside Store.Web entirely. A guard that only holds in the tree you happen to be
  // standing in is not a guard.
  const out: string[] = [];
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(join(dir, entry.name), rel);
      else if (/\.tsx?$/.test(entry.name) && !rel.includes('__tests__') && !rel.includes('.test.'))
        out.push(rel);
    }
  };
  walk(SRC, '');
  return out;
}

/**
 * A comment may quote the sentence -- `pack/[id].tsx` counts its own negative phrasings in a
 * docblock and names this one. A RENDERED string may not. The discriminator is the line's first
 * character, which is the whole difference between documenting the rule and breaking it.
 */
function rendersLiteral(body: string, needle: string): boolean {
  return body.split('\n').some((line) => {
    const text = line.trim();
    return text.includes(needle) && !text.startsWith('*') && !text.startsWith('//');
  });
}

describe('the honesty note', () => {
  it('is typed out in exactly one file', () => {
    // Matched on the distinctive tail rather than the whole sentence, so a surface that re-types
    // it with different leading words ("Remember, a pack is evidence-backed research, not a
    // promise of business success") is still caught.
    const TAIL = 'not a promise of business success';
    const authors = sourceFiles().filter((f) => rendersLiteral(readFileSync(`${SRC}/${f}`, 'utf8'), TAIL));
    expect(authors, 'import PACK_DISCLAIMER from @/lib/disclaimer instead of re-typing it')
      .toEqual(['lib/disclaimer.ts']);
  });

  it('still denies the thing a buyer would otherwise assume', () => {
    // A constant can be edited into meaninglessness as easily as it can be shared. This pins the
    // two words that do the work: what it is (research), and what it is not (a promise).
    expect(PACK_DISCLAIMER).toMatch(/research/i);
    expect(PACK_DISCLAIMER).toMatch(/not a promise/i);
  });

  it('has no near-miss wordings left behind on any surface', () => {
    const STALE = [/not a guarantee\b/i, /not a promise of outcome\b/i];
    const found: string[] = [];
    for (const file of sourceFiles()) {
      const body = readFileSync(`${SRC}/${file}`, 'utf8');
      for (const pattern of STALE) {
        const hit = body.match(pattern);
        // A comment explaining the consolidation is allowed to quote the old wording; a rendered
        // string is not. The cheap discriminator is whether the line is a comment.
        if (hit) {
          const line = body.slice(0, hit.index).split('\n').length;
          const text = body.split('\n')[line - 1].trim();
          if (!text.startsWith('*') && !text.startsWith('//')) found.push(`${file}:${line} ${text}`);
        }
      }
    }
    expect(found).toEqual([]);
  });
});
