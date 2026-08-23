import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 390, height: 844 } });
await p.goto('http://localhost:3000/', { waitUntil: 'networkidle', timeout: 60000 });
const out = await p.evaluate(() => {
  const r = [];
  const tile = document.querySelector('a.htile');
  if (tile) {
    const grid = tile.parentElement;
    r.push(`grid ${grid.className} w=${grid.getBoundingClientRect().width} cols=${getComputedStyle(grid).gridTemplateColumns}`);
    r.push(`tile w=${tile.getBoundingClientRect().width} scrollW=${tile.scrollWidth}`);
    for (const c of tile.querySelectorAll('*')) {
      const cr = c.getBoundingClientRect();
      if (cr.width > 340) r.push(`  ${c.tagName}.${c.className} w=${Math.round(cr.width)} sw=${c.scrollWidth} :: ${(c.textContent||'').slice(0,50)}`);
    }
  }
  const side = document.querySelector('span.side');
  if (side) {
    let e = side, chain = [];
    while (e && chain.length < 5) { const q = e.getBoundingClientRect(); chain.push(`${e.tagName}.${typeof e.className==='string'?e.className:''} w=${Math.round(q.width)} sw=${e.scrollWidth} ovf=${getComputedStyle(e).overflowX}`); e = e.parentElement; }
    r.push('side chain: ' + chain.join(' <- '));
  }
  return r;
});
console.log(out.join('\n'));
await b.close();
