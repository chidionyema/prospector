/**
 * VISUAL REGRESSION: THE RENDERED PAGE MUST LOOK LIKE THE DRAWING.
 *
 * Founder's spec, 2026-08-18, PART 2 step 4: "visual regression at 390 and 1280, diff < 0.02".
 * Steps 2 and 3 grade STRUCTURE — tag plus stylesheet-defined class, in document order. A page can
 * pass that and still look wrong: a wrong font size, a wrong gap, a section three times too tall.
 * This is the pixel half. It screenshots the drawing and the built page at the same viewport, full
 * length, and counts the pixels that differ.
 *
 * WHAT THE NUMBER IS. diff = differing pixels / total pixels of the taller image. Both shots are
 * padded to the same height with white, so a page that runs longer than its drawing pays for the
 * extra region rather than having it cropped away. Height is also reported on its own, because a
 * rhythm defect shows there first.
 *
 * WHAT IT CANNOT SEE. The drawings carry sample copy and the app carries the live catalogue, so
 * text pixels differ wherever the words differ. That is data, not layout, and it is why the bar is
 * a percentage rather than zero. Read the diff PNG before believing any number: a band of solid
 * colour is a layout defect, scattered speckle inside a paragraph is copy.
 *
 * Run:  node scripts/visual_regression.mjs [pageName ...]
 * Needs the built site on :3000 (BUILT_ORIGIN) and the mockups on :3002 (MOCK_ORIGIN).
 * Exit 1 if any page at any width exceeds THRESHOLD.
 */
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { PNG } from 'pngjs';
import pixelmatch from 'pixelmatch';

const BUILT = process.env.BUILT_ORIGIN || 'http://localhost:3000';
const MOCK = process.env.MOCK_ORIGIN || 'http://127.0.0.1:3002';
const ROOT = path.resolve(process.cwd(), '../../..');
const OUT = path.join(ROOT, 'docs/design/visual');
const REPORT = path.join(ROOT, 'docs/design/VISUAL_REGRESSION.md');
const THRESHOLD = Number(process.env.THRESHOLD || 0.02);
const WIDTHS = [390, 1280];
/* Chrome, hero and first section on every drawing. See the fold comment below. */
const FOLD_PX = Number(process.env.FOLD_PX || 2400);

/* One line per drawing. `route` is the built page that must end up looking like it. */
const PAIRS = [
  { name: 'index', mock: 'index.html', route: '/' },
  { name: 'ideas', mock: 'ideas.html', route: '/ideas' },
  { name: 'how-it-works', mock: 'how-it-works.html', route: '/how-it-works' },
  { name: 'kill-log', mock: 'kill-log.html', route: '/kill-log' },
  { name: 'faq', mock: 'faq.html', route: '/faq' },
  { name: 'pricing', mock: 'pricing.html', route: '/pricing' },
  { name: 'about', mock: 'about.html', route: '/about' },
  { name: 'account', mock: 'account.html', route: '/account' },
  { name: 'refund', mock: 'refund.html', route: '/refund' },
  { name: 'sample', mock: 'sample.html', route: '/sample' },
];

/* Pad a PNG to `height` with white, so two shots of different length can be compared without
   cropping the difference away. */
function padTo(png, height) {
  if (png.height === height) return png;
  const out = new PNG({ width: png.width, height });
  out.data.fill(255);
  PNG.bitblt(png, out, 0, 0, png.width, png.height, 0, 0);
  return out;
}

async function shoot(browser, url, width) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  /* Kill anything that moves: an animation mid-flight is a false diff. */
  await page.addStyleTag({
    content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}',
  });
  await page.waitForTimeout(600);
  const buf = await page.screenshot({ fullPage: true });
  await page.close();
  return PNG.sync.read(buf);
}

const only = process.argv.slice(2);
const pairs = only.length ? PAIRS.filter((p) => only.includes(p.name)) : PAIRS;

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();
const rows = [];

