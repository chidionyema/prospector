/**
 * DOES THE CONTROL PLANE ACTUALLY WORK?
 *
 * Founder, 2026-08-21: "we need to actually ui test the portal end to end to prove things work,
 * that is like a second class citizen while it is the control plane, the whole platform."
 *
 * He is right, and the gap was mechanical rather than a matter of taste. Before this file the
 * console's whole end-to-end suite asked two questions — does axe find a violation, and does the
 * page fit on a phone — and it asked them through a wait that ACCEPTS FAILURE AS A PASS:
 *
 *     text=/read .* ago|could not|is not set|Sign in/i        session.ts:settled, mobile.spec.ts:44
 *
 * A console whose every panel rendered "could not read" satisfied that locator on every screen,
 * scrolled sideways nowhere, and went green. Layout was proven; function was not tested at all.
 *
 * These tests assert the opposite thing: that the portal DID the job. Each one is a path the
 * founder actually takes, and each fails if the control plane stops working even though the page
 * still renders beautifully.
 *
 * They run in their own `journeys` project at a desktop viewport, because these are questions
 * about behaviour, not about width — the phone projects would run the same journey twice and
 * prove nothing new the second time.
 */
import { expect, test } from '@playwright/test';

import { NOT_WALKED, SCREENS, allScreens, signIn } from './session';

/** The document these journeys read, share and revoke. Tracked, readable, and not runtime state. */
const DOC = 'docs/LINKS.md';

/**
 * Open the share panel if it is closed.
 *
 * `ShareDoc` renders the compact "Share this doc" button ONLY while its panel is closed, and the
 * panel stays open after a mint. Waiting unconditionally for that button waits for something the
 * component has stopped rendering — measured 2026-08-21, a 240s timeout on a portal that was
 * working correctly.
 */
async function openSharePanel(page: import('@playwright/test').Page): Promise<void> {
  const opener = page.getByRole('button', { name: /Share this doc|Change who can read it/ });
  if (await opener.count()) {
    await opener.first().click();
    return;
  }
  // Finding no opener has two very different causes and they must not report the same way.
  // Either the panel is ALREADY open — ShareDoc stops rendering the opener then — or ShareDoc is
  // not on the page at all, because no document was ever opened. In the second case every step
  // after this waits on a control that cannot appear, and the run dies 240s later pointing at the
  // wrong line. Measured 2026-08-21: exactly that, a timeout on `getByLabel(/Who is it for/i)`
  // that said nothing about the document never having opened.
  await expect(
    page
      .getByRole('button', { name: 'Turn it off' })
      .or(page.getByLabel(/Who is it for/i))
      .first(),
    'no share panel on this page: the opener is absent and so are the controls it opens, which ' +
      'means the document was never opened, not that sharing failed',
  ).toBeVisible({ timeout: 30_000 });
}

/** Revoke the document's live link if it has one, so the journey starts from a known state. */
async function makePrivate(page: import('@playwright/test').Page): Promise<void> {
  const off = page.getByRole('button', { name: 'Turn it off' });
  if (!(await off.count())) return;
  await off.first().click();
  const ack = page.locator('input[type="checkbox"]');
  if (await ack.count()) await ack.first().check();
  await page.getByRole('button', { name: 'Yes, make it private' }).click();
  await expect(page.getByText('Private').first()).toBeVisible({ timeout: 60_000 });
}

