import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
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
    // Brand v2 (2026-08-05): the warm-paper palette was rejected as dated.
    // The v2 uses clean white (#FFFFFF) for bg and surface, a higher-contrast
    // neutral (#E5E5E5) for border, and a darker text (#0A0A0A).
    assertContains('page bg', css, /--bg:\s*#FFFFFF/i);
    assertContains('surface', css, /--surface:\s*#FFFFFF/i);
    assertContains('text', css, /--text:\s*#0A0A0A/i);
    assertContains('muted', css, /--muted:\s*#6B6B6B/i);
    assertContains('border', css, /--border:\s*#E5E5E5/i);
  });

  it('defines primary and primary-hover', () => {
    // Brand v2: --primary is the bold vermillion #FF5A1F (was the muddy
    // deep teal #042F2E, rejected by stakeholder on 2026-08-05).
    assertContains('primary', css, /--primary:\s*#FF5A1F/i);
    assertContains('primary-hover', css, /--primary-hover:\s*#E64500/i);
  });

  it('defines verified background and text tokens', () => {
    assertContains('verified-bg', css, /--verified-bg:\s*#ECFDF5/i);
    assertContains('verified-text', css, /--verified-text:\s*#065F46/i);
  });

  it('exposes primary and primary-hover in @theme inline block', () => {
    // The @theme inline block must map the CSS variables so Tailwind utilities resolve them.
    assertContains('--color-primary', css, /--color-primary:\s*var\(--primary\)/);
    // primary-hover should be exposed as a colour token so bg-primary-hover works
    expect(css).toMatch(/--color-primary-hover:\s*var\(--primary-hover\)/);
  });

  it('exposes verified tokens in @theme inline', () => {
    expect(css).toMatch(/--color-verified-bg:\s*var\(--verified-bg\)/);
    expect(css).toMatch(/--color-verified-text:\s*var\(--verified-text\)/);
  });

  it('sets H1 at 36px / line-height 1.1 / tracking -0.025em', () => {
    // Was 4.5rem (72px). The 6-step consolidation (2026-08-05) set the scale from the sizes the
    // pages actually used: no page ever rendered a 72px heading, the largest real one was
    // `text-5xl` (48px), which is now --text-display. --text-h1 is the 36px `text-4xl` tier.
    expect(css).toMatch(/--text-h1:\s*2\.25rem/); // 36px
    expect(css).toMatch(/--text-h1--line-height:\s*1\.1/);
    expect(css).toMatch(/--text-h1--letter-spacing:\s*-0\.025em/);
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

  it('renders cards with left-rule document styling, no rounded shadow', () => {
    // 'The Brief' direction: left-rule (3px primary), warm surface bg,
    // rounded-r-sm for subtle right corners, border-l-primary for the document look.
    assertContains('card surface bg', cardLinkClasses, 'bg-surface');
    assertContains('card left rule', cardLinkClasses, 'border-l-primary');
    assertContains('card 3px left border', cardLinkClasses, 'border-l-[3px]');
    // No rounded-xl — cards are documents, not SaaS tiles
    expect(cardLinkClasses, 'card must not have rounded-xl').not.toMatch(/rounded-xl/);
    // Card body padding
    assertContains('card padding', packCard, 'px-5');
  });

  it('answers hover with subtle warm shift', () => {
    // 'The Brief': hover shifts to slightly warmer (#F8F5EF), no lift, no shadow
    assertContains('card hover warm shift', cardLinkClasses, 'hover:bg-');
  });

  /**
   * Added 2026-08-01 with the card's three tiers. This is the assertion the old contract had no
   * equivalent of, and its absence is why the regression went unseen for as long as it did:
   * sources and freshness were entries 7 and 8 of a list sliced to 5, so proof lost every tie
   * against a descriptive tag — and lost more often as facet coverage improved. Measured on the
   * live catalogue that day (n=51): `verifiedAt` present on 51, freshness rendered on 2.
   */
  it('renders the proof tier outside the capped chip row', () => {
    assertContains('proof tier present', packCard, '<ProofLine');
    const proofLine = (() => {
      const start = page.indexOf('function ProofLine(');
      expect(start, 'function ProofLine not found in index.tsx').toBeGreaterThan(-1);
      const end = page.indexOf('\nfunction ', start + 1);
      return page.slice(start, end === -1 ? undefined : end);
    })();
    expect(proofLine, 'ProofLine must not be truncated by CARD_META_MAX').not.toContain(
      'CARD_META_MAX',
    );
    expect(proofLine, 'ProofLine must not slice its own entries').not.toMatch(/\.slice\(/);
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

  it('hero "Browse the packs" / "See the N that survived" uses primary style', () => {
    // The hero CTA links to #catalog. It should use bg-primary (#FF5A1F vermillion), on-primary text,
    // text-sm (14px), font-medium (500), px-6 py-3 (12px 24px), rounded-md (6px).
    // We look for a Link with href="#catalog" that carries the CTA classes.
    const heroLinkPattern = /href="#catalog"[^>]*className="([^"]*)"/;
    const match = heroLinkPattern.exec(page);
    expect(match, 'hero #catalog link not found').not.toBeNull();
    const classes = match![1];
    expect(classes, 'hero CTA bg-primary').toMatch(/bg-primary/);
    expect(classes, 'hero CTA uses the on-primary token, not a hardcoded white')
      .toMatch(/text-on-primary/);
    expect(classes, 'hero CTA text-sm').toMatch(/text-meta/);
    expect(classes, 'hero CTA font-medium').toMatch(/font-medium/);
    expect(classes, 'hero CTA px-6').toMatch(/px-6/);
    expect(classes, 'hero CTA py-3').toMatch(/py-3/);
    expect(classes, 'hero CTA rounded-md').toMatch(/rounded-md/);
  });

  it('spotlight "View vetted blueprint" button uses primary CTA style', () => {
    assertContains('spotlight CTA', page, 'View vetted blueprint');
    // The spotlight CTA surrounding span uses bg-primary, text-on-primary, etc.
    // Find the span containing "View vetted blueprint"
    const spotlightBtnPattern = /className="([^"]*)"[^>]*>\s*View vetted blueprint/;
    const match = spotlightBtnPattern.exec(page);
    expect(match, 'spotlight CTA not found').not.toBeNull();
    const classes = match![1];
    expect(classes, 'spotlight CTA bg-primary').toMatch(/bg-primary/);
    expect(classes, 'spotlight CTA uses the on-primary token, not a hardcoded white')
      .toMatch(/text-on-primary/);
    expect(classes, 'spotlight CTA text-sm').toMatch(/text-meta/);
    expect(classes, 'spotlight CTA font-bold').toMatch(/font-bold/);
  });

  it('comparison block "Browse the packs" uses primary CTA style', () => {
    // The comparison block has a Link with "Browse the packs"
    assertContains('comparison CTA text', page, 'Browse the packs');
    // Find the Link className near "Browse the packs"
    const comparisonPattern = /className="([^"]*)"[^>]*>\s*Browse the packs/;
    const match = comparisonPattern.exec(page);
    expect(match, 'comparison CTA not found').not.toBeNull();
    const classes = match![1];
    expect(classes, 'comparison CTA bg-primary').toMatch(/bg-primary/);
    expect(classes, 'comparison CTA uses the on-primary token, not a hardcoded white')
      .toMatch(/text-on-primary/);
    expect(classes, 'comparison CTA text-sm').toMatch(/text-meta/);
    expect(classes, 'comparison CTA font-medium').toMatch(/font-medium/);
    expect(classes, 'comparison CTA px-6').toMatch(/px-6/);
    expect(classes, 'comparison CTA py-3').toMatch(/py-3/);
    expect(classes, 'comparison CTA rounded-md').toMatch(/rounded-md/);
  });

  it('Button.tsx prominent variant uses primary colour and hover', () => {
    // The prominent variant should use bg-primary (#042F2E) not bg-text.
    // Check the VARIANTS record for 'prominent'.
    expect(button, 'prominent bg-primary').toMatch(/prominent:\s*cx\(\s*['"]bg-primary/);
    expect(button, 'prominent hover:bg-primary-hover').toMatch(/hover:bg-primary-hover/);
  });
});

describe('Design contract — wordmark (Logo.tsx)', () => {
  const logo = readSource('../components/ui/Logo.tsx');

  it('renders one word split into two spans with a teal period', () => {
    // The wordmark destructures from BRAND.wordmark (which lives in config.ts).
    // Logo.tsx should destructure first/second and render a teal period.
    expect(logo, 'destructures BRAND.wordmark').toMatch(/BRAND\.wordmark/);
    // The wordmark values are in config.ts — verify them there.
    const cfg = readSource('../lib/config.ts');
    expect(cfg, 'wordmark first').toMatch(/first:\s*['"]Mum['"]/);
    expect(cfg, 'wordmark second').toMatch(/second:\s*['"]chimp['"]/);
    // Teal period: the period should be rendered in a teal/primary colour
    expect(logo, 'teal period').toMatch(/text-primary[^"]*">\.</);
  });

  it('first span coloured text, second span muted', () => {
    // First part should have text color class (text-text or textColor variable)
    // Second part should have muted class
    // These are applied via the textColor and mutedColor variables
    expect(logo, 'textColor variable').toMatch(/textColor\s*=\s*onDark\s*\?\s*['"]text-white['"]\s*:\s*['"]text-text['"]/);
    expect(logo, 'mutedColor variable').toMatch(/mutedColor\s*=/);
    expect(logo, 'muted colour class on second span').toMatch(/mutedColor/);
  });

  it('uses weight 800 (font-extrabold or font-black)', () => {
    expect(logo).toMatch(/font-extrabold|font-black/);
  });

  it('has accessible name via sr-only or aria-label with full brand name', () => {
    // Accessible name should be the full brand name "Mumchimp"
    expect(logo, 'sr-only or aria-label with BRAND.name').toMatch(/sr-only.*\{BRAND\.name\}|aria-label=\{BRAND\.name\}/);
  });

  it('dark-ground variant (onDark) renders white text on dark', () => {
    // The textColor variable maps to white when onDark is true
    expect(logo, 'onDark white text').toMatch(/onDark\s*\?\s*['"]text-white['"]/);
    // And the span background/wrapper should be legible on dark
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

  it('has background fill #042F2E', () => {
    expect(svg).toMatch(/fill="#042F2E"/);
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

  it('principal content wrapper bounded at ≤1200px', () => {
    // The header in MarketingLayout uses max-w-6xl (1152px), SectionBand width="6xl" also maps
    // to max-w-6xl. Either is ≤1200px.
    const hasSixXl = layout.includes('max-w-6xl');
    const has1200px =
      layout.includes('max-w-[1200px]') ||
      page.includes('max-w-[1200px]');
    expect(
      hasSixXl || has1200px,
      'principal content wrapper should use max-w-6xl or max-w-[1200px]',
    ).toBe(true);
  });

  it('desktop catalogue shows StepFlow discovery by default', () => {
    // Discovery v2: the progressive question flow is visible on page load.
    // StepFlow is imported and rendered between toolbar and grid.
    expect(page).toContain('StepFlow');
    // The desktop FacetBar sidebar grid layout is gone.
    expect(page).not.toMatch(/lg:grid-cols-\[280px_1fr\]/);
  });
});
