import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

const SRC = fileURLToPath(new URL('..', import.meta.url));

/** Every `.tsx` under `src/`, tests excluded, as `{ path, src }`. */
function walkTsx(dir: string = SRC, out: { path: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walkTsx(path, out);
    else if (entry.endsWith('.tsx')) out.push({ path: path.slice(SRC.length), src: readFileSync(path, 'utf8') });
  }
  return out;
}

/**
 * The same file with its comments removed.
 *
 * Needed by every assertion of the form "X must be GONE": these files explain what they replaced,
 * by name, in prose ("the `onDark` prop is gone", "it was #042F2E teal"). Matching the rationale
 * makes a suite fail on its own documentation, which teaches the next author to delete the
 * explanation rather than keep the guarantee.
 */
function readStripped(relativePath: string): string {
  return readSource(relativePath)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^\s*\/\/.*$/gm, '');
}

// ── Helpers ────────────────────────────────────────────────────────────

/** Assert `text` contains `pattern` (string or regex). */
function assertContains(label: string, text: string, pattern: string | RegExp) {
  if (typeof pattern === 'string') {
    expect(text, `${label}: missing "${pattern}"`).toContain(pattern);
  } else {
    expect(text, `${label}: missing match for ${pattern}`).toMatch(pattern);
  }
}

