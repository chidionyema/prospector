// @ledger writes | node verify.mjs | The browser gate: 10 designed + 3 rolled looks x 4 viewports x 2 themes (gate A54), plus the 20 screenshots the contact sheet shows.
/* Playwright is not a dependency of this prototype; it is borrowed from the storefront's own
 * node_modules. It is resolved from THIS file's own location, so it works in the main
 * checkout and in every worktree. It stays overridable for a machine that keeps it elsewhere:
 *   PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node <tool>.mjs
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || new URL('../../../store_platform/src/Store.Web/node_modules/playwright/index.mjs', import.meta.url).href);
import { mkdirSync, readFileSync, writeFileSync } from 'fs';

const FILE = 'file://' + process.cwd() + '/looks-engine.html';
// Read from the look data itself. A hand-kept copy of these ids means an
// eleventh look is silently never measured and never shot, and the gate still
// prints ALL PASS.
const LOOK_IDS = new Function(readFileSync('parts/03-looks.js', 'utf8') + '\n;return LOOKS;')().map((l) => l.id);
const VPS = [{n:'phone-390',w:390,h:844},{n:'tablet-834',w:834,h:1194},{n:'laptop-1440',w:1440,h:900},{n:'wide-2560',w:2560,h:1440}];
/* GATE A54 — a look NOBODY DESIGNED gets measured by the same eight checks as the ten. This is
   the only honest proof of C35. Ten hand-built looks demonstrate ten hand-built looks; the claim
   is "as many as you want", and it is unproven until an unseen one survives the whole gate. The
   numbers are fixed so a failure is reproducible: `window.rollNewLook(101)` in the console
   brings the same look back, forever.

   It is A54 and not A46 because A46 is already the cold-open test in
   docs/STOREFRONT_REDESIGN_PROGRAM.md:466, and A53 is the highest number that document
   uses. Two gates sharing a number is a trap: a green "A46" here would read as evidence
   for a criterion nobody has started. Read the doc before you number the next one. */
/* Overridable, because grading a candidate set means putting THOSE seeds through this gate.
   The default is unchanged, so the standing A54 proof still runs three fixed looks a failure
   can be reproduced from: ROLLS=623,878 node verify.mjs grades those two instead. */
const ROLLS = (process.env.ROLLS || '101,102,103').split(',').map(Number).filter(Number.isFinite);
mkdirSync('shots', { recursive: true });

const browser = await chromium.launch();
const rows = [];
/* The rolled looks exist only in the browser's memory, so nothing downstream can describe them
   unless this run writes them down. `shots/rolled.json` is that record, and the contact sheet
   reads it rather than re-rolling: a second roller is a second implementation of the generator,
   and the two would drift the day the catalogue changes. The accent is read out of the COMPUTED
   style, so it is the colour the page actually painted, not the one the seed asked for. */
