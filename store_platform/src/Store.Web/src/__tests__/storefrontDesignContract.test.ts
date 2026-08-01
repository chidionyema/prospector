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
    assertContains('page bg', css, /--bg:\s*#F8FAFC/i);
    assertContains('surface', css, /--surface:\s*#FFFFFF/i);
    assertContains('text', css, /--text:\s*#0F172A/i);
    assertContains('muted', css, /--muted:\s*#64748B/i);
    assertContains('border', css, /--border:\s*#E2E8F0/i);
  });

  it('defines primary and primary-hover', () => {
    assertContains('primary', css, /--primary:\s*#042F2E/i);
    assertContains('primary-hover', css, /--primary-hover:\s*#022C22/i);
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

  it('sets H1 at 48px / weight 700 / line-height 1.1 / tracking -0.02em', () => {
    // --text-h1 is the h1 size token
    expect(css).toMatch(/--text-h1:\s*3rem/); // 48px
    expect(css).toMatch(/--text-h1--line-height:\s*1\.1/);
    expect(css).toMatch(/--text-h1--letter-spacing:\s*-0\.02em/);
  });

  it('sets H2 at 24px / weight 600 / line-height 1.3', () => {
    expect(css).toMatch(/--text-h2:\s*1\.5rem/); // 24px
    expect(css).toMatch(/--text-h2--line-height:\s*1\.3/);
  });

  it('sets body at 16px / line-height 1.6', () => {
    expect(css).toMatch(/--text-body:\s*1rem/); // 16px
    expect(css).toMatch(/--text-body--line-height:\s*1\.6/);
  });

  it('sets metadata at 13px / weight 500', () => {
    expect(css).toMatch(/--text-meta:\s*0\.8125rem/); // 13px
    expect(css).toMatch(/--text-meta--font-weight:\s*500/);
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

  /** The card's outermost `<Link>` — the element carrying surface, border, radius and hover. */
  const cardLinkClasses = (() => {
    const match = /<Link\s[^>]*className="([^"]*)"/.exec(packCard);
    expect(match, 'PackCard <Link> className not found').not.toBeNull();
    return match![1];
  })();

  it('renders cards with white bg, 1px border, 8px radius, 24px padding', () => {
    assertContains('card white bg', cardLinkClasses, 'bg-white');
    assertContains('card 1px border', cardLinkClasses, 'border border-border');
    // 8px radius = rounded-lg (the design token --radius-lg is 8px)
    assertContains('card 8px radius', cardLinkClasses, 'rounded-lg');
    // 24px padding = p-6, on the card's content well rather than the link itself (the cover
    // image is full-bleed, so padding cannot live on the outer element).
    assertContains('card 24px padding', packCard, 'p-6');
  });

  it('applies hover translateY(-2px) and the exact named shadow', () => {
    // -2px translate: Tailwind -translate-y-0.5 = -0.125rem = -2px
    // OR an arbitrary value like [transform:translateY(-2px)]
    expect(
      cardLinkClasses,
      'card hover translateY(-2px)',
    ).toMatch(/hover:-translate-y-0\.5|hover:\[transform:translateY\(-2px\)\]/);

    // Exact shadow from spec
    // Tailwind 4 JIT encodes spaces as underscores in arbitrary values.
    assertContains(
      'card hover shadow',
      cardLinkClasses,
      '0_10px_15px_-3px_rgba(15,23,42,0.08)',
    );
  });
});

describe('Design contract — primary CTAs', () => {
  const page = readSource('../pages/index.tsx');
  const button = readSource('../components/ui/Button.tsx');

  it('hero "Browse the packs" / "See the N that survived" uses primary style', () => {
    // The hero CTA links to #catalog. It should use bg-primary (#042F2E), white text,
    // text-sm (14px), font-medium (500), px-6 py-3 (12px 24px), rounded-md (6px).
    // We look for a Link with href="#catalog" that carries the CTA classes.
    const heroLinkPattern = /href="#catalog"[^>]*className="([^"]*)"/;
    const match = heroLinkPattern.exec(page);
    expect(match, 'hero #catalog link not found').not.toBeNull();
    const classes = match![1];
    expect(classes, 'hero CTA bg-primary').toMatch(/bg-primary/);
    expect(classes, 'hero CTA white text').toMatch(/text-white/);
    expect(classes, 'hero CTA text-sm').toMatch(/text-sm/);
    expect(classes, 'hero CTA font-medium').toMatch(/font-medium/);
    expect(classes, 'hero CTA px-6').toMatch(/px-6/);
    expect(classes, 'hero CTA py-3').toMatch(/py-3/);
    expect(classes, 'hero CTA rounded-md').toMatch(/rounded-md/);
  });

  it('spotlight "View vetted blueprint" button uses primary CTA style', () => {
    assertContains('spotlight CTA', page, 'View vetted blueprint');
    // The spotlight CTA surrounding span uses bg-primary, text-white, etc.
    // Find the span containing "View vetted blueprint"
    const spotlightBtnPattern = /className="([^"]*)"[^>]*>\s*View vetted blueprint/;
    const match = spotlightBtnPattern.exec(page);
    expect(match, 'spotlight CTA not found').not.toBeNull();
    const classes = match![1];
    expect(classes, 'spotlight CTA bg-primary').toMatch(/bg-primary/);
    expect(classes, 'spotlight CTA white text').toMatch(/text-white/);
    expect(classes, 'spotlight CTA text-sm').toMatch(/text-sm/);
    expect(classes, 'spotlight CTA font-medium').toMatch(/font-medium/);
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
    expect(classes, 'comparison CTA white text').toMatch(/text-white/);
    expect(classes, 'comparison CTA text-sm').toMatch(/text-sm/);
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

  it('desktop catalogue sidebar is 280px and sticky with top offset', () => {
    // grid-cols-[280px_1fr] or w-[280px] or w-70 for the aside column
    const sidebarColPattern = /lg:grid-cols-\[280px_1fr\]|lg:grid-cols-\[17\.5rem_1fr\]/;
    expect(page, 'sidebar 280px column').toMatch(sidebarColPattern);

    // sticky and top-24 (or top-6 for 24px)
    expect(page, 'sidebar sticky').toMatch(/lg:sticky/);
    expect(page, 'sidebar top offset').toMatch(/lg:top-(?:24|6)\b/);
  });
});
