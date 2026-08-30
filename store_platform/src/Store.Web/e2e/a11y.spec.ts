import AxeBuilder from '@axe-core/playwright';
import { test, expect } from '@playwright/test';

/**
 * ACCESSIBILITY, MEASURED ON THE RENDERED DOM.
 *
 * `eslint.config.mjs` already runs eslint-plugin-jsx-a11y's recommended set as ERRORS, so the
 * static half of this is not new. What a static rule cannot see is everything that only exists
 * once the page is rendered: colour contrast (the token could be fine and the pairing wrong),
 * duplicate landmarks assembled from two components, an `aria-labelledby` pointing at an id that
 * a conditional branch never rendered, a heading order that is correct per-component and wrong
 * per-page. axe-core reads the real accessibility tree, which is the only place those show up.
 *
 * WHAT FAILS THE RUN. `serious` and `critical` only. `moderate` and `minor` are printed for the
 * record but do not gate: axe's own severity scale is the industry one, and a gate that fails on
 * "minor" is a gate somebody turns off. The two viewports are the widths the design is drawn at.
 *
 * WHERE IT RUNS. The post-deploy live smoke (`.github/workflows/e2e-live-smoke.yml`), because it
 * needs a running site. `npm run test:a11y` runs it locally against WEB_BASE_URL.
 */
const BLOCKING = ['serious', 'critical'];

/**
 * KNOWN AND ACCEPTED — the only findings this gate lets through, each named, each with an owner
 * and an expiry.
 *
 * A blanket "these severities do not gate" is how an accessibility gate dies. This list is the
 * opposite: every other serious and critical rule blocks, and each entry here has to be argued
 * for individually and re-argued on `expires`. Two mechanisms keep it honest:
 *
 *   1. An entry past its expiry FAILS the run. The exception cannot outlive the decision.
 *   2. An entry that stops firing FAILS the run (see the last test in this file). A stale
 *      exception is a hole nobody is watching.
 */
type Known = { reason: string; expires: string };

const KNOWN: Record<string, Known> = {
  'color-contrast': {
    // Measured against the live site 2026-08-19: 15 of 15 a11y tests failed, on this rule and
    // nothing else. --subtle #8B9096 (src/styles/tokens.css:177) is 3.21:1 on #FFFFFF and 3.07:1
    // on --bg #FAFAF7 at 12px, against the WCAG AA floor of 4.5:1. It carries the meta rows: the
    // shelf counts ("6 survived"), eyebrows, market codes, "28 sources", "7/8 checks", "Verified
    // 2 days ago".
    //
    // It is that value on a founder directive (2026-08-18, "pixel perfect ... to colours") which
    // replaced the AA-passing #707478 with the mockups' literal value. That directive is a
    // decision, not a defect, so this gate records it instead of overruling it -- and records it
    // as an exception with a date rather than as silence, so the trade is visible and comes back
    // for a second look.
    reason:
      '--subtle #8B9096 (tokens.css:177) is 3.21:1 on white, below the 4.5:1 AA floor. Shipped ' +
      'on the founder directive of 2026-08-18 ("pixel perfect ... to colours") over the ' +
      'AA-passing #707478 it replaced.',
    expires: '2026-11-19',
  },

  // `link-in-text-block` WAS HERE AND IS FIXED, 2026-08-30. It was carried as an open defect
  // rather than an accepted trade -- 6 of 16 tests, the breadcrumb link at #2447c9 on --subtle
  // #8B9096, 2.31:1 against a 3:1 floor with `a{text-decoration:none}` (mumchimp.css:7) leaving
  // nothing to fall back on -- and the entry said the fix was one rule in globals.css that needed
  // a founder decision. He gave it on 2026-08-30 ("really polish the site thoroughly as best as
  // we possibly can, attention to details"). `.crumb a` and `.src a` now carry an underline
  // (globals.css, `@layer components`); the colours are untouched. The entry is deleted rather
  // than renewed, which is what an exception with an expiry is for.
};

