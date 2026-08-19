import { test, expect, type Page } from '@playwright/test';

/**
 * VISUAL REGRESSION AGAINST THE PAGE'S OWN LAST-KNOWN-GOOD SHOT.
 *
 * This is a different question from `scripts/visual_regression.mjs`, and that difference is the
 * reason both exist. That harness compares the built page to the DESIGNER'S DRAWING, so it can
 * never converge: the drawing carries sample copy and the app carries the live catalogue, and
 * making the words match moved `/about` from 3.89% to 3.95% — the wrong way (see the header of
 * that file). This one compares the page to ITSELF as it was when someone last looked at it and
 * said it was right. Same-document comparison, so the bar can be strict and a regression is a
 * regression rather than a copy difference.
 *
 * WHAT IT CATCHES THAT NOTHING ELSE DID. Two defects shipped green in the last week: the "624"
 * bar key rendered as a paragraph, and the shelf count line read "5 US · GA packs · 2 US · FL
 * packs" because a label contained the separator its own list joins with. Every functional
 * assertion passed on both. A pixel diff of the page against its own baseline fails on both.
 *
 * MASKING, AND WHY IT IS NARROW. The storefront renders the live catalogue, so a shot taken a day
 * later legitimately differs: a new pack, a moved price. The pack cards are masked because they
 * are pure catalogue volume. Everything else — header, footer, section rhythm, the bands, the
 * copy blocks — is chrome the design owns, and is compared for real.
 *
 * BASELINES ARE PER-PLATFORM AND LIVE IN GIT. Playwright puts the project name and the OS in the
 * filename, so a shot taken on darwin never grades a run on Linux. CI compares only Linux
 * baselines. To move them after a deliberate design change:
 *
 *   npm run test:visual:update          # locally, against WEB_BASE_URL
 *   gh workflow run visual-baselines.yml --ref <branch>    # on Linux, commits the new shots
 *
 * A baseline update is a claim that the new look is correct, so it belongs in the PR that changes
 * the design, reviewed as a picture.
 */
const ROUTES = [
  { route: '/', name: 'home' },
  { route: '/ideas', name: 'ideas' },
  { route: '/kill-log', name: 'kill-log' },
  { route: '/about', name: 'about' },
  { route: '/pricing', name: 'pricing' },
  { route: '/how-it-works', name: 'how-it-works' },
];

/**
 * Catalogue volume, and nothing else. Masking a region is giving up on it, so each entry needs a
 * reason that is about DATA rather than about the check being inconvenient.
 */
function masks(page: Page) {
  return [
    // One card per published pack. The count moves whenever the engine publishes.
    page.locator('a[href^="/pack/"]'),
    // One row per killed idea, newest first.
    page.locator('a[href^="/ideas/"]'),
  ];
}

async function settle(page: Page) {
  // Fonts decide layout; a shot taken before they load measures the fallback stack.
  await page.evaluate(() => document.fonts.ready);
  // Anything that animates in on scroll must have finished, or the baseline captures a transition.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForLoadState('networkidle');
}

for (const { route, name } of ROUTES) {
  test(`looks the same: ${route}`, async ({ page }) => {
    const res = await page.goto(route);
    expect(res?.status(), `${route} did not render`).toBeLessThan(400);
    await settle(page);
    await expect(page).toHaveScreenshot(`${name}.png`, {
      fullPage: true,
      mask: masks(page),
    });
  });
}

test('looks the same: a pack page', async ({ page }) => {
  await page.goto('/');
  const href = await page.locator('a[href^="/pack/"]').first().getAttribute('href');
  expect(href, 'the home page listed no pack to open').toBeTruthy();
  await page.goto(href!);
  await settle(page);
  /**
   * The pack itself changes with the catalogue, so the shot is of the PAGE FURNITURE: the buy
   * panel, the section headings, the check band. `maxDiffPixelRatio` is looser here for exactly
   * that reason, and is the only place in this file where it is relaxed.
   */
  await expect(page).toHaveScreenshot('pack.png', { fullPage: true, maxDiffPixelRatio: 0.08 });
});
