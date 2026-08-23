import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 390, height: 844 } });
const out = [];
for (const [route, sel] of [['/', 'div.w-max'], ['/kill-log', 'table.min-w-\\[44rem\\]'], ['/pricing', 'table.min-w-\\[38rem\\]']]) {
  await p.goto('http://localhost:3000' + route, { waitUntil: 'networkidle', timeout: 60000 });
  out.push(await p.evaluate((s) => {
    const el = document.querySelector(s.replace(/\\\\/g, '\\'));
    if (!el) return `${s}: not found`;
    let e = el.parentElement, chain = [];
    while (e && chain.length < 3) { chain.push(`${e.tagName} ovfX=${getComputedStyle(e).overflowX} w=${Math.round(e.getBoundingClientRect().width)}`); e = e.parentElement; }
    return `${s} -> ${chain.join(' <- ')}`;
  }, sel));
}
console.log(out.join('\n'));
await b.close();
