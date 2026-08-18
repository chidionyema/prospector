/**
 * SECTION LEDGER: the drawing's own words, checked against the built page, section by section.
 *
 * Why not the CSS probe next door: comparing computed styles can only speak about classes the
 * built page shares with the drawing. A section rebuilt in different markup shares none, so the
 * probe says "class missing" and cannot say the section is a different thing entirely. That is
 * exactly the failure that kept reaching the founder.
 *
 * The drawing's TEXT is the specification, and it cannot be argued with. Each drawing is split on
 * its own `<!-- N · NAME -->` comments, which is the author's own section list, so the ledger is
 * complete by construction rather than by my reading. For each section it takes the prose the
 * drawing prints and asks one question of the built page: is this sentence on it.
 *
 * A section at 0% was never built. A section in the middle was half-built or reworded. A section
 * at 100% still has to be looked at, but a section below 100% does not need looking at to know it
 * is wrong. Data that changes per pack (titles, prices, counts) is skipped: only sentences with
 * no digits and at least five words count, which is the copy a drawing is actually specifying.
 *
 * Run: node scripts/sections.mjs [page ...]
 */
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const ROOT = path.resolve(process.cwd(), '../../..');
const PAGES = [
  ['index.html', '/'], ['collections.html', '/collections'], ['how-it-works.html', '/how-it-works'],
  ['kill-log.html', '/kill-log'], ['faq.html', '/faq'], ['pricing.html', '/pricing'],
  ['about.html', '/about'], ['account.html', '/account'], ['refund.html', '/refund'],
  ['sample.html', '/sample'],
];

const norm = (s) => s.replace(/\s+/g, ' ').replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[—–]/g, '-').trim();

/** Split a drawing into its author-declared sections. */
function sections(html) {
  const main = /<main[^>]*>([\s\S]*)<\/main>/.exec(html);
  const body = main ? main[1] : html;
  const parts = [];
  const re = /<!--\s*(\d+)\s*·\s*([^>]*?)-->/g;
  let m, last = null;
  while ((m = re.exec(body)) !== null) {
    if (last) parts.push({ n: last.n, name: last.name, html: body.slice(last.at, m.index) });
    last = { n: m[1], name: m[2].trim(), at: m.index };
  }
  if (last) parts.push({ n: last.n, name: last.name, html: body.slice(last.at) });
  return parts;
}

/** The prose a drawing prints: text nodes only, no markup, no data. */
function prose(html) {
  const text = html.replace(/<(script|style)[\s\S]*?<\/\1>/g, '').replace(/<!--[\s\S]*?-->/g, '');
  const runs = [];
  for (const raw of text.split(/<[^>]*>/)) {
    const t = norm(raw);
    if (!t) continue;
    if (/\d/.test(t)) continue;                     // per-pack data, not copy
    if (t.split(' ').length < 5) continue;          // labels and single words
    runs.push(t);
  }
  return [...new Set(runs)];
}

const only = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
let worst = [];
for (const [file, route] of PAGES) {
  if (only.length && !only.includes(file.replace('.html', ''))) continue;
  const html = await readFile(path.join(ROOT, 'docs/design/mumchimp-build-bundle/mockups', file), 'utf8');
  await page.goto('http://localhost:3000' + route, { waitUntil: 'networkidle', timeout: 60000 });
  const built = norm(await page.evaluate(() => document.body.innerText));
  console.log(`\n═══ ${route} ═══`);
  for (const sec of sections(html)) {
    const lines = prose(sec.html);
    if (!lines.length) continue;
    const absent = lines.filter((l) => !built.includes(l));
    const pct = Math.round(((lines.length - absent.length) / lines.length) * 100);
    const mark = pct === 100 ? 'OK  ' : pct >= 60 ? 'PART' : 'GONE';
    console.log(`${mark} ${pct.toString().padStart(3)}%  ${sec.n} · ${sec.name}  (${lines.length - absent.length}/${lines.length})`);
    if (pct < 100) for (const a of absent.slice(0, 4)) console.log(`         - ${a.slice(0, 110)}`);
    if (pct < 100) worst.push({ route, sec: `${sec.n} · ${sec.name}`, pct });
  }
}
await browser.close();
worst.sort((a, b) => a.pct - b.pct);
console.log(`\n═══ WORST FIRST ═══`);
for (const w of worst) console.log(`${w.pct.toString().padStart(3)}%  ${w.route}  ${w.sec}`);
console.log(`\n${worst.length} sections below 100%`);
