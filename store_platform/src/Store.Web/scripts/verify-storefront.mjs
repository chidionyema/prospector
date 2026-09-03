/**
 * THE LIVE-DEFECT SWEEP. Founder's fix prompt, 2026-08-18, checks D1-D8, run against a real
 * server at two widths rather than read off a screenshot.
 *
 * Run it:  node scripts/verify-storefront.mjs          (localhost:3000)
 *          SITE=https://mumchimp.com node scripts/verify-storefront.mjs
 *          SHOTS=/tmp/shots node scripts/verify-storefront.mjs   (also writes full-page PNGs)
 *
 * WHAT IT ASSERTS, AND THE ONE THING THAT MAKES IT HONEST. Every page, both widths: no text ends
 * in an ellipsis or is vertically clipped (D3a), no horizontal page overflow, nothing escapes its
 * card (D3b). On `/` it also pins the H1 (D2) and the sample link (D6) as exact strings.
 * The honest part is the FIRST check: `the shelf actually rendered`. On its first run the local
 * build had no NEXT_PUBLIC_API_URL, every catalogue fetch died ECONNREFUSED, the shelf rendered
 * zero rows, and all nine checks went green because there was nothing left to clip or overflow. A
 * green with no cards behind it is worse than a red, so a page that should carry rows and does
 * not now fails before anything else is measured.
 *
 * Read-only. Exits non-zero on any failure.
 */
import { chromium } from 'playwright';
const BASE = process.env.SITE || 'http://localhost:3000';
/* EVERY PAGE, not just the two the founder named. "and not just landing page" was the second
   thing said about the live site, so the sweep covers the whole storefront. */
