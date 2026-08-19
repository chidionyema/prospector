/**
 * COMPONENT PARITY: EVERY COMPONENT THE STYLESHEET NAMES MUST RENDER THE SAME.
 *
 * WHY THIS EXISTS, AND WHY THE PIXEL DIFF NO LONGER GATES.
 * Step 4 of the parity spec was written as "visual regression at 390 and 1280, diff < 0.02".
 * `visual_regression.mjs` measures exactly that and it cannot reach the bar. The reason is
 * measured, not argued: on 2026-08-18 the top 100px of `/about` was compared box by box between
 * the drawing and the built page and every element matched -- `div.strip` y=0 h=44, `span.tag`
 * y=10 x=120, `header.hdr` y=44 h=59, `span.wordmark` y=63 x=155 fs=21px -- while the pixel diff
 * still read 18.8% in the 10px band at y=20. The nav says "Good for" where the drawing says
 * "Categories", and the drawing's strip advertises a different pack. The pixels differ because the
 * WORDS differ. Making the head of `/about` match the drawing exactly moved its diff from 3.89% to
 * 3.95%, the wrong way. A raw pixel diff between two documents whose text differs cannot converge,
 * however correct the layout is.
 *
 * So the pixel harness stays, as a report and a set of PNGs to look at, and the GATE moves here.
 *
 * THE UNIT IS A SELECTOR FROM THE SHIPPED BUNDLE.
 * `src/styles/mumchimp.css` is the design system, shipped verbatim (parity step 1). Every selector
 * it declares is a component someone drew: `.crumb a`, `.pagetop`, `.tc h4`, `.bars i`, `.sign`.
 * This script reads those selectors out of the stylesheet and, for each one, compares the first
 * matching element in the drawing against the first matching element in the built page.
 *
 * That is not a proxy for the nine defects in SITE_SPEC_PROGRAM.md 11.8. It is the thing that found
 * them: the missing dark strip was a component present in the drawing and absent in the build; the
 * ramp built with `.replace()` was wrong widths; the 420px cap was a `max-width`; the two `.bars`
 * collisions were a `height` and a `max-width`; the breadcrumb was a box 43px tall against 19px;
 * the `.tc` titles were a `font-size` of 14px against 17px; the page top was a `padding-top` and a
 * `margin-top`. Every one is a computed style on a named component. The pixel diff graded all ten
 * pages as failing before and after each of those fixes, so it never told anyone which was real.
 *
 * THREE BUCKETS, AND ONLY TWO OF THEM RATCHET.
 * - `hard`   computed-style differences on a component both documents render. A defect.
 * - `absent` a component one document renders and the other does not, `display:none` included.
 *            Sometimes a defect (the missing dark strip was one), sometimes the content divergence
 *            in 11.9 where three pages carry sections the drawings do not.
 * - `soft`   width and height past tolerance. Usually copy. Reported, never gating.
 *
 * THE GATE IS A RATCHET, NOT A ZERO. `docs/design/component_parity_baseline.json` records what each
 * page measured when the baseline was taken. A page may improve or hold; it may not get worse. That
 * is the same shape as `docs/doc_lint_baseline.json`, and it is the only shape that can be turned
 * on today: a bar of zero would be red on day one and would then be ignored, which is what happened
 * to the pixel threshold.
 *
 * WHAT IT DELIBERATELY DOES NOT GRADE.
 * - Absolute y. An extra section moves everything below it. Every property compared here is
 *   intrinsic to the element.
 * - `font-family`. Computed `Inter` against `Inter Variable` is the same face loaded two ways:
 *   "How it works" advances 117px in both documents.
 * - Padding against margin, side by side. `-my-3 py-3` on the breadcrumb link buys a 44px tap
 *   target and costs the line no height, and it must not read as a defect. The box model is
 *   compared as a SUM per side: margin + border + padding.
 * - `inline-block` against `block`. A flex or grid child is blockified by CSS itself, so our flex
 *   breadcrumb and the drawing's inline one report different `display` for identical output.
 *
 * Run:  node scripts/component_parity.mjs [pageName ...]
 *       node scripts/component_parity.mjs --update-baseline
 * Needs the built site on :3000 (BUILT_ORIGIN) and the mockups on :3002 (MOCK_ORIGIN).
 * Exit 1 if any page at any width is worse than its baseline.
 */
