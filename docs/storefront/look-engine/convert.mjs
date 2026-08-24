// @ledger writes | node convert.mjs [--write] | Rewrites the ten looks from 32 hex values each to one seed. Reports by default.
/* THE CONVERSION — criterion C35, gates A42/A43.
 *
 * A look is supposed to own a SEED: about thirty perceptual decisions in OKLCH, from which
 * sixteen tokens per theme are derived and then FITTED against the contrast pair table. The ten
 * looks own 32 hex values each, hand-picked, and a hand-picked palette cannot be re-fitted: change
 * one background and every foreground on it has to be re-eyed by a person who cannot measure.
 *
 * This tool runs in two modes because a rewrite of shipped data has no undo. `node convert.mjs`
 * reports and writes nothing. `--write` applies, and only after the SAME check the report ran.
 *
 * It refuses to write unless all three hold:
 *   1. every pair in PALETTE.PAIRS passes on the regenerated palettes,
 *   2. no token moves more than 0.06 lightness or 12 hue degrees from the palette on disk,
 *   3. the rewritten file still parses and still yields ten looks with their other fields intact.
 *
 * The hand-picked palettes are not deleted, they are moved to `handpicked.json`. That file is the
 * regression reference: without it, the drift measurement above can never be run again, and a
 * conversion that cannot be re-checked is a claim rather than a proof.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { PALETTE, LOOKS, seedOf } from './seedlib.mjs';

const WRITE = process.argv.includes('--write');
const PAIRS = PALETTE.PAIRS;
const { contrast, hexToOklch } = PALETTE;
const TOKENS = ['ground', 'surface', 'surface2', 'hair', 'hairStrong', 'ink', 'ink2', 'ink3',
  'accent', 'accentFill', 'accentInk', 'good', 'bad', 'plateBg', 'plateInk', 'plateAccent'];

/* Find the region of the source text holding one look's two palette blocks, by counting braces
   rather than matching a shape. A regex over 32 hex values in six lines is a second parser for a
   language that already has one, and it fails silently the day someone reflows a line. */
function region(src, id) {
  const at = src.indexOf(`id:'${id}'`);
  if (at < 0) throw new Error(`look ${id} not found in parts/03-looks.js`);
  const lightAt = src.indexOf('\n  light:', at);
  const darkAt = src.indexOf('\n  dark:', lightAt);
  if (lightAt < 0 || darkAt < 0) throw new Error(`look ${id} has no light/dark blocks`);
  let i = src.indexOf('{', darkAt), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) break;
  }
  let end = i + 1;
  while (end < src.length && src[end] !== '\n') end++;   // eat the trailing comma
  return [lightAt + 1, end + 1];
}

/* One seed printed the way a person will edit it: grouped by decision, not by field order. */
function render(seed) {
  const groups = [
    ['hue', 'hueDark', 'chroma', 'groundL', 'darkL', 'darkChroma'],
    ['inkShift', 'inkShiftDark', 'inkChroma', 'inkChromaDark'],
    ['inkL', 'inkLDark', 'ink2L', 'ink2LDark', 'ink3L', 'ink3LDark'],
    ['accentHue', 'accentChroma', 'darkAccentChroma', 'accentL', 'accentLDark'],
    ['lift', 'sunk', 'hairStep', 'liftDark', 'sunkDark', 'hairStepDark'],
    ['hairStrongL', 'hairStrongLDark'],
    ['goodHue', 'goodL', 'goodLDark', 'badHue', 'badL', 'badLDark'],
    ['fillFrom', 'fillL', 'fillChroma', 'fillHue',
      'fillFromDark', 'fillLDark', 'fillChromaDark', 'fillHueDark'],
    ['contrast'],
  ];
  const seen = new Set();
  const lines = [];
  for (const g of groups) {
    const parts = [];
    for (const k of g) {
      if (!(k in seed)) continue;
      seen.add(k);
      parts.push(`${k}:${typeof seed[k] === 'string' ? `'${seed[k]}'` : seed[k]}`);
    }
    if (parts.length) lines.push('         ' + parts.join(', ') + ',');
  }
  const missed = Object.keys(seed).filter((k) => !seen.has(k));
  if (missed.length) throw new Error(`render() would drop seed fields: ${missed.join(', ')}`);
  return '  seed:{ ' + lines.join('\n').slice(9) + ' },\n';
}

