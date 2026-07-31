import { test, expect } from '@playwright/test';

/**
 * The kill log is the only page on the site whose job is to be checkable, so these assert the
 * two ways it could quietly stop being that.
 *
 * The page exists because the storefront asks £49 on the strength of "these survived six brutal
 * checks" and shows none of the brutality. Testimonials are the conventional answer and are not
 * available to us honestly — there are no reviews to quote, and on a storefront whose whole
 * pitch is source-or-die, a reader who catches one fabricated claim is right to disbelieve the
 * rest. So we publish the rejects instead, and the value is entirely in their being verifiable.
 */

const CITATION_HASH = /[([][0-9a-f]{16}[)\]]/;

test('the kill log renders rejections with the reason that killed each one', async ({ page }) => {
  await page.goto('/kill-log');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/killed/i);

  // Asserted as "more than a handful" rather than an exact count: the log regenerates from the
  // dossiers, so the number climbs every time the engine runs. A page that rendered its shell
  // and no entries would still look fine to a screenshot, which is the failure worth catching.
  const entries = page.locator('main li').filter({ hasText: /killed/i });
  expect(await entries.count()).toBeGreaterThan(5);
});

test('no kill reason shows an unresolved source hash', async ({ page }) => {
  // The engine cites passages by hash — "(b94f6135b2f6fc5d)". Rendered raw, that is noise at
  // best and looks like a fabricated citation at worst, which is precisely the impression this
  // page exists to defeat. make_kill_log.py resolves each hash to the URL the dossier recorded
  // and drops the ones it cannot resolve; this fails if that ever silently stops happening.
  await page.goto('/kill-log');
  const body = await page.locator('main').innerText();
  expect(body).not.toMatch(CITATION_HASH);
});

test('every cited source is a real outbound link, safely attributed', async ({ page }) => {
  await page.goto('/kill-log');
  const links = page.locator('main a[target="_blank"]');
  const count = await links.count();
  expect(count).toBeGreaterThan(0);

  for (let i = 0; i < count; i++) {
    const link = links.nth(i);
    expect(await link.getAttribute('href')).toMatch(/^https?:\/\//);
    // We are linking pages we do not control and did not endorse, off a page that calls their
    // subject dead. nofollow keeps that from reading as a recommendation to a crawler, and
    // noopener is the plain tabnabbing guard.
    expect(await link.getAttribute('rel')).toContain('noopener');
    expect(await link.getAttribute('rel')).toContain('nofollow');
  }
});

test('the home page sends a doubtful reader to the kill log', async ({ page }) => {
  // The "why you can trust this" band makes the claim. Before this link it offered no way to
  // check it, which is the gap the whole page addresses — so the link is part of the feature,
  // not decoration, and a redesign that drops it should fail here.
  await page.goto('/');
  const link = page.locator('a[href="/kill-log"]').first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/kill-log$/);
});
