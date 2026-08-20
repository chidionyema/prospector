/**
 * Signing in, and the list of screens, in ONE place.
 *
 * `mobile.spec.ts` owned both. A second spec that needs a signed-in page has two choices: import
 * them, or write them again. Written again, they drift — a new screen gets added to one list and
 * not the other, and the spec that was not updated goes on passing while covering less. That
 * failure is silent, which is the kind this repo keeps paying for.
 *
 * The password comes from `playwright.config.ts`, which already exports it because the webServer
 * needs the same value. One literal, one owner.
 */
import type { Page } from '@playwright/test';

import { PASSWORD } from '../playwright.config';

/** Every screen behind the login, in the order the nav lists them. */
export const SCREENS = [
  '/',
  '/engine',
  '/config',
  '/queue',
  '/runs',
  '/spend',
  '/metrics',
  '/catalogue',
  '/tools',
  '/audit',
] as const;

export async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL('**/');
}

/**
 * Wait for a screen to have said something.
 *
 * Every panel fetches in the browser, so a screen is not "rendered" when navigation resolves. It
 * is rendered when it shows data, or states why it cannot. A blank page is a failure either way,
 * and auditing a blank page is how a spec reports zero violations on nothing at all.
 */
export async function settled(page: Page, timeout = 30_000): Promise<void> {
  await page
    .locator('text=/read .* ago|could not|is not set|Sign in/i')
    .first()
    .waitFor({ state: 'visible', timeout });
}
