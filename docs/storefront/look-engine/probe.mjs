// @ledger read-only | node probe.mjs | Prints the ancestor chain and geometry behind a layout finding, so a finding is diagnosed rather than assumed.
/* Playwright is not a dependency of this prototype; it is borrowed from the storefront's own
 * node_modules. The path is absolute because that is where it lives on this machine, and it
 * is overridable because that will not be true on the next one:
 *   PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node <tool>.mjs
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || '/private/tmp/claude-501/-Users-chidionyema-Documents-code-prospector/3fa47c70-c6d2-4273-9620-19dc9810b132/scratchpad/wt-redesign/store_platform/src/Store.Web/node_modules/playwright/index.mjs');
const FILE = 'file://' + process.cwd() + '/looks-engine.html';
const browser = await chromium.launch();
for (const [look, vpn, w, h] of [['prospectus','tablet-834',834,1194], ['ledger','laptop-1440',1440,900]]) {
  const ctx = await browser.newContext({ viewport:{width:w,height:h}, colorScheme:'light' });
  const page = await ctx.newPage();
  await page.goto(FILE, { waitUntil:'networkidle' });
  await page.evaluate((i)=>document.querySelector(`.chip[data-id="${i}"]`).click(), look);
  await page.waitForTimeout(120);
  const out = await page.evaluate(() => {
    const dl = document.querySelector('.masthead__dateline');
    const cs = getComputedStyle(dl);
    const kids = [...dl.children].map((el) => {
      const r = el.getBoundingClientRect(); const k = getComputedStyle(el);
      return `${el.tagName.toLowerCase()} "${el.textContent.trim().slice(0,16)}" ${r.left.toFixed(0)},${r.top.toFixed(0)} ${r.width.toFixed(0)}x${r.height.toFixed(0)} [disp:${k.display} pos:${k.position} ml:${k.marginLeft} mr:${k.marginRight} flex:${k.flex}]`;
    });
    const wm = document.querySelector('.wordmark em');
    const wr = wm.getBoundingClientRect(); const wk = getComputedStyle(wm);
    return { html: dl.outerHTML.slice(0, 420),
      dl: `${dl.getBoundingClientRect().left.toFixed(0)},${dl.getBoundingClientRect().top.toFixed(0)} ${dl.getBoundingClientRect().width.toFixed(0)}x${dl.getBoundingClientRect().height.toFixed(0)} [disp:${cs.display} wrap:${cs.flexWrap} just:${cs.justifyContent} gap:${cs.gap} ws:${cs.whiteSpace}]`,
      kids,
      wordmark: `em "${wm.textContent}" ${wr.left.toFixed(0)},${wr.top.toFixed(0)} ${wr.width.toFixed(0)}x${wr.height.toFixed(0)} font ${wk.fontSize}/${wk.lineHeight} ${wk.fontFamily.split(',')[0]}` };
  });
  console.log(`\n===== ${look} @ ${vpn} =====\ndateline ${out.dl}`);
  for (const k of out.kids) console.log('   ' + k);
  console.log('   ' + out.wordmark);
  console.log('   HTML: ' + out.html.replace(/\s+/g, ' '));
  await ctx.close();
}
await browser.close();
