import { chromium } from 'playwright';

const BASE = process.env.SITE || 'https://mumchimp.com';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });

const probe = async (path, sel) => {
  const page = await ctx.newPage();
  await page.goto(BASE + path, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(800);
  const r = await page.evaluate(([sel]) => {
    const out = [];
    for (const e of document.querySelectorAll(sel)) {
      const cs = getComputedStyle(e);
      const b = e.getBoundingClientRect();
      out.push({
        sel,
        cls: (typeof e.className === 'string' ? e.className : ''),
        text: (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 70),
        rect: `${Math.round(b.width)}x${Math.round(b.height)}`,
        client: `${e.clientWidth}x${e.clientHeight}`,
        scroll: `${e.scrollWidth}x${e.scrollHeight}`,
        css: `display:${cs.display} dir:${cs.flexDirection} height:${cs.height} align:${cs.alignItems} wrap:${cs.flexWrap} font:${cs.fontFamily.split(',')[0]} size:${cs.fontSize} overflow:${cs.overflow}`,
        html: e.outerHTML.slice(0, 260),
      });
    }
    return out;
  }, [sel]);
  console.log(`\n===== ${path}  ${sel}  (${r.length} match)`);
  r.forEach(x => console.log(`  cls=${x.cls}\n  rect=${x.rect} client=${x.client} scroll=${x.scroll}\n  ${x.css}\n  text="${x.text}"\n  html=${x.html}\n`));
  await page.close();
};

await probe('/kill-log', 'ul.bars');
await probe('/kill-log', 'ul.bars > li');
await probe('/', '.gridkey');
await probe('/', '.gridkey b');
await probe('/', '.gridkey span');
await browser.close();
