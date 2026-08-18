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

const norm = (s) => s.replace(/\s+/g, ' ').trim();

/**
 * The comparison key. Lowercased and stripped of everything that is not a letter or a digit.
 *
 * Two reasons, both of which produced a false miss on the first run. `innerText` returns text as
 * RENDERED, so a class carrying `text-transform:uppercase` (`.eyebrow`, every label on the site)
 * comes back in caps and never matches the drawing's sentence case. And punctuation legitimately
 * differs: the drawing writes an em-dash, our source is barred from carrying one, so the same
 * sentence reads `A - B` in the drawing and `A, B` on the page. Neither is a missing section, and
 * a check that cries wolf about them gets ignored, which is how the real misses survive.
 */
const key = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '');

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
  if (parts.length) return parts;

  /*
   * ONLY `index.html` NUMBERS ITS SECTIONS. The first run of this script reported twelve findings
   * on the home page and NOTHING on the other nine, and printed a page header for each of them,
   * so it read as nine clean pages. That is the same failure it was written to catch, committed
   * by the check itself: silence presented as a pass.
   *
   * Every drawing does use `<section>`, so that is the fallback boundary, named by its first
   * heading. Anything before the first `<section>` is a section too, or the page's opening would
   * go unchecked.
   */
  const chunks = body.split(/(?=<section\b)/i);
  return chunks
    .map((html, i) => {
      const h = /<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/i.exec(html);
      const name = h ? norm(h[1].replace(/<[^>]*>/g, '')).slice(0, 48) : 'opening';
      return { n: String(i + 1), name, html };
    })
    .filter((s) => s.html.trim());
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
  const built = key(norm(await page.evaluate(() => document.body.innerText)));
  console.log(`\n═══ ${route} ═══`);
  for (const sec of sections(html)) {
    const lines = prose(sec.html);
    if (!lines.length) continue;
    const absent = lines.filter((l) => !built.includes(key(l)));
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
