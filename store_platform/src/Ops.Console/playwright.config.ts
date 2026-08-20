/**
 * The console is used from a phone, usually through a link opened inside Telegram — a WKWebView,
 * not Safari. So the default project here is a small phone viewport, and 320px is tested too
 * because "it looked fine on my screen" is how a page ships with a sideways scrollbar.
 *
 * The server runs against THIS worktree (`PROSPECTOR_ROOT`), never the founder's checkout, and on
 * a port of its own so a running console is not disturbed.
 */
import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const PORT = Number(process.env.OPS_E2E_PORT || 8612);
// Playwright compiles this file to CommonJS (package.json has no "type": "module"), so
// `import.meta.url` is a syntax error at load time — measured 2026-08-16: "Cannot use
// 'import.meta' outside a module", config never loaded, zero tests ran. `__dirname` is the
// form that survives that compilation.
const ROOT = resolve(__dirname, '../../..');
const PASSWORD = 'e2e-password';

//: The phone projects exist to check width, overflow and tap targets. These two ask different
//: questions and set their own viewports, so they run in projects of their own.
const NOT_THE_PHONE = ['**/a11y.spec.ts'];

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  // WebKit would be the closer match to Telegram's WKWebView, and it cannot run on this machine.
  // Measured 2026-08-16: `npx playwright install webkit` prints "You are using a frozen webkit
  // browser which does not receive updates anymore on mac14", and driving that frozen build from
  // Playwright 1.62.1 fails at `browserContext.newPage` with "Protocol error
  // (Page.overrideSetting): Unknown setting: PushAPIEnabled" — every test errored in setup.
  // So these run on Chromium with mobile emulation. What that still proves: page width, overflow,
  // tap-target size and that each screen renders. What it does NOT prove: WebKit-only layout bugs.
  // Those stay covered by the CSS rules in the spec (no 100vh, no sticky under overflow:hidden),
  // and by a human opening the link in Telegram.
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    ...devices['Pixel 7'],
  },
  // The a11y and visual specs set their own viewports and must not be run once per phone
  // project: that is the same audit twice, and a screenshot baseline shot at two widths under one
  // name is a baseline that can never match.
  projects: [
    {
      name: 'phone-390',
      testIgnore: NOT_THE_PHONE,
      use: { viewport: { width: 390, height: 844 } },
    },
    {
      name: 'phone-320',
      testIgnore: NOT_THE_PHONE,
      use: { viewport: { width: 320, height: 568 } },
    },
    { name: 'a11y', testMatch: '**/a11y.spec.ts' },
  ],
  // BUILD, then start. `next start` serves whatever `.next` happens to be on disk, and it does not
  // check whether that build matches the source — so a spec run against a stale bundle passes,
  // fails, or reports overflow on a page nobody has touched, and every one of those readings is
  // about code that is no longer here. Measured 2026-08-20: a stale bundle reported `/config`
  // overflowing by 7px at 320px, twice, including on a control run with the change reverted, which
  // is exactly how a stale reading gets mistaken for a confirmed one. The same spec against a
  // fresh build: 6 passed, 0 failed. The build costs under a minute and buys the run its meaning.
  webServer: {
    command: `npx next build && npx next start -p ${PORT}`,
    port: PORT,
    reuseExistingServer: false,
    timeout: 300_000,
    env: {
      CONTROL_CENTER_PASSWORD: PASSWORD,
      PROSPECTOR_ROOT: ROOT,
      PROSPECTOR_PYTHON: `${ROOT}/.venv/bin/python`,
    },
  },
});

export { PASSWORD, PORT };
