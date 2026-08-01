import { test, expect } from '@playwright/test';

/**
 * Structured data has to be asserted against the served page, not just the object that builds
 * it. `productJsonLd` is unit-tested, but a crawler reads what reaches the HTML — and the head
 * is exactly where a change silently drops something without any visible symptom.
 */

test('a pack page carries Product structured data matching its visible price', async ({ page }) => {
  await page.goto('/');
  const href = await page.locator('a[href^="/pack/"]').first().getAttribute('href');
  expect(href).toBeTruthy();
  await page.goto(href!);

  const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
  const product = blocks.map((b) => JSON.parse(b)).find((d) => d['@type'] === 'Product');
  expect(product, 'no Product ld+json on the pack page').toBeTruthy();

  expect(product.name).toBeTruthy();
  expect(product.sku).toBeTruthy();

  // The offer must agree with the price the buyer can see. Structured data that advertises a
  // number the checkout does not charge is a consumer-law problem, and Google drops schema
  // that contradicts the page, so a mismatch is both illegal and pointless.
  const visiblePrice = await page.locator('body').innerText();
  expect(visiblePrice).toContain(`£${product.offers.price.replace(/\.00$/, '')}`);
  expect(product.offers.priceCurrency).toBe('GBP');
});

test('no page claims a rating or a review it does not have', async ({ page }) => {
  // We have no reviews. A fabricated one is an offence under the DMCCA 2024 fake-review
  // provisions. This asserts it across the surfaces a crawler actually reads.
  for (const path of ['/', '/sample', '/kill-log']) {
    await page.goto(path);
    const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
    for (const block of blocks) {
      expect(block, `${path} emits rating/review schema`).not.toMatch(/aggregateRating|"review"/i);
    }
  }
});

test('the sitemap lists the kill log', async ({ request }) => {
  // The page is only a discovery asset if a crawler is told it exists.
  const res = await request.get('/sitemap.xml');
  expect(res.ok()).toBeTruthy();
  expect(await res.text()).toContain('/kill-log');
});
