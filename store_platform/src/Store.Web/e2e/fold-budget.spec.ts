/**
 * THE PRE-DEPLOY FOLD GATE.
 *
 * WHY THIS FILE EXISTS. On 2026-08-19 the home page shipped with the "6 in 100" hero figure
 * rendering at every width. Below 901px `.hero` is a single column (`mumchimp.css:432`), so the
 * figure stacked under the headline and pushed the first pack card to y=1288 on a 400px-wide
 * phone. A shop's home page opened with no product on screen. It stayed that way for 30 hours.
 *
 * WHAT LET IT SHIP. The redraw was graded by `scripts/parity.mjs`, which compares DOM structure
 * -- tag names and the classes `mumchimp.css` defines -- and measures no geometry and no
 * viewport. The only check that measures the phone fold is `e2e/discovery.spec.ts`, and that
 * runs in `e2e-live-smoke.yml` against production, AFTER the deploy. A check that only runs
 * after deployment cannot prevent a bad deployment.
 *
 * WHAT THIS ONE DOES DIFFERENTLY. It runs in CI's `nextjs` job against a locally built server,
 * before merge. That server has no API behind it, so it renders no pack cards -- which is why
 * every assertion here anchors on chrome that renders whether or not the catalogue answers:
 * the shelf heading and the header's search control. That is enough to catch the whole class,
 * because the defect is always "something above the shelf grew", never the cards themselves.
 *
 * THE BUDGET. The shelf heading must have at least MIN_VISIBLE_PX showing inside the first
 * viewport. Measured on the fixed build 2026-08-19: 614px on a 390x844 phone, against a budget
 * of 804. Add a band to the hero and this fails before it reaches a buyer.
 */
import { test, expect } from '@playwright/test';

/** Same figure `e2e/discovery.spec.ts` uses for the card fold: 40px is "you can see it is there". */
const MIN_VISIBLE_PX = 40;

/** The three phone sizes the live smoke already tests, so the two gates agree on what a phone is. */
const PHONES = [
  { name: 'iPhone 14', width: 390, height: 844 },
  { name: 'small Android', width: 360, height: 780 },
  { name: 'iPhone 14 Pro Max', width: 430, height: 932 },
];

for (const phone of PHONES) {
  test(`the shelf starts on the first screen at ${phone.width}x${phone.height} (${phone.name})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: phone.width, height: phone.height });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const shelfHeading = page.getByRole('heading', { name: "What's for sale" }).first();
    await expect(shelfHeading).toBeAttached();

    const box = await shelfHeading.boundingBox();
    expect(box, 'the shelf heading has no box, so the shelf did not render').not.toBeNull();

    const budget = phone.height - MIN_VISIBLE_PX;
    expect(
      Math.round(box!.y),
      `the shelf heading starts at y=${Math.round(box!.y)} on a ${phone.height}px-tall screen; ` +
        `something above it grew past the ${budget}px budget`,
    ).toBeLessThanOrEqual(budget);
  });

  test(`the header search control is reachable at ${phone.width}x${phone.height} (${phone.name})`, async ({
    page,
  }) => {
    /* Below 980px the shelf's own search trigger is `display:none` (`mumchimp.css:436`), so this
       button is the ONLY way to search on a phone. The redraw renamed it to a bare "Search",
       which is what broke `discovery.spec.ts:254,266` on live. Assert the accessible name here,
       pre-deploy, because `parity.mjs` drops `aria-label` and cannot see this change. */
    await page.setViewportSize({ width: phone.width, height: phone.height });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const headerSearch = page
      .locator('header')
      .getByRole('button', { name: /Search the packs/ });
    await expect(headerSearch).toBeVisible();
  });
}
