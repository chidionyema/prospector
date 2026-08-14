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

/**
 * The first pack card a READER CAN SEE, which is not always the first one in the DOM.
 *
 * The hero's featured pack is `hidden lg:block`: it is the first `a[href^="/pack/"]` in document
 * order at every width, and on a phone it is `display: none`. `.first().boundingBox()` on the
 * plain selector therefore returned `null` on all three mobile viewports -- not "the card is off
 * screen" but "the card has no box at all", which fails the fold assertion for a reason that has
 * nothing to do with the fold. `:visible` measures what the buyer actually meets: the hero card on
 * desktop, the first shelf card on a phone.
 */
const visibleCards = 'a[href^="/pack/"]:visible';

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
  const box = await page.locator(visibleCards).first().boundingBox();
  expect(box).not.toBeNull();
  const fold = page.viewportSize()!.height;
  expect(fold - box!.y).toBeGreaterThan(MIN_VISIBLE_PX);
});

/**
 * The same bar, on a phone. This is a separate test because the project runs ONE Playwright
 * project at 1280x720 (playwright.config.ts, `devices['Desktop Chrome']`), so the desktop fold
 * test above physically cannot see a mobile regression -- and there was one, unnoticed while the
 * desktop fold was fixed and guarded: the filter-log panel is the hero's right column on lg+,
 * costing nothing vertically, and stacking it on a phone put the first pack card 1.23 screens
 * down at 390x844, 1.37 at 360x780 and 1.08 at 430x932. An ecommerce home page with no product
 * on the first screen, on every phone size measured.
 *
 * Three widths, not one, because the failure is a height budget and the panel's cost is fixed
 * while the viewport is not: 360x780 was the worst case and the one a single 390x844 check would
 * have missed by the widest margin.
 */
for (const [w, h, device] of [
  [390, 844, 'iPhone 12/13/14'],
  [360, 780, 'small Android'],
  [430, 932, 'iPhone Pro Max'],
] as const) {
  test(`the first pack card is above the fold at ${w}x${h} (${device})`, async ({ page }) => {
    const MIN_VISIBLE_PX = 40;
    await page.setViewportSize({ width: w, height: h });
    await page.goto('/');
    const box = await page.locator(visibleCards).first().boundingBox();
    expect(box).not.toBeNull();
    expect(h - box!.y, `first card starts at y=${Math.round(box!.y)} on a ${h}px screen`).toBeGreaterThan(
      MIN_VISIBLE_PX,
    );
  });
}

/**
 * The checks-log panel is OFF the home page, and this asserts the absence.
 *
 * History, because the inversion matters. The panel used to render twice -- `hidden lg:block` in
 * the hero, `lg:hidden` below the shelf -- and this block asserted "exactly one, after the first
 * card": a reader meets a product before they meet the argument. Both positions were the same
 * mistake at two widths (on desktop a ledger of discarded ideas was the largest object on the
 * first screen of a shop; on a phone it pushed the first card 1.23 screens down), so it was cut
 * to one copy below the shelf, and then removed from the page entirely by the founder on
 * 2026-08-14. `pages/index.tsx:2197` is the record of what it was and why it earned its place.
 *
 * The removal took this test red on main for two runs (31835917831 and the one before it) with
 * `Received: 0` -- a red that described a decision, not a defect. Rather than delete the test, it
 * is inverted: a panel deliberately taken off a page is exactly the kind of thing that comes back
 * by accident when a component is re-imported, and `count() === 0` is the cheapest guard against
 * that. `LiveKillCard` itself is NOT deleted from the codebase, so the import is one line away.
 *
 * Still measured in the rendered DOM, not in the source: `order-`/`flex-col-reverse`/`absolute`
 * all defeat a source-order assertion, and a component can be rendered from a place grep misses.
 */
for (const [w, h, label] of [
  [1280, 720, 'desktop'],
  [390, 844, 'mobile'],
] as const) {
  test(`the checks-log panel stays off the home page on ${label}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto('/');
    // Anchored on `data-testid`, not on the header copy. This asserted `getByText('The filter
    // log', {exact:true})` until 2026-08-08, when the sitewide rename in 75ed46d made the panel
    // say "The checks log" and the live smoke went red on main (run 31226558030) with
    // `Received: 0` -- a red that described a copy edit, not a broken page. Text matching was
    // also measuring the wrong noun: it counted TEXT NODES, so a nav link repeating the words
    // would have failed a test about this card. The testid counts panels.
    const panels = page.locator('[data-testid="checks-log"]');
    expect(await panels.count(), 'the checks log was removed from the home page, see index.tsx').toBe(0);

    // The property the old assertion was really protecting -- product before argument -- is still
    // worth pinning, and with the panel gone the first card carries it alone. The fold tests above
    // measure its position; this one only needs it to exist, so a home page that renders no shelf
    // at all cannot pass by virtue of having nothing to be above.
    await expect(page.locator(visibleCards).first()).toBeVisible();
  });
}

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
  // By destination, not by accessible name. `getByRole('link', {name: /sample/i})` matched zero
  // links on 2026-08-08 (run 31226558030, a 30s timeout) because none of the three routes to
  // /sample says the word: they read "Read a full pack free, no email needed.", "See the whole
  // thing" and "Read a full evidence record free". Naming a CTA after the URL it points at is
  // bad copy, so the test was pinning the wrong half -- what this test claims is that a stranger
  // can REACH the sample from the homepage, and the href is that claim. `:visible` because the
  // desktop-only route is display:none at 390px and Playwright will not click a hidden link.
  await page.locator('a[href="/sample"]:visible').first().click();
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

