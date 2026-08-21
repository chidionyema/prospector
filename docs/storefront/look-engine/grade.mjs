// @ledger read-only | node grade.mjs [N] | Rolls N looks, floor-gates each, ranks the survivors on seven axes, writes grades.json.
/* GRADING THE ROLL — founder, 2026-08-21: "we need final 1000, grade and pick the best one,
 * build and ship".
 *
 * The floor and the rank are SEPARATE, and that separation is the whole design. Gate A44
 * already proves the generator cannot emit a failing pair, so every rolled look passes the
 * contrast table -- which means the table can never rank them. A measure everything passes
 * sorts nothing. The floor is re-measured here anyway (a floor asserted is a floor drifting),
 * but the ORDER comes from seven axes that actually vary across the roll.
 *
 * Every axis cites the criterion it serves. An axis with no criterion is taste with a number
 * on it, and C22 requires measurable AND subjectively obvious -- so each one is also written
 * so a person can look at the winner and see why it won.
 */
import { readFileSync, writeFileSync } from 'node:fs';

const src = (f) => readFileSync(f, 'utf8');
const PALETTE = new Function(
  src('parts/08-palette.js').replace(/\nif \(typeof module[\s\S]*$/, '') + '\n;return PALETTE;')();
const { PAIRS, build, contrast, hexToOklch } = PALETTE;

/* rollLook reads PLATES and TREATMENTS as free variables, exactly as it does in the browser
   where all the parts share one <script>. Loading them the same way is what keeps this tool
   grading the page's own generator instead of a copy of it. */
const rollLook = new Function('PALETTE',
  src('parts/04-plates.js') + '\n' + src('parts/07-treatments.js') + '\n' +
  src('parts/09-roll.js') + '\n;return rollLook;')(PALETTE);

const clamp = (n, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));
const hueGap = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };
const inBand = (h, lo, hi) => (lo <= hi ? h >= lo && h <= hi : h >= lo || h <= hi);

/* ---- THE FLOOR. Pass/fail, and a failure disqualifies. ---- */
function floor(look) {
  const built = build(look.seed, PAIRS);
  let worst = Infinity, fails = [];
  for (const theme of ['light', 'dark']) {
    for (const p of PAIRS) {
      const r = contrast(built[theme][p.fg], built[theme][p.bg]);
      const margin = r / p.min;
      if (margin < worst) worst = margin;
      if (r + 1e-9 < p.min) fails.push(`${theme}:${p.fg}/${p.bg} ${r.toFixed(2)}<${p.min}`);
    }
  }
  return { built, worst, fails };
}

/* ---- THE SEVEN AXES. Each returns 0..1 and a one-line reason. ---- */

/* A1 VISIBLE LAYERS (C8 "our foundations, designwise are weak and haky we constantly have
   layout issues junk design", C17 "the user must never notice anything off").
   This axis REPLACED contrast headroom, and the reason is worth keeping. Headroom cannot rank
   anything here: the fitter fits every token TO the table, so the tightest pair sits at 1.00x
   by construction -- measured across the first 40 rolls, 38 of them were under 1.05x. A number
   everything scores the same on sorts nothing, and 18 points of the total were dead.
   What DOES vary, and what "junk design" actually looks like on a screen, is depth. Two things:
   the page needs three distinguishable levels of ink, or emphasis collapses and everything
   shouts equally; and the edge of a card has to be perceivable -- by a lift off the ground OR
   by a hairline you can see. Either alone is a design choice. Neither is a flat grey page.
   Graded in the WORSE of the two themes, because both themes get the same care. */
const axLayers = (l, f) => {
  const score = (t) => {
    const L = (k) => hexToOklch(t[k])[0];
    const d1 = Math.abs(L('ink2') - L('ink')), d2 = Math.abs(L('ink3') - L('ink2'));
    const ladder = clamp(Math.min(d1, d2) / 0.07);
    const lift = Math.abs(L('surface') - L('ground'));
    const hair = contrast(t.hair, t.ground);
    const edge = clamp(Math.max(lift / 0.025, (hair - 1) / 0.22));
    return { v: ladder * 0.5 + edge * 0.5, ladder, edge, lift, hair };
  };
  const a = score(f.built.light), b = score(f.built.dark);
  const w = a.v <= b.v ? a : b, which = a.v <= b.v ? 'light' : 'dark';
  return [w.v, `${which} is the weaker theme: ink ladder ${w.ladder.toFixed(2)}, ` +
    `card edge ${w.edge.toFixed(2)} (lift ${w.lift.toFixed(3)}L, hairline ${w.hair.toFixed(2)}:1)`];
};

/* A2 NOT A DEFAULT (C5 "free reign over branding", C6 "the current site is a ness"). Three
   palettes recur in machine-made design so often they read as unchosen: warm cream with a
   terracotta accent, near-black with one acid pop, and the purple-to-blue. A look that lands
   in one of them is a look the founder has seen a hundred times. */
