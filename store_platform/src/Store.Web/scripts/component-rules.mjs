/**
 * COMPONENT-SHEET RULES THAT ARE MEASURABLE, MEASURED.
 *
 * `docs/design/mumchimp-build-bundle/components.html` states a rule under each of its fifteen
 * components. Most are judgements. A few are counts, and a count is a test. This script measures
 * only those, at both widths, against the RUNNING BUILD (`next start` serves `.next`, so a stale
 * server measures stale markup -- rebuild before trusting a green line here).
 *
 * Rules measured, each quoted from the sheet:
 *  - Component 12: "Never render two full buy boxes. One sticky box on desktop, or one bottom bar
 *    on mobile, plus one closing bar at the end of the page."  => at most ONE VISIBLE `.buybox`
 *    per width. A hidden second copy is allowed: that is how one DOM serves both widths.
 *  - Component 01: "One wordmark in the DOM -- the live site currently renders it twice."
 *  - Component 15: "Identical on every page, including the disclaimer. The live /ideas page ships
 *    a different one."  => the footer's element signature must be identical across pages.
 */
import { chromium } from 'playwright';

const BASE = 'http://localhost:3000';
const browser = await chromium.launch();
const page = await browser.newPage();
let failures = 0;

const goto = async (url, width) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(BASE + url, { waitUntil: 'domcontentloaded', timeout: 30000 });
};

/** Total and VISIBLE matches. Visible means it has a box and is not display:none/visibility:hidden. */
const count = (sel) =>
  page.evaluate((s) => {
    const all = [...document.querySelectorAll(s)];
    const visible = all.filter((e) => {
      const r = e.getBoundingClientRect();
      const cs = getComputedStyle(e);
      return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
    });
    return { total: all.length, visible: visible.length };
  }, sel);

const report = (ok, label, detail) => {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label.padEnd(46)} ${detail}`);
};

await goto('/', 1280);
const packUrl = await page.evaluate(() => {
  const a = document.querySelector('a[href^="/pack/"]');
  return a ? a.getAttribute('href') : null;
});
if (!packUrl) {
  console.log('FAIL  the shelf actually rendered                    no /pack/ link on /');
  await browser.close();
  process.exit(1);
}
console.log(`measuring against ${BASE}, pack page ${packUrl}`);
console.log('-'.repeat(78));

for (const width of [390, 1280]) {
  await goto(packUrl, width);
  const bb = await count('.buybox');
  report(bb.visible <= 1, `${width}px  one visible buy box`, `total=${bb.total} visible=${bb.visible}`);

  /* Component 12 again, the other half of the rule: "or one bottom bar on mobile". A single
     visible buy box is only correct if a phone buyer still has a control to press. Measured
     separately, because "zero visible buy boxes" passes the first check and fails the buyer. */
  const pay = await count('button[aria-label^="Buy"], a[aria-label^="Buy"]');
  report(pay.visible >= 1, `${width}px  a visible way to buy`, `total=${pay.total} visible=${pay.visible}`);

  await goto('/', width);
  const mark = await count('header a[aria-label], header a[href="/"]');
  report(mark.total <= 1, `${width}px  one wordmark in the header`, `total=${mark.total} visible=${mark.visible}`);
}

// Footer identity: the same tag+class signature on every page, /ideas included.
const sigOf = () =>
  page.evaluate(() => {
    const f = document.querySelector('footer');
    if (!f) return null;
    return [...f.querySelectorAll('*')]
      .filter((e) => e.tagName.toLowerCase() !== 'svg' && !e.closest('svg'))
      .map((e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : ''))
      .join(' ');
  });

await goto('/', 1280);
const home = await sigOf();
for (const path of ['/ideas', '/collections', '/kill-log', '/how-it-works', '/faq']) {
  await goto(path, 1280);
  const sig = await sigOf();
  report(sig === home, `footer identical to / on ${path}`, sig === home ? 'same signature' : 'DIFFERENT signature');
}

console.log('-'.repeat(78));
console.log(failures === 0 ? 'ALL MEASURABLE RULES HOLD' : `${failures} rule(s) broken`);
await browser.close();
process.exit(failures === 0 ? 0 : 1);
