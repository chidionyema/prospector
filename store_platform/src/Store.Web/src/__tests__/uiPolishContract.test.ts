import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Source-level contract test for the 2026-08-01 UI polish PR.
 *
 * Mirrors the conventions of `storefrontDesignContract.test.ts` and `packContents.test.ts` —
 * read the source as text and assert structural facts that the verify chain cannot catch on its
 * own. Each `describe` block corresponds to one numbered item in
 * `specs/ui-polish-2026-08-01.md` so the failure output points at the spec section, not at a
 * mystery.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, 'utf8');

// ── A. Accessibility primitives ──────────────────────────────────────────────────────────────

describe('A1. prefers-reduced-motion rule in globals.css', () => {
  const css = read('styles/globals.css');

  it('declares a @media (prefers-reduced-motion: reduce) block', () => {
    expect(css).toMatch(/@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)/);
  });

  /*
   * ALL of them, not the first one.
   *
   * These two assertions used `css.match(...)`, which returns the FIRST match, on the assumption
   * that the stylesheet has exactly one reduced-motion block. It now has three (view transitions,
   * the hero's kill drift, and the catch-all), and the catch-all that actually carries these
   * declarations is last. The single-match form failed on a stylesheet where the property holds,
   * and would equally have PASSED on one where a later block silently dropped it. Matching every
   * block and asserting the property holds somewhere across them is what was meant all along.
   */
  const reducedMotionBlocks = () => {
    const blocks = css.match(/@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)[\s\S]*?\n\}\n\}/g)
      ?? css.match(/@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)[\s\S]*?\n\}/g);
    expect(blocks, 'at least one reduced-motion block').not.toBeNull();
    return blocks!.join('\n');
  };

  it('disables the global transition blanket under reduced motion', () => {
    // The blanket applies to a, button, input, select, textarea, .card-transition. Under reduced
    // motion it must set transition: none (or equivalent) on at least one of those selectors.
    expect(reducedMotionBlocks()).toMatch(/transition\s*:\s*none/);
  });

  it('sets scroll-behavior: auto under reduced motion', () => {
    expect(reducedMotionBlocks()).toMatch(/scroll-behavior\s*:\s*auto/);
  });
});

describe('A2. Modal close button has a visible (sr-only) label', () => {
  const modal = read('components/ui/Modal.tsx');

  it('keeps the existing aria-label="Close" (regression guard)', () => {
    expect(modal).toContain('aria-label="Close"');
  });

  it('adds an sr-only "Close" string for the icon-failed-load case', () => {
    expect(modal).toMatch(/sr-only[^>]*>\s*Close/);
  });
});

describe('A3. Toast region pauses on hover/focus and is keyboard reachable', () => {
  const toast = read('components/ui/Toast.tsx');

  it('declares onMouseEnter / onMouseLeave to pause/resume auto-dismiss', () => {
    expect(toast).toMatch(/onMouseEnter\s*=/);
    expect(toast).toMatch(/onMouseLeave\s*=/);
  });

  it('declares onFocusCapture / onBlurCapture (keyboard reach)', () => {
    expect(toast).toMatch(/onFocusCapture\s*=/);
    expect(toast).toMatch(/onBlurCapture\s*=/);
  });

  it('makes each toast card tab-focusable (tabIndex=0)', () => {
    expect(toast).toMatch(/tabIndex\s*=\s*\{?\s*0\s*\}?/);
  });
});

// ── B. Z-index layering ──────────────────────────────────────────────────────────────────────

describe('B. z-index stack is consistent across overlays', () => {
  // The header sits above content but below modal/drawer overlays.
  it('MarketingLayout header uses z-30 (below modal)', () => {
    const header = read('components/marketing/MarketingLayout.tsx');
    expect(header).toMatch(/<header[^>]*z-30/);
  });

  it('Modal (drawer + dialog) keeps z-50', () => {
    const modal = read('components/ui/Modal.tsx');
    expect(modal).toMatch(/z-50/);
  });

  it('CommandPalette uses z-50', () => {
    const palette = read('components/discovery/CommandPalette.tsx');
    expect(palette).toMatch(/z-50/);
  });

  it('Toast region sits above modals (z-60)', () => {
    const toast = read('components/ui/Toast.tsx');
    expect(toast).toMatch(/z-60/);
  });

  it('Embedded checkout overlay sits above toast (z-70)', () => {
    const overlay = read('components/checkout/EmbeddedCheckoutPanel.tsx');
    expect(overlay).toMatch(/z-70/);
  });
});

