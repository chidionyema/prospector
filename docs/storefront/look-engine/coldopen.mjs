// @ledger read-only | node coldopen.mjs | Gates A46, A48 and A49. Grades the FIRST SCREEN a stranger sees, at four widths including 320px.
/* GATE A46 — the cold-open test.  GATE A48 — no unexplained jargon above the fold.
 * GATE A49 — the entry costs nothing.
 *
 * C36's point is that everyone building this has seen the site hundreds of times and can no
 * longer experience the first five seconds, so the first five seconds have to be graded by a
 * procedure. This is that procedure for the three questions a machine can answer.
 *
 * WHAT COUNTS AS THE FIRST SCREEN: every element whose box starts above `innerHeight`, is
 * painted, and is NOT inside `.console`. The console strip is our prototype's look switcher —
 * scaffolding, not product. Counting it would let the word "look" and the button "Roll a look"
 * answer the visitor's questions, which is the proxy version of this gate: a page that passes
 * because of the tooling bolted to the top of it.
 *
 * WHY 320px IS IN THE MATRIX and is not in verify.mjs's: the doc pins Q1 to "above the fold,
 * without scrolling, at 320px". 390 is the narrowest phone anyone here owns, which is exactly
 * the reason it is the wrong floor to design against.
 *
 * THE VOCABULARY IS THE GATE, so it is written down rather than felt. Three lists, each short
 * on purpose: a generous list would pass any page with words on it. And the interlock that
 * makes A46 and A48 one gate rather than two: a product noun that is OUR word (pack, dossier)
 * only counts as an answer to "what is this" if the same screen defines it. A stranger cannot
 * be told what a thing is in a word they have never met.
 */
/* Playwright is not a dependency of this prototype; it is borrowed from the storefront's own
 * node_modules. The path is absolute because that is where it lives on this machine, and it
 * is overridable because that will not be true on the next one:
 *   PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node <tool>.mjs
 */
const { chromium } = await import(process.env.PLAYWRIGHT_MJS
  || '/private/tmp/claude-501/-Users-chidionyema-Documents-code-prospector/3fa47c70-c6d2-4273-9620-19dc9810b132/scratchpad/wt-redesign/store_platform/src/Store.Web/node_modules/playwright/index.mjs');
import { readFileSync } from 'fs';

const FILE = 'file://' + process.cwd() + '/looks-engine.html';
const LOOK_IDS = new Function(readFileSync('parts/03-looks.js', 'utf8') + '\n;return LOOKS;')().map((l) => l.id);
const VPS = [{ n: 'narrow-320', w: 320, h: 568 }, { n: 'phone-390', w: 390, h: 844 },
             { n: 'tablet-834', w: 834, h: 1194 }, { n: 'laptop-1440', w: 1440, h: 900 }];

/* Q1 "what is this" — the thing a visitor would leave with. */
const PRODUCT = ['report', 'write-up', 'writeup', 'brief', 'dossier', 'pack', 'catalogue'];
/* Q2 "is it for me" — a named buyer, or a direct address to one. */
const BUYER = ['founder', 'operator', 'investor', 'buyer', 'builder', 'entrepreneur'];
const ADDRESS = ['you ', 'your ', "you're", 'you’re'];
/* Q1/Q2 "and then what" — what the visitor gets to DO, in their words not ours. */
const OUTCOME = ['read', 'buy', 'download', 'browse', 'see', 'get', 'skip', 'avoid', 'decide'];
/* OUR words. Each may appear above the fold only if the same screen defines it. */
const JARGON = ['kill log', 'pack', 'moat', 'rung', 'dossier', 'gate', 'signal'];

/* A gloss is the term standing next to a definition, in the same sentence: "a pack IS a…",
 * "packs — the…", "pack (a…". A heading that merely USES the word ("What is in a pack") is
 * not a definition, and the shape of this check is what keeps those apart. */
const defines = (text, term) => {
  const t = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`\\b${t}s?\\b[^.!?]{0,40}?\\s(?:is|are|means?)\\s[^.!?]{12,}`, 'i').test(text)
      || new RegExp(`\\b${t}s?\\b\\s*[—:(\\-]\\s*[^.!?]{12,}`, 'i').test(text);
};

