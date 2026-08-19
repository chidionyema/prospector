import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

/**
 * MASTER-BRIEF section 9, the cross-cutting sweep, and the section 10 boxes it closes.
 *
 * Every property here is invisible until it is wrong, and each one was wrong in a way that no
 * screenshot would have shown: a focus ring that named a colour the stylesheet does not define, a
 * header height written out by hand in ten places, form errors drawing the colour reserved for
 * ideas that died. A test is the only thing that holds any of them.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(join(SRC, rel), 'utf8');

/** Comments are argument. A note about a colour must not read as a use of it. */
const codeOnly = (src: string) =>
  src
    .split('\n')
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
    .join('\n');

describe('the focus ring is visible on every interactive element', () => {
  it('is 2px at 2px offset, globally', () => {
    const css = read('styles/globals.css');
    expect(css).toContain('*:focus-visible');
    expect(css).toContain('outline: 2px solid var(--focus)');
    expect(css).toContain('outline-offset: 2px');
  });

  it('names no colour utility the stylesheet does not define', () => {
    // `focus-visible:ring-link` on the collections tiles removed the global ring and replaced it
    // with nothing: Tailwind v4 emits no rule for an unmapped colour, and at the time there was no
    // `--color-link`. The tiles had no focus indicator at all, and nothing failed.
    const tokens = read('styles/tokens.css');
    const files = [
      'components/marketing/CollectionMosaic.tsx',
      'components/discovery/CategoryGraph.tsx',
      'components/cart/AddToCartButton.tsx',
      'components/cart/CartButton.tsx',
    ];
    for (const file of files) {
      const code = codeOnly(read(file));
      const named = [...code.matchAll(/(?:ring|outline|border|text|bg)-([a-z][a-z0-9-]*)\b/g)]
        .map((m) => m[1])
        .filter((name) => name === 'link');
      expect(named, `${file} names a colour with no --color-* mapping`).toEqual([]);
    }
    // The token EXISTS now, and this assertion flipped deliberately. Every mockup draws text links
    // and the focus ring in `--link:#2447C9`, so the fix for the original defect was to define the
    // colour, not to ban the name. What still must not happen is a utility with no mapping behind
    // it, which is what the loop above checks.
    expect(tokens).toContain('--link: #2447C9;');
    expect(tokens).toContain('--color-link: var(--link);');
  });

  it('never removes the outline without putting one back', () => {
    // `outline-none` plus `ring-2` is a ring flush against the control: on a filled button the
    // ring and the fill touch, so there is no gap and nothing reads as a ring.
    for (const file of [
      'components/marketing/CollectionMosaic.tsx',
      'components/discovery/CategoryGraph.tsx',
      'components/cart/AddToCartButton.tsx',
      'components/cart/CartButton.tsx',
      'components/ui/Toast.tsx',
    ]) {
      const code = codeOnly(read(file));
      expect(code, `${file} still suppresses its focus ring`).not.toContain(
        'focus-visible:outline-none',
      );
      expect(code, `${file} still suppresses its focus ring`).not.toContain('focus:outline-none');
    }
  });
});

describe('touch targets clear 44px', () => {
  // Each control keeps its old desktop size behind `sm:`. 44px is a thumb, not a cursor.
  const CASES: Array<[string, string]> = [
    ['components/ui/Toast.tsx', 'min-h-11 min-w-11'],
    ['components/discovery/CommandPalette.tsx', 'min-h-11 min-w-11'],
    ['components/ui/Modal.tsx', 'min-h-11 min-w-11'],
    ['components/cart/CartButton.tsx', 'h-11 w-11'],
    ['components/cart/AddToCartButton.tsx', 'h-11 w-11'],
    ['components/ui/Dropdown.tsx', 'h-11 w-full'],
  ];
  for (const [file, expected] of CASES) {
    it(`${file} sizes its control for a thumb`, () => {
      expect(codeOnly(read(file))).toContain(expected);
    });
  }
});