// ── C. Viewport units ────────────────────────────────────────────────────────────────────────

describe('C. min-h-dvh replaces min-h-screen on primary surfaces', () => {
  it('ErrorBoundary uses min-h-dvh', () => {
    expect(read('components/ErrorBoundary.tsx')).toMatch(/min-h-dvh/);
    expect(read('components/ErrorBoundary.tsx')).not.toMatch(/min-h-screen/);
  });

  it('orders/[token].tsx uses min-h-dvh (replacing every min-h-screen)', () => {
    const page = read('pages/orders/[token].tsx');
    expect(page).toMatch(/min-h-dvh/);
    expect(page).not.toMatch(/min-h-screen/);
  });
});

// ── D. Focus styles ─────────────────────────────────────────────────────────────────────────

describe('D. PackCard has a :focus-visible ring', () => {
  const index = read('pages/index.tsx');

  it('PackCard link class string contains focus-visible:', () => {
    // The PackCard <Link> opens with a className that spans several lines. Pull the whole
    // className string out and assert focus-visible is present.
    //
    // The ring is now a `focusRing` constant shared by all three card variants instead of being
    // repeated inline, which is why the literal `focus-visible:` left the class string. The
    // assertion follows the indirection rather than treating it as a regression: a shared constant
    // is the stronger arrangement, because a fourth variant gets the ring by construction. Both
    // halves are asserted, so deleting the ring from the constant still fails here.
    const match = index.match(/<Link[\s\S]*?href=\{`\/pack\/\$\{pack\.id\}`\}[\s\S]*?className=\{cx\(([\s\S]*?)\}\)/);
    expect(match, 'PackCard link markup').not.toBeNull();
    expect(match![1], 'card link must carry the ring, inline or via focusRing').toMatch(
      /focus-visible:|focusRing/,
    );
    if (!/focus-visible:/.test(match![1])) {
      const ring = index.match(/const focusRing\s*=\s*([\s\S]*?);\n/);
      expect(ring, 'focusRing constant').not.toBeNull();
      expect(ring![1], 'the shared focusRing must define a visible ring').toMatch(/focus-visible:/);
    }
  });
});

// ── E. Loading skeletons ────────────────────────────────────────────────────────────────────

