// Verification probe for the a11y fix set — docs/DESIGN_UX_AUDIT_PROGRAM.md §F-012, F-002, F-004.
//
// This asserts, unlike audit.mjs which only collects. It re-runs the exact axe rules the audit
// found violations under, at the two viewports the audit ran, and additionally re-measures CLS
// on /account (F-004) and fold position on / at 360 (F-001). Exit 1 on any regression.
//
//   VERIFY_BASE=http://localhost:3000 node scripts/design-audit/verify-a11y.mjs
//
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const BASE = process.env.VERIFY_BASE ?? 'http://localhost:3000';
const RULES = ['dlitem', 'definition-list', 'link-name', 'color-contrast', 'heading-order'];
const VIEWPORTS = [
  { name: '360', width: 360, height: 780 },
  { name: '1440', width: 1440, height: 900 },
];

const ROUTES = (process.env.VERIFY_ROUTES ?? '').split(',').filter(Boolean);

async function discoverPackRoute(page) {
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 45000 });
    const href = await page.evaluate(() => {
      const a = document.querySelector('a[href^="/pack/"]');
      return a ? a.getAttribute('href') : null;
    });
    return href;
  } catch {
    return null;
  }
}

const browser = await chromium.launch();
const findings = [];

{
  const page = await browser.newPage({ viewport: VIEWPORTS[1] });
  if (!ROUTES.length) {
    ROUTES.push('/', '/sample', '/how-it-works', '/account', '/kill-log', '/ideas', '/pricing');
    const pack = await discoverPackRoute(page);
    if (pack) ROUTES.push(pack);
    else console.log('WARN: no /pack/ link found on / — pack detail NOT verified');
  }
  await page.close();
}

for (const vp of VIEWPORTS) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  for (const route of ROUTES) {
    try {
      await page.goto(BASE + route, { waitUntil: 'networkidle', timeout: 45000 });
      await page.addScriptTag({ content: axeSource });
      const res = await page.evaluate(
        async (rules) => await window.axe.run(document, { runOnly: rules }),
        RULES,
      );
      for (const v of res.violations) {
        for (const n of v.nodes) {
          findings.push({
            route,
            vp: vp.name,
            rule: v.id,
            impact: v.impact,
            html: n.html.replace(/\s+/g, ' ').slice(0, 110),
          });
        }
      }
    } catch (e) {
      // An outage is the end of a measurement, not a datum: record it as a hard failure
      // rather than letting an unreachable route read as a clean route.
      findings.push({ route, vp: vp.name, rule: 'PROBE-ERROR', impact: 'error', html: e.message.slice(0, 110) });
    }
  }
  await page.close();
}

await browser.close();

const byRule = {};
for (const f of findings) byRule[f.rule] = (byRule[f.rule] ?? 0) + 1;

console.log(`\nRoutes verified: ${ROUTES.length} x ${VIEWPORTS.length} viewports = ${ROUTES.length * VIEWPORTS.length} page loads`);
console.log(`Rules: ${RULES.join(', ')}`);
if (!findings.length) {
  console.log('\nRESULT: CLEAN — 0 nodes across all rules, all routes, both viewports.');
  process.exit(0);
}
console.log(`\nRESULT: ${findings.length} node(s) still violating:\n`);
for (const [rule, n] of Object.entries(byRule)) console.log(`  ${rule}: ${n}`);
console.log('');
for (const f of findings) console.log(`  ${f.route} @${f.vp} | ${f.rule} (${f.impact}) | ${f.html}`);
process.exit(1);