describe('the header height is a token, not ten hand-written numbers', () => {
  it('declares both states and a filter allowance', () => {
    const tokens = read('styles/tokens.css');
    // 58px, the height every mockup gives `.hdr-in`. It was 5rem/80px, 22px taller than the
    // drawing on every page at once. The compact value is the same number on purpose: the mockups'
    // header does not shrink on scroll.
    expect(tokens).toContain('--h-header: 58px;');
    expect(tokens).toContain('--h-header-compact: 58px;');
    expect(tokens).toContain('--h-filter: 0rem;');
  });

  it('steps to the compact height from the header\'s own state', () => {
    // :has() on the attribute the header already sets. Copying that state up to <html> in
    // JavaScript would be a second source of truth that can disagree with the first.
    const css = read('styles/globals.css');
    expect(css).toContain(':root:has(header[data-scrolled="true"])');
    expect(css).toContain('--h-header: var(--h-header-compact)');
    expect(read('components/marketing/MarketingLayout.tsx')).toContain('data-scrolled=');
  });

  it('measures anchor clearance from the token', () => {
    const css = read('styles/globals.css');
    expect(css).toContain('scroll-margin-top: calc(var(--h-header) + var(--h-filter) + 12px)');
    // The number this replaced. Two anchors carried it, and neither moved when the header did.
    expect(css).not.toContain('scroll-margin-top: 5.5rem');
  });

  it('sticks the filter bar under the header', () => {
    expect(codeOnly(read('components/discovery/FilterBar.tsx'))).toContain(
      "'sticky top-[var(--h-header)] z-20'",
    );
  });
});

describe('the mobile header gets out of the way', () => {
  const LAYOUT = read('components/marketing/MarketingLayout.tsx');

  it('hides on scroll down and comes back on scroll up', () => {
    expect(LAYOUT).toContain('setHeaderHidden(y > lastY && y > 160)');
    expect(LAYOUT).toContain('-translate-y-full');
    // Desktop never moves: there the header costs a small fraction of the viewport.
    expect(LAYOUT).toContain('md:!translate-y-0');
  });

  it('stays put under prefers-reduced-motion', () => {
    expect(LAYOUT).toContain("matchMedia('(prefers-reduced-motion: reduce)')");
    expect(LAYOUT).toContain('if (!reduced &&');
  });

  it('reads the scroll position once per frame', () => {
    // `window.scrollY` forces layout, and the scroll event fires far more often than the screen
    // refreshes. Without the frame guard this is a layout read per event on the busiest listener
    // on the site.
    expect(LAYOUT).toContain('window.requestAnimationFrame(read)');
    expect(LAYOUT).toContain('{ passive: true }');
  });
});

describe('kill red means an idea died, and nothing else', () => {
  it('gives form validation its own token', () => {
    const tokens = read('styles/tokens.css');
    expect(tokens).toContain('--error: var(--warning);');
    expect(tokens).toContain('--color-error: var(--error);');
    // Not --warn-mark. It measures 2.31:1 on the page ground, which fails AA for text and the
    // 3:1 floor for a border, so the brief's literal instruction cannot be followed as written.
    expect(tokens).not.toContain('--error: var(--warn-mark)');
  });

  it('has no danger utility left in the form components', () => {
    // A mistyped email address was being marked in the ink that means an idea died on the
    // evidence. Section 2 forbids that reuse by name, and the existing guard could not see it:
    // it matches `*-kill` utilities, and every form component reached the same hex as `*-danger`.
    for (const file of [
      'components/ui/Field.tsx',
      'components/ui/Input.tsx',
      'components/ui/RadioGroup.tsx',
      'components/ui/Checkbox.tsx',
    ]) {
      const code = codeOnly(read(file));
      expect(code, `${file} still draws the kill red`).not.toMatch(
        /(?:text|bg|border|ring|outline|decoration)-danger/,
      );
      expect(code).toMatch(/(?:text|bg|border|ring|outline)-error/);
    }
  });
});

describe('numbers line up and dead filters cannot be clicked', () => {
  it('sets tabular figures for the whole document', () => {
    // Inter's default figures are proportional, so a 1 is narrower than a 7 and a column of
    // prices does not align. It was opt-in at about thirty call sites, which means every number
    // nobody remembered to class was ragged.
    expect(read('styles/globals.css')).toContain('font-variant-numeric: tabular-nums');
  });

  it('disables a zero-count facet rather than hiding it', () => {
    // Hidden is worse than either: the option disappears and takes with it the information that
    // the category exists, so a buyer cannot tell a filter they have narrowed past from one this
    // shelf has never carried.
    const bar = codeOnly(read('components/discovery/FacetBar.tsx'));
    expect(bar).toContain('disabled={dead}');
    expect(bar).toContain('const dead = count === 0 && !active');
  });
});

