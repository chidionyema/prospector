// @ledger read-only | node check.mjs | The contrast gate outside the browser. Takes the pair table from the palette module.
/* The contrast gate, run outside the browser so it can fail a build.
 *
 * The pair table is IMPORTED, never copied. It was copied until 2026-08-20, and the copy is
 * exactly how the gate came to report "12/12 pass" for a set of pairs the engine had already
 * outgrown: two lists, one edited, both believed. A gate with its own private copy of the thing
 * it is grading is not a gate, it is a second opinion that never changes its mind.
 *
 * It used to parse the table out of `parts/05-engine.js` with a string slice, which is the same
 * defect one layer down: the engine stopped holding a literal table the moment the palette module
 * became the single source, and the gate then died on `PAIRS is not iterable` rather than grading
 * anything. Import the contract; never scrape it.
 *
 * A look may carry a SEED or hand-picked `light`/`dark` blocks. Both are graded here, through the
 * same resolver the engine uses, so the ten looks can be converted to seeds one at a time without
 * the gate going blind to whichever half has not moved yet. */
import { readFileSync, existsSync } from 'node:fs';
import { PALETTE, LOOKS } from './seedlib.mjs';

const PAIRS = PALETTE.PAIRS;
const cr = PALETTE.contrast;

const built = new Map();
function palette(look, theme) {
  if (!look.seed) return look[theme];
  if (!built.has(look.id)) built.set(look.id, PALETTE.build(look.seed));
  return built.get(look.id)[theme];
}

let fails = 0, seeded = 0;
for (const l of LOOKS) {
  if (l.seed) seeded++;
  for (const th of ['light', 'dark']) {
    const t = palette(l, th);
    for (const { fg, bg, min, what } of PAIRS) {
      const g = cr(t[fg], t[bg]);
      if (g < min) {
        fails++;
        console.log(`FAIL ${l.id.padEnd(11)} ${th.padEnd(5)} ${(fg + '/' + bg).padEnd(22)} ` +
          `${g.toFixed(2)} < ${min}  (${t[fg]} on ${t[bg]})  ${what}`);
      }
    }
  }
}
console.log(fails
  ? `\n${fails} failures across ${LOOKS.length * 2} look/theme combinations, ${PAIRS.length} pairs each`
  : `\nALL PASS — ${LOOKS.length} looks x 2 themes x ${PAIRS.length} pairs = ${LOOKS.length * 2 * PAIRS.length} checks`);
console.log(`${seeded} of ${LOOKS.length} looks are generated from a seed; ${LOOKS.length - seeded} still carry hand-picked hex.`);

/* GATE A43 — no look may carry a hand-written colour. Measured on the SOURCE, not on the
   objects, because the objects are what a generator produced and the file is what a person
   edits. The last one to go was `dot:'#7A1F1B'`, the swatch in the look picker: a colour the
   seed already decides, stated a second time, free to drift, and wrong in the other theme.
   A grep is the whole gate — which is the point of A43 being written as a grep. */