const axDistinct = (l) => {
  const s = l.seed;
  const gH = s.hue, aH = s.accentHue, gL = s.groundL, gC = s.chroma, aC = s.accentChroma;
  let pen = 0, why = [];
  if (gL > 0.92 && gL < 0.975 && inBand(gH, 35, 75) && gC > 0.006 &&
      (inBand(aH, 15, 50) || inBand(aH, 340, 15))) { pen += 0.55; why.push('cream+terracotta'); }
  if (s.darkL < 0.13 && aC > 0.20 && (inBand(aH, 100, 155) || inBand(aH, 15, 45))) {
    pen += 0.40; why.push('near-black+acid pop'); }
  if (inBand(aH, 255, 295) && aC > 0.14) { pen += 0.35; why.push('the purple-blue'); }
  if (gC < 0.0015) { pen += 0.15; why.push('pure grey ground'); }
  return [clamp(1 - pen), why.length ? `sits in ${why.join(', ')}` : 'no clustered default'];
};

/* A3 TYPE PAIRING (C16 "piel ultra ultra", and the pairing rule in 09-roll.js). The roll
   already refuses one face doing both jobs. This grades how well the two it picked work
   together, and it does NOT punish two serifs -- Bodoni over Source Serif is the best pairing
   the ten ship. What it punishes is a pairing that reads as unfinished. */
const axType = (l) => {
  const fam = (n) => n.match(/'([^']+)'/)?.[1] || n.split(',')[0].trim();
  /* Classify the FIRST family only, never the whole stack: every sans stack ends in
     `sans-serif`, which contains "serif", so a naive test called all nine display faces
     serifs and this axis scored 0.85 for every look in the roll. */
  const cls = (n) => {
    const first = fam(n);
    if (/Mono|Courier|Menlo/.test(first)) return 'mono';
    if (/Archivo|Chivo|Bricolage|Public Sans|Cabin|Helvetica|Arial|Grotesque/.test(first)) return 'sans';
    return 'serif';
  };
  const d = l.type.display, b = l.type.body, m = l.type.mono;
  const dc = cls(d), bc = cls(b);
  let v = dc !== bc ? 1.0 : 0.85, why = [`${fam(d)} over ${fam(b)}`];
  if (dc === 'mono') { v -= 0.25; why.push('mono as the display face'); }
  if (fam(m) === fam(d)) { v -= 0.20; why.push('mono repeats the display face'); }
  if (l.type.italic === 'italic' && dc === 'sans') { v -= 0.15; why.push('italic grotesque'); }
  if (l.type.labelTrack === '0.02em' && l.type.labelCase === 'uppercase') {
    v -= 0.10; why.push('uppercase labels with no tracking'); }
  return [clamp(v), why.join('; ')];
};

/* A4 STRUCTURAL COHERENCE (C8 "our foundations are weak and haky", C17 "page to page the
   layout must be seanless"). The switches are rolled independently, so nothing stops the roll
   pairing a soft radius with a heavy rule, or a drop cap under an all-caps headline. Those are
   not taste calls -- they are two decisions that contradict each other on the same screen. */
const axCoherent = (l) => {
  const w = l.switches, f = l.form;
  let v = 0.7, why = [];
  const bad = (c, n, m) => { if (c) { v -= n; why.push(m); } };
  const good = (c, n, m) => { if (c) { v += n; why.push(m); } };
  bad(w.panel === 'flat' && f.shadow !== 'none', 0.25, 'flat panels casting a shadow');
  bad(w.dropcap === 'on' && w.headlineCase === 'upper', 0.25, 'drop cap under an all-caps headline');
  bad(parseInt(f.radius) >= 6 && f.ruleWStrong === '3px', 0.15, 'soft corners with a 3px rule');
  bad(w.masthead === 'centred' && w.nav === 'filed', 0.10, 'centred masthead over a filed nav');
  good(w.masthead === 'centred' && w.mastheadRule === 'double', 0.15, 'centred masthead, double rule');
  good(w.headlineCase === 'upper' && w.sectionHead === 'ruled', 0.15, 'all-caps headings on ruled sections');
  good(w.readout === 'boxed' && w.nav === 'filed', 0.15, 'boxed readout with a filed nav');
  good(w.dropcap === 'on' && w.plateEdge === 'underline', 0.10, 'drop cap with underlined plates');
  good(parseInt(f.radius) === 0 && f.ruleW === '1px', 0.10, 'square corners, hairline rules');
  return [clamp(v), why.length ? why.join('; ') : 'no interaction either way'];
};

/* A5 RESTRAINT (artifact craft: spend the boldness in one place; C7 "do not produce another
   round that has to be redone"). Zero switches is the default skin wearing a new palette --
   the "ten skins, not ten looks" failure C35 was written to kill. Every switch on is a page
   shouting in eight directions. Four is the peak, and the curve is symmetric. */