const src = readFileSync('parts/03-looks.js', 'utf8');
let out = src;
const seeds = {}, handpicked = {};
for (const look of LOOKS) {
  seeds[look.id] = seedOf(look);
  handpicked[look.id] = { light: look.light, dark: look.dark };
}
/* Rewrite back-to-front so every region index stays valid as the text shrinks. */
for (const look of [...LOOKS].reverse()) {
  const [a, b] = region(out, look.id);
  out = out.slice(0, a) + render(seeds[look.id]) + out.slice(b);
}
out = out.replace(
  /   Each supplies the same token contract twice, once per theme, plus the few\n   form values \(radius, rule weight, density\) and the name of its plate\n   renderer\./,
  `   Each owns a SEED — about thirty perceptual decisions in OKLCH — plus the few\n` +
  `   form values (radius, rule weight, density) and the name of its plate renderer.\n` +
  `   PALETTE.build() derives the sixteen tokens per theme and FITS them against the\n` +
  `   contrast pair table, so no look can state a palette that fails its own gate. The\n` +
  `   hand-picked hex these seeds were recovered from is kept in handpicked.json, and\n` +
  `   \`node seed.mjs\` measures the distance between the two.`);

/* ---- the three checks, run in report mode and again before any write ---- */
const LOOKS2 = new Function(out + '\n;return LOOKS;')();
let pairFails = 0, moved = [], structural = [];
if (LOOKS2.length !== LOOKS.length) structural.push(`rewrite yields ${LOOKS2.length} looks, not ${LOOKS.length}`);
for (const l2 of LOOKS2) {
  const l1 = LOOKS.find((l) => l.id === l2.id);
  if (!l1) { structural.push(`unknown look ${l2.id}`); continue; }
  if (!l2.seed) structural.push(`${l2.id} has no seed after rewrite`);
  if (l2.light || l2.dark) structural.push(`${l2.id} still carries hand-picked hex`);
  for (const k of ['name', 'dot', 'tagline', 'plate', 'treatment']) {
    if (l1[k] !== l2[k]) structural.push(`${l2.id}.${k} changed: ${l1[k]} -> ${l2[k]}`);
  }
  for (const k of ['form', 'type']) {
    if (JSON.stringify(l1[k]) !== JSON.stringify(l2[k])) structural.push(`${l2.id}.${k} changed`);
  }
  if (!l2.seed) continue;
  const built = PALETTE.build(l2.seed);
  for (const theme of ['light', 'dark']) {
    for (const p of PAIRS) {
      if (contrast(built[theme][p.fg], built[theme][p.bg]) < p.min) {
        pairFails++;
        console.log(`  PAIR FAIL  ${l2.id} ${theme} ${p.fg} on ${p.bg}`);
      }
    }
    for (const t of TOKENS) {
      const [La, Ca, Ha] = hexToOklch(l1[theme][t]);
      const [Lb, Cb, Hb] = hexToOklch(built[theme][t]);
      const dh = Math.min(Math.abs(Ha - Hb), 360 - Math.abs(Ha - Hb));
      const dH = Math.min(Ca, Cb) > 0.02 ? dh : 0;
      if (Math.abs(Lb - La) > 0.06 || dH > 12) {
        moved.push(`  DRIFT ${l2.id.padEnd(11)} ${theme.padEnd(5)} ${t.padEnd(11)} ` +
          `${l1[theme][t]} -> ${built[theme][t]}  dL ${(Lb - La >= 0 ? '+' : '')}${(Lb - La).toFixed(3)}  dH ${dH.toFixed(0)}`);
      }
    }
  }
}
for (const m of moved) console.log(m);
for (const s of structural) console.log(`  STRUCT ${s}`);

const ok = !pairFails && !moved.length && !structural.length;
console.log('');
console.log(`${LOOKS.length} looks converted: ${src.length} bytes of hex -> ${out.length} bytes of seed ` +
  `(${Math.round((1 - out.length / src.length) * 100)}% smaller)`);
console.log(`${pairFails} pair failures, ${moved.length} tokens drifted past 0.06L/12H, ${structural.length} structural changes.`);

if (!ok) { console.log('\nREFUSED — the rewrite is not equivalent. Nothing written.'); process.exit(1); }
if (!WRITE) { console.log('\nWOULD PASS — re-run with --write to apply.'); process.exit(0); }

writeFileSync('handpicked.json', JSON.stringify(handpicked, null, 1) + '\n');
writeFileSync('parts/03-looks.js', out);
console.log('\nWRITTEN — parts/03-looks.js now carries seeds; handpicked.json keeps the reference palettes.');
