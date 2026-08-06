import { test, expect } from '@playwright/test';

/**
 * Discovery UX smoke (spec `specs/discovery-ux-2026-07-30.md`).
 *
 * These run against a REAL catalogue, which is why almost nothing here asserts a number. The
 * catalogue grows on every PASS and packs are only tagged once the engine can justify a value,
 * so a test that expects "15 packs" or "the effort filter exists" would fail on a Tuesday for
 * reasons that are not bugs. What is asserted is behaviour that must hold at any catalogue size
 * and any tagging level: the shelf renders, search finds by more than the title, filters go into
 * the URL, and a filtered URL comes back filtered.
 */

const cards = 'a[href^="/pack/"]';

test('the shelf renders and every card is a link to a pack', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator(cards).first()).toBeVisible();
  expect(await page.locator(cards).count()).toBeGreaterThan(0);
});

test('the first pack card is above the fold', async ({ page }) => {
  // Measured at the configured viewport (1280x720, playwright.config.ts), the first card used to
  // start at y=1094: a hero of 606px, a three-block section heading of 206px and a full-width
  // three-question form of 107px, so a storefront whose whole pitch is "here is what survived"
  // opened on an argument with no product on screen. It now starts at ~651.
  //
  // The bar is 40px of card actually visible, not merely `y < 720`: a card whose top edge lands
  // one pixel above the fold satisfies the letter of "above the fold" and shows the buyer nothing.
  // This is asserted as a number because the failure mode is additive — the next block someone
  // puts above the grid pushes it back down, and no reviewer measures.
  const MIN_VISIBLE_PX = 40;
  await page.goto('/');
  const box = await page.locator(cards).first().boundingBox();
  expect(box).not.toBeNull();
  const fold = page.viewportSize()!.height;
  expect(fold - box!.y).toBeGreaterThan(MIN_VISIBLE_PX);
});

/**
 * One email ask per screen, counted in the DOM.
 *
 * `index.tsx:537` already stated the rule in a comment -- "two email forms on one screen is a
 * duplicate ask that also breaks selector uniqueness" -- and the shelf branch honoured it, but a
 * second, unconditional waitlist band further down the page rendered under every branch, so both
 * the shelf state and the empty state asked a stranger for the same address twice in the same
 * words. No source-text test can see this: each form is correct where it is written, and the
 * defect only exists once the page is composed. Counting rendered inputs is the only artifact
 * that answers the question.
 */
for (const [label, url] of [
  ['the shelf', '/'],
  ['the empty state', '/?q=zzzzz-no-such-pack-anywhere'],
] as const) {
  test(`${label} asks for an email address at most once`, async ({ page }) => {
    await page.goto(url);
    await expect(page.locator('main').first()).toBeVisible();
    const emails = page.locator('input[type="email"]');
    // `toBeLessThanOrEqual`, not `toBe(1)`: a state that makes no ask at all is a product choice,
    // whereas asking twice is always a defect.
    expect(await emails.count(), `${url} renders more than one email ask`).toBeLessThanOrEqual(1);
  });
}

/**
 * The free sample opens cold, with no address given.
 *
 * The home page promises "No payment, no email." two lines above a waitlist form, and the two
 * cannot both be true if the sample is gated. This was guarded in `src/lib/__tests__/sources.test.ts`
 * by SOURCE ORDER -- the sample link had to appear before a particular `<WaitlistForm>` in the file
 * -- which is not what gating means. A form earlier in the file gates nothing, and that assertion
 * went red on 2026-08-06 for a band deletion that changed the reader's access not at all. The only
 * thing that answers "is it gated" is walking in off the street and opening it.
 */
