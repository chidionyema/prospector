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
const CONTRACTIONS = [
  [/can't/g, 'cannot'], [/won't/g, 'will not'], [/n't/g, ' not'],
  [/'re/g, ' are'], [/'ll/g, ' will'], [/'ve/g, ' have'], [/it's/g, 'it is'],
  [/that's/g, 'that is'], [/here's/g, 'here is'], [/what's/g, 'what is'],
];
const key = (s) => {
  let t = s.toLowerCase().replace(/[’‘]/g, "'").replace(/&amp;/g, '&');
  for (const [re, to] of CONTRACTIONS) t = t.replace(re, to);
  return t.replace(/[^a-z0-9]+/g, '');
};

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

/*
 * PER-PACK CONTENT IS DATA, NOT COPY, and leaving it in made the ledger lie in the expensive
 * direction. The drawing hard-codes the packs that were on the shelf the day it was drawn; the
 * built page renders whatever the catalogue holds now. So every pack title and description in the
 * drawing read as a missing sentence forever. Section 11 scored 0% with all four "misses" being
 * pack titles, which buried the one real gap on the page.
 *
 * A pack card is exactly an `<a href="/pack/...">`, so that is the strip. The featured card is the
 * one place the pack's title and description sit OUTSIDE the link, and there they are a bare
 * `<h3>` and a `<p class="d">` -- both of which only ever hold pack data in these drawings, while
 * the headings the page owns carry a class (`h3.sub`, `h2.sec`).
 */
function stripPackData(html) {
  return html
    .replace(/<a\b[^>]*href="\/pack\/[^"]*"[\s\S]*?<\/a>/g, ' ')
    .replace(/<h3>[\s\S]*?<\/h3>/g, ' ')
    .replace(/<p class="d">[\s\S]*?<\/p>/g, ' ');
}

/** The prose a drawing prints: text nodes only, no markup, no data. */
function prose(html) {
  const text = stripPackData(html).replace(/<(script|style)[\s\S]*?<\/\1>/g, '').replace(/<!--[\s\S]*?-->/g, '');
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

/*
 * SENTENCES THE SITE MAY NOT SHIP, whatever the drawing says.
 *
 * Two founder rules outrank the drawing, and without this list the ledger reports them as gaps
 * forever, which invites the next session to "fix" them by shipping the banned copy.
 *   - The survivor count is never printed (2026-08-13, encoded in `src/lib/stats.ts`). The
 *     drawings write it out in words, "Seventy-four packs are on the shelf".
 *   - No copy promises a closed number of checks: the count varies per idea, and
 *     `fixedCheckCount.test.ts` fails the build on "all six checks".
 */
const EXCEPT = [
  [/seventy-four|seventy four/i, 'survivor count, never printed (stats.ts)'],
  [/\b(six|6) checks\b/i, 'closed check count, banned by fixedCheckCount.test.ts'],
  /* Founder decisions that outrank the drawing. Each one was made on the built page, with the
     reason recorded at the render site, so the drawing's sentence is not a gap. */
  [/^Sixteen ways into the same shelf/i, 'founder kept the built title (2026-08-15)'],
  [/^Business ideas with the research already done/i, "founder's own h1 supersedes the drawing"],
  [/^Or see everything at once/i, 'band deleted 2026-08-13, 350px for a heading and a button'],
];


/*
 * THE STRUCTURE CHECK, and it is the half the text ledger cannot do.
 *
 * The text ledger asks "are the drawing's words on the page". It passed a section that carried
 * every word and was drawn as a different thing: the home shelf, the longest list on the site,
 * was a bare `divide-y` list on the page ground where the drawing draws ONE card
 * (`.rows{background;border;radius;overflow:hidden}`) with hairline-separated rows inside it. The
 * words were all there, so the ledger said 100%, and the founder saw a section that looked
 * nothing like the drawing.
 *
 * So this counts the drawing's own class names -- only the ones `mumchimp.css` actually styles,
 * which is the drawing's visual vocabulary -- and asks whether the built page uses them at all.
 * A class the drawing uses and the build never emits is a section built in different markup.
 * MISSING is that. THIN is the same defect at partial strength: the build emits it, but for a
 * fraction of the elements the drawing does, which is what a list rendered as cards looks like.
 */
/*
 * DELIBERATE STRUCTURAL DIFFERENCES, each with the reason it is not a defect. Anything not in here
 * that the drawing styles and the build never emits is a real gap and gets reported. Keep this list
 * tiny: it is the one place the structure check can be told to look away.
 */
const STRUCT_EXCEPT = {
  killgrid: 'the 1,444-square field is one <svg> of rects, not 1,444 <i> elements',
  // State the probe's fresh browser is never in. Each of these IS emitted by the build, on a
  // visitor who has filtered or has already opened a pack; the drawing shows that visitor and the
  // probe cannot be them. Verified by reading the source, not by assuming: `new` is PackRow.tsx and
  // PackTileGrid's "Seen" badge, the rest are FilterBar.tsx and AppliedFilterChips.
  new: 'the "Seen" badge, drawn only for a pack this browser has already opened',
  on: 'a filter button, drawn only while that facet has a selection',
  badge: 'the phone filter count, drawn only while a filter is on',
  'active-row': 'the applied-filter row, drawn only while a filter is on',
  pill: 'an applied-filter chip, drawn only while a filter is on',
  clear: 'the clear-all link, drawn only while two or more filters are on',
};

async function styleParity(page, html, cssClasses) {
  const drawn = new Map();
  for (const m of html.matchAll(/class="([^"]+)"/g)) {
    for (const c of m[1].split(/\s+/)) {
      if (cssClasses.has(c)) drawn.set(c, (drawn.get(c) ?? 0) + 1);
    }
  }
  const built = new Map(
    await page.evaluate(() => {
      const out = {};
      for (const el of document.querySelectorAll('[class]')) {
        for (const c of String(el.className.baseVal ?? el.className).split(/\s+/)) {
          if (c) out[c] = (out[c] ?? 0) + 1;
        }
      }
      return Object.entries(out);
    }),
  );
  const missing = [];
  const thin = [];
  for (const [c, n] of [...drawn].sort((a, b) => b[1] - a[1])) {
    const got = built.get(c) ?? 0;
    if (STRUCT_EXCEPT[c]) continue;
    if (got === 0) missing.push(`${c} (drawing uses ${n})`);
    else if (n >= 3 && got * 2 < n) thin.push(`${c} ${got}/${n}`);
  }
  return { missing, thin };
}

const ALL = process.argv.includes('--all');
const only = process.argv.slice(2).filter((a) => a !== '--all');
/* The drawing's visual vocabulary is exactly the classes `mumchimp.css` styles. Tailwind utilities
   and one-off ids are not part of it, so they are never reported. */
const MOCKUP_CSS = await readFile(path.join(process.cwd(), 'src/styles/mumchimp.css'), 'utf8');
const CSS_CLASSES = new Set([...MOCKUP_CSS.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]));

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
    const banned = [];
    const absent = lines.filter((l) => {
      if (built.includes(key(l))) return false;
      const hit = EXCEPT.find(([re]) => re.test(l));
      if (hit) { banned.push([l, hit[1]]); return false; }
      return true;
    });
    const counted = lines.length - banned.length;
    const pct = counted === 0 ? 100 : Math.round(((counted - absent.length) / counted) * 100);
    const mark = pct === 100 ? 'OK  ' : pct >= 60 ? 'PART' : 'GONE';
    console.log(`${mark} ${pct.toString().padStart(3)}%  ${sec.n} · ${sec.name}  (${counted - absent.length}/${counted})`);
    /* Four lines per section is enough when a page splits into a dozen sections. On the nine
       drawings that carry no `<!-- N -->` comments the whole page collapses into ONE section, and
       four lines hid the rest of the worklist. `--all` prints every absent sentence, whole. */
    for (const [l, why] of banned) console.log(`    SKIP    ${l.slice(0, 70)}  [${why}]`);
    const cap = ALL ? absent.length : 4;
    if (pct < 100) for (const a of absent.slice(0, cap)) {
      console.log(`         - ${ALL ? a : a.slice(0, 110)}`);
    }
    if (pct < 100) worst.push({ route, sec: `${sec.n} · ${sec.name}`, pct });
  }
  const { missing, thin } = await styleParity(page, html, CSS_CLASSES);
  if (missing.length) console.log(`STRUCT  never emitted: ${missing.join(', ')}`);
  if (thin.length) console.log(`STRUCT  thin (built/drawn): ${thin.join(', ')}`);
}
await browser.close();
worst.sort((a, b) => a.pct - b.pct);
console.log(`\n═══ WORST FIRST ═══`);
for (const w of worst) console.log(`${w.pct.toString().padStart(3)}%  ${w.route}  ${w.sec}`);
console.log(`\n${worst.length} sections below 100%`);
