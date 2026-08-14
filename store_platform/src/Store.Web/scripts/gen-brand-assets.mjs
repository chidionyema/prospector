/**
 * Regenerates every static brand asset in `public/` from ONE source of truth.
 *
 * WHY THIS EXISTS. On 2026-08-14 the founder reported "remnants of the introduction exchange"
 * when sharing a link. They were not remnants: `public/og.png` was, in full, the link-preview
 * card of a DIFFERENT product -- "The Intro Exchange / Warm introductions to the people you can't
 * reach cold." -- and `favicon.ico` ("E"), `apple-touch-icon.png`, `icon-192.png` and
 * `icon-512.png` ("IX" on navy) were that product's icon set. All five were committed in `5f95ca7`
 * dated 16 Jun and never touched again, while `icon.svg` alone was updated to the strata mark on
 * 13 Aug. `Seo.tsx` nominates `/og.png` as both `og:image` and `twitter:image` on every route
 * except pack pages (which render their own card via `/og/pack/[id]`), so every share of the home
 * page, /sample, /kill-log, /pricing and the rest previewed as another company.
 *
 * The defect is not that the files were wrong once; it is that nothing REGENERATED them, so a
 * brand change could land in `Logo.tsx` and `icon.svg` and leave the raster set behind. This
 * script is the fix for that: `public/icon.svg` is the only place the mark is drawn, and every
 * PNG/ICO here is rasterised FROM it. A future change to the mark means re-running this, not
 * redrawing five files by hand.
 *
 *   node scripts/gen-brand-assets.mjs
 *
 * WHY PLAYWRIGHT FOR THE CARD AND SHARP FOR THE ICONS. The icons are pure vector -> raster, which
 * sharp does directly. The card has type in it, and the type has to be Switzer, the site's own
 * face. `next/og` (satori) is already wired for the per-pack cards, but satori reads ttf/otf/woff
 * and the self-hosted file is `Switzer-Variable.woff2` -- which is exactly why `/og/pack/[id].tsx`
 * settled for "the container's default sans". Chromium reads woff2 natively, so rendering the card
 * as a real page and screenshotting it is what gets the actual brand face onto the actual card.
 * The page is loaded over file:// with a file:// @font-face, so this needs no dev server running.
 */

import { chromium } from '@playwright/test';
import sharp from 'sharp';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, '..');
const PUBLIC = path.join(WEB, 'public');

/*
 * Kept in sync with `src/styles/tokens.css` by hand, because this script runs outside the Tailwind
 * pipeline and cannot read a CSS custom property. Each one is quoted with its token name so a
 * drift is greppable rather than invisible.
 */
const TOKEN = {
  bg: '#FFFFFF', //        --bg
  surface2: '#FAFAFA', //  --surface2
  border: '#E4E4E7', //    --border
  text: '#171717', //      --text
  muted: '#52525B', //     --muted
  subtle: '#71717A', //    --subtle
  brandMark: '#0F766E', // --brand-mark
};

const OG_WIDTH = 1200;
const OG_HEIGHT = 630;

/**
 * The icon raster set.
 *
 * FLATTENED ONTO WHITE, NOT LEFT TRANSPARENT. The mark is an ink tile with one corner cut at a
 * straight diagonal, so the area outside it is transparent in the SVG. iOS ignores alpha in
 * `apple-touch-icon` and composites onto BLACK, which would fill the cut corner with black and
 * destroy the one feature that distinguishes this tile from every other rounded app icon. White is
 * also the page ground the lockup is drawn against everywhere else, so flattening keeps the raster
 * icons and the header lockup the same object.
 */
const ICONS = [
  { file: 'icon-192.png', size: 192 },
  { file: 'icon-512.png', size: 512 },
  { file: 'apple-touch-icon.png', size: 180 },
];

/** favicon.ico carries three sizes: 16 (tab strip), 32 (retina tab / bookmark bar), 48 (Windows). */
const FAVICON_SIZES = [16, 32, 48];

