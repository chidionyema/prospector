// @ledger read-only | node seed.mjs | Reads the ten hand-picked palettes back into seeds, rebuilds them, and reports what changes.
/* SEEDS FROM THE HAND-PICKED PALETTES — criterion C35, the step before gates A42/A43.
 *
 * A look is supposed to own a SEED (about a dozen perceptual decisions), not 32 hex
 * values. The ten looks we ship own hex values. This tool is the bridge, and it is
 * READ-ONLY on purpose: it prints the seed it recovers and the distance between the
 * palette that seed regenerates and the one on disk today.
 *
 * The inversion is exact where the derivation is one operation — `hue` is the OKLCH
 * hue of `light.ground`, `hairStep` is the lightness step from ground to hair — and it
 * is a MEASUREMENT everywhere else, because `derive` runs `fitAgainst` for the accent
 * and the two semantic colours. Those three are solved against the ground for a
 * contrast ratio, so their lightness is not the operator's to keep. A look whose
 * hand-picked accent already passes will barely move; one that does not will move
 * exactly as far as it must, and the size of that move is the point of this report.
 *
 * Read the ORIG column before the DELTA column. Any pair marked FAIL there is a
 * contrast failure that shipped, and the whole argument for generating palettes is
 * that a person cannot see those and a machine cannot miss them.
 */
import { readFileSync } from 'node:fs';
import { PALETTE, LOOKS, seedOf } from './seedlib.mjs';

/* The reference is `handpicked.json` now. Until 2026-08-20 the looks carried both the seed
   and the hex it was recovered from, and this report compared one against the other in the
   same file. Converting the looks removed the hex, which would have left the report grading
   a palette against itself and printing ALL PASS forever — a gate whose two sides are the
   same object is the proxy defect this whole thread exists to kill. */
const REF = JSON.parse(readFileSync('handpicked.json', 'utf8'));

/* The pair table comes from the palette module itself, so this report is measured
   against the same contract the fitter satisfies and the page renders. */
const PAIRS = PALETTE.PAIRS;
const { contrast, hexToOklch } = PALETTE;

/* Distance in the space the palette is designed in, not in hex. Two colours four
   lightness steps apart read as the same decision; two colours 40 hue degrees apart do
   not, however close their hex strings look. */
function dist(a, b) {
  const [La, Ca, Ha] = hexToOklch(a), [Lb, Cb, Hb] = hexToOklch(b);
  const dh = Math.min(Math.abs(Ha - Hb), 360 - Math.abs(Ha - Hb));
  const hueCounts = Math.min(Ca, Cb) > 0.02;      // hue of a near-grey is noise
  return { dL: Lb - La, dC: Cb - Ca, dH: hueCounts ? dh : 0 };
}

const TOKENS = ['ground', 'surface', 'surface2', 'hair', 'ink', 'ink2', 'ink3',
  'accent', 'accentFill', 'accentInk', 'good', 'bad'];

let origFails = 0, newFails = 0, moved = [];
const seeds = {};

for (const look of LOOKS) {
  const ref = REF[look.id];
  const seed = look.seed || seedOf(look);
  seeds[look.id] = seed;
  const built = PALETTE.build(seed, PAIRS);
  const rows = [];
  for (const theme of ['light', 'dark']) {
    for (const p of PAIRS) {
      if (contrast(ref[theme][p.fg], ref[theme][p.bg]) < p.min) {
        origFails++;
        rows.push(`    ORIG FAIL  ${theme} ${p.fg} on ${p.bg}: ` +
          `${contrast(ref[theme][p.fg], ref[theme][p.bg]).toFixed(2)} < ${p.min}`);
      }
      if (contrast(built[theme][p.fg], built[theme][p.bg]) < p.min) {
        newFails++;
        rows.push(`    NEW FAIL   ${theme} ${p.fg} on ${p.bg}`);
      }
    }
    for (const t of TOKENS) {
      const d = dist(ref[theme][t], built[theme][t]);
      if (Math.abs(d.dL) > 0.06 || d.dH > 12) {
        moved.push({ look: look.id, theme, token: t, from: ref[theme][t], to: built[theme][t], ...d });
      }
    }
  }
  console.log(`${look.id.padEnd(11)} hue ${String(seed.hue).padStart(5)}  chroma ${seed.chroma}  ` +
    `groundL ${seed.groundL}  darkL ${seed.darkL}  accentHue ${String(seed.accentHue).padStart(5)}  ` +
    `accentC ${seed.accentChroma}  fill ${seed.fillFrom}/${seed.fillFromDark}`);
  for (const r of rows) console.log(r);
}

console.log('');
console.log(origFails
  ? `${origFails} contrast pairs FAIL in the hand-picked palettes on disk today.`
  : 'The hand-picked palettes pass every pair — the generator has to match, not rescue.');
console.log(newFails
  ? `FAIL — ${newFails} pairs still fail after generation. The fitter did not close them.`
  : `ALL PASS — 10 looks x 2 themes x ${PAIRS.length} pairs = ${10 * 2 * PAIRS.length} regenerated pairs, 0 failing.`);
console.log(`${moved.length} tokens move by more than 0.06 lightness or 12 hue degrees:`);
for (const m of moved.slice(0, 24)) {
  console.log(`  ${m.look.padEnd(11)} ${m.theme.padEnd(5)} ${m.token.padEnd(10)} ` +
    `${m.from} -> ${m.to}   dL ${m.dL >= 0 ? '+' : ''}${m.dL.toFixed(3)}  dH ${m.dH.toFixed(0)}`);
}
if (moved.length > 24) console.log(`  ... and ${moved.length - 24} more`);

console.log('');
console.log('SEEDS (paste-ready):');
console.log(JSON.stringify(seeds, null, 1).replace(/"(\w+)":/g, '$1:'));

process.exitCode = newFails ? 1 : 0;
