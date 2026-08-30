import { test, expect } from '@playwright/test';

// Non-payment UI smoke: the rendered storefront pages must load and link together. The money
// path (the actual Stripe redirect) is proven server-side by prove_launch.sh; here we stop at
// the buy button so the smoke needs no card. Runs against a real Store.Api catalogue.

test('home page renders and lists packs', async ({ page }) => {
  const res = await page.goto('/');
  expect(res?.status()).toBeLessThan(400);
  await expect(page.locator('h1').first()).toBeVisible();
  // Every pack card links to its detail page.
  const cards = page.locator('a[href^="/pack/"]');
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(0);
});

test('pack detail renders with a buy button', async ({ page }) => {
  await page.goto('/');
  const firstCard = page.locator('a[href^="/pack/"]').first();
  const href = await firstCard.getAttribute('href');
  await firstCard.click();
  await expect(page).toHaveURL(new RegExp('/pack/'));
  await expect(page.locator('h1').first()).toBeVisible();
  // The buy control renders ("Buy this pack" + the price in a separate mono span, brand v3). The
  // accessible name still carries both, which is why matching on the words alone is enough here.
  // The handler/redirect is proven
  // server-side by prove_launch.sh, so the smoke stops here and needs no card.
  await expect(page.getByRole('button', { name: /buy this pack/i }).first()).toBeVisible();
  expect(href).toMatch(/^\/pack\//);
});

test('order success page renders', async ({ page }) => {
  // Pull a real pack id so the success page has something to reference.
  await page.goto('/');
  const href = await page.locator('a[href^="/pack/"]').first().getAttribute('href');
  const id = (href || '/pack/x').split('/pack/')[1];
  const res = await page.goto(`/orders/success?pack=${id}`);
  expect(res?.status()).toBeLessThan(400);
  await expect(page.locator('h1').first()).toBeVisible();
});

test('unknown route returns the 404 page', async ({ page }) => {
  const res = await page.goto('/this-route-does-not-exist-zzz');
  expect(res?.status()).toBe(404);
  await expect(page.getByText(/404|not found/i).first()).toBeVisible();
});

/*
 * The basket drawer must paint over the page, not through it.
 *
 * REPRODUCED 2026-08-06 at 390x844 with three packs in the basket, before the fix: the drawer's
 * panel measured 390x64 -- the height of the site header -- while its content was 285px tall. Only
 * the title row painted `bg-surface`; the line items, the £147 total and the Pay button rendered
 * outside the panel's painted box, over live page copy, illegible. Checkout was effectively
 * blocked: the CTA was visible but the totals beside it could not be read or trusted.
 *
 * The cause was not a missing background. `<CartButton>` renders the Modal inside `<header class="
 * sticky ... backdrop-blur-md">`, and an ancestor carrying a `backdrop-filter` becomes the
 * containing block for `position: fixed` descendants, so `fixed inset-0` resolved against the 65px
 * header instead of the viewport. Same ancestor is `z-30` and a stacking context, so the drawer's
 * `z-50` was scoped inside it too. `Modal` now portals to <body>.
 *
 * This is deliberately a MEASUREMENT and not a source-text assertion: the defect is invisible in
 * Modal.tsx (whose classes were correct throughout) and visible only in the layout it produces
 * under a particular ancestor. A future header that adds `transform` or `filter` would reintroduce
 * it in exactly the same way, and only a rendered check would catch that.
 *
 * 390x844 is the iPhone 13/14 logical viewport, which is where it was reported.
 */
test.describe('basket drawer', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('opens as a full-height opaque panel with no page content showing through', async ({
    page,
  }) => {
    // Seeded rather than clicked through: `parseStoredCart` validates shape only, so the drawer
    // needs no API call and no real pack. The bug is in the drawer's box, not its contents.
    await page.addInitScript(() => {
      window.localStorage.setItem(
        'mumchimp.cart.v1',
        JSON.stringify([
          { id: 'e2e-basket-1', title: 'A pack with a fairly long title so it wraps', price: '£49' },
          { id: 'e2e-basket-2', title: 'Second pack in the basket', price: '£49' },
          { id: 'e2e-basket-3', title: 'Third pack in the basket', price: '£49' },
        ]),
      );
    });
    await page.goto('/');
    await page.getByRole('button', { name: /^Basket,/ }).click();

    const panel = page.locator('[role="dialog"]');
    await expect(panel).toBeVisible();

    // 1. The panel fills the viewport height. 64px (the header) is the exact failure. Compared
    //    with a 1px tolerance because the measured height is 843.99998 -- a sub-pixel rounding,
    //    not a layout fact, and pinning 844 exactly would make this fail on a device-pixel-ratio
    //    change that nobody would consider a regression.
    const box = (await panel.boundingBox())!;
    expect(box.height, 'the drawer must be full-height, not the height of the header').toBeCloseTo(
      844,
      0,
    );

    // 2. Nothing from the page paints ABOVE the overlay in the middle of the drawer's body.
    //    Measured with elementsFromPoint rather than by reading background-color, because the
    //    panel's own background was already correct while the bug was live -- what was wrong is
    //    what sat above it.
    //
    //    Note the shape of the assertion. `elementsFromPoint` hit-tests the whole depth of the
    //    document, so <main> is in the list either way and "the page is not in the stack" would be
    //    a test that can never pass. What distinguishes the two states is ORDER: with the drawer
    //    trapped in the header, the page's <section>/<main> were returned ABOVE the overlay root
    //    and therefore painted over the basket contents. Everything above the overlay root must
    //    belong to the overlay.
    const strangers = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]')!;
      const overlay = document.querySelector('[role="presentation"]')!;
      const body = dialog.children[1].getBoundingClientRect();
      const stack = document.elementsFromPoint(
        body.x + body.width / 2,
        body.y + body.height / 2,
      );
      return stack
        .slice(0, stack.indexOf(overlay))
        .filter((el) => !overlay.contains(el))
        .map((el) => `${el.tagName}.${typeof el.className === 'string' ? el.className.slice(0, 40) : ''}`);
    });
    expect(strangers, 'nothing from the page may paint above the open drawer').toEqual([]);

    // 3. The money is legible: totals and CTA inside the panel's box.
    for (const target of [page.getByText('£147'), page.getByRole('button', { name: /Pay once/i })]) {
      const t = (await target.first().boundingBox())!;
      expect(t.y + t.height, 'the totals row must sit inside the drawer').toBeLessThanOrEqual(
        box.y + box.height,
      );
    }
  });
});