import { chromium } from 'playwright';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const BUILT = process.env.BUILT_ORIGIN || 'http://localhost:3000';
const MOCK = process.env.MOCK_ORIGIN || 'http://127.0.0.1:3002';
const ROOT = path.resolve(process.cwd(), '../../..');
const REPORT = path.join(ROOT, 'docs/design/COMPONENT_PARITY.md');
const BASELINE = path.join(ROOT, 'docs/design/component_parity_baseline.json');
const BUNDLE = path.resolve(process.cwd(), 'src/styles/mumchimp.css');
const WIDTHS = [390, 1280];

/* Same ten pairs as the pixel harness. `route` is the built page that must look like `mock`. */
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

/* Typography and colour. A difference here is visible and is nobody's accident. */
const HARD_EXACT = [
  'fontWeight', 'textTransform', 'textAlign', 'color', 'backgroundColor',
  'borderTopColor', 'borderBottomColor', 'display', 'flexDirection',
  'justifyContent', 'alignItems', 'position', 'gridTemplateColumns',
];
/* Lengths, compared with the tolerance below rather than as strings. */
const HARD_LEN = [
  'fontSize', 'lineHeight', 'letterSpacing', 'borderRadius', 'gap', 'maxWidth',
  'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
  'boxTop', 'boxRight', 'boxBottom', 'boxLeft',
];
/* SOFT: copy-driven. Reported, never gating. */
const SOFT = ['width', 'height'];

/* A length may be this far out before it counts. 1px absorbs subpixel rounding. The 1.5% absorbs
   `ch` and `em` measures resolving against `Inter` on one side and `Inter Variable` on the other:
   `.essay p` computes max-width 631.969px in the drawing and 635.906px in the build, which is the
   same 56ch rule, not a defect. Every real defect in 11.8 was far larger: 43px against 19px, 14px
   against 17px, a 420px cap against none. */
const LEN_ABS = 1;
const LEN_PCT = 0.015;
/* Height and width follow the copy. One line of the essay is 30.24px, so allow a line either way. */
const SOFT_ABS = 32;
const SOFT_PCT = 0.06;

/* Pull every selector the shipped bundle declares. A selector it bothers to style is a component
   someone drew, which makes it exactly the right probe list -- nobody maintains it by hand, and it
   grows when the design system grows. */