const browser = await chromium.launch();
const rows = [];
for (const vp of VPS) {
  const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 1, colorScheme: 'light' });
  const page = await ctx.newPage();
  await page.goto(FILE, { waitUntil: 'networkidle' });
  /* The look switcher is removed from the LAYOUT for the same reason its words are removed from
     the reading: it is this prototype's scaffolding and it is not on the storefront. At 320px it
     was 166px tall — a third of the first screen — so leaving it in would have graded the
     storefront on the height of our own tooling. Hiding it is the honest measurement; the two
     exclusions are now one rule rather than two. */
  await page.addStyleTag({ content: '.console { display: none !important; }' });
  for (const id of LOOK_IDS) {
    await page.evaluate((i) => { document.querySelector(`.chip[data-id="${i}"]`).click(); window.scrollTo(0, 0); }, id);
    await page.waitForTimeout(80);
    const m = await page.evaluate(() => {
      const H = window.innerHeight;
      const seen = [];
      const links = [];
      for (const el of document.querySelectorAll('body *')) {
        if (el.closest('.console')) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
        const r = el.getBoundingClientRect();
        if (r.height === 0 || r.top >= H || r.bottom <= 0) continue;
        if (el.tagName === 'A') links.push({ href: el.getAttribute('href') || '', text: (el.textContent || '').trim() });
        if (!el.children.length && el.textContent.trim()) seen.push(el.textContent.trim());
        const al = el.getAttribute('aria-label');
        if (al) seen.push(al);
      }
      const h1 = document.querySelector('.hero__head');
      const hr = h1 ? h1.getBoundingClientRect() : null;
      const acts = document.querySelector('.hero .actions');
      const ar = acts ? acts.getBoundingClientRect() : null;
      return {
        /* BY HOW MUCH, not just pass or fail. A fold failure is a distance, and the distance is
           the whole of the fix: 12px over is a padding change, 300px over is a copy change. */
        fold: H,
        headTop: hr ? Math.round(hr.top) : -1,
        headBottom: hr ? Math.round(hr.bottom) : -1,
        actionsBottom: ar ? Math.round(ar.bottom) : -1,
        leaves: seen,
        links,
        headVisible: !!hr && hr.top >= 0 && hr.bottom <= H,
        /* Every route the SPA can reach in ONE more click from the sections this screen links
           to. A49 is a distance, so it needs the graph, not a feeling about the graph. */
        packLinksOnScreen: [...document.querySelectorAll('a[href*="#/pack/"]')]
          .filter((a) => { const r = a.getBoundingClientRect(); return r.top < H && r.bottom > 0; }).length,
        packLinksAnywhere: document.querySelectorAll('a[href*="#/pack/"]').length,
      };
    });
    /* Presence is measured across the whole screen; a DEFINITION is measured inside ONE element.
       The first cut joined the leaves with ' · ' and tested the definition regex against the
       join, which let a nav strip define its own jargon: "Kill log · What is in a pack" matched
       "<term> ... is ..." across two links that have nothing to do with each other, and "kill
       log" passed as explained. Text from two elements is not a sentence. */
    const low = m.leaves.join(' · ').toLowerCase();
    const product = PRODUCT.filter((w) => low.includes(w));
    const undefinedJargon = JARGON.filter((w) => low.includes(w) && !m.leaves.some((t) => defines(t, w)));
    /* The interlock: our own words do not answer "what is this" unless this screen defines them. */
    const productOK = product.filter((w) => !JARGON.includes(w) || !undefinedJargon.includes(w));
    const buyer = BUYER.filter((w) => low.includes(w));
    const addressed = ADDRESS.some((w) => low.includes(w));
    const outcome = OUTCOME.filter((w) => new RegExp(`\\b${w}\\b`).test(low));
    /* A49: 1 click if a whole sample is linked from this screen; 2 if the screen links to a
       section that lists them; more than that is a fail whatever the page says about itself. */
    const clicks = m.packLinksOnScreen ? 1 : (m.packLinksAnywhere ? 2 : 99);
    rows.push({ look: id, vp: vp.n, productOK, buyer, addressed, outcome, undefinedJargon,
                headVisible: m.headVisible, clicks, chars: low.length,
                fold: m.fold, headTop: m.headTop, headBottom: m.headBottom, actionsBottom: m.actionsBottom,
                outcome_hit: outcome.join('/') });
  }
  await ctx.close();
}
await browser.close();