/**
 * NO HEADING MAY RENDER AS BODY TEXT.
 *
 * Tailwind's preflight sets every heading to `font-size:inherit;font-weight:inherit`, and the
 * shipped bundle styles headings per container -- `.htile h3`, `.band h3`, `.checkrow h5`,
 * `.klrow h4`. Between the two there is a silent hole: a heading at a level no rule names keeps
 * the body's 400 and 16px, looks like a paragraph, and fails nothing. Measured on the built home
 * page 2026-08-30, six headings were in it, including the three tiles at the top of the first
 * shelf a visitor sees. Nobody could point at what was wrong; it just read cheap.
 *
 * `globals.css` now carries a weight floor for h1-h6 in `@layer base`, which is the fix. This is
 * the guard, and it grades the rendered page rather than the stylesheet because the defect lives
 * in the gap between them. The threshold is the floor's own 560 minus a margin: anything at 500
 * or below is the reset's value, which is the exact signature of a heading no rule reached.
 */
test.describe('typography', () => {
  const ROUTES = ['/', '/ideas', '/kill-log', '/how-it-works', '/pricing'];

  for (const route of ROUTES) {
    test(`every visible heading on ${route} is set as a heading`, async ({ page }) => {
      await page.goto(route);
      const unstyled = await page.$$eval('h1,h2,h3,h4,h5,h6', (els) =>
        els
          .filter((el) => (el as HTMLElement).offsetParent !== null)
          .map((el) => {
            const s = getComputedStyle(el);
            return {
              tag: el.tagName,
              weight: parseInt(s.fontWeight, 10),
              size: s.fontSize,
              text: (el.textContent || '').trim().slice(0, 60),
            };
          })
          .filter((h) => h.weight <= 500),
      );
      expect(
        unstyled,
        'a heading rendering at the body weight is a heading no stylesheet rule reached',
      ).toEqual([]);
    });
  }
});

/*
 * THE DRAWING WINS WHERE IT HAS AN OPINION.
 *
 * `noUtilityOverpaint.test.ts` reads the source and can only see what one className string holds.
 * Twice on 2026-08-30 that was not enough. `textLinkClass()` emits the bundle's `tlink` and the
 * call site passed `font-medium` separately, so every inline link on the site rendered at weight
 * 500 against the 550 `mumchimp.css:27` draws -- measured with getComputedStyle on the built page
 * at :3177, on /ideas, /about and /faq. And `.sigcard .key`, drawn once at 12px mono, rendered at
 * 14px on /how-it-works because that one call site also wore `text-meta`.
 *
 * These two assertions are the rendered-DOM angle on the same rule: whatever the source looks
 * like, and wherever a future override arrives from, the page has to show the drawn value.
 */
test.describe('the bundle is not overpainted', () => {
  for (const route of ['/ideas', '/about', '/faq']) {
    test(`inline links on ${route} carry the drawn weight`, async ({ page }) => {
      await page.goto(route);
      const weights = await page.$$eval('.tlink', (els) => [
        ...new Set(els.map((el) => getComputedStyle(el).fontWeight)),
      ]);
      expect(weights.length, `no .tlink on ${route} to measure`).toBeGreaterThan(0);
      expect(weights, 'mumchimp.css:27 draws .tlink at font-weight 550').toEqual(['550']);
    });
  }

  test('the signature card key strip is drawn at the bundle size', async ({ page }) => {
    await page.goto('/how-it-works');
    const sizes = await page.$$eval('.sigcard .key', (els) => [
      ...new Set(els.map((el) => getComputedStyle(el).fontSize)),
    ]);
    expect(sizes.length, 'no .sigcard .key to measure').toBeGreaterThan(0);
    expect(sizes, 'mumchimp.css:174 draws .sigcard .key at 12px').toEqual(['12px']);
  });
});
