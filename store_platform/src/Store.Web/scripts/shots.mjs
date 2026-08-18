/* Side-by-side full-page screenshots: the drawing and the built page, desktop and phone.
   Usage: node scripts/shots.mjs <mockName> <builtPath> */
import { chromium } from 'playwright';
const [mock, route] = process.argv.slice(2);
const b = await chromium.launch();
for (const [w, h, tag] of [[1440, 1000, 'desktop'], [390, 844, 'phone']]) {
  for (const [url, kind] of [
    [`http://127.0.0.1:3001/${mock}.html`, 'mock'],
    [`http://localhost:3000${route}`, 'built'],
  ]) {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await p.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
    await p.waitForTimeout(700);
    await p.screenshot({ path: `/tmp/shots/${mock}-${tag}-${kind}.png`, fullPage: true });
    await p.close();
  }
}
await b.close();
console.log('done');
