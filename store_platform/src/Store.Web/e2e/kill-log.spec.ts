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
 * The log renders one <li id={slug} class="klrow"> per record: a title button carrying
 * `aria-expanded`, a two-line excerpt, a mono meta line reading "<date> · <n> sources", a side
 * column holding the killed chip and the gate label, and an argument panel that mounts only once
 * the row is expanded. That is a real improvement for 400 records and a trap for a test — an
 * assertion made against the page as loaded now sees zero arguments and zero links, and passes or
 * fails for reasons that have nothing to do with whether the evidence is there.
 *
 * So each test below expands what it intends to assert on. A test that reads only the collapsed
 * page is vacuous here, which is exactly how the previous version of this file went green while
 * checking nothing.
 *
 * WHY THIS BLOCK IS DATED. These selectors said <tbody>/<tr>/<td> until 2026-08-20. The page was
 * a table when they were written; #377 (2026-08-19) rebuilt it as a list, and nothing failed in a
 * way anyone read — `main tbody[id]` simply matched nothing, so `records().count()` returned 0 and
 * all three record tests failed the same "> 5" assertion for 36 hours on the live smoke. A count
 * of zero is the one result a structural selector produces for BOTH "the page is empty" and "the
 * selector is stale", which is why the argument panel now carries `data-testid="kill-argument"`:
 * a hook the page states on purpose cannot rot silently behind a redesign that keeps the feature.
 */

/** The one-<li>-per-record group. `[id]` is the per-kill permalink slug and `klrow` is the
 *  drawing's own class for a record, so this cannot match the filter bar or the chart above. */
const records = (page: import('@playwright/test').Page) => page.locator('main li.klrow[id]');

/**
 * The expanded argument panel.
 *
 * TWO SELECTORS ON PURPOSE, and the reason is the whole shape of this suite: it grades
 * https://mumchimp.com (playwright.config.ts:5), which is the PREVIOUSLY deployed build, not the
 * branch under review. A test that names only the markup in the branch is red from the moment it
 * merges until the web image ships, and a test that names only the deployed markup is red from
 * the moment it does. So this accepts both sides of a deploy: `data-testid` is the hook the page
 * now states on purpose, `.bg-surface3` is the styling class the currently-live build carries.
 * Drop the second one once a build carrying the testid is live.
 */
const detailPanel = (record: import('@playwright/test').Locator) =>
  record.locator('[data-testid="kill-argument"], div.bg-surface3').first();

/** The gate that killed a record, as rendered in the row's side column. */
const gateOf = (record: import('@playwright/test').Locator) =>
  record.locator('.side .mono').first();

/** The source COUNT, read off the mono meta line, which reads "20 Aug 2026 · 3 sources".
 *  Parsed rather than positional: the line is one string, and the date in front of it is
 *  formatted for a reader, so an index into it would be an index into prose. */
async function sourceCount(record: import('@playwright/test').Locator): Promise<number> {
  const meta = (await record.locator('p.m.num').first().innerText()).trim();
  const m = meta.match(/(\d+)\s+sources?\b/);
  return m ? Number(m[1]) : 0;
}

/** Expand the first record whose source COUNT column is non-zero, and hand back its detail row.
 *  Chosen by reading the count off the summary row rather than by index: which kills carry a
 *  resolvable source changes every time the engine runs, so a hardcoded row would rot. */
async function openFirstSourcedRecord(page: import('@playwright/test').Page) {
  const all = records(page);
  const total = await all.count();
  expect(total).toBeGreaterThan(5);

  for (let i = 0; i < total; i++) {
    const record = all.nth(i);
    if ((await sourceCount(record)) > 0) {
      await record.locator('button[aria-expanded]').first().click();
      const detail = detailPanel(record);
      await expect(detail).toBeVisible();
      // The row is visible the instant it is expanded, but the argument inside it comes from
      // /api/kill-log-detail, one ~400KB fetch for the whole page (`kill-log.tsx:495`). Until it
      // lands the row renders the single line "Loading the argument…", which is 21 characters and
      // carries no links. A caller that read the row here therefore saw a length of 21 against an
      // expectation of >40, and a link count of 0. That is what failed this suite on live for six
      // consecutive deploys from #227 onward. Waiting for the placeholder to clear is the whole
      // fix. A fetch that FAILS renders different copy ("This argument could not be loaded.
      // Reload the page to try again.", 64 characters), so this wait cannot hide a real outage.
      // It only removes the race.
      await expect(detail).not.toContainText('Loading the argument');
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

  // The count alone is no longer enough. Every row renders the gate that killed it in its side
  // column, so 400 ideas with an empty gate label would satisfy a bare count while losing the
  // entire point of the page.
  for (let i = 0; i < 5; i++) {
    await expect(gateOf(all.nth(i))).not.toBeEmpty();
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
