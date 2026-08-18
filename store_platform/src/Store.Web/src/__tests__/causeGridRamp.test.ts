import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * A CLASS NAME BUILT AT RUNTIME IS A CLASS NAME THAT DOES NOT EXIST.
 *
 * Tailwind v4 generates a rule only for text it finds in the source. `CauseGrid` held its ramp as
 * `fill-kill/85` and turned it into `bg-kill/85` with `String.replace` on the way to the DOM, so
 * the text `bg-kill/85` was in no file the scanner read. Eight of the nine ramp steps had no rule.
 * Measured on the built page 2026-08-18 at 1280: 624 cells drew `rgb(180, 52, 43)`, 80 drew
 * `rgb(20, 112, 106)`, and 740 computed to `rgba(0, 0, 0, 0)` -- the chart on the page whose whole
 * subject is how ideas die was showing one cause and a blank field.
 *
 * Nothing catches this at build time. `tsc` is happy, the build is happy, and the page renders. It
 * has to be caught in the source text, which is what this file does.
 */
describe('the cause grid paints every cause', () => {
  const source = readFileSync(
    path.join(process.cwd(), 'src/components/marketing/CauseGrid.tsx'),
    'utf8',
  );
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

  it('writes the ramp in the form the DOM receives', () => {
    const ramp = /const RAMP = \[([\s\S]*?)\] as const;/.exec(code);
    expect(ramp).not.toBeNull();
    const names = [...ramp![1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
    expect(names.length).toBeGreaterThan(1);
    for (const name of names) expect(name.startsWith('bg-')).toBe(true);
  });

  it('never rewrites a class name on the way to the DOM', () => {
    expect(code).not.toMatch(/\.replace\(\s*['"]fill-/);
    expect(code).not.toMatch(/`(bg|fill)-[a-z]+\/\$\{/);
  });

  it('keeps the palest step readable against the surface', () => {
    const ramp = /const RAMP = \[([\s\S]*?)\] as const;/.exec(code);
    const steps = [...ramp![1].matchAll(/'bg-kill(?:\/(\d+))?'/g)].map((m) =>
      m[1] ? Number(m[1]) : 100,
    );
    expect(steps.length).toBeGreaterThan(1);
    expect(Math.min(...steps)).toBeGreaterThanOrEqual(30);
    // Strictly descending, or the ramp stops encoding the ranking it exists to encode.
    for (let i = 1; i < steps.length; i += 1) expect(steps[i]).toBeLessThan(steps[i - 1]);
  });
});
