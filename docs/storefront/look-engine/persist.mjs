// @ledger read-only | node persist.mjs | Gate A45. Rolls a look, reloads, and checks it is still there — over http, because file:// has no storage.
/* GATE A45 — the console can add a look without a deploy.
 *
 * The roll button was the "add" half. This is the half that makes it real: a look that
 * disappears on reload has not been added to anything, it has been previewed. The check
 * runs the actual page in an actual browser and reloads it, because the claim is about
 * what survives a reload and nothing else can answer that.
 *
 * It serves the page over http on an ephemeral port instead of opening it from disk. A
 * file:// document has an opaque origin, so `localStorage.setItem` throws SecurityError,
 * and the engine catches it — so on file:// this gate would pass by never storing anything
 * and never reading anything back. That is the proxy defect again: the test would be
 * grading a page whose storage was switched off by the way the test opened it.
 */
/* Playwright is not a dependency of this prototype; it is borrowed from the storefront's own
 * node_modules. It is resolved from THIS file's own location, so it works in the main
 * checkout and in every worktree. It stays overridable for a machine that keeps it elsewhere:
 *   PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node <tool>.mjs
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || new URL('../../../store_platform/src/Store.Web/node_modules/playwright/index.mjs', import.meta.url).href);
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname } from 'node:path';

const HERE = process.cwd();
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.json': 'application/json' };
const server = createServer(async (req, res) => {
  const p = join(HERE, decodeURIComponent(req.url.split('?')[0]));
  try {
    const buf = await readFile(p);
    res.writeHead(200, { 'content-type': TYPES[extname(p)] || 'application/octet-stream' });
    res.end(buf);
  } catch { res.writeHead(404); res.end('no'); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${server.address().port}/looks-engine.html`;

const fails = [];
const ok = (cond, what) => { if (!cond) fails.push(what); return cond; };

const browser = await chromium.launch();

/* Everything below runs inside one try. A gate that throws prints a stack and loses the
   checks it had already collected — measured here: the mutant that switched storage off
   failed four checks and reported none of them, because step 3 then hit a chip that was
   never restored and crashed. An exception IS a failure; it is not a reason to stop
   reporting the failures already in hand. */
let before = { ids: ['roll-?'] };
try {

/* --- 1. Roll two looks, reload, and look for them. ----------------------- */
const ctx = await browser.newContext();
const page = await ctx.newPage();
await page.goto(BASE, { waitUntil: 'networkidle' });
before = await page.evaluate(async () => {
  const ids = [];
  for (let i = 0; i < 2; i++) {
    document.getElementById('rollBtn').click();
    ids.push(document.documentElement.getAttribute('data-look'));
  }
  return { ids, stored: localStorage.getItem('rolled'), chips: [...document.querySelectorAll('.chip')].map((c) => c.dataset.id) };
});
ok(before.ids.length === 2 && before.ids.every((i) => /^roll-\d+$/.test(i)),
   `the button did not produce two rolled looks: ${JSON.stringify(before.ids)}`);
ok(before.stored && JSON.parse(before.stored).length === 2,
   `localStorage.rolled is ${before.stored}, expected two numbers — file:// storage is the usual cause`);
for (const id of before.ids) ok(before.chips.includes(id), `${id} has no chip before the reload`);

await page.reload({ waitUntil: 'networkidle' });
const after = await page.evaluate((ids) => ({
  chips: [...document.querySelectorAll('.chip')].map((c) => c.dataset.id),
  known: ids.map((i) => !!LOOKS.find((l) => l.id === i)),
  /* Not just "a look with that id exists" — the SAME look. rollLook(n) is deterministic in
     n, so a restored look whose accent differs is a generator that changed underneath a
     stored number, which is the one failure this design can still have. */
  accents: ids.map((i) => { const l = LOOKS.find((x) => x.id === i); return l ? palette(l, resolved()).accent : null; }),
}), before.ids);
for (const [n, id] of before.ids.entries()) {
  ok(after.chips.includes(id), `${id} is gone from the chip strip after a reload`);
  ok(after.known[n], `${id} is not in LOOKS after a reload`);
}

/* --- 2. The same look, on a browser that has never rolled. --------------- */
const fresh = await browser.newContext();
const p2 = await fresh.newPage();
await p2.goto(BASE + '?look=' + before.ids[0], { waitUntil: 'networkidle' });
const linked = await p2.evaluate((id) => ({
  applied: document.documentElement.getAttribute('data-look'),
  accent: (() => { const l = LOOKS.find((x) => x.id === id); return l ? palette(l, resolved()).accent : null; })(),
  a11y: document.getElementById('a11y').dataset.state,
}), before.ids[0]);
ok(linked.applied === before.ids[0], `?look=${before.ids[0]} opened ${linked.applied} instead`);
ok(linked.accent === after.accents[0], `the linked look is a different colour from the rolled one: ${linked.accent} vs ${after.accents[0]}`);
ok(linked.a11y === 'good', `the linked look does not pass its own contrast audit: ${linked.a11y}`);

/* --- 3. Forgetting one. An add with no remove fills the strip forever. --- */
const forgot = await page.evaluate(async (id) => {
  const chip = document.querySelector(`.chip[data-id="${id}"]`);
  if (!chip) return { missing: 1, stored: localStorage.getItem('rolled'), chips: [] };
  chip.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
  return { stored: localStorage.getItem('rolled'), chips: [...document.querySelectorAll('.chip')].map((c) => c.dataset.id) };
}, before.ids[0]);
ok(!forgot.missing, `there was no ${before.ids[0]} chip to shift-click`);
ok(forgot.missing || !forgot.chips.includes(before.ids[0]), `shift-click left ${before.ids[0]} on the strip`);
ok(!JSON.parse(forgot.stored || '[]').includes(Number(before.ids[0].replace('roll-', ''))),
   `shift-click left ${before.ids[0]} in storage: ${forgot.stored}`);
await page.reload({ waitUntil: 'networkidle' });
const stillGone = await page.evaluate((id) => [...document.querySelectorAll('.chip')].map((c) => c.dataset.id).includes(id), before.ids[0]);
ok(!stillGone, `${before.ids[0]} came back after being forgotten`);

} catch (e) {
  fails.push('the gate threw before it finished: ' + ((e && e.message) || e));
}

await browser.close();
server.close();

console.log(`rolled ${before.ids.join(' and ')} over http, reloaded, linked and forgot one.`);
if (fails.length) { console.log(`\nA45 FAIL — ${fails.length} checks:`); for (const f of fails) console.log('  ' + f); }
else console.log('A45 PASS — a rolled look survives a reload, opens from a link on a browser that has never rolled, and can be forgotten.');
process.exitCode = fails.length ? 1 : 0;
