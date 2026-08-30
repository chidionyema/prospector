/**
 * MOCKUP DIFF HARNESS
 *
 * Why this exists. Five hours of work on 2026-08-18 produced about ten changes, because every
 * observation came from one 815px viewport and no artifact anywhere listed what was actually
 * different between a built page and its drawing. So there was no definition of done, nothing to
 * work down, and the same deltas got rediscovered one at a time. Reading the mockup's CSS text
 * and translating it into Tailwind cannot catch a section in the wrong ORDER, a section that is
 * MISSING, or a page whose rhythm is three times too tall. Those were exactly the complaints.
 *
 * What it does, for all twelve pages in one run:
 *   1. Screenshots the drawing and the built page FULL LENGTH, top to bottom.
 *   2. Reads the outline of both, every top-level section, its height, and its heading.
 *   3. Reads every heading in document order with its rendered size.
 *   4. Writes docs/design/MOCKUP_DIFF.md, the list of differences per page in document order.
 *
 * Run:  node scripts/mockup_diff.mjs
 * Needs both servers up: the built site on :3000 and the mockups on :3001.
 */
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const BUILT = process.env.BUILT_ORIGIN || 'http://localhost:3000';
const MOCK = process.env.MOCK_ORIGIN || 'http://127.0.0.1:3001';
const ROOT = path.resolve(process.cwd(), '../../..');
const OUT = path.join(ROOT, 'docs/design/diff');
const REPORT = path.join(ROOT, 'docs/design/MOCKUP_DIFF.md');

/* One line per drawing. `route` is the built page that must end up looking like it. */
const PAIRS = [
  { name: 'index', mock: 'index.html', route: '/' },
  { name: 'pack-detail', mock: 'pack-detail.html', route: process.env.PACK_ROUTE || null },
  /* `ideas`, not `collections`. There is no `collections.html` in the bundle and `/collections`
     answers 308, so this line compared a real page against the static server's own 404 body and
     reported it as a 900px drawing -- "collections: +2808px, 4.12x" in every report this harness
     has ever written. `ideas.html` IS in the bundle and `/ideas` answers 200, and it was the one
     drawing nothing compared. Nothing below silently accepts a missing drawing any more, so this
     class of line cannot come back unnoticed. */
  { name: 'ideas', mock: 'ideas.html', route: '/ideas' },
  { name: 'how-it-works', mock: 'how-it-works.html', route: '/how-it-works' },
  { name: 'kill-log', mock: 'kill-log.html', route: '/kill-log' },
  { name: 'faq', mock: 'faq.html', route: '/faq' },
  { name: 'pricing', mock: 'pricing.html', route: '/pricing' },
  { name: 'about', mock: 'about.html', route: '/about' },
  { name: 'account', mock: 'account.html', route: '/account' },
  { name: 'refund', mock: 'refund.html', route: '/refund' },
  { name: 'sample', mock: 'sample.html', route: '/sample' },
  { name: '404', mock: '404.html', route: '/404' },
];

/* Runs INSIDE the page. Keep it dependency-free and defensive: it runs against both a hand-written
   mockup and a React tree, and neither is allowed to break the other's read. */
