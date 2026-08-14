// Renders the LIVE storefront at real device widths and measures the boxes it produces.
//
// Why this exists as a geometry measurement and not a source assertion: the defect class it
// guards is invisible in the component that carries it. On 2026-08-14 the pack row's meta line
// painted "48" on top of "US rules" ("48S rules" on the founder's phone) because a flex row could
// not wrap and had no `min-w-0`; every class in `PackFigure` read correctly, and the collision
// existed only in the layout those classes produced under that particular parent. `storefront.
// spec.ts:71` already makes this argument for the basket drawer, in its own words: "only a
// rendered check would catch that." This file is the same instrument aimed at production and at
// the pack list, which is the page every buyer lands on.
//
// It reports the POPULATION it scored alongside the verdict, and exits non-zero when that
// population is empty. That is not defensive padding. The first version of this probe reported
// zero collisions against the very production page the founder had just photographed showing the
// bug, because its row filter was `width > 340` while real rows measure 342 -- it had skipped
// every visible row and scored only the collapsed ones, whose rects are all zero. A probe that
// has never been seen to fire has proven nothing, so "0 rows scored" must fail loudly rather than
// read as "0 defects".
//
// It lives under Store.Web/scripts/ rather than beside its driver in store_platform/scripts/
// because ESM resolves a bare import from the IMPORTING FILE's directory, not from the process
// cwd. Running it with `cwd=Store.Web` therefore does not help it find `@playwright/test`; the
// file itself has to sit inside the package that owns the dependency.
//
// Usage: node scripts/prove_live_geometry.mjs <base-url>
//   exit 0 = clean, 1 = defects found, 2 = probe could not measure

import { chromium } from '@playwright/test';

const BASE = (process.argv[2] || 'https://mumchimp.com').replace(/\/$/, '');

// `--self-test` deliberately breaks the live page in memory before measuring it, and then
// REQUIRES the probe to report the breakage. It is the answer to the failure this file's header
// describes: the instrument reported clean against a page that was visibly broken, and clean is
// indistinguishable from blind unless the instrument has been seen to fire.
//
// The injected defect is a positioned span dropped on top of an existing leaf rather than a
// recreation of the original CSS bug. That is on purpose -- what silently broke last time was the
// DETECTOR (row anchoring, leaf selection, the intersection maths), not the app, so the self-test
// exercises the detector against a violation it cannot miss for any reason to do with the app's
// current stylesheet.
const SELF_TEST = process.argv.includes('--self-test');

// 390x844 is the iPhone 13/14 logical viewport, which is where every mobile defect in this
// programme has been reported. 1440x900 is carried because the 2026-08-14 failure was
// mobile-ONLY (0 collisions at 1440 on both sides of the fix) -- without the desktop column a
// future regression that runs the other way would look identical to a clean mobile run.
const VIEWPORTS = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'desktop', width: 1440, height: 900 },
];

// The measurement, run inside the page. Kept in one evaluate() so the rects are all sampled from
// the same layout pass; sampling across round-trips would let a lazy image resize the row between
// two reads and manufacture a collision that no human could ever see.
function measure() {
  // Anchor on the real row element rather than on a size heuristic. `index.tsx:381/:520/:658`
  // render every pack card as a link to `/pack/<id>`, so this selector is the page's own
  // structure and cannot drift by two pixels the way a width threshold can.
  const rows = Array.from(document.querySelectorAll('a[href^="/pack/"]'));

  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // Leaves only. A parent's box legitimately contains its children's, so scoring every element
  // against every other would report the whole document as one giant collision.
  const leaves = (root) =>
    Array.from(root.querySelectorAll('*')).filter(
      (el) => el.children.length === 0 && (el.textContent || '').trim() !== '' && visible(el),
    );

  const label = (el) => {
    const t = (el.textContent || '').trim().slice(0, 24);
    return `${el.tagName.toLowerCase()}"${t}"`;
  };

  const collisions = [];
  const overflows = [];
  let scored = 0;

  for (const row of rows) {
    const rb = row.getBoundingClientRect();
    // Collapsed rows (behind "show the other N packs") have zero-area boxes and are not being
    // shown to anyone; measuring them is what produced the false clean.
    if (rb.width < 40 || rb.height < 20) continue;
    scored += 1;

    const items = leaves(row);

    // 1. Nothing inside a row may paint over anything else inside it. A 1px tolerance absorbs
    //    sub-pixel rounding on fractional layouts; the real defect measured 7px of overlap.
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        const a = items[i].getBoundingClientRect();
        const b = items[j].getBoundingClientRect();
        if (items[i].contains(items[j]) || items[j].contains(items[i])) continue;
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 1 && oy > 1) {
          collisions.push(
            `${label(items[i])} X ${label(items[j])} ox=${Math.round(ox)} oy=${Math.round(oy)}`,
          );
        }
      }
    }

    // 2. Nothing may escape its own card. The sparkline ran to the viewport edge past the card's
    //    right padding, which is how the defect showed up on the phone.
    for (const el of items) {
      const b = el.getBoundingClientRect();
      if (b.right > rb.right + 1 || b.left < rb.left - 1) {
        overflows.push(
          `${label(el)} L=${Math.round(b.left)} R=${Math.round(b.right)} outside card ${Math.round(rb.left)}..${Math.round(rb.right)}`,
        );
      }
    }
  }

  return {
    scored,
    rowsFound: rows.length,
    collisions,
    overflows,
    // 3. The page itself must not scroll sideways. This is the cheapest possible catch for a
    //    whole family of overflow bugs that never manifest as a row-internal collision.
    docScrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
}

