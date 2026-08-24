// @ledger read-only | node grade-designed.mjs | Scores the ten DESIGNED looks on grade.mjs's axes, as the control for the roll.
/* THE CONTROL. grade.mjs ranks a thousand looks nobody has seen. On its own that is one
 * instrument reading, and an instrument can be wrong in a way that is invisible from inside
 * itself. The ten designed looks are the estate's own bar -- they were hand-built, reviewed,
 * and shipped through every gate. So they are the calibration: if the grader is measuring
 * design quality, the ten should land high on it. If a random roll beats all ten by a wide
 * margin, the grader is measuring something that is not quality, and the pick it produces
 * cannot be trusted.
 */
import { readFileSync } from 'node:fs';
const src = (f) => readFileSync(f, 'utf8');
const PALETTE = new Function(
  src('parts/08-palette.js').replace(/\nif \(typeof module[\s\S]*$/, '') + '\n;return PALETTE;')();
const LOOKS = new Function(src('parts/03-looks.js') + '\n;return LOOKS;')();
const g = JSON.parse(src('grades.json'));

/* Reuse grade.mjs's own axes rather than re-implementing them. Two copies of a rubric is a
   control that can disagree with the thing it is controlling. */
/* Take grade.mjs from its first helper to its last axis. Everything above `const clamp` is
   the module loader, which this file has already done and which would re-declare PALETTE. */
const gsrc = src('grade.mjs');
const mod = gsrc.slice(gsrc.indexOf('const clamp ='), gsrc.indexOf('const N = Number'));
const H = new Function('PALETTE', 'PAIRS', 'build', 'contrast', 'hexToOklch',
  mod + '\n;return { AXES, floor };')(
  PALETTE, PALETTE.PAIRS, PALETTE.build, PALETTE.contrast, PALETTE.hexToOklch);

const rows = [];
for (const look of LOOKS) {
  if (!look.seed) { console.log(`SKIP ${look.id}: no seed`); continue; }
  const f = H.floor(look);
  let total = 0; const parts = {};
  for (const [name, w, fn] of H.AXES) {
    const [v] = fn(look, f); parts[name] = v; total += v * w;
  }
  rows.push({ id: look.id, name: look.name, score: Math.round(total * 10) / 10, parts,
              fails: f.fails.length });
}
rows.sort((a, b) => b.score - a.score);

const roll = g.rows.map((r) => r.score);
const pct = (s) => (100 * roll.filter((x) => x < s).length / roll.length).toFixed(1);
console.log('THE TEN DESIGNED LOOKS, on the same seven axes\n');
console.log('score  pctile-vs-1000  floor  name');
for (const r of rows) {
  console.log(`${String(r.score).padStart(5)}  ${pct(r.score).padStart(9)}%      ` +
    `${r.fails ? 'FAIL' : ' ok '}   ${r.name}`);
}
const med = (a) => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];
console.log(`\ndesigned: median ${med(rows.map((r) => r.score))}, best ${rows[0].score}, worst ${rows[rows.length - 1].score}`);
console.log(`rolled:   median ${med(roll)}, best ${roll[0]}, worst ${roll[roll.length - 1]}`);
console.log(`\nrolls beating the BEST designed look: ${roll.filter((x) => x > rows[0].score).length} of ${roll.length}`);
console.log(`rolls beating the MEDIAN designed look: ${roll.filter((x) => x > med(rows.map((r) => r.score))).length} of ${roll.length}`);

/* On disk as well as on stdout, for the same reason grade.mjs writes grades.json: a control
   that only ever exists in a terminal cannot be read by the page that cites it. */
(await import('node:fs')).writeFileSync('grades-designed.json',
  JSON.stringify({ rows, rolledMedian: med(roll) }, null, 1));
