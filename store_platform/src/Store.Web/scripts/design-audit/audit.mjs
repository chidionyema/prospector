// Design/UX audit capture harness — docs/DESIGN_UX_AUDIT_PROGRAM.md §2.
//
// READ-ONLY against a running site. It writes PNGs + one JSON of measurements and
// never asserts anything: judgement belongs in the findings, not in the collector.
// The programme's §0.2 rule is why this exists at all — "measure the RENDERED page",
// because a stylesheet declares intent while only the page tells the truth.
//
//   AUDIT_BASE=https://mumchimp.com node scripts/design-audit/audit.mjs
//
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../../../../..');

const BASE = process.env.AUDIT_BASE ?? 'https://mumchimp.com';
const OUTDIR = path.resolve(process.env.AUDIT_OUT ?? path.join(REPO_ROOT, 'docs/audit'));
const ONLY = process.env.AUDIT_ONLY ? new Set(process.env.AUDIT_ONLY.split(',')) : null;

// §2: five real viewports plus 2560 for max-width behaviour. 360x780 is the worst-case
// Android that already caught the fold regression; 768 is "the width nobody tests".
const VIEWPORTS = [
  { w: 320, h: 568, label: '320' },
  { w: 360, h: 780, label: '360' },
  { w: 390, h: 844, label: '390' },
  { w: 768, h: 1024, label: '768' },
  { w: 1440, h: 900, label: '1440' },
  { w: 2560, h: 1440, label: '2560' },
];

const ROUTES = [
  { id: 'home', route: '/' },
  { id: 'pricing', route: '/pricing' },
  { id: 'sample', route: '/sample' },
  { id: 'kill-log', route: '/kill-log' },
  { id: 'how-it-works', route: '/how-it-works' },
  { id: 'ideas-index', route: '/ideas' },
  { id: 'about', route: '/about' },
  { id: 'faq', route: '/faq' },
  { id: 'order-success', route: '/orders/success' },
  { id: 'account', route: '/account' },
  { id: 'terms', route: '/terms' },
  { id: 'privacy', route: '/privacy' },
  { id: 'refund', route: '/refund' },
  { id: '404', route: '/__audit_probe_404__' },
];

const skipped = [];

// The two dynamic routes are the money page and the SEO page; hardcoding an id would
// rot silently, so resolve a real one off the live index each run.
async function resolveDynamic() {
  const pick = async (url, re, id) => {
    try {
      const html = await (await fetch(url)).text();
      const hit = [...new Set(html.match(re) ?? [])][0];
      if (hit) return { id, route: hit };
      skipped.push(`${id}: no ${re} link found on ${url}`);
    } catch (err) {
      skipped.push(`${id}: could not fetch ${url} — ${String(err)}`);
    }
    return null;
  };
  const out = [];
  const pack = await pick(`${BASE}/`, /\/pack\/[a-zA-Z0-9_-]+/g, 'pack-detail');
  const idea = await pick(`${BASE}/ideas`, /\/ideas\/[a-zA-Z0-9_-]+/g, 'idea-detail');
  if (pack) out.push(pack);
  if (idea) out.push(idea);
  return out;
}

