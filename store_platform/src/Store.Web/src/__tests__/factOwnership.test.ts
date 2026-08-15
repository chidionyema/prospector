import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Say it once, sitewide -- and at least once.
 *
 * `docs/SITE_SPEC_PROGRAM.md` §5.3 assigns every load-bearing fact an owning page. Until now that
 * map lived only in prose, and prose cannot fail. On 2026-08-07 it cost us the fact itself:
 *
 *   Home rendered the pack manifest TWICE. Two agents ran concurrently against `index.tsx`, each
 *   told to "remove the duplicated pack-contents section". Each deleted a different one. Both
 *   reported success. `npx tsc --noEmit` returned 0, because deleting a section is type-correct.
 *   The manifest ended up on NO page at all, and nothing in the tree noticed.
 *
 * The lesson usually drawn -- "never run two agents against one file" -- is a rule about process,
 * and process rules are not falsifiable. This is the falsifier. It asserts the thing that was
 * actually broken: each owned fact renders on EXACTLY one page. Not at-most-one, which is the
 * assertion a de-duplication pass invites you to write and which would have passed at zero. The
 * `>= 1` half is the half that was missing, and it is the half that caught nothing that day.
 *
 * It is deliberately anchored on STRUCTURAL markers -- the component or the DOM id that renders
 * the canonical form -- not on copy. Copy is rewritten every session (§6 is a copy programme), so
 * a prose grep would fail on every legitimate edit and be deleted within a week. A component name
 * survives rewording, which is exactly the property a long-lived guard needs.
 *
 * Scope note: a bare COUNT is not the fact. `PACK_DOCUMENTS.length` renders in nine files on
 * purpose -- the document count is a number any page may cite, and §1 requires it be read from one
 * source rather than typed. What is owned is the enumerated MANIFEST, and that is what
 * `<PackContentsSection` matches.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

/** Every `.tsx` under `src/pages`, as `{ path, src }` with `path` relative to `src/`. */
function pageFiles(dir: string = join(SRC, 'pages'), out: { path: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) pageFiles(full, out);
    else if (entry.endsWith('.tsx')) {
      out.push({ path: full.slice(SRC.length).replace(/\\/g, '/'), src: readFileSync(full, 'utf8') });
    }
  }
  return out;
}

/**
 * The same source with comments blanked out, newlines preserved so line numbers still line up.
 *
 * Every one of these files explains, in prose, which section it gave up and to whom -- `index.tsx`
 * alone names `PackContentsSection` in three separate docblocks arguing about where it belongs. A
 * raw match would count those as renderings, report the manifest on four pages, and teach the next
 * author that the fix is to delete the explanation. Same reasoning as `readStripped` in
 * `storefrontDesignContract.test.ts`.
 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/^\s*\/\/.*$/gm, '');
}

interface OwnedFact {
  /** §5.3 row this pins. */
  fact: string;
  /** The structural signature of the canonical rendering. */
  marker: RegExp;
  /** The single page that owns it, relative to `src/`. */
  owner: string;
  /** Pages that may legitimately render it too, each with the reason it is not a duplicate. */
  alsoAllowed?: { path: string; because: string }[];
}

const OWNED_FACTS: OwnedFact[] = [
  {
    fact: "What's in a pack (the 8-document manifest)",
    marker: /<PackContentsSection/,
    owner: 'pages/index.tsx',
    alsoAllowed: [
      {
        path: 'pages/pack/[id].tsx',
        because:
          'a pack page lists its OWN contents -- that is the product, not a restatement of the ' +
          'marketing claim. §5.3 names Home the owner of the marketing manifest specifically.',
      },
    ],
  },
  {
    fact: 'Pricing logic (the rung ladder)',
    marker: /<PriceLadder/,
    owner: 'pages/pricing.tsx',
  },
  {
    fact: 'Kill-cause taxonomy (the "How ideas die" distribution)',
    marker: /id="distribution-heading"/,
    owner: 'pages/kill-log.tsx',
  },
  {
    fact: 'Honest limits ("What you do not get")',
    // The ANCHOR, not a link to it. `how-it-works.tsx` links to
    // `/pricing#what-you-do-not-get` and must keep doing so -- §6.2 replaced its own copy of this
    // section with exactly that link. `id="..."` matches the section; the href does not.
    marker: /id="what-you-do-not-get"/,
    owner: 'pages/pricing.tsx',
  },
  {
    // Added when `FOUNDER.bio` was deleted. The story was told in two places -- `pages/about.tsx`
    // in full, and a five-sentence config string that `FounderNote` rendered whole on /about and
    // `line-clamp-2`'d on the home page. The homepage comment recording the fix
    // (`pages/index.tsx:1785`, "the founder's paragraph now lives once, on /about") was prose, and
    // prose cannot fail; the config string survived it by eight months of edits. This can fail.
    fact: 'The founder story (why this shop exists)',
    marker: /id="founder-story"/,
    owner: 'pages/about.tsx',
  },
  {
    // §5.3's last row reads "Email-capture promise | The capture block itself, once | Was stated
    // 4x WITHIN the block". The within-block repetition was fixed as copy; what this pins is the
    // structural half -- one block, on one page. A second capture on another page is how the
    // promise starts drifting into two wordings again.
    fact: 'Email-capture promise (the capture block)',
    marker: /<ShelfEndCapture/,
    owner: 'pages/index.tsx',
  },
];