describe('every route has a heading to land on', () => {
  it('gives the sign-in callback an h1', () => {
    // It had none: the page's only content was a paragraph, so the route had no h1 and a screen
    // reader had nothing to navigate to.
    expect(read('pages/auth/callback.tsx')).toContain('<h1 className="sr-only">Signing in</h1>');
  });
});

describe('the site states its evidence one way', () => {
  // MASTER-BRIEF section 10. Four call sites said the same thing in four wordings -- "12 sources",
  // "6 checks · 12 sources · verified 2026-08-01", "12 sources cited", "12 cited sources" -- because
  // each was written where it stood and nobody saw them together.
  it('routes every proof line through the shared component', () => {
    /* THE ROW'S SHARED COMPONENT IS `CardProof`, NOT `sourcesLabel` (2026-08-18, D4).
       The rule is unchanged and this test still enforces it: a card never words its own count.
       What moved is which shared thing it calls. Three proof sentences were live on the shelf
       that day ("38 sources", "16 cited sources behind it", "2x the price back in month one,
       modelled"), because a card could reach a raw label through `packLeadStat` as well as
       through `sourcesLabel`. `CardProof` takes the two raw numbers and renders the drawing's
       two forms, so there is one sentence per fact and no way to word a third. */
    expect(codeOnly(read('components/discovery/PackRow.tsx'))).toContain('<CardProof');
    const seq = codeOnly(read('components/marketing/CheckSequence.tsx'));
    expect(seq).toContain('<ProofLine');
    expect(seq).toContain('sourcesLabel(report.sourceCount)');
    expect(codeOnly(read('pages/sample.tsx'))).toContain('sourcesLabel(report.sourceCount)');
  });

  it('leaves no hand-written source count behind', () => {
    for (const file of [
      'components/discovery/PackRow.tsx',
      'components/marketing/CheckSequence.tsx',
      'pages/sample.tsx',
    ]) {
      expect(codeOnly(read(file)), `${file} still words its own count`).not.toMatch(
        /sourceCount\} (?:cited )?sources|sourceCount === 1 \? 'source'/,
      );
    }
  });
});

describe('the kill log tells a stage apart from a check', () => {
  const PAGE = codeOnly(read('pages/kill-log.tsx'));

  it('marks the three stage causes in both places it names a cause', () => {
    // `STAGE_GATES` and `isStage` were computed and carried all the way to the component, and no
    // component read either. "Scored too low" was drawn identically to "no durable advantage", so
    // the chart's biggest bar could be a tally rather than a finding and nothing said so.
    expect(PAGE).toContain('isStageLabel(entry.gateLabel)');
    expect(PAGE).toContain('d.isStage &&');
  });

  it('says on the page what the mark means', () => {
    expect(PAGE).toContain('points in the run rather than findings about the idea');
  });
});

describe('the hero grid records where a click came from', () => {
  it('sends card_click without needing JavaScript to navigate', () => {
    // The survivor squares were the one route to a pack with no event on it. The href still does
    // the navigating, so the graphic works with scripting off; the handler only adds the source.
    const grid = codeOnly(read('components/marketing/KillGrid.tsx'));
    expect(grid).toContain('href={`/pack/${pack.id}`}');
    expect(grid).toContain("track('card_click', `grid:${pack.id}`)");
  });
});

describe('a sector with nothing in it is disabled, not hidden', () => {
  it('offers every category and greys the empty ones', () => {
    const page = codeOnly(read('pages/index.tsx'));
    expect(page).toContain('const offered = allCategories();');
    expect(page).toContain("const dead = (counts[cat.key] ?? 0) === 0 && !active;");
    expect(page).toContain('disabled={dead}');
    // The count still prints. `counts[cat.key]` is undefined for a sector no pack occupies, and
    // React renders undefined as nothing, so the disabled chip would have carried no number.
    expect(page).toContain('{counts[cat.key] ?? 0}');
  });
});