const browser = await chromium.launch();
let worst = 0;

try {
  for (const vp of VIEWPORTS) {
    const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
    // `networkidle` never settles against a page with polling or analytics and turns a probe into
    // a hang; the rows are server-rendered, so `domcontentloaded` plus an explicit wait for the
    // row selector is both faster and stricter about what it actually needs.
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForSelector('a[href^="/pack/"]', { timeout: 30_000 }).catch(() => {});
    // The Next dev overlay is a fixed-position element that legitimately covers the page; it does
    // not exist in production but would poison a local run of the same probe.
    await page.evaluate(() => document.querySelector('nextjs-portal')?.remove());

    if (SELF_TEST) {
      const planted = await page.evaluate(() => {
        const row = Array.from(document.querySelectorAll('a[href^="/pack/"]')).find((el) => {
          const b = el.getBoundingClientRect();
          return b.width > 40 && b.height > 20;
        });
        if (!row) return 0;
        const victim = Array.from(row.querySelectorAll('*')).find(
          (el) => el.children.length === 0 && (el.textContent || '').trim() !== '',
        );
        if (!victim) return 0;
        const b = victim.getBoundingClientRect();
        const spy = document.createElement('span');
        spy.textContent = 'PROBE-SELFTEST';
        spy.style.cssText = `position:fixed;left:${b.left + 2}px;top:${b.top + 2}px;width:${Math.max(b.width - 4, 8)}px;height:${Math.max(b.height - 4, 8)}px;`;
        victim.parentElement.appendChild(spy);
        return 1;
      });
      if (!planted) {
        console.log(`FAIL  ${vp.name} ${vp.width}px — self-test could not plant a defect (no row to break)`);
        worst = Math.max(worst, 2);
        await page.close();
        continue;
      }
    }

    const r = await page.evaluate(measure);

    if (SELF_TEST) {
      // Inverted verdict: a clean read here means the instrument is broken, not the page.
      const caught = r.collisions.some((c) => c.includes('PROBE-SELFTEST'));
      if (caught) {
        console.log(`PASS  ${vp.name} ${vp.width}px — self-test: probe DID detect the planted overlap (${r.scored} rows scored)`);
      } else {
        console.log(`FAIL  ${vp.name} ${vp.width}px — self-test: probe MISSED a planted overlap; it is blind, and any clean result from it is worthless`);
        worst = Math.max(worst, 2);
      }
      await page.close();
      continue;
    }
    const bad = r.collisions.length + r.overflows.length;
    const sideways = r.docScrollWidth > r.innerWidth + 1;

    if (r.scored === 0) {
      console.log(`FAIL  ${vp.name} ${vp.width}px — scored 0 rows (found ${r.rowsFound}); the probe measured nothing`);
      worst = Math.max(worst, 2);
    } else if (bad === 0 && !sideways) {
      console.log(`PASS  ${vp.name} ${vp.width}px — ${r.scored} rows, 0 collisions, 0 overflow, doc ${r.docScrollWidth}px`);
    } else {
      console.log(
        `FAIL  ${vp.name} ${vp.width}px — ${r.scored} rows, ${r.collisions.length} collisions, ${r.overflows.length} overflow, doc ${r.docScrollWidth}px vs ${r.innerWidth}px`,
      );
      for (const c of r.collisions.slice(0, 8)) console.log(`        overlap  ${c}`);
      for (const o of r.overflows.slice(0, 8)) console.log(`        escapes  ${o}`);
      worst = Math.max(worst, 1);
    }
    await page.close();
  }
} finally {
  // The browser must close on every path. A `pi` session was wedged 4h32m because a verifier's
  // browser was never closed and Node's event loop never drained.
  await browser.close();
}

process.exit(worst);