/** An exception that has run out of time is not an exception. */
function expired(id: string, today: Date): boolean {
  return today.toISOString().slice(0, 10) > KNOWN[id].expires;
}

// Every known id that actually fired somewhere in this run. Checked at the end: an exception for
// a finding that no longer exists is a fence around nothing, and it hides the next regression in
// the same rule.
const fired = new Set<string>();

// The pages a buyer actually walks through. `/pack/...` is discovered rather than hardcoded
// because slugs come from the live catalogue and any pinned one eventually 404s.
const ROUTES = ['/', '/ideas', '/kill-log', '/about', '/pricing', '/how-it-works', '/faq'];

const WIDTHS = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'desktop', width: 1280, height: 900 },
];

type Violation = {
  id: string;
  impact?: string | null;
  help: string;
  nodes: { target: unknown[] }[];
};

function report(route: string, width: string, violations: Violation[]): string {
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
    .concat(`\n  (${route} at ${width})`);
}

/**
 * Splits one axe run three ways and records what the known exceptions did. `blocking` is what the
 * caller asserts on; the rest is printed.
 */
function triage(results: { violations: Violation[] }, route: string, width: string) {
  const serious = results.violations.filter((v) => BLOCKING.includes(v.impact ?? ''));
  const advisory = results.violations.filter((v) => !BLOCKING.includes(v.impact ?? ''));

  const today = new Date();
  const blocking = serious.filter((v) => !(v.id in KNOWN) || expired(v.id, today));
  for (const v of serious) if (v.id in KNOWN) fired.add(v.id);

  const excused = serious.filter((v) => v.id in KNOWN && !expired(v.id, today));
  if (excused.length) {
    console.log(
      `known and accepted on ${route} at ${width}:\n` +
        excused.map((v) => `  ${v.id} (until ${KNOWN[v.id].expires}) — ${KNOWN[v.id].reason}`).join('\n'),
    );
  }
  if (advisory.length) {
    // Printed, never gating. The record matters: a moderate finding that stays for months is
    // how a serious one arrives unnoticed in the same component.
    console.log(`advisory (not gating) on ${route} at ${width}:\n${report(route, width, advisory)}`);
  }
  return blocking;
}

for (const vp of WIDTHS) {
  for (const route of ROUTES) {
    test(`a11y: ${route} at ${vp.width}px`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      const res = await page.goto(route);
      expect(res?.status(), `${route} did not render`).toBeLessThan(400);

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze();

      const blocking = triage(results, route, vp.name);
      expect(blocking, report(route, vp.name, blocking)).toHaveLength(0);
    });
  }
}

test('a11y: a pack page at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const href = await page.locator('a[href^="/pack/"]').first().getAttribute('href');
  expect(href, 'the home page listed no pack to open').toBeTruthy();

  await page.goto(href!);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  const blocking = triage(results, href!, 'mobile');
  expect(blocking, report(href!, 'mobile', blocking)).toHaveLength(0);
});

/**
 * Declared last so it runs last: by this point every route above has reported.
 *
 * Two ways an exception rots, and both fail here rather than quietly widening the gate. It can
 * run out of time, or the finding it excuses can be fixed -- at which point the entry stops being
 * an exception and becomes a blind spot in front of the next regression in that same rule.
 */
test('a11y: the known-exception list is still true', () => {
  const today = new Date();
  const stale = Object.keys(KNOWN).filter((id) => !fired.has(id));
  const overdue = Object.keys(KNOWN).filter((id) => expired(id, today));

  expect(
    overdue,
    `these exceptions have expired and must be fixed or re-argued with a new date:\n` +
      overdue.map((id) => `  ${id} — expired ${KNOWN[id].expires}`).join('\n'),
  ).toHaveLength(0);

  expect(
    stale,
    `these exceptions no longer fire anywhere. Delete them from KNOWN in this file:\n` +
      stale.map((id) => `  ${id} — ${KNOWN[id].reason}`).join('\n'),
  ).toHaveLength(0);
});
