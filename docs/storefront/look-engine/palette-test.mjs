// @ledger read-only | node palette-test.mjs | Gate A44. 2000 random seeds through the palette generator, to prove it cannot emit a failing pair.
/* GATE A44 — the palette generator must be INCAPABLE of emitting a failing
   pair, not merely checked afterwards. Random seeds rather than the ten we
   ship, because the ten are the cases we already looked at. */
import { readFileSync } from 'node:fs';
const src = readFileSync('parts/08-palette.js', 'utf8').replace(/\nif \(typeof module[\s\S]*$/, '');
const PALETTE = new Function(src + '\n;return PALETTE;')();

/* The pair table is the palette module's own (`PALETTE.PAIRS`). It used to be copied
   here, which meant this gate could pass against a table the page did not use. */
const PAIRS = PALETTE.PAIRS;

/* Seeded, so a failure is reproducible from its index alone. */
let s = 1;
const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
const pick = (lo, hi) => lo + rnd() * (hi - lo);

let fails = 0, worst = { r: Infinity };
const N = 2000;
for (let i = 0; i < N; i++) {
  /* The generator is PALETTE.randomSeed, the same one the page's roll button calls. It was
     written here and moved into the palette module on 2026-08-20: while it lived in the test,
     this gate could pass on a distribution the page never produced, and the page could produce
     one the gate never saw. A gate and the thing it grades must not own separate generators. */
  const seed = PALETTE.randomSeed(rnd);
  const built = PALETTE.build(seed, PAIRS);
  for (const theme of ['light', 'dark']) {
    const t = built[theme];
    for (const p of PAIRS) {
      const r = PALETTE.contrast(t[p.fg], t[p.bg]);
      if (r < worst.r / 1) { /* track the tightest margin, not the lowest ratio */ }
      const margin = r / p.min;
      if (margin < worst.r) worst = { r: margin, i, theme, pair: `${p.fg} on ${p.bg}`, got: r.toFixed(3), min: p.min };
      if (r + 1e-9 < p.min) {
        fails++;
        if (fails <= 5) console.log(`FAIL seed#${i} ${theme} ${p.fg} on ${p.bg}: ${r.toFixed(3)} < ${p.min}  (${t[p.fg]} / ${t[p.bg]})`);
        /* Print the seed itself on the first failure. The header of this file claims a
           failure is reproducible from its index alone, and that was only true while
           the generator's field list never changed — an index is a pointer into a
           sequence, and the sequence moves the moment a field is added. The seed is
           the reproduction. */
        if (fails === 1) console.log(`  seed#${i} = ${JSON.stringify(seed)}`);
      }
    }
  }
}
console.log(`${N} seeds x 2 themes x ${PAIRS.length} pairs = ${N * 2 * PAIRS.length} assertions`);
console.log(fails ? `${fails} FAILING PAIRS` : 'ALL PASS — the generator cannot emit a failing pair');
console.log(`tightest margin: ${worst.r.toFixed(3)}x required (${worst.pair}, ${worst.theme}, got ${worst.got} vs ${worst.min})`);
process.exit(fails ? 1 : 0);