/** Every `.ts`/`.tsx` under `src/`, so a rule cannot be re-declared -- or a required fact
 *  re-typed -- in a file this test never thought to name. A fixed file list is the same defect as
 *  a per-caller bound. */
function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(join(SRC, dir), { withFileTypes: true })) {
    const rel = dir ? `${dir}/${entry.name}` : entry.name;
    if (entry.isDirectory()) sourceFiles(rel, found);
    else if (/\.tsx?$/.test(entry.name)) found.push(rel);
  }
  return found;
}

describe('a shop-wide rule is declared once', () => {
  it('declares CREDIBLE_MULTIPLE_CEILING in lib/payback.ts and nowhere else', () => {
    // 2026-08-19. `lib/packStat.ts` carried a second `const CREDIBLE_MULTIPLE_CEILING = 20;`, with
    // a near-copy of the founder's argument above it, and then re-checked the bound twice on
    // values `paybackEquation` had already bounded. Nothing failed, because the two numbers agreed
    // -- which is the whole trap. `lib/payback.ts:80` states the principle the site is built on:
    // "A ceiling enforced per-caller is a ceiling the next caller forgets." The second copy makes
    // the first one optional, and the day the ceiling moves the shelf and the pack page start
    // making different claims about the same pack.
    const files = sourceFiles('');
    expect(files.length, 'the source walk found nothing; this test would pass vacuously')
      .toBeGreaterThan(100);
    expect(files, 'the walk missed the file that owns the rule').toContain('lib/payback.ts');

    const declaration = /^\s*(?:export\s+)?(?:const|let|var)\s+CREDIBLE_MULTIPLE_CEILING\b/m;
    const owners = files.filter((file) => declaration.test(read(file)));
    expect(owners).toEqual(['lib/payback.ts']);
  });
});

describe('the trader is identified on the shop front, not only in the small print', () => {
  /*
   * 2026-08-19. A persona teardown grepped all ten public pages of the live site for a company
   * number, a Companies House registration or a named limited company and found none. The footer
   * read "(c) 2026 Mumchimp. All rights reserved." and gave one email address.
   *
   * The data was not missing. `LEGAL.companyNumber` was confirmed against Companies House on
   * 2026-08-16, with the note that five DISSOLVED companies share the name "ByteSync", which is
   * why the number was recorded rather than the name alone. It was then rendered on zero pages,
   * and `legalName`/`address` reached only /terms, /privacy and /refund.
   *
   * That is the class: a fact held in config, required by law to be published, and rendered
   * nowhere -- invisible to every screenshot, every typecheck and every unit test, because
   * nothing was wrong, something was absent. reg 6 of the Electronic Commerce (EC Directive)
   * Regulations 2002 requires the name, geographic address and registration number to be easily,
   * directly and permanently accessible; the Consumer Contracts Regulations 2013 require trader
   * identity and geographic address before a distance contract is concluded. These tests fail if
   * the identity leaves the footer, or if a caller re-implements the sentence instead of asking
   * for it.
   */

  it('names the company number, the legal name and the address in one sentence', async () => {
    const { traderIdentity, LEGAL } = await import('../lib/config');
    const line = traderIdentity();
    expect(line).toContain(LEGAL.legalName);
    expect(line).toContain(LEGAL.address);
    expect(LEGAL.companyNumber, 'the registration number is the fact the name alone cannot carry')
      .toMatch(/^\d{6,8}$/);
    expect(line).toContain(`company number ${LEGAL.companyNumber}`);
  });

  it('renders that sentence in the footer of every marketing page', () => {
    const layout = codeOnly(read('components/marketing/MarketingLayout.tsx'));
    expect(layout).toContain('traderIdentity()');
    // In `.f-bottom`, the block that renders on every page, and not in a route-specific panel.
    const footer = layout.slice(layout.indexOf('f-bottom'));
    expect(footer, 'the identity moved out of the always-rendered footer').toContain(
      'traderIdentity()',
    );
  });

  it('is asked for, never re-typed: no file inlines the registration number', async () => {
    const { LEGAL } = await import('../lib/config');
    const offenders = sourceFiles('').filter(
      (file) => file !== 'lib/config.ts' && read(file).includes(LEGAL.companyNumber),
    );
    expect(offenders).toEqual([]);
  });
});