function selectorsFrom(css) {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = new Set();
  for (const m of stripped.matchAll(/(^|[};])\s*([^{};@]+?)\s*\{/g)) {
    for (const raw of m[2].split(',')) {
      const sel = raw.trim().replace(/\s+/g, ' ');
      if (!sel || !sel.includes('.')) continue;
      /* States and pseudo-elements have no resting box to compare. `*` and attribute selectors
         match half the document and say nothing about a component. */
      if (/[:>~+*[]/.test(sel)) continue;
      if (sel.length > 60) continue;
      out.add(sel);
    }
  }
  return [...out].sort();
}

async function shoot(page, url, selectors) {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  await page.evaluate(() => document.fonts.ready.then(() => true));
  /* FREEZE THE PAGE BEFORE READING IT, or the gate flaps. A computed style read while a transition
     or an entrance animation is still running is an interpolated value, not the resting one, and
     the ratchet then fails a page nobody touched. Measured 2026-08-18: `account` at 390 returned
     32 hard findings on three runs and 30 on a fourth, with no code change between them; the first
     recorded baseline took the 30 and would have called every later run a regression. Same
     treatment the pixel harness already used (`visual_regression.mjs`), plus a settle beat. */
  await page.addStyleTag({
    content: '*,*::before,*::after{animation:none!important;transition:none!important}',
  });
  await page.waitForTimeout(400);
  return page.evaluate(
    ([sels, exact, len, soft]) =>
      sels.map((sel) => {
        const all = document.querySelectorAll(sel);
        const el = all[0];
        if (!el) return { sel, present: false, count: 0 };
        const cs = getComputedStyle(el);
        /* A component that renders nothing is absent, whatever the DOM says. This is how the
           `hidden md:block` band on phones reads as a component the drawing does not have. */
        if (cs.display === 'none' || cs.visibility === 'hidden') return { sel, present: false };
        const box = el.getBoundingClientRect();
        const rec = { sel, present: true, count: all.length, style: {}, len: {}, box: {} };
        const px = (v) => parseFloat(v) || 0;
        for (const p of exact) {
          /* A flex or grid child is blockified by CSS itself. Our breadcrumb row is flex and the
             drawing's is inline text, so identical output computes two different words. */
          rec.style[p] = p === 'display' && cs[p] === 'inline-block' ? 'block' : cs[p];
        }
        /* A COLOUR ON A BORDER THAT IS NOT DRAWN IS NOT A COLOUR. When a side's width computes to
           0, its `border-*-color` is whatever `currentColor` or the UA sheet left behind, and it
           paints nothing. `mumchimp.css:33` is `.rule2{border:0;border-top:2px solid var(--ink)}`,
           so the bottom border is 0px wide on both sides of the comparison -- and the gate still
           reported "drawing rgb(128,128,128) / built rgb(23,25,28)" on it, 8 times. Across the
           whole report 94 of the 724 hard findings were border colours. A real difference in
           whether a border is drawn at all is still caught: `borderTopWidth` and `borderBottomWidth`
           are compared as lengths, and both feed `boxTop` and `boxBottom`. */
        for (const p of ['borderTopColor', 'borderBottomColor']) {
          const w = p === 'borderTopColor' ? cs.borderTopWidth : cs.borderBottomWidth;
          if (px(w) === 0) rec.style[p] = 'no-border';
        }
        /* VERTICAL KEEPS ITS MARGIN, HORIZONTAL DOES NOT. A vertical margin is a rhythm decision
           and the drawings make it deliberately. A horizontal one is usually `auto`, and
           `getComputedStyle` reports the USED value of an auto margin, which is whatever the rest
           of the row left over. `mumchimp.css:48` sets `.logo{margin-right:auto}`: the drawing
           computed 436.109px and the built page 447.641px, on all ten pages at both widths, because
           our nav says "Good for" where the drawing says "Categories". That is copy, and it was 20
           of the 751 hard findings. Horizontal padding and border are still real style claims and
           are still compared. */
        const side = {
          boxTop: px(cs.marginTop) + px(cs.borderTopWidth) + px(cs.paddingTop),
          boxRight: px(cs.borderRightWidth) + px(cs.paddingRight),
          boxBottom: px(cs.marginBottom) + px(cs.borderBottomWidth) + px(cs.paddingBottom),
          boxLeft: px(cs.borderLeftWidth) + px(cs.paddingLeft),
        };
        for (const p of len) {
          if (p in side) rec.len[p] = side[p];
          else if (cs[p] === 'normal' || cs[p] === 'none') rec.len[p] = cs[p];
          else rec.len[p] = px(cs[p]);
        }
        for (const p of soft) rec.box[p] = Math.round(box[p] * 10) / 10;
        return rec;
      }),
    [selectors, HARD_EXACT, HARD_LEN, SOFT],
  );
}

function compare(mockRecs, builtRecs) {
  const byMock = new Map(mockRecs.map((r) => [r.sel, r]));
  const hard = [];
  const absent = [];
  const softOut = [];
  const multi = [];
  for (const b of builtRecs) {
    const m = byMock.get(b.sel);
    if (!m || (!m.present && !b.present)) continue;
    if (m.present !== b.present) {
      absent.push({ sel: b.sel, mock: m.present ? 'yes' : 'no', built: b.present ? 'EXTRA' : 'MISSING' });
      continue;
    }
    /* ONLY A SELECTOR THAT MATCHES ONE ELEMENT IN BOTH DOCUMENTS CAN BE GATED. The two documents
       are written independently -- the drawings by hand, the pages by us -- so there is no way to
       tell mechanically that the drawing's third `.btn` is the same button as ours. This harness
       pairs the FIRST match, and for a selector used many times per page that pairs two unrelated
       elements. The tell is findings that contradict each other: `.num` reported "drawing normal /
       built -0.38" on one page and "drawing -0.38 / built normal" on another, and `mumchimp.css:9`
       declares nothing but `font-variant-numeric` on it. `.tlink` (76 findings) and `.btn` (48) had
       the same shape. Those selectors are still probed and still printed, as MULTI -- they say where
       to look. They do not gate, because a number nobody can act on is not a gate. Singletons like
       `.hero`, `h2.sec` and `.logo` still gate, and defect 10 was found on one of those. */
    const gated = m.count === 1 && b.count === 1;
    const out = gated ? hard : multi;
    if (!gated) multi.push({ sel: b.sel, prop: 'count', mock: m.count, built: b.count });
    for (const p of HARD_EXACT) {
      if (m.style[p] !== b.style[p]) out.push({ sel: b.sel, prop: p, mock: m.style[p], built: b.style[p] });
    }
    for (const p of HARD_LEN) {
      const a = m.len[p];
      const c = b.len[p];
      if (a === c) continue;
      /* `normal` against a number, or `none` against a cap, is a real change of kind. */
      if (typeof a !== 'number' || typeof c !== 'number') {
        out.push({ sel: b.sel, prop: p, mock: a, built: c });
        continue;
      }
      if (Math.abs(a - c) <= Math.max(LEN_ABS, Math.abs(a) * LEN_PCT)) continue;
      out.push({ sel: b.sel, prop: p, mock: `${a}px`, built: `${c}px` });
    }
    for (const p of SOFT) {
      const a = m.box[p];
      const c = b.box[p];
      if (Math.abs(a - c) <= Math.max(SOFT_ABS, a * SOFT_PCT)) continue;
      softOut.push({ sel: b.sel, prop: p, mock: a, built: c });
    }
  }
  return { hard, absent, soft: softOut, multi };
}

const argv = process.argv.slice(2);
const updateBaseline = argv.includes('--update-baseline');
const only = argv.filter((a) => !a.startsWith('--'));

const css = await readFile(BUNDLE, 'utf8');
const SELECTORS = selectorsFrom(css);
const pairs = only.length ? PAIRS.filter((p) => only.includes(p.name)) : PAIRS;

let baseline = null;
try {
  baseline = JSON.parse(await readFile(BASELINE, 'utf8'));
} catch {
  baseline = null;
}

const browser = await chromium.launch();
const rows = [];
const details = [];

for (const pair of pairs) {
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const mockRecs = await shoot(page, `${MOCK}/${pair.mock}`, SELECTORS);
    const builtRecs = await shoot(page, `${BUILT}${pair.route}`, SELECTORS);
    await ctx.close();

    const { hard, absent, soft, multi } = compare(mockRecs, builtRecs);
    const key = `${pair.name}@${width}`;
    const base = baseline?.pages?.[key];
    const regressed =
      base != null && (hard.length > base.hard || absent.length > base.absent);
    rows.push({
      key,
      page: pair.name,
      width,
      hard: hard.length,
      absent: absent.length,
      soft: soft.length,
      multi: multi.length,
      base,
      regressed,
    });
    console.log(
      `${pair.name.padEnd(14)} ${String(width).padStart(4)}` +
        `  hard=${String(hard.length).padStart(3)}${base ? `/${base.hard}` : ''}` +
        `  absent=${String(absent.length).padStart(3)}${base ? `/${base.absent}` : ''}` +
        `  soft=${String(soft.length).padStart(3)}` +
        `  multi=${String(multi.length).padStart(3)}${regressed ? '   REGRESSED' : ''}`,
    );
    if (hard.length || absent.length || soft.length || multi.length) {
      details.push(`\n### ${pair.name} at ${width}\n`);
      for (const f of hard) {
        details.push(`- HARD \`${f.sel}\` **${f.prop}**: drawing \`${f.mock}\` / built \`${f.built}\``);
      }
      for (const f of absent) {
        details.push(`- ABSENT \`${f.sel}\`: drawing \`${f.mock}\` / built \`${f.built}\``);
      }
      for (const f of soft) {
        details.push(`- soft \`${f.sel}\` ${f.prop}: drawing ${f.mock} / built ${f.built}`);
      }
      for (const f of multi) {
        details.push(`- MULTI \`${f.sel}\` ${f.prop}: drawing \`${f.mock}\` / built \`${f.built}\``);
      }
    }
  }
}
await browser.close();

