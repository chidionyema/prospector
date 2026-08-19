import { defineConfig, devices } from '@playwright/test';

/**
 * Browser checks for the storefront. Assumes the web app is already running at WEB_BASE_URL
 * (prove_web.sh boots Store.Api + Store.Web first; the live smoke workflow points it at
 * https://mumchimp.com). Chromium only — the goal is to prove the rendered pages work end to
 * end, not cross-browser parity.
 *
 * FOUR PROJECTS, THREE DIFFERENT QUESTIONS.
 *
 *   chromium  — does it work? Links, buttons, statuses. The original smoke.
 *   a11y      — is it usable? axe-core against the real DOM. Static lint (eslint-plugin-jsx-a11y,
 *               already enforced as errors in eslint.config.mjs) cannot see contrast, focus order,
 *               duplicate landmarks, or an aria-labelledby pointing at an id that never rendered.
 *   visual-*  — does it still LOOK right? toHaveScreenshot() baselines at the two widths the
 *               design is drawn at. This is the check that would have caught the "624" bar key
 *               rendering as a paragraph, and the shelf line reading "5 US · GA packs · 2 US · FL
 *               packs". Both shipped green because every functional assertion still passed.
 *
 * `testIgnore` on the smoke project keeps `npm run test:e2e` exactly what it was: a stale baseline
 * must not turn the post-deploy smoke red, and a11y findings are reported as their own lane.
 */
const NOT_THE_SMOKE = ['**/a11y.spec.ts', '**/visual.spec.ts'];

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
    /**
     * The storefront renders the LIVE catalogue, so a screenshot is never byte-identical twice:
     * a new pack changes a count, a price moves a rung. `visual.spec.ts` masks the data-bearing
     * regions, and this ratio absorbs the sub-pixel text rendering that survives masking. It is
     * a ratio of the whole page, so a layout defect — a collapsed grid, a section three times
     * too tall — is orders of magnitude above it.
     */
    toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled', scale: 'css' },
  },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.WEB_BASE_URL || 'http://localhost:3000',
    headless: true,
    trace: 'off',
  },
  projects: [
    { name: 'chromium', testIgnore: NOT_THE_SMOKE, use: { ...devices['Desktop Chrome'] } },
    { name: 'a11y', testMatch: '**/a11y.spec.ts', use: { ...devices['Desktop Chrome'] } },
    /**
     * 390 and 1280 are the widths in the design brief, and the two the parity harness shoots.
     * The project name lands in the baseline filename, and so does the platform: a baseline shot
     * on darwin does not match one shot on Linux (different font stacks, different subpixel
     * rendering), so the two live side by side and CI only ever compares its own.
     */
    {
      name: 'visual-mobile',
      testMatch: '**/visual.spec.ts',
      use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } },
    },
    {
      name: 'visual-desktop',
      testMatch: '**/visual.spec.ts',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } },
    },
  ],
});