/**
 * Search is reachable from the site chrome, on a page that has no catalogue.
 *
 * The header button cannot hold the palette: `MarketingLayout` renders on /faq, /terms and
 * /pack/[id], none of which have the pack list the palette searches. So it takes two different
 * routes to the same dialog — a window event on `/`, and a navigation to `/?search=1` everywhere
 * else — and a two-path mechanism is exactly the kind that ships with one path working. Both are
 * asserted here.
 *
 * Only the header button is targeted (`header` scope): on `/` the shelf's own SearchTrigger has
 * the same accessible name, and an unscoped match would let this pass on the control that was
 * already reachable.
 */
test('the header search button opens the palette from a page with no catalogue', async ({ page }) => {
  await page.goto('/faq');
  const headerSearch = page.locator('header').getByRole('button', { name: /Search the catalogue/ });
  await expect(headerSearch).toBeVisible();
  await headerSearch.click();

  // It has to land on the catalogue AND open, not merely navigate.
  await expect(page).toHaveURL(/\/\?search=1/);
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('option').first()).toBeVisible();
});

test('the header search button opens the palette in place on the catalogue', async ({ page }) => {
  await page.goto('/');
  const headerSearch = page.locator('header').getByRole('button', { name: /Search the catalogue/ });
  await headerSearch.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  // No navigation: the event path must not fall through to the `/?search=1` push.
  expect(new URL(page.url()).search).toBe('');
});

test('a facet click lands in the URL, and that URL comes back filtered', async ({ page }) => {
  await page.goto('/');

  /*
   * THIS TEST WAS SKIPPING, EVERY RUN, SILENTLY.
   *
   * It scoped to `aside button[aria-pressed]`, which is `FacetBar` — a component that is exported
   * and rendered by nothing (`grep -rn FacetBar src/ e2e/`, 2026-08-06: only its own file and its
   * own test). So the count was 0, `test.skip` fired, and the suite reported a pass. The one
   * property this file was written to prove in a real browser — that clicking a facet writes the
   * URL and that the URL comes back SERVER-filtered rather than flashing 63 cards and narrowing
   * after hydration — has never actually been checked.
   *
   * The selector is now the shelf's own sector chips, which is the control a buyer can reach:
   * `data-facet-control` rather than a class, so restyling the chip cannot silently un-skip this
   * back to zero. The `aside` form is kept in the union so a future FacetBar is covered too.
   */
  const controls = page.locator(
    '[data-facet-control] button[aria-pressed], aside button[aria-pressed]',
  );
  // The "show everything" chip is excluded by prefix, not by exact text: it reads "All packs"
  // followed by a count, so an `^All$` match — what this used — would have excluded nothing and
  // then clicked the one control that deliberately writes NO parameter.
  const firstValue = controls.filter({ hasNotText: /^All/ }).first();
  const count = await controls.count();
  test.skip(count === 0, 'No facet is populated in this catalogue yet — nothing to click.');

  await firstValue.click();
  await expect(page).toHaveURL(/\?(q|adv|sector|payer|effort|commitment|mechanism)=/);

  // The same URL, loaded cold: server-rendered HTML must already be filtered, not flash the
  // whole catalogue and then filter on the client.
  const url = page.url();
  const filteredCount = await page.locator(cards).count();
  await page.goto(url);
  await expect(
    page
      .locator('[data-facet-control] button[aria-pressed="true"], aside button[aria-pressed="true"]')
      .filter({ hasNotText: /^All/ })
      .first(),
  ).toBeVisible();
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

/**
 * REACHING the filter, as opposed to where the filter happens to sit.
 *
 * History this pins (all measured on prod, 2026-08-08, Playwright): the three-question router was
 * moved to the foot of the shelf, which put it at y=4054 on a 1280x800 desktop -- 5.1 screens down,
 * past all 53 cards -- and y=4882 on a 390px phone. Before that it was at the top, where it pushed
 * the first card 500px below the fold and broke the fold test above. Every fix was a MOVE, and each
 * move traded one reader's problem for another's, because reachability was being expressed as a
 * position and a position can only serve the reader standing at it.
 *
 * So these assert the property, not the coordinate: the controls are reachable from anywhere via a
 * pinned trigger, and the router is not duplicated when that trigger opens it. No absolute y is
 * asserted, because the catalogue grows and the page gets longer -- which is exactly the additive
 * drift that buried it the first time.
 */
const FAB = '[data-testid="filter-fab"]';

test('the filter is reachable from the foot of the shelf without scrolling back', async ({ page }) => {
  await page.goto('/');

  // Nothing pinned before the reader has met the controls: a "narrow it down" button on a page
  // where no product has been seen yet is the control-panel-first defect in a smaller box.
  await expect(page.locator(FAB)).toHaveCount(0);

  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect(page.locator(FAB)).toBeVisible();

  await page.locator(FAB).click();
  await expect(page.locator('[role="dialog"]')).toBeVisible();

  // The trigger hides while the thing it opens is open, or it sits on top of its own sheet.
  await expect(page.locator(FAB)).toBeHidden();
});

test('the router is mounted exactly once when the filter sheet is open', async ({ page }) => {
  // The page renders the router inline AND in the sheet, and the inline one unmounts while the
  // sheet is open. Two mounted routers would be two wizard positions for one filter state, and
  // would double every selector matching on this copy -- the failure the `shelfControls` note in
  // pages/index.tsx calls "two sources of truth".
  const ROUTER_COPY = 'Show me packs I could actually run';
  await page.goto('/');
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.locator(FAB).click();
  await expect(page.locator('[role="dialog"]')).toBeVisible();

  const instances = await page.evaluate(
    (copy) => document.body.innerText.split(copy).length - 1,
    ROUTER_COPY,
  );
  expect(instances).toBe(1);
});
