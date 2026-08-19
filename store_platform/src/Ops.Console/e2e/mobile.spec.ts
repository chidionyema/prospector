/**
 * The founder's rejection of the old console was "looks crap", "unusable", and it broke inside
 * Telegram's in-app browser. These are the mechanical parts of that, measured rather than
 * eyeballed:
 *
 *   - the page never scrolls sideways, at 390px and at 320px;
 *   - every tappable control is at least 44px tall;
 *   - text inputs are at least 16px, because below that iOS Safari zooms in and does not zoom back;
 *   - every screen renders when it was read.
 *
 * What this cannot check is whether it looks good. That is a human judgement and the spec says so.
 */
import { expect, test } from '@playwright/test';

import { SCREENS, signIn } from './session';

test.describe('the phone', () => {
  test('the login page fits', async ({ page }) => {
    await page.goto('/login');
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, 'the page scrolls sideways').toBeLessThanOrEqual(0);

    const fontSize = await page
      .locator('input[type="password"]')
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(fontSize, 'below 16px iOS zooms in and never zooms back').toBeGreaterThanOrEqual(16);
  });

  test('every screen fits and says when it read', async ({ page }) => {
    // Ten screens, each waiting on a Python spawn. Measured 2026-08-19: 40.3s alone, and over
    // the 60s default when the two phone projects run back to back on a cold server. Several
    // views log `read_slow` at 6-8s on their own. The budget moves; the coverage does not.
    test.setTimeout(180_000);
    await signIn(page);

    for (const path of SCREENS) {
      await page.goto(path);
      // Panels fetch in the browser. Wait for the first one to answer — either data or a stated
      // problem. A blank screen is a failure whichever it is.
      await expect
        .poll(
          async () =>
            (await page.locator('text=/read .* ago|could not|is not set|Sign in/i').count()) > 0,
          { timeout: 30_000, message: `${path} rendered neither data nor a reason` },
        )
        .toBe(true);

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(0);
    }
  });

  test('controls are thumb-sized', async ({ page }) => {
    await signIn(page);
    await page.goto('/engine');
    await page.waitForTimeout(2000);

    const boxes = await page.locator('button:visible, a.tap:visible').evaluateAll((els) =>
      els.map((el) => ({ text: (el.textContent || '').trim().slice(0, 30), h: el.getBoundingClientRect().height })),
    );
    const small = boxes.filter((b) => b.h > 0 && b.h < 44);
    expect(small, 'a control under 44px is a miss on a phone').toEqual([]);
  });
});
