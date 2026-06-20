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
  // The buy control renders ("Get this pack for £XX"). The handler/redirect is proven
  // server-side by prove_launch.sh, so the smoke stops here and needs no card.
  await expect(page.getByRole('button', { name: /get this pack/i }).first()).toBeVisible();
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