const READ_OUTLINE = () => {
  const txt = (el) => (el && el.textContent ? el.textContent : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

  /* Find the content container: `main` if there is one, else the body. Then descend past any
     wrapper that holds everything in a single child, so we outline real sections rather than
     one <div class="wrap">. */
  let root = document.querySelector('main') || document.body;
  for (let i = 0; i < 4; i += 1) {
    const kids = Array.from(root.children).filter((c) => c.offsetHeight > 0);
    if (kids.length === 1) root = kids[0];
    else break;
  }

  const sections = Array.from(root.children)
    .filter((el) => el.offsetHeight > 4)
    .map((el, i) => {
      const cs = getComputedStyle(el);
      const h = el.querySelector('h1,h2,h3,h4');
      const rect = el.getBoundingClientRect();
      return {
        i,
        tag: el.tagName.toLowerCase(),
        cls: clip(String(el.className || ''), 52),
        heading: clip(txt(h), 46),
        height: Math.round(rect.height),
        top: Math.round(rect.top + window.scrollY),
        card: cs.borderTopWidth !== '0px' || cs.backgroundColor !== 'rgba(0, 0, 0, 0)',
      };
    });

  const headings = Array.from(document.querySelectorAll('h1,h2,h3'))
    .filter((el) => el.offsetHeight > 0)
    .map((el) => {
      const cs = getComputedStyle(el);
      return {
        tag: el.tagName.toLowerCase(),
        text: clip(txt(el), 54),
        size: Math.round(parseFloat(cs.fontSize) * 10) / 10,
        weight: cs.fontWeight,
      };
    });

  /* THE COLOUR CENSUS. Every visible element on the page, bucketed by the job the colour does:
     text, background, border. Counting how MANY elements wear each colour is what separates the
     palette from the accidents, and it is the only read that catches a hue the build uses and the
     drawing never does. */
  const hex = (v) => {
    const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(v || '');
    if (!m) return v || '';
    if (m[4] !== undefined && Number(m[4]) === 0) return '';
    const h = `#${[m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('')}`;
    return m[4] !== undefined && Number(m[4]) < 1 ? `${h}@${m[4]}` : h;
  };
  const roles = { text: {}, background: {}, border: {} };
  const bump = (role, value) => {
    const h = hex(value);
    if (!h) return;
    roles[role][h] = (roles[role][h] || 0) + 1;
  };
  Array.from(document.querySelectorAll('*')).forEach((el) => {
    if (!el.offsetWidth && !el.offsetHeight) return;
    const cs = getComputedStyle(el);
    if ((el.textContent || '').trim()) bump('text', cs.color);
    bump('background', cs.backgroundColor);
    const w = [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth];
    if (w.some((x) => x !== '0px')) bump('border', cs.borderTopColor);
  });
  const rank = (m) => Object.entries(m)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 14)
    .map(([colour, count]) => ({ colour, count }));

  return {
    pageHeight: Math.round(document.documentElement.scrollHeight),
    sections,
    headings,
    colours: { text: rank(roles.text), background: rank(roles.background), border: rank(roles.border) },
  };
};

async function read(page, url, shotPath, isDrawing = false) {
  const res = await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => null);
  /* 404 IS THE CORRECT STATUS FOR ONE OF THESE PAGES. `/404` answered 404, the harness read that
     as a failure, and the not-found page was the one page never measured against its drawing. Any
     other route answering 404 still shows up: its outline comes back empty and the diff prints
     every section as missing. */
  if (!res || (res.status() >= 400 && res.status() !== 404)) {
    return { error: `HTTP ${res ? res.status() : 'no response'}` };
  }
  /* A DRAWING THAT IS NOT THERE IS NOT A 900px DRAWING. The mockups are served by a plain static
     server, which answers a missing file with its own listing or error body: a short page that
     reads back as a perfectly valid outline about 900px tall. The report then prints a confident
     "+2808px, 4.12x" for a comparison that never happened. `python3 -m http.server` answers 404
     for a missing file and `waitUntil` still resolves, so the status is the only thing that knows,
     and the `/404` exemption above deliberately lets 404 through for the built side. Drawings are
     files on disk: for them, 404 means the pair is wrong. */
  if (isDrawing && res.status() === 404) {
    return { error: `no drawing at ${url} -- the PAIRS entry names a file the bundle does not have` };
  }
  await page.waitForTimeout(700); // let fonts settle so the heading sizes are real
  await page.screenshot({ path: shotPath, fullPage: true });
  return page.evaluate(READ_OUTLINE);
}

/* The comparison. Sections are matched BY POSITION, deliberately: a section that appears at index
   4 in the drawing and index 6 in the build is a real defect, and any clever fuzzy matching would
   hide exactly that. */