describe('E. Skeleton is wired to the three loading surfaces', () => {
  it('pages/orders/[token].tsx imports Skeleton', () => {
    const page = read('pages/orders/[token].tsx');
    expect(page).toMatch(/import[\s\S]*?Skeleton[\s\S]*?from\s+['"]@\/components\/ui['"]/);
  });

  it('AccountPanel OrdersTab uses Skeleton instead of bare "Loading" text', () => {
    const page = read('components/account/AccountPanel.tsx');
    expect(page).toMatch(/<Skeleton/);
  });

  it('pages/orders/success.tsx uses Skeleton during the polling "resolving" phase', () => {
    const page = read('pages/orders/success.tsx');
    expect(page).toMatch(/<Skeleton/);
  });
});

// ── F. Post-purchase page rebrand ────────────────────────────────────────────────────────────

describe('F. orders/[token].tsx uses design tokens, not raw gray utilities', () => {
  const page = read('pages/orders/[token].tsx');

  it('contains no text-gray-*, bg-gray-*, or border-gray-* classes', () => {
    expect(page).not.toMatch(/text-gray-/);
    expect(page).not.toMatch(/bg-gray-/);
    expect(page).not.toMatch(/border-gray-/);
  });

  it('wraps the page in MarketingLayout', () => {
    expect(page).toMatch(/import[\s\S]*?MarketingLayout/);
    expect(page).toMatch(/<MarketingLayout>/);
  });

  it('uses the design-system text-text / text-muted / border-border tokens', () => {
    expect(page).toMatch(/text-text/);
    expect(page).toMatch(/text-muted/);
    expect(page).toMatch(/border-border/);
  });
});

// ── G. Pack detail — fetch error + breadcrumbs ──────────────────────────────────────────────

describe('G1. pack/[id].tsx surfaces a UI error state on fetch failure', () => {
  const page = read('pages/pack/[id].tsx');

  it('imports ErrorState', () => {
    expect(page).toMatch(/import[\s\S]*?ErrorState[\s\S]*?from\s+['"]@\/components\/ui['"]/);
  });

  it('renders a "Try again" button in the error branch', () => {
    expect(page).toMatch(/Try again/);
  });

  it('keeps the existing console.error (it is the diagnostic channel)', () => {
    expect(page).toMatch(/console\.error\(['"]Error fetching pack details/);
  });
});

describe('G2. Breadcrumbs component exists and is rendered on the pack page', () => {
  it('src/components/ui/Breadcrumbs.tsx exists and exports a Breadcrumbs component', () => {
    const comp = read('components/ui/Breadcrumbs.tsx');
    expect(comp).toMatch(/export\s+function\s+Breadcrumbs/);
    expect(comp).toMatch(/<nav[^>]*aria-label="Breadcrumb"/);
  });

  it('the last crumb is non-clickable (aria-current="page")', () => {
    const comp = read('components/ui/Breadcrumbs.tsx');
    expect(comp).toMatch(/aria-current="page"/);
  });

  it('pack/[id].tsx renders Breadcrumbs with three items (Catalog, Browse by category, title)', () => {
    const page = read('pages/pack/[id].tsx');
    expect(page).toMatch(/<Breadcrumbs/);
    expect(page).toMatch(/Catalog/);
    expect(page).toMatch(/Browse by category/);
  });
});

// ── H. Basket feedback ───────────────────────────────────────────────────────────────────────

describe('H1. CartButton shows a just-added pulse on count increase', () => {
  const cart = read('components/cart/CartButton.tsx');

  it('badge class string includes animate-rise', () => {
    expect(cart).toMatch(/animate-rise/);
  });

  it('badge carries a data-just-added attribute that is removed after 600ms', () => {
    expect(cart).toMatch(/data-just-added/);
    expect(cart).toMatch(/600/);
  });
});

describe('H2. CartButton toasts on basket remove (symmetric with add)', () => {
  const cart = read('components/cart/CartButton.tsx');

  it('imports useToast', () => {
    expect(cart).toMatch(/useToast/);
  });

  it('calls toast() in the remove path', () => {
    expect(cart).toMatch(/cart\.remove[\s\S]*?toast\(/);
  });
});

describe('H3. AddToCartButton announces busy state to assistive tech', () => {
  const btn = read('components/cart/AddToCartButton.tsx');

  it('the hydration reserve has aria-busy="true"', () => {
    expect(btn).toMatch(/aria-busy\s*=\s*\{?true\}?/);
  });
});

// ── I. Polling progress affordance ──────────────────────────────────────────────────────────

describe('I. /orders/success shows a linear progress bar during polling', () => {
  const page = read('pages/orders/success.tsx');

  it('progress bar style width grows with the attempt counter', () => {
    expect(page).toMatch(/style=\{\{ width:/);
  });

  it('uses bg-border for the track and ink for the fill', () => {
    /*
     * The fill was `bg-primary` and is now `bg-text`. Both resolve to the same ink in v3
     * (`--primary: #171717`), so this is not a visual change -- it is a semantic one. `--primary`
     * means "the colour of the primary ACTION"; a progress bar is not an action, and pinning it
     * to the action token would drag the fill along the day the primary stops being ink.
     */
    expect(page, 'the track must be the hairline grey').toMatch(/bg-border/);
    expect(page, 'the fill must be ink, not the action colour').toMatch(/bg-text/);
  });
});