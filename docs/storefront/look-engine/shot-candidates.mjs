// @ledger writes | CANDS=623,878 node shot-candidates.mjs | First-screen shots of the graded candidates, light and dark, for the founder's pick.
/* THE FIRST SCREEN, not the whole page. C36: "the first-time visitor is the only visitor who
 * matters". verify.mjs already writes a full-page shot of every look it gates; those are 5,800
 * pixels tall and they are for auditing, not for choosing. A person picking between five looks
 * is deciding on what lands in the first screen, so that is what this shoots.
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || '/Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web/node_modules/playwright/index.mjs');
import { mkdirSync } from 'node:fs';

/* split() on '' yields [''], and Number('') is 0 -- so an unset CANDS silently shot seed 0
   alongside the designed ten. Drop empties BEFORE the Number(). */
const CANDS = (process.env.CANDS || '').split(',').map((s) => s.trim())
  .filter(Boolean).map(Number).filter(Number.isFinite);
/* LOOKS= names the DESIGNED ten by id; CANDS= names rolled looks by seed. The two are selected
   differently -- a roll goes through rollNewLook, a designed look through its own chip -- so the
   shooter takes both rather than making the caller keep two scripts in step. */
const IDS = (process.env.LOOKS || '').split(',').map((s) => s.trim()).filter(Boolean);
if (!CANDS.length && !IDS.length) { console.error('CANDS=<seeds> or LOOKS=<ids> required'); process.exit(2); }
const FILE = 'file://' + process.cwd() + '/looks-engine.html';
mkdirSync('shots/first', { recursive: true });

const browser = await chromium.launch();
let n = 0, refused = [];
for (const theme of ['light', 'dark']) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 },
                                         deviceScaleFactor: 1, colorScheme: theme });
  const page = await ctx.newPage();
  await page.goto(FILE, { waitUntil: 'networkidle' });
  /* The prototype's own look switcher eats the top ~130px of a 800px viewport, so a shot that
     includes it is judging 84% of the first screen plus a control bar that does not ship. Hide
     it AFTER load -- the chips are how a designed look is selected, so it has to exist, and
     `visibility` keeps it clickable-by-script while taking it out of the picture. */
  await page.addStyleTag({ content: '.console{position:absolute !important;visibility:hidden !important;height:0 !important;overflow:hidden !important}' });
  for (const seed of CANDS) {
    /* applyLook returns null when its contrast audit refuses. A refusal here is a finding,
       not something to shoot around -- the whole claim is that it cannot happen. */
    const got = await page.evaluate((s) => window.rollNewLook(s), seed);
    if (!got) { refused.push(`roll-${seed}/${theme}`); continue; }
    await page.waitForTimeout(140);
    await page.screenshot({ path: `shots/first/roll-${seed}-${theme}.png` });
    n++;
  }
  for (const id of IDS) {
    const ok = await page.evaluate((i) => {
      const chip = document.querySelector(`.chip[data-id="${i}"]`);
      if (!chip) return false;
      chip.click(); return true;
    }, id);
    if (!ok) { refused.push(`${id}/${theme} (no chip)`); continue; }
    await page.waitForTimeout(180);
    await page.screenshot({ path: `shots/first/${id}-${theme}.png` });
    n++;
  }
  await ctx.close();
}
await browser.close();
console.log(`${n} first-screen shots written to shots/first/`);
if (refused.length) { console.log('REFUSED: ' + refused.join(', ')); process.exit(1); }