test.describe('the control plane', () => {
  /**
   * The screen list cannot silently shrink.
   *
   * Measured 2026-08-21: 25 screens existed, `SCREENS` named 11, and the 14 missing included
   * /docs, /share, /money and /revenue. Nothing failed, because a short list is a list that
   * passes faster. This compares the hand-written list against the pages directory itself.
   */
  test('every screen is walked, or is named here with a reason', () => {
    const known = new Set<string>([...SCREENS, ...Object.keys(NOT_WALKED)]);
    const missing = allScreens().filter((p) => !known.has(p));
    expect(
      missing,
      `these screens exist and no e2e walk visits them — add them to SCREENS in e2e/session.ts, ` +
        `or to NOT_WALKED with the reason:\n  ${missing.join('\n  ')}`,
    ).toEqual([]);

    const gone = Object.keys(NOT_WALKED).filter((p) => !allScreens().includes(p));
    expect(gone, `NOT_WALKED names screens that no longer exist — delete them: ${gone}`).toEqual([]);
  });

  /**
   * Every screen READ something.
   *
   * This is the assertion the old wait could not make. `AsOf` renders "read <n> ago" only when a
   * view returned data, so requiring it — and nothing else — is the difference between "the page
   * rendered" and "the portal worked".
   */
  test('every screen reads real data, not an excuse', async ({ page }) => {
    test.setTimeout(300_000);
    await signIn(page);

    const broken: string[] = [];
    for (const path of SCREENS) {
      await page.goto(path);
      const read = page.locator('text=/read .* ago/i').first();
      try {
        await read.waitFor({ state: 'visible', timeout: 30_000 });
      } catch {
        // Capture WHY, not just that it failed. A screen that says "could not read X" is a
        // different defect from one that rendered nothing at all, and the two get fixed by
        // different people.
        const said = (await page.locator('main').first().innerText().catch(() => '')) || '(blank)';
        broken.push(`${path}: ${said.replace(/\s+/g, ' ').slice(0, 160)}`);
      }
    }
    expect(broken, `screens that never read anything:\n  ${broken.join('\n  ')}`).toEqual([]);
  });

  /**
   * The founder's words about the old docs page: "i can see a list but cant read it, loads slow,
   * no way to search and filter etc or categorise". So: it lists, it filters, and it opens.
   */
  test('documents can be searched, filtered and read', async ({ page }) => {
    test.setTimeout(180_000);
    await signIn(page);
    await page.goto('/docs');

    const search = page.getByLabel('Search documents');
    await search.waitFor({ state: 'visible', timeout: 60_000 });

    // The placeholder carries the total, so it is the count the page itself believes.
    const placeholder = (await search.getAttribute('placeholder')) ?? '';
    const total = Number(placeholder.match(/Search (\d+) documents/)?.[1] ?? 0);
    expect(total, 'the index is empty, so there is nothing to miss out').toBeGreaterThan(100);

    // Filtering must actually narrow the list, and say by how much.
    await search.fill('LINKS');
    const shown = page.locator('text=/\\d+ of \\d+ shown/');
    await expect(shown).toBeVisible({ timeout: 15_000 });
    const matched = Number(((await shown.innerText()) || '').match(/^(\d+) of/)?.[1] ?? -1);
    expect(matched, 'a search that matches nothing is a search that does not work').toBeGreaterThan(0);
    expect(matched, 'the filter did not narrow anything').toBeLessThan(total);

    // And the document opens and renders its text — the half the founder said was missing.
    await page.locator('li', { hasText: DOC }).getByRole('button').first().click();
    await expect(page.getByText('Share this doc')).toBeVisible({ timeout: 60_000 });
    await expect(page.locator('text=/Every shareable link, in one place/i').first()).toBeVisible({
      timeout: 30_000,
    });
  });

  /**
   * "i also want a page where i ccan view all sanples generated so far ... i cant preview what
   * else was produced". The gallery is parsed out of docs/LINKS.md, so this fails both when the
   * page breaks and when the index it reads stops being parseable.
   */
  test('the reports gallery groups every published page', async ({ page }) => {
    test.setTimeout(180_000);
    await signIn(page);
    await page.goto('/reports');

    const links = page.locator('a[href^="https://claude.ai/code/artifact/"]');
    await expect(links.first()).toBeVisible({ timeout: 60_000 });
    expect(await links.count(), 'the gallery lost the published pages').toBeGreaterThan(40);

    // Grouped, not one flat wall. The section headings come from the ## headings in LINKS.md.
    const headings = page.locator('h2');
    expect(await headings.count(), 'nothing is grouped').toBeGreaterThan(3);
  });

  /**
   * THE ONE THE FOUNDER ASKED FOR BY NAME: "i need to be aable to share any docuent inthis repo
   * as a http link and control if public or not".
   *
   * End to end means end to end: the console mints, a browser holding NO SESSION reads the file
   * through that link, the console revokes, and the same sessionless browser is refused. Every
   * layer is real — UI, gateway, Python, token store, and the public route.
   */
  test('a document can be made public, read without a login, and made private again', async ({
    page,
    browser,
  }) => {
    test.setTimeout(240_000);
    await signIn(page);
    await page.goto('/docs');

    const search = page.getByLabel('Search documents');
    await search.waitFor({ state: 'visible', timeout: 60_000 });
    await search.fill(DOC);
    await page.locator('li', { hasText: DOC }).getByRole('button').first().click();

    // The row is clicked; that is not the same as the document being open. Assert it here so a
    // search that matched nothing is reported as a search that matched nothing.
    await expect(
      page.getByRole('button', { name: /Share this doc|Change who can read it|Turn it off/ }).first(),
      `clicking the row for ${DOC} did not open a document that can be shared — check that the ` +
        'search matched it at all',
    ).toBeVisible({ timeout: 60_000 });

    // Mint. `Confirm` previews first and applies second — that two-step is the safety rail, so
    // the test drives it rather than routing around it.
    await openSharePanel(page);
    // A live token from an earlier run would show the revoke controls instead of the mint form,
    // so this journey would fail on its second run for a reason that is not a defect. Start from
    // private, whatever the last run left behind.
    await makePrivate(page);
    await page.getByLabel(/Who is it for/i).fill('e2e: proving the share rail end to end');
    await page.getByRole('button', { name: 'Check what this covers' }).click();
    await page.getByRole('button', { name: 'Mint the link' }).click();

    await expect(page.getByText(/Copy this now/i)).toBeVisible({ timeout: 60_000 });
    const url = ((await page.locator('.font-mono').filter({ hasText: /\/s\// }).first().innerText()) ?? '').trim();
    expect(url, 'the console minted a link it did not show').toMatch(/\/s\/[A-Za-z0-9_-]+$/);

    // A SEPARATE browser context: no cookie, no session, exactly what the recipient has.
    const stranger = await browser.newContext();
    try {
      const theirs = await stranger.newPage();
      const res = await theirs.goto(url, { waitUntil: 'domcontentloaded' });
      expect(res?.status(), 'the minted link did not serve').toBeLessThan(400);
      await expect(
        theirs.locator('text=/Every shareable link, in one place/i').first(),
        'the link opened but the document was not in it',
      ).toBeVisible({ timeout: 30_000 });

      // Now turn it off, and prove the stranger loses it.
      await page.bringToFront();
      await expect(page.getByText('Public').first()).toBeVisible({ timeout: 30_000 });
      await openSharePanel(page);
      await makePrivate(page);
      await expect(page.getByText('Private').first()).toBeVisible({ timeout: 60_000 });

      await theirs.goto(url, { waitUntil: 'domcontentloaded' });
      await expect(
        theirs.locator('text=/Every shareable link, in one place/i').first(),
        'REVOKED AND STILL READABLE — the off switch does not turn it off',
      ).toHaveCount(0);
    } finally {
      await stranger.close();
    }
  });
});
