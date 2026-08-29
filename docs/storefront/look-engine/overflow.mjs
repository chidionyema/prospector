// @ledger read-only | node overflow.mjs | Finds any element that makes the PAGE scroll sideways, at seven widths.
/* THE SIDEWAYS-SCROLL GATE.
 *
 * It grades one thing: does the page scroll horizontally, and if so, what is sticking out.
 *
 * It used to grade something else, and reported six offenders at 320px on a page whose
 * `scrollWidth` equalled its `clientWidth` at every width — that is, on a page that does not
 * scroll sideways at all. The offenders were the look-switcher's chips. That strip is
 * `overflow-x: auto` by design; its children are SUPPOSED to sit beyond the viewport, because
 * that is what a scrolling strip is. A gate that cannot tell a designed scroll region from a
 * layout failure prints a list nobody can act on, exits 0, and teaches every reader to ignore
 * it. Measured 2026-08-20: 6 findings, 0 of them real.
 *
 * So an element is only reported when no ancestor between it and the root scrolls horizontally.
 * The verdict line comes first, and a real finding exits non-zero, so this can gate a build.
 */
/* Playwright is not a dependency of this prototype; it is borrowed from the storefront's own
 * node_modules. It is resolved from THIS file's own location, so it works in the main
 * checkout and in every worktree. It stays overridable for a machine that keeps it elsewhere:
 *   PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node <tool>.mjs
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || new URL('../../../store_platform/src/Store.Web/node_modules/playwright/index.mjs', import.meta.url).href);

const WIDTHS = [320, 390, 744, 834, 1024, 1440, 2560];
const b = await chromium.launch();
const rows = [];
for (const w of WIDTHS) {
  const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
  const p = await ctx.newPage();
  await p.goto('file://' + process.cwd() + '/looks-engine.html', { waitUntil: 'networkidle' });
  rows.push(await p.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const scrolls = (el) => {
      const s = getComputedStyle(el);
      return /auto|scroll|hidden/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1;
    };
    /* An element inside a horizontally scrolling box is not overflowing the PAGE; the box owns
       it. Walk up and let any such ancestor absolve it. */
    const inScroller = (el) => {
      for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
        if (scrolls(a)) return true;
      }
      return false;
    };
    const out = [];
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.right <= vw + 0.5 && r.left >= -0.5) continue;
      if (inScroller(el)) continue;
      out.push({
        sel: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim()
          ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
        left: +r.left.toFixed(1), right: +r.right.toFixed(1), over: +(r.right - vw).toFixed(1),
      });
    }
    return {
      vw,
      scrollW: document.documentElement.scrollWidth,
      doc: document.documentElement.scrollWidth - vw,
      out,
    };
  }));
  await ctx.close();
}
await b.close();

const bad = rows.filter((r) => r.doc > 1 || r.out.length);
if (bad.length) {
  console.log(`FAIL — ${bad.length} of ${rows.length} widths scroll sideways`);
  for (const r of bad) {
    console.log(`  ${r.vw}px  doc overflows by ${r.doc}px  ${JSON.stringify(r.out.slice(0, 6))}`);
  }
} else {
  console.log(`ALL PASS — no sideways scroll and no escaping element at ${WIDTHS.length} widths (${WIDTHS.join(', ')})`);
}
for (const r of rows) {
  console.log(`  ${String(r.vw).padStart(4)}px  scrollWidth ${r.scrollW}  escaping ${r.out.length}`);
}
process.exitCode = bad.length ? 1 : 0;