const PATHS = (process.env.PATHS || '/,/ideas,/collections,/kill-log,/how-it-works,/pricing,/sample,/pack/4e8d62f51dbce15b').split(',');
const SHOTS = process.env.SHOTS || '';
const b = await chromium.launch();
let fails = 0;
const ok = (t, c, d = '') => { console.log(`${c ? 'PASS' : 'FAIL'}  ${t}${d ? '  ' + d : ''}`); if (!c) fails++; };
for (const vp of [{ w: 390, n: '390px' }, { w: 1280, n: '1280px' }]) {
  const ctx = await b.newContext({ viewport: { width: vp.w, height: 900 } });
  for (const path of PATHS) {
    const p = await ctx.newPage();
    await p.goto(BASE + path, { waitUntil: 'networkidle', timeout: 60000 });
    await p.waitForTimeout(900);
    const r = await p.evaluate(() => {
      const cut = [], over = [], esc = [];
      for (const e of document.querySelectorAll('body *')) {
        const t = (e.textContent || '').replace(/\s+/g, ' ').trim(); if (!t) continue;
        const cs = getComputedStyle(e);
        if (e.children.length === 0 && /[…]$|\.\.\.$/.test(t)) cut.push('ELLIPSIS: ' + t.slice(-60));
        // `sr-only` headings are 1x1 clipped boxes BY DESIGN -- that is how a visually-hidden
        // heading is drawn. They are not clipped copy, so they are not a defect. Skipping them
        // by measured size rather than by class name catches every spelling of the pattern.
        const srOnly = e.clientHeight <= 1 || e.clientWidth <= 1;
        if (!srOnly && cs.overflow !== 'visible' && e.scrollHeight > e.clientHeight + 1 && e.children.length === 0) cut.push('CLIPY: ' + t.slice(0, 60));
      }
      for (const card of document.querySelectorAll('.rows,.row,.htile,.band,.sigcard')) {
        const cb = card.getBoundingClientRect();
        for (const kid of card.querySelectorAll('*')) {
          if (kid.children.length) continue;
          const kb = kid.getBoundingClientRect();
          if (kb.width === 0) continue;
          /* A HORIZONTAL SCROLL CONTAINER IS NOT AN ESCAPE. `IdenticalContentsMatrix` puts a
             `min-w-[38rem]` table inside `figure.matrix.overflow-x-auto`, which is the correct
             treatment for a wide table on a phone: the table scrolls inside its own box and the
             PAGE does not. Measured 2026-08-18, this rule reported six false escapes on /pricing
             at 390px while the page-overflow check beside it passed. */
          let scrolls = false;
          for (let a = kid.parentElement; a && a !== card.parentElement; a = a.parentElement) {
            const ox = getComputedStyle(a).overflowX;
            if (ox === 'auto' || ox === 'scroll') { scrolls = true; break; }
          }
          if (scrolls) continue;
          if (kb.right > cb.right + 1 || kb.left < cb.left - 1) esc.push(`${kid.tagName}.${(typeof kid.className === 'string' ? kid.className : '')} r+${Math.round(kb.right - cb.right)} "${(kid.textContent || '').trim().slice(0, 45)}"`);
        }
      }
      if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
        over.push(`page scrollWidth ${document.documentElement.scrollWidth} > ${document.documentElement.clientWidth}`);
      const h1 = document.querySelector('h1');
      return {
        cut, over, esc, h1: h1 ? h1.textContent.trim() : null,
        proof: [...document.querySelectorAll('.proof')].slice(0, 4).map(e => e.textContent.trim()),
        rowsHtml: document.querySelector('.rows > .row')?.outerHTML.slice(0, 900) || null,
        heroHtml: document.querySelector('.gridwrap')?.outerHTML.slice(0, 600) || null,
        tlink: document.querySelector('.tlink')?.textContent.trim() || null,
        market: [...document.querySelectorAll('.market')].slice(0, 3).map(e => e.textContent.trim()),
        barkey: document.querySelector('.barkey')?.textContent.trim() || null,
        rows: document.querySelectorAll('.rows .row, .rows > li').length,
        src: document.querySelector('.band .src')?.textContent.trim() || null,
      };
    });
    console.log(`\n----- ${vp.n} ${path}`);
    // THE HARNESS MUST NOT PASS ON AN EMPTY PAGE. First run, 2026-08-18: the local build had no
    // NEXT_PUBLIC_API_URL, every catalog fetch died ECONNREFUSED, the shelf rendered zero rows,
    // and all nine checks went green because there was nothing to clip or overflow. A green with
    // no cards behind it is worse than a red.
    if (path === '/' || path === '/ideas') ok('the shelf actually rendered', r.rows >= 10, `${r.rows} rows`);
    ok('no text ends in an ellipsis / is vertically clipped', r.cut.length === 0, r.cut.slice(0, 6).join(' | '));
    ok('no horizontal page overflow', r.over.length === 0, r.over.join(' | '));
    ok('no text escapes its card', r.esc.length === 0, r.esc.slice(0, 6).join(' | '));
    if (path === '/') {
      ok('H1 exact', r.h1 === 'Business opportunities with the research already done.' || r.h1 === "Skip 6 months of research. Launch a business or side hustle.", JSON.stringify(r.h1));
      ok('sample link exact', r.tlink === 'Read the opening of a real pack free — no email needed', JSON.stringify(r.tlink));
      if (vp.w === 1280) {
        console.log('  proof lines:', JSON.stringify(r.proof));
        console.log('  market tags:', JSON.stringify(r.market));
        console.log('  barkey:', r.barkey);
        console.log('  band src:', r.src);
        console.log('\n  ROW HTML:\n', r.rowsHtml, '\n\n  HERO FIGURE:\n', r.heroHtml);
      }
    }
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/${vp.n}${path.replace(/\//g, '_')}.png`, fullPage: true });
    await p.close();
  }
  await ctx.close();
}
await b.close();
console.log(`\n${fails === 0 ? 'ALL CHECKS PASS' : 'FAILURES: ' + fails}`);
process.exit(fails ? 1 : 0);
