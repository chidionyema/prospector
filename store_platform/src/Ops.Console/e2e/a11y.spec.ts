import AxeBuilder from '@axe-core/playwright';
import { test, expect } from '@playwright/test';

import { SCREENS, settled, signIn } from './session';

/**
 * ACCESSIBILITY OF THE OPS CONSOLE, MEASURED ON THE RENDERED DOM.
 *
 * The console is not a public site, and that is an argument for this rather than against it. It is
 * operated from a phone, usually inside Telegram's in-app browser, often one-handed, sometimes
 * during an incident. Every failure mode axe measures -- a control with no accessible name, a
 * contrast that disappears in sunlight, a form field with no label -- costs the most in exactly
 * that situation.
 *
 * WHAT FAILS THE RUN. `serious` and `critical` only, and any of those may be excused only by a
 * named entry in KNOWN below. `moderate` and `minor` print for the record. A gate that fails on
 * "minor" is a gate somebody turns off.
 *
 * WHERE IT RUNS. `npm run test:a11y`, against the Playwright webServer in playwright.config.ts,
 * which boots `next start` on its own port. In CI it runs WITHOUT the Python gateway, so most
 * panels render their stated-problem branch rather than data. That is deliberate and it is not a
 * lesser test: an operator meets those states during an outage, which is the worst moment for an
 * unreadable one. The data-filled version is what a local run gives you.
 */
const BLOCKING = ['serious', 'critical'];

type Known = { reason: string; expires: string };

/**
 * What is deferred, named and dated. Everything else blocks.
 *
 * Three defects this spec found on its first run were fixed the same day: `<html>` had no `lang`
 * (every screen, both widths), the stat placeholder used --faint at 2.56:1, and a provider pill
 * blended --ok-strong to 3.65:1 with `opacity-70`. What is left is below. The founder capped the
 * time this console gets -- it is an admin tool, not the storefront -- so these are recorded with
 * a date rather than chased now.
 *
 * The list is not a severity being switched off. Each entry fails the run when it expires, and
 * fails the run if it ever stops firing.
 */
// EMPTY, and that is the point. The one entry this held -- --subtle #71717A on --bad-bg
// #FEF2F2 at 4.41:1, 0.09 under the floor -- was deferred to 2026-09-19 and then fixed on
// 2026-08-19 instead: globals.css now sets --subtle to #6D6D76, which measures 4.68:1 on that
// ground and 5.12:1 on white. The stale-exception check below is what forced the choice. It
// failed the run the moment the violation stopped firing, so an exception cannot quietly
// outlive the defect it excuses.
const KNOWN: Record<string, Known> = {};

const WIDTHS = [
  { name: 'phone', width: 390, height: 844 },
  { name: 'desktop', width: 1280, height: 900 },
];

type Violation = {
  id: string;
  impact?: string | null;
  help: string;
  nodes: { target: unknown[] }[];
};

const fired = new Set<string>();

function expired(id: string, today: Date): boolean {
  return today.toISOString().slice(0, 10) > KNOWN[id].expires;
}

function report(where: string, violations: Violation[]): string {
  return violations
    .map(
      (v) =>
        `  [${v.impact}] ${v.id} — ${v.help}\n` +
        v.nodes
          .slice(0, 4)
          .map((n) => `      ${JSON.stringify(n.target)}`)
          .join('\n'),
    )
    .join('\n')
    .concat(`\n  (${where})`);
}

function triage(results: { violations: Violation[] }, where: string): Violation[] {
  const serious = results.violations.filter((v) => BLOCKING.includes(v.impact ?? ''));
  const advisory = results.violations.filter((v) => !BLOCKING.includes(v.impact ?? ''));
  const today = new Date();

  for (const v of serious) if (v.id in KNOWN) fired.add(v.id);
  if (advisory.length) {
    console.log(`advisory (not gating) on ${where}:\n${report(where, advisory)}`);
  }
  return serious.filter((v) => !(v.id in KNOWN) || expired(v.id, today));
}

/**
 * Audits one page and RETURNS what blocks, rather than asserting.
 *
 * Asserting here aborted the loop on the first bad screen, so nine screens were never audited and
 * the known-exception list looked stale because rules that do fire never got the chance to. A
 * gate that stops measuring at the first finding under-reports by design.
 */
async function audit(page: import('@playwright/test').Page, where: string): Promise<string[]> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  const blocking = triage(results, where);
  return blocking.length ? [report(where, blocking)] : [];
}

/**
 * The login page is audited signed OUT and first, because it is the one screen every operator
 * meets before anything else works, and the only one a failure locks you out of.
 */
for (const vp of WIDTHS) {
  test(`a11y: /login at ${vp.width}px`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto('/login');
    const found = await audit(page, `/login at ${vp.name}`);
    expect(found, found.join('\n')).toHaveLength(0);
  });
}

for (const vp of WIDTHS) {
  test(`a11y: every screen at ${vp.width}px`, async ({ page }) => {
    // Ten screens, each audited by axe, in one test. Measured: 59.6s at 1280px and a timeout at
    // 390px, both against the 60s default. The audit is the slow part and it is not optional, so
    // the budget moves rather than the coverage.
    test.setTimeout(180_000);
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await signIn(page);

    const found: string[] = [];
    for (const path of SCREENS) {
      await page.goto(path);
      await settled(page);
      found.push(...(await audit(page, `${path} at ${vp.name}`)));
    }
    expect(found, found.join('\n')).toHaveLength(0);
  });
}

/**
 * Declared last so it runs last. An exception that has run out of time, or that no longer fires,
 * is a hole in the gate rather than a decision -- and a stale one sits in front of the next
 * regression in that same rule.
 */
test('a11y: the known-exception list is still true', () => {
  const today = new Date();
  const overdue = Object.keys(KNOWN).filter((id) => expired(id, today));
  const stale = Object.keys(KNOWN).filter((id) => !fired.has(id));

  expect(overdue, `expired exceptions: ${overdue.join(', ')}`).toHaveLength(0);
  expect(stale, `exceptions that no longer fire — delete them: ${stale.join(', ')}`).toHaveLength(0);
});