describe('Design contract — global tokens (globals.css)', () => {
  const css = readSource('../styles/globals.css');

  it('defines page surface text muted border colours', () => {
    // Brand v3 (2026-08-06): a neutral grey scale. The v2 values pinned here were
    // #0A0A0A text and #E5E5E5 border; v3 moves to the Zinc-derived ramp so text, muted,
    // subtle and border are steps of ONE scale rather than four separately-chosen greys.
    assertContains('page bg', css, /--bg:\s*#FFFFFF/i);
    assertContains('surface', css, /--surface:\s*#FFFFFF/i);
    assertContains('text', css, /--text:\s*#171717/i);
    assertContains('muted', css, /--muted:\s*#52525B/i);
    assertContains('border', css, /--border:\s*#E4E4E7/i);
  });

  it('defines primary and primary-hover', () => {
    // Brand v3: --primary is INK. v2 pinned the vermillion #FF5A1F here, and a saturated
    // orange fill on every CTA is the single loudest thing the founder rejected. The buy
    // button is now the darkest element on the page, which is what makes it the only one.
    assertContains('primary', css, /--primary:\s*#171717/i);
    assertContains('primary-hover', css, /--primary-hover:\s*#2E2E33/i);
  });

  it('defines the semantic success pair used by the evidence surfaces', () => {
    // Replaces the v2 `--verified-bg`/`--verified-text` pair, which was a second, parallel
    // green that existed only for "verified" chrome and drifted from --success. One green.
    // `--success-strong` exists because --success on --success-bg measures below AA, which
    // is exactly the pairing every Badge tone was using.
    assertContains('success', css, /--success:\s*#/i);
    assertContains('success-bg', css, /--success-bg:\s*#/i);
    assertContains('success-strong', css, /--success-strong:\s*#/i);
    expect(css, 'the parallel --verified-* green must be gone').not.toMatch(/--verified-bg:/);
  });

  it('exposes primary and primary-hover in @theme inline block', () => {
    // The @theme inline block must map the CSS variables so Tailwind utilities resolve them.
    assertContains('--color-primary', css, /--color-primary:\s*var\(--primary\)/);
    // primary-hover should be exposed as a colour token so bg-primary-hover works
    expect(css).toMatch(/--color-primary-hover:\s*var\(--primary-hover\)/);
  });

  it('exposes the semantic colours in @theme inline', () => {
    // In Tailwind v4 an UNMAPPED colour utility emits no rule at all -- silently. That is how
    // `text-eyebrow`, `bg-vault-wash` and `text-gold` rendered nothing for weeks. Any token a
    // component names has to appear here or the class is a no-op.
    for (const token of ['success', 'success-bg', 'success-strong', 'warning', 'danger', 'accent']) {
      expect(css, `--color-${token} must be mapped in @theme inline`).toMatch(
        new RegExp(`--color-${token}:\\s*var\\(--${token}\\)`),
      );
    }
  });

  it('sets H1 at 32px / line-height 1.2 / tracking -0.02em', () => {
    // Was 36px/1.1/-0.025em under v2. Measured on the live pack pages, titles average ~90
    // characters: at 36px with 1.1 leading the h1 alone ran past the fold and the lines
    // collided. 32px at 1.2 is the step that fits the real content.
    expect(css).toMatch(/--text-h1:\s*2rem/); // 32px
    expect(css).toMatch(/--text-h1--line-height:\s*1\.2/);
    expect(css).toMatch(/--text-h1--letter-spacing:\s*-0\.02em/);
  });

  it('sets display at 48px, the largest step there is', () => {
    expect(css).toMatch(/--text-display:\s*3rem/); // 48px
    // A seventh step cannot be reached for: --text-hero/-h3/-small are deleted, not unused.
    expect(css).not.toMatch(/--text-hero:/);
    expect(css).not.toMatch(/--text-h3:/);
    expect(css).not.toMatch(/--text-small:/);
  });

  it('sets H2 at 24px / weight 600 / line-height 1.3', () => {
    expect(css).toMatch(/--text-h2:\s*1\.5rem/); // 24px
    expect(css).toMatch(/--text-h2--line-height:\s*1\.3/);
  });

  it('sets body at 16px / line-height 1.6', () => {
    expect(css).toMatch(/--text-body:\s*1rem/); // 16px
    expect(css).toMatch(/--text-body--line-height:\s*1\.6/);
  });

  it('sets metadata at 14px, and does not also set a weight', () => {
    // 0.875rem, not the old 0.8125rem, on purpose: --text-meta absorbed all 173 `text-sm`
    // utilities, and 0.875rem IS `text-sm`, so the consolidation renames rather than restyles.
    // --text-meta--font-weight: 500 was dropped for the same reason -- a size token that also set
    // a weight would have bolded all 173 of them.
    expect(css).toMatch(/--text-meta:\s*0\.875rem/); // 14px
    // Anchored on the colon: `css` here is the raw stylesheet, and the comment above the scale
    // block names this token while explaining why it went.
    expect(css).not.toMatch(/--text-meta--font-weight\s*:/);
  });

  it('hints a monospace font for data/metadata', () => {
    // Must mention mono in the font stack — Roboto Mono or ui-monospace are both fine.
    expect(css).toMatch(/--font-mono:\s*.*mono/i);
  });
});

describe('Design contract — catalogue blueprint cards (pages/index.tsx)', () => {
  const page = readSource('../pages/index.tsx');

  /**
   * Only the body of `function PackCard`. Scoping matters: `bg-white` appears 10 times in
   * index.tsx, `p-6` 4 times, `rounded-lg` 3 times — a whole-file `toContain` would still pass
   * with the card reverted to its old look, which is the same as no test at all.
   */
  const packCard = (() => {
    const start = page.indexOf('function PackCard(');
    expect(start, 'function PackCard not found in index.tsx').toBeGreaterThan(-1);
    const end = page.indexOf('\nfunction ', start + 1);
    return page.slice(start, end === -1 ? undefined : end);
  })();

  /** The card's outermost visual container — the element carrying surface, border, radius and hover.
   *  Accepts both plain string className and cx()-wrapped multi-line form. */
  const cardLinkClasses = (() => {
    // Try the cx() form first (multi-line), then fall back to plain string form.
    const cxMatch = /<Link[\s\S]*?className=\{cx\(([\s\S]*?)\)\}/.exec(packCard);
    if (cxMatch) {
      // Each arg to cx() is a JS string literal. Extract and join with space.
      const strings = [...cxMatch[1].matchAll(/'([^']*)'/g)].map((m) => m[1]);
      return strings.join(' ');
    }
    const match = /<Link\s[^>]*className="([^"]*)"/.exec(packCard);
    expect(match, 'PackCard <Link> className not found').not.toBeNull();
    return match![1];
  })();

  it('renders cards as a hairline-bordered surface, not a coloured document rule', () => {
    // v2 pinned `border-l-[3px] border-l-primary` -- a 3px vermillion rule down every card in
    // the grid. Sixty of them on one screen is sixty saturated stripes, and it is why the shelf
    // read as decoration rather than as a catalogue. v3: one hairline, all four sides.
    assertContains('card surface bg', cardLinkClasses, 'bg-surface');
    assertContains('card hairline', cardLinkClasses, 'border-border');
    assertContains('card radius', cardLinkClasses, 'rounded-md');
    expect(cardLinkClasses, 'card must not carry a coloured left rule').not.toMatch(
      /border-l-primary|border-l-\[3px\]/,
    );
    expect(cardLinkClasses, 'card must not have rounded-xl').not.toMatch(/rounded-xl/);
    assertContains('card padding', packCard, 'px-4');
  });

  it('answers hover with a lift and a stronger edge, not a background wash', () => {
    // A tint change on a white card is either invisible or dirty; the readable hover on a
    // bordered card is the border darkening and the card lifting 1px.
    assertContains('card hover border', cardLinkClasses, 'hover:border-border-strong');
    assertContains('card hover lift', cardLinkClasses, 'hover:-translate-y-px');
    expect(cardLinkClasses, 'hover must not wash the card background').not.toMatch(
      /hover:bg-(?!transparent)/,
    );
  });

  /**
   * Added 2026-08-01 with the card's three tiers. This is the assertion the old contract had no
   * equivalent of, and its absence is why the regression went unseen for as long as it did:
   * sources and freshness were entries 7 and 8 of a list sliced to 5, so proof lost every tie
   * against a descriptive tag — and lost more often as facet coverage improved. Measured on the
   * live catalogue that day (n=51): `verifiedAt` present on 51, freshness rendered on 2.
   */
  it('renders the proof tier outside any capped chip row', () => {
    // The defect this guards is unchanged; only the carrier is. `<ProofLine>` was deleted with
    // the gradient card on 2026-08-06 and the evidence row is now rendered inline in PackCard,
    // so the assertion follows it: the source count and the freshness date must appear in the
    // card body and must not be fed through anything that truncates.
    assertContains('source count', packCard, 'sources');
    assertContains('freshness', packCard, 'fresh');
    expect(packCard, 'the evidence row must not be capped by CARD_META_MAX').not.toMatch(
      /CARD_META_MAX[\s\S]{0,200}sources/,
    );
    // The chip row above it may still be capped -- that is what the cap is for. What must never
    // happen again is proof competing for those slots and losing.
    const evidenceRow = /font-mono[^`'"]*text-caption[\s\S]{0,400}?sources/.exec(packCard);
    expect(evidenceRow, 'the evidence row must be its own mono row, not a chip').not.toBeNull();
  });
});

/*
 * REVISED 2026-08-05: these three assertions pinned the literal `text-white` on primary CTAs.
 *
 * White on the brand vermillion #FF5A1F measures 3.12:1, below the WCAG 2.x AA floor of 4.5:1 for
 * normal text, so the site's most important controls were unreadable to the contrast the standard
 * assumes. The palette carries an `--on-primary` token for exactly this, and it now resolves to
 * #0A0A0A (6.35:1), but 20 call sites hardcoded `text-white` and bypassed it, which is why editing
 * the token alone changed nothing on screen.
 *
 * Pinning a raw colour in a design-contract test is what let that happen: it made the accessible
 * fix fail CI. The contract is "the CTA uses the palette's on-primary pairing", not "the CTA is
 * white", so these now assert the token.
 */
describe('Design contract — primary CTAs', () => {
  const page = readSource('../pages/index.tsx');
  const button = readSource('../components/ui/Button.tsx');

  /*
   * REWRITTEN 2026-08-06 (brand v3). The v2 version of this block asserted the literal utility
   * classes (`bg-primary text-on-primary text-meta font-medium px-6 py-3 rounded-md`) at each
   * CTA's CALL SITE, three times over. Two things were wrong with that:
   *
   *  - it pinned the style to the page rather than to the component, so the only way to keep it
   *    green was for every CTA to hand-roll the same class string. Twenty of them did, and when
   *    `--on-primary` was fixed for contrast, none of them picked it up (see the v2 note below,
   *    kept because that lesson stands);
   *  - it named `View vetted blueprint`, copy that no longer exists.
   *
   * v3 routes every CTA through `Button` / `buttonClasses`, so the contract is now: the component
   * owns the look, and the call sites use the component. That is checkable and it is what
   * actually prevents drift.
   *
   * v2's note, still true: white on the old vermillion measured 3.12:1, below the AA floor of
   * 4.5:1 for normal text. Pinning a raw colour in a design-contract test is what made the
   * accessible fix fail CI. Assert the token, never the hex.
   */

  it('Button owns the primary CTA look', () => {
    expect(button, 'primary variant fills with the primary token').toMatch(
      /primary:\s*cx\(\s*['"]bg-primary text-on-primary/,
    );
    expect(button, 'primary hover').toMatch(/hover:bg-primary-hover/);
    expect(button, 'CTA uses the on-primary token, not a hardcoded white').not.toMatch(
      /primary:\s*cx\(\s*['"][^'"]*text-white/,
    );
    expect(button, 'one radius on every button').toMatch(/rounded-md/);
    // Sizes are heights, not paddings: `py-3` on a text-meta button and `py-3` on a text-body
    // button produce two different control heights, which is why the CTAs never lined up.
    expect(button, 'md is a 40px control').toMatch(/md:\s*['"]h-10/);
    expect(button, 'lg is a 48px control').toMatch(/lg:\s*['"]h-12/);
  });

  it('the deleted v2 variants cannot be reached', () => {
    // `prominent` was the vermillion-fill-plus-3px-ink-shadow CTA. Gone, not merely unused.
    expect(button, "the 'prominent' variant must be deleted").not.toMatch(/prominent:/);
    expect(button, 'the sticker shadow must be gone').not.toMatch(/shadow-hard/);
  });

  it('the hero and comparison CTAs go through Button, not hand-rolled classes', () => {
    expect(page, 'hero CTA copy').toContain('Browse the packs');
    expect(page, 'index.tsx must import the shared button').toMatch(
      /import\s*\{[^}]*\bButton\b[^}]*\}\s*from\s*'@\/components\/ui'/,
    );
    // No CTA on the shelf may re-declare the primary fill inline. One place owns it.
    expect(page, 'no hand-rolled primary fill at a call site').not.toMatch(
      /className="[^"]*bg-primary[^"]*text-on-primary/,
    );
  });

  it('nowhere in the tree declares the primary CTA SHAPE except Button.tsx', () => {
    /*
     * The assertion above was scoped to `index.tsx`, and it passed the whole time six other files
     * were hand-rolling the same control: /orders/[token]'s download button, the pack page's
     * notify link, PriceArgument's browse link, and three in FacetBar. `PackBuyButton` -- the one
     * a buyer actually pays through -- carried a copy of `SIZES.lg` with a comment claiming it
     * "matches ui/Button.tsx size lg". So the scope is the tree, and the signature is the SHAPE
     * (a control height paired with the primary fill), because that is what visibly diverges: the
     * site shipped four different primary-CTA heights when each page invented its own.
     *
     * Scoped to shape, not to `bg-primary` alone, because a count badge legitimately wears the
     * fill without being a button (`CartButton`, `FacetBar`'s result pill).
     */
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      if (file.path.endsWith('ui/Button.tsx')) continue; // the one place that owns it
      file.src.split('\n').forEach((line, i) => {
        if (/\bh-1[02]\b[^"'`]*\bbg-primary\b|\bbg-primary\b[^"'`]*\bh-1[02]\b/.test(line)) {
          offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 100)}`);
        }
      });
    }
    expect(
      offenders,
      `call buttonClasses() instead of reproducing the shape:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('the buy button IS a Button, not a look-alike', () => {
    // The money control specifically. If this ever goes back to a literal class string, the day
    // `SIZES.lg` changes every CTA on the site follows it except the one that takes the payment.
    const buy = readSource('../components/checkout/PackBuyButton.tsx');
    expect(buy, 'PackBuyButton must call buttonClasses').toMatch(
      /const shapeClasses = buttonClasses\(\{ size: 'lg' \}\)/,
    );
  });

  it('nowhere in the tree declares the filter-chip SHAPE except Button.tsx', () => {
    /*
     * Same failure as the CTA above, found on the same day and with the same cause: the chip was
     * hand-rolled in three files and came out three ways.
     *
     *   kill-log.tsx   rounded-full pill, `bg-text` selected
     *   FacetBar.tsx   rounded-full pill, `bg-primary` selected
     *   faq.tsx        SQUARE, `border-primary bg-primary/10` selected
     *
     * The reasoning for the ink fill was written as a comment in FacetBar and nowhere else, so
     * the FAQ shipped the 10%-tint version that comment argues against (desktop-faq-fold.png,
     * 2026-08-06). `chipClasses()` now owns it.
     *
     * The signature is the pill height paired with a full-round radius: `h-8` + `rounded-full` on
     * one line. That is the chip and nothing else on the site is shaped like it -- avatars and
     * count badges are `rounded-full` but square (`h-5 w-5`, `h-8 w-8`), so they do not match.
     */
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      if (file.path.endsWith('ui/Button.tsx')) continue; // the one place that owns it
      file.src.split('\n').forEach((line, i) => {
        if (/\bh-8\b(?![^"'`]*\bw-8\b)[^"'`]*\brounded-full\b/.test(line)) {
          offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 100)}`);
        }
      });
    }
    expect(
      offenders,
      `call chipClasses() instead of reproducing the shape:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('renders no emoji anywhere in the tree', () => {
    /*
     * Stated twice in prose, enforced nowhere, and therefore only half true.
     *
     * `pricing.tsx` records the reason it stopped rendering the pack-contents emoji: each one is
     * a different vendor's artwork per OS, and a row of them is the loudest thing on a page
     * selling professional research. The FAQ went on rendering a thumbs-up and a thumbs-down
     * against every answer, including the refund policy (desktop-faq-fold.png, 2026-08-06),
     * because the rule lived in a comment on a different page.
     *
     * Comments are stripped: a comment may name the character it is banning, and this suite must
     * not make the fix be "delete the explanation". Scope is `.tsx` only, so any emoji in test
     * fixtures or catalogue DATA is out of scope -- this is about what the components draw.
     *
     * `\p{Extended_Pictographic}` is the line, and it is the right one: it matches the characters
     * a platform substitutes its own colour artwork for, and it does NOT match the monochrome
     * typographic marks the site legitimately sets in Geist. Verified, not assumed:
     *   node -e "const r=/\p{Extended_Pictographic}/u; for (const c of ['↵','→','✕','✓','👍','⚠️'])
     *            console.log(c, r.test(c))"
     *   -> ↵ false  → false  ✕ false  ✓ false  👍 true  ⚠️ true
     * A first cut of this test used explicit code-point ranges and flagged all six, which would
     * have forced seven arrow and tick glyphs through an Icon component for no reason.
     */
    const EMOJI = /\p{Extended_Pictographic}/u;
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      const stripped = file.src
        .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
        .replace(/^\s*\/\/.*$/gm, '');
      stripped.split('\n').forEach((line, i) => {
        if (EMOJI.test(line)) offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 100)}`);
      });
    }
    expect(
      offenders,
      `use an Icon or a word:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('renders no raw <input> outside the primitive library', () => {
    /*
     * `components/ui/index.ts` already says screens "never reach for raw <button>/<input>", and
     * three pages did it anyway: kill-log, faq and ideas/index each hand-rolled a search box, and
     * two of the three came out square with a `border-border` edge and a `focus:border-primary/40`
     * that is now grey-on-grey (2026-08-06). The rule was written down and enforced nowhere, so it
     * was true on the pages that happened to obey it. `SearchInput` is the shape now.
     *
     * The palette is the one exception and is listed by name: there the modal draws the border and
     * the input is transparent inside it, so it has no shape of its own to agree about.
     */
    const ALLOWED = /components\/ui\/|components\/discovery\/CommandPalette\.tsx$/;
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      if (ALLOWED.test(file.path)) continue;
      file.src.split('\n').forEach((line, i) => {
        if (/<input\b/.test(line)) offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 100)}`);
      });
    }
    expect(
      offenders,
      `use Input / SearchInput / Checkbox instead of a raw <input>:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('never hides a link behind :hover alone', () => {
    /*
     * `hover:underline` with no persistent underline puts the entire "this is a link" cue behind a
     * pointer event, and a phone has no pointer. What is left on touch is colour alone, which WCAG
     * 1.4.1 allows only at 3:1 against the surrounding text. Measured 2026-08-06 on the production
     * build, the pattern in the tree was `text-primary` links (`--primary` is `#171717`, byte-equal
     * to `--text`) inside `--muted` `#52525b` prose:
     *
     *   #171717 vs #52525b -> 2.32:1     (needs 3.00:1 when colour is the only cue)
     *
     * So 20 links across /terms, /refund, /privacy, /faq and /ideas were, on a phone, ink-coloured
     * words in a grey paragraph with nothing marking them as clickable. `textLinkClass` pairs the
     * accent with an underline that is always drawn, so the cue never depends on a hover.
     */
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      if (/components\/ui\/TextLink\.tsx$/.test(file.path)) continue;
      file.src.split('\n').forEach((line, i) => {
        if (!/hover:underline/.test(line)) return;
        // A line that already draws a permanent underline is fine; `hover:underline` is then
        // redundant rather than load-bearing.
        if (/(^|[\s"'`])underline([\s"'`]|$)|underline-offset/.test(line.replace(/hover:underline/g, ''))) return;
        offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 110)}`);
      });
    }
    expect(
      offenders,
      `a touch device never fires :hover -- use textLinkClass() so the underline is always drawn:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('gives every four-sided bordered surface the site radius', () => {
    /*
     * The contract already pins `rounded-md` on cards (line 180) and buttons (line 267), and 35
     * other surfaces were square anyway. Measured on the production build with
     * `getComputedStyle(...).borderTopLeftRadius === '0px'` on elements bordered on all four sides
     * (2026-08-06): 54 across 8 pages, including the sticky buy card on /pack/[id] sitting beside
     * rounded shelf cards, and all six evidence cards on /how-it-works, a page that rendered ZERO
     * rounded surfaces while every other page mixed the two.
     *
     * Four-sided only. A `border-t` above a footer row or a `border-b` between accordion rows is a
     * DIVIDER, and a rounded divider is a different bug; those must stay square, which is why this
     * anchors on the bare `border ` shorthand rather than on any border utility.
     */
    const FOUR_SIDED = /\bborder border-(border|text|warning|primary|accent)(\/\d+)?\b/;
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      // `Button.tsx` composes the border in `VARIANTS.secondary` and the radius in the shared BASE
      // string, so a line-scoped check cannot see them together. Every button's radius is already
      // asserted directly, against the composed output, by 'one radius on every button' above.
      if (/components\/ui\/Button\.tsx$/.test(file.path)) continue;
      file.src.split('\n').forEach((line, i) => {
        if (!FOUR_SIDED.test(line)) return;
        if (/rounded/.test(line)) return;
        offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 110)}`);
      });
    }
    expect(
      offenders,
      `a four-sided border is a surface and takes rounded-md; a one-sided rule is a divider:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('uses ONE inline-link treatment across the site', () => {
    /*
     * Four were in the tree on 2026-08-06, each of them "the house style" in the file that used it,
     * and two of them landed in the same buy box on /pack/[id]: "creating an account" in
     * rgb(113,113,122) next to "refund policy" in rgb(37,99,235), both underlined, one card apart.
     * The rule now lives in `textLinkClass`; this stops a fifth from being invented.
     */
    const KNOWN_ALTERNATIVES = [
      /className="[^"]*\btext-text underline\b/,
      /className="underline"/,
      /className="[^"]*\btext-primary\b[^"]*\bunderline\b/,
    ];
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      if (/components\/ui\//.test(file.path)) continue;
      file.src.split('\n').forEach((line, i) => {
        if (!/<(a|Link)\b/.test(line) && !/className=/.test(line)) return;
        if (KNOWN_ALTERNATIVES.some((re) => re.test(line))) {
          offenders.push(`${file.path}:${i + 1}  ${line.trim().slice(0, 110)}`);
        }
      });
    }
    expect(
      offenders,
      `use textLinkClass() for a link inside a sentence:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });
});

describe('Design contract — wordmark (Logo.tsx)', () => {
  const logo = readSource('../components/ui/Logo.tsx');

  /*
   * REWRITTEN 2026-08-06. Every assertion in the v2 version pinned a decision the founder then
   * rejected: "Mum" in ink + "chimp" in grey + a vermillion full stop, at weight 800, with a
   * white-on-dark inverted variant. Three colour decisions inside eight characters, and the split
   * fell mid-word so the two-tone read as a rendering fault. The v3 wordmark is ONE weight, ONE
   * ink, no dot, tracking closed up slightly.
   */

  it('renders the brand name from config, as one word', () => {
    expect(logo, 'reads BRAND.wordmark').toMatch(/BRAND\.wordmark/);
    const cfg = readSource('../lib/config.ts');
    expect(cfg, 'wordmark first').toMatch(/first:\s*['"]Mum['"]/);
    expect(cfg, 'wordmark second').toMatch(/second:\s*['"]chimp['"]/);
    // Assembled into a single rendered string, not two independently-styled spans.
    expect(logo, 'the halves render as one word').toMatch(/\$\{first\}\$\{second\}/);
  });

  it('uses one ink and one weight, with no coloured period', () => {
    expect(logo, 'single ink').toMatch(/text-text/);
    expect(logo, 'no coloured full stop').not.toMatch(/text-primary[^"]*">\.</);
    expect(logo, 'no second, muted half').not.toMatch(/mutedColor/);
    expect(logo, 'tracking closed up').toMatch(/tracking-\[-0\.02em\]/);
  });

  it('does not use a weight the font never loaded', () => {
    // _app.tsx loads Geist at 400/500/600 only. `font-bold`/`font-extrabold`/`font-black` would
    // be synthesised by the browser -- a smeared fake bold -- on the one string that is the
    // brand. This is the inverse of the v2 assertion, which REQUIRED weight 800.
    expect(logo, 'no synthesised weight on the wordmark').not.toMatch(
      /font-extrabold|font-black|font-bold/,
    );
    expect(logo, 'semibold is the heaviest weight loaded').toMatch(/font-semibold/);
  });

  it('has an accessible name carrying the full brand name', () => {
    expect(logo, 'sr-only or aria-label with BRAND.name').toMatch(
      /sr-only.*\{BRAND\.name\}|aria-label=\{BRAND\.name\}/,
    );
  });

  it('has no dark-ground variant, because v3 has no dark chrome', () => {
    // v2 required `onDark ? 'text-white'`. The dark band it inverted onto is deleted, and a prop
    // with no ground to sit on is how a lockup ends up white-on-white.
    expect(readStripped('../components/ui/Logo.tsx'), 'the onDark variant must be gone').not.toMatch(
      /onDark/,
    );
  });
});

describe('Design contract — favicon (public/icon.svg)', () => {
  const svg = readSource('../../public/icon.svg');

  it('is a 32×32 square', () => {
    expect(svg).toMatch(/viewBox="0 0 32 32"/);
    // The rect should be 32×32
    expect(svg).toMatch(/width="32"/);
    expect(svg).toMatch(/height="32"/);
  });

  it('has an ink background matching the monogram tile', () => {
    // Was the #042F2E teal -- a colour that appears nowhere in the v3 palette, on the one mark
    // that sits in a tab strip beside every other site the buyer has open.
    expect(svg).toMatch(/fill="#171717"/);
    expect(readStripped('../../public/icon.svg'), 'the old teal must be gone').not.toMatch(
      /#042F2E/i,
    );
  });

  it('has a white letter M centred', () => {
    // The letter should be "M", not "P"
    expect(svg, 'white M').toMatch(/fill="#ffffff"[^>]*>M</);
    // Or the other way around
    if (!/>M</.test(svg)) {
      // Maybe it's in a different order
      expect(svg).toMatch(/>M</);
    }
  });

  it('contains no monkey/ape imagery (brand name in aria-label is not imagery)', () => {
    // Strip the aria-label which contains the brand name "Mumchimp".
    const visual = svg.replace(/aria-label="[^"]*"/i, '');
    expect(visual.toLowerCase()).not.toMatch(/monkey|chimp|ape|gorilla|primate/);
  });
});

describe('Design contract — layout', () => {
  const page = readSource('../pages/index.tsx');
  const layout = readSource('../components/marketing/MarketingLayout.tsx');

  it('principal content wrapper is bounded, and bounded in one place', () => {
    // v2 required <=1200px (max-w-6xl). v3's shell is max-w-7xl (1280px), which is what the
    // three-column shelf needs to show three cards at a readable width without the grid
    // collapsing to two on a 1440 laptop. The contract that matters is not the exact number, it
    // is that ONE constant sets it: an unbounded or per-page wrapper is how the header, the
    // shelf and the footer end up on three different left edges.
    expect(layout, 'the shell width is a single named constant').toMatch(
      /const SHELL = '[^']*\bmax-w-(6xl|7xl|\[1200px\])\b/,
    );
    expect(page, 'pages must not re-declare their own wider wrapper').not.toMatch(
      /max-w-(screen|full|none)\b[^'"]*mx-auto/,
    );
  });

  it('every marketing page declares ONE band width', () => {
    /*
     * One page, one left edge.
     *
     * `PageHero` used to hardcode `width="4xl"` and `CtaBand` `width="3xl"`, while the pages that
     * render them set their body bands to 6xl or 7xl. The result was two and sometimes three left
     * margins down a single column of text: on /how-it-works the headline began at x=432 and every
     * one of the six checks below it at x=258 (desktop-how-it-works-fold.png, 2026-08-06). Both now
     * take a `width`, and this asserts each page picks exactly one value.
     *
     * The band width is not the measure. Line length is capped inside each block (`max-w-[60ch]`
     * and friends), so matching the band costs nothing in readability -- it only decides where the
     * column starts. That is why the fix is "agree", not "everything narrow".
     */
    const offenders: string[] = [];
    for (const file of walkTsx()) {
      // `walkTsx` yields paths relative to src, e.g. `pages/faq.tsx` -- a leading-slash pattern
      // here matched nothing and the whole test passed vacuously on the first run.
      if (!/(^|\/)pages\//.test(file.path)) continue;
      const widths = new Set<string>();
      // The default each component falls back to when a page does not say.
      if (/<PageHero(?![\w-])/.test(file.src) && !/<PageHero\b[\s\S]{0,200}?width=/.test(file.src)) {
        widths.add('4xl');
      }
      if (/<CtaBand(?![\w-])/.test(file.src) && !/<CtaBand\b[\s\S]{0,200}?width=/.test(file.src)) {
        widths.add('3xl');
      }
      // Only band widths. An unanchored `width="..."` also matches `<svg width="16">`, which is
      // how the first run reported `pages/pack/[id].tsx  16 + 6xl`.
      for (const m of file.src.matchAll(/width="(2xl|3xl|4xl|6xl|7xl)"/g)) widths.add(m[1]);
      if (widths.size > 1) offenders.push(`${file.path}  ${[...widths].sort().join(' + ')}`);
    }
    expect(
      offenders,
      `each page must use one band width so it has one left edge:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('desktop catalogue shows StepFlow discovery by default', () => {
    // Discovery v2: the progressive question flow is visible on page load.
    // StepFlow is imported and rendered between toolbar and grid.
    expect(page).toContain('StepFlow');
    // The desktop FacetBar sidebar grid layout is gone.
    expect(page).not.toMatch(/lg:grid-cols-\[280px_1fr\]/);
  });
});
