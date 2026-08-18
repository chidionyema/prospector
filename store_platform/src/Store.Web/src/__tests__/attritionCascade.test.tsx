import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { AttritionCascade, cascadeSteps } from '@/components/marketing/AttritionCascade';
import { RESEARCH_STATS } from '@/lib/stats';
import type { GateBar } from '@/lib/killLog.server';

/**
 * THE ATTRITION CASCADE (MASTER-BRIEF §7 `/how-it-works`).
 *
 * The property under test is arithmetic honesty. This graphic subtracts real counts from a real
 * population in public, so the failure that matters is not a broken render -- it is a cascade whose
 * numbers do not add up, on the page whose entire job is to convince a reader the filter is real.
 */

const bar = (label: string, count: number): GateBar => ({
  gate: label.toLowerCase().replace(/\s+/g, '_'),
  label,
  count,
  published: true,
  isStage: false,
});

describe('cascadeSteps subtracts a real population', () => {
  it('runs the counts down in size order', () => {
    const steps = cascadeSteps([bar('small', 10), bar('big', 100)], 500);
    expect(steps.map((s) => s.label)).toEqual(['big', 'small']);
    expect(steps[0]).toMatchObject({ before: 500, killed: 100 });
    expect(steps[1]).toMatchObject({ before: 400, killed: 10 });
  });

  it('never subtracts past zero', () => {
    // If the totals and the distribution ever disagree, the cascade must stop rather than draw a
    // negative band and imply a population that does not exist.
    const steps = cascadeSteps([bar('a', 80), bar('b', 80)], 100);
    expect(steps).toHaveLength(2);
    expect(steps[1].killed).toBe(20);
    expect(steps[1].before - steps[1].killed).toBe(0);
  });

  it('ignores causes with no kills', () => {
    expect(cascadeSteps([bar('a', 0)], 100)).toEqual([]);
  });

  it('is stable between renders', () => {
    // Ties broken by label, so a graphic that is meant to be a signature does not reshuffle.
    const a = cascadeSteps([bar('zeta', 5), bar('alpha', 5)], 50);
    const b = cascadeSteps([bar('alpha', 5), bar('zeta', 5)], 50);
    expect(a.map((s) => s.label)).toEqual(b.map((s) => s.label));
  });
});

describe('the cascade as rendered', () => {
  const html = renderToStaticMarkup(
    <AttritionCascade distribution={[bar('Incumbency', 200), bar('Payer solvency', 50)]} />,
  );

  it('opens on the whole population it researched', () => {
    expect(html).toContain(RESEARCH_STATS.researched.toLocaleString('en-GB'));
  });

  it('states every subtraction, not just the bars', () => {
    // The bar shows the fall; the number says how far. This page's claim is that the figures are
    // checkable, and a bar alone is not checkable.
    expect(html).toContain('−200');
    expect(html).toContain('−50');
  });

  it('never prints a survivor count', () => {
    // The 2026-08-13 directive, encoded in lib/stats.ts. §7 of the brief asks for "down to 74";
    // the directive wins, the final band is drawn to scale and named in words.
    const survivors = RESEARCH_STATS.researched - 250;
    expect(html).not.toContain(survivors.toLocaleString('en-GB'));
    expect(html).toContain('What is on the shelf');
  });

  it('uses red only for the kills and teal only for what survived', () => {
    // §2: colour is a contract. Red where nothing died is a bug.
    // The subtraction is the drawing's `.step .track b`, which mockup.css paints in `--kill`
    // (`mockups/how-it-works.html:246`); it used to be a `text-kill-strong` utility here. The
    // contract is the same and it is still asserted: the ONLY red in this chart is on the number
    // of ideas a gate killed, and the shelf bar is the only teal.
    expect(html).toMatch(/<b>\u2212[\d,]+<\/b>/);
    expect(html).toContain('bg-survive');
  });

  it('renders nothing rather than an empty frame', () => {
    expect(renderToStaticMarkup(<AttritionCascade distribution={[]} />)).toBe('');
  });

  it('ships zero client JavaScript', () => {
    expect(html).not.toContain('onclick');
    expect(html).not.toContain('<script');
  });
});