const rolledMeta = {};
for (const theme of ['light','dark']) {
  for (const vp of VPS) {
    const ctx = await browser.newContext({ viewport:{width:vp.w,height:vp.h}, deviceScaleFactor:1, colorScheme:theme });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    await page.goto(FILE, { waitUntil:'networkidle' });
    for (const target of [...LOOK_IDS.map((id) => ({ id })), ...ROLLS.map((n) => ({ roll: n }))]) {
      const id = target.roll ? `roll-${target.roll}` : target.id;
      if (target.roll) {
        /* applyLook REFUSES a look that fails its contrast audit and returns null here when it
           does. A refusal is a gate FAILURE, not an exception to skip: the generator is supposed
           to be incapable of producing one. */
        const got = await page.evaluate((n) => window.rollNewLook(n), target.roll);
        if (!got) { rows.push({ look: id, theme, vp: vp.n, refused: 1, a11y: 'refused', errors: 0 }); continue; }
      } else {
        await page.evaluate((i)=>{ document.querySelector(`.chip[data-id="${i}"]`).click(); }, id);
      }
      await page.waitForTimeout(90);
      const m = await page.evaluate(() => {
        const html = document.documentElement;
        const a11y = document.getElementById('a11y');
        // Tap targets: every interactive element, measured as the union of its
        // line fragments would over-report inline links, so measure each box.
        const small = [];
        for (const el of document.querySelectorAll('a,button')) {
          const cs = getComputedStyle(el);
          if (cs.display === 'inline') continue;          // WCAG 2.2 inline exception
          for (const r of el.getClientRects()) {
            if (r.width < 1) continue;
            if (r.width < 24 || r.height < 24) small.push({ t: el.textContent.trim().slice(0,28), w:+r.width.toFixed(1), h:+r.height.toFixed(1) });
          }
        }
        const under44 = [];
        for (const el of document.querySelectorAll('.btn, nav.bar a, .chip, .console__theme')) {
          /* An element with NO box is not a small tap target, it is an absent control, and the
             two need different answers. `getClientRects()` is the difference: display:none
             returns none of them, while a control that is present and collapsed to 0px returns
             one and still fails — which is the bug this check exists to catch. Measured
             2026-08-20: the narrow nav hides FAQ and Account below 40rem, and this check called
             both of them 0px-tall tap targets and failed 26 of 104 cells. Two rules, each right
             on its own: hide what does not fit; refuse a control smaller than a fingertip. */
          const rects = el.getClientRects();
          if (!rects.length) continue;
          const r = rects[0];
          if (r.height < 44) under44.push({ t: el.textContent.trim().slice(0,24), h:+r.height.toFixed(1) });
        }
        // Blank canvas = a plate that failed to draw: every pixel in the buffer the same colour.
        //
        // This used to read ONE row, the middle one, and that is a gate that grades 1/130th of
        // the picture. `raster` lays its marks on rows where y % 3 === 0, two rows tall, so any
        // canvas whose mid-row lands on y % 3 === 2 reads as blank however well it drew. It cost
        // a diagnosis on 2026-08-20: The Instrument failed at tablet-834 (208x130, mid-row 65,
        // 65 % 3 === 2) and passed at 744 and 1024 for no reason but arithmetic. Read the whole
        // buffer. Any treatment may leave any single row empty, and that is not a defect.
        let blank = 0;
        for (const cv of document.querySelectorAll('canvas')) {
          const g = cv.getContext('2d');
          const d = g.getImageData(0, 0, cv.width, cv.height).data;
          const first = d[0] + ',' + d[1] + ',' + d[2];
          let same = true;
          for (let i = 4; i < d.length; i += 4) {
            if (d[i] + ',' + d[i+1] + ',' + d[i+2] !== first) { same = false; break; }
          }
          if (same) blank++;
        }
        /* COLLISION AND TRUNCATION — the C32 decision, research/C32-tooling.md.
           A property checker gates; a pixel comparator only reports change. These are the two
           layout failures a contrast gate and a document-overflow gate both miss: text clipped
           to nothing by a box that is too small for it, and two elements drawn on top of each
           other. Both look fine in a screenshot taken at the one width nobody broke.

           Only LEAVES are compared. An ancestor always overlaps its descendant, so comparing
           every element against every element reports the DOM tree as a wall of collisions —
           that is the proxy version of this check, and it is worse than no check because
           somebody has to read it. A leaf is an element with no element children that draws
           something: text, an image, a canvas.

           Rects, not bounding boxes. A link wrapped across two lines has a bounding box that
           covers the whole paragraph and every word beside it. `getClientRects()` gives the
           line fragments, which is what is actually painted. */
        const leaves = [];
        const meas = document.createElement('canvas').getContext('2d');
        const pathOf = (el) => {
          const p = [];
          for (let e = el; e && e !== document.body; e = e.parentElement) {
            const c = typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/)[0] : '';
            p.unshift(e.tagName.toLowerCase() + c);
          }
          return p.slice(-3).join('>');
        };
        /* RANGE rects, not element rects. `selectNodeContents` returns one rect per LINE of
           actual text, with no padding, no border and no empty box around it. An element rect is
           whatever the box model made — the ledger wordmark measures 253x146 for one 96px word,
           59px of which is nothing at all. */
        const lineRects = (el) => {
          if (['IMG', 'CANVAS', 'SVG'].includes(el.tagName)) return [...el.getClientRects()];
          const rg = document.createRange();
          rg.selectNodeContents(el);
          return [...rg.getClientRects()];
        };
        /* INK, measured from the font, not guessed from line-height. TextMetrics gives the real
           glyph extent for this string in this face: `actualBoundingBox*` is where the paint
           stops. The half-leading formula recovers the baseline inside a line box — and it works
           when line-height is SMALLER than font-size, which the ledger's wordmark is (96px text
           on an 86.4px line), where a (lh - fs)/2 inset silently gives up and reports the box. */
        const inkOf = (el, cs, rects, txt) => {
          if (['IMG', 'CANVAS', 'SVG'].includes(el.tagName)) return rects.map((r) => ({ left: r.left, right: r.right, top: r.top, bottom: r.bottom }));
          meas.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
          const m = meas.measureText(txt || 'X');
          const F = m.fontBoundingBoxAscent + m.fontBoundingBoxDescent;
          const out = [];
          for (const r of rects) {
            const base = r.top + (r.height - F) / 2 + m.fontBoundingBoxAscent;
            const top = base - m.actualBoundingBoxAscent, bottom = base + m.actualBoundingBoxDescent;
            if (bottom - top > 0.5) out.push({ left: r.left, right: r.right, top, bottom });
          }
          return out;
        };
        for (const el of document.querySelectorAll('body *')) {
          if (el.children.length && !['IMG', 'CANVAS', 'SVG'].includes(el.tagName)) continue;
          const txt = el.textContent.trim();
          if (!txt && !['IMG', 'CANVAS', 'SVG', 'HR'].includes(el.tagName)) continue;
          const cs = getComputedStyle(el);
          if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
          const rects = lineRects(el).filter((r) => r.width > 1 && r.height > 1);
          if (!rects.length) continue;
          const ink = inkOf(el, cs, rects, txt);
          if (!ink.length) continue;
          leaves.push({ el, cs, txt, rects, ink, path: pathOf(el),
            layered: cs.position !== 'static' || cs.transform !== 'none' || cs.zIndex !== 'auto' });
        }

        /* TRUNCATION. Not "does this element scroll" — "is any painted text hidden by a box that
           clips". So walk up to the nearest CLIPPING ancestor: a clipped leaf usually has
           overflow:visible itself and the clip lives two levels up. `text-overflow: ellipsis` and
           `-webkit-line-clamp` are deliberate — the reader can see the cut happened. A silent
           clip is the defect, and it is invisible in a screenshot by definition. */
        const clipped = [];
        for (const L of leaves) {
          let anc = L.el, box = null, deliberate = false;
          while (anc && anc !== document.body) {
            const cs = anc === L.el ? L.cs : getComputedStyle(anc);
            if (cs.textOverflow === 'ellipsis' || cs.webkitLineClamp !== 'none') deliberate = true;
            if (/hidden|clip/.test(cs.overflowX + cs.overflowY)) { box = anc; break; }
            anc = anc.parentElement;
          }
          if (!box || deliberate) continue;
          const b = box.getBoundingClientRect();
          for (const r of L.rects) {
            const over = Math.max(b.left - r.left, r.right - b.right, b.top - r.top, r.bottom - b.bottom);
            if (over > 1) { clipped.push({ t: L.txt.slice(0, 30), by: +over.toFixed(1), at: L.path }); break; }
          }
        }

        /* COLLISION. Two painted leaves sharing pixels. Anything the author LAYERED on purpose is
           excluded — positioned, transformed, or given a z-index — because deliberate stacking is
           what those three properties are FOR, and a check that flags them flags every badge on
           every card. What is left is normal flow, where an overlap is a box that grew past the
           room made for it. The 4px floor on both axes keeps sub-pixel rounding out. */
        const collide = [];
        for (let i = 0; i < leaves.length; i++) {
          const A = leaves[i];
          if (A.layered) continue;
          for (let j = i + 1; j < leaves.length; j++) {
            const B = leaves[j];
            if (B.layered) continue;
            if (A.el.contains(B.el) || B.el.contains(A.el)) continue;
            let hit = null;
            for (const ra of A.ink) for (const rb of B.ink) {
              const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
              const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
              if (w > 4 && h > 4) hit = { w: +w.toFixed(1), h: +h.toFixed(1) };
            }
            if (hit) collide.push({ a: `${A.path} "${A.txt.slice(0, 14)}"`, b: `${B.path} "${B.txt.slice(0, 14)}"`, ...hit });
          }
        }

        return {
          look: html.getAttribute('data-look'),
          theme: html.getAttribute('data-theme'),
          a11y: a11y ? a11y.dataset.state : 'missing',
          a11yText: a11y ? a11y.textContent : '',
          overflow: document.documentElement.scrollWidth > window.innerWidth + 1
                    ? document.documentElement.scrollWidth - window.innerWidth : 0,
          small: small.length, smallEx: small.slice(0,3),
          under44: under44.length, under44Ex: under44.slice(0,3),
          canvases: document.querySelectorAll('canvas').length, blank,
          leaves: leaves.length,
          clipped: clipped.length, clippedEx: clipped.slice(0, 3),
          collide: collide.length, collideEx: collide.slice(0, 3),
          heroFont: getComputedStyle(document.querySelector('.hero__head')).fontFamily.split(',')[0].replace(/"/g,''),
        };
      });
      if (target.roll && vp.n === 'laptop-1440') {
        const meta = await page.evaluate((i) => {
          const l = LOOKS.find((x) => x.id === i);
          const cs = getComputedStyle(document.documentElement);
          return { id: l.id, name: l.name, tagline: l.tagline, plate: l.plate, treatment: l.treatment,
                   display: l.type.display, body: l.type.body, mono: l.type.mono,
                   switches: l.switches, seed: l.seed, accent: cs.getPropertyValue('--accent').trim() };
        }, id);
        const { accent, ...rest } = meta;
        rolledMeta[id] = { ...(rolledMeta[id] || {}), ...rest, [`accent_${theme}`]: accent };
      }
      m.vp = vp.n; m.errors = errors.length; m.errEx = errors.slice(0,2);
      rows.push(m);
      if (vp.n === 'laptop-1440') await page.screenshot({ path:`shots/${id}-${theme}.png`, fullPage:true });
    }
    await ctx.close();
  }
}
await browser.close();
writeFileSync('shots/rolled.json', JSON.stringify(Object.values(rolledMeta), null, 1) + '\n');

const bad = rows.filter(r => r.refused || r.a11y!=='good' || r.overflow || r.small || r.under44 || r.errors || r.blank || r.clipped || r.collide);
console.log(`${rows.length} cells measured (${LOOK_IDS.length} designed + ${ROLLS.length} rolled looks x ${VPS.length} viewports x 2 themes)`);
if (bad.length) { console.log(`\n${bad.length} FAILING CELLS:`); for (const r of bad) console.log(JSON.stringify(r)); }
else console.log(`ALL PASS — 0 contrast refusals, 0 overflow, 0 sub-24px targets, 0 sub-44px controls, 0 blank plates, `
  + `0 clipped text, 0 collisions (${rows.reduce((n, r) => n + r.leaves, 0)} painted leaves compared), 0 console errors`);
console.log('\nfonts actually resolved per look:');
console.log([...new Set(rows.map(r=>`${r.look.padEnd(11)} ${r.heroFont}`))].join('\n'));
/* A gate that prints failures and exits 0 is a report. `runlog.sh` recorded `exit=0` for a run
   with 80 failing cells, and every tool downstream of it — the tools page, the log header, the
   next agent reading a green tick — repeated that. Say it in the status. */
process.exitCode = bad.length ? 1 : 0;
