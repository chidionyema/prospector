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
import { readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

import type { Page } from '@playwright/test';

import { PASSWORD } from '../playwright.config';

/**
 * Every screen behind the login.
 *
 * Alphabetical, not nav order, because nav order is a judgement and alphabetical is a fact —
 * and a list ordered by judgement is a list where a missing entry looks deliberate. On
 * 2026-08-21 this named 11 of the 25 screens that exist, and the 14 it missed included /docs,
 * /share, /money and /revenue. `allScreens()` below now derives the truth from the pages
 * directory and a test compares the two, so the next omission fails instead of passing faster.
 */
export const SCREENS = [
  '/',
  '/audit',
  '/catalogue',
  '/config',
  '/data',
  '/delivery',
  '/deploys',
  '/disputes',
  '/docs',
  '/engine',
  '/incidents',
  '/logs',
  '/method',
  '/metrics',
  '/money',
  '/orders',
  '/processes',
  '/queue',
  '/reports',
  '/revenue',
  '/runs',
  '/share',
  '/shelf',
  '/spend',
  '/tools',
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

/**
 * EVERY screen the console serves, read off the pages directory rather than typed here.
 *
 * `SCREENS` above is hand-written, and on 2026-08-21 it listed 11 of the 25 screens that exist.
 * The 14 it missed included `/docs`, `/share`, `/money` and `/revenue` — the four the founder
 * asks about most. Nothing failed, because a list that is short is a list that passes quicker.
 * That is the drift this repo keeps paying for, so the second list is DERIVED and the two are
 * compared by a test instead of by whoever remembers.
 */
export function allScreens(): string[] {
  const dir = resolve(__dirname, '../src/pages');
  const out: string[] = [];
  const walk = (d: string, prefix: string) => {
    for (const entry of readdirSync(d, { withFileTypes: true })) {
      const name = entry.name;
      if (entry.isDirectory()) {
        if (name === 'api') continue;
        walk(join(d, name), `${prefix}${name}/`);
        continue;
      }
      if (!name.endsWith('.tsx')) continue;
      const stem = name.slice(0, -4);
      // `_app`/`_document` are not routes. A `[param]` route cannot be visited without an id, so
      // it is covered by a journey that supplies one, never by walking a list of paths.
      if (stem.startsWith('_') || stem.includes('[') || prefix.includes('[')) continue;
      const path = stem === 'index' ? `/${prefix}`.replace(/\/$/, '') || '/' : `/${prefix}${stem}`;
      out.push(path);
    }
  };
  walk(dir, '');
  return out.sort();
}

/**
 * Screens deliberately outside `SCREENS`, each with the reason. An entry naming a screen that no
 * longer exists fails, so this list cannot rot into an excuse.
 */
export const NOT_WALKED: Record<string, string> = {
  '/login': 'the sign-in page itself; mobile.spec.ts visits it signed out',
};