function diffPage(mock, built) {
  const lines = [];
  const hDelta = built.pageHeight - mock.pageHeight;
  const ratio = (built.pageHeight / mock.pageHeight).toFixed(2);
  lines.push(
    `Page height: drawing **${mock.pageHeight}px**, built **${built.pageHeight}px** `
      + `(${hDelta >= 0 ? '+' : ''}${hDelta}px, ${ratio}x).`,
  );
  lines.push('');
  lines.push(`Sections: drawing has **${mock.sections.length}**, built has **${built.sections.length}**.`);
  lines.push('');
  lines.push('| # | drawing | h | built | h | verdict |');
  lines.push('| - | ------- | - | ----- | - | ------- |');
  const n = Math.max(mock.sections.length, built.sections.length);
  for (let i = 0; i < n; i += 1) {
    const m = mock.sections[i];
    const b = built.sections[i];
    let verdict;
    if (!b) verdict = '**MISSING in build**';
    else if (!m) verdict = '**EXTRA in build**';
    else if (m.heading && b.heading && m.heading !== b.heading) verdict = '**heading differs**';
    else if (b.height > m.height * 1.5) verdict = `**${(b.height / m.height).toFixed(1)}x too tall**`;
    else if (b.height * 1.5 < m.height) verdict = `**${(m.height / b.height).toFixed(1)}x too short**`;
    else if (m.card && !b.card) verdict = '**drawing is a card, build is not**';
    else verdict = 'ok';
    const cell = (x) => (x ? `${x.tag}${x.heading ? ` "${x.heading}"` : ` .${x.cls.split(' ')[0] || ''}`}` : '-');
    lines.push(`| ${i} | ${cell(m)} | ${m ? m.height : '-'} | ${cell(b)} | ${b ? b.height : '-'} | ${verdict} |`);
  }
  lines.push('');

  /* Headings in document order. This is the cheapest signal for a missing or reordered block, and
     the size column is the one that catches an h2 that should have been an h1. */
  const hn = Math.max(mock.headings.length, built.headings.length);
  const bad = [];
  for (let i = 0; i < hn; i += 1) {
    const m = mock.headings[i];
    const b = built.headings[i];
    if (!m) { bad.push(`${i}: EXTRA heading in build, "${b.text}" (${b.size}px)`); continue; }
    if (!b) { bad.push(`${i}: MISSING heading in build, "${m.text}" (${m.size}px)`); continue; }
    if (m.text !== b.text) { bad.push(`${i}: text, drawing "${m.text}" / built "${b.text}"`); continue; }
    if (Math.abs(m.size - b.size) > 1.5) {
      bad.push(`${i}: size, "${m.text}" drawing ${m.size}px / built ${b.size}px`);
    }
  }
  lines.push(`Headings: drawing has **${mock.headings.length}**, built has **${built.headings.length}**.`);
  lines.push('');
  bad.forEach((l) => lines.push(`- ${l}`));
  if (bad.length) lines.push('');

  /* Colours, per role. Rank matters as much as membership: the drawing's most-worn text colour is
     its body ink, so if the build's most-worn text colour is a different hex the whole page reads
     in the wrong voice even when every hex in the list is legitimate. */
  lines.push('### Colours');
  lines.push('');
  lines.push('| role | drawing (colour × elements) | built | verdict |');
  lines.push('| ---- | --------------------------- | ----- | ------- |');
  for (const role of ['text', 'background', 'border']) {
    const m = mock.colours[role];
    const b = built.colours[role];
    const mSet = new Set(m.map((x) => x.colour));
    const bSet = new Set(b.map((x) => x.colour));
    const only = b.filter((x) => !mSet.has(x.colour)).map((x) => x.colour);
    const missing = m.filter((x) => !bSet.has(x.colour)).map((x) => x.colour);
    const notes = [];
    if (m[0] && b[0] && m[0].colour !== b[0].colour) notes.push(`**top ${role} differs**`);
    if (only.length) notes.push(`**not in drawing: ${only.join(' ')}**`);
    if (missing.length) notes.push(`missing: ${missing.join(' ')}`);
    const show = (list) => list.slice(0, 6).map((x) => `${x.colour}×${x.count}`).join(' ');
    lines.push(`| ${role} | ${show(m)} | ${show(b)} | ${notes.join('<br>') || 'ok'} |`);
  }
  lines.push('');
  return lines.join('\n');
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await mkdir(OUT, { recursive: true });

const out = [
  '# Mockup diff, every built page against its drawing',
  '',
  'Generated by `store_platform/src/Store.Web/scripts/mockup_diff.mjs`. Re-run it after any change;',
  'do not edit this file by hand. Full-length screenshots of both sides are in `docs/design/diff/`.',
  '',
  'Sections are matched BY POSITION. A section at index 4 in the drawing and index 6 in the build',
  'is a real defect, so nothing here tries to be clever about pairing them up.',
  '',
];

for (const pair of PAIRS) {
  process.stdout.write(`${pair.name} ... `);
  const mock = await read(page, `${MOCK}/${pair.mock}`, path.join(OUT, `${pair.name}-drawing.png`), true);
  out.push(`## ${pair.name}`, '');
  if (!pair.route) {
    out.push('No route captured: this page needs a live id. Set `PACK_ROUTE` and re-run.', '');
    process.stdout.write('skipped, no route\n');
    continue;
  }
  const built = await read(page, `${BUILT}${pair.route}`, path.join(OUT, `${pair.name}-built.png`));
  if (mock.error || built.error) {
    out.push(`Could not compare: drawing ${mock.error || 'ok'}, built ${built.error || 'ok'}.`, '');
    process.stdout.write('error\n');
    continue;
  }
  out.push(`\`${pair.mock}\` vs \`${pair.route}\``, '');
  out.push(diffPage(mock, built));
  process.stdout.write(`${built.pageHeight}px vs ${mock.pageHeight}px\n`);
}

await browser.close();
await writeFile(REPORT, out.join('\n'));
console.log(`\nwrote ${REPORT}`);
