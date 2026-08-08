// Fold probe — docs/DESIGN_UX_AUDIT_PROGRAM.md F-001.
//
// F-001 was measured against production at `bcda8cc` and blamed "the proof strip, 240px".
// That attribution cannot be carried forward: on main the strip renders `hidden md:block`
// (src/pages/index.tsx), so it contributes ZERO height on a phone. `e2e/discovery.spec.ts:56`
// blames something else again (the filter-log panel stacking). Two prose diagnoses, neither
// re-measured against the tree we are about to edit.
//
// So this probe does not assert a culprit. It measures the height budget and ATTRIBUTES it:
// every block between the top of the document and the first visible pack card, with its own
// height, sorted by cost. You fix the top of that list, not the one a stale doc names.
//
//   FOLD_BASE=http://localhost:3411 node scripts/design-audit/measure-fold.mjs
//
// Exit 1 if the first pack card shows less than MIN_VISIBLE_PX at any phone viewport --
// the same bar `e2e/discovery.spec.ts` asserts (40px of card actually on screen, because a
// card whose top edge lands one pixel above the fold satisfies "above the fold" and shows
// the buyer nothing).
//
import { chromium } from '@playwright/test';

const BASE = process.env.FOLD_BASE ?? 'http://localhost:3000';
const MIN_VISIBLE_PX = 40;

// Three widths, not one: the failure is a height budget and a fixed-cost block clears a tall
// phone while failing a short one. 430x932 cleared by 2px in the original audit -- that is a
// pass that carries no margin, so it is reported as a number, never as "fine".
const VIEWPORTS = [
  { name: '360x780', width: 360, height: 780 },
  { name: '390x844', width: 390, height: 844 },
  { name: '430x932', width: 430, height: 932 },
  { name: '1280x720', width: 1280, height: 720 }, // the viewport CI actually runs
];

// Two forms of the same target. `:visible` is a Playwright selector-engine pseudo-class and is
// NOT valid CSS, so it works in page.locator() and throws inside document.querySelectorAll().
// The in-page walk therefore uses the plain selector and filters on a non-zero box itself.
const CARD = 'a[href^="/pack/"]:visible';
const CARD_CSS = 'a[href^="/pack/"]';

/**
 * Attribute the vertical budget above the first card.
 *
 * Walks down from <body>, descending into any element whose subtree contains the card, and
 * records the siblings that sit ABOVE it. That yields the blocks whose height is actually
 * spent, at the grain a person can edit -- not a flat list of every node on the page.
 */
async function attributeBudget(page) {
  return page.evaluate((cardSel) => {
    const card = [...document.querySelectorAll(cardSel)].find((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    if (!card) return null;

    const cardTop = card.getBoundingClientRect().top + window.scrollY;
    const blocks = [];

    function describe(el) {
      const tag = el.tagName.toLowerCase();
      const id = el.id ? `#${el.id}` : '';
      const cls = typeof el.className === 'string' && el.className
        ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.')
        : '';
      // innerText, NOT textContent. textContent serialises `display:none` subtrees too, so the
      // hero band reported the text of `AmbientKillColumn` -- a `hidden lg:block` element
      // contributing zero pixels on a phone -- and that label sent me looking for a 379px
      // block that does not exist on mobile. A height probe must name what is RENDERED.
      const text = (el.innerText ?? el.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 48);
      return `${tag}${id}${cls}${text ? ` "${text}"` : ''}`;
    }

    let container = document.body;
    // Descend while some child still fully contains the card: that child is a wrapper, and
    // its siblings above are the real cost centres.
    for (let depth = 0; depth < 12; depth++) {
      const kids = [...container.children];
      const holder = kids.find((k) => k.contains(card));
      if (!holder) break;
      for (const k of kids) {
        if (k === holder) break; // only siblings before the card's ancestor in DOM order
        const r = k.getBoundingClientRect();
        // DOM order is not visual order once flex `order` is in play -- the F-001 fix moves a
        // band below the shelf while leaving it earlier in the document. A block that renders
        // BELOW the card costs the fold nothing, so listing it as part of the budget would
        // report a fix as having changed nothing.
        if (r.height > 0 && r.bottom + window.scrollY <= cardTop + 1) {
          blocks.push({ h: Math.round(r.height), what: describe(k), depth });
        }
      }
      if (holder === card) break;
      container = holder;
    }

    return {
      cardTop: Math.round(cardTop),
      cardHref: card.getAttribute('href'),
      docHeight: Math.round(document.documentElement.scrollHeight),
      blocks,
    };
  }, CARD_CSS);
}

const browser = await chromium.launch();
const rows = [];
let hardFail = false;

for (const vp of VIEWPORTS) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  try {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 45000 });
    const box = await page.locator(CARD).first().boundingBox();
    const budget = await attributeBudget(page);

    if (!box) {
      // A card with no box is not "below the fold", it is absent. Reported as its own
      // failure so it is never read as a fold measurement.
      rows.push({ vp: vp.name, error: 'no visible pack card on / — NOT a fold result' });
      hardFail = true;
      continue;
    }

    const visible = Math.round(vp.height - box.y);
    const pass = visible > MIN_VISIBLE_PX;
    if (!pass) hardFail = true;
    rows.push({
      vp: vp.name,
      y: Math.round(box.y),
      fold: vp.height,
      visible,
      screens: (box.y / vp.height + 1).toFixed(2),
      pass,
      budget,
    });
  } catch (e) {
    // An outage is the end of the measurement, not a datum.
    rows.push({ vp: vp.name, error: `PROBE-ERROR ${e.message.slice(0, 120)}` });
    hardFail = true;
  } finally {
    await page.close();
  }
}

await browser.close();

console.log(`\nFOLD PROBE — ${BASE}/  (bar: >${MIN_VISIBLE_PX}px of the first pack card visible)\n`);
for (const r of rows) {
  if (r.error) {
    console.log(`  ${r.vp.padEnd(10)} ERROR  ${r.error}`);
    continue;
  }
  const verdict = r.pass ? 'PASS' : 'FAIL';
  console.log(
    `  ${r.vp.padEnd(10)} card top y=${String(r.y).padStart(4)}  fold=${r.fold}  ` +
      `visible=${String(r.visible).padStart(5)}px  (${r.screens} screens)  ${verdict}`,
  );
}

console.log('\nHEIGHT BUDGET above the first card (biggest first, per viewport):\n');
for (const r of rows) {
  if (r.error || !r.budget) continue;
  console.log(`  ${r.vp}  — card at y=${r.budget.cardTop}, doc ${r.budget.docHeight}px, card ${r.budget.cardHref}`);
  const sorted = [...r.budget.blocks].sort((a, b) => b.h - a.h);
  for (const b of sorted) console.log(`      ${String(b.h).padStart(4)}px  ${b.what}`);
  console.log('');
}

process.exit(hardFail ? 1 : 0);