test('the free sample opens without giving an email', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: /sample/i }).first().click();
  await expect(page).toHaveURL(/\/sample/);
  // The report itself, not just a 200: a gate that renders a capture panel at /sample would
  // still be a page load. The evidence section is the thing being given away.
  const evidence = page.getByRole('heading', { name: /Every check, every source/i });
  await expect(evidence).toBeVisible();
  await expect(page.locator('a[href^="http"]').first()).toBeVisible();

  // NOT `count() === 0`. /sample does carry one ask -- `WaitlistCallout` at sample.tsx:259, the
  // last element on the page, under the buy CTA. An ask below the thing you already read is not
  // a gate; a gate is an ask you must clear FIRST. So the assertion is document ORDER against
  // the evidence, which is what the word means, plus the one-ask-per-screen rule this page has
  // to obey like every other.
  const asks = page.locator('input[type="email"]');
  expect(await asks.count(), '/sample must make at most one ask').toBeLessThanOrEqual(1);
  if (await asks.count()) {
    const askIsAfterEvidence = await page.evaluate(() => {
      const heading = [...document.querySelectorAll('h2')].find((h) =>
        /Every check, every source/i.test(h.textContent || ''),
      );
      const input = document.querySelector('input[type="email"]');
      if (!heading || !input) return false;
      // DOCUMENT_POSITION_FOLLOWING === 4: the input comes after the heading.
      return Boolean(heading.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(askIsAfterEvidence, 'an email ask above the evidence is a gate on the free sample').toBe(true);
  }
});

test('the command palette opens by click and by ⌘K, and searches as you type', async ({ page }) => {
  await page.goto('/');
  const dialog = page.getByRole('dialog');

  // Click first, deliberately. The ⌘K listener is attached on hydration, so pressing the key
  // straight after `goto` is a race against React, not a test of the shortcut. Clicking a button
  // waits for actionability, which puts us safely past hydration for the keyboard check below.
  await page.getByRole('button', { name: /Search the catalogue/ }).first().click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);

  await page.keyboard.press('ControlOrMeta+k');
  await expect(dialog).toBeVisible();

  // Results respond to typing — no Enter, no results page (spec Part 6).
  const search = dialog.getByRole('combobox');
  const before = await dialog.getByRole('option').count();
  expect(before).toBeGreaterThan(0);
  await search.fill('zzzzz-no-such-pack');
  await expect(dialog.getByText(/Nothing in the catalogue matches/)).toBeVisible();
  await search.fill('');
  await expect.poll(async () => dialog.getByRole('option').count()).toBe(before);

  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('a facet click lands in the URL, and that URL comes back filtered', async ({ page }) => {
  await page.goto('/');

  // "All" is the one control guaranteed to exist in every rendered group — a group with no data
  // does not render at all (AC-12), so this test picks whatever the catalogue actually offers.
  const firstValue = page
    .locator('aside button[aria-pressed]')
    .filter({ hasNotText: /^All$/ })
    .first();
  const count = await page.locator('aside button[aria-pressed]').count();
  test.skip(count === 0, 'No facet is populated in this catalogue yet — nothing to click.');

  await firstValue.click();
  await expect(page).toHaveURL(/\?(q|adv|sector|payer|effort|commitment|mechanism)=/);

  // The same URL, loaded cold: server-rendered HTML must already be filtered, not flash the
  // whole catalogue and then filter on the client.
  const url = page.url();
  const filteredCount = await page.locator(cards).count();
  await page.goto(url);
  await expect(page.locator('aside button[aria-pressed="true"]').first()).toBeVisible();
  expect(await page.locator(cards).count()).toBe(filteredCount);
});

test('the waitlist refuses to submit without consent, and the box starts unticked', async ({ page }) => {
  // A query no pack can match forces the catalogue-wide empty state.
  await page.goto('/?q=zzzzz-no-such-pack-anywhere');

  // Matched loosely on purpose. 9b87875 moved this form to a second placement and generalised
  // the label from "a pack in this space" to "a pack", which left this test red on a copy edit
  // while the consent behaviour it exists to protect was never touched. The assertions that
  // matter are the two below: the box is visible, and it does not start ticked.
  const consent = page.getByRole('checkbox', { name: /Email me if a pack/ });
  await expect(consent).toBeVisible();
  // Pre-ticked is not consent under UK GDPR. This is the assertion that keeps it that way.
  await expect(consent).not.toBeChecked();

  await page.getByRole('textbox', { name: /^Email/ }).fill('e2e@example.com');
  await page.getByRole('button', { name: 'Put it in the queue' }).click();
  await expect(page.getByText(/Without it we have no lawful basis/)).toBeVisible();
});

test('the privacy notice states the waitlist basis and its retention', async ({ page }) => {
  await page.goto('/privacy');
  await expect(page.getByText(/Waitlist sign-ups/).first()).toBeVisible();
  await expect(page.getByText(/Art\.\s*6\(1\)\(a\)/)).toBeVisible();
  await expect(page.getByText(/24 months from sign-up/)).toBeVisible();
});

// A pack withdrawn via PATCH /internal/catalog/{id}/listing must be GONE, not merely absent
// from the shelf. On 2026-07-31 it was only the latter: GET /catalog filtered on IsListed but
// GET /catalog/{id} did not, so a withdrawn pack still served its full sales page — verified
// claims, sources, and a "Get instant access" button — to anyone with the URL. Checkout
// refused it (Program.cs:605), so no money could move; the damage was that withdrawn claims
// stayed public and the button became an error instead of an absence.
//
// The ids below are the three quarantined that day for a moat breach (kill-checks and the
// adversarial pass run on DeepSeek, which CLAUDE.md forbids from touching verification).
// If one is ever re-listed this test goes red — deliberately: re-listing them is a decision
// that has to be made with the re-verification, not by a test quietly agreeing.
const QUARANTINED_2026_07_31 = ['42bf9861ecc08079', 'f7783abea10a4216', '54f775d91cbe09d8'];

// THE SECOND HALF, found 2026-08-05: the API was fixed, the storefront was not. Measured against
// production for all three ids below:
//
//     api.mumchimp.com/catalog/{id}  ->  404, and absent from /catalog   (the fix worked)
//     mumchimp.com/pack/{id}         ->  200, robots "index, follow"     (the fix was undone here)
//
// `getServerSideProps` caught every fetch failure into `props: { pack: null }`, which Next serves
// as a 200. So a quarantined pack still had a live, indexable URL -- a soft-404. This test was
// red for months and read as a stale expectation rather than the open defect it was.
for (const id of QUARANTINED_2026_07_31) {
  test(`a withdrawn pack is gone, not just unlisted: ${id}`, async ({ page }) => {
    const res = await page.goto(`/pack/${id}`);
    // A HARD 404. A 200 carrying an error panel satisfies every visible expectation below while
    // still telling a crawler the URL is a live page, which is the exact defect this caught.
    expect(res?.status(), 'a withdrawn pack must 404, not soft-404').toBe(404);
    await expect(page.getByRole('button', { name: /instant access/i })).toHaveCount(0);
  });
}