const totals = rows.reduce(
  (a, r) => ({
    hard: a.hard + r.hard,
    absent: a.absent + r.absent,
    soft: a.soft + r.soft,
    multi: a.multi + r.multi,
  }),
  { hard: 0, absent: 0, soft: 0, multi: 0 },
);
const regressions = rows.filter((r) => r.regressed);

if (updateBaseline) {
  const pages = {};
  for (const r of rows) pages[r.key] = { hard: r.hard, absent: r.absent };
  const prev = baseline?.pages ?? {};
  await writeFile(BASELINE, `${JSON.stringify({ pages: { ...prev, ...pages } }, null, 2)}\n`, 'utf8');
  console.log(`\nbaseline written: ${BASELINE}`);
}

const lines = [
  '# Component parity: drawing against built page',
  '',
  'Generated by `store_platform/src/Store.Web/scripts/component_parity.mjs`.',
  `${SELECTORS.length} selectors are read out of`,
  '`store_platform/src/Store.Web/src/styles/mumchimp.css`; for each one, the first matching element',
  'in the drawing is compared against the first matching element in the built page, at 390 and 1280.',
  '',
  '- `hard` is a computed-style difference on a component both documents render. It is a defect.',
  '  Only selectors matching exactly ONE element in BOTH documents can be hard, because that is the',
  '  only case where the two elements are certainly the same component.',
  '- `MULTI` is the same comparison on a selector used more than once on the page. The two documents',
  '  were written independently, so the first match on each side may be unrelated elements. It says',
  '  where to look. It never gates.',
  '- `absent` is a component one document renders and the other does not, `display:none` included.',
  '  Some are defects and some are the content divergence in `docs/SITE_SPEC_PROGRAM.md` 11.9.',
  '- `soft` is width or height past tolerance. Usually copy. It never gates.',
  '',
  'The gate is a ratchet against `docs/design/component_parity_baseline.json`: a page may improve or',
  'hold, never get worse. The pixel harness `visual_regression.mjs` still runs and still writes its',
  'PNGs, but it reports rather than gates, for the reason recorded in 11.9.',
  '',
  '| Page | Width | Hard | Baseline | Absent | Baseline | Soft | Multi |',
  '| --- | --- | --- | --- | --- | --- | --- | --- |',
  ...rows.map(
    (r) =>
      `| ${r.page} | ${r.width} | ${r.hard} | ${r.base?.hard ?? '-'} | ${r.absent} |` +
      ` ${r.base?.absent ?? '-'} | ${r.soft} | ${r.multi} |`,
  ),
  '',
  `**Totals: hard ${totals.hard}, absent ${totals.absent}, soft ${totals.soft}.**`,
  regressions.length
    ? `**REGRESSED: ${regressions.map((r) => r.key).join(', ')}**`
    : '**No page is worse than its baseline.**',
  '',
  '## Findings',
  ...details,
  '',
];
await writeFile(REPORT, lines.join('\n'), 'utf8');

console.log(
  `\ntotals: hard=${totals.hard} absent=${totals.absent} soft=${totals.soft} multi=${totals.multi}`,
);
console.log(`report: ${REPORT}`);
/* RECORDING A BASELINE IS NOT GRADING AGAINST ONE. `regressions` was computed against the file as
   it stood BEFORE this run overwrote it, so reporting it here would grade a run against a baseline
   that no longer exists. The first `--update-baseline` run also used to print "no baseline on disk"
   one line after writing one. Recording ends the run. */
if (updateBaseline) {
  console.log(`baseline recorded for ${rows.length} page/width pairs`);
  process.exit(0);
}
if (!baseline) {
  console.log('no baseline on disk: reporting only. Run with --update-baseline to record one.');
  process.exit(0);
}
console.log(regressions.length ? `REGRESSED: ${regressions.length} page/width` : 'no page worse than baseline');
process.exit(regressions.length ? 1 : 0);
