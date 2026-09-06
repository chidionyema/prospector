import { chromium } from 'playwright';

const BASE = process.env.SITE || 'https://mumchimp.com';
const OUT  = process.env.OUT  || '.';
const PAGES = (process.env.PAGES || '/,/ideas,/how-it-works,/pricing,/faq,/about,/sample,/kill-log').split(',');
const VIEWS = [{ n: 'desktop', w: 1440, h: 900 }, { n: 'mobile', w: 390, h: 844 }];

// Runs IN the page. Returns concrete, measured layout defects.
const AUDIT = () => {
  const px = n => Math.round(n);
  const label = e => {
    const cls = (typeof e.className === 'string' ? e.className : '').trim().split(/\s+/).slice(0, 4).join('.');
    const txt = (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    return `${e.tagName.toLowerCase()}${cls ? '.' + cls : ''} "${txt}"`;
  };
  const all = [...document.querySelectorAll('body *')].filter(e => {
    const cs = getComputedStyle(e);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && e.getBoundingClientRect().width > 0;
  });

  const vw = document.documentElement.clientWidth;
  const out = { scrollWidth: document.documentElement.scrollWidth, clientWidth: vw, past: [], selfOverflow: [], escapes: [] };

  // A. anything sticking out past the right edge of the page
  for (const e of all) {
    const r = e.getBoundingClientRect();
    if (r.right > vw + 1 && r.width < vw * 3) out.past.push({ el: label(e), left: px(r.left), right: px(r.right), over: px(r.right - vw) });
  }

  // B. a box whose own content is wider or taller than the box, with nothing clipping it
  for (const e of all) {
    const cs = getComputedStyle(e);
    if (cs.overflowX === 'visible' && e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0)
      out.selfOverflow.push({ el: label(e), axis: 'x', box: e.clientWidth, content: e.scrollWidth });
    if (cs.overflowY === 'visible' && e.scrollHeight > e.clientHeight + 1 && e.clientHeight > 0 && cs.height !== 'auto')
      out.selfOverflow.push({ el: label(e), axis: 'y', box: e.clientHeight, content: e.scrollHeight });
  }

  // C. text escaping a CARD: a painted container (border or background) whose descendant text
  //    is drawn outside it. This is the "text falling out of cards" defect, measured.
  const isCard = e => {
    const cs = getComputedStyle(e);
    const painted = cs.borderTopWidth !== '0px' || (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent');
    const r = e.getBoundingClientRect();
    return painted && r.width > 80 && r.height > 40 && cs.overflow === 'visible';
  };
  for (const card of all.filter(isCard)) {
    const cr = card.getBoundingClientRect();
    for (const kid of card.querySelectorAll('*')) {
      if (!kid.textContent || !kid.textContent.trim()) continue;
      if (kid.children.length) continue;                       // leaf text only
      const kcs = getComputedStyle(kid);
      if (kcs.position === 'absolute' || kcs.position === 'fixed') continue;
      const kr = kid.getBoundingClientRect();
      if (kr.width === 0) continue;
      const dr = kr.right - cr.right, db = kr.bottom - cr.bottom, dl = cr.left - kr.left;
      const worst = Math.max(dr, db, dl);
      if (worst > 2) out.escapes.push({ card: label(card), text: label(kid), right: px(dr), bottom: px(db), left: px(dl) });
    }
  }
  return out;
};

const browser = await chromium.launch();
let defects = 0;
for (const view of VIEWS) {
  const ctx = await browser.newContext({ viewport: { width: view.w, height: view.h }, deviceScaleFactor: 1 });
  for (const path of PAGES) {
    const page = await ctx.newPage();
    const url = BASE + path;
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
    } catch { try { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }); } catch (e) { console.log(`\n### ${view.n} ${path}  LOAD FAILED ${e.message.split('\n')[0]}`); await page.close(); continue; } }
    await page.waitForTimeout(1200);
    const r = await page.evaluate(AUDIT);
    const slug = (path === '/' ? 'home' : path.replace(/\//g, '-').replace(/^-/, ''));
    await page.screenshot({ path: `${OUT}/${view.n}-${slug}.png`, fullPage: true });
    const bad = r.past.length + r.selfOverflow.length + r.escapes.length + (r.scrollWidth > r.clientWidth + 1 ? 1 : 0);
    defects += bad;
    console.log(`\n### ${view.n} ${path}   ${bad ? bad + ' DEFECTS' : 'clean'}`);
    if (r.scrollWidth > r.clientWidth + 1) console.log(`  PAGE SCROLLS SIDEWAYS: document is ${r.scrollWidth}px wide in a ${r.clientWidth}px viewport (+${r.scrollWidth - r.clientWidth})`);
    r.past.slice(0, 8).forEach(d => console.log(`  PAST RIGHT EDGE +${d.over}px  ${d.el}`));
    r.selfOverflow.slice(0, 8).forEach(d => console.log(`  CONTENT > BOX (${d.axis}) box=${d.box} content=${d.content}  ${d.el}`));
    r.escapes.slice(0, 12).forEach(d => console.log(`  TEXT OUT OF CARD r+${d.right} b+${d.bottom} l+${d.left}\n      card: ${d.card}\n      text: ${d.text}`));
    await page.close();
  }
  await ctx.close();
}
await browser.close();
console.log(`\nTOTAL DEFECTS ${defects}`);