// Runs in the browser. Everything here is a number off the rendered page.
function measure() {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.01;
  };
  const parseRGB = (s) => {
    const m = String(s).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x.trim()));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const lum = (c) => {
    const f = c.slice(0, 3).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  };
  const ratio = (fg, bg) => {
    const a = lum(fg);
    const b = lum(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  // First opaque ancestor background. Compositing translucent layers would be guesswork;
  // taking the first >=0.95 alpha is honest and reproducible.
  const effectiveBg = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const c = parseRGB(getComputedStyle(n).backgroundColor);
      if (c && c[3] >= 0.95) return c;
      n = n.parentElement;
    }
    const rootC = parseRGB(getComputedStyle(document.body).backgroundColor);
    return rootC && rootC[3] >= 0.95 ? rootC : [255, 255, 255, 1];
  };
  const accName = (el) =>
    (
      el.getAttribute('aria-label') ||
      el.getAttribute('title') ||
      el.getAttribute('alt') ||
      (el.textContent || '').trim().replace(/\s+/g, ' ')
    ).slice(0, 60);
  const cssPath = (el) => {
    const parts = [];
    let n = el;
    for (let i = 0; n && i < 4; i++) {
      let s = n.tagName.toLowerCase();
      if (n.id) {
        parts.unshift(`${s}#${n.id}`);
        break;
      }
      const cls =
        n.className && typeof n.className === 'string'
          ? n.className.trim().split(/\s+/).slice(0, 2).join('.')
          : '';
      if (cls) s += `.${cls}`;
      parts.unshift(s);
      n = n.parentElement;
    }
    return parts.join('>').slice(0, 160);
  };

  const all = [...document.querySelectorAll('body *')];
  const vis = all.filter(visible);
  // Only elements owning a DIRECT text node: otherwise every wrapper inherits its
  // child's text and the census counts the same string a dozen times.
  const textEls = vis.filter((el) =>
    [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 0),
  );

  // 1. Block ledger — the technique that turned "the fold feels tight" into a table.
  const root = document.querySelector('main') || document.body;
  const blocks = [];
  for (const child of [...root.children]) {
    const r = child.getBoundingClientRect();
    const consider = [child];
    if (r.height > vh) consider.push(...child.children);
    for (const el of consider) {
      const rr = el.getBoundingClientRect();
      if (rr.top < vh && rr.bottom > 0 && rr.height > 0) {
        blocks.push({
          sel: cssPath(el),
          y: Math.round(rr.top + scrollY),
          h: Math.round(rr.height),
          text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60),
        });
      }
    }
  }
  blocks.sort((a, b) => a.y - b.y);

  // 2. Type census
  const typeCensus = {};
  const sizeSet = new Set();
  for (const el of textEls) {
    const cs = getComputedStyle(el);
    const key = `${cs.fontSize}|${cs.fontWeight}|${cs.lineHeight}`;
    sizeSet.add(parseFloat(cs.fontSize));
    if (!typeCensus[key]) {
      typeCensus[key] = { count: 0, sample: cssPath(el), family: cs.fontFamily.split(',')[0] };
    }
    typeCensus[key].count += 1;
  }

  // 3. Style census
  const bag = {
    colors: new Set(),
    backgrounds: new Set(),
    borderColors: new Set(),
    radii: new Set(),
    shadows: new Set(),
    gaps: new Set(),
    durations: new Set(),
    easings: new Set(),
  };
  for (const el of textEls) bag.colors.add(getComputedStyle(el).color);
  for (const el of vis) {
    const cs = getComputedStyle(el);
    const bg = parseRGB(cs.backgroundColor);
    if (bg && bg[3] >= 0.05) bag.backgrounds.add(cs.backgroundColor);
    if (cs.borderTopWidth !== '0px') bag.borderColors.add(cs.borderTopColor);
    if (cs.borderRadius !== '0px') bag.radii.add(cs.borderRadius);
    if (cs.boxShadow !== 'none') bag.shadows.add(cs.boxShadow);
    for (const g of [cs.columnGap, cs.rowGap]) {
      if (g && g !== 'normal' && g !== '0px') bag.gaps.add(g);
    }
    for (const d of [cs.transitionDuration, cs.animationDuration]) {
      if (d && d !== '0s' && !/^0s(,\s*0s)*$/.test(d)) bag.durations.add(d);
    }
    if (cs.transitionDuration !== '0s') bag.easings.add(cs.transitionTimingFunction);
  }
  const styleCensus = {};
  for (const [k, v] of Object.entries(bag)) {
    const arr = [...v].sort();
    styleCensus[k] = arr.slice(0, 60);
    styleCensus[`${k}Count`] = arr.length;
  }

  // 4. Contrast at the programme's AAA bar (T1), not the WCAG AA floor.
  const cf = [];
  let checked = 0;
  for (const el of textEls) {
    const cs = getComputedStyle(el);
    const fg = parseRGB(cs.color);
    if (!fg || fg[3] < 0.5) continue;
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (weight >= 700 && size >= 18.66);
    const required = large ? 4.5 : 7;
    const bg = effectiveBg(el);
    const r = ratio(fg, bg);
    checked += 1;
    if (r < required) {
      cf.push({
        sel: cssPath(el),
        text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40),
        size,
        weight,
        ratio: Math.round(r * 100) / 100,
        required,
        fg: cs.color,
        bg: `rgb(${bg[0]}, ${bg[1]}, ${bg[2]})`,
      });
    }
  }
  cf.sort((a, b) => a.ratio - b.ratio);

  // 5. Tap targets (T3: 44x44)
  const INTERACTIVE =
    'a, button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [tabindex]:not([tabindex="-1"])';
  const targets = [...document.querySelectorAll(INTERACTIVE)].filter(visible);
  const tf = [];
  for (const el of targets) {
    const r = el.getBoundingClientRect();
    if (r.width < 44 || r.height < 44) {
      tf.push({ sel: cssPath(el), name: accName(el), w: Math.round(r.width), h: Math.round(r.height) });
    }
  }
  tf.sort((a, b) => a.w * a.h - b.w * b.h);

  // 6. Reflow (T9)
  const culprits = [];
  for (const el of vis) {
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) {
      culprits.push({ sel: cssPath(el), left: Math.round(r.left), right: Math.round(r.right) });
    }
  }

  // 8. CLS risk (T6): an image with no reserved box is a shift waiting to happen.
  const imagesNoBox = [];
  for (const el of [...document.querySelectorAll('img')].filter(visible)) {
    const hasAttrs = el.getAttribute('width') && el.getAttribute('height');
    const ar = getComputedStyle(el).aspectRatio;
    if (!hasAttrs && (!ar || ar === 'auto')) {
      const r = el.getBoundingClientRect();
      imagesNoBox.push({
        sel: cssPath(el),
        src: (el.currentSrc || el.src || '').slice(-70),
        w: Math.round(r.width),
        h: Math.round(r.height),
      });
    }
  }

  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .filter(visible)
    .map((el) => ({ level: Number(el.tagName[1]), text: (el.textContent || '').trim().slice(0, 70) }));

  return {
    blockLedger: blocks,
    typeCensus,
    sizes: [...sizeSet].sort((a, b) => a - b),
    styleCensus,
    contrast: { checked, failureCount: cf.length, failures: cf.slice(0, 40) },
    tapTargets: { checked: targets.length, failureCount: tf.length, failures: tf.slice(0, 40) },
    overflow: {
      scrollWidth: Math.round(document.documentElement.scrollWidth),
      innerWidth: vw,
      overflows: document.documentElement.scrollWidth > vw + 1,
      culprits: culprits.slice(0, 15),
    },
    perf: {
      lcp: Math.round(window.__lcp || 0),
      cls: Math.round((window.__cls || 0) * 1000) / 1000,
      shifts: (window.__shifts || []).slice(0, 10),
    },
    imagesNoBox: { count: imagesNoBox.length, items: imagesNoBox.slice(0, 20) },
    focusOrder: {
      focusableCount: targets.length,
      positiveTabindex: targets
        .filter((el) => Number(el.getAttribute('tabindex')) > 0)
        .map((el) => ({ sel: cssPath(el), tabindex: el.getAttribute('tabindex') }))
        .slice(0, 10),
    },
    headings,
    h1Count: headings.filter((h) => h.level === 1).length,
    title: document.title,
    metaDescription: document.querySelector('meta[name=description]')?.content ?? null,
  };
}