async function renderIcons(svg) {
  for (const { file, size } of ICONS) {
    await sharp(svg, { density: 384 })
      .resize(size, size, { fit: 'contain', background: TOKEN.bg })
      .flatten({ background: TOKEN.bg })
      .png({ compressionLevel: 9 })
      .toFile(path.join(PUBLIC, file));
    console.log(`  public/${file}  ${size}x${size}`);
  }
}

/**
 * .ico is the one format sharp will not write, so the three frames are rasterised here and packed
 * by Pillow. Pillow's ICO writer takes a single image plus a `sizes` list and downsamples itself;
 * feeding it the 48px frame keeps one code path instead of three temp files.
 */
async function renderFavicon(svg) {
  const png48 = await sharp(svg, { density: 384 })
    .resize(48, 48, { fit: 'contain', background: TOKEN.bg })
    .flatten({ background: TOKEN.bg })
    .png()
    .toBuffer();
  const tmp = await mkdtemp(path.join(tmpdir(), 'favicon-'));
  const src = path.join(tmp, 'src.png');
  await writeFile(src, png48);
  const { execFile } = await import('node:child_process');
  const { promisify } = await import('node:util');
  await promisify(execFile)('python3', [
    '-c',
    [
      'import sys',
      'from PIL import Image',
      'im = Image.open(sys.argv[1]).convert("RGBA")',
      `im.save(sys.argv[2], sizes=[${FAVICON_SIZES.map((s) => `(${s},${s})`).join(',')}])`,
    ].join('\n'),
    src,
    path.join(PUBLIC, 'favicon.ico'),
  ]);
  await rm(tmp, { recursive: true, force: true });
  console.log(`  public/favicon.ico  ${FAVICON_SIZES.join('/')}`);
}

/**
 * The default link-preview card.
 *
 * NO ENGINE NUMBERS ON IT, deliberately. `docs/SITE_SPEC_PROGRAM.md` §8 bans hand-typed engine
 * counts anywhere in the product, and a static PNG cannot re-render when the daemon publishes
 * tonight -- a card reading "1,364 killed" is a wrong number the day after it is generated, on the
 * one surface that gets cached hardest by every scraper on the internet. Pack pages, which DO
 * carry live figures, render per-request through `/og/pack/[id]`.
 *
 * The claim is the home page's own H1 promise, so a shared link and the page it opens say the
 * same thing.
 */
function cardHtml(fontUrl, markSvg) {
  return `<!doctype html>
<meta charset="utf-8">
<style>
  @font-face {
    font-family: 'Switzer';
    src: url('${fontUrl}') format('woff2');
    font-weight: 100 900;
    font-display: block;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: ${OG_WIDTH}px; height: ${OG_HEIGHT}px; }
  body {
    background: ${TOKEN.surface2};
    /* A 2px full frame, same reasoning as the pack card: a social card renders against an
       arbitrary timeline, and an unbordered near-white card dissolves into a light one. */
    border: 2px solid ${TOKEN.border};
    font-family: 'Switzer', system-ui, sans-serif;
    color: ${TOKEN.text};
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 64px;
    -webkit-font-smoothing: antialiased;
  }
  .lockup { display: flex; align-items: center; gap: 12px; font-size: 34px; line-height: 1;
            letter-spacing: -0.02em; }
  .lockup svg { width: 0.82em; height: 0.82em; flex: none; color: ${TOKEN.brandMark}; }
  .claim { font-size: 76px; font-weight: 700; line-height: 1.08; letter-spacing: -0.03em;
           max-width: 15ch; }
  .foot { display: flex; align-items: center; gap: 16px; font-size: 24px; color: ${TOKEN.subtle};
          letter-spacing: -0.01em; }
  .foot .dot { width: 4px; height: 4px; background: ${TOKEN.border}; }
</style>
<div class="lockup">${markSvg}<span><b style="font-weight:700">Mum</b><span style="font-weight:400">chimp</span></span></div>
<div class="claim">Business ideas that survived a filter built to kill them.</div>
<div class="foot">
  <span>Every claim sourced.</span><span class="dot"></span><span>Every kill published.</span>
</div>`;
}