const fail = {
  a46_product: rows.filter((r) => !r.productOK.length),
  a46_buyer: rows.filter((r) => !r.buyer.length && !r.addressed),
  a46_outcome: rows.filter((r) => !r.outcome.length),
  a46_head: rows.filter((r) => !r.headVisible),
  /* A screen a stranger cannot ACT on is a screen that failed, whatever it says. The first cut
     of A46 graded the headline only, which passed a page whose two buttons were 191px below the
     fold at 320px — the same defect this whole gate exists to catch, in the gate itself. */
  a46_act: rows.filter((r) => r.actionsBottom < 0 || r.actionsBottom > r.fold),
  a48: rows.filter((r) => r.undefinedJargon.length),
  a49: rows.filter((r) => r.clicks > 2),
};
console.log(`${rows.length} first screens graded (${LOOK_IDS.length} looks x ${VPS.length} widths, 320px included)`);
const line = (k, what, sel) => {
  const bad = fail[k];
  if (!bad.length) { console.log(`  ${what}: PASS`); return 0; }
  /* Which WIDTHS, not which four rows. A failure that is 10/10 at 320px and 0/10 at 1440px is a
     layout problem; the same count spread evenly across widths is a copy problem. Printing four
     example rows hid that distinction, and the two have completely different fixes. */
  const tally = VPS.map((v) => `${v.n} ${bad.filter((r) => r.vp === v.n).length}/${LOOK_IDS.length}`).join(', ');
  const ex = [...new Set(bad.map(sel))].slice(0, 2).join('; ');
  console.log(`  ${what}: FAIL on ${bad.length}/${rows.length} — ${tally}${ex.includes(':') ? ' — ' + ex : ''}`);
  return bad.length;
};
let n = 0;
console.log('\nA46 — the cold-open test');
n += line('a46_product', 'a product noun a stranger knows', (r) => `${r.look}@${r.vp}`);
n += line('a46_buyer', 'a buyer noun or a direct address', (r) => `${r.look}@${r.vp}`);
n += line('a46_outcome', 'an outcome verb', (r) => `${r.look}@${r.vp}`);
n += line('a46_head', 'the headline fits above the fold', (r) => `${r.look}@${r.vp}`);
n += line('a46_act', 'the first thing to do is on the first screen', (r) => `${r.look}@${r.vp}`);
console.log('\nA48 — no unexplained jargon above the fold');
n += line('a48', 'our words are defined where they are used', (r) => `${r.look}@${r.vp}: ${r.undefinedJargon.join(', ')}`);
console.log('\nA49 — the entry costs nothing');
n += line('a49', 'a whole sample within 2 clicks', (r) => `${r.look}@${r.vp}: ${r.clicks} clicks`);
console.log(`\noutcome verbs found above the fold at 320px: ${[...new Set(rows.filter((r) => r.vp === 'narrow-320').map((r) => r.outcome_hit))].join(' | ')}`);
console.log('\nthe fold, in pixels — worst look at each width (negative = room to spare)');
for (const v of VPS) {
  const at = rows.filter((r) => r.vp === v.n);
  const over = (k) => Math.max(...at.map((r) => r[k] - r.fold));
  const w = (k) => at.find((r) => r[k] - r.fold === over(k)).look;
  /* headline TOP separates the two fixes that a single "ends +150px" cannot: everything above
     the headline is chrome, everything below its top is the headline itself. */
  const worstTop = Math.max(...at.map((r) => r.headTop));
  console.log(`  ${v.n} (fold ${v.h}px): chrome above the headline ${worstTop}px; headline ends ${over('headBottom') > 0 ? '+' : ''}${over('headBottom')}px (${w('headBottom')}), buttons end ${over('actionsBottom') > 0 ? '+' : ''}${over('actionsBottom')}px (${w('actionsBottom')})`);
}
console.log(`\nclicks to a whole sample: ${[...new Set(rows.map((r) => r.clicks))].sort().join(', ')} (target 1, ceiling 2)`);
console.log(n ? `\n${n} failing first screens across A46, A48 and A49.` : '\nALL PASS — the first screen answers Q1 and Q2 in words a stranger knows, at every width.');
process.exitCode = n ? 1 : 0;