const src = readFileSync('parts/03-looks.js', 'utf8');
const hex = src.match(/#[0-9A-Fa-f]{6}\b/g) || [];
const seedless = LOOKS.filter((l) => !l.seed).map((l) => l.id);
if (hex.length) console.log(`\nA43 FAIL — ${hex.length} hand-written colours in parts/03-looks.js: ${[...new Set(hex)].join(' ')}`);
if (seedless.length) console.log(`\nA43 FAIL — looks with no seed: ${seedless.join(', ')}`);
if (!hex.length && !seedless.length) console.log('A43 PASS — no hand-written colour in the look table, every look owns a seed.');

/* GATE A42 — no CSS rule may name a look, and no look may ask for a switch nobody built.
   Two halves, because each alone is a proxy. A stylesheet with no look name in it can still
   be ten forks if the switches are `data-look-ledger`; and a look can declare
   `switches:{ dropcap:'on' }` against a stylesheet that has no dropcap rule, in which case
   the switch does nothing, silently, forever.

   Comments are STRIPPED before the grep. The rule this file enforces is quoted in the
   stylesheet's own header as the example of what not to write, and a guard that greps source
   grades its comments too — the message explaining the ban would trip the ban. */
const css = readFileSync('parts/06-switches.css', 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const named = css.match(/\[data-look[=~|^$*]?=/g) || [];
if (named.length) console.log(`\nA42 FAIL — ${named.length} CSS rules name a look.`);

const attrOf = (k) => 'data-' + k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

/* The CATALOGUE is the contract, not the ten looks. Grading only what the ten declare lets a
   switch exist in the catalogue with no rule behind it: the roll button hands it to a look,
   the look sets the attribute, nothing happens, and no gate has an opinion. Both directions,
   so the catalogue, the CSS and the looks are one thing or the gate is red. */
const SWITCHES = new Function(readFileSync('parts/09-roll.js', 'utf8') + '\n;return SWITCHES;')();
const declared = [];
for (const [k, ax] of Object.entries(SWITCHES)) for (const v of ax.v) declared.push(`[${attrOf(k)}="${v}"]`);

const missing = declared.filter((sel) => !css.includes(sel));
if (missing.length) console.log(`\nA42 FAIL — ${missing.length} catalogue switches no stylesheet implements: ${missing.join(' ')}`);

const implemented = [...new Set(css.match(/\[data-[a-z-]+="[a-z]+"\]/g) || [])];
const stray = implemented.filter((sel) => !declared.includes(sel));
if (stray.length) console.log(`\nA42 FAIL — ${stray.length} CSS rules key on a switch no catalogue declares: ${stray.join(' ')}`);

/* And every switch the ten looks actually state must be a real catalogue value — a typo in a
   look ("centered") is a look that quietly gets the default and nobody notices. */
const bogus = [];
for (const l of LOOKS) for (const [k, v] of Object.entries(l.switches || {})) {
  if (!SWITCHES[k] || !SWITCHES[k].v.includes(v)) bogus.push(`${l.id}: ${k}="${v}"`);
}
if (bogus.length) console.log(`\nA42 FAIL — ${bogus.length} looks state a switch the catalogue does not define: ${bogus.join(', ')}`);

const a42 = named.length + missing.length + stray.length + bogus.length;
if (!a42) console.log(`A42 PASS — 0 CSS rules name a look; ${declared.length} switch values across ` +
  `${Object.keys(SWITCHES).length} axes, all implemented and all implemented rules declared. ` +
  `The switch space alone is ${Object.values(SWITCHES).reduce((n, ax) => n * (ax.v.length + 1), 1).toLocaleString()} structures.`);


/* THE GATE-NUMBER AUDIT — part of A37, and paid for by a collision on 2026-08-20.
 *
 * The rolled-look gate in verify.mjs was written as "A46". A46 was already taken:
 * docs/STOREFRONT_REDESIGN_PROGRAM.md:466 gives it to the cold-open test, a criterion
 * nobody has started. A green "A46 PASS" in a log would have read as evidence for it.
 * Two gates sharing a number is the same proxy defect as everything else in this thread:
 * the number is a POINTER to a criterion, and nothing was checking that it still pointed
 * at the one the tool means.
 *
 * The check is an exact string compare on purpose. CLAIMED is a COPY of the doc's own
 * title for each number, so a tool cannot claim a number without someone reading the line
 * the doc already has there, and the doc cannot renumber underneath us silently.
 */
/* The program doc is the authority on what each gate number means, so this tool reads it.
 * Two locations, in order: the copy two directories up, which is where it sits when these
 * tools live in the repo at docs/storefront/look-engine/, then the worktree they were
 * written in. PROGRAM_DOC overrides both. */
const DOC = [process.env.PROGRAM_DOC,
  new URL('../../STOREFRONT_REDESIGN_PROGRAM.md', import.meta.url).pathname,
  '/private/tmp/claude-501/-Users-chidionyema-Documents-code-prospector/3fa47c70-c6d2-4273-9620-19dc9810b132/scratchpad/wt-redesign/docs/STOREFRONT_REDESIGN_PROGRAM.md',
].filter(Boolean).find((f) => existsSync(f));
const CLAIMED = {
  42: 'no CSS rule may name a look',
  43: 'no look may carry a hand-written colour',
  44: 'a randomly generated seed passes the contrast table',
  45: 'the console can add a look without a deploy',
  46: 'the cold-open test',
  48: 'no unexplained jargon above the fold',
  49: 'the entry costs nothing',
  54: 'a look nobody designed survives the whole browser gate',
};
const TOOLS = ['check.mjs', 'verify.mjs', 'palette-test.mjs', 'seed.mjs', 'overflow.mjs', 'persist.mjs', 'coldopen.mjs'];
let gateFails = 0;
let docText = '';
try { docText = readFileSync(DOC, 'utf8'); }
catch { console.log(`\nGATE AUDIT FAIL — cannot read ${DOC}. The numbers are unverifiable, which is a failure, not a skip.`); gateFails++; }
if (docText) {
  const defined = {};
  for (const m of docText.matchAll(/\*\*(?:Gate )?A(\d+) — ([^.*]+)/g)) defined[+m[1]] = m[2].trim();
  const used = new Set();
  for (const f of TOOLS) {
    for (const m of readFileSync(f, 'utf8').matchAll(/GATE A(\d+)/g)) {
      used.add(+m[1]);
      if (!(m[1] in CLAIMED)) {
        console.log(`\nGATE AUDIT FAIL — ${f} claims A${m[1]}, which this audit does not know. Add it to CLAIMED with the doc's own title.`);
        gateFails++;
      }
    }
  }
  for (const [n, title] of Object.entries(CLAIMED)) {
    if (!(n in defined)) {
      console.log(`\nGATE AUDIT FAIL — A${n} is claimed by a tool but the program doc defines no such gate.`);
      gateFails++;
    } else if (defined[n] !== title) {
      console.log(`\nGATE AUDIT FAIL — A${n} is "${defined[n]}" in the doc, but a tool here uses it for "${title}".`);
      gateFails++;
    }
  }
  if (!gateFails) console.log(`GATE AUDIT PASS — ${used.size} gate numbers used by the tools, all defined in the program doc with the title the tool means.`);
}

process.exit(fails || hex.length || seedless.length || a42 || gateFails ? 1 : 0);