async function renderCard(svgText) {
  /* The tile is re-coloured to --brand-mark for the card lockup, matching Logo.tsx's BrandMark
     (the accent lands on the tile only, never on the wordmark). icon.svg hardcodes ink because a
     16px tab strip needs the solid fill; here there is room for the accent. */
  const markSvg = svgText
    .replace(`fill="${TOKEN.text}"`, 'fill="currentColor"')
    .replace(/fill="#ffffff"/g, `fill="${TOKEN.surface2}"`);

  const fontUrl = pathToFileURL(path.join(PUBLIC, 'fonts', 'Switzer-Variable.woff2')).href;
  const tmp = await mkdtemp(path.join(tmpdir(), 'ogcard-'));
  const page = path.join(tmp, 'card.html');
  await writeFile(page, cardHtml(fontUrl, markSvg));

  const browser = await chromium.launch();
  const ctx = await browser.newPage({
    viewport: { width: OG_WIDTH, height: OG_HEIGHT },
    deviceScaleFactor: 1,
  });
  await ctx.goto(pathToFileURL(page).href, { waitUntil: 'load' });
  await ctx.evaluate(() => document.fonts.ready);
  await ctx.screenshot({ path: path.join(PUBLIC, 'og.png') });
  await browser.close();
  await rm(tmp, { recursive: true, force: true });
  console.log(`  public/og.png  ${OG_WIDTH}x${OG_HEIGHT}`);
}

const svgPath = path.join(PUBLIC, 'icon.svg');
const svgText = await readFile(svgPath, 'utf8');

/*
 * COMMENTS STRIPPED BEFORE RASTERISING, and this is not cosmetic. `icon.svg`'s explanatory comment
 * contains a literal `--` (in "-- see Logo.tsx's BrandMark"), and a double hyphen inside `<!-- -->`
 * is malformed XML. Every browser's HTML-ish parser tolerates it, so the file renders correctly in
 * a tab strip and nothing ever flagged it; librsvg, which sharp uses, is a real XML parser and
 * refuses the whole document: "Double hyphen within comment", line 13 column 52. So the file is
 * simultaneously the working favicon and an unrasterisable input. Stripping comments is the
 * narrow fix -- rewriting the prose to dodge a parser would put the constraint somewhere no
 * future editor can see it.
 */
const svgClean = svgText.replace(/<!--[\s\S]*?-->/g, '');

console.log('Regenerating brand assets from public/icon.svg:');
await renderIcons(Buffer.from(svgClean));
await renderFavicon(Buffer.from(svgClean));
await renderCard(svgClean);

/*
 * THE LOCK FILE, and why the guard is a hash rather than a re-render.
 *
 * The defect this script fixes lasted two months because nothing connected `icon.svg` to the
 * rasters beside it: the mark could be redrawn and the PNGs left behind, with no failing anything.
 * The obvious guard -- a test that re-runs this script and diffs the bytes -- is not stable enough
 * to gate a build: libvips and Chromium both change their output across versions and platforms
 * (subpixel AA in particular), so byte equality would fail on a machine where nothing is actually
 * wrong, and a flaky guard gets deleted.
 *
 * Recording the SOURCE hash instead makes the test a pure string comparison with no rasteriser in
 * it, and it still catches the exact drift that happened: edit `icon.svg`, forget to re-run this,
 * and `brandAssets.test.ts` fails naming the command to run. It cannot catch someone overwriting
 * a PNG by hand with an unrelated image, which is what originally happened -- but that path now
 * requires deliberately replacing a generated file, rather than simply never regenerating one.
 */
const lock = {
  source: 'public/icon.svg',
  sha256: createHash('sha256').update(svgText).digest('hex'),
  generates: [...ICONS.map((i) => `public/${i.file}`), 'public/favicon.ico', 'public/og.png'],
  regenerate: 'node scripts/gen-brand-assets.mjs',
};
await writeFile(path.join(HERE, 'brand-assets.lock.json'), JSON.stringify(lock, null, 2) + '\n');
console.log('  scripts/brand-assets.lock.json');
console.log('Done.');