for (const pair of pairs) {
  for (const width of WIDTHS) {
    let mockPng;
    let builtPng;
    try {
      mockPng = await shoot(browser, `${MOCK}/${pair.mock}`, width);
      builtPng = await shoot(browser, `${BUILT}${pair.route}`, width);
    } catch (err) {
      rows.push({ name: pair.name, width, diff: null, note: String(err.message || err).split('\n')[0] });
      continue;
    }
    const w = Math.min(mockPng.width, builtPng.width);
    const h = Math.max(mockPng.height, builtPng.height);
    const a = padTo(mockPng, h);
    const b = padTo(builtPng, h);
    const out = new PNG({ width: w, height: h });
    const differing = pixelmatch(a.data, b.data, out.data, w, h, { threshold: 0.1, includeAA: false });
    const diff = differing / (w * h);

    /* THE SECOND NUMBER, AND WHY IT IS NOT A SOFTER BAR. Several built pages are legitimately
       longer than their drawing because they render the real catalogue: /kill-log draws 400 rows
       where the drawing draws six. A full-page number on those measures how much data we have, not
       how far the layout is off, and it can never come down. The fold number compares only the
       first FOLD_PX, which is chrome, hero and first section on every page: the region where the
       drawing and the page hold the same amount of content, so a difference there is a real one. */
    const fh = Math.min(FOLD_PX, h);
    const foldOut = new PNG({ width: w, height: fh });
    const foldDiffering = pixelmatch(
      a.data.subarray(0, w * fh * 4),
      b.data.subarray(0, w * fh * 4),
      foldOut.data,
      w,
      fh,
      { threshold: 0.1, includeAA: false },
    );
    const foldDiff = foldDiffering / (w * fh);
    await writeFile(path.join(OUT, `${pair.name}-${width}.diff.png`), PNG.sync.write(out));
    rows.push({
      name: pair.name,
      width,
      diff,
      foldDiff,
      mockH: mockPng.height,
      builtH: builtPng.height,
      note: '',
    });
    console.log(
      `${pair.name.padEnd(14)} ${String(width).padStart(4)}  page=${(diff * 100).toFixed(2).padStart(6)}%  ` +
        `fold=${(foldDiff * 100).toFixed(2).padStart(6)}%  height mock=${mockPng.height} built=${builtPng.height}`,
    );
  }
}
await browser.close();

const failures = rows.filter((r) => r.diff === null || r.diff > THRESHOLD);
const lines = [
  '# Visual regression — the built page against its drawing',
  '',
  `Generated by \`scripts/visual_regression.mjs\`. Threshold ${(THRESHOLD * 100).toFixed(0)}%.`,
  'Whole page = differing pixels / total pixels of the taller image, both padded to equal height with white.',
  `First ${FOLD_PX}px = the same count over the top of the page only, where the drawing and the app hold the same amount of content.`,
  '',
  `| Page | Width | Whole page | First ${FOLD_PX}px | Height mock | Height built | Note |`,
  '|---|---:|---:|---:|---:|---:|---|',
  ...rows.map(
    (r) =>
      `| ${r.name} | ${r.width} | ${r.diff === null ? 'ERROR' : `${(r.diff * 100).toFixed(2)}%`} | ` +
      `${r.foldDiff === undefined ? '' : `${(r.foldDiff * 100).toFixed(2)}%`} | ` +
      `${r.mockH ?? ''} | ${r.builtH ?? ''} | ${r.note} |`,
  ),
  '',
  `Diff images: \`docs/design/visual/<page>-<width>.diff.png\`.`,
];
await writeFile(REPORT, `${lines.join('\n')}\n`);

console.log(`\n${failures.length === 0 ? 'ALL PAGES WITHIN THRESHOLD' : `${failures.length} of ${rows.length} OVER THRESHOLD`}`);
console.log(`report: ${REPORT}`);
process.exit(failures.length === 0 ? 0 : 1);
