/**
 * CLASS PARITY: the drawing's own classes, checked against the built page, by machine.
 *
 * The method this replaces was "look at a section, convert it, move on", which missed sections
 * because the list of sections lived in my head. This list is generated FROM the twelve drawings,
 * so it cannot be short. For every class the drawing uses on a page, it asks the built page two
 * questions: is that class on the page at all, and does the element it lands on compute the same
 * values for the properties the drawing sets on it.
 *
 * A MISS is a section that was never converted. A DIFF is a section converted in name only --
 * the class is there and something else (a Tailwind utility in a higher cascade layer, usually)
 * is overruling it. Both are invisible to a screenshot skim and to a page-height measurement.
 *
 * Run: node scripts/parity.mjs [page ...]
 */
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const ROOT = path.resolve(process.cwd(), '../../..');
const MOCK = 'http://127.0.0.1:3001';
const BUILT = 'http://localhost:3000';

/* drawing file -> built route */
const PAGES = [
  ['index.html', '/'],
  ['collections.html', '/collections'],
  ['how-it-works.html', '/how-it-works'],
  ['kill-log.html', '/kill-log'],
  ['faq.html', '/faq'],
  ['pricing.html', '/pricing'],
  ['about.html', '/about'],
  ['account.html', '/account'],
  ['refund.html', '/refund'],
  ['sample.html', '/sample'],
  ['pack.html', null],
  ['404.html', null],
];

/* The properties worth comparing: the ones a drawing actually specifies. Colour and type first,
   because those are what "looks nothing like it" means; box metrics after. */
const PROPS = [
  'display', 'gridTemplateColumns', 'flexDirection', 'flexWrap', 'gap',
  'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'fontStyle',
  'color', 'backgroundColor', 'borderTopWidth', 'borderBottomWidth', 'borderLeftWidth',
  'borderColor', 'borderRadius', 'paddingTop', 'paddingLeft', 'marginTop', 'marginBottom',
  'maxWidth', 'textAlign', 'textTransform',
];

/** Every class the drawing's own stylesheet styles, in the order it declares them. */
function drawingClasses(html) {
  const style = /<style[^>]*>([\s\S]*?)<\/style>/g;
  const found = new Set();
  let m;
  while ((m = style.exec(html)) !== null) {
    for (const sel of m[1].matchAll(/(^|[\s,{}])\.([a-zA-Z][\w-]*)/g)) found.add(sel[2]);
  }
  return [...found];
}

async function snap(page, url, classes) {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  return page.evaluate(
    ({ classes, props }) => {
      const out = {};
      for (const c of classes) {
        const el = document.querySelector('.' + CSS.escape(c));
        if (!el) { out[c] = null; continue; }
        const cs = getComputedStyle(el);
        const rec = {};
        for (const p of props) rec[p] = cs[p];
        out[c] = rec;
      }
      return out;
    },
    { classes, props: PROPS },
  );
}

/**
 * Noise the comparison must not report, or the real misses drown in it.
 *  - The font STACK differs by design: the drawing names `Inter, system-ui`, the built site loads
 *    Inter Variable with a full fallback chain. Same typeface. Only a different FAMILY counts.
 *  - Sub-pixel and one-pixel box differences are fluid-layout rounding, not a design difference.
 */
function family(v) {
  const first = String(v).split(',')[0].replace(/["']/g, '').toLowerCase();
  if (first.includes('inter')) return 'inter';
  if (first.includes('mono') || first.includes('plex')) return 'mono';
  return first;
}
function noisy(prop, a, b) {
  if (a === b) return true;
  if (prop === 'fontFamily') return family(a) === family(b);
  const na = parseFloat(a), nb = parseFloat(b);
  if (Number.isFinite(na) && Number.isFinite(nb) && String(a).endsWith('px') && String(b).endsWith('px')) {
    return Math.abs(na - nb) <= 1;
  }
  return false;
}

const only = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const report = [];
for (const [file, route] of PAGES) {
  if (!route) continue;
  if (only.length && !only.includes(file.replace('.html', ''))) continue;
  const html = await readFile(path.join(ROOT, 'docs/design/mumchimp-build-bundle/mockups', file), 'utf8');
  const classes = drawingClasses(html);
  const mock = await snap(page, `${MOCK}/${file}`, classes);
  const built = await snap(page, BUILT + route, classes);
  const missing = [];
  const diffs = [];
  for (const c of classes) {
    if (!mock[c]) continue;             // drawing declares it but does not use it on this page
    if (!built[c]) { missing.push(c); continue; }
    const bad = PROPS.filter((p) => noisy(p, mock[c][p], built[c][p]) === false);
    if (bad.length) diffs.push({ c, bad: bad.map((p) => `${p}: ${mock[c][p]} != ${built[c][p]}`) });
  }
  report.push({ file, route, used: classes.filter((c) => mock[c]).length, missing, diffs });
}
await browser.close();

let totalMiss = 0, totalDiff = 0;
for (const r of report) {
  totalMiss += r.missing.length;
  totalDiff += r.diffs.length;
  console.log(`\n### ${r.route}  (${r.used} classes drawn)  MISSING ${r.missing.length}  DIFF ${r.diffs.length}`);
  if (r.missing.length) console.log('  MISSING: ' + r.missing.join(' '));
  for (const d of r.diffs.slice(0, 40)) console.log(`  .${d.c}\n      ${d.bad.slice(0, 6).join('\n      ')}`);
  if (r.diffs.length > 40) console.log(`  ... ${r.diffs.length - 40} more`);
}
console.log(`\nTOTAL  missing ${totalMiss}  diff ${totalDiff}`);