/**
 * The violations for one fact across a set of pages. Extracted from the assertions so the guard
 * can be run against SYNTHETIC pages below and proven to fire.
 *
 * A guard whose failure path has never executed is a guard you are trusting on its shape. This
 * whole file exists because a green suite missed a real defect, so it does not get to make that
 * assumption about itself.
 */
export function auditFact(fact: OwnedFact, pages: { path: string; src: string }[]): string[] {
  const rendering = pages.filter((p) => fact.marker.test(p.src)).map((p) => p.path);
  const allowed = new Set([fact.owner, ...(fact.alsoAllowed ?? []).map((a) => a.path)]);
  const problems: string[] = [];
  if (rendering.length === 0) problems.push(`orphaned: renders on no page (owner ${fact.owner})`);
  else if (!rendering.includes(fact.owner)) problems.push(`moved: owner ${fact.owner} does not render it`);
  for (const p of rendering.filter((p) => !allowed.has(p))) problems.push(`restated on ${p}`);
  return problems;
}

describe('§5.3 ownership map -- every owned fact renders on exactly one page', () => {
  const pages = pageFiles().map((p) => ({ ...p, src: stripComments(p.src) }));

  it('finds the pages to scan', () => {
    // Vacuity guard. A broken walk returns [], every fact then renders on zero pages, and the
    // suite below would report the incident it exists to detect -- or, with the assertion written
    // the other way round, pass while describing nothing. Neither is acceptable silently.
    expect(pages.length, 'the page walk found nothing').toBeGreaterThan(10);
    expect(pages.map((p) => p.path)).toContain('pages/index.tsx');
  });

  it.each(OWNED_FACTS.map((f) => [f.fact, f] as const))('%s', (_label, fact) => {
    const rendering = pages.filter((p) => fact.marker.test(p.src)).map((p) => p.path);
    const allowed = new Set([fact.owner, ...(fact.alsoAllowed ?? []).map((a) => a.path)]);

    // THE HALF THAT WAS MISSING. Two correct-looking deletions took this to zero and every other
    // check in the tree stayed green.
    expect(
      rendering,
      `"${fact.fact}" renders on NO page. §5.3 gives it an owner (${fact.owner}); a fact with an ` +
        `owner and no renderer is the 2026-08-07 defect exactly. Restore it to ${fact.owner}.`,
    ).not.toEqual([]);

    expect(
      rendering,
      `"${fact.fact}" is owned by ${fact.owner} and must render there.`,
    ).toContain(fact.owner);

    const trespassers = rendering.filter((p) => !allowed.has(p));
    expect(
      trespassers,
      `"${fact.fact}" is restated on ${trespassers.join(', ')}. §5.3 says it is stated once, on ` +
        `${fact.owner}; every other page links. If a second rendering is genuinely correct, add ` +
        `it to alsoAllowed WITH the reason, so the exception is reviewable instead of invisible.`,
    ).toEqual([]);
  });
});

