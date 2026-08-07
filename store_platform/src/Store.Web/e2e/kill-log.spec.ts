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

/**
 * These selectors track a redesign, and the redesign is why they are written this way.
 *
 * The log used to be a flat <li> list with every argument and every source link rendered up
 * front. It is now a table with one <tbody id={slug}> per record: a summary row (idea, the gate
 * that killed it, a source COUNT, the date) and a detail row that mounts only once the row is
 * expanded. That is a real improvement for 400 records and a trap for a test — an assertion made
 * against the page as loaded now sees zero arguments and zero links, and passes or fails for
 * reasons that have nothing to do with whether the evidence is there.
 *
 * So each test below expands what it intends to assert on. A test that reads only the collapsed
 * page is vacuous here, which is exactly how the previous version of this file went green while
 * checking nothing.
 */

/** The one-<tbody>-per-record group. `[id]` is the per-kill permalink slug, so this cannot
 *  accidentally match the <thead> or a layout table elsewhere on the page. */
const records = (page: import('@playwright/test').Page) => page.locator('main tbody[id]');

/** Expand the first record whose source COUNT column is non-zero, and hand back its detail row.
 *  Chosen by reading the count off the summary row rather than by index: which kills carry a
 *  resolvable source changes every time the engine runs, so a hardcoded row would rot. */
async function openFirstSourcedRecord(page: import('@playwright/test').Page) {
  const all = records(page);
  const total = await all.count();
  expect(total).toBeGreaterThan(5);

  for (let i = 0; i < total; i++) {
    const record = all.nth(i);
    const sources = (await record.locator('tr').first().locator('td').nth(2).innerText()).trim();
    if (Number(sources) > 0) {
      await record.locator('button[aria-expanded]').first().click();
      const detail = record.locator('tr').nth(1);
      await expect(detail).toBeVisible();
      return detail;
    }
  }
  throw new Error('no kill on the page carries a published source');
}

test('the kill log renders rejections with the reason that killed each one', async ({ page }) => {
  await page.goto('/kill-log');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/killed/i);

  // Asserted as "more than a handful" rather than an exact count: the log regenerates from the
  // dossiers, so the number climbs every time the engine runs. A page that rendered its shell
  // and no entries would still look fine to a screenshot, which is the failure worth catching.
  const all = records(page);
  expect(await all.count()).toBeGreaterThan(5);

  // The count alone is no longer enough. Every row now renders the gate that killed it in its
  // own cell, so a table of 400 ideas with an empty "Killed by" column would satisfy a bare
  // count while losing the entire point of the page.
  for (let i = 0; i < 5; i++) {
    const killedBy = all.nth(i).locator('tr').first().locator('td').nth(1);
    await expect(killedBy).not.toBeEmpty();
  }

  // And the argument itself, which only exists once a row is open.
  const detail = await openFirstSourcedRecord(page);
  expect((await detail.innerText()).trim().length).toBeGreaterThan(40);
});

test('no kill reason shows an unresolved source hash', async ({ page }) => {
  // The engine cites passages by hash — "(b94f6135b2f6fc5d)". Rendered raw, that is noise at
  // best and looks like a fabricated citation at worst, which is precisely the impression this
  // page exists to defeat. make_kill_log.py resolves each hash to the URL the dossier recorded
  // and drops the ones it cannot resolve; this fails if that ever silently stops happening.
  await page.goto('/kill-log');
  expect(await page.locator('main').innerText()).not.toMatch(CITATION_HASH);

  // The reasons and the citations live in the detail row, so the collapsed page cannot see the
  // text this test is actually about — checking only the summary table would be checking the
  // one place a raw hash can never appear.
  const detail = await openFirstSourcedRecord(page);
  expect(await detail.innerText()).not.toMatch(CITATION_HASH);
});

test('every cited source is a real outbound link, safely attributed', async ({ page }) => {
  await page.goto('/kill-log');
  const detail = await openFirstSourcedRecord(page);

  const links = detail.locator('a[target="_blank"]');
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
