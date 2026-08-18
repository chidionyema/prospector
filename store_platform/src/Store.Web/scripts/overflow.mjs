/* Finds every element that sticks out past a 390px viewport, on every page. */
import { chromium } from 'playwright';
const routes = ['/', '/collections', '/how-it-works', '/kill-log', '/faq', '/pricing', '/about', '/account', '/refund', '/sample'];
const b = await chromium.launch();
for (const r of routes) {
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  try {
    await p.goto(`http://localhost:3000${r}`, { waitUntil: 'networkidle', timeout: 60000 });
    await p.waitForTimeout(400);
    const out = await p.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const bad = [];
      for (const el of document.querySelectorAll('body *')) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0) continue;
        if (rect.right > vw + 1 || rect.left < -1) {
          const parent = el.parentElement;
          const prect = parent ? parent.getBoundingClientRect() : null;
          if (prect && prect.right > vw + 1) continue; // report the outermost only
          bad.push(`${el.tagName.toLowerCase()}.${(el.className || '').toString().split(/\s+/).slice(0,4).join('.')} right=${Math.round(rect.right)} w=${Math.round(rect.width)} :: ${(el.textContent||'').trim().slice(0,50)}`);
        }
      }
      return { vw, sw: document.documentElement.scrollWidth, bad: bad.slice(0, 8) };
    });
    console.log(`\n### ${r} vw=${out.vw} scrollWidth=${out.sw}`);
    out.bad.forEach((l) => console.log('  ' + l));
  } catch (e) { console.log(`\n### ${r} ERROR ${e.message.slice(0,80)}`); }
  await p.close();
}
await b.close();
