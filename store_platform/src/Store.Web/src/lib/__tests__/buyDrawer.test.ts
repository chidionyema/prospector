import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The Buy drawer lets someone spend £49 without opening the pack page. That is only defensible
 * while the drawer itself carries what the pack page would have told them first, so these tests
 * hold it to that, the doc comment saying so is not a mechanism.
 *
 * Source-reading rather than DOM-rendering because this repo's web tests are all source-level
 * (there is no jsdom/RTL setup here), and because the properties below are structural: which
 * module owns the buy path, and which promises appear at all.
 */
const SRC = join(__dirname, '..', '..');
const drawer = readFileSync(join(SRC, 'components', 'checkout', 'BuyDrawer.tsx'), 'utf8');
const packPage = readFileSync(join(SRC, 'pages', 'pack', '[id].tsx'), 'utf8');
const hook = readFileSync(join(SRC, 'lib', 'checkout', 'usePackCheckout.ts'), 'utf8');

describe('the drawer carries the pre-contract set', () => {
  it('lists the deliverables from the one shared source, never its own copy', () => {
    // PACK_DOCUMENTS is already drift-tested against the engine's BUNDLE_FILES
    // (packContents.test.ts), so reusing it is what stops a third surface promising a ninth file.
    expect(drawer).toContain("from '@/components/marketing/PackContents'");
    expect(drawer).toContain('PACK_DOCUMENTS.map');
  });

  it('shows the catalogue price string rather than recomputing one', () => {
    expect(drawer).toContain('formatPrice(pack.price)');
    // A hand-built "£" + number in a buy surface is how a drawer ends up disagreeing with what
    // the server will actually charge.
    expect(drawer).not.toMatch(/['"`]£\s*\d/);
  });

  it('states the cancellation right and links the refund policy', () => {
    expect(drawer).toContain('14 day money back');
    expect(drawer).toContain('href="/refund"');
  });

  it('keeps the honesty note that a pack is research, not a promise', () => {
    // Was `toContain('evidence-backed research, not a promise of business success')`. The
    // sentence moved to `lib/disclaimer.ts` because four surfaces had drifted into three
    // wordings; this now checks the drawer still RENDERS it, which is what the test was ever
    // about. `disclaimerSaidOnce.test.ts` owns the wording itself.
    expect(drawer).toContain("from '@/lib/disclaimer'");
    expect(drawer).toContain('{PACK_DISCLAIMER}');
  });

  it('always offers the full evidence one click away', () => {
    // The drawer is a shortcut through the shelf, never a shortcut past the evidence.
    expect(drawer).toContain('`/pack/${pack.id}`');
  });
});

describe('the buy path is shared, not copied', () => {
  it('both surfaces run usePackCheckout', () => {
    expect(drawer).toContain("from '@/lib/checkout/usePackCheckout'");
    expect(packPage).toContain("from '@/lib/checkout/usePackCheckout'");
  });

  it('neither surface re-implements the Stripe routing decision', () => {
    // resolveStripeCheckout owns "embedded is preferred but never required", including the throw
    // case. A second call site is a second place for that guarantee to rot.
    for (const [name, source] of [['BuyDrawer', drawer], ['pack page', packPage]] as const) {
      expect(source, `${name} must reach Stripe only through the hook`).not.toContain(
        'resolveStripeCheckout',
      );
      expect(source, `${name} must not create sessions directly`).not.toContain(
        'createEmbeddedCheckout',
      );
    }
    expect(hook).toContain('resolveStripeCheckout');
  });

  it('gates the buy button on a provisioned price, never on the publishable key', () => {
    // The regression this pins cost every buy button in production: gating on stripeConfigured
    // hid the whole shelf's checkout when the key was missing from the web build args.
    expect(hook).toContain('price_stub');
    expect(hook).toMatch(/canCheckout[\s\S]{0,200}hasProvisionedPrice/);
    // stripeConfigured may still be consulted for the embedded PREFERENCE, it must simply not
    // be what decides whether a sale is possible.
    const canCheckoutBlock = hook.slice(hook.indexOf('const canCheckout'));
    expect(canCheckoutBlock).not.toContain('stripeConfigured');
  });

  it('keeps the three-state overlay so a closed overlay cannot reopen itself', () => {
    // undefined = undecided (a pre-opened session may win), null = closed, string = open.
    // Collapsing this to a plain nullable is what reintroduces the reopen bug.
    expect(hook).toContain('string | null | undefined');
  });
});

describe('the shelf keeps opening the pack as its primary action', () => {
  const index = readFileSync(join(SRC, 'pages', 'index.tsx'), 'utf8');

  it('still leads with opening the pack, not with buying it', () => {
    /*
     * This pinned the literal copy "View vetted blueprint" on `SpotlightCard`. That component was
     * deleted in brand v3 (it was a second product card with its own rules sitting above the grid
     * of the first kind, showing the pack that was already the first card in it), so the literal
     * cannot be asserted. The CLAIM it stood for is what matters and still holds: the shelf's
     * primary action opens the pack page, and the drawer is reached from there -- a card that
     * checks out in place sells before the evidence has been seen.
     */
    expect(index, 'the card must link to the pack page').toMatch(/href=\{`\/pack\/\$\{pack\.id\}`\}/);
    expect(index, 'the card must label that action').toContain('View pack');
    expect(index, 'the shelf card must not open checkout directly').not.toMatch(
      /<PackBuyButton|openDrawer\(/,
    );
  });

  it('mounts exactly one drawer for the whole page', () => {
    // Matches the opening tag with or without props: the provider now takes the visitor's
    // currency, and a literal `<BuyDrawerProvider>` would have made adding any prop look like
    // "the drawer is gone" rather than "the assertion was too narrow".
    expect(index.match(/<BuyDrawerProvider[\s>]/g)).toHaveLength(1);
  });
});
