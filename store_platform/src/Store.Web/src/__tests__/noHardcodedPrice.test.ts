import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * No price is written down anywhere in the storefront.
 *
 * WHAT HAPPENED
 *
 * Every pack was £49, so the number was typed into the copy: the `<title>` suffix, the default
 * meta description, 16 static landing-page descriptions, the footer tagline, the trust row, three
 * hero paragraphs, five blocks on the home page, the FAQ answer, the OG card's fallback, and a
 * `/pricing` page headed "One price, every pack."
 *
 * Then the segment price ladder shipped (`feat(pricing)` #105/#107) and prices stopped being one
 * number. Measured 2026-08-05, `curl -s https://api.mumchimp.com/catalog`:
 *
 *     61 packs -- £29 x5, £49 x48, £79 x5, £99 x1, £149 x1, £199 x1
 *
 * Every one of those strings was then wrong for 13 of 61 packs, and the worst of them
 * (`Seo.tsx`, `lib/seo/landings.ts`) are the surfaces a search engine caches for months, where
 * the buyer is told the number BEFORE they ever see a price tag.
 *
 * THE RULE
 *
 * A price claim is computed from the catalogue (`lib/priceRange.ts`, or the pack's own
 * `pack.price`) or it is not made. This test fails on any `£<number>` literal reaching a render
 * path, which is the mechanical version of that sentence -- the previous guard was a regex
 * looking FOR "£49", and it went on passing against comments after the copy had changed.
 *
 * Comments are stripped, deliberately: every one of these edits left a comment naming the price
 * it removed, and that prose is why the change is legible six months from now.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

const SKIP_DIRS = new Set(['__tests__', 'node_modules']);
/** Fixtures and sample data are documents, not claims about the live shelf. */
const SKIP_FILES = [/\/data\//, /\.test\.tsx?$/];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(entry)) out.push(path);
  }
  return out;
}

/* Trailing `//` comments count too -- `lib/meeting.ts` annotates a cents amount with `// £500`.
   The `[^:]` guard keeps `https://` in a string from being read as the start of a comment. */
const stripComments = (src: string) =>
  src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

describe('no price is hardcoded', () => {
  it('has no £<amount> literal on any render path', () => {
    const offenders: string[] = [];
    for (const path of walk(SRC)) {
      const rel = path.slice(SRC.length);
      if (SKIP_FILES.some((re) => re.test(rel))) continue;
      stripComments(readFileSync(path, 'utf8'))
        .split('\n')
        .forEach((line, i) => {
          if (/£\s?\d/.test(line)) offenders.push(`${rel}:${i + 1}  ${line.trim().slice(0, 100)}`);
        });
    }
    expect(
      offenders,
      `a price must come from the catalogue, never from the source:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('routes every catalogue-wide price claim through priceRange', () => {
    // The guard above only proves no literal. This proves the replacement is the shared, tested
    // derivation rather than sixteen ad-hoc `packs[0].price` reads that would each drift alone.
    const home = readFileSync(join(SRC, 'pages', 'index.tsx'), 'utf8');
    const pricing = readFileSync(join(SRC, 'pages', 'pricing.tsx'), 'utf8');
    const llms = readFileSync(join(SRC, 'pages', 'llms.txt.tsx'), 'utf8');
    for (const [name, src] of [['index', home], ['pricing', pricing], ['llms.txt', llms]] as const) {
      expect(src, `${name} must derive its price claims`).toMatch(/priceRange\(/);
    }
  });
});