const axRestraint = (l) => {
  const n = Object.keys(l.switches).length;
  /* PENALISE EXCESS ONLY. This read `1 - |n-4|/6` until 2026-08-21, which punished a look for
     being SPARE exactly as hard as for being busy -- so nine of the ten designed looks scored
     0.50 on an axis named restraint, and the only way to score well was to add switches. That
     is the opposite of what the word means. Restraint is a ceiling, not a target: few, chosen
     switches cost nothing, and the score falls only once a look is asking for everything. */
  return [clamp(1 - Math.max(0, n - 5) / 5), `${n} structural switch${n === 1 ? '' : 'es'}`];
};

/* A6 CHROMA DISCIPLINE (C21 "engage user before we can sell"; a page whose accent cannot be
   found is a page with no call to action). Two things: the ground should be a CHOSEN neutral,
   carrying a trace of hue rather than none at all, and the accent must be loud enough to be
   the loud thing. An accent at 0.05 chroma on a 0.02 ground is not an accent, it is a smudge. */
const axChroma = (l) => {
  const s = l.seed;
  const gC = s.chroma, aC = s.accentChroma;
  let v = 0, why = [];
  if (gC >= 0.003 && gC <= 0.018) { v += 0.5; why.push('ground is a tinted neutral'); }
  else if (gC < 0.003) { v += 0.22; why.push('ground is untinted'); }
  else { v += 0.30; why.push('ground is a coloured page'); }
  if (aC >= 0.13) { v += 0.5; why.push('accent carries'); }
  else if (aC >= 0.09) { v += 0.36; why.push('accent is quiet'); }
  else { v += 0.12; why.push('accent barely reads'); }
  return [clamp(v), why.join(', ')];
};

/* A7 THEME PARITY (C15 "all screens all devices"; the artifact rule that both themes get the
   same care). The seed states the dark theme separately, so a look can have an identity by day
   and a different one by night. Grade whether the accent survives the switch: same hue, similar
   lightness, comparable chroma. */
const axParity = (l, f) => {
  const [lL, lC, lH] = hexToOklch(f.built.light.accent);
  const [dL, dC, dH] = hexToOklch(f.built.dark.accent);
  const dHue = hueGap(lH, dH), dLit = Math.abs(lL - dL);
  const dChr = Math.min(lC, dC) / Math.max(lC, dC, 1e-6);
  const v = clamp(1 - dHue / 40) * 0.4 + clamp(1 - dLit / 0.35) * 0.35 + clamp(dChr) * 0.25;
  return [v, `accent moves ${dHue.toFixed(0)}deg and ${dLit.toFixed(2)}L between themes`];
};

const AXES = [
  ['layers', 18, axLayers], ['distinct', 16, axDistinct], ['type', 16, axType],
  ['coherent', 16, axCoherent], ['restraint', 12, axRestraint], ['chroma', 12, axChroma],
  ['parity', 10, axParity],
];

const N = Number(process.argv[2] || 1000);
const rows = [], rejected = [];
for (let n = 1; n <= N; n++) {
  const look = rollLook(n);
  const f = floor(look);
  if (f.fails.length) { rejected.push({ n, fails: f.fails.slice(0, 3) }); continue; }
  const parts = {}, reasons = {};
  let total = 0;
  for (const [name, w, fn] of AXES) {
    const [v, why] = fn(look, f);
    parts[name] = Math.round(v * 1000) / 1000; reasons[name] = why; total += v * w;
  }
  rows.push({
    n, id: look.id, score: Math.round(total * 10) / 10, parts, reasons,
    worst: Math.round(f.worst * 1000) / 1000,
    display: look.type.display.match(/'([^']+)'/)?.[1],
    body: look.type.body.match(/'([^']+)'/)?.[1],
    mono: look.type.mono.match(/'([^']+)'/)?.[1],
    plate: look.plate, treatment: look.treatment,
    switches: look.switches, radius: look.form.radius,
    accent: f.built.light.accent, ground: f.built.light.ground,
    accentDark: f.built.dark.accent, groundDark: f.built.dark.ground,
  });
}
rows.sort((a, b) => b.score - a.score);
writeFileSync('grades.json', JSON.stringify({ n: N, graded: rows.length, rejected, rows }, null, 1));

const q = (p) => rows[Math.floor((rows.length - 1) * p)].score;
console.log(`rolled ${N}, floor-passed ${rows.length}, floor-failed ${rejected.length}`);
console.log(`score  min ${rows[rows.length - 1].score}  p25 ${q(0.75)}  median ${q(0.5)}  p75 ${q(0.25)}  max ${rows[0].score}`);
console.log('\nrank  seed   score  layr dist type cohr rstr chrm prty  display / body');
for (const r of rows.slice(0, 20)) {
  const p = r.parts;
  console.log(`${String(rows.indexOf(r) + 1).padStart(4)}  ${String(r.n).padStart(4)}   ${String(r.score).padStart(5)}  ` +
    [p.layers, p.distinct, p.type, p.coherent, p.restraint, p.chroma, p.parity]
      .map((x) => x.toFixed(2)).join(' ') + `  ${r.display} / ${r.body}`);
}