const OBSERVERS = () => {
  window.__lcp = 0;
  window.__cls = 0;
  window.__shifts = [];
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__lcp = Math.max(window.__lcp, e.startTime);
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch {}
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        if (!e.hadRecentInput) {
          window.__cls += e.value;
          window.__shifts.push({ v: Math.round(e.value * 1000) / 1000, t: Math.round(e.startTime) });
        }
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch {}
};

fs.mkdirSync(OUTDIR, { recursive: true });
const routes = [...ROUTES, ...(await resolveDynamic())].filter((r) => !ONLY || ONLY.has(r.id));
const results = [];
let errors = 0;

const browser = await chromium.launch();
try {
  for (const { id, route } of routes) {
    for (const { w, h, label } of VIEWPORTS) {
      const page = await browser.newPage({ viewport: { width: w, height: h } });
      const rec = { id, route, viewport: label, w, h };
      try {
        await page.addInitScript(OBSERVERS);
        await page.goto(BASE + route, { waitUntil: 'networkidle', timeout: 45000 });
        await page.waitForTimeout(1200);

        // MEASURE BEFORE SCREENSHOTTING. A fullPage screenshot resizes the viewport,
        // which re-fires largest-contentful-paint for the SAME element at its new size
        // with a late timestamp — and `measure` takes the max of every entry. Read in
        // the other order this reported home@1440 LCP as 4964ms when the real figure is
        // ~1100ms; the late "candidate" was the H1 again, 3652ms, size 55263 vs 51728.
        // Layout-shift is buffered and accumulating too, so CLS was inflated the same way.
        Object.assign(rec, await page.evaluate(measure));

        for (const [file, opts] of [
          [`${id}-${label}.png`, { fullPage: true }],
          [`${id}-${label}-fold.png`, {}],
        ]) {
          try {
            await page.screenshot({ path: path.join(OUTDIR, file), ...opts });
          } catch (err) {
            rec.screenshotError = String(err).slice(0, 200);
          }
        }

        // Axe twice per route, not six times: the violations are structural, and a
        // six-viewport sweep would triple the run for near-duplicate output.
        rec.axe = null;
        if (label === '360' || label === '1440') {
          try {
            await page.addScriptTag({ path: require.resolve('axe-core') });
            const res = await page.evaluate(async () =>
              window.axe.run(document, { resultTypes: ['violations'] }),
            );
            rec.axe = res.violations.map((v) => ({
              id: v.id,
              impact: v.impact,
              help: v.help,
              nodes: v.nodes.length,
              sample: (v.nodes[0]?.target ?? []).join(' '),
            }));
          } catch (err) {
            rec.axeError = String(err).slice(0, 200);
          }
        }

        rec.reducedMotion = null;
        rec.dark = null;
        if (label === '360') {
          try {
            await page.emulateMedia({ reducedMotion: 'reduce' });
            await page.reload({ waitUntil: 'networkidle', timeout: 45000 });
            await page.waitForTimeout(600);
            // A DECLARED transition is not a violation — 3766 elements carrying a
            // 150ms transition is a design system, not a defect. The only honest
            // question under `reduce` is: does anything still move for longer than
            // the 200ms bar? Counting non-zero durations flagged a passing site.
            rec.reducedMotion = await page.evaluate(() => {
              const over = [];
              let declared = 0;
              for (const el of document.querySelectorAll('body *')) {
                const cs = getComputedStyle(el);
                const d = parseFloat(cs.transitionDuration) || 0;
                const a = parseFloat(cs.animationDuration) || 0;
                if (d > 0 || a > 0) declared += 1;
                if (d > 0.2 || a > 0.2) {
                  over.push({
                    sel: `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)}`,
                    transition: cs.transitionDuration,
                    animation: cs.animationDuration,
                  });
                }
              }
              let rmRules = 0;
              for (const s of document.styleSheets) {
                try {
                  for (const r of s.cssRules) {
                    if (/prefers-reduced-motion/.test(r.conditionText || r.media?.mediaText || '')) rmRules += 1;
                  }
                } catch {}
              }
              return {
                emulated: matchMedia('(prefers-reduced-motion: reduce)').matches,
                reducedMotionRules: rmRules,
                declaredNonZero: declared,
                over200ms: over.length,
                sample: over.slice(0, 10),
              };
            });
            await page.emulateMedia({ reducedMotion: null });

            await page.emulateMedia({ colorScheme: 'dark' });
            await page.reload({ waitUntil: 'networkidle', timeout: 45000 });
            await page.waitForTimeout(600);
            rec.dark = await page.evaluate(() => {
              const cs = getComputedStyle(document.body);
              return { bg: cs.backgroundColor, fg: cs.color };
            });
            await page.screenshot({ path: path.join(OUTDIR, `${id}-360-dark.png`) });
            await page.emulateMedia({ colorScheme: null });
          } catch (err) {
            rec.mediaError = String(err).slice(0, 200);
          }
        }

        console.log(
          `${id.padEnd(14)} ${label.padEnd(5)} text:${String(rec.contrast.checked).padStart(4)} ` +
            `contrast:${String(rec.contrast.failureCount).padStart(3)} ` +
            `tap:${String(rec.tapTargets.failureCount).padStart(3)}/${rec.tapTargets.checked} ` +
            `ovf:${rec.overflow.overflows ? 'YES' : 'no '} ` +
            `lcp:${String(rec.perf.lcp).padStart(5)} cls:${rec.perf.cls}`,
        );
      } catch (err) {
        rec.error = String(err).slice(0, 300);
        errors += 1;
        console.log(`${id.padEnd(14)} ${label.padEnd(5)} ERROR ${rec.error.slice(0, 90)}`);
      } finally {
        results.push(rec);
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
}

const outfile = path.join(OUTDIR, 'audit-raw.json');
fs.writeFileSync(
  outfile,
  JSON.stringify({ base: BASE, generatedAt: new Date().toISOString(), skipped, results }, null, 2),
);
console.log(`\nWROTE ${outfile} — ${results.length} page/viewport pairs, ${errors} errors`);
if (skipped.length) console.log(`SKIPPED: ${skipped.join('; ')}`);
process.exit(0);