describe('§5.3 ownership map -- the map itself stays honest', () => {
  it('names an owner that exists', () => {
    // An owner path that has been renamed makes every assertion above unfalsifiable: the fact
    // renders nowhere, and the failure reads as a missing section rather than a stale map.
    const paths = new Set(pageFiles().map((p) => p.path));
    for (const fact of OWNED_FACTS) {
      expect(paths, `${fact.fact}: owner ${fact.owner} is not a page`).toContain(fact.owner);
      for (const extra of fact.alsoAllowed ?? []) {
        expect(paths, `${fact.fact}: allowance ${extra.path} is not a page`).toContain(extra.path);
      }
    }
  });

  /**
   * Replays 2026-08-07 against synthetic pages.
   *
   * These four cases are the proof that the assertions above are load-bearing rather than
   * decorative. The first is the incident itself, reduced to its mechanism: a fact rendered twice
   * on one page, two deletions, zero renderers left. Under an at-most-once rule -- the natural way
   * to write a de-duplication guard, and the way it would have been written that day -- case 1
   * PASSES. That is the whole reason this file asserts exactly-once.
   */
  const manifest = OWNED_FACTS.find((f) => f.marker.source.includes('PackContentsSection'))!;

  it('fires when a fact is deleted from every page (the 2026-08-07 defect)', () => {
    const problems = auditFact(manifest, [
      { path: 'pages/index.tsx', src: 'export default function Home() { return <main /> }' },
      { path: 'pages/pricing.tsx', src: 'export default function Pricing() { return <main /> }' },
    ]);
    expect(problems).toEqual(['orphaned: renders on no page (owner pages/index.tsx)']);
  });

  it('fires when a fact is restated on a second page', () => {
    const problems = auditFact(manifest, [
      { path: 'pages/index.tsx', src: '<PackContentsSection />' },
      { path: 'pages/about.tsx', src: '<PackContentsSection />' },
    ]);
    expect(problems).toEqual(['restated on pages/about.tsx']);
  });

  it('fires when a fact migrates off its owner', () => {
    const problems = auditFact(manifest, [
      { path: 'pages/index.tsx', src: '<main />' },
      { path: 'pages/pack/[id].tsx', src: '<PackContentsSection />' },
    ]);
    expect(problems).toEqual(['moved: owner pages/index.tsx does not render it']);
  });

  it('stays silent on the correct arrangement, allowance included', () => {
    // The non-firing guard. Without it the three above are satisfied by a predicate that always
    // reports a problem, which would fail every real edit and be deleted within the week.
    const problems = auditFact(manifest, [
      { path: 'pages/index.tsx', src: '<PackContentsSection />' },
      { path: 'pages/pack/[id].tsx', src: '<PackContentsSection />' },
      { path: 'pages/about.tsx', src: '<main />' },
    ]);
    expect(problems).toEqual([]);
  });

  it('the ownership map cannot be bypassed by moving prose into config', () => {
    /*
     * The walk above reads `src/pages` only, which is the right scope for "which page renders
     * this" and the wrong scope for the way this rule was actually broken. `FOUNDER.bio` held the
     * founder's story as a five-sentence string in `lib/config.ts`; it rendered on whatever
     * surface imported it, and the page walk would have called the story correctly owned the
     * entire time. A config constant is a page's copy with the ownership check routed around it.
     *
     * The threshold is length, not content: paragraph-length prose in a config object is the
     * signature, and matching on the story's words would pass the moment someone reworded it.
     * 200 chars clears everything the block is for -- a name, a role in a few words, a path, a URL
     * -- and sits well under the 417-char string that was there (measured against `HEAD` before
     * the deletion: OLD flags `FOUNDER.bio (417 chars)`, the working tree is clean).
     */
    const config = stripComments(readFileSync(join(SRC, 'lib/config.ts'), 'utf8'));
    const founder = /export const FOUNDER = \{([\s\S]*?)\n\} as const;/.exec(config);
    expect(founder, 'FOUNDER block not found -- this guard has gone vacuous').not.toBeNull();

    const prose = [...founder![1].matchAll(/(\w+):\s*(["'])([\s\S]*?)\2\s*,/g)]
      .filter(([, , , value]) => value.length > 200)
      .map(([, key, , value]) => `FOUNDER.${key} (${value.length} chars)`);

    expect(
      prose,
      `These hold paragraph-length copy in config:\n  ${prose.join('\n  ')}\n` +
        `§5.3 gives each fact one owning PAGE. Prose in a config constant renders wherever it is ` +
        `imported and this file's page walk cannot see it -- which is exactly how the founder ` +
        `story was told twice. Put it in the owning page's markup.`,
    ).toEqual([]);
  });

  it('gives every allowance a stated reason', () => {
    // An allowance list is where an exactly-once rule goes to die. Requiring prose forces the
    // next author to argue for the exception in writing rather than append a path.
    for (const fact of OWNED_FACTS) {
      for (const extra of fact.alsoAllowed ?? []) {
        expect(
          extra.because.length,
          `${fact.fact}: allowance ${extra.path} has no stated reason`,
        ).toBeGreaterThan(40);
      }
    }
  });
});
