import { defineConfig, devices } from '@playwright/test';

// Browser smoke for the storefront UI. Assumes the web app is already running at WEB_BASE_URL
// (prove_web.sh boots Store.Api + Store.Web first). Chromium only — the goal is to prove the
// rendered pages work end to end, not cross-browser parity.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.WEB_BASE_URL || 'http://localhost:3000',
    headless: true,
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
