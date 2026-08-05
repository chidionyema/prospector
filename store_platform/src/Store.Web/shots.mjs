import { chromium } from '@playwright/test';
import fs from 'node:fs';

const BASE = 'http://localhost:3210';
const OUT = 'shots';
fs.mkdirSync(OUT, { recursive: true });

const pages = [
  ['home', '/'],
  ['ideas', '/ideas'],
  ['sample', '/sample'],
  ['faq', '/faq'],
  ['how-it-works', '/how-it-works'],
  ['pricing', '/pricing'],
  ['about', '/about'],
  ['kill-log', '/kill-log'],
];

const browser = await chromium.launch();

// grab a real pack id from the catalog
const probe = await browser.newPage();
await probe.goto(BASE + '/', { waitUntil: 'networkidle' });
const packHref = await probe.locator('a[href^="/pack/"]').first().getAttribute('href');
if (packHref) pages.push(['pack', packHref]);
await probe.close();

for (const [device, viewport] of [
  ['desktop', { width: 1440, height: 900 }],
  ['mobile', { width: 390, height: 844 }],
]) {
  const ctx = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    isMobile: device === 'mobile',
    hasTouch: device === 'mobile',
  });
  for (const [name, path] of pages) {
    const page = await ctx.newPage();
    try {
      await page.goto(BASE + path, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(600);
      // fold shot
      await page.screenshot({ path: `${OUT}/${device}-${name}-fold.png` });
      // full page shot (capped)
      await page.screenshot({ path: `${OUT}/${device}-${name}-full.png`, fullPage: true, animations: 'disabled', timeout: 90000 });

      // measure horizontal overflow
      const overflow = await page.evaluate(() => {
        const de = document.documentElement;
        return { scrollW: de.scrollWidth, clientW: de.clientWidth };
      });
      if (overflow.scrollW > overflow.clientW + 1) {
        console.log(`OVERFLOW ${device} ${name}: scrollW=${overflow.scrollW} clientW=${overflow.clientW}`);
      }
    } catch (e) {
      console.log(`FAIL ${device} ${name}: ${e.message.split('\n')[0]}`);
    }
    await page.close();
  }
  await ctx.close();
}

await browser.close();
console.log('done');
